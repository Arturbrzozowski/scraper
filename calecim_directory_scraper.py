#!/usr/bin/env python3
"""
CALECIM Professional Pro Directory Scraper

Extracts clinic/salon data from the CALECIM Professional pro directory at
https://calecimprofessional.com/pages/pro-directory

The page embeds a Stockist.co widget (tag u7465) whose account has the
full-dump endpoint enabled, so all 2995 records come back from a single
request to /api/v1/u7465/locations/all. The shared fetching, normalisation
and CSV logic lives in stockist_scraper.py; see README.md for the field
inventory and the list of source defects this repairs.

Usage:
    python calecim_directory_scraper.py
    python calecim_directory_scraper.py --raw-json calecim_raw.json
    python calecim_directory_scraper.py --no-repair   # source values, unmodified
"""

import sys

import stockist_scraper

PAGE_URL = "https://calecimprofessional.com/pages/pro-directory"
FALLBACK_WIDGET_TAG = "u7465"
OUTPUT_FILE = "calecim_directory.csv"


if __name__ == "__main__":
    sys.exit(stockist_scraper.run(
        page_url=PAGE_URL,
        fallback_tag=FALLBACK_WIDGET_TAG,
        default_output=OUTPUT_FILE,
        description="Scrape the CALECIM pro directory",
    ))
