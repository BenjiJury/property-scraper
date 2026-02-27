"""
tfl.py — Fetch public-transport journey time from a lat/lng to COMMUTE_DEST
         using the TfL Unified API.

Returns minutes (int) for the fastest journey arriving at TFL_ARRIVE_TIME
on a weekday, using tube/overground/elizabeth-line/national-rail.
Returns None on any API error or if no journey is found.
"""

import logging
from datetime import date, timedelta

import requests
from config import COMMUTE_DEST, TFL_APP_KEY, TFL_ARRIVE_TIME

logger = logging.getLogger(__name__)

_TFL_BASE = "https://api.tfl.gov.uk/Journey/JourneyResults"
_MODES    = "tube,overground,elizabeth-line,national-rail"


def _next_monday() -> str:
    """Return the date of the next Monday (or today if today is Monday) as YYYYMMDD."""
    d = date.today()
    days_ahead = (7 - d.weekday()) % 7 or 7   # days until next Monday (never 0)
    return (d + timedelta(days=days_ahead)).strftime("%Y%m%d")


# Computed once at import time — always a future Monday for consistent timetable data.
_DATE = _next_monday()


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
