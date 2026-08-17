"""Confirm Lambda: the double opt-in click target.

Exposed via a Lambda Function URL (infra/template.yaml) rather than API Gateway -- it's a single
public GET endpoint with no other routes, and a Function URL is free with no per-request charge,
where API Gateway (reserved for the real Phase 4 read API) isn't. AuthType is NONE since this
has to be clickable straight from an email link with no credentials; the random per-subscriber
token in the URL is what makes a specific confirmation unguessable, not the endpoint itself.

Run locally from services/src/: python -m confirm.handler
"""
import html
import json
import logging
import os
import sys

from common import config
from common.store import Store

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def _html_response(status_code: int, message: str) -> dict:
    body = (
        "<!doctype html><html><body style='font-family: sans-serif; max-width: 480px; "
        f"margin: 4rem auto;'><p>{html.escape(message)}</p></body></html>"
    )
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": body,
    }


def handler(event, context):
    params = (event or {}).get("queryStringParameters") or {}
    location_id = params.get("location_id")
    email = params.get("email")
    token = params.get("token")

    if not (location_id and email and token):
        return _html_response(400, "Missing location_id, email, or token.")

    store = Store(config.DDB_TABLE_NAME)
    if store.confirm_subscriber(location_id, email, token):
        logger.info("Confirmed subscriber %s for %s", email, location_id)
        return _html_response(
            200, "Subscription confirmed — you'll now receive pollen alerts for this location."
        )

    logger.info("Confirm failed for %s / %s (bad or already-used token)", email, location_id)
    return _html_response(400, "This confirmation link is invalid or has already been used.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"queryStringParameters": {}}
    print(json.dumps(handler(event, None), indent=2, default=str))
