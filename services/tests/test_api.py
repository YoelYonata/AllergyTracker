"""Tests for the read API's pure request-handling logic.

Everything here runs without boto3 or a network call: parsing, validation, range math, and
response encoding are deliberately split out of the route functions so they're testable on
their own, the same way pollen_api.py separates parsing from fetching.
"""
import base64
import json
from decimal import Decimal

import pytest

from api.handler import (
    DEFAULT_HISTORY_DAYS,
    MAX_HISTORY_DAYS,
    _history_range,
    _json_response,
    _parse_body,
    _parse_days,
    _public_reading,
    _validate_subscribe,
)


# --- Response encoding ------------------------------------------------------------------


def test_encodes_dynamodb_decimals_as_plain_numbers():
    response = _json_response(200, {"upi": Decimal("4"), "lat": Decimal("49.28")})
    body = json.loads(response["body"])

    # A whole-number Decimal must not come out as 4.0 -- UPI is an integer scale.
    assert body["upi"] == 4
    assert isinstance(body["upi"], int)
    assert body["lat"] == pytest.approx(49.28)


def test_encodes_dynamodb_string_sets_as_lists():
    body = json.loads(_json_response(200, {"pollen_types": {"TREE", "GRASS"}})["body"])

    assert body["pollen_types"] == ["GRASS", "TREE"]


def test_public_reading_strips_internal_attributes():
    item = {
        "pk": "LOC#vancouver",
        "sk": "READING#2026-08-10",
        "entity": "READING",
        "ttl": 1786000000,
        "date": "2026-08-10",
        "max_upi": Decimal("4"),
    }

    assert _public_reading(item) == {"date": "2026-08-10", "max_upi": Decimal("4")}


# --- History range ----------------------------------------------------------------------


def test_history_range_is_inclusive_of_both_ends():
    start, end = _history_range(14, "2026-08-13")

    assert start == "2026-07-31"
    assert end == "2026-08-13"


def test_history_range_of_one_day_is_just_today():
    assert _history_range(1, "2026-08-13") == ("2026-08-13", "2026-08-13")


def test_history_range_ends_today_not_at_the_furthest_forecast():
    # Readings exist for days ahead of today; the trend chart must not silently include them.
    _, end = _history_range(30, "2026-08-13")

    assert end == "2026-08-13"


def test_history_range_crosses_a_month_boundary():
    assert _history_range(5, "2026-03-02")[0] == "2026-02-26"


# --- ?days= parsing ---------------------------------------------------------------------


@pytest.mark.parametrize("params", [{}, {"days": ""}])
def test_days_defaults_when_absent_or_blank(params):
    assert _parse_days(params) == (DEFAULT_HISTORY_DAYS, None)


def test_days_accepts_a_valid_value():
    assert _parse_days({"days": "7"}) == (7, None)


@pytest.mark.parametrize("raw", ["0", "-3", str(MAX_HISTORY_DAYS + 1), "100000"])
def test_days_rejects_out_of_range_values(raw):
    days, error = _parse_days({"days": raw})

    assert days is None
    assert error


def test_days_rejects_non_integers():
    days, error = _parse_days({"days": "fourteen"})

    assert days is None
    assert "integer" in error


# --- Body parsing -----------------------------------------------------------------------


def test_parses_a_plain_json_body():
    payload, error = _parse_body({"body": '{"email": "a@b.com"}'})

    assert error is None
    assert payload == {"email": "a@b.com"}


def test_parses_a_base64_encoded_body():
    raw = base64.b64encode(b'{"email": "a@b.com"}').decode()
    payload, error = _parse_body({"body": raw, "isBase64Encoded": True})

    assert error is None
    assert payload == {"email": "a@b.com"}


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"body": ""},
        {"body": "not json"},
        {"body": "[1, 2, 3]"},  # valid JSON, but not an object
    ],
)
def test_rejects_unusable_bodies(event):
    payload, error = _parse_body(event)

    assert payload is None
    assert error


# --- Subscribe validation ---------------------------------------------------------------


def test_accepts_a_minimal_subscribe_payload():
    data, error = _validate_subscribe({"email": "User@Example.com", "location": "Vancouver"})

    assert error is None
    # Both are normalized to lowercase so "User@..." and "user@..." can't become two subscribers
    # for what is the same DynamoDB partition key in every other respect.
    assert data["email"] == "user@example.com"
    assert data["location_id"] == "vancouver"
    assert data["pollen_types"] is None


def test_accepts_location_id_as_an_alias_for_location():
    data, error = _validate_subscribe({"email": "a@b.com", "location_id": "vancouver"})

    assert error is None
    assert data["location_id"] == "vancouver"


@pytest.mark.parametrize("email", ["", "not-an-email", "no@tld", "two @spaces.com", "a@" + "b" * 300 + ".com"])
def test_rejects_bad_email_addresses(email):
    data, error = _validate_subscribe({"email": email, "location": "vancouver"})

    assert data is None
    assert error


def test_rejects_a_missing_location():
    data, error = _validate_subscribe({"email": "a@b.com"})

    assert data is None
    assert "location" in error


@pytest.mark.parametrize("threshold", [-1, 6, 99])
def test_rejects_thresholds_outside_the_upi_scale(threshold):
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "threshold": threshold}
    )

    assert data is None
    assert error


@pytest.mark.parametrize("threshold", ["3", 3.5, None, True])
def test_rejects_non_integer_thresholds(threshold):
    # True is the interesting one: bool subclasses int, so it would otherwise pass as 1.
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "threshold": threshold}
    )

    assert data is None
    assert "integer" in error


def test_threshold_zero_is_valid():
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "threshold": 0}
    )

    assert error is None
    assert data["threshold"] == 0


def test_normalizes_and_deduplicates_pollen_types():
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "pollen_types": ["tree", "GRASS", "Tree"]}
    )

    assert error is None
    assert data["pollen_types"] == ["GRASS", "TREE"]


def test_empty_pollen_types_means_all_types():
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "pollen_types": []}
    )

    assert error is None
    assert data["pollen_types"] is None


def test_rejects_unknown_pollen_types():
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "pollen_types": ["GRASS", "RAGWEED"]}
    )

    assert data is None
    assert "RAGWEED" in error


def test_rejects_non_list_pollen_types():
    data, error = _validate_subscribe(
        {"email": "a@b.com", "location": "vancouver", "pollen_types": "GRASS"}
    )

    assert data is None
    assert error
