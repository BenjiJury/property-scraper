"""
scraper.py — Fetches listings from Rightmove.

How data is extracted
---------------------
Rightmove embeds all search-result data as a JSON blob in a
<script id="__NEXT_DATA__" type="application/json"> tag on every results
page (the site migrated to Next.js).  We extract that JSON and navigate to
props.pageProps.searchResults, which contains the properties list, result
count, and pagination metadata.

Previously the data was assigned to `window.jsonModel`; that approach no
longer works as of early 2026.

Pagination
----------
The pagination.next field in the searchResults JSON gives the 0-based index
of the next page (increments of 24).  We follow pages until there is no next
index or we hit MAX_PAGES_PER_AREA.

Freehold filtering
------------------
Rightmove does not reliably expose tenure in search-result JSON.
config.FILTER_FREEHOLD removes any listing whose tenure field is
explicitly "leasehold"; listings with tenure "freehold", "share_of_freehold",
or "unknown" are kept.  The scraper also strips new-build / shared-ownership
flags at the URL level with dontShow=newHome,sharedOwnership,retirement.
"""

import json
import logging
import random
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from config import (
    FILTER_FREEHOLD,
    MAX_PAGES_PER_AREA,
    MIN_BEDROOMS,
    MAX_BEDROOMS,
    MIN_PRICE,
    MAX_PRICE,
    PROPERTY_TYPES,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    REQUEST_TIMEOUT,
    SEARCH_LOCATIONS,
)

logger = logging.getLogger(__name__)

_BASE_URL    = "https://www.rightmove.co.uk"
_SEARCH_PATH = "/property-for-sale/find.html"

# ── Request headers ────────────────────────────────────────────────────────────
# A pool of realistic browser User-Agent strings; one is chosen at random for
# each request to reduce the chance of pattern-based blocking.

_HEADERS_POOL = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "none",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-GB,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
    },
]


def _random_headers() -> dict:
    return dict(random.choice(_HEADERS_POOL))


def _delay() -> None:
    """Sleep for a randomised interval between requests."""
    secs = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    logger.debug("Waiting %.1f s before next request", secs)
    time.sleep(secs)


# ── URL builder ────────────────────────────────────────────────────────────────

def _search_url(location_identifier: str, index: int = 0) -> str:
    params = {
        "locationIdentifier": location_identifier,
        "minBedrooms":        MIN_BEDROOMS,
        "maxBedrooms":        MAX_BEDROOMS,
        "minPrice":           MIN_PRICE,
        "maxPrice":           MAX_PRICE,
        "propertyTypes":      ",".join(PROPERTY_TYPES),
        "mustHave":           "",
        "dontShow":           "newHome,sharedOwnership,retirement",
        "furnishTypes":       "",
        "keywords":           "",
        "index":              index,
    }
    return f"{_BASE_URL}{_SEARCH_PATH}?{urlencode(params)}"


# ── HTTP fetch ─────────────────────────────────────────────────────────────────

