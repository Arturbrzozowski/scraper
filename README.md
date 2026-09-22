# Store / Provider Locator Scrapers

Python scrapers that extract location data from vendor store-locator pages and
save it to CSV.

| Scraper | Source | Output |
| --- | --- | --- |
| `cyspera_provider_scraper.py` | [cyspera.com/pages/find-a-provider](https://cyspera.com/pages/find-a-provider) | `cyspera_providers.csv` |
| `dna_store_scraper.py` | DNA store locator (Blipstar widget) | `dna_stores.csv` |

## Cyspera provider locator

The Cyspera map has **no search API**. Its inline page script loads the entire
provider dataset in one request from a static JSON file on Shopify's CDN, then
filters and renders it client-side. So the scraper needs no browser automation
and no per-city search loop — it just reads the page, extracts the current data
URL, and downloads the file.

The JSON URL carries a version query parameter that changes whenever the
dataset is re-uploaded in Shopify, so the scraper re-reads it from the page on
every run instead of hard-coding it (a hard-coded URL is kept only as a
fallback).

Run it:

```bash
python cyspera_provider_scraper.py
```

Only the standard library is needed for this one.

### Fields available per clinic

Everything the map has is in the JSON; there is no richer record behind it.

| Column | Coverage (1237 records) |
| --- | --- |
| `name` | 1237 |
| `address` | 1237 |
| `lat` / `lng` | 1236 |
| `country` | 1218 |
| `phone` | 1202 |
| `description` | 1123 |
| `website` | 811 |
| `email` | 252 |

Coverage figures are from the September 2026 snapshot and will drift as Cyspera
updates the file.

### Data quality notes

- `description` is a duplicate of `name` in 178 records; it is not a
  specialty or service description.
- `address` is a single free-text field. It is not split into city / state /
  ZIP, and its contents are inconsistent — some records include the city and
  region, others stop at the street line. 10 records contain embedded
  newlines (quoted correctly in the CSV, so the file has more physical lines
  than records).
- `country` is empty on 19 records and is not normalised: values include
  `Saudi Arabia - المملكة العربية السعودية`, `Viet Nam - Tiếng Việt` and
  `West indies`.
- One record has `lat`/`lng` of `null`, so it never renders on the map.
- No record IDs, opening hours, or service/product fields exist in the source.

## DNA store locator

Scrapes a Blipstar map widget, which *does* expose a search endpoint
(`searchdbnew`) that returns results near a coordinate. Because that endpoint
is radius-based rather than a full dump, the scraper sweeps a list of major US
cities and de-duplicates the results.

Requires Playwright:

```bash
pip install -r requirements.txt
playwright install chromium
```

```bash
python dna_store_scraper.py
python dna_store_scraper.py --no-headless   # visible browser, for debugging
```

Columns: `store_name`, `address`, `city`, `state`, `zip_code`, `phone_number`,
`email`, `website`.
