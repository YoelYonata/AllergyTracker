"""Ingestion Lambda.

Triggered on a schedule by EventBridge. For every enabled location it fetches the pollen
forecast from the Google Pollen API and writes one DynamoDB item per forecast day (idempotent
-- re-runs overwrite rather than duplicate).

That's all this function does. Threshold checking and alerting used to live here too, but
that's now the notify Lambda's job (services/src/notify/handler.py), triggered off this
function's DynamoDB writes via a Stream -- see docs/IMPLEMENTATION_PLAN.md Phase 3. Splitting
it this way means ingest failing to send an email (or SES being down) can never cause a
forecast fetch to be skipped, and vice versa.

Optional event override, useful for manual invokes:
    {"location_id": "vancouver"}   -- process just this one location

Run locally from services/src/: python -m ingest.handler
"""
import json
import logging
import os
import sys

from common import config, pollen_api
from common.store import Store

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def process_location(store: Store, location: dict, api_key: str) -> dict:
    """Fetch and store one location's forecast."""
    location_id = location["location_id"]

    payload = pollen_api.fetch_forecast(
        latitude=float(location["latitude"]),
        longitude=float(location["longitude"]),
        days=config.FORECAST_DAYS,
        api_key=api_key,
    )
    readings = pollen_api.parse_forecast(payload)

    for reading in readings:
        store.put_reading(location_id, reading)

    logger.info(
        "Stored %d readings for %s (max UPI today: %s)",
        len(readings),
        location_id,
        readings[0].get("max_upi") if readings else None,
    )
    return {"location_id": location_id, "readings_written": len(readings)}


def handler(event, context):
    event = event or {}

    store = Store(config.DDB_TABLE_NAME, ttl_days=config.READING_TTL_DAYS)
    api_key = config.get_pollen_api_key()

    locations = store.get_enabled_locations()
    if event.get("location_id"):
        locations = [loc for loc in locations if loc["location_id"] == event["location_id"]]
        if not locations:
            raise ValueError(f"No enabled location config found for {event['location_id']!r}")

    results, failures = [], []
    for location in locations:
        # One bad location shouldn't stop the others -- a partial run beats no run.
        try:
            results.append(process_location(store, location, api_key))
        except Exception:
            logger.exception("Failed to process location %s", location.get("location_id"))
            failures.append(location.get("location_id"))

    return {
        "locations_processed": len(results),
        "locations_failed": failures,
        "readings_written": sum(r["readings_written"] for r in results),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(handler(event, None), indent=2, default=str))
