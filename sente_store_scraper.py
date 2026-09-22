#!/usr/bin/env python3
"""
Sente Labs Store Locator Scraper

Extracts stockist/clinic data from the Sente Labs store locator at
https://sentelabs.com/pages/store-locator

The page embeds a Closeby (closeby.co) locator widget. Unlike the Cyspera
locator, this one does have a real API, but it is not radius-based: a single
unauthenticated GET to

    https://www.closeby.co/embed/{map_key}/locations

returns every location in one response (`is_limited_results: false`), so no
city sweep, pagination or browser automation is needed.

The widget also exposes a per-location detail endpoint, /locations/{id}.
Sampling shows it returns no fields beyond those already in the list payload
for this map, so it is only queried when --details is passed.

Usage:
    python sente_store_scraper.py
    python sente_store_scraper.py --details   # also hit /locations/{id} per row
    python sente_store_scraper.py --raw-json out.json
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request

PAGE_URL = "https://sentelabs.com/pages/store-locator"
CLOSEBY_HOST = "https://www.closeby.co"
# Fallback if the map key can no longer be read from the page
FALLBACK_MAP_KEY = "2e658a27294cde0b092c16380ff14426"
OUTPUT_FILE = "sente_stores.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FIELDS = [
    "id",
    "title",
    "address_full",
    "city",
    "state",
    "zip_code",
    "country",
    "phone_number",
    "email",
    "website",
    "latitude",
    "longitude",
    "short_description",
    "categories",
    "hours",
    "status",
    "slug",
    "updated_at",
]

# --------------------------------------------------------------------------
# Address parsing
#
# Closeby stores only a single free-text `address_full`. Most records are
# US addresses in "Street, City, State ZIP" form, so city/state/ZIP can be
# recovered. Note that ZIP codes in the source have lost their leading zero
# (Massachusetts "02115" is stored as "2115"), which is repaired below.
# --------------------------------------------------------------------------

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "Puerto Rico": "PR",
}
STATE_LOOKUP = {k.lower(): v for k, v in STATES.items()}
STATE_LOOKUP.update({v.lower(): v for v in STATES.values()})
_STATE_ALT = "|".join(
    re.escape(s)
    for s in sorted(list(STATES) + list(STATES.values()), key=len, reverse=True)
)

_CITY = r"(?P<city>[A-Za-z][A-Za-z .'\-/]*?)"
# Anchored at the end of the string: the normal, well-formed case.
US_END_RE = re.compile(
    rf"(?:^|[,\s]){_CITY}\s*,?\s+(?P<state>{_STATE_ALT})"
    rf"\s*,?\s+(?P<zip>\d{{3,5}}(?:-\d{{4}})?)\s*$",
    re.IGNORECASE,
)
# Unanchored: rescues records with a duplicated or trailing junk tail,
# e.g. "1950 E Greenway Dr Tempe, AZ 85282, , Arizona 85282".
US_ANY_RE = re.compile(
    rf"(?:^|[,\s]){_CITY}\s*,\s*(?P<state>{_STATE_ALT})"
    rf"\s+(?P<zip>\d{{3,5}}(?:-\d{{4}})?)\b",
    re.IGNORECASE,
)
# No ZIP at all, e.g. "..., Portland, Maine".
US_NOZIP_RE = re.compile(
    rf"(?:^|[,\s]){_CITY}\s*,\s*(?P<state>{_STATE_ALT})\s*,?\s*$",
    re.IGNORECASE,
)

# Matched as whole words against the address to label non-US records.
COUNTRY_HINTS = [
    ("Vietnam", "Vietnam"), ("Viet Nam", "Vietnam"), ("Ho Chi Minh", "Vietnam"),
    ("Binh Duong", "Vietnam"),
    ("Thailand", "Thailand"), ("Bangkok", "Thailand"), ("Subdistrict", "Thailand"),
    ("Ireland", "Ireland"),
    ("United Kingdom", "United Kingdom"), ("UK", "United Kingdom"),
    ("England", "United Kingdom"), ("Scotland", "United Kingdom"),
    ("Wales", "United Kingdom"), ("London", "United Kingdom"),
    ("Canada", "Canada"), ("British Columbia", "Canada"), ("Ontario", "Canada"),
    ("Alberta", "Canada"), ("Quebec", "Canada"),
    ("Australia", "Australia"), ("Singapore", "Singapore"), ("Malaysia", "Malaysia"),
    ("Philippines", "Philippines"), ("Indonesia", "Indonesia"), ("Japan", "Japan"),
    ("Mexico", "Mexico"), ("Spain", "Spain"), ("France", "France"),
    ("Germany", "Germany"), ("Italy", "Italy"), ("Greece", "Greece"),
    ("Switzerland", "Switzerland"), ("Austria", "Austria"),
    ("Netherlands", "Netherlands"), ("India", "India"), ("China", "China"),
    ("Taiwan", "Taiwan"), ("Hong Kong", "Hong Kong"), ("Korea", "South Korea"),
    ("New Zealand", "New Zealand"), ("Brazil", "Brazil"),
    ("UAE", "United Arab Emirates"), ("Dubai", "United Arab Emirates"),
    ("Saudi", "Saudi Arabia"), ("Qatar", "Qatar"), ("Turkey", "Turkey"),
    ("Poland", "Poland"), ("Portugal", "Portugal"), ("Sweden", "Sweden"),
    ("Norway", "Norway"), ("Denmark", "Denmark"), ("Finland", "Finland"),
    ("Belgium", "Belgium"),
]
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)


def normalize_address(addr: str) -> str:
    a = re.sub(r"\s+", " ", (addr or "").strip())
    a = re.sub(r"(?:,\s*)+,", ",", a)  # collapse ", ," artifacts
    a = re.sub(r",\s*(?:USA|U\.S\.A\.|United States)\s*$", "", a, flags=re.IGNORECASE)
    return a.strip().rstrip(",").strip()


def pad_zip(z: str) -> str:
    """Restore leading zeros stripped by the source (e.g. 2115 -> 02115)."""
    if not z:
        return ""
    head, _, plus4 = z.partition("-")
    head = head.zfill(5)
    return f"{head}-{plus4}" if plus4 else head


def parse_address(addr: str) -> tuple[str, str, str, str]:
    """Return (city, state, zip_code, country) parsed from a free-text address."""
    a = normalize_address(addr)
    for rx in (US_END_RE, US_ANY_RE, US_NOZIP_RE):
        m = rx.search(a)
        if m:
            state = STATE_LOOKUP.get(m.group("state").lower(), "")
            zip_code = pad_zip(m.groupdict().get("zip") or "")
            return m.group("city").strip().title(), state, zip_code, "United States"

    low = a.lower()
    for needle, country in COUNTRY_HINTS:
        if re.search(r"\b" + re.escape(needle.lower()) + r"\b", low):
            return "", "", "", country
    if UK_POSTCODE_RE.search(a):
        return "", "", "", "United Kingdom"
    return "", "", "", ""


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_JSON = "application/json"


def http_get(url: str, referer: str | None = None, accept: str = ACCEPT_JSON) -> bytes:
    """GET a URL.

    The Accept header matters: Shopify varies on it, and asking for JSON on a
    storefront page returns the page metadata API instead of the rendered HTML
    the locator widget lives in.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def find_map_key() -> str:
    """Read the Closeby map key out of the Sente Labs page."""
    print(f"Fetching page: {PAGE_URL}")
    try:
        html = http_get(PAGE_URL, accept=ACCEPT_HTML).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Failed to fetch page ({e}), using fallback map key")
        return FALLBACK_MAP_KEY

    m = re.search(r'window\.closeby\s*=\s*\{\s*mapKey:\s*"([0-9a-f]+)"', html)
    if not m:
        m = re.search(r'closeby-embed-([0-9a-f]{16,})', html)
    if m:
        print(f"  Found Closeby map key: {m.group(1)}")
        return m.group(1)

    print("  Map key not found in page source, using fallback")
    return FALLBACK_MAP_KEY


