"""Google Pollen API client and response parsing.

Endpoint: GET https://pollen.googleapis.com/v1/forecast:lookup
Docs: https://developers.google.com/maps/documentation/pollen/reference/rest/v1/forecast/lookup

Parsing lives as pure functions (no network, no AWS) so it's unit-testable against recorded
payloads -- see services/tests/test_pollen_api.py.
"""
from decimal import Decimal

import requests

API_URL = "https://pollen.googleapis.com/v1/forecast:lookup"
REQUEST_TIMEOUT_SECONDS = 10


def fetch_forecast(latitude: float, longitude: float, days: int, api_key: str) -> dict:
    """Call the Pollen API and return the decoded JSON body."""
    params = {
        "key": api_key,
        "location.latitude": latitude,
        "location.longitude": longitude,
        "days": days,
        # Per-plant descriptions are long prose we never display; omitting them keeps the
        # response (and DynamoDB item size) small.
        "plantsDescription": 0,
    }
    response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    # parse_float=Decimal keeps numeric values DynamoDB-safe; boto3 rejects native floats.
    return response.json(parse_float=Decimal)


def _format_date(date_obj: dict) -> str:
    """Turn the API's {"year": 2026, "month": 8, "day": 10} into "2026-08-10".

    Zero-padding matters: the DynamoDB sort key relies on ISO dates sorting lexicographically
    in the same order they sort chronologically.
    """
    return f"{int(date_obj['year']):04d}-{int(date_obj['month']):02d}-{int(date_obj['day']):02d}"


def parse_daily_info(daily: dict) -> dict:
    """Parse one entry of the API's dailyInfo array into a flat reading dict.

    Only pollenTypeInfo (GRASS/TREE/WEED) is kept -- plantInfo (individual species like MAPLE,
    ELM) isn't something the dashboard shows, so it's dropped here rather than stored.
    """
    types = {}
    for type_info in daily.get("pollenTypeInfo", []):
        code = type_info.get("code")
        if not code:
            continue
        # indexInfo is omitted entirely by the API when it has no coverage for this
        # type/location -- that must come through as an explicit null, not a 0.
        index_info = type_info.get("indexInfo") or {}
        types[code] = {
            "display_name": type_info.get("displayName"),
            "in_season": type_info.get("inSeason"),
            "upi": index_info.get("value"),
            "category": index_info.get("category"),
        }

    known_upis = [t["upi"] for t in types.values() if t["upi"] is not None]

    return {
        "date": _format_date(daily["date"]),
        "types": types,
        # Denormalized so callers don't have to walk the map to find the day's worst reading.
        "max_upi": max(known_upis) if known_upis else None,
    }


def parse_forecast(payload: dict) -> list:
    """Parse a full forecast:lookup response into one reading dict per forecast day."""
    region_code = payload.get("regionCode")
    readings = []
    for daily in payload.get("dailyInfo", []):
        reading = parse_daily_info(daily)
        reading["region_code"] = region_code
        readings.append(reading)
    return readings


def find_breaches(reading: dict, threshold, pollen_types=None) -> list:
    """Return the pollen types in `reading` whose UPI meets or exceeds `threshold`.

    `pollen_types` optionally limits the check to a subscriber's watched types; empty/missing
    means "all types". Types with an unknown UPI (None) are skipped -- missing coverage isn't
    the same as low pollen and shouldn't silently count as zero.
    """
    breaches = []
    for code, data in reading.get("types", {}).items():
        if pollen_types and code not in pollen_types:
            continue
        upi = data.get("upi")
        if upi is None:
            continue
        if upi >= threshold:
            breaches.append(
                {
                    "code": code,
                    "display_name": data.get("display_name"),
                    "upi": upi,
                    "category": data.get("category"),
                }
            )
    # Worst offender first, so an alert email leads with the most severe reading.
    return sorted(breaches, key=lambda b: b["upi"], reverse=True)
