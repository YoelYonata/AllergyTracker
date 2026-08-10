"""Ingestion & anomaly-check Lambda.

Triggered on a schedule by EventBridge. For every enabled location it:

  1. fetches the pollen forecast from the Google Pollen API,
  2. writes one DynamoDB item per forecast day (idempotent -- re-runs overwrite),
  3. checks today's reading against each subscriber's threshold and claims the right to
     notify them, returning the alerts that should be sent.

Actually sending the email is Phase 3 (SES); this function currently returns the alerts it
would send so the pipeline can be verified end to end first.

Optional event overrides, useful for manual invokes:
    {"location_id": "vancouver"}   -- process just this one location
    {"skip_alerts": true}          -- ingest only, no threshold check

Run locally with:  python -m ingest.handler
"""
import json
import logging
import os
import sys

try:
    from . import config, pollen_api
    from .store import Store
except ImportError:  # allow `python handler.py` from this directory
    import config
    import pollen_api
    from store import Store

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

DEFAULT_THRESHOLD = 3


def process_location(store: Store, location: dict, api_key: str, skip_alerts: bool) -> dict:
    """Fetch, store, and threshold-check a single location."""
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

    result = {"location_id": location_id, "readings_written": len(readings), "alerts": []}
    if skip_alerts or not readings:
        return result

    # dailyInfo[0] is today; alerts are about current conditions, not the forecast tail.
    today_reading = readings[0]
    today = today_reading["date"]

    for subscriber in store.get_subscribers(location_id):
        threshold = subscriber.get("threshold", DEFAULT_THRESHOLD)
        breaches = pollen_api.find_breaches(
            today_reading,
            threshold=threshold,
            pollen_types=subscriber.get("pollen_types"),
        )
        if not breaches:
            continue

        email = subscriber["email"]
        if not store.claim_notification(location_id, email, today):
            logger.info("Already notified %s for %s on %s; skipping", email, location_id, today)
            continue

        result["alerts"].append(
            {
                "email": email,
                "location_id": location_id,
                "display_name": location.get("display_name", location_id),
                "date": today,
                "breaches": breaches,
            }
        )

    return result


def handler(event, context):
    event = event or {}
    skip_alerts = bool(event.get("skip_alerts"))
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
            results.append(process_location(store, location, api_key, skip_alerts))
        except Exception:
            logger.exception("Failed to process location %s", location.get("location_id"))
            failures.append(location.get("location_id"))

    return {
        "locations_processed": len(results),
        "locations_failed": failures,
        "readings_written": sum(r["readings_written"] for r in results),
        "alerts": [alert for r in results for alert in r["alerts"]],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(handler(event, None), indent=2, default=str))
