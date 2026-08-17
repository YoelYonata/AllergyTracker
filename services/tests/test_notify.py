from notify.handler import _parse_stream_record


def _record(event_name, new_image):
    return {"eventName": event_name, "dynamodb": {"NewImage": new_image}} if new_image else {
        "eventName": event_name,
        "dynamodb": {},
    }


READING_IMAGE = {
    "pk": {"S": "LOC#vancouver"},
    "sk": {"S": "READING#2026-08-10"},
    "entity": {"S": "READING"},
    "location_id": {"S": "vancouver"},
    "date": {"S": "2026-08-10"},
    "max_upi": {"N": "4"},
    "types": {
        "M": {
            "GRASS": {
                "M": {
                    "display_name": {"S": "Grass"},
                    "upi": {"N": "4"},
                    "category": {"S": "High"},
                    "in_season": {"BOOL": True},
                }
            }
        }
    },
}

SUBSCRIBER_IMAGE = {
    "pk": {"S": "LOC#vancouver"},
    "sk": {"S": "SUB#user@example.com"},
    "entity": {"S": "SUBSCRIBER"},
    "last_notified_date": {"S": "2026-08-10"},
}


def test_parses_insert_of_a_reading_item():
    reading = _parse_stream_record(_record("INSERT", READING_IMAGE))

    assert reading["location_id"] == "vancouver"
    assert reading["date"] == "2026-08-10"
    # Deserialized DynamoDB numbers come back as Decimal, but compare equal to int/float.
    assert reading["types"]["GRASS"]["upi"] == 4


def test_parses_modify_of_a_reading_item():
    reading = _parse_stream_record(_record("MODIFY", READING_IMAGE))

    assert reading is not None
    assert reading["entity"] == "READING"


def test_ignores_remove_events():
    assert _parse_stream_record(_record("REMOVE", READING_IMAGE)) is None


def test_ignores_non_reading_items():
    assert _parse_stream_record(_record("MODIFY", SUBSCRIBER_IMAGE)) is None


def test_ignores_records_with_no_new_image():
    assert _parse_stream_record(_record("INSERT", None)) is None
