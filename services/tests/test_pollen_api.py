"""Unit tests for Pollen API response parsing and the threshold check.

These cover the pure functions only -- no network, no AWS -- against a payload shaped like a
real forecast:lookup response. Replace SAMPLE_RESPONSE with a genuine recorded payload from
scripts/fetch_pollen_sample.py once you have an API key.
"""
from ingest import pollen_api

SAMPLE_RESPONSE = {
    "regionCode": "CA",
    "dailyInfo": [
        {
            "date": {"year": 2026, "month": 8, "day": 10},
            "pollenTypeInfo": [
                {
                    "code": "GRASS",
                    "displayName": "Grass",
                    "inSeason": True,
                    "indexInfo": {
                        "code": "UPI",
                        "displayName": "Universal Pollen Index",
                        "value": 4,
                        "category": "High",
                    },
                },
                {
                    "code": "TREE",
                    "displayName": "Tree",
                    "inSeason": False,
                    "indexInfo": {"code": "UPI", "value": 1, "category": "Very Low"},
                },
                # No indexInfo at all -- the API omits it where it has no coverage.
                {"code": "WEED", "displayName": "Weed", "inSeason": False},
            ],
        },
        {
            "date": {"year": 2026, "month": 8, "day": 11},
            "pollenTypeInfo": [
                {
                    "code": "GRASS",
                    "displayName": "Grass",
                    "inSeason": True,
                    "indexInfo": {"code": "UPI", "value": 2, "category": "Low"},
                }
            ],
        },
    ],
}


def test_parse_forecast_returns_one_reading_per_day():
    readings = pollen_api.parse_forecast(SAMPLE_RESPONSE)
    assert [r["date"] for r in readings] == ["2026-08-10", "2026-08-11"]
    assert all(r["region_code"] == "CA" for r in readings)


def test_dates_are_zero_padded_so_they_sort_correctly():
    payload = {"dailyInfo": [{"date": {"year": 2026, "month": 1, "day": 5}}]}
    assert pollen_api.parse_forecast(payload)[0]["date"] == "2026-01-05"


def test_missing_index_info_yields_none_not_zero():
    reading = pollen_api.parse_forecast(SAMPLE_RESPONSE)[0]
    assert reading["types"]["WEED"]["upi"] is None
    assert reading["types"]["GRASS"]["upi"] == 4


def test_max_upi_ignores_unknown_values():
    reading = pollen_api.parse_forecast(SAMPLE_RESPONSE)[0]
    assert reading["max_upi"] == 4


def test_max_upi_is_none_when_no_type_has_data():
    payload = {
        "dailyInfo": [
            {
                "date": {"year": 2026, "month": 8, "day": 10},
                "pollenTypeInfo": [{"code": "WEED", "displayName": "Weed"}],
            }
        ]
    }
    assert pollen_api.parse_forecast(payload)[0]["max_upi"] is None


def test_find_breaches_respects_threshold():
    reading = pollen_api.parse_forecast(SAMPLE_RESPONSE)[0]
    assert [b["code"] for b in pollen_api.find_breaches(reading, threshold=4)] == ["GRASS"]
    assert [b["code"] for b in pollen_api.find_breaches(reading, threshold=5)] == []


def test_find_breaches_orders_most_severe_first():
    reading = pollen_api.parse_forecast(SAMPLE_RESPONSE)[0]
    breaches = pollen_api.find_breaches(reading, threshold=1)
    assert [b["code"] for b in breaches] == ["GRASS", "TREE"]


def test_find_breaches_filters_to_subscribed_types():
    reading = pollen_api.parse_forecast(SAMPLE_RESPONSE)[0]
    breaches = pollen_api.find_breaches(reading, threshold=1, pollen_types=["TREE"])
    assert [b["code"] for b in breaches] == ["TREE"]


def test_find_breaches_skips_unknown_upi():
    """A missing UPI must never count as a breach, even at threshold 0."""
    reading = pollen_api.parse_forecast(SAMPLE_RESPONSE)[0]
    breaches = pollen_api.find_breaches(reading, threshold=0, pollen_types=["WEED"])
    assert breaches == []