def fetch_locations(map_key: str) -> dict:
    url = f"{CLOSEBY_HOST}/embed/{map_key}/locations"
    print(f"Fetching locations: {url}")
    payload = json.loads(http_get(url, referer=f"{CLOSEBY_HOST}/embed/{map_key}"))
    locs = payload.get("locations") or []
    print(
        f"  Retrieved {len(locs)} locations "
        f"(total_count={payload.get('total_count')}, "
        f"is_limited_results={payload.get('is_limited_results')})"
    )
    if payload.get("is_limited_results"):
        print("  WARNING: API reports limited results; the dump may be incomplete.")
    return payload


def fetch_detail(location_id: int, map_key: str) -> dict:
    url = f"{CLOSEBY_HOST}/locations/{location_id}"
    try:
        data = json.loads(http_get(url, referer=f"{CLOSEBY_HOST}/embed/{map_key}"))
        return data.get("location") or {}
    except Exception as e:
        print(f"  detail fetch failed for {location_id}: {e}")
        return {}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def format_hours(location_hours) -> str:
    if not location_hours:
        return ""
    parts = []
    for h in location_hours:
        if not isinstance(h, dict):
            continue
        day = h.get("day") or h.get("day_of_week") or ""
        opens, closes = h.get("opens_at") or "", h.get("closes_at") or ""
        parts.append(f"{day} {opens}-{closes}".strip())
    return "; ".join(p for p in parts if p)


