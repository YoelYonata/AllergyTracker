"""Notifier Lambda: triggered by the DynamoDB Stream on new pollen readings.

Decoupled from the ingestion Lambda -- ingest only fetches and stores; this function reacts to
what changed in the table, checks subscriber thresholds, and sends alert emails via SES.

The event source mapping (infra/template.yaml) applies a FilterCriteria so this function is
only invoked for entity=READING inserts/updates -- subscriber claim writes and location config
changes hit the same stream but never reach this handler. `_parse_stream_record` re-checks that
condition anyway (belt and suspenders, and it's what makes the filtering logic unit-testable
without a real DynamoDB Stream event).

Run locally from services/src/: python -m notify.handler
"""
import json
import logging
import os
import sys

from boto3.dynamodb.types import TypeDeserializer

from common import config, pollen_api, ses
from common.store import Store

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_deserializer = TypeDeserializer()


def _deserialize_image(image: dict) -> dict:
    """Convert a DynamoDB Streams low-level image ({"S": "..."}, {"N": "..."}, ...) into a
    plain Python dict, the same shape put_reading() originally wrote."""
    return {key: _deserializer.deserialize(value) for key, value in image.items()}


def _parse_stream_record(record: dict) -> dict:
    """Return the reading dict for a relevant record, or None to skip it."""
    if record.get("eventName") not in ("INSERT", "MODIFY"):
        return None
    new_image = record.get("dynamodb", {}).get("NewImage")
    if not new_image:
        return None
    reading = _deserialize_image(new_image)
    if reading.get("entity") != "READING":
        return None
    return reading


def _notify_subscribers(store: Store, reading: dict) -> int:
    """Check every confirmed subscriber for this location against today's reading, claim and
    send an alert for each breach. Returns the number of alerts actually sent."""
    location_id = reading["location_id"]
    date = reading["date"]

    subscribers = store.get_subscribers(location_id)
    if not subscribers:
        return 0

    location = store.get_location(location_id) or {}
    display_name = location.get("display_name", location_id)
    sent = 0

    for subscriber in subscribers:
        threshold = subscriber.get("threshold", config.DEFAULT_THRESHOLD)
        breaches = pollen_api.find_breaches(
            reading, threshold=threshold, pollen_types=subscriber.get("pollen_types")
        )
        if not breaches:
            continue

        email = subscriber["email"]
        if not store.claim_notification(location_id, email, date):
            logger.info("Already notified %s for %s on %s; skipping", email, location_id, date)
            continue

        try:
            ses.send_alert_email(
                sender=config.SES_SENDER_EMAIL,
                to=email,
                location_name=display_name,
                date=date,
                breaches=breaches,
            )
            sent += 1
        except Exception:
            # The claim already succeeded, so a send failure here means this subscriber won't
            # be retried until the next reading comes in -- acceptable for v1, worth revisiting
            # if SES delivery issues turn out to be common.
            logger.exception("Failed to send alert email to %s for %s", email, location_id)

    return sent


def handler(event, context):
    store = Store(config.DDB_TABLE_NAME, ttl_days=config.READING_TTL_DAYS)

    records_processed = 0
    alerts_sent = 0
    for record in event.get("Records", []):
        reading = _parse_stream_record(record)
        if reading is None:
            continue
        records_processed += 1
        alerts_sent += _notify_subscribers(store, reading)

    logger.info("Processed %d reading(s), sent %d alert(s)", records_processed, alerts_sent)
    return {"records_processed": records_processed, "alerts_sent": alerts_sent}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"Records": []}
    print(json.dumps(handler(event, None), indent=2, default=str))
