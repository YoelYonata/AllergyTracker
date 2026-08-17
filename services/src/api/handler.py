"""Read API Lambda: the only backend the dashboard talks to.

Fronted by an API Gateway **HTTP API** (infra/template.yaml), not a REST API -- ~3.5x cheaper
per request and simpler to define. The browser never reads DynamoDB directly; it goes through
here so table credentials stay server-side and the routes can be throttled.

One Lambda serves all four routes rather than one Lambda per route: they share the same Store,
the same cold start, and the same deployment package, and at this scale splitting them would
just multiply cold starts for no isolation benefit.

    GET  /locations                        -- what the dashboard's location picker offers
    GET  /pollen/{location}/latest         -- today's reading (access pattern 2)
    GET  /pollen/{location}/history?days=N -- trend chart data (access pattern 3)
    POST /subscribe                        -- double opt-in signup, emails the confirm link

CORS headers are set by the HTTP API's CorsConfiguration, not here -- API Gateway also answers
the preflight OPTIONS request itself, so no OPTIONS route reaches this function.

Run locally from services/src/:
    python -m api.handler '{"routeKey": "GET /locations"}'
"""
import base64
import json
import logging
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from common import config, ses
from common.store import Store

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

DEFAULT_HISTORY_DAYS = 14
# Bounded so a hand-edited ?days=100000 can't turn one request into a huge paginated Query.
MAX_HISTORY_DAYS = 30

VALID_POLLEN_TYPES = {"GRASS", "TREE", "WEED"}
# UPI is a 0-5 scale; a threshold outside it is either always-on or never-on, so reject it.
MIN_THRESHOLD, MAX_THRESHOLD = 0, 5

# Deliberately loose. Real validation of an email address is delivery, and that's exactly what
# the double opt-in confirmation link already does -- this only rejects obvious junk.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254  # RFC 5321 practical limit.

# Same wording whether the address is new, still pending, or already confirmed, so the endpoint
# can't be used to test which addresses are subscribed.
SUBSCRIBE_ACCEPTED_MESSAGE = (
    "If that address isn't already subscribed, a confirmation email is on its way. "
    "Alerts start once you click the link in it."
)

# Internal/storage-only attributes, stripped before anything goes over the wire.
_INTERNAL_ATTRIBUTES = {"pk", "sk", "gsi1pk", "gsi1sk", "entity", "ttl"}


class _DecimalEncoder(json.JSONEncoder):
    """DynamoDB hands back Decimal for every number and set() for string sets; json.dumps
    chokes on both."""

    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        if isinstance(o, set):
            return sorted(o)
        return super().default(o)


def _json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def _error(status_code: int, message: str) -> dict:
    return _json_response(status_code, {"error": message})


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _public_reading(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in _INTERNAL_ATTRIBUTES}


def _public_location(item: dict) -> dict:
    return {
        "location_id": item["location_id"],
        "display_name": item.get("display_name", item["location_id"]),
    }


def _history_range(days: int, today: str) -> tuple:
    """The inclusive [from, to] window for a `days`-long trend ending today.

    Ends at today rather than running out to the furthest forecast day: the chart is a trend
    line, and mixing already-past dates with days-ahead predictions on one axis reads as
    history when half of it isn't.
    """
    end = datetime.strptime(today, "%Y-%m-%d").date()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _parse_days(params: dict):
    """Returns (days, error_message)."""
    raw = params.get("days")
    if raw is None or raw == "":
        return DEFAULT_HISTORY_DAYS, None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None, "days must be an integer."
    if not 1 <= days <= MAX_HISTORY_DAYS:
        return None, f"days must be between 1 and {MAX_HISTORY_DAYS}."
    return days, None


def _parse_body(event: dict):
    """Decode an HTTP API request body into a dict. Returns (payload, error_message)."""
    body = event.get("body")
    if not body:
        return None, "Request body is required."
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None, "Request body could not be decoded."
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, "Request body must be valid JSON."
    if not isinstance(payload, dict):
        return None, "Request body must be a JSON object."
    return payload, None


def _validate_subscribe(payload: dict):
    """Validate and normalize a POST /subscribe body. Returns (data, error_message).

    Pure -- no DynamoDB. Whether the *location* actually exists is checked separately by the
    route, since that needs a read.
    """
    email = (payload.get("email") or "").strip().lower()
    if not email or len(email) > MAX_EMAIL_LENGTH or not EMAIL_RE.match(email):
        return None, "A valid email address is required."

    location_id = (payload.get("location") or payload.get("location_id") or "").strip().lower()
    if not location_id:
        return None, "A location is required."

    threshold = payload.get("threshold", config.DEFAULT_THRESHOLD)
    # bool is an int subclass in Python, so True would otherwise sail through as threshold=1.
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        return None, "threshold must be an integer."
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        return None, f"threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}."

    pollen_types = payload.get("pollen_types")
    if pollen_types is not None:
        if not isinstance(pollen_types, list):
            return None, "pollen_types must be a list."
        pollen_types = [str(t).strip().upper() for t in pollen_types]
        unknown = sorted(set(pollen_types) - VALID_POLLEN_TYPES)
        if unknown:
            return None, f"Unknown pollen types: {', '.join(unknown)}."
        # Empty list means "all types" -- same as omitting it.
        pollen_types = sorted(set(pollen_types)) or None

    return {
        "email": email,
        "location_id": location_id,
        "threshold": threshold,
        "pollen_types": pollen_types,
    }, None


