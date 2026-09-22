# Store / Provider Locator Scrapers

Python scrapers that extract location data from vendor store-locator pages and
save it to CSV.

| Scraper | Source | Locator tech | Output |
| --- | --- | --- | --- |
| `cyspera_provider_scraper.py` | [cyspera.com/pages/find-a-provider](https://cyspera.com/pages/find-a-provider) | static JSON on Shopify CDN | `cyspera_providers.csv` |
| `sente_store_scraper.py` | [sentelabs.com/pages/store-locator](https://sentelabs.com/pages/store-locator) | Closeby embed API | `sente_stores.csv` |
| `calecim_directory_scraper.py` | [calecimprofessional.com/pages/pro-directory](https://calecimprofessional.com/pages/pro-directory) | Stockist.co, full dump | `calecim_directory.csv` |
| `pavise_store_scraper.py` | [pavise.com/pages/store-locator](https://pavise.com/pages/store-locator) | Stockist.co, geohash sweep | `pavise_stores.csv` |
| `dna_store_scraper.py` | DNA store locator | Blipstar widget | `dna_stores.csv` |

`stockist_scraper.py` is the shared module behind the two Stockist sites: both
fetch strategies, the field normalisation, and the CSV writer. The two
per-site scripts are thin wrappers over it.

None of these needs a browser or an API key.

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

## CALECIM Professional pro directory

The page embeds a [Stockist](https://stockist.co) widget (tag `u7465`), which
publishes a documented full-dump endpoint:

```
GET https://stockist.co/api/v1/{widget_tag}/locations/all
```

One unauthenticated request returns all 2995 records — this account has the
full-dump endpoint enabled, unlike Pavise's below. The widget's other two
endpoints add nothing: `/locations/search` returns the same records plus a
`distance` relative to a query point, and `/locations/overview.js` is a geohash
index used to place map pins. The widget tag is read from the page on each run
(`data-stockist-widget-tag="..."`), with the last known tag as a fallback.

```bash
python calecim_directory_scraper.py
python calecim_directory_scraper.py --raw-json calecim_raw.json
python calecim_directory_scraper.py --no-repair   # source values, unmodified
```

Standard library only.

### Why this source is the useful one

It is the only one of the four with real contact data **and** structured
address fields. 2387 of 2995 records have a phone number and 2120 have an
email; 2584 have at least one of the two. It also splits clinics from salons
via Stockist's filter taxonomy: **1126 Clinics, 1868 Salons**, which the other
three sources cannot distinguish at all.

### Fields available per record

| Column | Coverage (2995 records) | Notes |
| --- | --- | --- |
| `id`, `name`, `latitude`, `longitude` | 2995 | |
| `category` | 2994 | `Clinics` or `Salons`, from Stockist filters |
| `address_line_1` | 2895 | |
| `postal_code` | 2673 | after repair |
| `phone` | 2387 | after repair |
| `email` | 2120 | after repair |
| `state` | 2488 | after repair |
| `city` | 2098 | |
| `website` | 939 | |
| `address_line_2` | 325 | |
| `country` | 2858 | derived; only 2188 in the source |
| `description`, `image_url`, `full_address`, `priority` | **0** | present in the schema, null everywhere |

The only custom fields defined on this map are two marker-icon URLs, which are
presentation, not data, so they are not written to the CSV.

### This data is dirty, and the scraper repairs it

Normalisation is on by default; `--no-repair` turns it off. Every change is
recorded per-row in a `data_flags` column, and `country_raw` always preserves
the original value, so nothing is silently rewritten. Repairs applied on the
current snapshot:

| Repair | Records | What was wrong |
| --- | --- | --- |
| `country_normalized` | 1144 | 123 distinct country spellings: `US`, `USA`, `Us`, `United States`; `UK`, `GB`, `United Kingdome`; `AU`/`Au`; `TW`/`Tw` |
| `country_inferred` | 739 | country blank, recovered from a US/Canadian/Australian region code or a Taiwanese district name |
| `zip_recovered_from_country` | 84 | **a ZIP code sitting in the `country` field** with `postal_code` left empty — a column shift in their import |
| `state_split_from_postal` | 76 | `postal_code` holding `MI 48313` rather than `48313` |
| `country_from_tld` | 41 | country recovered from a `.ie`/`.pl`/`.hu` website or email domain |
| `email_placeholder_blanked` | 27 | the literal string `NA` stored as an email address |
| `country_not_a_country` | 22 | `Europe` in the country field |
| `phone_comma_stripped` | 17 | **phone numbers mangled by thousands separators**: `665,930,009` for `665930009` |
| `name_whitespace` | 14 | leading or trailing spaces in the name |
| `email_multivalue` | 12 | two addresses in one field, semicolon-separated (flagged, not split) |
| `phone_placeholder_blanked` | 6 | placeholder text in the phone field |
| `email_malformed` | 4 | not an email address |
| `website_recovered_from_country` | 4 | a URL in the `country` field, moved to `website` |
| `email_was_url` | 2 | a URL in the `email` field |
| `website_recovered_from_email` | 1 | as above, recovered into an empty `website` |

### Remaining known problems

- **137 records still have no country** and no signal to infer one from: no
  region, no postal code, and either no web presence or only a generic `.com`
  domain. Inferring these would require geocoding the coordinates, which the
  scraper deliberately does not do.
- **26 exact name+address duplicates** and 157 records sharing coordinates with
  another record. Some of the latter are genuinely co-located (a clinic and a
  salon at one address); they are not de-duplicated.
- 101 email addresses appear on more than one record — group practices sharing
  an inbox, not necessarily errors.
- `city` is empty on 897 records even where `address_line_1` contains the city,
  because Stockist stores whatever the importer put in each column.
- Region codes `WA`, `SA` and `NT` are ambiguous between US, Australian and
  Canadian schemes. The inference tables resolve them to the US reading and
  exclude them from the Australian and Canadian sets, so a Western Australia
  record with a blank country may be labelled United States. This affects a
  small number of records and is the one repair rule that can be wrong.

## Pavise store locator

Also Stockist, **but do not assume that means it behaves like CALECIM.** This
account has the full-dump endpoint disabled:

```
GET https://stockist.co/api/v1/u19167/locations/all
-> HTTP 400  {"error": "Method not allowed."}
```

`/locations/search` still works, but it caps at **100 results per request
regardless of the `distance` parameter** — asking for a 10000-mile radius
returns the same 100 records as a 100-mile one. So the whole dataset cannot be
pulled in one shot, and a blind city sweep would silently miss anything far
from a chosen city.

### How the sweep gets complete coverage

`/locations/overview.js` is still enabled, and it is the map's pin index: a
9-character geohash (~5 m precision) for **every** location. That turns an
open-ended search problem into an enumeration:

1. Fetch the overview and decode every geohash to a coordinate.
2. Search at each uncovered coordinate, starting at a 25-mile radius.
3. If a response comes back at the 100-result cap, retry that point at 10, 4,
   then 1 mile, so dense metros are not truncated.
4. Re-encode each returned record's own coordinates to a geohash and mark it
   covered, so one search in a dense area retires many pending points.
5. De-duplicate by location id.

On the current snapshot this recovers **1274 unique locations from 1274
overview pins with zero geohashes left uncovered, in 258 requests**. The
scraper prints both numbers at the end, so an incomplete run is visible rather
than silent, and warns if any point stays at the cap down to a 1-mile radius.

```bash
python pavise_store_scraper.py
python pavise_store_scraper.py --raw-json pavise_raw.json
python pavise_store_scraper.py --force-sweep   # skip the full-dump attempt
```

The sweep takes a few minutes at the default 0.25 s delay between requests.

### Fields available per store

| Column | Coverage (1274 records) | Notes |
| --- | --- | --- |
| `id`, `name`, `city`, `state`, `latitude`, `longitude` | 1274 | |
| `postal_code` | 1274 | after repair |
| `country` | 1273 | derived; only 151 in the source |
| `address_line_1` | 1271 | |
| `address_line_2` | 366 | |
| `category` | 233 | only one value exists: `⟡ Pavise Diamond Partner ⟡` |
| `priority` | 232 | `50` on the Diamond Partner records, blank otherwise |
| `website` | 110 | |
| `phone` | **59** | |
| `email` | **0** | |
| `description`, `image_url`, `full_address` | **0** | in the schema, null everywhere |

`distance` and `distance_units` appear on search responses but are artifacts of
the query point, not properties of the store, so they are not written out.

### Data quality notes

- **Contact data is nearly absent**, as with Sente: 59 phone numbers and no
  email addresses at all across 1274 records. Only 110 records have a website.
  What this source is genuinely good for is **locations** — `city`, `state` and
  `postal_code` are complete, which is better structured than any of the other
  three.
- `category` is not a taxonomy. The single filter is a partner tier, so it
  splits the file into 233 Diamond Partners and 1041 unlabelled records; it
  does not distinguish clinics from salons.
- The **same ZIP-in-the-country-field column shift** seen on the CALECIM map
  appears here on 6 records, which suggests a defect in Stockist's import path
  rather than in one merchant's spreadsheet. The shared normaliser repairs it.
- 1128 records had no country and were inferred from their US state code; 145
  more were normalised from `United States of America`. One record is Canadian
  and one could not be resolved.
- 35 names carry leading or trailing whitespace. Names also contain decorative
  `⟡` characters, which are left as-is because they are part of how the brand
  presents these partners.
- 14 exact name+address duplicates remain, un-merged.

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
