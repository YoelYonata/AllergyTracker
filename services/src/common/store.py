"""DynamoDB access layer.

All key construction lives here so the single-table key scheme has exactly one source of truth.
See docs/DATA_MODEL.md for the schema and the access patterns these methods implement.
"""
import secrets
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

CONFIG_LOCATIONS_PK = "CONFIG#LOCATIONS"


def location_pk(location_id: str) -> str:
    return f"LOC#{location_id}"


def reading_sk(date_str: str) -> str:
    return f"READING#{date_str}"


def subscriber_sk(email: str) -> str:
    return f"SUB#{email}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, table_name: str, ttl_days: int = 365):
        self.table = boto3.resource("dynamodb").Table(table_name)
        self.ttl_days = ttl_days

    def _query_all(self, **kwargs) -> list:
        """Run a Query, following pagination until every page is consumed."""
        items = []
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            kwargs["ExclusiveStartKey"] = last_key

    def get_enabled_locations(self) -> list:
        """Access pattern 1: every location the ingestion job should fetch."""
        items = self._query_all(KeyConditionExpression=Key("pk").eq(CONFIG_LOCATIONS_PK))
        return [item for item in items if item.get("enabled", True)]

    def get_location(self, location_id: str) -> dict:
        """Single location's config item, e.g. for its display_name in an alert email."""
        response = self.table.get_item(
            Key={"pk": CONFIG_LOCATIONS_PK, "sk": location_pk(location_id)}
        )
        return response.get("Item")

    def put_reading(self, location_id: str, reading: dict) -> None:
        """Write one reading, keyed on the forecast date -- re-runs overwrite rather than
        duplicate, which is what makes the ingestion job idempotent."""
        expires_at = int(time.time()) + self.ttl_days * 86400
        self.table.put_item(
            Item={
                "pk": location_pk(location_id),
                "sk": reading_sk(reading["date"]),
                "entity": "READING",
                "location_id": location_id,
                "date": reading["date"],
                "types": reading["types"],
                "max_upi": reading.get("max_upi"),
                "region_code": reading.get("region_code"),
                "fetched_at": _utc_now_iso(),
                "ttl": expires_at,
            }
        )

    def get_subscribers(self, location_id: str) -> list:
        """Access pattern 4: confirmed subscribers for one location."""
        items = self._query_all(
            KeyConditionExpression=Key("pk").eq(location_pk(location_id))
            & Key("sk").begins_with("SUB#")
        )
        return [item for item in items if item.get("status") == "CONFIRMED"]

    def create_pending_subscriber(
        self, location_id: str, email: str, threshold: int, pollen_types=None
    ) -> dict:
        """Create a new subscriber in PENDING status with a random confirm token.

        get_subscribers() only ever returns CONFIRMED subscribers, so this subscriber won't
        receive alerts until confirm_subscriber() is called with the matching token -- the
        double opt-in this project's design calls for.
        """
        confirm_token = secrets.token_urlsafe(24)
        item = {
            "pk": location_pk(location_id),
            "sk": subscriber_sk(email),
            "gsi1pk": f"EMAIL#{email}",
            "gsi1sk": location_pk(location_id),
            "entity": "SUBSCRIBER",
            "email": email,
            "location_id": location_id,
            "threshold": threshold,
            "status": "PENDING",
            "confirm_token": confirm_token,
            "unsubscribe_token": secrets.token_urlsafe(24),
            "created_at": _utc_now_iso(),
        }
        if pollen_types:
            item["pollen_types"] = set(pollen_types)
        self.table.put_item(Item=item)
        return item

    def confirm_subscriber(self, location_id: str, email: str, token: str) -> bool:
        """Move a subscriber from PENDING to CONFIRMED if the token matches.

        Returns True on success, False if the token is wrong/stale or the subscriber is
        already confirmed (idempotent: clicking an old confirm link twice just no-ops).
        """
        try:
            self.table.update_item(
                Key={"pk": location_pk(location_id), "sk": subscriber_sk(email)},
                UpdateExpression="SET #status = :confirmed",
                ConditionExpression=(
                    Attr("confirm_token").eq(token) & Attr("status").eq("PENDING")
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":confirmed": "CONFIRMED"},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def claim_notification(self, location_id: str, email: str, today: str) -> bool:
        """Atomically claim the right to send today's alert to this subscriber.

        Returns True if the claim succeeded (caller should send the email), False if another
        run already claimed it today. The claim happens before sending, arbitrated by DynamoDB's
        conditional update -- a read-then-write check from application code would race under
        concurrent runs.
        """
        try:
            self.table.update_item(
                Key={"pk": location_pk(location_id), "sk": subscriber_sk(email)},
                UpdateExpression="SET last_notified_date = :today",
                ConditionExpression=(
                    Attr("last_notified_date").not_exists() | Attr("last_notified_date").lt(today)
                ),
                ExpressionAttributeValues={":today": today},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
