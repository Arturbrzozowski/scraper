#!/usr/bin/env python3
"""
DNA Store Locator Scraper

This scraper extracts store location data from the DNA store locator page
(Blipstar widget) and saves it to a CSV file with the following columns:
- store_name
- address
- city
- state
- zip_code
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
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright, Page, Browser, Route


@dataclass
class StoreLocation:
    """Represents a store location with its details."""
    store_name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone_number: str
    email: str
    website: str


class DNAStoreScraper:
    """Scraper for DNA store locator page (Blipstar widget)."""

    # Blipstar map widget URL
    URL = "https://viewer.blipstar.com/map?uid=4734573&width=auto"
    OUTPUT_FILE = "dna_stores.csv"

    def __init__(self, headless: bool = True, timeout: int = 60000, debug: bool = False):
        """
        Initialize the scraper.

        Args:
            headless: Run browser in headless mode (no GUI)
            timeout: Default timeout in milliseconds
            debug: Save debug files (screenshot, HTML)
        """
        self.headless = headless
        self.timeout = timeout
        self.debug = debug
        self.stores: list[StoreLocation] = []
        self.captured_api_responses: list[dict] = []

    async def _save_debug_files(self, page: Page):
        """Save page screenshot and HTML for debugging."""
        print("Saving debug files...")
        try:
            await page.screenshot(path="debug_screenshot.png", full_page=True)
            print("  Saved: debug_screenshot.png")
        except Exception as e:
            print(f"  Failed to save screenshot: {e}")

        try:
            html_content = await page.content()
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("  Saved: debug_page.html")
        except Exception as e:
            print(f"  Failed to save HTML: {e}")

        # Also save captured API responses
        try:
            if self.captured_api_responses:
                with open("debug_api_responses.json", "w", encoding="utf-8") as f:
                    json.dump(self.captured_api_responses, f, indent=2)
                print(f"  Saved: debug_api_responses.json ({len(self.captured_api_responses)} responses)")
        except Exception as e:
            print(f"  Failed to save API responses: {e}")

    async def _handle_response(self, response):
        """Capture API responses that might contain store data."""
        url = response.url
        content_type = response.headers.get("content-type", "")

        # Look for JSON responses that might contain store data
        keywords = ["store", "location", "marker", "dealer", "retailer", "pin", "branch", "api", "json", "blipstar", "search", "data"]
        is_json = "application/json" in content_type
        is_blipstar = "blipstar" in url.lower()
        has_keyword = any(kw in url.lower() for kw in keywords)

        if is_json or is_blipstar or has_keyword:
            try:
                if response.status == 200:
                    body = await response.text()
                    if body and len(body) > 10:
                        # Try to parse as JSON
                        try:
                            data = json.loads(body)
                            print(f"  [API Capture] Found JSON response from: {url[:100]}")
                            self.captured_api_responses.append({
                                "url": url,
                                "data": data
                            })
                        except json.JSONDecodeError:
                            # Check for JSONP or other formats
                            if is_blipstar and ("name" in body.lower() or "address" in body.lower()):
                                print(f"  [API Capture] Found potential Blipstar data in: {url[:100]}")
                                # Try to extract JSON from JSONP callback
                                jsonp_match = re.search(r'\w+\s*\(\s*(\[[\s\S]*\]|\{[\s\S]*\})\s*\)', body)
                                if jsonp_match:
                                    try:
                                        data = json.loads(jsonp_match.group(1))
                                        self.captured_api_responses.append({
                                            "url": url,
                                            "data": data
                                        })
                                    except json.JSONDecodeError:
                                        pass
            except Exception:
                pass

    async def scrape(self) -> list[StoreLocation]:
        """
        Main scraping method.

        Returns:
            List of StoreLocation objects
        """
        import shutil
        import os
        async with async_playwright() as p:
            # Use system Chromium if available, otherwise fall back to Playwright's bundled browser
            chromium_path = shutil.which("chromium")
            launch_options = {
                "headless": self.headless,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--ignore-certificate-errors",
                ]
            }
            if chromium_path:
                launch_options["executable_path"] = chromium_path

            # Configure proxy if environment variable is set
            proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
            if proxy_url:
                # Parse proxy URL to extract credentials if present
                parsed = urlparse(proxy_url)
                proxy_config = {
                    "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
                }
                if parsed.username:
                    proxy_config["username"] = parsed.username
                if parsed.password:
                    proxy_config["password"] = parsed.password
                launch_options["proxy"] = proxy_config
                print(f"Using proxy: {parsed.hostname}:{parsed.port}")

            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Set up network interception to capture API responses
            page.on("response", self._handle_response)

            try:
                # Load the Blipstar map widget
                print(f"Loading page: {self.URL}")
                await page.goto(self.URL, wait_until="domcontentloaded", timeout=self.timeout)

                # Wait for the map to initialize
                print("Waiting for Blipstar widget to initialize...")
                await page.wait_for_timeout(5000)

                # Try to extract stores from Blipstar widget
                stores = await self._extract_from_blipstar(page)

                # Save debug files if requested
                if self.debug:
                    await self._save_debug_files(page)

                if not stores:
                    # Try to extract from captured API responses
                    stores = self._extract_from_api_responses()

                if not stores:
                    # Try standard extraction methods
                    stores = await self._extract_stores(page)

                if not stores:
                    print("Attempting alternative extraction methods...")
                    stores = await self._extract_from_scripts(page)

                if not stores:
                    stores = await self._extract_from_map_markers(page)

                if not stores:
                    # Try clicking on map elements to reveal store info
                    stores = await self._interact_with_map(page)

                self.stores = stores

            except Exception as e:
                print(f"Error during scraping: {e}")
                raise
            finally:
                await browser.close()

        return self.stores

    async def _extract_from_blipstar(self, page: Page) -> list[StoreLocation]:
        """Extract stores from the Blipstar map widget."""
        stores = []
        print("Extracting from Blipstar widget...")

        try:
            # Blipstar uses a search form - we need to trigger a search to load locations
            # First, check if there's a search input and trigger a broad search
            search_input = await page.query_selector('input[name="q"], input[type="text"], #searchInput, .search-input')

            if search_input:
                # Search for "USA" or use a central US location to get all stores
                print("  Triggering search for all US locations...")
                await search_input.fill("United States")
                await page.wait_for_timeout(1000)

                # Try to submit the form or press Enter
                await search_input.press("Enter")
                await page.wait_for_timeout(5000)

            # Try to extract location data from JavaScript variables
            store_data = await page.evaluate("""
                () => {
                    const results = [];

                    // Look for Blipstar-specific data structures
                    // Blipstar typically stores data in window.locations or similar
                    const checkVars = ['locations', 'markers', 'storeData', 'locData',
                                       'allLocations', 'mapData', 'locationData', 'results'];

                    for (const varName of checkVars) {
                        if (window[varName] && Array.isArray(window[varName])) {
                            return window[varName];
                        }
                    }

                    // Check for Leaflet layers with location data
                    if (window.map && window.map._layers) {
                        const layers = Object.values(window.map._layers);
                        for (const layer of layers) {
                            if (layer.options && layer.options.locations) {
                                return layer.options.locations;
                            }
                            // Check for marker clusters
                            if (layer._markers && Array.isArray(layer._markers)) {
                                return layer._markers.map(m => m.options || m);
                            }
                        }
                    }

                    // Look for data in global scope
                    for (const key of Object.keys(window)) {
                        if (key.startsWith('_') || key === 'window') continue;
                        try {
                            const val = window[key];
                            if (Array.isArray(val) && val.length > 0 && val.length < 10000) {
                                const first = val[0];
                                if (first && typeof first === 'object') {
                                    const keys = Object.keys(first).join(',').toLowerCase();
                                    if (keys.includes('name') || keys.includes('address') ||
                                        keys.includes('lat') || keys.includes('lng')) {
                                        return val;
                                    }
                                }
                            }
                        } catch (e) {}
                    }

                    return results;
                }
            """)

            if store_data and isinstance(store_data, list) and len(store_data) > 0:
                print(f"  Found {len(store_data)} locations in Blipstar widget")
                for item in store_data:
                    store = self._parse_blipstar_location(item)
                    if store:
                        stores.append(store)

            # Also try to extract from the results list in the DOM
            if not stores:
                stores = await self._extract_blipstar_from_dom(page)

        except Exception as e:
            print(f"  Error extracting from Blipstar widget: {e}")

        return stores

    def _parse_blipstar_location(self, data: dict) -> Optional[StoreLocation]:
        """Parse a Blipstar location object into StoreLocation."""
        if not isinstance(data, dict):
            return None

        # Blipstar field mapping based on fieldOrder:
        # ['distance','icon','logo','name','address','country','phone','website','email','opening','misc1','misc2','misc3','misc4','tags','thumb','social']

        name = data.get('name', '') or data.get('title', '') or ''
        address = data.get('address', '') or data.get('street', '') or ''
        phone = data.get('phone', '') or data.get('telephone', '') or ''
        email = data.get('email', '') or ''
        website = data.get('website', '') or data.get('url', '') or ''

        # Extract city, state, zip from address if not separate fields
        city = data.get('city', '') or ''
        state = data.get('state', '') or data.get('province', '') or ''
        zip_code = data.get('zip', '') or data.get('zipcode', '') or data.get('postal_code', '') or ''

        # If city/state/zip not separate, try to parse from address
        if address and (not city or not state or not zip_code):
            parsed_city, parsed_state, parsed_zip = self._extract_city_state_zip_from_text(address)
            if not city:
                city = parsed_city
            if not state:
                state = parsed_state
            if not zip_code:
                zip_code = parsed_zip

        if name or address:
            return StoreLocation(
                store_name=str(name).strip(),
                address=str(address).strip(),
                city=str(city).strip(),
                state=str(state).strip(),
                zip_code=str(zip_code).strip(),
                phone_number=str(phone).strip(),
                email=str(email).strip(),
                website=str(website).strip()
            )

        return None

    async def _extract_blipstar_from_dom(self, page: Page) -> list[StoreLocation]:
        """Extract store data from Blipstar DOM elements."""
        stores = []

        # Common Blipstar result selectors
        selectors = [
            ".location-result", ".store-result", ".result-item",
            ".leaflet-popup-content", "[data-location]",
            ".location-details", ".store-info"
        ]

        for selector in selectors:
            elements = await page.query_selector_all(selector)
            if elements:
                print(f"  Found {len(elements)} DOM elements: {selector}")
                for el in elements:
                    store = await self._parse_store_element(el)
                    if store:
                        stores.append(store)
                if stores:
                    break

        return stores

    async def _extract_from_progus_widget(self, page: Page) -> list[StoreLocation]:
        """Extract stores from the Progus Commerce store locator widget."""
        stores = []
        print("Extracting from Progus Commerce widget...")

        try:
            # The Progus widget stores data in JavaScript - try to extract it
            store_data = await page.evaluate("""
                () => {
                    // Try to find store data in various locations
                    const results = [];

                    // Check for Progus-specific data structures
                    if (window.Progus && window.Progus.locations) {
                        return window.Progus.locations;
                    }

                    // Check for MapLibre markers or features
                    if (window.map && window.map.getSource) {
                        try {
                            const source = window.map.getSource('locations');
                            if (source && source._data) {
                                return source._data.features || source._data;
                            }
                        } catch (e) {}
                    }

                    // Look for any global variables containing location arrays
                    const varNames = ['locations', 'stores', 'markers', 'storeData', 'locationData'];
                    for (const name of varNames) {
                        if (window[name] && Array.isArray(window[name])) {
                            return window[name];
                        }
                    }

                    // Try to find data in the DOM
                    const dataElements = document.querySelectorAll('[data-locations], [data-stores]');
                    for (const el of dataElements) {
                        const data = el.dataset.locations || el.dataset.stores;
                        if (data) {
                            try {
                                return JSON.parse(data);
                            } catch (e) {}
                        }
                    }

                    return results;
                }
            """)

            if store_data and isinstance(store_data, list):
                print(f"  Found {len(store_data)} locations in widget")
                for item in store_data:
                    store = self._parse_json_store(item)
                    if store:
                        stores.append(store)

            # Also try to find store list elements in the widget DOM
            list_selectors = [
                ".location-item", ".store-item", ".location-card",
                "[data-location-id]", ".progus-location", ".sl-location",
                ".location-list-item", ".store-list-item"
            ]

            for selector in list_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"  Found {len(elements)} elements with selector: {selector}")
                    for el in elements:
                        store = await self._parse_store_element(el)
                        if store:
                            stores.append(store)

        except Exception as e:
            print(f"  Error extracting from Progus widget: {e}")

        return stores

    async def _extract_from_iframes(self, page: Page) -> list[StoreLocation]:
        """Extract store data from iframes (common for third-party store locators)."""
        stores = []

        # Find all iframes on the page
        iframes = await page.query_selector_all("iframe")
        print(f"Found {len(iframes)} iframes on page")

        for i, iframe in enumerate(iframes):
            src = await iframe.get_attribute("src") or ""
            print(f"  Iframe {i+1}: {src[:100] if src else '(no src)'}")

            # Check for known store locator services (including Progus)
            if any(service in src.lower() for service in [
                "storemapper", "storepoint", "stockist", "storelocator",
                "bullseye", "destini", "yext", "locatorhq", "mapquest",
                "progus", "sl-widget"
            ]):
                print(f"  -> Detected third-party store locator service")

                try:
                    frame = await iframe.content_frame()
                    if frame:
                        # Wait for the frame content to load
                        print("    Waiting for iframe to fully load...")
                        await page.wait_for_timeout(5000)

                        # For Progus widget, try specialized extraction
                        if "progus" in src.lower() or "sl-widget" in src.lower():
                            frame_stores = await self._extract_from_progus_frame(frame)
                            stores.extend(frame_stores)
                        else:
                            # Try extraction methods within the frame
                            frame_stores = await self._extract_stores_from_frame(frame)
                            stores.extend(frame_stores)
                except Exception as e:
                    print(f"  -> Error accessing iframe: {e}")

        return stores

    async def _extract_from_progus_frame(self, frame) -> list[StoreLocation]:
        """Extract stores from a Progus Commerce iframe."""
        stores = []
        print("    Extracting from Progus Commerce iframe...")

        try:
            # Wait for the map to initialize
            await frame.wait_for_timeout(3000)

            # Try to get store data from the frame's JavaScript context
            store_data = await frame.evaluate("""
                () => {
                    const results = [];

                    // Try to find Progus data structures
                    if (window.Progus && window.Progus.locations) {
                        return window.Progus.locations;
                    }

                    // Look for MapLibre map instance
                    if (window.map) {
                        // Try to get features from map source
                        try {
                            const sources = window.map.style.sourceCaches;
                            for (const key in sources) {
                                const source = sources[key];
                                if (source._data && source._data.features) {
                                    return source._data.features;
                                }
                            }
                        } catch (e) {}

                        // Try getSource method
                        try {
                            const source = window.map.getSource('locations') ||
                                           window.map.getSource('markers') ||
                                           window.map.getSource('stores');
                            if (source && source._data) {
                                return source._data.features || source._data;
                            }
                        } catch (e) {}
                    }

                    // Look for any arrays that might contain store data
                    const checkObject = (obj, depth = 0) => {
                        if (depth > 3 || !obj) return null;
                        if (Array.isArray(obj) && obj.length > 0) {
                            // Check if it looks like store data
                            const first = obj[0];
                            if (first && typeof first === 'object') {
                                const keys = Object.keys(first).join(',').toLowerCase();
                                if (keys.includes('name') || keys.includes('address') ||
                                    keys.includes('lat') || keys.includes('lng') ||
                                    keys.includes('properties')) {
                                    return obj;
                                }
                            }
                        }
                        if (typeof obj === 'object') {
                            for (const key in obj) {
                                const result = checkObject(obj[key], depth + 1);
                                if (result) return result;
                            }
                        }
                        return null;
                    };

                    // Check common global variables
                    for (const name of Object.keys(window)) {
                        if (name.startsWith('_') || name === 'window') continue;
                        try {
                            const result = checkObject(window[name]);
                            if (result) return result;
                        } catch (e) {}
                    }

                    return results;
                }
            """)

            if store_data and isinstance(store_data, list) and len(store_data) > 0:
                print(f"    Found {len(store_data)} locations in Progus iframe")
                for item in store_data:
                    store = self._parse_json_store(item)
                    if store:
                        stores.append(store)

            # Also try extracting from visible DOM elements
            if not stores:
                # Look for location list items
                list_selectors = [
                    ".location-item", ".store-item", "[data-location]",
                    ".marker-info", ".store-info", ".location-details"
                ]

                for selector in list_selectors:
                    elements = await frame.query_selector_all(selector)
                    if elements:
                        print(f"    Found {len(elements)} DOM elements: {selector}")
                        for el in elements:
                            store = await self._parse_store_element(el)
                            if store:
                                stores.append(store)

        except Exception as e:
            print(f"    Error extracting from Progus frame: {e}")

        return stores

    async def _extract_stores_from_frame(self, frame) -> list[StoreLocation]:
        """Extract stores from an iframe's content."""
        stores = []

        # Get the frame's HTML content
        try:
            content = await frame.content()

            # Look for store data in the frame's scripts
            scripts = await frame.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script');
                    const data = [];
                    scripts.forEach(s => {
                        if (s.textContent) data.push(s.textContent);
                    });
                    return data;
                }
            """)

            for script_content in scripts:
                stores.extend(self._extract_stores_from_script_content(script_content))

            # Try common selectors in the frame
            selectors = [
                ".store-item", ".location-item", ".store-listing",
                ".ssm-marker-content", ".stockist-result",
                "[data-store]", "[data-location]", ".marker-content"
            ]

            for selector in selectors:
                elements = await frame.query_selector_all(selector)
                if elements:
                    print(f"    Found {len(elements)} elements with selector: {selector}")
                    for el in elements:
                        store = await self._parse_store_element(el)
                        if store:
                            stores.append(store)

        except Exception as e:
            print(f"    Error extracting from frame: {e}")

        return stores

    def _extract_stores_from_script_content(self, script_content: str) -> list[StoreLocation]:
        """Extract stores from script content."""
        stores = []

        # Common patterns for store data in scripts
        patterns = [
            r'locations\s*[=:]\s*(\[[\s\S]*?\]);',
            r'stores\s*[=:]\s*(\[[\s\S]*?\]);',
            r'markers\s*[=:]\s*(\[[\s\S]*?\]);',
            r'"locations"\s*:\s*(\[[\s\S]*?\])',
            r'"stores"\s*:\s*(\[[\s\S]*?\])',
            r'"features"\s*:\s*(\[[\s\S]*?\])',  # GeoJSON format
            r'window\.locations\s*=\s*(\[[\s\S]*?\]);',
            r'var\s+locations\s*=\s*(\[[\s\S]*?\]);',
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
                except json.JSONDecodeError:
                    pass

        return stores

    def _extract_from_api_responses(self) -> list[StoreLocation]:
        """Extract stores from captured API responses."""
        stores = []

        print(f"Processing {len(self.captured_api_responses)} captured API responses...")

        for response in self.captured_api_responses:
            data = response["data"]

            # Handle various API response structures
            if isinstance(data, list):
                for item in data:
                    store = self._parse_json_store(item)
                    if store:
                        stores.append(store)
            elif isinstance(data, dict):
                # Look for nested arrays
                for key in ["locations", "stores", "results", "data", "features", "items", "markers"]:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            store = self._parse_json_store(item)
                            if store:
                                stores.append(store)

                # Also try parsing the dict itself
                if not stores:
                    store = self._parse_json_store(data)
                    if store:
                        stores.append(store)

        return stores

    async def _interact_with_map(self, page: Page) -> list[StoreLocation]:
        """Try clicking on map markers to reveal store information."""
        stores = []

        print("Attempting to interact with map markers...")

        # Common map marker selectors
        marker_selectors = [
            ".gm-style img[src*='marker']",  # Google Maps markers
            ".leaflet-marker-icon",           # Leaflet markers
            "[data-marker]",
            ".map-marker",
            ".store-marker",
            ".location-marker",
            "img[src*='pin']",
            "button[aria-label*='marker']",
            ".ssm-marker",  # Storemapper markers
        ]

        for selector in marker_selectors:
            markers = await page.query_selector_all(selector)
            if markers:
                print(f"  Found {len(markers)} markers with selector: {selector}")

                # Click on each marker and extract info
                for i, marker in enumerate(markers[:50]):  # Limit to avoid too many clicks
                    try:
                        await marker.click()
                        await page.wait_for_timeout(500)

                        # Look for info popup that appeared
                        info_selectors = [
                            ".gm-style-iw", ".info-window", ".popup",
                            ".marker-popup", ".store-popup", ".location-info",
                            ".ssm-popup", ".stockist-popup"
                        ]

                        for info_sel in info_selectors:
                            info_element = await page.query_selector(info_sel)
                            if info_element:
                                store = await self._parse_store_element(info_element)
                                if store and store not in stores:
                                    stores.append(store)
                                    print(f"    Extracted store: {store.store_name}")
                                break

                    except Exception as e:
                        pass  # Marker might not be clickable

        return stores

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
                "[data-address]", ".street"
            ]) or self._extract_address_from_text(text_content)

            # Extract city
            city = await self._find_text(element, [
                ".city", "[data-city]", ".locality"
            ]) or ""

            # Extract state
            state = await self._find_text(element, [
                ".state", "[data-state]", ".region", ".province"
            ]) or ""

            # Extract zip code
            zip_code = await self._find_text(element, [
                ".zip", ".zipcode", ".zip-code", "[data-zip]",
                ".postal-code", ".postcode"
            ]) or ""

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

            if name != "Unknown Store" or address or city:
                return StoreLocation(
                    store_name=name.strip(),
                    address=address.strip() if address else "",
                    city=city.strip() if city else "",
                    state=state.strip() if state else "",
                    zip_code=zip_code.strip() if zip_code else "",
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

        # Handle GeoJSON format (features have "properties" containing data)
        if "properties" in data and isinstance(data["properties"], dict):
            data = data["properties"]

        # Handle nested "attributes" field (common in some APIs)
        if "attributes" in data and isinstance(data["attributes"], dict):
            data = {**data, **data["attributes"]}

        # Common field names for store data
        name_fields = ['name', 'store_name', 'storeName', 'title', 'business_name',
                       'Name', 'StoreName', 'company', 'Company', 'dealer_name', 'retailer_name']
        address_fields = ['address', 'full_address', 'street', 'location', 'Address',
                          'formatted_address', 'address1', 'street_address']
        city_fields = ['city', 'City', 'town', 'Town', 'locality']
        state_fields = ['state', 'State', 'province', 'Province', 'region', 'Region']
        zip_fields = ['zip', 'zipcode', 'zip_code', 'postal_code', 'postalCode',
                      'Zip', 'ZipCode', 'PostalCode', 'postcode']
        phone_fields = ['phone', 'telephone', 'tel', 'phone_number', 'phoneNumber',
                        'Phone', 'contact_phone', 'mobile']
        email_fields = ['email', 'mail', 'email_address', 'emailAddress', 'Email', 'contact_email']
        website_fields = ['website', 'url', 'web', 'site', 'Website', 'Url', 'homepage']

        name = self._get_first_value(data, name_fields) or "Unknown Store"
        address = self._get_first_value(data, address_fields) or ""
        city = self._get_first_value(data, city_fields) or ""
        state = self._get_first_value(data, state_fields) or ""
        zip_code = self._get_first_value(data, zip_fields) or ""
        phone = self._get_first_value(data, phone_fields) or ""
        email = self._get_first_value(data, email_fields) or ""
        website = self._get_first_value(data, website_fields) or ""

        # Build address from components if not found
        if not address:
            parts = []
            for field in ['street', 'street1', 'street2', 'address1', 'address2']:
                if field in data and data[field]:
                    parts.append(str(data[field]))
            address = ", ".join(parts)

        if name != "Unknown Store" or address or city:
            return StoreLocation(
                store_name=str(name).strip(),
                address=str(address).strip(),
                city=str(city).strip(),
                state=str(state).strip(),
                zip_code=str(zip_code).strip(),
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
        city, state, zip_code = self._extract_city_state_zip_from_text(text)
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
                city=city or "",
                state=state or "",
                zip_code=zip_code or "",
                phone_number=phone or "",
                email=email or "",
                website=website or ""
            )

        return None

    def _extract_city_state_zip_from_text(self, text: str) -> tuple[str, str, str]:
        """Extract city, state, and zip code from text."""
        city, state, zip_code = "", "", ""

        # Pattern: City, ST 12345 or City, State 12345
        pattern = r'([A-Za-z\s]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)'
        match = re.search(pattern, text)
        if match:
            city = match.group(1).strip()
            state = match.group(2).strip()
            zip_code = match.group(3).strip()
            return city, state, zip_code

        # Try just zip code
        zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', text)
        if zip_match:
            zip_code = zip_match.group(1)

        # Try state abbreviation
        state_match = re.search(r'\b([A-Z]{2})\b', text)
        if state_match:
            state = state_match.group(1)

        return city, state, zip_code

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
                'store_name', 'address', 'city', 'state', 'zip_code',
                'phone_number', 'email', 'website'
            ])
            writer.writeheader()

            for store in self.stores:
                writer.writerow(asdict(store))

        print(f"Saved {len(self.stores)} stores to {output_file}")
        return output_file


async def main():
    """Main entry point."""
    print("=" * 60)
    print("DNA Store Locator Scraper")
    print("=" * 60)

    # Check for command-line flags
    headless = "--no-headless" not in sys.argv
    debug = "--debug" in sys.argv

    if debug:
        print("Debug mode enabled - will save screenshot and HTML")

    scraper = DNAStoreScraper(headless=headless, debug=debug)

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
                if store.city or store.state or store.zip_code:
                    print(f"   Location: {store.city}, {store.state} {store.zip_code}".strip())
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
