#!/usr/bin/env python3
"""
Scraper for Hydrinity professional locations from Stockist API.
Downloads all locations and saves to CSV file.
"""

import csv
import json
import urllib.request

API_URL = "https://stockist.co/api/v1/u14539/locations/all"
OUTPUT_FILE = "hydrinity_professionals.csv"

# CSV columns to export
COLUMNS = [
    "id",
    "name",
    "latitude",
    "longitude",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postal_code",
    "country",
    "phone",
    "website",
    "email",
    "description",
]


def fetch_locations():
    """Fetch all locations from Stockist API."""
    print(f"Fetching data from {API_URL}...")
    req = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.hydrinity.com/",
        },
    )
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode("utf-8"))
    print(f"Found {len(data)} locations")
    return data


def save_to_csv(locations, filename):
    """Save locations to CSV file."""
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(locations)
    print(f"Saved to {filename}")


def main():
    locations = fetch_locations()
    save_to_csv(locations, OUTPUT_FILE)


if __name__ == "__main__":
    main()
