"""Throwaway script: print a raw Google Pollen API response so the ingestion Lambda's
parser can be written against the real payload shape instead of guessed.

Setup:
1. In Google Cloud Console, enable the "Pollen API" on a project and create an API key.
2. export GOOGLE_POLLEN_API_KEY=your-key-here
3. python scripts/fetch_pollen_sample.py --lat 49.2827 --lng -123.1207

Docs: https://developers.google.com/maps/documentation/pollen/reference/rest/v1/forecast/lookup
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

API_URL = "https://pollen.googleapis.com/v1/forecast:lookup"


def fetch_forecast(lat: float, lng: float, days: int, api_key: str) -> dict:
    params = {
        "key": api_key,
        "location.latitude": lat,
        "location.longitude": lng,
        "days": days,
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, default=49.2827, help="Latitude (default: Vancouver)")
    parser.add_argument("--lng", type=float, default=-123.1207, help="Longitude (default: Vancouver)")
    parser.add_argument("--days", type=int, default=1, help="Forecast days, 1-5 (default: 1)")
    args = parser.parse_args()

    api_key = os.getenv("GOOGLE_POLLEN_API_KEY")
    if not api_key:
        print("Set GOOGLE_POLLEN_API_KEY first (see docstring for setup).", file=sys.stderr)
        sys.exit(1)

    data = fetch_forecast(args.lat, args.lng, args.days, api_key)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
