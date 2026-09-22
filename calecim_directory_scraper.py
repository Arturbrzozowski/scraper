#!/usr/bin/env python3
"""
CALECIM Professional Pro Directory Scraper

Extracts clinic/salon data from the CALECIM Professional pro directory at
https://calecimprofessional.com/pages/pro-directory

The page embeds a Stockist.co widget. Stockist publishes a full-dump endpoint,
so one unauthenticated request returns every location:

    https://stockist.co/api/v1/{widget_tag}/locations/all

The widget's other two endpoints add nothing: /locations/search returns the
same records plus a `distance` relative to a query point, and
/locations/overview.js is a geohash index used to draw the map.

Unlike the Cyspera and Sente locators, this source has structured address
fields and real contact data. It is also the dirtiest of the three, so this
scraper repairs several source defects and records what it changed in a
`data_flags` column. See README.md for the full list.

Usage:
    python calecim_directory_scraper.py
    python calecim_directory_scraper.py --raw-json calecim_raw.json
    python calecim_directory_scraper.py --no-repair   # emit source values as-is
"""

import argparse
import csv
import json
import re
import sys
import urllib.request

PAGE_URL = "https://calecimprofessional.com/pages/pro-directory"
STOCKIST_HOST = "https://stockist.co"
FALLBACK_WIDGET_TAG = "u7465"
OUTPUT_FILE = "calecim_directory.csv"

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


def find_widget_tag() -> str:
    """Read the Stockist widget tag out of the directory page."""
    print(f"Fetching page: {PAGE_URL}")
    try:
        html = http_get(PAGE_URL, accept=ACCEPT_HTML).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Failed to fetch page ({e}), using fallback widget tag")
        return FALLBACK_WIDGET_TAG

    m = re.search(r'data-stockist-widget-tag="([A-Za-z0-9_-]+)"', html)
    if m:
        print(f"  Found Stockist widget tag: {m.group(1)}")
        return m.group(1)
    print("  Widget tag not found in page source, using fallback")
    return FALLBACK_WIDGET_TAG


def fetch_all_locations(tag: str) -> list[dict]:
    url = f"{STOCKIST_HOST}/api/v1/{tag}/locations/all"
    print(f"Fetching locations: {url}")
    data = json.loads(http_get(url, referer=PAGE_URL))
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")
    print(f"  Retrieved {len(data)} locations")
    return data


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape the CALECIM pro directory")
    ap.add_argument("-o", "--output", default=OUTPUT_FILE, help="CSV output path")
    ap.add_argument("--raw-json", help="also save the raw API payload to this path")
    ap.add_argument("--no-repair", action="store_true",
                    help="write source values verbatim, without normalisation")
    args = ap.parse_args()

    tag = find_widget_tag()
    try:
        locations = fetch_all_locations(tag)
    except Exception as e:
        print(f"ERROR: failed to fetch locations: {e}")
        return 1
    if not locations:
        print("ERROR: API returned no locations")
        return 1

    if args.raw_json:
        with open(args.raw_json, "w", encoding="utf-8") as f:
            json.dump(locations, f, indent=2, ensure_ascii=False)
        print(f"Saved raw payload to {args.raw_json}")

    rows = [normalize_record(loc, repair=not args.no_repair) for loc in locations]
    write_csv(rows, args.output)
    summarize(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
