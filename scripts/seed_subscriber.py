"""Manually create a test subscriber, standing in for the real Phase 4/5 subscribe form.

The subscriber is created PENDING -- get_subscribers() only returns CONFIRMED subscribers, so
no alerts go out until the printed confirm link is opened. This script only prints the link
(it doesn't email it) so it's usable before SES is fully set up; once Phase 4/5 build the real
`POST /subscribe` endpoint, that flow will email this same link via
common.ses.send_confirmation_email instead.

Usage:
    DDB_TABLE_NAME=allergy-tracker CONFIRM_BASE_URL=https://xxxx.lambda-url.ca-central-1.on.aws \
      python scripts/seed_subscriber.py --location vancouver --email you@example.com --threshold 0
"""
import argparse
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "src"))

from common.store import Store  # noqa: E402

TABLE_NAME = os.getenv("DDB_TABLE_NAME", "allergy-tracker")
CONFIRM_BASE_URL = os.getenv("CONFIRM_BASE_URL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", required=True, help="location_id, e.g. vancouver")
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--threshold",
        type=int,
        default=3,
        help="Alert when any watched type's UPI >= this (default 3). Use 0 to test against "
        "today's real reading regardless of how low pollen currently is.",
    )
    parser.add_argument(
        "--types",
        help="Comma-separated pollen types to watch, e.g. GRASS,TREE. Omit for all types.",
    )
    args = parser.parse_args()

    if not CONFIRM_BASE_URL:
        print(
            "Set CONFIRM_BASE_URL to the deployed ConfirmFunction's Function URL first "
            "(see the stack's Outputs, or `sam list stack-outputs`).",
            file=sys.stderr,
        )
        sys.exit(1)

    pollen_types = [t.strip().upper() for t in args.types.split(",")] if args.types else None

    store = Store(TABLE_NAME)
    subscriber = store.create_pending_subscriber(
        location_id=args.location,
        email=args.email,
        threshold=args.threshold,
        pollen_types=pollen_types,
    )

    if subscriber is None:
        print(
            f"{args.email} is already CONFIRMED for {args.location} -- refusing to reset it to "
            "PENDING (that would stop their alerts). Delete the item first, or use another "
            "address.",
            file=sys.stderr,
        )
        sys.exit(1)

    confirm_url = f"{CONFIRM_BASE_URL.rstrip('/')}/?" + urllib.parse.urlencode(
        {
            "location_id": args.location,
            "email": args.email,
            "token": subscriber["confirm_token"],
        }
    )

    print(f"Created PENDING subscriber {args.email} for {args.location} (threshold={args.threshold})")
    print("Open this link to confirm (it will not receive alerts until confirmed):")
    print(confirm_url)


if __name__ == "__main__":
    main()
