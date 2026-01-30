#!/usr/bin/env python3
"""
Circadia Store Locator Scraper

This scraper extracts store location data from the Circadia store locator page
and saves it to a CSV file with the following columns:
- store_name
- address
- phone_number
- email
- website

Uses Playwright for browser automation to handle dynamic JavaScript content.
"""

import asyncio
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Optional
from playwright.async_api import async_playwright, Page, Browser


@dataclass
class StoreLocation:
    """Represents a store location with its details."""
    store_name: str
    address: str
    phone_number: str
    email: str
    website: str


class CircadiaStoreScraper:
    """Scraper for Circadia store locator page."""

    URL = "https://circadia.com/pages/store-locator"
    OUTPUT_FILE = "circadia_stores.csv"

    def __init__(self, headless: bool = True, timeout: int = 60000):
        """
        Initialize the scraper.

        Args:
            headless: Run browser in headless mode (no GUI)
            timeout: Default timeout in milliseconds
        """
        self.headless = headless
        self.timeout = timeout
        self.stores: list[StoreLocation] = []

    async def scrape(self) -> list[StoreLocation]:
        """
        Main scraping method.

        Returns:
            List of StoreLocation objects
        """
        import shutil
        async with async_playwright() as p:
            # Use system Chromium if available, otherwise fall back to Playwright's bundled browser
            chromium_path = shutil.which("chromium")
            launch_options = {"headless": self.headless}
            if chromium_path:
                launch_options["executable_path"] = chromium_path
            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                print(f"Loading page: {self.URL}")
                await page.goto(self.URL, wait_until="domcontentloaded", timeout=self.timeout)

                # Wait for potential dynamic content to load
                await page.wait_for_timeout(3000)

                # Try multiple extraction strategies
                stores = await self._extract_stores(page)

                if not stores:
                    print("Attempting alternative extraction methods...")
                    stores = await self._extract_from_scripts(page)

                if not stores:
                    stores = await self._extract_from_map_markers(page)

                if not stores:
                    stores = await self._extract_from_visible_content(page)

                self.stores = stores

            except Exception as e:
                print(f"Error during scraping: {e}")
                raise
            finally:
                await browser.close()

        return self.stores

    async def _extract_stores(self, page: Page) -> list[StoreLocation]:
        """
        Primary extraction method - look for common store list patterns.
        """
        stores = []

        # Common selectors for store locator listings
        selectors = [
            ".store-item",
            ".location-item",
            ".store-listing",
            ".store-card",
            "[data-store]",
            "[data-location]",
            ".marker-info",
            ".info-window",
            ".store-info",
            ".location-info",
            ".store-details",
            ".dealer-item",
            ".retailer-item",
            ".salon-item",
            ".spa-item",
        ]

        for selector in selectors:
            elements = await page.query_selector_all(selector)
            if elements:
                print(f"Found {len(elements)} elements with selector: {selector}")
                for el in elements:
                    store = await self._parse_store_element(el)
                    if store:
                        stores.append(store)

        return stores

    async def _parse_store_element(self, element) -> Optional[StoreLocation]:
        """Parse a store element and extract its data."""
        try:
            text_content = await element.text_content() or ""
            inner_html = await element.inner_html() or ""

            # Extract store name
            name = await self._find_text(element, [
                ".store-name", ".location-name", ".name", "h2", "h3", "h4",
                "[data-name]", ".title"
            ]) or "Unknown Store"

            # Extract address
            address = await self._find_text(element, [
                ".address", ".store-address", ".location-address",
                "[data-address]", ".street", ".city"
            ]) or self._extract_address_from_text(text_content)

            # Extract phone
            phone = await self._find_text(element, [
                ".phone", ".tel", ".telephone", "[data-phone]",
                "a[href^='tel:']"
            ]) or self._extract_phone_from_text(text_content)

            # Extract email
            email = await self._find_text(element, [
                ".email", "[data-email]", "a[href^='mailto:']"
            ]) or self._extract_email_from_text(text_content)

            # Extract website
            website = await self._find_href(element, [
                ".website", ".url", "a.external", "[data-website]"
            ]) or self._extract_website_from_html(inner_html)

            if name != "Unknown Store" or address:
                return StoreLocation(
                    store_name=name.strip(),
                    address=address.strip() if address else "",
                    phone_number=phone.strip() if phone else "",
                    email=email.strip() if email else "",
                    website=website.strip() if website else ""
                )
        except Exception as e:
            print(f"Error parsing store element: {e}")

        return None

    async def _find_text(self, element, selectors: list[str]) -> Optional[str]:
        """Find text content using multiple selectors."""
        for selector in selectors:
            try:
                sub_element = await element.query_selector(selector)
                if sub_element:
                    text = await sub_element.text_content()
                    if text and text.strip():
                        return text.strip()
            except:
                pass
        return None

    async def _find_href(self, element, selectors: list[str]) -> Optional[str]:
        """Find href attribute using multiple selectors."""
        for selector in selectors:
            try:
                sub_element = await element.query_selector(selector)
                if sub_element:
                    href = await sub_element.get_attribute("href")
                    if href and not href.startswith(("tel:", "mailto:")):
                        return href
            except:
                pass
        return None

    async def _extract_from_scripts(self, page: Page) -> list[StoreLocation]:
        """Extract store data from inline scripts and JSON."""
        stores = []

        # Look for JSON data in script tags
        scripts = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script');
                const data = [];
                scripts.forEach(s => {
                    if (s.textContent) {
                        data.push(s.textContent);
                    }
                });
                return data;
            }
        """)

        for script_content in scripts:
            # Look for common patterns
            patterns = [
                r'locations\s*[=:]\s*(\[[\s\S]*?\])',
                r'stores\s*[=:]\s*(\[[\s\S]*?\])',
                r'markers\s*[=:]\s*(\[[\s\S]*?\])',
                r'"locations"\s*:\s*(\[[\s\S]*?\])',
                r'"stores"\s*:\s*(\[[\s\S]*?\])',
                r'__STORE_DATA__\s*=\s*(\{[\s\S]*?\})',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, script_content, re.IGNORECASE)
                for match in matches:
                    try:
                        data = json.loads(match)
                        if isinstance(data, list):
                            for item in data:
                                store = self._parse_json_store(item)
                                if store:
                                    stores.append(store)
                        elif isinstance(data, dict) and 'locations' in data:
                            for item in data['locations']:
                                store = self._parse_json_store(item)
                                if store:
                                    stores.append(store)
                    except json.JSONDecodeError:
                        pass

        return stores

    def _parse_json_store(self, data: dict) -> Optional[StoreLocation]:
        """Parse a JSON object representing a store."""
        if not isinstance(data, dict):
            return None

        # Common field names for store data
        name_fields = ['name', 'store_name', 'storeName', 'title', 'business_name']
        address_fields = ['address', 'full_address', 'street', 'location']
        phone_fields = ['phone', 'telephone', 'tel', 'phone_number', 'phoneNumber']
        email_fields = ['email', 'mail', 'email_address', 'emailAddress']
        website_fields = ['website', 'url', 'web', 'site']

        name = self._get_first_value(data, name_fields) or "Unknown Store"
        address = self._get_first_value(data, address_fields) or ""
        phone = self._get_first_value(data, phone_fields) or ""
        email = self._get_first_value(data, email_fields) or ""
        website = self._get_first_value(data, website_fields) or ""

        # Build address from components if not found
        if not address:
            parts = []
            for field in ['street', 'street1', 'street2', 'city', 'state', 'zip', 'postal_code', 'country']:
                if field in data and data[field]:
                    parts.append(str(data[field]))
            address = ", ".join(parts)

        if name != "Unknown Store" or address:
            return StoreLocation(
                store_name=str(name).strip(),
                address=str(address).strip(),
                phone_number=str(phone).strip(),
                email=str(email).strip(),
                website=str(website).strip()
            )

        return None

    def _get_first_value(self, data: dict, fields: list[str]) -> Optional[str]:
        """Get the first non-empty value from a list of field names."""
        for field in fields:
            if field in data and data[field]:
                return str(data[field])
        return None

    async def _extract_from_map_markers(self, page: Page) -> list[StoreLocation]:
        """Extract data from Google Maps markers or similar map implementations."""
        stores = []

        # Try to get map marker data from window objects
        marker_data = await page.evaluate("""
            () => {
                const results = [];

                // Check for Google Maps markers
                if (window.google && window.google.maps) {
                    // Try to find map instances
                    const maps = document.querySelectorAll('[data-map]');
                    maps.forEach(m => {
                        if (m.__gmap && m.__gmap.markers) {
                            m.__gmap.markers.forEach(marker => {
                                results.push({
                                    name: marker.title || '',
                                    lat: marker.position?.lat(),
                                    lng: marker.position?.lng()
                                });
                            });
                        }
                    });
                }

                // Check for common store locator variables
                const varNames = ['storeLocations', 'locations', 'stores', 'markers', 'mapData'];
                varNames.forEach(name => {
                    if (window[name] && Array.isArray(window[name])) {
                        results.push(...window[name]);
                    }
                });

                return results;
            }
        """)

        if marker_data:
            for item in marker_data:
                if isinstance(item, dict):
                    store = self._parse_json_store(item)
                    if store:
                        stores.append(store)

        return stores

    async def _extract_from_visible_content(self, page: Page) -> list[StoreLocation]:
        """
        Fallback: Extract from visible page content by looking for patterns.
        """
        stores = []

        # Get all text content from the page
        content = await page.content()

        # Look for info window content (common in Google Maps implementations)
        info_patterns = [
            r'<div[^>]*class="[^"]*info[^"]*"[^>]*>([\s\S]*?)</div>',
            r'<div[^>]*class="[^"]*store[^"]*"[^>]*>([\s\S]*?)</div>',
            r'<div[^>]*class="[^"]*location[^"]*"[^>]*>([\s\S]*?)</div>',
        ]

        for pattern in info_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                store = self._parse_html_store_block(match)
                if store:
                    stores.append(store)

        return stores

    def _parse_html_store_block(self, html: str) -> Optional[StoreLocation]:
        """Parse a block of HTML that might contain store info."""
        # Remove HTML tags for text extraction
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) < 10:
            return None

        address = self._extract_address_from_text(text)
        phone = self._extract_phone_from_text(text)
        email = self._extract_email_from_text(text)
        website = self._extract_website_from_html(html)

        # Try to extract name (usually first line or bold text)
        name_match = re.search(r'<(?:strong|b|h\d)[^>]*>([^<]+)</(?:strong|b|h\d)>', html)
        name = name_match.group(1).strip() if name_match else ""

        if not name and text:
            # Take first line as name
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            if lines:
                name = lines[0][:100]

        if name or address or phone or email:
            return StoreLocation(
                store_name=name or "Unknown Store",
                address=address or "",
                phone_number=phone or "",
                email=email or "",
                website=website or ""
            )

        return None

    def _extract_address_from_text(self, text: str) -> str:
        """Extract an address from text using patterns."""
        # US address pattern
        patterns = [
            r'\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct)[\s,]+[\w\s]+,?\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?',
            r'\d+\s+[\w\s]+,\s*[\w\s]+,\s*[A-Z]{2}\s+\d{5}',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return ""

    def _extract_phone_from_text(self, text: str) -> str:
        """Extract a phone number from text."""
        patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
            r'\+1[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip()
        return ""

    def _extract_email_from_text(self, text: str) -> str:
        """Extract an email address from text."""
        pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        match = re.search(pattern, text)
        return match.group(0) if match else ""

    def _extract_website_from_html(self, html: str) -> str:
        """Extract a website URL from HTML."""
        pattern = r'href=["\']?(https?://[^"\'\s>]+)'
        matches = re.findall(pattern, html, re.IGNORECASE)
        for url in matches:
            # Skip common non-store URLs
            if not any(skip in url.lower() for skip in ['facebook', 'twitter', 'instagram', 'linkedin', 'tel:', 'mailto:', 'javascript:']):
                return url
        return ""

    def save_to_csv(self, filename: Optional[str] = None) -> str:
        """
        Save extracted stores to CSV.

        Args:
            filename: Output filename (defaults to circadia_stores.csv)

        Returns:
            Path to the saved file
        """
        output_file = filename or self.OUTPUT_FILE

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'store_name', 'address', 'phone_number', 'email', 'website'
            ])
            writer.writeheader()

            for store in self.stores:
                writer.writerow(asdict(store))

        print(f"Saved {len(self.stores)} stores to {output_file}")
        return output_file


async def main():
    """Main entry point."""
    print("=" * 60)
    print("Circadia Store Locator Scraper")
    print("=" * 60)

    # Check for headless flag
    headless = "--no-headless" not in sys.argv

    scraper = CircadiaStoreScraper(headless=headless)

    try:
        stores = await scraper.scrape()

        if stores:
            print(f"\nFound {len(stores)} store locations!")
            scraper.save_to_csv()

            # Print first few stores as preview
            print("\nPreview of extracted data:")
            print("-" * 40)
            for i, store in enumerate(stores[:5]):
                print(f"\n{i+1}. {store.store_name}")
                if store.address:
                    print(f"   Address: {store.address}")
                if store.phone_number:
                    print(f"   Phone: {store.phone_number}")
                if store.email:
                    print(f"   Email: {store.email}")
                if store.website:
                    print(f"   Website: {store.website}")

            if len(stores) > 5:
                print(f"\n... and {len(stores) - 5} more stores")
        else:
            print("\nNo store locations found.")
            print("\nPossible reasons:")
            print("1. The store locator requires authentication/login")
            print("2. Store data is loaded via a protected API")
            print("3. The page structure has changed")
            print("\nTry running with --no-headless to see the browser.")

            # Save empty CSV with headers
            scraper.save_to_csv()

    except Exception as e:
        print(f"\nError: {e}")
        print("\nMake sure Playwright browsers are installed:")
        print("  playwright install chromium")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
