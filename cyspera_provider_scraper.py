#!/usr/bin/env python3
"""
Cyspera Provider Locator Scraper

Extracts clinic/provider data from the Cyspera "Find a Provider" map at
https://cyspera.com/pages/find-a-provider

Unlike the Blipstar-based locators, this map has no search API: the page's
inline JavaScript loads the FULL provider dataset from a single static JSON
file hosted on Shopify's CDN, then filters it client-side. So no browser
automation is needed — this script:

1. Fetches the find-a-provider page HTML
2. Extracts the current DATA_URL (the JSON file's version parameter changes
   whenever the dataset is updated in Shopify)
3. Downloads the JSON and writes it to CSV

Fields available per clinic (from the JSON):
- name, description, address, country, phone, email, website, lat, lng

Usage:
    python cyspera_provider_scraper.py
"""

import csv
import json
import re
import sys
import urllib.request

PAGE_URL = "https://cyspera.com/pages/find-a-provider"
# Fallback in case the DATA_URL can no longer be found in the page source
FALLBACK_DATA_URL = (
    "https://cdn.shopify.com/s/files/1/0678/3988/5386/files/"
    "cyspera-providers.json?v=1780933281"
)
OUTPUT_FILE = "cyspera_providers.csv"

FIELDS = [
    "name",
    "description",
    "address",
    "country",
    "phone",
    "email",
    "website",
    "lat",
    "lng",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def find_data_url() -> str:
    """Extract the provider JSON URL from the page's inline locator script."""
    print(f"Fetching page: {PAGE_URL}")
    try:
        html = http_get(PAGE_URL).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Failed to fetch page ({e}), using fallback data URL")
        return FALLBACK_DATA_URL

    m = re.search(
        r"DATA_URL\s*=\s*'(https://cdn\.shopify\.com/[^']+\.json[^']*)'", html
    )
    if m:
        print(f"  Found DATA_URL: {m.group(1)}")
        return m.group(1)

    # Looser match: any providers JSON on the Shopify CDN
    m = re.search(r"(https://cdn\.shopify\.com/[^\"']*providers[^\"']*\.json[^\"']*)", html)
    if m:
        print(f"  Found provider JSON URL: {m.group(1)}")
        return m.group(1)

    print("  DATA_URL not found in page source, using fallback data URL")
    return FALLBACK_DATA_URL


def fetch_providers(data_url: str) -> list[dict]:
    print(f"Fetching provider data: {data_url}")
    data = json.loads(http_get(data_url))
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array of providers, got {type(data)}")
    print(f"  Retrieved {len(data)} providers")
    return data


def write_csv(providers: list[dict], path: str = OUTPUT_FILE) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for p in providers:
            writer.writerow({k: p.get(k, "") for k in FIELDS})
    print(f"Wrote {len(providers)} providers to {path}")


def summarize(providers: list[dict]) -> None:
    countries: dict[str, int] = {}
    for p in providers:
        c = p.get("country") or "(unspecified)"
        countries[c] = countries.get(c, 0) + 1
    print("\nProviders per country:")
    for c, n in sorted(countries.items(), key=lambda kv: -kv[1]):
        print(f"  {c}: {n}")
    for field in FIELDS:
        filled = sum(1 for p in providers if p.get(field))
        print(f"Field '{field}': {filled}/{len(providers)} filled")


def main() -> int:
    data_url = find_data_url()
    try:
        providers = fetch_providers(data_url)
    except Exception as e:
        print(f"ERROR: failed to fetch provider data: {e}")
        return 1
    write_csv(providers)
    summarize(providers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
