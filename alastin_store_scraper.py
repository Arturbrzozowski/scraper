#!/usr/bin/env python3
"""
Alastin Store Locator Scraper

This scraper extracts store location data from the Alastin provider locator
(RetailLink API) and saves it to a CSV file with the following columns:
- store_name
- address
- city
- state
- zip_code
- phone_number
- email
- website

Uses the RetailLink API via Shopify app proxy for data extraction.
"""

import csv
import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlencode


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


class AlastinStoreScraper:
    """Scraper for Alastin provider locator (RetailLink API)."""

    # RetailLink API configuration (Shopify app proxy)
    API_BASE = "https://alastin.com/apps/retail-link/locations"
    SHOP = "alastin.myshopify.com"

    OUTPUT_FILE = "alastin_stores.csv"

    # Limit per request (max 125 per the config)
    PAGE_LIMIT = 125

    # US regions to cover (bounding boxes to ensure full coverage)
    # Each region is: (name, minLat, maxLat, minLng, maxLng)
    US_REGIONS = [
        # West Coast
        ("Pacific Northwest", 42.0, 49.0, -125.0, -116.0),
        ("Northern California", 37.0, 42.0, -125.0, -119.0),
        ("Southern California", 32.5, 37.0, -125.0, -114.0),
        # Mountain West
        ("Mountain North", 42.0, 49.0, -116.0, -104.0),
        ("Mountain Central", 36.5, 42.0, -114.0, -104.0),
        ("Mountain South", 31.0, 36.5, -114.0, -103.0),
        # Central
        ("Plains North", 42.0, 49.0, -104.0, -96.0),
        ("Plains Central", 36.0, 42.0, -104.0, -94.0),
        ("Plains South", 29.0, 36.0, -106.0, -94.0),
        # Midwest
        ("Great Lakes", 41.0, 49.0, -96.0, -82.0),
        ("Midwest Central", 36.0, 41.0, -94.0, -84.0),
        # South
        ("Gulf Coast", 26.0, 31.0, -98.0, -82.0),
        ("Deep South", 31.0, 36.0, -94.0, -82.0),
        ("Southeast", 25.0, 31.0, -82.0, -75.0),
        # East
        ("Mid-Atlantic", 36.0, 41.5, -82.0, -74.0),
        ("Northeast", 40.5, 45.5, -79.0, -69.5),
        ("New England", 41.0, 47.5, -74.0, -66.5),
        # East Coast extended
        ("Atlantic South", 31.0, 36.0, -82.0, -75.5),
        # Additional coverage
        ("Hawaii", 18.5, 22.5, -161.0, -154.0),
        ("Alaska South", 54.0, 62.0, -165.0, -140.0),
        ("Puerto Rico", 17.5, 18.6, -67.5, -65.0),
    ]

    def __init__(self, debug: bool = False):
        """
        Initialize the scraper.

        Args:
            debug: Save debug files (API responses JSON)
        """
        self.debug = debug
        self.stores: list[StoreLocation] = []
        self.seen_tokens: set[str] = set()  # For deduplication

    def _build_api_url(self, min_lat: float, max_lat: float, min_lng: float, max_lng: float) -> str:
        """Build the RetailLink API URL with bounding box."""
        params = {
            "shop": self.SHOP,
            "limit": self.PAGE_LIMIT,
            "format": "search",
            "minLat": min_lat,
            "maxLat": max_lat,
            "minLng": min_lng,
            "maxLng": max_lng,
        }
        return f"{self.API_BASE}?{urlencode(params)}"

    def _fetch_region(self, name: str, min_lat: float, max_lat: float, min_lng: float, max_lng: float) -> list[dict]:
        """Fetch locations for a region from the RetailLink API."""
        url = self._build_api_url(min_lat, max_lat, min_lng, max_lng)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://alastin.com/pages/provider-locator",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))

            if data.get("success") and data.get("data"):
                return data["data"]
            return []
        except Exception as e:
            print(f"    Error fetching {name}: {e}")
            return []

    def scrape(self) -> list[StoreLocation]:
        """
        Main scraping method. Fetches all locations from RetailLink API.

        Returns:
            List of StoreLocation objects
        """
        print("Fetching locations from RetailLink API...")
        print(f"Searching {len(self.US_REGIONS)} regions for complete coverage\n")

        all_results = []

        for region_name, min_lat, max_lat, min_lng, max_lng in self.US_REGIONS:
            print(f"  Searching: {region_name}...", end=" ", flush=True)

            locations = self._fetch_region(region_name, min_lat, max_lat, min_lng, max_lng)
            new_count = 0

            for loc in locations:
                token = loc.get("token")
                if token and token not in self.seen_tokens:
                    self.seen_tokens.add(token)
                    all_results.append(loc)
                    new_count += 1

            print(f"found {len(locations)} locations ({new_count} new)")

        print(f"\nTotal unique locations found: {len(all_results)}")
        print(f"Processing locations...")

        # Parse each result into StoreLocation
        for result in all_results:
            store = self._parse_retaillink_location(result)
            if store:
                self.stores.append(store)

        # Save debug file if requested
        if self.debug:
            with open("debug_api_responses.json", "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2)
            print(f"  Saved debug file: debug_api_responses.json")

        print(f"Successfully parsed {len(self.stores)} stores")
        return self.stores

    def _parse_retaillink_location(self, result: dict) -> Optional[StoreLocation]:
        """Parse a RetailLink API result into a StoreLocation."""
        try:
            # RetailLink returns flat structure
            company = result.get("company", "") or ""
            name = result.get("name", "") or ""

            # Use company as store name, fallback to name
            store_name = company if company else name

            street = result.get("street", "") or ""
            street2 = result.get("street2", "") or ""
            if street2:
                address = f"{street}, {street2}"
            else:
                address = street

            city = result.get("city", "") or ""
            state = result.get("state", "") or ""
            zip_code = result.get("zip", "") or ""

            phone = result.get("phone", "") or ""
            # Format phone if it's a raw number
            formatted_phone = result.get("formattedPhone", "") or ""
            if formatted_phone:
                phone = formatted_phone

            email = result.get("email", "") or ""
            website = result.get("website", "") or ""

            if store_name:
                return StoreLocation(
                    store_name=str(store_name).strip(),
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
    print("Alastin Provider Locator Scraper")
    print("=" * 60)

    debug = "--debug" in sys.argv

    if debug:
        print("Debug mode enabled - will save API responses")

    scraper = AlastinStoreScraper(debug=debug)

    try:
        stores = scraper.scrape()

        if stores:
            print(f"\nFound {len(stores)} provider locations!")
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
            print("\nNo provider locations found.")

    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