def _confirm_url(location_id: str, email: str, token: str) -> str:
    base = config.CONFIRM_BASE_URL.rstrip("/")
    query = urllib.parse.urlencode(
        {"location_id": location_id, "email": email, "token": token}
    )
    return f"{base}/?{query}"


# --- Routes -----------------------------------------------------------------------------


def _get_locations(store: Store, event: dict) -> dict:
    locations = store.get_enabled_locations()
    return _json_response(200, {"locations": [_public_location(loc) for loc in locations]})


def _get_latest(store: Store, event: dict) -> dict:
    location_id = ((event.get("pathParameters") or {}).get("location") or "").lower()
    location = store.get_location(location_id)
    if not location:
        return _error(404, f"Unknown location {location_id!r}.")

    reading = store.get_latest_reading(location_id, _today())
    return _json_response(
        200,
        {
            "location": _public_location(location),
            "reading": _public_reading(reading) if reading else None,
        },
    )


def _get_history(store: Store, event: dict) -> dict:
    location_id = ((event.get("pathParameters") or {}).get("location") or "").lower()
    days, error = _parse_days(event.get("queryStringParameters") or {})
    if error:
        return _error(400, error)

    location = store.get_location(location_id)
    if not location:
        return _error(404, f"Unknown location {location_id!r}.")

    start, end = _history_range(days, _today())
    readings = store.get_readings(location_id, start, end)
    return _json_response(
        200,
        {
            "location": _public_location(location),
            "days": days,
            "from": start,
            "to": end,
            "readings": [_public_reading(r) for r in readings],
        },
    )


def _post_subscribe(store: Store, event: dict) -> dict:
    payload, error = _parse_body(event)
    if error:
        return _error(400, error)

    data, error = _validate_subscribe(payload)
    if error:
        return _error(400, error)

    if not config.CONFIRM_BASE_URL or not config.SES_SENDER_EMAIL:
        logger.error("CONFIRM_BASE_URL / SES_SENDER_EMAIL not configured; cannot subscribe")
        return _error(500, "Subscriptions are not configured on this deployment.")

    location = store.get_location(data["location_id"])
    if not location or not location.get("enabled", True):
        return _error(404, f"Unknown location {data['location_id']!r}.")

    subscriber = store.create_pending_subscriber(
        location_id=data["location_id"],
        email=data["email"],
        threshold=data["threshold"],
        pollen_types=data["pollen_types"],
    )
    if subscriber is None:
        # Already CONFIRMED. Nothing to do, and the response must look identical to a real
        # signup so this endpoint can't be used to probe which addresses are subscribed.
        logger.info("Subscribe no-op: %s already confirmed for %s", data["email"], data["location_id"])
        return _json_response(202, {"message": SUBSCRIBE_ACCEPTED_MESSAGE})

    try:
        ses.send_confirmation_email(
            sender=config.SES_SENDER_EMAIL,
            to=data["email"],
            confirm_url=_confirm_url(
                data["location_id"], data["email"], subscriber["confirm_token"]
            ),
            location_name=location.get("display_name", data["location_id"]),
        )
    except Exception:
        # The PENDING item exists but the link never arrived. Say so rather than returning a
        # success the caller would be waiting on forever -- re-posting is safe and re-issues
        # the token, since the item is still PENDING.
        logger.exception("Failed to send confirmation email to %s", data["email"])
        return _error(502, "Couldn't send the confirmation email. Please try again shortly.")

    logger.info("Sent confirmation email to %s for %s", data["email"], data["location_id"])
    return _json_response(202, {"message": SUBSCRIBE_ACCEPTED_MESSAGE})


# API Gateway's HTTP API payload v2.0 hands us the matched route template as `routeKey`
# ("GET /pollen/{location}/latest"), so routing is a dict lookup rather than path parsing.
ROUTES = {
    "GET /locations": _get_locations,
    "GET /pollen/{location}/latest": _get_latest,
    "GET /pollen/{location}/history": _get_history,
    "POST /subscribe": _post_subscribe,
}


def handler(event, context):
    event = event or {}
    route_key = event.get("routeKey")
    route = ROUTES.get(route_key)
    if route is None:
        # Only reachable if the template declares a route this module doesn't implement --
        # anything else is rejected by API Gateway before it gets here.
        logger.warning("No handler for routeKey %r", route_key)
        return _error(404, "Not found.")

    store = Store(config.DDB_TABLE_NAME, ttl_days=config.READING_TTL_DAYS)
    try:
        return route(store, event)
    except Exception:
        # Never let a stack trace reach the browser; it's in CloudWatch instead.
        logger.exception("Unhandled error serving %s", route_key)
        return _error(500, "Internal server error.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"routeKey": "GET /locations"}
    print(json.dumps(handler(event, None), indent=2, default=str))
