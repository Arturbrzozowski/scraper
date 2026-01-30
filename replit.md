# Circadia Store Locator Scraper

## Overview
A Python web scraper that extracts store location data from the Circadia store locator page using Playwright for browser automation.

## Project Structure
- `circadia_store_scraper.py` - Main scraper script
- `requirements.txt` - Python dependencies (playwright)
- `circadia_stores.csv` - Output file with scraped store data

## Running the Scraper
The scraper runs via the "Circadia Scraper" workflow. Click Run to execute.

To run manually:
```bash
python circadia_store_scraper.py
```

## Output
The scraper creates `circadia_stores.csv` with columns:
- store_name
- address
- phone_number
- email
- website

## Notes
- Uses system-installed Chromium browser for compatibility
- The Circadia store locator may require professional verification to access full data
- Timeout set to 60 seconds for slow-loading pages
