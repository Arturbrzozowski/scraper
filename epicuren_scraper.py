#!/usr/bin/env python3
"""
Scraper for Epicuren Discovery spa locations (https://epicuren.com/pages/locate-spa).

The page embeds a Stockist.co widget (tag u3402). Its search API returns at most
25 locations within at most 250 miles of a point, so this script sweeps a
worldwide grid of 250-mile circles. Any circle that returns the full 25 results
is split into smaller circles until no search is saturated. Results are
deduplicated by Stockist location id and saved to CSV.
"""

import csv
import json
import math
import time
import urllib.parse
import urllib.request

TAG = "u3402"
API_URL = f"https://stockist.co/api/v1/{TAG}/locations/search"
OUTPUT_FILE = "epicuren_spas.csv"
MAX_RESULTS = 25          # server-side cap per search
MAX_RADIUS_MI = 250       # server-side cap on distance
MIN_RADIUS_MI = 2         # stop subdividing below this
DELAY_S = 1.0             # politeness delay between requests
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
    "filters",
    "custom_fields",
]

_request_count = 0


def search(lat, lng, radius):
    """Query the Stockist search endpoint for one circle."""
    global _request_count
    params = urllib.parse.urlencode(
        {"latitude": f"{lat:.5f}", "longitude": f"{lng:.5f}", "distance": radius}
    )
    req = urllib.request.Request(f"{API_URL}?{params}", headers={"Accept": "application/json",
                                                          "User-Agent": "epicuren-scraper/1.0"})
    for attempt in range(4):
        try:
            time.sleep(DELAY_S)
            _request_count += 1
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8")).get("locations", [])
        except Exception as exc:  # network hiccup / rate limit: back off and retry
            wait = 2 ** (attempt + 1)
            print(f"  error at ({lat:.2f},{lng:.2f}) r={radius}: {exc}; retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed search at ({lat}, {lng}) r={radius}")


def grid_points(radius):
    """Square grid whose circles of `radius` miles cover the globe (lat -60..75)."""
    spacing = radius * math.sqrt(2)  # half-diagonal == radius -> full coverage
    dlat = spacing / EARTH_MI_PER_DEG_LAT
    lat = -60.0
    while lat <= 75.0 + dlat:
        lat_c = min(lat, 89.0)
        mi_per_deg_lng = EARTH_MI_PER_DEG_LAT * max(math.cos(math.radians(lat_c)), 0.05)
        dlng = spacing / mi_per_deg_lng
        n = max(1, math.ceil(360.0 / dlng))
        for i in range(n):
            yield lat_c, -180.0 + (i + 0.5) * 360.0 / n
        lat += dlat


def sweep_circle(lat, lng, radius, found, depth=0):
    """Search a circle; subdivide if the result list was capped."""
    locs = search(lat, lng, radius)
    new = 0
    for loc in locs:
        if loc["id"] not in found:
            found[loc["id"]] = loc
            new += 1
    if locs:
        print(f"{'  ' * depth}({lat:7.2f},{lng:8.2f}) r={radius:<4} -> {len(locs):2d} results, "
              f"{new} new, total {len(found)}")
    if len(locs) >= MAX_RESULTS and radius > MIN_RADIUS_MI:
        sub_r = radius / 2
        spacing = sub_r * math.sqrt(2)
        dlat = spacing / EARTH_MI_PER_DEG_LAT
        dlng = spacing / (EARTH_MI_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.05))
        steps = math.ceil(radius / spacing)
        for i in range(-steps, steps + 1):
            for j in range(-steps, steps + 1):
                sl, sg = lat + i * dlat, lng + j * dlng
                # skip sub-circles entirely outside the parent circle
                dy = (sl - lat) * EARTH_MI_PER_DEG_LAT
                dx = (sg - lng) * EARTH_MI_PER_DEG_LAT * math.cos(math.radians(lat))
                if math.hypot(dx, dy) - sub_r > radius:
                    continue
                sweep_circle(sl, sg, sub_r, found, depth + 1)


def save_to_csv(locations, filename):
    rows = []
    for loc in sorted(locations, key=lambda l: (l.get("country") or "", l.get("state") or "",
                                                l.get("city") or "", l.get("name") or "")):
        row = dict(loc)
        for key in ("filters", "custom_fields"):
            row[key] = json.dumps(row.get(key) or [])
        rows.append(row)
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} locations to {filename}")


def main():
    found = {}
    points = list(grid_points(MAX_RADIUS_MI))
    print(f"Sweeping {len(points)} grid points at r={MAX_RADIUS_MI} mi...")
    for k, (lat, lng) in enumerate(points, 1):
        if k % 100 == 0:
            print(f"-- {k}/{len(points)} points, {len(found)} locations, {_request_count} requests")
        sweep_circle(lat, lng, MAX_RADIUS_MI, found)
    with_email = sum(1 for l in found.values() if l.get("email"))
    print(f"Done: {len(found)} unique locations ({with_email} with email), {_request_count} requests")
    save_to_csv(found.values(), OUTPUT_FILE)


if __name__ == "__main__":
    main()
