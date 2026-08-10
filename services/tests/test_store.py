from ingest.store import CONFIG_LOCATIONS_PK, location_pk, reading_sk, subscriber_sk


def test_location_pk():
    assert location_pk("vancouver") == "LOC#vancouver"


def test_reading_sk():
    assert reading_sk("2026-08-10") == "READING#2026-08-10"


def test_subscriber_sk():
    assert subscriber_sk("user@example.com") == "SUB#user@example.com"


def test_config_locations_pk_is_a_fixed_partition():
    assert CONFIG_LOCATIONS_PK == "CONFIG#LOCATIONS"
