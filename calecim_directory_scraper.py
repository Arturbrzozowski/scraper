#!/usr/bin/env python3
"""
CALECIM Professional Pro-Directory Scraper

This scraper extracts the salon/clinic directory data behind the locations map
on https://calecimprofessional.com/pages/pro-directory.

The directory is powered by the Stockist store-locator widget (tag "u7465").
Stockist exposes a public JSON endpoint that returns every location in a single
request, so no browser automation is required.

Captured columns:
- id
- name              (clinic / salon name)
- contact_name      (from Stockist "description" field, e.g. owner / practitioner)
- category          (Salons or Clinics, from Stockist filters)
- address_line_1    (street)
- address_line_2
- city
- state
- postal_code
- country
- phone
- landline          (custom field)
- email
- website
- short_address     (custom field)
- hair_treatments   (custom field)
- latitude
- longitude
"""

import csv
import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, fields as dataclass_fields
from typing import Optional


@dataclass
class DirectoryLocation:
    """Represents a single salon/clinic directory entry."""
    id: str
    name: str
    contact_name: str
    category: str
    address_line_1: str
    address_line_2: str
    city: str
    state: str
    postal_code: str
    country: str
    phone: str
    landline: str
    email: str
    website: str
    short_address: str
    hair_treatments: str
    latitude: str
    longitude: str


class CalecimDirectoryScraper:
    """Scraper for the CALECIM Professional pro-directory (Stockist widget)."""

    # Stockist widget tag found on the pro-directory page
    # (data-stockist-widget-tag="u7465")
    WIDGET_TAG = "u7465"

    # Stockist public locations endpoint - returns ALL locations in one call
    API_URL = "https://stockist.co/api/v1/{tag}/locations/all"

    OUTPUT_FILE = "calecim_directory.csv"

    def __init__(self, debug: bool = False):
        """
        Initialize the scraper.

        Args:
            debug: Save the raw API response to a JSON file.
        """
        self.debug = debug
        self.locations: list[DirectoryLocation] = []

    def _fetch_all(self) -> list[dict]:
        """Fetch every location from the Stockist API."""
        url = self.API_URL.format(tag=self.WIDGET_TAG)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://calecimprofessional.com/pages/pro-directory",
            },
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def scrape(self) -> list[DirectoryLocation]:
        """
        Main scraping method. Fetches and parses all directory locations.

        Returns:
            List of DirectoryLocation objects.
        """
        print(f"Fetching locations from Stockist API (widget {self.WIDGET_TAG})...")

        raw = self._fetch_all()
        print(f"  Retrieved {len(raw)} raw locations")

        if self.debug:
            with open("debug_stockist_response.json", "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)
            print("  Saved debug file: debug_stockist_response.json")

        for entry in raw:
            location = self._parse_location(entry)
            if location:
                self.locations.append(location)

        print(f"Successfully parsed {len(self.locations)} locations")
        return self.locations

    @staticmethod
    def _clean(value) -> str:
        """Normalise a value to a trimmed string ('' for None)."""
        if value is None:
            return ""
        return str(value).strip()

    def _parse_location(self, entry: dict) -> Optional[DirectoryLocation]:
        """Parse a single Stockist location record into a DirectoryLocation."""
        try:
            # Category comes from the Stockist "filters" (e.g. Salons / Clinics)
            category = ", ".join(
                self._clean(f.get("name"))
                for f in (entry.get("filters") or [])
                if self._clean(f.get("name"))
            )

            # Custom fields are a list of {name, value, ...}
            custom = {
                self._clean(cf.get("name")): self._clean(cf.get("value"))
                for cf in (entry.get("custom_fields") or [])
            }

            return DirectoryLocation(
                id=self._clean(entry.get("id")),
                name=self._clean(entry.get("name")),
                # Stockist's free-text "description" is used by this directory to
                # store the contact / owner / practitioner name.
                contact_name=self._clean(entry.get("description")),
                category=category,
                address_line_1=self._clean(entry.get("address_line_1")),
                address_line_2=self._clean(entry.get("address_line_2")),
                city=self._clean(entry.get("city")),
                state=self._clean(entry.get("state")),
                postal_code=self._clean(entry.get("postal_code")),
                country=self._clean(entry.get("country")),
                phone=self._clean(entry.get("phone")),
                landline=custom.get("Landline", ""),
                email=self._clean(entry.get("email")),
                website=self._clean(entry.get("website")),
                short_address=custom.get("Short Address", ""),
                hair_treatments=custom.get("Hair Treatments Available", ""),
                latitude=self._clean(entry.get("latitude")),
                longitude=self._clean(entry.get("longitude")),
            )
        except Exception as e:
            print(f"  Error parsing location {entry.get('id')}: {e}")
            return None

    def save_to_csv(self, filename: Optional[str] = None) -> str:
        """Save locations to a CSV file."""
        output_file = filename or self.OUTPUT_FILE
        fieldnames = [f.name for f in dataclass_fields(DirectoryLocation)]

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for location in self.locations:
                writer.writerow(asdict(location))

        print(f"Saved {len(self.locations)} locations to {output_file}")
        return output_file


def main():
    """Main entry point."""
    print("=" * 60)
    print("CALECIM Professional Pro-Directory Scraper")
    print("=" * 60)

    debug = "--debug" in sys.argv
    if debug:
        print("Debug mode enabled - will save raw API response")

    scraper = CalecimDirectoryScraper(debug=debug)

    try:
        locations = scraper.scrape()

        if locations:
            print(f"\nFound {len(locations)} directory locations!")
            scraper.save_to_csv()

            print("\nPreview of extracted data:")
            print("-" * 40)
            for i, loc in enumerate(locations[:5]):
                print(f"\n{i + 1}. {loc.name or '(no name)'}")
                if loc.contact_name:
                    print(f"   Contact: {loc.contact_name}")
                if loc.category:
                    print(f"   Category: {loc.category}")
                addr = ", ".join(
                    p for p in [loc.address_line_1, loc.address_line_2, loc.city,
                                loc.state, loc.postal_code, loc.country] if p
                )
                if addr:
                    print(f"   Address: {addr}")
                if loc.phone:
                    print(f"   Phone: {loc.phone}")
                if loc.email:
                    print(f"   Email: {loc.email}")
                if loc.website:
                    print(f"   Website: {loc.website}")

            if len(locations) > 5:
                print(f"\n... and {len(locations) - 5} more locations")
        else:
            print("\nNo directory locations found.")

    except urllib.error.HTTPError as e:
        print(f"\nHTTP error fetching data: {e.code} {e.reason}")
        raise
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
