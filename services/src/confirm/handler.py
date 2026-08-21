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
import sys

from aws_lambda_powertools import Logger, Metrics, Tracer

from common import config
from common.store import Store

logger = Logger(service="confirm")
tracer = Tracer(service="confirm")
metrics = Metrics(namespace="AllergyTracker", service="confirm")


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


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event, context):
    params = (event or {}).get("queryStringParameters") or {}
    location_id = params.get("location_id")
    email = params.get("email")
    token = params.get("token")

    if not (location_id and email and token):
        return _html_response(400, "Missing location_id, email, or token.")

    store = Store(config.DDB_TABLE_NAME)
    if store.confirm_subscriber(location_id, email, token):
        logger.info("Confirmed subscriber", email=email, location_id=location_id)
        return _html_response(
            200, "Subscription confirmed — you'll now receive pollen alerts for this location."
        )

    logger.info(
        "Confirm failed (bad or already-used token)", email=email, location_id=location_id
    )
    return _html_response(400, "This confirmation link is invalid or has already been used.")


if __name__ == "__main__":
    from common.local_context import LocalLambdaContext

    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"queryStringParameters": {}}
    print(json.dumps(handler(event, LocalLambdaContext()), indent=2, default=str))
