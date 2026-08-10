"""DynamoDB access layer.

All key construction lives here so the single-table key scheme is defined in exactly one place.
See docs/DATA_MODEL.md for the schema and the access patterns these methods implement.
"""
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr, Key

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
        """Query, following pagination until every page is consumed."""
        items = []
        while True:
            resp = self.table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                return items
            kwargs["ExclusiveStartKey"] = last_key

    def get_enabled_locations(self) -> list:
        """Access pattern 1: every location the ingestion job should fetch."""
        items = self._query_all(
            KeyConditionExpression=Key("pk").eq(CONFIG_LOCATIONS_PK),
        )
        return [item for item in items if item.get("enabled", True)]

    def put_reading(self, location_id: str, reading: dict) -> None:
        """Write one reading. Keyed on the forecast date, so re-runs overwrite rather than
        duplicate -- this is what makes the ingestion job idempotent."""
        expires_at = int(time.time()) + self.ttl_days * 86400
        item = {
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
        self.table.put_item(Item=item)

    def get_subscribers(self, location_id: str) -> list:
        """Access pattern 4: confirmed subscribers for one location."""
        items = self._query_all(
            KeyConditionExpression=Key("pk").eq(location_pk(location_id))
            & Key("sk").begins_with("SUB#"),
        )
        return [item for item in items if item.get("status") == "CONFIRMED"]

    def claim_notification(self, location_id: str, email: str, today: str) -> bool:
        """Atomically claim the right to send today's alert to this subscriber.

        Returns True if the claim succeeded (caller should send the email), False if another
        run already claimed it. The claim happens before sending and is arbitrated by DynamoDB,
        which is what prevents two concurrent runs from both sending -- a read-then-write check
        would race.
        """
        try:
            self.table.update_item(
                Key={"pk": location_pk(location_id), "sk": subscriber_sk(email)},
                UpdateExpression="SET last_notified_date = :today",
                ConditionExpression=Attr("last_notified_date").not_exists()
                | Attr("last_notified_date").lt(today),
                ExpressionAttributeValues={":today": today},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
