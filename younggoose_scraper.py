#!/usr/bin/env python3
"""
Scraper for Young Goose store locations (https://www.younggoose.com/pages/store-locator).

The page embeds a Stockist.co widget (tag map_9q946n43) that returns up to 100
nearest locations per search with no practical distance cap, so the sweep starts
from 1000-mile circles and subdivides wherever a search is saturated.
"""

from stockist_scraper import StockistScraper, save_to_csv

TAG = "map_9q946n43"
OUTPUT_FILE = "younggoose_stores.csv"


def main():
    scraper = StockistScraper(TAG, max_results=100, max_radius=50000)
    save_to_csv(scraper.run(start_radius=1000), OUTPUT_FILE)


if __name__ == "__main__":
    main()
