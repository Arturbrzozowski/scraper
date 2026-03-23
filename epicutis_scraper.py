#!/usr/bin/env python3
"""
Scraper for Epicutis provider locations.
Downloads all providers and saves to CSV file.
"""

import csv
import json
import urllib.request

API_URL = "https://admin-aizm.onrender.com/providers"
OUTPUT_FILE = "epicutis_providers.csv"

COLUMNS = [
    "name",
    "providerCode",
    "phoneNumber",
    "address",
    "streetAddress1",
    "streetAddress2",
    "city",
    "state",
    "zipCode",
    "country",
    "status",
    "latitude",
    "longitude",
    "createdAt",
    "updatedAt",
]


def fetch_providers():
    """Fetch all providers from Epicutis API."""
    print(f"Fetching data from {API_URL}...")
    req = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode("utf-8"))
    print(f"Found {len(data)} providers")
    return data


def flatten_provider(provider):
    """Flatten nested location coordinates into top-level fields."""
    flat = {k: v for k, v in provider.items() if k != "location"}
    coords = provider.get("location", {}).get("coordinates", [None, None])
    flat["longitude"] = coords[0] if len(coords) > 0 else None
    flat["latitude"] = coords[1] if len(coords) > 1 else None
    return flat


def save_to_csv(providers, filename):
    """Save providers to CSV file."""
    rows = [flatten_provider(p) for p in providers]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved to {filename}")


def main():
    providers = fetch_providers()
    save_to_csv(providers, OUTPUT_FILE)


if __name__ == "__main__":
    main()