def to_row(loc: dict) -> dict:
    city, state, zip_code, country = parse_address(loc.get("address_full", ""))
    cats = loc.get("categories") or []
    cat_names = [
        c.get("name", "") if isinstance(c, dict) else str(c) for c in cats
    ]
    return {
        "id": loc.get("id", ""),
        "title": loc.get("title", ""),
        "address_full": normalize_address(loc.get("address_full", "")),
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "country": country,
        "phone_number": loc.get("phone_number") or "",
        "email": loc.get("email") or "",
        "website": loc.get("website") or "",
        "latitude": loc.get("latitude", ""),
        "longitude": loc.get("longitude", ""),
        "short_description": loc.get("short_description") or "",
        "categories": "; ".join(n for n in cat_names if n),
        "hours": format_hours(loc.get("location_hours")),
        "status": loc.get("status") or "",
        "slug": loc.get("slug") or "",
        "updated_at": loc.get("updated_at") or "",
    }


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} stores to {path}")


def summarize(rows: list[dict]) -> None:
    total = len(rows)
    countries: dict[str, int] = {}
    states: dict[str, int] = {}
    for r in rows:
        countries[r["country"] or "(unresolved)"] = countries.get(r["country"] or "(unresolved)", 0) + 1
        if r["state"]:
            states[r["state"]] = states.get(r["state"], 0) + 1

    print("\nBy country:")
    for c, n in sorted(countries.items(), key=lambda kv: -kv[1]):
        print(f"  {c}: {n}")
    print("\nTop US states:")
    for s, n in sorted(states.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {s}: {n}")
    print("\nField coverage:")
    for field in FIELDS:
        filled = sum(1 for r in rows if str(r.get(field, "")).strip())
        print(f"  {field}: {filled}/{total}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape the Sente Labs store locator")
    ap.add_argument("-o", "--output", default=OUTPUT_FILE, help="CSV output path")
    ap.add_argument("--raw-json", help="also save the raw API payload to this path")
    ap.add_argument(
        "--details",
        action="store_true",
        help="additionally GET /locations/{id} per store (slow; adds no fields "
             "for this map as of the last check)",
    )
    ap.add_argument("--delay", type=float, default=0.3,
                    help="seconds between detail requests (default 0.3)")
    args = ap.parse_args()

    map_key = find_map_key()
    try:
        payload = fetch_locations(map_key)
    except Exception as e:
        print(f"ERROR: failed to fetch locations: {e}")
        return 1

    locations = payload.get("locations") or []
    if not locations:
        print("ERROR: API returned no locations")
        return 1

    if args.raw_json:
        with open(args.raw_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Saved raw payload to {args.raw_json}")

    if args.details:
        print(f"Fetching per-location details for {len(locations)} stores...")
        for i, loc in enumerate(locations, 1):
            detail = fetch_detail(loc["id"], map_key)
            for k, v in detail.items():
                if v not in (None, "", [], {}):
                    loc[k] = v
            if i % 50 == 0:
                print(f"  {i}/{len(locations)}")
            time.sleep(args.delay)

    rows = [to_row(loc) for loc in locations]
    write_csv(rows, args.output)
    summarize(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