def _fetch(url: str, session: requests.Session) -> str | None:
    """
    GET a URL and return the response text, or None on any error.
    Handles 429 with exponential back-off: 3 attempts with 60 s and 120 s waits.
    """
    for attempt, wait in enumerate([0, 60, 120], start=1):
        if wait:
            logger.warning(
                "Rate-limited — backing off %ds before attempt %d/3", wait, attempt
            )
            time.sleep(wait)
        try:
            response = session.get(
                url,
                headers=_random_headers(),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if response.status_code == 429:
                logger.warning("Rate-limited (429) on attempt %d/3", attempt)
                continue   # next iteration will sleep before retrying
            if response.status_code == 403:
                logger.warning("Blocked (403) fetching %s", url)
                return None
            response.raise_for_status()
            return response.text
        except requests.ConnectionError as exc:
            logger.error("Connection error fetching %s: %s", url, exc)
            return None
        except requests.Timeout:
            logger.error("Timeout fetching %s", url)
            return None
        except requests.RequestException as exc:
            logger.error("HTTP error fetching %s: %s", url, exc)
            return None

    logger.warning("Rate-limited (429) after 3 attempts — giving up on %s", url)
    return None


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_next_data(html: str) -> dict | None:
    """
    Pull the search results from the __NEXT_DATA__ JSON embedded in the page.

    Rightmove migrated to Next.js in early 2026.  All search-result data is
    now embedded as a JSON blob in:
        <script id="__NEXT_DATA__" type="application/json">...</script>

    The search results payload is at props.pageProps.searchResults and
    contains:
        - properties:   list of listing dicts
        - resultCount:  total matching listings (int)
        - pagination:   dict with 'next' key (str index of next page, or absent)
    """
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        logger.warning("Could not find __NEXT_DATA__ in page")
        return None
    try:
        page_data = json.loads(m.group(1))
        search_results = (
            page_data
            .get("props", {})
            .get("pageProps", {})
            .get("searchResults")
        )
        if search_results is None:
            logger.warning("searchResults key missing from __NEXT_DATA__")
        return search_results
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse __NEXT_DATA__ JSON: %s", exc)
        return None


# ── Square footage parser ──────────────────────────────────────────────────────

def _parse_sq_footage(text: str) -> int | None:
    """
    Parse a Rightmove displaySize string into sq ft (integer).

    Examples:
        "1,120 sq. ft."  → 1120
        "120 sq. m"      → 1292   (120 × 10.764)
        ""               → None
    """
    if not text:
        return None
    text = text.strip()

    # Extract the leading number (may contain commas)
    m = re.match(r"^([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None

    # Determine unit from the remainder of the string
    remainder = text[m.end():].lower()
    if "sq. m" in remainder or "sqm" in remainder or "m²" in remainder:
        value = value * 10.7639  # convert sq m → sq ft
    # Otherwise assume sq ft (covers "sq. ft.", "sqft", etc.)

    return int(round(value))


# ── Property parser ────────────────────────────────────────────────────────────

def _parse_property(raw: dict, area_name: str) -> dict | None:
    """
    Convert a raw Rightmove property dict into our standard listing dict.
    Returns None if the listing is missing required fields.
    """
    try:
        listing_id = str(raw.get("id", "")).strip()
        if not listing_id:
            return None

        price_block = raw.get("price") or {}
        price       = price_block.get("amount", 0)
        if not price:
            return None

        # Property sub-type ("Detached", "Semi-Detached", "Terraced", …)
        prop_type = raw.get("propertySubType") or raw.get("propertyType") or ""

        # Tenure — not always present in search JSON; default to "unknown".
        # Values from Rightmove are uppercase: FREEHOLD, LEASEHOLD,
        # SHARE_OF_FREEHOLD.  Normalise to lowercase for consistent filtering.
        tenure_raw = raw.get("tenure") or {}
        if isinstance(tenure_raw, dict):
            tenure = (tenure_raw.get("tenureType") or "unknown").lower()
        elif isinstance(tenure_raw, str):
            tenure = tenure_raw.lower()
        else:
            tenure = "unknown"

        # Skip explicit leaseholds when filter is enabled
        if FILTER_FREEHOLD and tenure == "leasehold":
            return None

        # Listing / first-visible date
        update_block = raw.get("listingUpdate") or {}
        listing_date = (
            update_block.get("listingUpdateDate")
            or raw.get("firstVisibleDate")
            or ""
        )
        if "T" in listing_date:
            listing_date = listing_date.split("T")[0]

        # Full URL
        prop_url = raw.get("propertyUrl", "")
        if prop_url and not prop_url.startswith("http"):
            prop_url = _BASE_URL + prop_url

        # Location (lat/lng)
        location  = raw.get("location") or {}
        latitude  = location.get("latitude")
        longitude = location.get("longitude")

        # Square footage
        display_size = raw.get("displaySize", "") or ""
        sq_footage   = _parse_sq_footage(display_size)

        return {
            "listing_id":    listing_id,
            "address":       raw.get("displayAddress") or "Unknown",
            "price":         int(price),
            "bedrooms":      raw.get("bedrooms"),
            "bathrooms":     raw.get("bathrooms"),
            "property_type": prop_type,
            "tenure":        tenure,
            "area":          area_name,
            "listing_url":   prop_url,
            "listing_date":  listing_date,
            "latitude":      latitude,
            "longitude":     longitude,
            "sq_footage":    sq_footage,
        }

    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Skipping malformed property (id=%s): %s", raw.get("id"), exc)
        return None


# ── Public helpers ─────────────────────────────────────────────────────────────

def lookup_location(query: str) -> list:
    """
    Query Rightmove's typeahead API for a place name.
    Returns a list of {"displayName": str, "identifier": str} dicts.

    The typeahead endpoint expects the query tokenised into two-character
    chunks separated by slashes, e.g. "cornwall" → "CO/RN/WA/LL".

    Usage:
        python3 -c "from scraper import lookup_location; print(lookup_location('Wandsworth'))"
    """
    try:
        q = query.upper().replace(" ", "")
        token_path = "/".join(q[i:i+2] for i in range(0, len(q), 2))
        url = f"{_BASE_URL}/typeAhead/uknostreet/{token_path}/"
        resp = requests.get(
            url,
            headers=_random_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "displayName": loc.get("displayName", ""),
                "identifier":  loc.get("locationIdentifier", ""),
            }
            for loc in data.get("typeAheadLocations", [])
        ]
    except Exception as exc:
        logger.error("Location lookup failed for '%s': %s", query, exc)
        return []


def scrape_listing_page(listing_id: str, session: requests.Session) -> int | None:
    """
    Fetch an individual Rightmove listing page and return sq_footage (sq ft), or None.

    Individual listing pages contain richer data than search results — in
    particular, displaySize is present for many listings that don't expose it
    in the search-result JSON.
    """
    url  = f"{_BASE_URL}/properties/{listing_id}"
    html = _fetch(url, session)
    if not html:
        return None

    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        logger.debug("No __NEXT_DATA__ on listing page %s", listing_id)
        return None

    try:
        page_data  = json.loads(m.group(1))
        page_props = page_data.get("props", {}).get("pageProps", {}) or {}

        # Navigate to the property detail object — path varies by page type
        prop = (
            page_props.get("propertyData")
            or page_props.get("property")
            or {}
        )

        # displaySize is a top-level field on the property object
        display_size = prop.get("displaySize", "") or ""

        # Also check sizings array (alternative schema used on some listing types)
        if not display_size:
            sizings = prop.get("sizings") or []
            if sizings and isinstance(sizings, list):
                display_size = sizings[0].get("displaySize", "") or ""

        return _parse_sq_footage(display_size)
    except Exception as exc:
        logger.debug("Error parsing listing page %s: %s", listing_id, exc)
        return None


# ── Area scraper ───────────────────────────────────────────────────────────────

def _scrape_area(location: dict, session: requests.Session) -> list:
    """Scrape all result pages for one location. Returns a list of listings."""
    name       = location["name"]
    identifier = location["identifier"]
    results    = []
    page_index = 0

    logger.info("Scraping: %s (%s)", name, identifier)

    while True:
        if page_index > 0:
            _delay()

        url  = _search_url(identifier, page_index)
        html = _fetch(url, session)

        if not html:
            logger.warning("%s — failed to fetch page at index %d; stopping.", name, page_index)
            break

        data = _extract_next_data(html)
        if not data:
            logger.warning("%s — no search results data at index %d; stopping.", name, page_index)
            break

        properties = data.get("properties") or []
        if not properties:
            logger.debug("%s — empty properties list at index %d", name, page_index)
            break

        # Log total on first page only
        if page_index == 0:
            raw_count = data.get("resultCount", "0")
            try:
                total = int(str(raw_count).replace(",", "").strip())
            except ValueError:
                total = "?"
            logger.info("%s — %s total results", name, total)

        for raw in properties:
            parsed = _parse_property(raw, name)
            if parsed:
                results.append(parsed)

        logger.debug(
            "%s — page %d → %d listings accumulated",
            name, page_index // 24 + 1, len(results),
        )

        # Follow pagination
        pagination = data.get("pagination") or {}
        next_val   = pagination.get("next")
        if next_val is None:
            break
        next_index = int(next_val)
        if next_index <= page_index:
            break
        if next_index >= MAX_PAGES_PER_AREA * 24:
            logger.warning("%s — reached page cap (%d pages)", name, MAX_PAGES_PER_AREA)
            break
        page_index = next_index

    logger.info("%s — done (%d listings)", name, len(results))
    return results


# ── Main entry point ───────────────────────────────────────────────────────────

def scrape_all() -> list:
    """
    Scrape every configured area and return a deduplicated list of listings.

    Deduplication is by listing_id because the same property can appear in
    multiple area searches (e.g. a house on the Wandsworth/Lambeth border).
    The last area to return a listing wins, so more-specific area names placed
    later in SEARCH_LOCATIONS (e.g. Teddington after Richmond, Herne Hill
    after Lambeth) correctly relabel overlapping listings.
    """
    session  = requests.Session()
    seen: dict[str, dict] = {}

    for i, location in enumerate(SEARCH_LOCATIONS):
        if i > 0:
            _delay()
        try:
            for listing in _scrape_area(location, session):
                seen[listing["listing_id"]] = listing
        except Exception as exc:
            logger.error("Unhandled error scraping %s: %s", location["name"], exc)

    logger.info("Scrape complete — %d unique listings", len(seen))
    return list(seen.values())
