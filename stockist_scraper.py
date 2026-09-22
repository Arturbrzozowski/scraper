#!/usr/bin/env python3
"""
Stockist.co store locator scraper (shared).

Stockist powers the locators on several of the sites in this repo. This module
holds everything that is the same across them: the two fetch strategies, the
field normalisation, and the CSV writer. Per-site entry points are thin.

Two fetch strategies, because Stockist accounts are configured differently:

  1. Full dump -- GET /api/v1/{tag}/locations/all returns every record in one
     request. This is what CALECIM's account allows.

  2. Geohash sweep -- accounts with the directory feature disabled answer that
     endpoint with {"error": "Method not allowed."} (HTTP 400). Pavise is one.
     For those, /locations/overview.js still works and returns a 9-character
     geohash for every location, which is the map's pin index. Decoding those
     geohashes gives the position of every location, and /locations/search
     returns full records near a point. Searching at each decoded position and
     de-duplicating by id recovers the whole dataset.

     /locations/search caps at 100 results per request regardless of the
     distance parameter, so the sweep shrinks its radius (25 -> 10 -> 4 -> 1
     miles) whenever a response comes back at the cap, and tracks coverage by
     re-encoding each returned record's coordinates back to a geohash.

The widget tag is read from the site's page on each run rather than
hard-coded; callers pass a fallback.

Not run directly -- see calecim_directory_scraper.py and pavise_store_scraper.py.
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

STOCKIST_HOST = "https://stockist.co"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_JSON = "application/json"

FIELDS = [
    "id",
    "name",
    "category",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "postal_code",
    "country",
    "country_raw",
    "phone",
    "email",
    "website",
    "latitude",
    "longitude",
    "priority",
    "data_flags",
]

# --------------------------------------------------------------------------
# Normalisation tables
# --------------------------------------------------------------------------

US_STATE_CODES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA "
    "WV WI WY PR".split()
)
CA_PROVINCE_CODES = set("AB BC MB NB NL NS NT NU ON PE QC SK YT".split())
# Deliberately excludes WA/SA/NT, which collide with US and Canadian codes.
AU_STATE_CODES = set("NSW QLD VIC TAS ACT".split())

COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States", "u.s.": "United States",
    "u.s.a.": "United States", "united states": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "gbr": "United Kingdom",
    "united kingdom": "United Kingdom", "united kingdome": "United Kingdom",
    "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom",
    "au": "Australia", "aus": "Australia", "australia": "Australia",
    "nz": "New Zealand", "new zealand": "New Zealand",
    "sg": "Singapore", "singapore": "Singapore",
    "my": "Malaysia", "malaysia": "Malaysia",
    "ph": "Philippines", "philippines": "Philippines",
    "tw": "Taiwan", "taiwan": "Taiwan",
    "jp": "Japan", "japan": "Japan",
    "vn": "Vietnam", "vietnam": "Vietnam", "viet nam": "Vietnam",
    "th": "Thailand", "thailand": "Thailand",
    "hk": "Hong Kong", "hong kong": "Hong Kong",
    "hong kong & macau": "Hong Kong",
    "ca": "Canada", "can": "Canada", "canada": "Canada",
    "in": "India", "india": "India",
    "fr": "France", "france": "France",
    "de": "Germany", "germany": "Germany",
    "ie": "Ireland", "ireland": "Ireland",
    "gr": "Greece", "greece": "Greece",
    "hu": "Hungary", "hungary": "Hungary",
    "lu": "Luxembourg", "luxembourg": "Luxembourg",
    "no": "Norway", "norway": "Norway",
    "ch": "Switzerland", "switzerland": "Switzerland",
    "za": "South Africa", "south africa": "South Africa",
    "pl": "Poland", "poland": "Poland",
}

# Country-code TLDs used as a last-resort country signal, from the website or
# email domain. Generic and ambiguous TLDs (.com, .net, .co, .io, .me, ...) are
# deliberately absent: they carry no reliable country meaning.
CCTLD_COUNTRIES = {
    "ie": "Ireland", "hu": "Hungary", "pl": "Poland", "au": "Australia",
    "by": "Belarus", "jp": "Japan", "ua": "Ukraine", "ca": "Canada",
    "nz": "New Zealand", "sg": "Singapore", "my": "Malaysia", "ph": "Philippines",
    "tw": "Taiwan", "th": "Thailand", "vn": "Vietnam", "hk": "Hong Kong",
    "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy",
    "nl": "Netherlands", "be": "Belgium", "ch": "Switzerland", "at": "Austria",
    "se": "Sweden", "no": "Norway", "dk": "Denmark", "fi": "Finland",
    "gr": "Greece", "pt": "Portugal", "cz": "Czechia", "sk": "Slovakia",
    "ro": "Romania", "bg": "Bulgaria", "hr": "Croatia", "si": "Slovenia",
    "lt": "Lithuania", "lv": "Latvia", "ee": "Estonia", "is": "Iceland",
    "za": "South Africa", "in": "India", "id": "Indonesia", "kr": "South Korea",
    "cn": "China", "ru": "Russia", "tr": "Turkey", "il": "Israel",
    "ae": "United Arab Emirates", "sa": "Saudi Arabia", "mx": "Mexico",
    "br": "Brazil", "ar": "Argentina", "cl": "Chile", "lu": "Luxembourg",
    "mt": "Malta", "cy": "Cyprus",
}
DOMAIN_RE = re.compile(r"(?:https?://)?(?:www\.)?([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def country_from_domain(*sources: str) -> str:
    """Infer a country from a .uk/.ie/.pl style ccTLD in a URL or email domain."""
    for src in sources:
        src = (src or "").strip().lower()
        if not src:
            continue
        if "@" in src:
            src = src.rsplit("@", 1)[-1]
        m = DOMAIN_RE.search(src)
        if not m:
            continue
        parts = m.group(1).rstrip("/").split(".")
        if len(parts) < 2:
            continue
        tld = parts[-1]
        if tld == "uk":
            return "United Kingdom"
        if tld in CCTLD_COUNTRIES:
            # Skip second-level generics that merely sit under a ccTLD.
            return CCTLD_COUNTRIES[tld]
    return ""


ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
STATE_ZIP_RE = re.compile(r"^([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$")
UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
# e.g. "665,930,009" -- a phone number mangled by thousands separators
COMMA_PHONE_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")
CJK_DISTRICT_RE = re.compile(r"[一-鿿]")
NULL_TOKENS = {"na", "n/a", "none", "null", "-", "--", "tbc", "tba"}


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def is_null_token(value: str) -> bool:
    return value.strip().lower() in NULL_TOKENS


def normalize_country(raw: str, state: str, postal: str,
                     website: str = "", email: str = "") -> tuple[str, str]:
    """Return (country, flag). Infers from state/postal when country is unusable."""
    raw = clean(raw)
    key = raw.lower().strip(" .")
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key], ""
    if raw and not ZIP_RE.fullmatch(raw) and not raw.lower().startswith("http"):
        if key == "europe":
            return "", "country_not_a_country"
        return raw, ""

    # Country is blank, a ZIP, or a URL -- infer it from the region instead.
    st = clean(state)
    st_up = st.upper()
    if st_up in US_STATE_CODES or st.title() in _US_STATE_NAMES:
        return "United States", "country_inferred"
    if st_up in CA_PROVINCE_CODES:
        return "Canada", "country_inferred"
    if st_up in AU_STATE_CODES:
        return "Australia", "country_inferred"
    if CJK_DISTRICT_RE.search(st):
        return "Taiwan", "country_inferred"
    if UK_POSTCODE_RE.fullmatch(clean(postal)):
        return "United Kingdom", "country_inferred"
    from_domain = country_from_domain(website, email)
    if from_domain:
        return from_domain, "country_from_tld"
    return "", ""


_US_STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming", "Puerto Rico",
}


def normalize_record(loc: dict, repair: bool = True) -> dict:
    flags: list[str] = []

    name = clean(loc.get("name"))
    if repair and name != str(loc.get("name") or ""):
        flags.append("name_whitespace")

    city = clean(loc.get("city"))
    state = clean(loc.get("state"))
    postal = clean(loc.get("postal_code"))
    country_raw = clean(loc.get("country"))
    country = country_raw
    website = clean(loc.get("website"))
    phone = clean(loc.get("phone"))
    email = clean(loc.get("email"))

    if repair:
        # A ZIP sitting in the country column, with postal_code left empty.
        if ZIP_RE.fullmatch(country_raw) and not postal:
            postal = country_raw
            flags.append("zip_recovered_from_country")

        # A website sitting in the country column.
        if country_raw.lower().startswith("http"):
            if not website:
                website = country_raw
                flags.append("website_recovered_from_country")
            else:
                flags.append("url_in_country_discarded")

        # postal_code holding "MI 48313" -- split the state back out.
        m = STATE_ZIP_RE.fullmatch(postal)
        if m:
            code = m.group(1).upper()
            if code in US_STATE_CODES:
                if not state or state.title() in _US_STATE_NAMES or state.upper() == code:
                    state = code
                postal = m.group(2)
                flags.append("state_split_from_postal")

        # Phone mangled into thousands-separator form, e.g. "665,930,009".
        if COMMA_PHONE_RE.fullmatch(phone):
            phone = phone.replace(",", "")
            flags.append("phone_comma_stripped")

        for field_name, value in (("phone", phone), ("email", email)):
            if value and is_null_token(value):
                if field_name == "phone":
                    phone = ""
                else:
                    email = ""
                flags.append(f"{field_name}_placeholder_blanked")

        if email and (";" in email or "," in email):
            flags.append("email_multivalue")
        if email and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}", email):
            if email.lower().startswith("http"):
                if not website:
                    website = email
                    flags.append("website_recovered_from_email")
                email = ""
                flags.append("email_was_url")
            elif "email_multivalue" not in flags:
                flags.append("email_malformed")

        country, cflag = normalize_country(country_raw, state, postal, website, email)
        if cflag:
            flags.append(cflag)
        elif country != country_raw:
            flags.append("country_normalized")

    filters = loc.get("filters") or []
    categories = [clean(f.get("name")) for f in filters if isinstance(f, dict)]

    return {
        "id": loc.get("id", ""),
        "name": name,
        "category": "; ".join(c for c in categories if c),
        "address_line_1": clean(loc.get("address_line_1")),
        "address_line_2": clean(loc.get("address_line_2")),
        "city": city,
        "state": state,
        "postal_code": postal,
        "country": country,
        "country_raw": country_raw,
        "phone": phone,
        "email": email,
        "website": website,
        "latitude": loc.get("latitude", ""),
        "longitude": loc.get("longitude", ""),
        "priority": loc.get("priority") or "",
        "data_flags": "; ".join(flags),
    }


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def http_get(url: str, referer: str | None = None, accept: str = ACCEPT_JSON) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} records to {path}")


def summarize(rows: list[dict]) -> None:
    total = len(rows)
    print("\nField coverage:")
    for field in FIELDS:
        filled = sum(1 for r in rows if str(r.get(field, "")).strip())
        print(f"  {field}: {filled}/{total}")

    def tally(key):
        out: dict[str, int] = {}
        for r in rows:
            out[r[key] or "(blank)"] = out.get(r[key] or "(blank)", 0) + 1
        return sorted(out.items(), key=lambda kv: -kv[1])

    print("\nBy category:")
    for c, n in tally("category"):
        print(f"  {c}: {n}")
    print("\nBy country (top 15):")
    for c, n in tally("country")[:15]:
        print(f"  {c}: {n}")

    flags: dict[str, int] = {}
    for r in rows:
        for fl in filter(None, r["data_flags"].split("; ")):
            flags[fl] = flags.get(fl, 0) + 1
    if flags:
        print("\nRepairs applied:")
        for fl, n in sorted(flags.items(), key=lambda kv: -kv[1]):
            print(f"  {fl}: {n}")


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def http_get(url: str, referer: str | None = None, accept: str = ACCEPT_JSON) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def http_get_json(url: str, referer: str | None = None, retries: int = 3):
    """GET and parse JSON, retrying transient failures with a backoff."""
    for attempt in range(retries):
        try:
            return json.loads(http_get(url, referer=referer))
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def find_widget_tag(page_url: str, fallback: str) -> str:
    """Read the Stockist widget tag out of a store-locator page."""
    print(f"Fetching page: {page_url}")
    try:
        html = http_get(page_url, accept=ACCEPT_HTML).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Failed to fetch page ({e}), using fallback widget tag")
        return fallback

    m = re.search(r'data-stockist-widget-tag="([A-Za-z0-9_-]+)"', html)
    if m:
        print(f"  Found Stockist widget tag: {m.group(1)}")
        return m.group(1)
    print("  Widget tag not found in page source, using fallback")
    return fallback


def fetch_all_locations(tag: str, referer: str) -> list[dict] | None:
    """Strategy 1: the full-dump endpoint. Returns None if it is disabled."""
    url = f"{STOCKIST_HOST}/api/v1/{tag}/locations/all"
    print(f"Trying full dump: {url}")
    try:
        data = http_get_json(url, referer=referer)
    except urllib.error.HTTPError as e:
        if e.code in (400, 403, 404, 405):
            print(f"  Full dump unavailable for this account (HTTP {e.code})")
            return None
        raise
    if isinstance(data, dict) and data.get("error"):
        print(f"  Full dump unavailable for this account: {data['error']}")
        return None
    if not isinstance(data, list):
        print(f"  Unexpected full-dump payload: {type(data).__name__}")
        return None
    print(f"  Retrieved {len(data)} locations in one request")
    return data


# --- geohash ---------------------------------------------------------------

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_decode(gh: str) -> tuple[float, float]:
    lat, lon, even = (-90.0, 90.0), (-180.0, 180.0), True
    for ch in gh:
        idx = _B32.index(ch)
        for mask in (16, 8, 4, 2, 1):
            if even:
                mid = (lon[0] + lon[1]) / 2
                lon = (mid, lon[1]) if idx & mask else (lon[0], mid)
            else:
                mid = (lat[0] + lat[1]) / 2
                lat = (mid, lat[1]) if idx & mask else (lat[0], mid)
            even = not even
    return (lat[0] + lat[1]) / 2, (lon[0] + lon[1]) / 2


def geohash_encode(lat: float, lon: float, precision: int = 9) -> str:
    latr, lonr = (-90.0, 90.0), (-180.0, 180.0)
    even, bit, chunk, out = True, 0, 0, []
    while len(out) < precision:
        if even:
            mid = (lonr[0] + lonr[1]) / 2
            if lon > mid:
                chunk = (chunk << 1) | 1
                lonr = (mid, lonr[1])
            else:
                chunk <<= 1
                lonr = (lonr[0], mid)
        else:
            mid = (latr[0] + latr[1]) / 2
            if lat > mid:
                chunk = (chunk << 1) | 1
                latr = (mid, latr[1])
            else:
                chunk <<= 1
                latr = (latr[0], mid)
        even = not even
        bit += 1
        if bit == 5:
            out.append(_B32[chunk])
            bit, chunk = 0, 0
    return "".join(out)


SEARCH_RESULT_CAP = 100
SWEEP_RADII = (25, 10, 4, 1)


def search_locations(tag: str, lat: float, lon: float, distance: int,
                     referer: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "tag": tag,
        "latitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "distance": distance,
    })
    url = f"{STOCKIST_HOST}/api/v1/{tag}/locations/search?{params}"
    payload = http_get_json(url, referer=referer)
    return payload.get("locations") or []


def fetch_via_geohash_sweep(tag: str, referer: str, delay: float = 0.25) -> list[dict]:
    """Strategy 2: enumerate via the map's geohash index, then search each point."""
    url = f"{STOCKIST_HOST}/api/v1/{tag}/locations/overview.js"
    print(f"Falling back to geohash sweep via {url}")
    overview = http_get_json(url, referer=referer)
    entries = overview.get("i") or []
    targets = {e.split(":")[0] for e in entries if e}
    print(f"  Overview lists {len(entries)} pins across {len(targets)} distinct geohashes")

    points = {gh: geohash_decode(gh) for gh in targets}
    found: dict[str, dict] = {}
    covered: set[str] = set()
    requests_made = 0

    for gh in sorted(points):
        if gh in covered:
            continue
        lat, lon = points[gh]
        locations: list[dict] = []
        for radius in SWEEP_RADII:
            locations = search_locations(tag, lat, lon, radius, referer)
            requests_made += 1
            if len(locations) < SEARCH_RESULT_CAP:
                break
        else:
            print(f"  WARNING: still at the {SEARCH_RESULT_CAP}-result cap at "
                  f"{lat:.4f},{lon:.4f}; some records there may be missed")

        for loc in locations:
            found[loc["id"]] = loc
            try:
                covered.add(geohash_encode(float(loc["latitude"]),
                                           float(loc["longitude"])))
            except (TypeError, ValueError):
                pass
        covered.add(gh)
        if len(found) % 200 == 0:
            print(f"  {len(found)} found / {requests_made} requests")
        time.sleep(delay)

    uncovered = [gh for gh in points if gh not in covered]
    print(f"  Sweep complete: {len(found)} unique locations in {requests_made} requests")
    print(f"  Overview pins: {len(entries)}; geohashes never matched by a result: "
          f"{len(uncovered)}")
    if len(found) < len(entries):
        print(f"  NOTE: {len(entries) - len(found)} fewer records than overview pins. "
              "Pins can share a geohash, so some difference is expected.")
    return list(found.values())


