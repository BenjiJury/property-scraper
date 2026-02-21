"""
config.py — Search parameters and application settings.

Finding / updating location identifiers
----------------------------------------
Rightmove uses internal numeric IDs for every region and outcode.
Three ways to find the correct identifier for an area:

  1. Visit rightmove.co.uk, search for the area, and copy the
     'locationIdentifier' value from the URL.
     e.g. https://www.rightmove.co.uk/property-for-sale/find.html?locationIdentifier=REGION%5E93924

  2. Run the built-in lookup helper:
       python3 -c "
       from scraper import lookup_location
       for r in lookup_location('Wandsworth'): print(r)
       "

  3. Use Rightmove's typeahead API directly:
       curl 'https://api.rightmove.co.uk/api/typeAhead/uknoauth?query=Wandsworth&numberOfSuggestions=5'
"""

import os

# ── Search criteria ────────────────────────────────────────────────────────────

MIN_BEDROOMS = 3
MAX_BEDROOMS = 4
MIN_PRICE    = 900_000
MAX_PRICE    = 1_100_000

# Rightmove propertyTypes param values (houses = detached/semi/terraced)
PROPERTY_TYPES = ["detached", "semi-detached", "terraced"]

# Post-scrape tenure filter: keep "freehold" and "unknown" tenure,
# discard explicit "leasehold" listings.
FILTER_FREEHOLD = True

# Any price drop triggers a notification (threshold = 0 means any reduction).
PRICE_DROP_THRESHOLD = 0

# ── Rightmove location identifiers ────────────────────────────────────────────
#
# Coverage:
#   Wandsworth  — SW11 (Battersea), SW12 (Balham), SW17 (Tooting),
#                 SW18 (Wandsworth Town)
#   Lambeth     — SE11 (Kennington), SW4 (Clapham), SW8 (S.Lambeth),
#                 SW9 (Brixton/Stockwell), SE24 (Herne Hill)
#   Lewisham    — SE4, SE6, SE12, SE13, SE14, SE23, SE21/SE22 (Dulwich border)
#   Kingston    — KT1, KT2
#   Merton      — SW19 (Wimbledon), SW20, CR4
#   Richmond    — TW1, TW2, TW9, TW10
#
# Note: Lambeth's REGION^93799 has been migrated to Rightmove's new Next.js
# architecture and serves a client-side shell page with no listing data in HTML.
# It is replaced here with individual outcode entries which remain on the old
# server-rendered stack.  OUTCODE IDs are verified from live Rightmove URLs
# (SW4=2517, SW8=2521 confirmed; others derived from the sequential pattern
# visible in the existing SE21=2050, SE22=2051, SE24=2053 entries below).
#
# Herne Hill (SE24) falls within the Lambeth region.
# Dulwich (SE21) and East Dulwich (SE22) fall within Lewisham/Lambeth regions.
# Uncomment the outcode entries below for finer-grained targeting.

SEARCH_LOCATIONS = [
    {"name": "Wandsworth",           "identifier": "REGION^93977"},
    # ── Tooting (SW17) ────────────────────────────────────────────────────────
    # SW17 is already included in the Wandsworth region above; listings will
    # appear labelled "Wandsworth".  A separate OUTCODE^2530 entry was tried
    # but that outcode has migrated to Rightmove's Next.js stack and cannot be
    # scraped without a headless browser.
    #
    # Lambeth (REGION^93799) and all its outcode pages have been migrated to
    # Rightmove's Next.js client-side architecture.  Listing data is fetched
    # by browser JavaScript via tokens we cannot replicate without a headless
    # browser.  Outcode entries below were tested and all return the same
    # empty shell; they are commented out to avoid dead run time.
    # {"name": "Lambeth (SE11/Kennington)", "identifier": "OUTCODE^2040"},
    # {"name": "Lambeth (SW4/Clapham)",     "identifier": "OUTCODE^2517"},
    # {"name": "Lambeth (SW8/S.Lambeth)",   "identifier": "OUTCODE^2521"},
    # {"name": "Lambeth (SW9/Brixton)",     "identifier": "OUTCODE^2522"},
    # {"name": "Lambeth (SE24/Herne Hill)", "identifier": "OUTCODE^2053"},
    {"name": "Lewisham",             "identifier": "REGION^61413"},
    {"name": "Kingston upon Thames", "identifier": "REGION^93968"},
    {"name": "Richmond upon Thames", "identifier": "REGION^93937"},
    # ── Teddington (TW11) ─────────────────────────────────────────────────────
    # TW11 is NOT covered by Richmond upon Thames (REGION^93937 covers TW1/2/9/10 only).
    # OUTCODE^2644 was tried but pointed to Devon — IDs are not assigned in
    # postal-code order.  To find the correct ID, visit:
    #   rightmove.co.uk → search "Teddington" → copy locationIdentifier from URL
    # or run from ~/property-scraper:
    #   python3 -c "import sys,sys; sys.path.insert(0,'property_tracker'); from scraper import lookup_location; [print(r) for r in lookup_location('Teddington')]"
    # {"name": "Teddington (TW11)",    "identifier": "OUTCODE^????"},
    #
    # ── Dulwich ───────────────────────────────────────────────────────────────
    # East Dulwich (SE22) is within Lewisham borough and is already covered by
    # the Lewisham region above (listings labelled "Lewisham").
    # Dulwich (SE21) spans Lewisham and Southwark; the Southwark portion is not
    # covered.  OUTCODE^2050 was tried for SE21 but hits Next.js (same issue as
    # Lambeth above).  To cover Southwark/SE21 add the Southwark REGION once
    # you have the correct ID:
    #   rightmove.co.uk → search "Southwark" → copy locationIdentifier from URL
    # {"name": "Southwark",            "identifier": "REGION^?????"},
    #
    # ── Bermondsey (SE1 / SE16) ───────────────────────────────────────────────
    # Both SE1 and SE16 outcodes have migrated to Rightmove's Next.js stack and
    # cannot be scraped without a headless browser.  Bermondsey is in Southwark
    # borough — once you have the Southwark REGION ID (see above), those
    # listings will be covered automatically.
]

# ── Request / scraping settings ────────────────────────────────────────────────

REQUEST_DELAY_MIN  = 4    # seconds  — minimum wait between HTTP requests
REQUEST_DELAY_MAX  = 10   # seconds  — maximum wait between HTTP requests
REQUEST_TIMEOUT    = 30   # seconds  — HTTP request timeout
MAX_PAGES_PER_AREA = 20   # safety cap (24 results/page → 480 max per area)

# ── File paths ────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "properties.db")
LOG_PATH = os.path.join(BASE_DIR, "tracker.log")

# ── Termux notification settings ──────────────────────────────────────────────

# Set to False to disable notifications (useful for testing on desktop)
TERMUX_API_AVAILABLE = True

NOTIFICATION_ID_NEW  = 1001   # Android notification ID for new listings
NOTIFICATION_ID_DROP = 1002   # Android notification ID for price drops

# ── Dashboard display settings ────────────────────────────────────────────────

SHOW_REMOVED_LISTINGS = True   # Show de-listed properties (dimmed) in table

# ── Export settings ───────────────────────────────────────────────────────────

# Discord: paste your webhook URL here (Server Settings → Integrations → Webhooks)
# Leave empty ("") to disable Discord export.
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1474878416619835613/7MSv7qIIGB27zqNvUaaVGrnSJHI0ZZ14PMOgJ3m0QdqAP1i0cOb2tXCVuW94GWxTOtDJ"

# PDF and CSV output directory (defaults to the same folder as this file)
EXPORT_DIR = BASE_DIR
