"""Seed the tracked-location config items into DynamoDB.

The ingestion job reads these to decide what to fetch. Run once after deploying the stack:

    DDB_TABLE_NAME=allergy-tracker python scripts/seed_locations.py

Edit LOCATIONS below to track somewhere else. Re-running is safe -- writes are keyed by
location id, so they overwrite rather than duplicate.
"""
import os
from decimal import Decimal

import boto3

TABLE_NAME = os.getenv("DDB_TABLE_NAME", "allergy-tracker")

LOCATIONS = [
    {
        "location_id": "vancouver",
        "display_name": "Vancouver, BC",
        "latitude": Decimal("49.2827"),
        "longitude": Decimal("-123.1207"),
    },
    {
        "location_id": "toronto",
        "display_name": "Toronto, ON",
        "latitude": Decimal("43.6532"),
        "longitude": Decimal("-79.3832"),
    },
    {
        "location_id": "new_york",
        "display_name": "New York, NY",
        "latitude": Decimal("40.7128"),
        "longitude": Decimal("-74.0060"),
    },
    {
        "location_id": "los_angeles",
        "display_name": "Los Angeles, CA",
        "latitude": Decimal("34.0522"),
        "longitude": Decimal("-118.2437"),
    },
    {
        "location_id": "chicago",
        "display_name": "Chicago, IL",
        "latitude": Decimal("41.8781"),
        "longitude": Decimal("-87.6298"),
    },
    {
        "location_id": "seattle",
        "display_name": "Seattle, WA",
        "latitude": Decimal("47.6062"),
        "longitude": Decimal("-122.3321"),
    },
    {
        "location_id": "mexico_city",
        "display_name": "Mexico City",
        "latitude": Decimal("19.4326"),
        "longitude": Decimal("-99.1332"),
    },
    {
        "location_id": "london",
        "display_name": "London, UK",
        "latitude": Decimal("51.5072"),
        "longitude": Decimal("-0.1276"),
    },
    {
        "location_id": "paris",
        "display_name": "Paris, France",
        "latitude": Decimal("48.8566"),
        "longitude": Decimal("2.3522"),
    },
    {
        "location_id": "berlin",
        "display_name": "Berlin, Germany",
        "latitude": Decimal("52.5200"),
        "longitude": Decimal("13.4050"),
    },
    {
        "location_id": "madrid",
        "display_name": "Madrid, Spain",
        "latitude": Decimal("40.4168"),
        "longitude": Decimal("-3.7038"),
    },
    {
        "location_id": "rome",
        "display_name": "Rome, Italy",
        "latitude": Decimal("41.9028"),
        "longitude": Decimal("12.4964"),
    },
    {
        "location_id": "amsterdam",
        "display_name": "Amsterdam, Netherlands",
        "latitude": Decimal("52.3676"),
        "longitude": Decimal("4.9041"),
    },
    {
        "location_id": "dublin",
        "display_name": "Dublin, Ireland",
        "latitude": Decimal("53.3498"),
        "longitude": Decimal("-6.2603"),
    },
    {
        "location_id": "zurich",
        "display_name": "Zurich, Switzerland",
        "latitude": Decimal("47.3769"),
        "longitude": Decimal("8.5417"),
    },
    {
        "location_id": "vienna",
        "display_name": "Vienna, Austria",
        "latitude": Decimal("48.2082"),
        "longitude": Decimal("16.3738"),
    },
    {
        "location_id": "stockholm",
        "display_name": "Stockholm, Sweden",
        "latitude": Decimal("59.3293"),
        "longitude": Decimal("18.0686"),
    },
    {
        "location_id": "warsaw",
        "display_name": "Warsaw, Poland",
        "latitude": Decimal("52.2297"),
        "longitude": Decimal("21.0122"),
    },
    {
        "location_id": "sydney",
        "display_name": "Sydney, Australia",
        "latitude": Decimal("-33.8688"),
        "longitude": Decimal("151.2093"),
    },
    {
        "location_id": "sao_paulo",
        "display_name": "Sao Paulo, Brazil",
        "latitude": Decimal("-23.5505"),
        "longitude": Decimal("-46.6333"),
    },
]


def main():
    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    for loc in LOCATIONS:
        table.put_item(
            Item={
                "pk": "CONFIG#LOCATIONS",
                "sk": f"LOC#{loc['location_id']}",
                "entity": "LOCATION",
                "enabled": True,
                **loc,
            }
        )
        print(f"Seeded {loc['location_id']} ({loc['display_name']})")


if __name__ == "__main__":
    main()
