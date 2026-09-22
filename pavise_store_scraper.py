#!/usr/bin/env python3
"""
Pavise Store Locator Scraper

Extracts stockist data from the Pavise store locator at
https://pavise.com/pages/store-locator

The page embeds a Stockist.co widget (tag u19167), the same vendor as the
CALECIM directory -- but this account has the full-dump endpoint disabled:
/api/v1/u19167/locations/all answers {"error": "Method not allowed."}.

So this one is recovered by the geohash sweep in stockist_scraper.py: the
map's overview.js pin index gives a geohash for every location, and the
search endpoint returns full records near a point. See that module for the
mechanics, and README.md for what the data looks like.

Usage:
    python pavise_store_scraper.py
    python pavise_store_scraper.py --raw-json pavise_raw.json
    python pavise_store_scraper.py --no-repair
"""

import sys

import stockist_scraper

PAGE_URL = "https://pavise.com/pages/store-locator"
FALLBACK_WIDGET_TAG = "u19167"
OUTPUT_FILE = "pavise_stores.csv"


if __name__ == "__main__":
    sys.exit(stockist_scraper.run(
        page_url=PAGE_URL,
        fallback_tag=FALLBACK_WIDGET_TAG,
        default_output=OUTPUT_FILE,
        description="Scrape the Pavise store locator",
    ))
