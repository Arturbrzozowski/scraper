# Circadia Store Locator Scraper

A Python scraper that extracts store location data from the Circadia store locator page and saves it to a CSV file.

## Features

- Uses Playwright for browser automation to handle dynamic JavaScript content
- Multiple extraction strategies for different page structures
- Extracts: store name, address, phone number, email, website
- Outputs data to CSV format

## Installation

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install Playwright browsers:
   ```bash
   playwright install chromium
   ```

## Usage

Run the scraper:
```bash
python circadia_store_scraper.py
```

Run with visible browser (for debugging):
```bash
python circadia_store_scraper.py --no-headless
```

## Output

The scraper creates a `circadia_stores.csv` file with the following columns:
- `store_name` - Name of the store/location
- `address` - Full address
- `phone_number` - Contact phone number
- `email` - Email address
- `website` - Store website URL

## Notes

- The Circadia store locator page may require professional verification to access full store data
- If no stores are found, try running with `--no-headless` to see what the browser is loading
- The scraper includes multiple extraction strategies to handle different page structures
