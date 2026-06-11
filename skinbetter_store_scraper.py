#!/usr/bin/env python3
"""
Skinbetter Store Locator Scraper

This scraper extracts store location data from the Skinbetter store locator
(Yext Answers API) and saves it to a CSV file with the following columns:
- store_name
- address
- city
- state
- zip_code
- phone_number
- email
- website

Uses the Yext Answers API directly for efficient data extraction.
"""

import asyncio
import csv
import json
import re
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode


@dataclass
class StoreLocation:
    """Represents a store location with its details."""
    store_name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone_number: str
    email: str
    website: str


class SkinbetterStoreScraper:
    """Scraper for Skinbetter store locator (Yext Answers API)."""

    # Yext Answers API configuration
    API_BASE = "https://liveapi.yext.com/v2/accounts/me/answers/vertical/query"
    API_KEY = "33d953f8ebf5d0a82a78683fa4bab095"
    EXPERIENCE_KEY = "skinbetter-science-search-locator"
    VERTICAL_KEY = "locations"

    OUTPUT_FILE = "skinbetter_stores.csv"

    # Results per page (max 50 for Yext)
    PAGE_SIZE = 50

    def __init__(self, debug: bool = False):
        """
        Initialize the scraper.

        Args:
            debug: Save debug files (API responses JSON)
        """
        self.debug = debug
        self.stores: list[StoreLocation] = []

    def _build_api_url(self, offset: int = 0) -> str:
        """Build the Yext API URL with pagination."""
        params = {
            "experienceKey": self.EXPERIENCE_KEY,
            "api_key": self.API_KEY,
            "v": "20220511",
            "version": "PRODUCTION",
            "locale": "en",
            "input": "",  # Empty to get all locations
            "verticalKey": self.VERTICAL_KEY,
            "limit": self.PAGE_SIZE,
            "offset": offset,
            "retrieveFacets": "false",
            "sessionTrackingEnabled": "false",
            "locationRadius": "50000000",  # Large radius to get all
        }
        return f"{self.API_BASE}?{urlencode(params)}"

    def _fetch_page(self, offset: int = 0) -> dict:
        """Fetch a page of results from the Yext API."""
        url = self._build_api_url(offset)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def scrape(self) -> list[StoreLocation]:
        """
        Main scraping method. Fetches all locations from Yext API.

        Returns:
            List of StoreLocation objects
        """
        print("Fetching locations from Yext API...")

        all_results = []
        offset = 0
        total_count = None

        while True:
            try:
                print(f"  Fetching page at offset {offset}...")
                data = self._fetch_page(offset)

                # Get total count from first response
                if total_count is None:
                    total_count = data.get("response", {}).get("resultsCount", 0)
                    print(f"  Total locations available: {total_count}")

                # Extract results
                results = data.get("response", {}).get("results", [])
                if not results:
                    break

                all_results.extend(results)
                print(f"  Retrieved {len(results)} locations (total so far: {len(all_results)})")

                # Check if we've got all results
                if len(all_results) >= total_count:
                    break

                offset += self.PAGE_SIZE

            except Exception as e:
                print(f"  Error fetching page: {e}")
                break

        print(f"\nProcessing {len(all_results)} locations...")

        # Parse each result into StoreLocation
        for result in all_results:
            store = self._parse_yext_location(result)
            if store:
                self.stores.append(store)

        # Save debug file if requested
        if self.debug:
            with open("debug_api_responses.json", "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2)
            print(f"  Saved debug file: debug_api_responses.json")

        print(f"Successfully parsed {len(self.stores)} stores")
        return self.stores

    def _parse_yext_location(self, result: dict) -> Optional[StoreLocation]:
        """Parse a Yext API result into a StoreLocation."""
        try:
            # The actual data is nested under 'data'
            data = result.get("data", {})

            name = data.get("name", "") or ""
            address_data = data.get("address", {})

            address = address_data.get("line1", "") or ""
            line2 = address_data.get("line2", "") or ""
            if line2:
                address = f"{address}, {line2}"

            city = address_data.get("city", "") or ""
            state = address_data.get("region", "") or ""  # Yext uses 'region' for state
            zip_code = address_data.get("postalCode", "") or ""

            phone = data.get("mainPhone", "") or ""
            email = data.get("c_accountEmailAddress", "") or ""
            website = data.get("websiteUrl", "") or data.get("website", "") or ""

            if name:
                return StoreLocation(
                    store_name=str(name).strip(),
                    address=str(address).strip(),
                    city=str(city).strip(),
                    state=str(state).strip(),
                    zip_code=str(zip_code).strip(),
                    phone_number=str(phone).strip(),
                    email=str(email).strip(),
                    website=str(website).strip()
                )
        except Exception as e:
            print(f"  Error parsing location: {e}")

        return None

    def save_to_csv(self, filename: Optional[str] = None) -> str:
        """Save stores to CSV file."""
        output_file = filename or self.OUTPUT_FILE

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'store_name', 'address', 'city', 'state', 'zip_code',
                'phone_number', 'email', 'website'
            ])
            writer.writeheader()

            for store in self.stores:
                writer.writerow(asdict(store))

        print(f"Saved {len(self.stores)} stores to {output_file}")
        return output_file


def main():
    """Main entry point."""
    print("=" * 60)
    print("Skinbetter Store Locator Scraper")
    print("=" * 60)

    debug = "--debug" in sys.argv

    if debug:
        print("Debug mode enabled - will save API responses")

    scraper = SkinbetterStoreScraper(debug=debug)

    try:
        stores = scraper.scrape()

        if stores:
            print(f"\nFound {len(stores)} store locations!")
            scraper.save_to_csv()

            # Print first few stores as preview
            print("\nPreview of extracted data:")
            print("-" * 40)
            for i, store in enumerate(stores[:5]):
                print(f"\n{i+1}. {store.store_name}")
                if store.address:
                    print(f"   Address: {store.address}")
                if store.city or store.state or store.zip_code:
                    print(f"   Location: {store.city}, {store.state} {store.zip_code}".strip())
                if store.phone_number:
                    print(f"   Phone: {store.phone_number}")
                if store.email:
                    print(f"   Email: {store.email}")
                if store.website:
                    print(f"   Website: {store.website}")

            if len(stores) > 5:
                print(f"\n... and {len(stores) - 5} more stores")
        else:
            print("\nNo store locations found.")

    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
