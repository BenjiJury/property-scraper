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
#   Wandsworth    — SW11 (Battersea), SW12 (Balham), SW15 (Putney),
#                   SW17 (Tooting), SW18 (Wandsworth Town)
#   Lambeth       — SE11, SW4 (Clapham), SW8, SW9, SE24 (Herne Hill)
#   Kingston      — KT1, KT2
#   Richmond      — TW1, TW2, TW9, TW10
#   Wimbledon     — SW19, SW20
#   Teddington    — TW11
#   Herne Hill    — SE24 (also inside Lambeth; deduped by listing_id;
#                   SE24 listings relabelled "Herne Hill" on each run)
#   Tooting       — SW17 (more targeted label; also in Wandsworth region)
#   Dulwich       — SE21
#   East Dulwich  — SE22
#   West Dulwich  — SE21/SE27
#   Bermondsey    — SE1/SE16
#   Surbiton      — KT5/KT6
#
# Identifiers updated 2026-02-22 using the typeAhead endpoint:
#   https://www.rightmove.co.uk/typeAhead/uknostreet/{TOKEN}/
# Areas updated 2026-02-23: removed Merton, added Wimbledon/Teddington/Herne Hill.
# Areas updated 2026-02-24: removed Lewisham, added Tooting/Dulwich/East Dulwich/
#   Bermondsey/Surbiton.
# Areas updated 2026-02-27: added West Dulwich.

SEARCH_LOCATIONS = [
    {"name": "Wandsworth",           "identifier": "REGION^93977"},
    {"name": "Lambeth",              "identifier": "REGION^93971"},
    {"name": "Kingston upon Thames", "identifier": "REGION^93968"},
    {"name": "Richmond upon Thames", "identifier": "REGION^61415"},
    {"name": "Wimbledon",            "identifier": "REGION^87540"},
    {"name": "Teddington",           "identifier": "REGION^1321"},
    {"name": "Surbiton",             "identifier": "REGION^1296"},
    {"name": "Bermondsey",           "identifier": "REGION^85212"},
    {"name": "Tooting",              "identifier": "REGION^85419"},
    {"name": "Dulwich",              "identifier": "OUTCODE^2050"},
    {"name": "East Dulwich",         "identifier": "OUTCODE^2051"},
    {"name": "West Dulwich",         "identifier": "REGION^70448"},
    {"name": "Herne Hill",           "identifier": "OUTCODE^2053"},
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

# ── TfL journey time settings ─────────────────────────────────────────────────

COMMUTE_DEST       = "EC3V4AB"   # Bank / Monument, City of London
TFL_APP_KEY        = ""          # optional — register free at api.tfl.gov.uk
TFL_ARRIVE_TIME    = "0900"      # HHMM — target arrival time for comparison
TFL_ENRICH_MAX_RUN = 50          # max existing-listing backfills per run
