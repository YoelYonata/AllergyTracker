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
import sys

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit

from common import config, pollen_api
from common.store import Store

logger = Logger(service="ingest")
tracer = Tracer(service="ingest")
metrics = Metrics(namespace="AllergyTracker", service="ingest")


@tracer.capture_method
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
        "Stored readings for location",
        location_id=location_id,
        readings_written=len(readings),
        max_upi_today=readings[0].get("max_upi") if readings else None,
    )
    return {"location_id": location_id, "readings_written": len(readings)}


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
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
            logger.exception("Failed to process location", location_id=location.get("location_id"))
            failures.append(location.get("location_id"))

    readings_written = sum(r["readings_written"] for r in results)
    metrics.add_metric(name="LocationsFailed", unit=MetricUnit.Count, value=len(failures))
    metrics.add_metric(name="ReadingsWritten", unit=MetricUnit.Count, value=readings_written)

    logger.info(
        "Ingestion run complete",
        locations_processed=len(results),
        locations_failed=failures,
        readings_written=readings_written,
    )
    return {
        "locations_processed": len(results),
        "locations_failed": failures,
        "readings_written": readings_written,
    }


if __name__ == "__main__":
    from common.local_context import LocalLambdaContext

    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(handler(event, LocalLambdaContext()), indent=2, default=str))
