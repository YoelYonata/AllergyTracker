from decimal import Decimal

from ingest import pollen_api


def test_parse_forecast_returns_one_reading_per_day(sample_forecast_payload):
    readings = pollen_api.parse_forecast(sample_forecast_payload)

    assert len(readings) == 2
    assert [r["date"] for r in readings] == ["2026-08-10", "2026-08-11"]
    assert all(r["region_code"] == "CA" for r in readings)


def test_parse_daily_info_flattens_pollen_types(sample_forecast_payload):
    reading = pollen_api.parse_forecast(sample_forecast_payload)[0]

    assert reading["types"]["TREE"] == {
        "display_name": "Tree",
        "in_season": True,
        "upi": Decimal("0"),
        "category": "None",
    }
    assert reading["types"]["WEED"]["upi"] == Decimal("1")


def test_parse_daily_info_treats_missing_coverage_as_null_not_zero(sample_forecast_payload):
    reading = pollen_api.parse_forecast(sample_forecast_payload)[0]

    # GRASS has no indexInfo in the fixture (the real API omits it when there's no coverage).
    assert reading["types"]["GRASS"]["upi"] is None


def test_max_upi_ignores_null_types(sample_forecast_payload):
    reading = pollen_api.parse_forecast(sample_forecast_payload)[0]

    # GRASS (null) is excluded; the max across TREE=0 and WEED=1 is 1.
    assert reading["max_upi"] == Decimal("1")


def test_max_upi_is_none_when_no_type_has_coverage():
    reading = pollen_api.parse_daily_info(
        {
            "date": {"year": 2026, "month": 8, "day": 10},
            "pollenTypeInfo": [{"code": "GRASS", "displayName": "Grass"}],
        }
    )

    assert reading["max_upi"] is None


def test_find_breaches_flags_types_at_or_above_threshold():
    reading = {
        "types": {
            "GRASS": {"display_name": "Grass", "upi": 4, "category": "High"},
            "TREE": {"display_name": "Tree", "upi": 1, "category": "Very Low"},
            "WEED": {"display_name": "Weed", "upi": 3, "category": "Moderate"},
        }
    }

    breaches = pollen_api.find_breaches(reading, threshold=3)

    # Sorted worst-first.
    assert [b["code"] for b in breaches] == ["GRASS", "WEED"]


def test_find_breaches_skips_null_upi():
    reading = {"types": {"GRASS": {"display_name": "Grass", "upi": None, "category": None}}}

    assert pollen_api.find_breaches(reading, threshold=0) == []


def test_find_breaches_respects_subscriber_pollen_type_filter():
    reading = {
        "types": {
            "GRASS": {"display_name": "Grass", "upi": 5, "category": "Very High"},
            "TREE": {"display_name": "Tree", "upi": 5, "category": "Very High"},
        }
    }

    breaches = pollen_api.find_breaches(reading, threshold=1, pollen_types=["TREE"])

    assert [b["code"] for b in breaches] == ["TREE"]
