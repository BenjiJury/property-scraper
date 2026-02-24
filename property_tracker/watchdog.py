"""
watchdog.py — Alert via ntfy if the scraper hasn't run in > STALE_HOURS hours.
Intended to be called by property-tracker-watchdog.timer every 30 minutes.
"""

import sys
import sqlite3
from datetime import datetime, timezone, timedelta

from config import DB_PATH, NTFY_URL

STALE_HOURS = 3


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    row  = conn.execute(
        "SELECT MAX(last_seen) FROM listings"
    ).fetchone()
    conn.close()

    if not row or not row[0]:
        return   # empty DB — nothing to alert on

    last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    age  = datetime.now(timezone.utc) - last

    if age > timedelta(hours=STALE_HOURS):
        hours = round(age.total_seconds() / 3600, 1)
        _send(f"Property tracker silent for {hours}h — check Pi")


def _send(message: str) -> None:
    if not NTFY_URL:
        return
    import requests
    requests.post(
        NTFY_URL,
        data=message.encode(),
        headers={"Title": "Scraper alert", "Priority": "high", "Tags": "warning"},
        timeout=10,
    )


if __name__ == "__main__":
    main()
