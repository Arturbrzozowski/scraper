#!/usr/bin/env python3
"""
Scraper for iS Clinical professional locations
(https://www.isclinical.com/pages/find-a-professional).

The page embeds a Storepoint widget (id 1689cd98fb7dd2). Storepoint serves every
location for a widget in a single public JSON response, so one request gets all
records. The free-text address is split into street / city / state / zip, and
`is_usa` flags US locations.
"""

import csv
import json
import re
import urllib.request

WIDGET_ID = "1689cd98fb7dd2"
API_URL = f"https://api.storepoint.co/v1/{WIDGET_ID}/locations"
OUTPUT_FILE = "isclinical_professionals.csv"
USER_AGENT = "stockist-scraper/1.0"

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands",
}
STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

# Emails on the brand's own domain (Innovative Skincare) are placeholders or
# rep/staff addresses, not the clinic's own contact.
BRAND_EMAIL_DOMAIN = "myinnovativeskincare.com"
# Internal records: staff ("iS Lastname, First"), departments and test entries.
INTERNAL_NAME = re.compile(r"^(iS\s|INT\s|INTNL\s)|tester", re.IGNORECASE)

COLUMNS = [
    "id", "public_id", "name", "email", "phone", "website",
    "brand_email", "likely_internal",
    "streetaddress", "street", "city", "state", "zip", "country_guess", "is_usa",
    "loc_lat", "loc_long", "tags", "description",
    "custom_tdeut9eu61", "custom_07irkz7nir", "custom_fields",
    "facebook", "instagram", "twitter", "image_url", "priority",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "extra", "extra2", "extra3",
]


def fetch_locations():
    print(f"Fetching {API_URL} ...")
    req = urllib.request.Request(API_URL, headers={"Accept": "application/json",
                                                   "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    locs = data["results"]["locations"]
    print(f"Found {len(locs)} locations")
    return locs


def parse_address(addr):
    """Split 'street,city,ST 12345' into parts; best effort for messy rows."""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    if parts and parts[-1].upper() in ("US", "USA", "UNITED STATES"):
        parts = parts[:-1]
    street = city = state = zip_code = ""
    if parts:
        last = parts[-1]
        m = re.match(r"^(.*?)\s*(\d{5}(?:-?\d{4})?|\d{6})?\s*$", last)
        region, zip_code = (m.group(1).strip(), m.group(2) or "") if m else (last, "")
        if region.upper() in US_STATES:
            state = region.upper()
        elif region.lower() in STATE_BY_NAME:
            state = STATE_BY_NAME[region.lower()]
        else:
            # e.g. "CA Sherman Oak": leading two-letter state code
            m2 = re.match(r"^([A-Za-z]{2})\b", region)
            state = m2.group(1).upper() if m2 and m2.group(1).upper() in US_STATES else region
        if len(parts) >= 2:
            city = parts[-2]
            street = ", ".join(parts[:-2])
        else:
            street = ""
    is_usa = state in US_STATES and not (addr or "").upper().startswith(("INT ", "COMPANY INTNL"))
    return street, city, state, zip_code, ("US" if is_usa else ""), is_usa


def to_row(loc):
    row = dict(loc)
    street, city, state, zip_code, country, is_usa = parse_address(loc.get("streetaddress"))
    row.update(street=street, city=city, state=state, zip=zip_code,
               country_guess=country, is_usa="yes" if is_usa else "no",
               brand_email="yes" if BRAND_EMAIL_DOMAIN in (loc.get("email") or "").lower() else "no",
               likely_internal="yes" if INTERNAL_NAME.search(loc.get("name") or "") else "no")
    try:
        custom = json.loads(loc.get("custom_fields") or "{}")
    except ValueError:
        custom = {}
    if isinstance(custom, dict):
        row["custom_tdeut9eu61"] = custom.get("tdeut9eu61", "")
        row["custom_07irkz7nir"] = custom.get("07irkz7nir", "")
    return row


def save_to_csv(locs, filename):
    rows = sorted((to_row(l) for l in locs),
                  key=lambda r: (r["is_usa"] != "yes", r["state"], r["city"], r["name"] or ""))
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    usa = sum(1 for r in rows if r["is_usa"] == "yes")
    print(f"Saved {len(rows)} locations ({usa} in USA) to {filename}")


def main():
    save_to_csv(fetch_locations(), OUTPUT_FILE)


if __name__ == "__main__":
    main()
