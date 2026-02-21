"""
scraper.py — Fetches listings from Rightmove.

How data is extracted
---------------------
Rightmove is mid-migration from a server-rendered architecture to
Next.js with client-side data fetching.  We use a two-strategy approach:

  Strategy A (HTML extraction) — works for areas still on the old stack.
    The search-results HTML page embeds listing data in a window.jsonModel
    JS variable which _extract_json_model() pulls out via regex / BeautifulSoup.

  Strategy B (API fallback) — used when Strategy A finds nothing.
    Newer areas serve a Next.js shell page (no listing data in HTML); the
    browser then calls /api/_search to fetch listings as JSON.  We replicate
    this by fetching the HTML page first (which seeds the session with the
    necessary cookies) and then calling /api/_search with those cookies.

Pagination
----------
The pagination.next field gives the 0-based index of the next page
(increments of 24).  We follow pages until there is no next index or
we hit MAX_PAGES_PER_AREA.

Freehold filtering
------------------
Rightmove does not reliably expose tenure in search-result JSON.
config.FILTER_FREEHOLD removes any listing whose tenure field is
explicitly "leasehold"; listings with tenure "freehold" or "unknown"
are kept.  The scraper also strips new-build / shared-ownership flags
at the URL level with dontShow=newHome,sharedOwnership,retirement.

Location identifier lookup
--------------------------
Use lookup_location('Area Name') to resolve a place name to its
Rightmove REGION^ identifier via the typeahead API.
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
_SEARCH_PATH = "/property-for-sale/find.html"   # kept for warm-up referer
_API_SEARCH  = "/api/_search"
_TYPEAHEAD   = "https://www.rightmove.co.uk/typeAhead/uknostreet"

# ── Request headers ────────────────────────────────────────────────────────────
# A pool of realistic browser User-Agent strings; one is chosen at random for
# each request to reduce the chance of pattern-based blocking.

_HEADERS_POOL = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.6261.112 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language":           "en-GB,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Sec-Fetch-User":            "?1",
        "sec-ch-ua":                 '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "sec-ch-ua-mobile":          "?0",
        "sec-ch-ua-platform":        '"Windows"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.6261.112 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language":           "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Sec-Fetch-User":            "?1",
        "sec-ch-ua":                 '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "sec-ch-ua-mobile":          "?0",
        "sec-ch-ua-platform":        '"macOS"',
    },
]


def _random_headers(referer: str | None = None) -> dict:
    headers = dict(random.choice(_HEADERS_POOL))
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = "same-origin"
    return headers


def _delay() -> None:
    """Sleep for a randomised interval between requests."""
    secs = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    logger.debug("Waiting %.1f s before next request", secs)
    time.sleep(secs)


# ── URL builder ────────────────────────────────────────────────────────────────

def _api_search_url(location_identifier: str, index: int = 0) -> str:
    """Build a URL for Rightmove's internal JSON search API (Next.js fallback)."""
    params = {
        "locationIdentifier":        location_identifier,
        "numberOfPropertiesPerPage": 24,
        "radius":                    "0.0",
        "sortType":                  6,
        "index":                     index,
        "includeSSTC":               "false",
        "viewType":                  "LIST",
        "channel":                   "BUY",
        "areaSizeUnit":              "sqft",
        "currencyCode":              "GBP",
        "isFetching":                "false",
        "minBedrooms":               MIN_BEDROOMS,
        "maxBedrooms":               MAX_BEDROOMS,
        "minPrice":                  MIN_PRICE,
        "maxPrice":                  MAX_PRICE,
        "propertyTypes":             ",".join(PROPERTY_TYPES),
        "mustHave":                  "",
        "dontShow":                  "newHome,sharedOwnership,retirement",
    }
    # Keep literal '^' in locationIdentifier (urlencode produces %5E)
    return f"{_BASE_URL}{_API_SEARCH}?{urlencode(params)}".replace("%5E", "^")


def _search_url(location_identifier: str, index: int = 0) -> str:
    """Build a Rightmove search-results page URL."""
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

