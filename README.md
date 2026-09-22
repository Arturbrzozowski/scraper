# Store / Provider Locator Scrapers

Python scrapers that extract location data from vendor store-locator pages and
save it to CSV.

| Scraper | Source | Locator tech | Output |
| --- | --- | --- | --- |
| `cyspera_provider_scraper.py` | [cyspera.com/pages/find-a-provider](https://cyspera.com/pages/find-a-provider) | static JSON on Shopify CDN | `cyspera_providers.csv` |
| `sente_store_scraper.py` | [sentelabs.com/pages/store-locator](https://sentelabs.com/pages/store-locator) | Closeby embed API | `sente_stores.csv` |
| `dna_store_scraper.py` | DNA store locator | Blipstar widget | `dna_stores.csv` |

None of the three needs a browser or an API key. Two of them dump their whole
dataset in a single request; only the Blipstar one requires a search sweep.

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

## Sente Labs store locator

The page embeds a [Closeby](https://closeby.co) locator widget. It *does* have
a real API, and unlike Blipstar it is not radius-based — a single
unauthenticated request returns every location at once:

```
GET https://www.closeby.co/embed/{map_key}/locations
```

The response carries `total_count` and `is_limited_results`; for this map it
returns all 1046 locations with `is_limited_results: false`, so there is no
pagination or city sweep to do. The scraper prints a warning if that flag ever
flips to true.

The map key is read from the store-locator page on each run
(`window.closeby = { mapKey: "..." }`) rather than hard-coded, with the last
known key kept as a fallback.

Run it:

```bash
python sente_store_scraper.py
python sente_store_scraper.py --raw-json sente_raw.json   # keep the API payload
python sente_store_scraper.py --details                   # see caveat below
```

Standard library only.

### A Shopify gotcha

Shopify's storefront sends `Vary: Accept` and serves a **page metadata JSON
API** rather than the rendered HTML when the request asks for JSON. Fetching
the locator page with `Accept: application/json` returns a 216-byte stub with
no widget markup in it. The scraper therefore sends a browser-style HTML
`Accept` header for page fetches and a JSON one only for API calls.

### The per-location detail endpoint is a dead end

The widget also calls `GET /locations/{id}` when a marker is clicked. Against
this map that response adds only two keys to what the list already returns,
`location_hours` and `secondary_images`, and both were empty across a 30-record
sample, along with `phone_number`, `email`, `short_description`, `categories`
and `banner_url`. The `--details` flag will fetch them anyway (about 1046
requests at ~0.3 s each), but as of the last check it changes nothing in the
output. The `/embed/{map_key}/categories` endpoint returns an empty list too.

### Fields available per store

| Column | Coverage (1046 records) | Notes |
| --- | --- | --- |
| `id`, `title`, `address_full` | 1046 | |
| `latitude`, `longitude` | 1046 | |
| `status`, `slug`, `updated_at` | 1046 | `status` is `in_stock` for every record |
| `country` | 1038 | derived, not in the source |
| `city`, `state` | 995 | derived, not in the source |
| `zip_code` | 994 | derived, not in the source |
| `website` | 870 | often bare hostnames, no scheme |
| `phone_number` | **1** | |
| `email` | **0** | |
| `short_description`, `categories`, `hours` | **0** | |

Closeby's schema carries a long tail of food-delivery fields (`doordash`,
`uber_eats`, `deliveroo`, `grubhub`, `swiggy`, `zomato`, `rappi` and friends)
plus `banner_url`, `custom_button_*` and `priority`. All are null for every
record on this map, so they are not written to the CSV.

### Data quality notes

- **Contact data is effectively absent.** One phone number and zero email
  addresses across 1046 records. If you need to reach these clinics, this
  source gives you a name, a location and — 83% of the time — a website, and
  nothing else. That is the main limitation of the dataset.
- **ZIP codes have lost their leading zeros** in the source: Boston is stored
  as `Massachusetts 2115`, not `02115`. This affects roughly 49 records in
  Massachusetts, New Hampshire, New Jersey and Puerto Rico. The scraper
  left-pads them back to five digits.
- `address_full` is a single free-text field, so `city`, `state`, `zip_code`
  and `country` are parsed out of it rather than read directly. 995 of 1046
  resolve to a US state. The rest are genuinely international (UK, Vietnam,
  Thailand, Canada, Ireland) or malformed.
- 8 records resolve to no country at all: four have no city or region in the
  address, two misspell the state (`Washignton`, `Washinton`), one is a
  Puerto Rico address with a duplicated tail, and one is not an address.
- 9 titles repeat across different addresses — multi-site practices, not
  duplicates. There are no exact title+address duplicates.
- `website` values are inconsistent: some include `https://`, some are bare
  hostnames like `www.mainelaserclinic.com`. Normalise before using them.
- Every record shares the same `updated_at` minute (2026-09-17T00:02–00:03Z),
  which suggests the whole map was last bulk-reimported rather than edited
  per-location.

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
