#!/usr/bin/env python3
"""Final pass scraper with better error handling, saves incrementally."""

import csv
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import http.client
from collections import OrderedDict

API_BASE = "https://us.alumiermd.com/apps/lambda/webtheme/theme/clinic-locator"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

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

OUTPUT_CSV = "alumier_clinics.csv"

# All search terms - comprehensive list
LOCATION_SEARCHES = [
    # 50 states
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
    # 150+ cities
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
    "Irvine", "Toledo", "Jersey City", "Durham", "Norfolk", "Reno",
    "Fort Lauderdale", "Salt Lake City", "Chattanooga", "Savannah",
    "Charleston", "Little Rock", "Huntsville", "Grand Rapids",
    "Bridgeport", "Providence", "Rochester", "Fayetteville",
    "Birmingham", "Baton Rouge", "Macon", "Paterson",
    "Knoxville", "Tallahassee", "Scottsdale", "Spokane",
    "Eugene", "Palm Bay", "Provo", "Tampa", "Naperville",
    # California deep dive
    "Beverly Hills", "Santa Monica", "Calabasas", "Thousand Oaks",
    "Santa Barbara", "Palo Alto", "Walnut Creek", "Napa",
    "Palm Springs", "Temecula", "Carlsbad", "La Jolla",
    "Newport Beach", "Laguna Beach", "Huntington Beach",
    "Torrance", "Manhattan Beach", "Woodland Hills", "Chatsworth",
    "Simi Valley", "Redlands", "Rancho Cucamonga", "Corona",
    "Lake Forest CA", "Mission Viejo", "Roseville", "Folsom",
    "Elk Grove", "Pleasanton", "Santa Cruz", "Chico", "Redding",
    # Texas deep dive
    "Plano TX", "Frisco TX", "McKinney TX", "Southlake TX",
    "The Woodlands TX", "Sugar Land TX", "Katy TX", "Pearland TX",
    "Galveston", "Tyler TX", "Midland TX", "Lubbock", "Amarillo",
    "El Paso", "Waco", "Round Rock TX", "Cedar Park TX", "McAllen",
    # Florida deep dive
    "Fort Myers FL", "Naples FL", "Sarasota", "Bradenton",
    "St Petersburg FL", "Clearwater", "West Palm Beach",
    "Boca Raton", "Delray Beach", "Pompano Beach",
    "Coral Gables", "Key West", "Gainesville FL", "Daytona Beach",
    "Vero Beach", "Pensacola", "Destin", "St Augustine",
    "Winter Park FL", "Lakeland FL",
    # New York deep dive
    "Manhattan NY", "Brooklyn NY", "White Plains", "Scarsdale",
    "Garden City NY", "Great Neck", "Huntington NY",
    "Albany NY", "Saratoga Springs", "Syracuse", "Buffalo NY", "Ithaca",
    # Georgia deep dive
    "Marietta GA", "Alpharetta GA", "Sandy Springs GA",
    "Decatur GA", "Peachtree City", "Augusta GA", "Athens GA",
    # Supplemental
    "Sedona AZ", "Flagstaff AZ", "Evanston IL", "Oak Brook IL",
    "Highland Park IL", "Edina MN", "Wayzata MN", "Rochester MN",
    "Princeton NJ", "Morristown NJ", "Summit NJ", "Red Bank NJ",
    "Cherry Hill NJ", "Greenville SC", "Columbia SC", "Hilton Head",
    "Mount Pleasant SC", "Boulder CO", "Fort Collins CO", "Aspen CO",
    "Akron OH", "Canton OH", "Franklin TN", "Brentwood TN",
    "Cape Cod MA", "Wellesley MA", "Bethesda MD", "Annapolis MD",
    "Bend OR", "McLean VA", "Alexandria VA", "Charlottesville VA",
    "Kirkland WA", "Redmond WA", "Olympia WA",
    "Bozeman MT", "Missoula MT", "Billings MT",
    "Sioux Falls SD", "Rapid City SD",
    "Fargo ND", "Bismarck ND",
    "Burlington VT", "Stowe VT",
    "Charleston WV", "Morgantown WV",
    "Jackson WY", "Cheyenne WY",
    "Bangor ME", "Portland ME", "Bar Harbor ME",
    "Wilmington DE", "Dover DE",
    "Manchester NH", "Portsmouth NH",
]

CLINIC_NAME_SEARCHES = [
    "dermatology", "medspa", "skin", "aesthetic", "beauty",
    "wellness", "laser", "cosmetic", "plastic", "med spa",
    "derm", "face", "rejuvenation", "glow", "radiance",
    "spa", "clinic", "body", "anti-aging", "botox",
    "institute", "center", "studio", "luxe", "pure",
    "renew", "revive", "refresh", "enhance", "sculpt",
    "restore", "vitality", "bloom", "medical",
]


def fetch_clinics(search_term, search_type="location", country_code="US"):
    params = urllib.parse.urlencode({
        "search": search_term,
        "countrycode": country_code,
        "type": search_type,
    })
    url = f"{API_BASE}?{params}"
    req = urllib.request.Request(url, headers=HEADERS)

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if data.get("error") is False and data.get("message") == "ok":
                    clinics = data.get("clinics", [])
                    return [c for c in clinics if c.get("type") != "origin"]
                return []
        except Exception:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return []


def save_csv(clinics):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for clinic in clinics.values():
            writer.writerow(clinic)


def main():
    all_clinics = OrderedDict()

    all_searches = (
        [(t, "location") for t in LOCATION_SEARCHES]
        + [(t, "clinic") for t in CLINIC_NAME_SEARCHES]
    )

    total = len(all_searches)
    print(f"Running {total} searches...")

    for i, (term, stype) in enumerate(all_searches, 1):
        label = f"clinic:{term}" if stype == "clinic" else term
        print(f"[{i}/{total}] {label}...", end=" ", flush=True)
        clinics = fetch_clinics(term, search_type=stype)
        new_count = 0
        for c in clinics:
            code = c.get("code")
            if code and code not in all_clinics:
                all_clinics[code] = c
                new_count += 1
        print(f"{len(clinics)} ({new_count} new) | total: {len(all_clinics)}")

        # Save every 50 searches
        if i % 50 == 0:
            save_csv(all_clinics)
            print(f"  [checkpoint saved: {len(all_clinics)} clinics]")

        time.sleep(1.2)

    save_csv(all_clinics)
    print(f"\nDone! Saved {len(all_clinics)} unique clinics to {OUTPUT_CSV}")

    # Summary
    provinces = {}
    for c in all_clinics.values():
        prov = c.get("billing_province") or c.get("clinic_province") or "Unknown"
        provinces[prov] = provinces.get(prov, 0) + 1

    print(f"\nStates/provinces: {len(provinces)}")
    print(f"\nTop 20 states:")
    for state, count in sorted(provinces.items(), key=lambda x: -x[1])[:20]:
        print(f"  {state}: {count}")


if __name__ == "__main__":
    main()
