#!/usr/bin/env python3
"""
Jan Marini Skin Solutions Locator Scraper

This scraper extracts the professional directory data behind the locations map
on https://mariniskinsolutions.com/pages/locator.

The map is a custom React app that queries Jan Marini's own API by map
bounding box:

    https://api.janmarini.com/api/locator/qualified/bounds
        ?northWestLat=..&northWestLong=..&southEastLat=..&southEastLong=..

The endpoint returns at most 25 locations per request, so the scraper starts
from a world-spanning bounding box and recursively subdivides any tile that
hits the 25-result cap (quadtree scan), deduplicating along the way.

Captured columns (everything the API exposes):
- name              (clinic / business name, "CustName")
- address_line_1    (street, "Line1")
- address_line_2    ("Line2")
- city
- state
- zip
- location          (pre-formatted full address, "Location")
- customer_class    ("CustClassID", e.g. DOCTOR / WHOLESALE / SPA)
- loyalty
- grade
- national_account
- national_account_id
- phone
- website
- latitude
- longitude

Note: the API does not expose email addresses or owner/contact names.
"""

import csv
import json
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, fields as dataclass_fields
from typing import Optional
from urllib.parse import urlencode


@dataclass
class LocatorEntry:
    """Represents a single professional directory entry."""
    name: str
    address_line_1: str
    address_line_2: str
    city: str
    state: str
    zip: str
    location: str
    customer_class: str
    loyalty: str
    grade: str
    national_account: str
    national_account_id: str
    phone: str
    website: str
    latitude: str
    longitude: str


