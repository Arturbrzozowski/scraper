#!/usr/bin/env python3
"""
Second pass scraper - retry failed states and add granular city searches
for states that likely have more than 20 clinics.
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

# Failed states from pass 1
RETRY_TERMS = [
    "Alabama", "Arkansas", "Colorado", "Georgia", "Louisiana",
    "Maryland", "Massachusetts", "Montana", "Nebraska", "Ohio",
    "Oregon", "South Carolina", "Vermont", "West Virginia", "Wyoming",
    "Portland", "Memphis", "Omaha", "Tucson", "Oakland", "Tampa",
    "Bakersfield", "Fontana", "Oxnard", "Knoxville", "Fort Lauderdale",
    "Tallahassee", "Jackson", "Naperville", "Eugene", "Palm Bay",
    "San Bernardino", "Spokane", "Fremont", "Irvine", "Toledo",
    "Durham", "Norfolk", "Reno", "Santa Ana", "Riverside",
]

# Granular city searches for large states (API returns max 20)
CA_CITIES = [
    "Beverly Hills", "Santa Monica", "Malibu", "Calabasas", "Burbank",
    "Glendale CA", "Pasadena CA", "West Hollywood", "Sherman Oaks",
    "Encino", "Thousand Oaks", "Ventura", "Santa Barbara", "San Luis Obispo",
    "Monterey", "Carmel", "Palo Alto", "Mountain View", "Sunnyvale",
    "Cupertino", "Walnut Creek", "Concord", "Berkeley", "Napa",
    "Sonoma", "Palm Springs", "Palm Desert", "Rancho Mirage",
    "Temecula", "Carlsbad", "Encinitas", "La Jolla", "Del Mar",
    "Newport Beach", "Laguna Beach", "Dana Point", "Huntington Beach",
    "Costa Mesa", "Torrance", "Manhattan Beach", "Redondo Beach",
    "El Segundo", "Woodland Hills", "Northridge", "Chatsworth",
    "Simi Valley", "Camarillo", "Redlands", "Rancho Cucamonga",
    "Claremont", "Upland", "Ontario CA", "Corona", "Lake Forest",
    "Mission Viejo", "San Clemente", "Rancho Santa Fe", "Escondido",
    "Vista", "Chico", "Redding", "Roseville", "Folsom", "Elk Grove",
    "Davis CA", "Vacaville", "Fairfield CA", "Vallejo", "San Rafael",
    "Novato", "Pleasanton", "Livermore", "Dublin CA", "Tracy CA",
    "Manteca", "Visalia", "Merced", "Salinas", "Santa Cruz",
]

TX_CITIES = [
    "Plano", "Frisco", "McKinney", "Allen", "Southlake", "Keller",
    "Grapevine", "Flower Mound", "Lewisville", "Denton TX",
    "The Woodlands TX", "Sugar Land", "Katy TX", "Pearland",
    "League City", "Galveston", "Beaumont TX", "Tyler TX",
    "Midland TX", "Lubbock", "Amarillo", "El Paso", "Waco",
    "Temple TX", "Bryan TX", "College Station", "Round Rock",
    "Cedar Park TX", "Georgetown TX", "San Marcos TX", "New Braunfels",
    "Boerne", "Fredericksburg TX", "Kerrville", "Laredo TX",
    "McAllen", "Harlingen", "Edinburg TX", "Abilene TX",
]

FL_CITIES = [
    "Fort Myers", "Naples FL", "Sarasota", "Bradenton", "St Petersburg",
    "Clearwater", "Palm Beach", "West Palm Beach", "Boca Raton",
    "Delray Beach", "Pompano Beach", "Hollywood FL", "Coral Gables",
    "Coconut Grove", "Key West", "Gainesville FL", "Ocala",
    "Daytona Beach", "Melbourne FL", "Vero Beach", "Stuart FL",
    "Port St Lucie", "Jupiter FL", "Pensacola", "Destin",
    "Panama City FL", "Tallahassee FL", "St Augustine", "Ponte Vedra",
    "Amelia Island", "Winter Park FL", "Lake Mary", "Altamonte Springs",
    "Kissimmee", "Celebration FL", "Lakeland FL", "Brandon FL",
]

NY_CITIES = [
    "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island",
    "White Plains", "Scarsdale", "Larchmont", "Rye NY", "Greenwich CT",
    "Garden City NY", "Great Neck", "Manhasset", "Roslyn",
    "Huntington NY", "Northport", "Smithtown", "Stony Brook",
    "Commack", "Babylon NY", "Long Beach NY", "Rockville Centre",
    "Hewlett", "Woodbury NY", "Syosset", "Jericho NY",
    "Albany NY", "Saratoga Springs", "Syracuse", "Buffalo NY",
    "Ithaca NY", "Poughkeepsie", "Newburgh NY", "Kingston NY",
]

GA_CITIES = [
    "Marietta GA", "Roswell GA", "Alpharetta", "Johns Creek",
    "Dunwoody", "Sandy Springs", "Buckhead", "Decatur GA",
    "Peachtree City", "Newnan GA", "Savannah GA", "Brunswick GA",
    "St Simons Island", "Augusta GA", "Athens GA", "Columbus GA",
    "Valdosta", "Tifton", "Warner Robins", "Perry GA",
]

# Other large-state supplemental searches
SUPPLEMENTAL = [
    "Scottsdale AZ", "Chandler AZ", "Gilbert AZ", "Tempe AZ", "Sedona",
    "Flagstaff AZ", "Prescott AZ",
    "Naperville IL", "Schaumburg", "Evanston IL", "Oak Brook",
    "Highland Park IL", "Lake Forest IL", "Hinsdale IL", "Barrington IL",
    "Edina MN", "Wayzata", "Plymouth MN", "Minnetonka", "St Paul MN",
    "Rochester MN", "Duluth MN",
    "Princeton NJ", "Morristown NJ", "Summit NJ", "Westfield NJ",
    "Short Hills NJ", "Red Bank NJ", "Hoboken", "Montclair NJ",
    "Cherry Hill NJ", "Haddonfield NJ",
    "Charleston SC", "Greenville SC", "Columbia SC", "Hilton Head",
    "Bluffton SC", "Mount Pleasant SC",
    "Boulder CO", "Fort Collins CO", "Aspen", "Vail CO",
    "Breckenridge CO", "Steamboat Springs",
    "Columbus OH", "Cincinnati OH", "Akron", "Canton OH",
    "Youngstown", "Toledo OH", "Dayton OH",
    "Nashville TN", "Knoxville TN", "Chattanooga TN", "Memphis TN",
    "Franklin TN", "Brentwood TN", "Murfreesboro TN",
    "Boston MA", "Cambridge MA", "Brookline MA", "Newton MA",
    "Wellesley MA", "Lexington MA", "Concord MA", "Worcester MA",
    "Springfield MA", "Cape Cod",
    "Baltimore MD", "Bethesda MD", "Chevy Chase MD", "Annapolis",
    "Columbia MD", "Towson MD",
    "Portland OR", "Bend OR", "Eugene OR", "Salem OR", "Ashland OR",
    "Virginia Beach VA", "Richmond VA", "Arlington VA", "McLean VA",
    "Alexandria VA", "Charlottesville VA", "Norfolk VA", "Roanoke VA",
    "Bellevue WA", "Tacoma WA", "Kirkland WA", "Redmond WA",
    "Olympia WA", "Spokane WA",
]

# Clinic name searches
CLINIC_NAMES = [
    "skin", "laser", "med spa", "rejuvenation", "radiance",
    "spa", "clinic", "body", "anti-aging", "botox",
    "filler", "peel", "facial", "acne", "rosacea",
    "eczema", "institute", "center", "studio", "lounge",
    "luxe", "glow", "pure", "renew", "revive",
    "refresh", "enhance", "sculpt", "contour", "age",
    "restore", "vitality", "bloom", "blossom", "shine",
]

OUTPUT_CSV = "alumier_clinics.csv"


def fetch_clinics(search_term, search_type="location", country_code="US", retries=2):
    """Fetch clinics with retry logic."""
    params = urllib.parse.urlencode({
        "search": search_term,
        "countrycode": country_code,
        "type": search_type,
    })
    url = f"{API_BASE}?{params}"
    req = urllib.request.Request(url, headers=HEADERS)

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if data.get("error") is False and data.get("message") == "ok":
                    clinics = data.get("clinics", [])
                    return [c for c in clinics if c.get("type") != "origin"]
                return []
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            if attempt < retries:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
            else:
                print(f"FAIL", end=" ")
                return []


def load_existing_csv():
    """Load existing clinics from CSV."""
    clinics = OrderedDict()
    try:
        with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("code")
                if code:
                    clinics[code] = row
    except FileNotFoundError:
        pass
    return clinics


def main():
    all_clinics = load_existing_csv()
    initial_count = len(all_clinics)
    print(f"Loaded {initial_count} existing clinics from CSV")

    all_searches = (
        [(t, "location") for t in RETRY_TERMS]
        + [(t, "location") for t in CA_CITIES]
        + [(t, "location") for t in TX_CITIES]
        + [(t, "location") for t in FL_CITIES]
        + [(t, "location") for t in NY_CITIES]
        + [(t, "location") for t in GA_CITIES]
        + [(t, "location") for t in SUPPLEMENTAL]
        + [(t, "clinic") for t in CLINIC_NAMES]
    )

    total = len(all_searches)
    print(f"Running {total} additional searches...")

    for i, (term, stype) in enumerate(all_searches, 1):
        label = f"clinic:{term}" if stype == "clinic" else term
        print(f"[{i}/{total}] {label}...", end=" ")
        clinics = fetch_clinics(term, search_type=stype)
        new_count = 0
        for c in clinics:
            code = c.get("code")
            if code and code not in all_clinics:
                all_clinics[code] = c
                new_count += 1
        print(f"{len(clinics)} ({new_count} new) | total: {len(all_clinics)}")
        time.sleep(1.0)  # Be more conservative with rate limiting

    # Write updated CSV
    print(f"\nWriting {len(all_clinics)} clinics to {OUTPUT_CSV}...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for clinic in all_clinics.values():
            writer.writerow(clinic)

    new_total = len(all_clinics) - initial_count
    print(f"Done! {len(all_clinics)} total clinics ({new_total} new in this pass)")

    # Summary
    provinces = {}
    for c in all_clinics.values():
        prov = c.get("billing_province") or c.get("clinic_province") or "Unknown"
        provinces[prov] = provinces.get(prov, 0) + 1

    print(f"\nTop states:")
    for state, count in sorted(provinces.items(), key=lambda x: -x[1])[:20]:
        print(f"  {state}: {count}")


if __name__ == "__main__":
    main()
