# Store / Pro-Directory Scrapers

Python scrapers that extract location directory data from brand websites and
save it to CSV. No third-party dependencies are required (Python 3.9+) — each
scraper talks directly to the JSON API behind the brand's locations map.

## Jan Marini Skin Solutions locator

Scrapes the professional directory map on
[mariniskinsolutions.com/pages/locator](https://mariniskinsolutions.com/pages/locator).

The map is a custom React app backed by Jan Marini's own API, which is queried
by map bounding box and returns at most 25 results per request:

```
https://api.janmarini.com/api/locator/qualified/bounds
    ?northWestLat=..&northWestLong=..&southEastLat=..&southEastLong=..
```

The scraper starts from a world-spanning bounding box and recursively
subdivides any tile that hits the 25-result cap (quadtree scan), deduplicating
as it goes. It throttles politely and re-queues tiles that hit rate limits so
no data is lost.

```bash
python marini_locator_scraper.py          # writes marini_locations.csv
python marini_locator_scraper.py --debug  # also saves raw API records
```

Output columns (~2,300 US locations): `name`, `address_line_1`,
`address_line_2`, `city`, `state`, `zip`, `location` (pre-formatted full
address), `customer_class` (DOCTOR / MEDICALSPA / WHOLESALE / MECLASS),
`loyalty`, `grade`, `national_account`, `national_account_id`, `phone`,
`website`, `latitude`, `longitude`.

Note: this API does not expose email addresses or owner/contact names, and the
directory is US-only (the country is therefore not a column).

## CALECIM Professional pro-directory

Scrapes the salon/clinic directory map on
[calecimprofessional.com/pages/pro-directory](https://calecimprofessional.com/pages/pro-directory).

The map is powered by the **Stockist** store-locator widget
(`data-stockist-widget-tag="u7465"`), whose public endpoint returns every
location in a single request:

```
https://stockist.co/api/v1/u7465/locations/all
```

```bash
python calecim_directory_scraper.py          # writes calecim_directory.csv
python calecim_directory_scraper.py --debug  # also saves the raw API response
```

Output columns (~2,900 worldwide locations): `id`, `name`, `contact_name`
(owner / practitioner, from the Stockist description field), `category`
(Salons or Clinics), `address_line_1`, `address_line_2`, `city`, `state`,
`postal_code`, `country`, `phone`, `landline`, `email`, `website`,
`short_address`, `hair_treatments`, `latitude`, `longitude`.

## Owner first-name finder (Alastin leads)

`find_owner_first_names.py` fills the `first_name` column (owner / founder /
principal provider) for the clinic leads in
`alastin 800 leads test names search.csv` using **only free sources**, run
concurrently so the full 838-row file finishes in minutes rather than the
~800 minutes a manual "search each clinic by hand" loop would take.

It runs four tiers, each only handling rows the previous tiers left empty:

1. **Email local-part** — personal business emails (`jane@clinic.com`),
   precision-filtered against a known-first-name dictionary (`first_names.json`)
   so business names (`bellezaspa.llc@`) and role accounts (`ap@`, `info@`) are
   rejected.
2. **NPI registry** — the free CMS NPPES API; takes the authorized-official
   name for clinics registered as medical organizations. Highest yield.
3. **Website crawl** — derives the clinic domain from its email, fetches
   About/Team pages with plain concurrent HTTP (no browser), and extracts the
   owner via schema.org JSON-LD + heuristics (titles and accreditation-board
   names are filtered out).
4. **DuckDuckGo HTML search** — keyless fallback for whatever remains.

```bash
python find_owner_first_names.py            # full file
python find_owner_first_names.py --limit=25 # quick test on first 25 rows
```

Output: `alastin 800 leads test names search_with_first_names.csv` (same `;`
format, original columns plus filled `first_name`, `owner_full_name`, and
`first_name_source` = email / npi / website / search). Network responses are
cached under `./cache` so reruns are free.

**Coverage is honest, not padded.** On this file it fills ~28% (NPI ~223,
website ~14, email ~1); rows where no free source exposes an owner name are
left blank rather than guessed. Many small aesthetic businesses simply don't
publish an owner name anywhere free — reaching 80%+ would require paid
enrichment APIs (Apollo, Clearbit, People Data Labs).

## Notes

- Not every field is populated for every location — the scrapers write
  whatever the directory provides and leave missing values blank.
- Values entered free-form by listees (e.g. `country` in the CALECIM data)
  vary in format: `US`, `USA` and `United States` all appear.
