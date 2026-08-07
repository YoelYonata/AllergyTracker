"""Ingestion Lambda handler

This Lambda is written in Python and is intended to run on AWS Lambda.
It fetches pollen data for a location (default: "vancouver") from a configured
POLLEN_API_URL (or uses a mocked payload if none is provided), then writes
a record to DynamoDB table configured in DDB_TABLE_NAME.

The module also supports running locally as a small test harness:
    python -m src.handler

Environment variables:
- POLLEN_API_URL (optional)
- POLLEN_API_KEY (optional)
- DDB_TABLE_NAME (optional)

"""
import os
import json
import time
from datetime import datetime, timezone
from decimal import Decimal

from dotenv import load_dotenv
import requests
import boto3

# Load local .env values if present
load_dotenv()

# Config
POLLEN_API_URL = os.getenv("POLLEN_API_URL")
POLLEN_API_KEY = os.getenv("POLLEN_API_KEY")
DDB_TABLE_NAME = os.getenv("DDB_TABLE_NAME", "pollen_readings")
DEFAULT_LOCATION = "vancouver"

# Helpers for DynamoDB numeric conversion
def to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def fetch_pollen_for_location(location_id: str):
    """Fetch pollen data from external provider or return a mocked payload.

    Returns a dict with keys: pollen_level (number), pollen_type (str), raw (dict)
    """
    if POLLEN_API_URL:
        params = {"location": location_id}
        headers = {}
        if POLLEN_API_KEY:
            if "googleapis.com" in POLLEN_API_URL:
                params["key"] = POLLEN_API_KEY
            else:
                headers["Authorization"] = f"Bearer {POLLEN_API_KEY}"
        resp = requests.get(POLLEN_API_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            raise ValueError(
                f"Expected JSON response from POLLEN_API_URL but got Content-Type={content_type}. "
                "Please confirm POLLEN_API_URL points at the real API endpoint, not the docs page."
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ValueError(
                f"Failed to parse JSON from POLLEN_API_URL response. Response preview: {resp.text[:500]!r}"
            ) from exc
        # TODO: adapt parsing to your provider's payload structure
        # The following attempts to extract sensible defaults
        pollen_level = payload.get("pollen_level") or payload.get("level") or 0
        pollen_type = payload.get("pollen_type") or payload.get("type") or "unknown"
        return {"pollen_level": pollen_level, "pollen_type": pollen_type, "raw": payload}

    # Mocked payload for local development
    now = datetime.now(timezone.utc)
    mocked = {
        "timestamp": now.isoformat(),
        "location": location_id,
        "pollen_level": 42,  # mock number
        "pollen_type": "grass",
        "notes": "mocked payload",
    }
    return {"pollen_level": mocked["pollen_level"], "pollen_type": mocked["pollen_type"], "raw": mocked}


class DynamoWriter:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.ddb = boto3.resource("dynamodb")
        self.table = self.ddb.Table(table_name)

    def write_reading(self, location_id: str, pollen_level, pollen_type, raw_payload: dict):
        timestamp = datetime.now(timezone.utc).isoformat()
        item = {
            "location_id": location_id,
            "timestamp": timestamp,
            "pollen_level": to_decimal(pollen_level),
            "pollen_type": pollen_type,
            "raw_payload": raw_payload,
        }
        # Remove None values (DynamoDB doesn't accept Decimal(None))
        clean_item = {k: v for k, v in item.items() if v is not None}
        # Put item
        resp = self.table.put_item(Item=clean_item)
        return resp


# Lambda handler
def handler(event, context):
    """Lambda handler entrypoint

    Sample event (optional): {"location_id": "vancouver"}
    """
    location = (event or {}).get("location_id") or DEFAULT_LOCATION
    result = fetch_pollen_for_location(location)

    writer = DynamoWriter(DDB_TABLE_NAME)
    resp = writer.write_reading(location, result["pollen_level"], result["pollen_type"], result["raw"])  # noqa: E501

    return {"status": "ok", "ddb_response": resp}


# Local run support
if __name__ == "__main__":
    print("Running ingestion handler locally (mock mode if POLLEN_API_URL is not set)...")
    test_event = {"location_id": DEFAULT_LOCATION}
    out = handler(test_event, None)
    print(json.dumps(out, default=str, indent=2))
