#!/usr/bin/env python3
"""
Generic scraper for store locators built on the Stockist.co widget.

Stockist's search API returns at most `max_results` locations (nearest first)
within at most `max_radius` miles of a point. This module sweeps a worldwide
grid of circles; any circle that returns a full page of results is split into
smaller circles until no search is saturated. Locations are deduplicated by
Stockist id and written to CSV.

Usage:
    python stockist_scraper.py <widget_tag> <output.csv> [--max-results N] [--max-radius MI]
"""

import argparse
import csv
import json
import math
import time
import urllib.parse
import urllib.request

USER_AGENT = "stockist-scraper/1.0"  # Python's default UA is rejected with 403
EARTH_MI_PER_DEG_LAT = 69.0

COLUMNS = [
    "id",
    "name",
    "email",
    "phone",
    "website",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postal_code",
    "country",
    "full_address",
    "latitude",
    "longitude",
    "description",
    "image_url",
    "priority",
    "filter_names",
    "filters",
    "custom_fields",
]


class StockistScraper:
    def __init__(self, tag, max_results=25, max_radius=250, min_radius=1.0, delay=1.0):
        self.api_url = f"https://stockist.co/api/v1/{tag}/locations/search"
        self.max_results = max_results
        self.max_radius = max_radius
        self.min_radius = min_radius
        self.delay = delay
        self.requests = 0
        self.found = {}

    def search(self, lat, lng, radius):
        params = urllib.parse.urlencode(
            {"latitude": f"{lat:.5f}", "longitude": f"{lng:.5f}", "distance": f"{radius:g}"}
        )
        req = urllib.request.Request(
            f"{self.api_url}?{params}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        for attempt in range(4):
            try:
                time.sleep(self.delay)
                self.requests += 1
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8")).get("locations", [])
            except Exception as exc:
                wait = 2 ** (attempt + 1)
                print(f"  error at ({lat:.2f},{lng:.2f}) r={radius:g}: {exc}; retry in {wait}s")
                time.sleep(wait)
        raise RuntimeError(f"Failed search at ({lat}, {lng}) r={radius}")

    @staticmethod
    def _mi_per_deg_lng(lat):
        return EARTH_MI_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.05)

    def grid_points(self, radius):
        """Square grid whose circles of `radius` miles cover lat -60..75."""
        spacing = radius * math.sqrt(2)  # half-diagonal == radius -> full coverage
        dlat = spacing / EARTH_MI_PER_DEG_LAT
        lat = -60.0
        while lat <= 75.0 + dlat:
            lat_c = min(lat, 89.0)
            n = max(1, math.ceil(360.0 / (spacing / self._mi_per_deg_lng(lat_c))))
            for i in range(n):
                yield lat_c, -180.0 + (i + 0.5) * 360.0 / n
            lat += dlat

    def sweep_circle(self, lat, lng, radius, depth=0):
        locs = self.search(lat, lng, radius)
        new = 0
        for loc in locs:
            if loc["id"] not in self.found:
                self.found[loc["id"]] = loc
                new += 1
        if locs:
            print(f"{'  ' * depth}({lat:7.2f},{lng:8.2f}) r={radius:g} -> {len(locs)} results, "
                  f"{new} new, total {len(self.found)}")
        if len(locs) >= self.max_results and radius > self.min_radius:
            sub_r = radius / 2
            spacing = sub_r * math.sqrt(2)
            dlat = spacing / EARTH_MI_PER_DEG_LAT
            dlng = spacing / self._mi_per_deg_lng(lat)
            steps = math.ceil(radius / spacing)
            for i in range(-steps, steps + 1):
                for j in range(-steps, steps + 1):
                    sl, sg = lat + i * dlat, lng + j * dlng
                    dy = (sl - lat) * EARTH_MI_PER_DEG_LAT
                    dx = (sg - lng) * self._mi_per_deg_lng(lat)
                    if math.hypot(dx, dy) - sub_r > radius:
                        continue  # sub-circle entirely outside parent
                    self.sweep_circle(sl, sg, sub_r, depth + 1)

    def run(self, start_radius=None):
        radius = min(start_radius or self.max_radius, self.max_radius)
        points = list(self.grid_points(radius))
        print(f"Sweeping {len(points)} grid points at r={radius:g} mi...")
        for k, (lat, lng) in enumerate(points, 1):
            if k % 25 == 0:
                print(f"-- {k}/{len(points)} points, {len(self.found)} locations, "
                      f"{self.requests} requests")
            self.sweep_circle(lat, lng, radius)
        with_email = sum(1 for l in self.found.values() if l.get("email"))
        print(f"Done: {len(self.found)} unique locations ({with_email} with email), "
              f"{self.requests} requests")
        return list(self.found.values())


def save_to_csv(locations, filename):
    rows = []
    for loc in sorted(locations, key=lambda l: (l.get("country") or "", l.get("state") or "",
                                                l.get("city") or "", l.get("name") or "")):
        row = dict(loc)
        row["filter_names"] = "; ".join(f.get("name", "") for f in (loc.get("filters") or []))
        for key in ("filters", "custom_fields"):
            row[key] = json.dumps(row.get(key) or [], ensure_ascii=False)
        rows.append(row)
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} locations to {filename}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag", help="Stockist widget tag, e.g. u3402 or map_9q946n43")
    ap.add_argument("output", help="CSV file to write")
    ap.add_argument("--max-results", type=int, default=25, help="per-search result cap (widget max_results)")
    ap.add_argument("--max-radius", type=float, default=250, help="server distance cap in miles")
    ap.add_argument("--start-radius", type=float, default=None, help="initial grid circle radius")
    args = ap.parse_args()
    scraper = StockistScraper(args.tag, args.max_results, args.max_radius)
    save_to_csv(scraper.run(args.start_radius), args.output)


if __name__ == "__main__":
    main()