def fetch_locations(tag: str, referer: str, force_sweep: bool = False,
                    delay: float = 0.25) -> list[dict]:
    """Full dump when the account allows it, geohash sweep when it does not."""
    if not force_sweep:
        data = fetch_all_locations(tag, referer)
        if data:
            return data
    return fetch_via_geohash_sweep(tag, referer, delay=delay)



# --------------------------------------------------------------------------
# Entry point shared by the per-site scrapers
# --------------------------------------------------------------------------

def run(page_url: str, fallback_tag: str, default_output: str,
        description: str, argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("-o", "--output", default=default_output, help="CSV output path")
    ap.add_argument("--raw-json", help="also save the raw API payload to this path")
    ap.add_argument("--no-repair", action="store_true",
                    help="write source values verbatim, without normalisation")
    ap.add_argument("--force-sweep", action="store_true",
                    help="skip the full-dump endpoint and always sweep")
    ap.add_argument("--delay", type=float, default=0.25,
                    help="seconds between sweep requests (default 0.25)")
    args = ap.parse_args(argv)

    tag = find_widget_tag(page_url, fallback_tag)
    try:
        locations = fetch_locations(tag, page_url,
                                    force_sweep=args.force_sweep, delay=args.delay)
    except Exception as e:
        print(f"ERROR: failed to fetch locations: {e}")
        return 1
    if not locations:
        print("ERROR: no locations returned")
        return 1

    if args.raw_json:
        with open(args.raw_json, "w", encoding="utf-8") as f:
            json.dump(locations, f, indent=2, ensure_ascii=False)
        print(f"Saved raw payload to {args.raw_json}")

    rows = [normalize_record(loc, repair=not args.no_repair) for loc in locations]
    rows.sort(key=lambda r: r["name"].lower())
    write_csv(rows, args.output)
    summarize(rows)
    return 0