class MariniLocatorScraper:
    """Scraper for the Jan Marini locator (bounding-box API with quadtree scan)."""

    API_URL = "https://api.janmarini.com/api/locator/qualified/bounds"

    # The API returns at most this many results per bounding box
    RESULT_CAP = 25

    # Initial bounding box covering the whole map
    WORLD_NW = (85.0, -180.0)
    WORLD_SE = (-85.0, 180.0)

    # Stop subdividing once a tile edge is this small (degrees); accept its
    # results even if capped (e.g. many locations geocoded to one point)
    MIN_TILE_DEG = 0.0005

    MAX_WORKERS = 4
    MAX_RETRIES = 5
    # How many times a tile may be re-queued after exhausting in-call retries
    MAX_TILE_REQUEUES = 3

    OUTPUT_FILE = "marini_locations.csv"

    def __init__(self, debug: bool = False):
        """
        Initialize the scraper.

        Args:
            debug: Save all raw API records to a JSON file.
        """
        self.debug = debug
        self.entries: list[LocatorEntry] = []
        self._raw_by_key: dict[tuple, dict] = {}
        self._request_count = 0

    def _fetch_tile(self, nw: tuple[float, float], se: tuple[float, float]) -> list[dict]:
        """Fetch all locations within one bounding box (NW and SE corners)."""
        params = {
            "northWestLat": f"{nw[0]:.6f}",
            "northWestLong": f"{nw[1]:.6f}",
            "southEastLat": f"{se[0]:.6f}",
            "southEastLong": f"{se[1]:.6f}",
        }
        url = f"{self.API_URL}?{urlencode(params)}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Origin": "https://mariniskinsolutions.com",
                "Referer": "https://mariniskinsolutions.com/",
            },
        )

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    self._request_count += 1
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last_error = e
                # Back off harder when rate-limited
                time.sleep(10 * (attempt + 1) if e.code == 429 else 2 ** attempt)
            except Exception as e:
                last_error = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Tile {nw} -> {se} failed after retries: {last_error}")

    @staticmethod
    def _split_tile(nw: tuple[float, float], se: tuple[float, float]) -> list[tuple]:
        """Split a bounding box into four quadrants."""
        mid_lat = (nw[0] + se[0]) / 2
        mid_lng = (nw[1] + se[1]) / 2
        return [
            (nw, (mid_lat, mid_lng)),                # NW quadrant
            ((nw[0], mid_lng), (mid_lat, se[1])),    # NE quadrant
            ((mid_lat, nw[1]), (se[0], mid_lng)),    # SW quadrant
            ((mid_lat, mid_lng), se),                # SE quadrant
        ]

    @staticmethod
    def _record_key(record: dict) -> tuple:
        """Deduplication key for a raw API record."""
        return (
            (record.get("CustName") or "").strip().lower(),
            (record.get("Line1") or "").strip().lower(),
            (record.get("City") or "").strip().lower(),
            (record.get("State") or "").strip().lower(),
            (record.get("Zip") or "").strip().lower(),
        )

    def scrape(self) -> list[LocatorEntry]:
        """
        Main scraping method. Quadtree-scans the world bounding box until every
        tile is below the API's result cap, then parses the deduplicated set.

        Returns:
            List of LocatorEntry objects.
        """
        print("Scanning Jan Marini locator API (quadtree over map bounds)...")

        frontier = [(self.WORLD_NW, self.WORLD_SE)]
        requeues: dict[tuple, int] = {}
        wave = 0

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            while frontier:
                wave += 1
                futures = {
                    pool.submit(self._fetch_tile, nw, se): (nw, se)
                    for nw, se in frontier
                }
                next_frontier = []

                for future in as_completed(futures):
                    nw, se = futures[future]
                    try:
                        results = future.result()
                    except RuntimeError as e:
                        # Re-queue the failed tile rather than losing its data
                        attempts = requeues.get((nw, se), 0)
                        if attempts < self.MAX_TILE_REQUEUES:
                            requeues[(nw, se)] = attempts + 1
                            next_frontier.append((nw, se))
                            print(f"  Re-queueing failed tile: {e}")
                        else:
                            print(f"  WARNING: giving up on tile: {e}")
                        continue

                    tile_is_tiny = (
                        abs(nw[0] - se[0]) < self.MIN_TILE_DEG
                        or abs(se[1] - nw[1]) < self.MIN_TILE_DEG
                    )

                    if len(results) >= self.RESULT_CAP and not tile_is_tiny:
                        next_frontier.extend(self._split_tile(nw, se))
                    else:
                        for record in results:
                            self._raw_by_key.setdefault(self._record_key(record), record)

                print(
                    f"  Wave {wave}: {len(frontier)} tiles fetched, "
                    f"{len(next_frontier)} need subdivision, "
                    f"{len(self._raw_by_key)} unique locations so far"
                )
                frontier = next_frontier

        print(f"\nDone scanning: {self._request_count} API requests")

        if self.debug:
            with open("debug_marini_records.json", "w", encoding="utf-8") as f:
                json.dump(list(self._raw_by_key.values()), f, indent=2, ensure_ascii=False)
            print("  Saved debug file: debug_marini_records.json")

        for record in self._raw_by_key.values():
            entry = self._parse_record(record)
            if entry:
                self.entries.append(entry)

        self.entries.sort(key=lambda e: (e.state, e.city, e.name))
        print(f"Successfully parsed {len(self.entries)} unique locations")
        return self.entries

    @staticmethod
    def _clean(value) -> str:
        """Normalise a value to a trimmed string ('' for None)."""
        if value is None:
            return ""
        return str(value).strip()

    def _parse_record(self, record: dict) -> Optional[LocatorEntry]:
        """Parse a raw API record into a LocatorEntry."""
        try:
            lat = record.get("Latitude")
            lng = record.get("Longitude")
            return LocatorEntry(
                name=self._clean(record.get("CustName")),
                address_line_1=self._clean(record.get("Line1")),
                address_line_2=self._clean(record.get("Line2")),
                city=self._clean(record.get("City")),
                state=self._clean(record.get("State")),
                zip=self._clean(record.get("Zip")),
                location=self._clean(record.get("Location")),
                customer_class=self._clean(record.get("CustClassID")),
                loyalty=self._clean(record.get("Loyalty")),
                grade=self._clean(record.get("Grade")),
                national_account=self._clean(record.get("NationalAccount")),
                national_account_id=self._clean(record.get("NationalAccountID")),
                phone=self._clean(record.get("Phone")),
                website=self._clean(record.get("Website")),
                # (0, 0) means the record was never geocoded
                latitude="" if not lat else self._clean(lat),
                longitude="" if not lng else self._clean(lng),
            )
        except Exception as e:
            print(f"  Error parsing record {record.get('CustName')}: {e}")
            return None

    def save_to_csv(self, filename: Optional[str] = None) -> str:
        """Save entries to a CSV file."""
        output_file = filename or self.OUTPUT_FILE
        fieldnames = [f.name for f in dataclass_fields(LocatorEntry)]

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in self.entries:
                writer.writerow(asdict(entry))

        print(f"Saved {len(self.entries)} locations to {output_file}")
        return output_file


def main():
    """Main entry point."""
    print("=" * 60)
    print("Jan Marini Skin Solutions Locator Scraper")
    print("=" * 60)

    debug = "--debug" in sys.argv
    if debug:
        print("Debug mode enabled - will save raw API records")

    scraper = MariniLocatorScraper(debug=debug)

    try:
        entries = scraper.scrape()

        if entries:
            print(f"\nFound {len(entries)} locations!")
            scraper.save_to_csv()

            print("\nPreview of extracted data:")
            print("-" * 40)
            for i, entry in enumerate(entries[:5]):
                print(f"\n{i + 1}. {entry.name or '(no name)'}")
                if entry.customer_class:
                    print(f"   Class: {entry.customer_class}")
                if entry.location:
                    print(f"   Address: {entry.location}")
                if entry.phone:
                    print(f"   Phone: {entry.phone}")
                if entry.website:
                    print(f"   Website: {entry.website}")

            if len(entries) > 5:
                print(f"\n... and {len(entries) - 5} more locations")
        else:
            print("\nNo locations found.")

    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
