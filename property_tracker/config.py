"""
config.py — Search parameters and application settings.

Finding / updating location identifiers
----------------------------------------
Rightmove uses internal numeric IDs for every region and outcode.
Three ways to find the correct identifier for an area:

  1. Visit rightmove.co.uk, search for the area, and copy the
     'locationIdentifier' value from the URL.
     e.g. https://www.rightmove.co.uk/property-for-sale/find.html?locationIdentifier=REGION%5E93977

  2. Run the built-in lookup helper:
       python3 -c "
       from scraper import lookup_location
       for r in lookup_location('Wandsworth'): print(r)
       "

  3. Use Rightmove's typeahead API directly (two-character token path):
       curl 'https://www.rightmove.co.uk/typeAhead/uknostreet/WA/ND/SW/OR/TH/'
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
#   Lambeth     — SE11, SW4 (Clapham), SW8, SW9, SE24 (Herne Hill)
#   Lewisham    — SE4, SE6, SE12, SE13, SE14, SE23, SE21/SE22 (Dulwich border)
#   Kingston    — KT1, KT2
#   Merton      — SW19 (Wimbledon), SW20, CR4
#   Richmond    — TW1, TW2, TW9, TW10
#
# Identifiers updated 2026-02-22 using the typeAhead endpoint:
#   https://www.rightmove.co.uk/typeAhead/uknostreet/{TOKEN}/
#
# Herne Hill (SE24) falls within the Lambeth region.
# Dulwich (SE21) and East Dulwich (SE22) fall within Lewisham/Lambeth regions.
# Uncomment the outcode entries below for finer-grained targeting.

SEARCH_LOCATIONS = [
    {"name": "Wandsworth",           "identifier": "REGION^93977"},
    {"name": "Lambeth",              "identifier": "REGION^93971"},
    {"name": "Lewisham",             "identifier": "REGION^61413"},
    {"name": "Kingston upon Thames", "identifier": "REGION^93968"},
    {"name": "Merton",               "identifier": "REGION^61414"},
    {"name": "Richmond upon Thames", "identifier": "REGION^61415"},
    # Outcode-level alternatives (uncomment for tighter targeting):
    # {"name": "Dulwich (SE21)",     "identifier": "OUTCODE^2050"},
    # {"name": "East Dulwich (SE22)","identifier": "OUTCODE^2051"},
    # {"name": "Herne Hill (SE24)",  "identifier": "OUTCODE^2053"},
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

# ── Notification settings ──────────────────────────────────────────────────────

# ntfy push notification URL.
# Self-hosted (Docker/apt): http://localhost/<topic>
# Cloud:                    https://ntfy.sh/<topic>
# Leave empty ("") to disable notifications.
NTFY_URL = "https://ntfy.home.lan/keng-kxm29"

# ── Dashboard display settings ────────────────────────────────────────────────

SHOW_REMOVED_LISTINGS = True   # Show de-listed properties (dimmed) in table
