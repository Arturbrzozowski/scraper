# CALECIM Professional Pro-Directory Scraper

A Python scraper that extracts the salon/clinic directory data behind the
locations map on
[calecimprofessional.com/pages/pro-directory](https://calecimprofessional.com/pages/pro-directory)
and saves it to a CSV file.

## How it works

The directory map is powered by the **Stockist** store-locator widget
(`data-stockist-widget-tag="u7465"`). Stockist exposes a public JSON endpoint
that returns every location in a single request:

```
https://stockist.co/api/v1/u7465/locations/all
```

Because the data is available directly from the API, no browser automation is
needed — the scraper uses only the Python standard library.

## Installation

No third-party dependencies are required (Python 3.9+). Just run the script:

```bash
python calecim_directory_scraper.py
```

To also save the raw API response for inspection:

```bash
python calecim_directory_scraper.py --debug
```

## Output

The scraper creates `calecim_directory.csv` (~2,900 locations) with the
following columns:

| Column | Description |
| --- | --- |
| `id` | Stockist location id |
| `name` | Clinic / salon name |
| `contact_name` | Owner / practitioner / contact (from the Stockist description field) |
| `category` | Salons or Clinics |
| `address_line_1` | Street address |
| `address_line_2` | Secondary address line |
| `city` | City |
| `state` | State / region |
| `postal_code` | Postcode / ZIP |
| `country` | Country |
| `phone` | Phone number |
| `landline` | Landline (custom field) |
| `email` | Email address |
| `website` | Website URL |
| `short_address` | Short address (custom field) |
| `hair_treatments` | Hair treatments available (custom field) |
| `latitude` | Latitude |
| `longitude` | Longitude |

## Notes

- Not every field is populated for every location — the script writes whatever
  the directory provides and leaves missing values blank.
- `country`, `state` and `city` values are entered free-form by listees, so
  formats vary (e.g. `US`, `USA` and `United States` all appear).
