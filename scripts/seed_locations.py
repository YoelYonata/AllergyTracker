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