def _warm_up(session: requests.Session) -> None:
    """
    Prime the session with cookies before hitting the JSON API.

    Step 1 — homepage: establishes a session and picks up global cookies.
    Step 2 — search results HTML page: sets the search-specific cookies
              that the /api/_search endpoint checks for.
    """
    # Step 1: homepage
    try:
        resp = session.get(
            _BASE_URL,
            headers=_random_headers(),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        logger.debug("Warm-up homepage: HTTP %d", resp.status_code)
    except Exception as exc:
        logger.warning("Warm-up homepage failed (continuing): %s", exc)

    time.sleep(random.uniform(3, 5))

    # Step 2: a real search results page so we look like a genuine browser
    warmup_search = (
        f"{_BASE_URL}{_SEARCH_PATH}"
        "?locationIdentifier=REGION^93799"
        "&numberOfPropertiesPerPage=24&index=0&channel=BUY"
    )
    try:
        resp = session.get(
            warmup_search,
            headers=_random_headers(),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        logger.debug("Warm-up search page: HTTP %d", resp.status_code)
    except Exception as exc:
        logger.warning("Warm-up search page failed (continuing): %s", exc)

    time.sleep(random.uniform(3, 5))


def _fetch(url: str, session: requests.Session, referer: str | None = None) -> str | None:
    """
    GET a URL and return the response text, or None on any error.
    Handles 429 / 403 with a longer back-off before giving up.
    """
    for attempt in (1, 2):
        try:
            response = session.get(
                url,
                headers=_random_headers(referer=referer),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if response.status_code == 429:
                logger.warning("Rate-limited (429) on attempt %d — backing off 60 s", attempt)
                time.sleep(60)
                continue
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
    return None


def _random_xhr_headers(referer: str | None = None) -> dict:
    """Headers that mimic an XHR/fetch request from the Rightmove page."""
    base = random.choice(_HEADERS_POOL)
    return {
        "User-Agent":         base["User-Agent"],
        "Accept":             "application/json, text/plain, */*",
        "Accept-Language":    "en-GB,en;q=0.9",
        "Accept-Encoding":    "gzip, deflate, br",
        "Referer":            referer or f"{_BASE_URL}/property-for-sale/",
        "sec-ch-ua":          base.get("sec-ch-ua", ""),
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": base.get("sec-ch-ua-platform", '"Windows"'),
        "Sec-Fetch-Dest":     "empty",
        "Sec-Fetch-Mode":     "cors",
        "Sec-Fetch-Site":     "same-origin",
        "Connection":         "keep-alive",
    }


def _fetch_json(url: str, session: requests.Session, referer: str | None = None) -> dict | None:
    """
    GET a JSON API endpoint and return the parsed response, or None on error.
    Handles 429 with a back-off retry; treats 403/404 as hard stops.
    """
    for attempt in (1, 2):
        try:
            response = session.get(
                url,
                headers=_random_xhr_headers(referer=referer),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if response.status_code == 429:
                logger.warning("Rate-limited (429) on attempt %d — backing off 60 s", attempt)
                time.sleep(60)
                continue
            if response.status_code in (403, 404):
                logger.warning("HTTP %d fetching %s", response.status_code, url)
                return None
            response.raise_for_status()
            body = response.text
            if not body or not body.strip():
                logger.warning(
                    "Empty response body (HTTP %d) — bot detection likely; url=%s",
                    response.status_code, url,
                )
                return None
            if not body.lstrip().startswith("{"):
                logger.warning(
                    "Non-JSON response (HTTP %d, %d bytes): %.300s",
                    response.status_code,
                    len(body),
                    body[:300].replace("\n", " "),
                )
                return None
            return response.json()
        except requests.ConnectionError as exc:
            logger.error("Connection error fetching %s: %s", url, exc)
            return None
        except requests.Timeout:
            logger.error("Timeout fetching %s", url)
            return None
        except (requests.RequestException, ValueError) as exc:
            logger.error("Error fetching %s: %s", url, exc)
            return None
    return None


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json_model(html: str) -> dict | None:
    """
    Pull listing data out of the page HTML.

    Strategy 1 — window.jsonModel regex (old Rightmove architecture).
    Strategy 2 — BeautifulSoup window.jsonModel script tag search.
    Strategy 3 — Next.js __NEXT_DATA__ extraction (new architecture).
    """
    # Detect a hard "not found" page early so we get a clear log message.
    if "We couldn\u2019t find the place you were looking for" in html or \
       "We couldn't find the place you were looking for" in html:
        logger.warning("Rightmove returned a 'not found' page — location identifier may be stale")
        return None

    # Strategy 1: window.jsonModel — simple regex on full page text
    m = re.search(r"window\.jsonModel\s*=\s*(\{)", html)
    if m:
        start = m.start(1)
        json_str = _extract_balanced_json(html, start)
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as exc:
                logger.debug("Strategy-1 JSON decode failed: %s", exc)

    soup = None  # parsed once and reused by strategies 2 and 3

    # Strategy 2: window.jsonModel — BeautifulSoup script tag iteration
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("script"):
            text = tag.string or ""
            if "window.jsonModel" not in text:
                continue
            m2 = re.search(r"window\.jsonModel\s*=\s*(\{)", text)
            if not m2:
                continue
            json_str = _extract_balanced_json(text, m2.start(1))
            if json_str:
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as exc:
                    logger.debug("Strategy-2 JSON decode failed: %s", exc)
    except Exception as exc:
        logger.debug("BeautifulSoup parse error: %s", exc)

    # Strategy 3: Next.js __NEXT_DATA__ (Rightmove migrated to Next.js)
    try:
        if soup is None:
            soup = BeautifulSoup(html, "html.parser")
        next_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_tag and next_tag.string:
            next_data = json.loads(next_tag.string)
            page_props = next_data.get("props", {}).get("pageProps", {})
            # Rightmove nests results under various keys — try all known paths.
            properties = (
                page_props.get("properties")
                or page_props.get("searchResults", {}).get("properties")
                or page_props.get("results", {}).get("properties")
            )
            if properties is not None:
                logger.debug("Extracted %d properties via __NEXT_DATA__", len(properties))
                return {
                    "properties":  properties,
                    "pagination":  page_props.get("pagination", {}),
                    "resultCount": page_props.get("resultCount", len(properties)),
                }
            # Dump up to two levels of pageProps so we can find the right key path
            def _summarise(obj, depth=2):
                if depth == 0 or not isinstance(obj, dict):
                    return type(obj).__name__
                return {k: _summarise(v, depth - 1) for k, v in list(obj.items())[:10]}
            logger.warning(
                "__NEXT_DATA__ found but no 'properties' key; pageProps structure: %s",
                _summarise(page_props),
            )
    except Exception as exc:
        logger.debug("__NEXT_DATA__ extraction failed: %s", exc)

    logger.warning("Could not extract listing data from page")
    logger.warning("Page snippet (first 300 chars): %s", html[:300].replace("\n", " "))
    return None


def _extract_balanced_json(text: str, start: int) -> str | None:
    """
    Extract a balanced JSON object starting at position `start` in `text`.
    Returns the JSON string, or None if braces are unbalanced.
    """
    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text[start:]):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : start + i + 1]
    return None


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

        # Tenure — not always present in search JSON; default to "unknown"
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
        }

    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Skipping malformed property (id=%s): %s", raw.get("id"), exc)
        return None


# ── Public helpers ─────────────────────────────────────────────────────────────

def _tokenize_location(query: str) -> str:
    """
    Convert a place name to Rightmove's typeahead URL path format.
    e.g. "Wandsworth" → "WA/ND/SW/OR/TH"
         "Lewisham"   → "LE/WI/SH/AM"
    """
    clean = query.replace(" ", "").upper()
    return "/".join(clean[i:i + 2] for i in range(0, len(clean), 2))


def lookup_location(query: str) -> list:
    """
    Query Rightmove's typeahead API for a place name.
    Returns a list of {"displayName": str, "identifier": str} dicts.

    Usage:
        python3 -c "from scraper import lookup_location; print(lookup_location('Wandsworth'))"
    """
    url = f"{_TYPEAHEAD}/{_tokenize_location(query)}/"
    try:
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
        html = _fetch(url, session, referer=f"{_BASE_URL}/property-for-sale/")

        if not html:
            logger.warning("%s — failed to fetch page at index %d; stopping.", name, page_index)
            break

        # Detect stale identifier early — skip API fallback, it won't help either
        if ("We couldn\u2019t find the place you were looking for" in html
                or "We couldn't find the place you were looking for" in html):
            logger.warning("%s — 'not found' page; identifier may be stale", name)
            break

        data = _extract_json_model(html)
        if not data:
            # HTML extraction failed — page is probably a Next.js client-side
            # shell (listings fetched by browser JS via /api/_search).  The HTML
            # page visit above has seeded the session with the cookies the API
            # needs; try the JSON endpoint now with those credentials.
            logger.debug(
                "%s — HTML extraction failed; trying /api/_search with session cookies",
                name,
            )
            api_url = _api_search_url(identifier, page_index)
            data = _fetch_json(api_url, session, referer=url)

        if not data:
            logger.warning("%s — no listing data at index %d; stopping.", name, page_index)
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
    The first area that returns the listing wins.
    """
    session  = requests.Session()
    seen: dict[str, dict] = {}

    _warm_up(session)

    for i, location in enumerate(SEARCH_LOCATIONS):
        if i > 0:
            _delay()
        try:
            for listing in _scrape_area(location, session):
                if listing["listing_id"] not in seen:
                    seen[listing["listing_id"]] = listing
        except Exception as exc:
            logger.error("Unhandled error scraping %s: %s", location["name"], exc)

    logger.info("Scrape complete — %d unique listings", len(seen))
    return list(seen.values())
