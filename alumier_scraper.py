#!/usr/bin/env python3
"""
Scraper for AlumierMD US clinic-locator API.
Collects all clinic/provider data by searching across US states and major cities.
"""

import csv
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from collections import OrderedDict

API_BASE = "https://us.alumiermd.com/apps/lambda/webtheme/theme/clinic-locator"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

# US states + major cities for comprehensive coverage
SEARCH_TERMS = [
    # All 50 US states
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
    # Major cities for denser coverage
    "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "San Jose", "Austin",
    "Jacksonville", "Fort Worth", "Columbus", "Charlotte", "Indianapolis",
    "San Francisco", "Seattle", "Denver", "Nashville", "Oklahoma City",
    "Portland", "Las Vegas", "Memphis", "Louisville", "Baltimore",
    "Milwaukee", "Albuquerque", "Tucson", "Fresno", "Sacramento",
    "Mesa", "Kansas City", "Atlanta", "Omaha", "Colorado Springs",
    "Raleigh", "Long Beach", "Virginia Beach", "Miami", "Oakland",
    "Minneapolis", "Tampa", "Tulsa", "Arlington", "New Orleans",
    "Bakersfield", "Wichita", "Cleveland", "Aurora", "Anaheim",
    "Honolulu", "Santa Ana", "Riverside", "Corpus Christi", "Lexington",
    "Stockton", "St. Louis", "Pittsburgh", "Cincinnati", "Anchorage",
    "Henderson", "Greensboro", "Plano", "Newark", "Lincoln", "Orlando",
    "Irvine", "Toledo", "Jersey City", "Chula Vista", "Durham",
    "Laredo", "Madison", "Gilbert", "Norfolk", "Reno", "Winston-Salem",
    "Glendale", "Hialeah", "Garland", "Scottsdale", "Irving", "Chesapeake",
    "North Las Vegas", "Fremont", "Baton Rouge", "Richmond", "Boise",
    "San Bernardino", "Spokane", "Des Moines", "Birmingham", "Tacoma",
    "Rochester", "Modesto", "Fayetteville", "Fontana", "Moreno Valley",
    "Santa Clarita", "Oxnard", "Knoxville", "Fort Lauderdale",
    "Salt Lake City", "Chattanooga", "Savannah", "Charleston",
    "Sioux Falls", "Little Rock", "Huntsville", "Grand Rapids",
    "Brownsville", "Tallahassee", "Peoria", "Overland Park",
    "Bridgeport", "Providence", "Jackson", "Garden Grove", "Oceanside",
    "Tempe", "Naperville", "Bellevue", "Pasadena", "Macon",
    "Dayton", "Paterson", "Eugene", "Palm Bay", "Provo",
]

# Also search by zip code ranges for major metro areas
ZIP_PREFIXES = [
    "100", "101", "102", "103", "104",  # NYC area
    "900", "901", "902", "903", "904", "905", "906",  # LA area
    "606", "607",  # Chicago
    "770", "771", "772",  # Houston
    "850", "851", "852",  # Phoenix
    "191",  # Philadelphia
    "021", "022",  # Boston
    "752", "753", "750",  # Dallas
    "941", "940",  # San Francisco
    "981", "980",  # Seattle
    "802", "803",  # Denver
    "331", "332", "333",  # Miami
    "303", "304",  # Atlanta
    "551", "554",  # Minneapolis
    "967", "968",  # Hawaii
]

OUTPUT_CSV = "alumier_clinics.csv"

CSV_FIELDS = [
    "code", "name", "zipcode", "zipcode_address",
    "latitude", "longitude",
    "contact_email", "shippingEmail",
    "billing_phone", "contact_phone",
    "billing_street_address_1", "billing_city", "billing_province",
    "billing_postal_code", "billing_country",
    "clinic_street_address_1", "clinic_street_address_2",
    "clinic_city", "clinic_province", "clinic_country", "clinic_postal_code",
    "website",
    "is_diamond_provider", "reward_tier_name", "reward_tier_number",
    "reward_tier_rank", "digital_excellence", "hide_from_clinic_locator",
    "distance_in_km",
]


def fetch_clinics(search_term, search_type="location", country_code="US"):
    """Fetch clinics from the API for a given search term."""
    params = urllib.parse.urlencode({
        "search": search_term,
        "countrycode": country_code,
        "type": search_type,
    })
    url = f"{API_BASE}?{params}"
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if data.get("error") is False and data.get("message") == "ok":
                clinics = data.get("clinics", [])
                # Filter out the "origin" entry (search coordinates)
                return [c for c in clinics if c.get("type") != "origin"]
            return []
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"  Error fetching '{search_term}': {e}")
        return []


def main():
    all_clinics = OrderedDict()  # code -> clinic data, to deduplicate

    # Search by location (state/city names)
    total_searches = len(SEARCH_TERMS) + len(ZIP_PREFIXES)
    print(f"Starting Alumier clinic scraper with {total_searches} search queries...")

    for i, term in enumerate(SEARCH_TERMS, 1):
        print(f"[{i}/{total_searches}] Searching: {term}...", end=" ")
        clinics = fetch_clinics(term, search_type="location")
        new_count = 0
        for c in clinics:
            code = c.get("code")
            if code and code not in all_clinics:
                all_clinics[code] = c
                new_count += 1
        print(f"found {len(clinics)} clinics ({new_count} new) | total: {len(all_clinics)}")
        time.sleep(0.5)

    # Search by zip code prefixes
    for i, zipcode in enumerate(ZIP_PREFIXES, len(SEARCH_TERMS) + 1):
        print(f"[{i}/{total_searches}] Searching zip: {zipcode}XX...", end=" ")
        clinics = fetch_clinics(zipcode, search_type="location")
        new_count = 0
        for c in clinics:
            code = c.get("code")
            if code and code not in all_clinics:
                all_clinics[code] = c
                new_count += 1
        print(f"found {len(clinics)} clinics ({new_count} new) | total: {len(all_clinics)}")
        time.sleep(0.5)

    # Also try clinic name search for common terms
    clinic_search_terms = [
        "dermatology", "medspa", "skin", "aesthetic", "beauty",
        "wellness", "laser", "cosmetic", "plastic", "med spa",
        "derm", "face", "rejuvenation", "glow", "radiance",
    ]

    for i, term in enumerate(clinic_search_terms, 1):
        print(f"[Clinic name search {i}/{len(clinic_search_terms)}] '{term}'...", end=" ")
        clinics = fetch_clinics(term, search_type="clinic")
        new_count = 0
        for c in clinics:
            code = c.get("code")
            if code and code not in all_clinics:
                all_clinics[code] = c
                new_count += 1
        print(f"found {len(clinics)} clinics ({new_count} new) | total: {len(all_clinics)}")
        time.sleep(0.5)

    # Write CSV
    print(f"\nWriting {len(all_clinics)} clinics to {OUTPUT_CSV}...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for clinic in all_clinics.values():
            writer.writerow(clinic)

    print(f"Done! Saved {len(all_clinics)} unique clinics to {OUTPUT_CSV}")

    # Print summary
    provinces = {}
    for c in all_clinics.values():
        prov = c.get("billing_province") or c.get("clinic_province") or "Unknown"
        provinces[prov] = provinces.get(prov, 0) + 1

    print(f"\nSummary:")
    print(f"  Total unique clinics: {len(all_clinics)}")
    print(f"  States/provinces covered: {len(provinces)}")
    print(f"\n  Top states:")
    for state, count in sorted(provinces.items(), key=lambda x: -x[1])[:15]:
        print(f"    {state}: {count}")


if __name__ == "__main__":
    main()
