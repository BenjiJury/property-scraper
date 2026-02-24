"""
tfl.py — Fetch public-transport journey time from a lat/lng to COMMUTE_DEST
         using the TfL Unified API.

Returns minutes (int) for the fastest journey arriving at TFL_ARRIVE_TIME
on a weekday, using tube/overground/elizabeth-line/national-rail.
Returns None on any API error or if no journey is found.
"""

import logging
import requests
from config import COMMUTE_DEST, TFL_APP_KEY, TFL_ARRIVE_TIME

logger = logging.getLogger(__name__)

_TFL_BASE = "https://api.tfl.gov.uk/Journey/JourneyResults"
_MODES    = "tube,overground,elizabeth-line,national-rail"
_DATE     = "20260309"   # Monday 9 Mar 2026 — fixed weekday for consistency


def get_journey_mins(lat: float, lng: float) -> int | None:
    """Return fastest journey time in minutes, or None on failure."""
    url    = f"{_TFL_BASE}/{lat},{lng}/to/{COMMUTE_DEST}"
    params = {
        "mode":   _MODES,
        "timeIs": "Arriving",
        "time":   TFL_ARRIVE_TIME.replace(":", ""),
        "date":   _DATE,
    }
    if TFL_APP_KEY:
        params["app_key"] = TFL_APP_KEY
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        journeys = r.json().get("journeys", [])
        if journeys:
            return min(j["duration"] for j in journeys)
    except Exception as exc:
        logger.debug("TfL API error for (%s,%s): %s", lat, lng, exc)
    return None
