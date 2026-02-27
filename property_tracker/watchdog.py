"""
watchdog.py — Alert via ntfy if the scraper hasn't run in > STALE_HOURS hours.
Intended to be called by property-tracker-watchdog.timer every 30 minutes.
"""

import logging
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

from config import DB_PATH, NTFY_URL, NTFY_VERIFY_SSL

STALE_HOURS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("watchdog")


def main() -> None:
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
        row  = conn.execute(
            "SELECT MAX(last_seen) FROM listings"
        ).fetchone()
        conn.close()
    except Exception as exc:
        logger.error("DB read failed: %s", exc)
        return

    if not row or not row[0]:
        return   # empty DB — nothing to alert on

    ts = row[0]
    # DB stores UTC ISO timestamps without timezone suffix (e.g. "2026-02-27T14:30:00.123456")
    # Make them timezone-aware so we can subtract from datetime.now(timezone.utc)
    if ts.endswith("+00:00") or ts.endswith("Z"):
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        last = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)

    age = datetime.now(timezone.utc) - last

    if age > timedelta(hours=STALE_HOURS):
        hours = round(age.total_seconds() / 3600, 1)
        msg = f"Property tracker silent for {hours}h — check Pi"
        logger.warning(msg)
        ok = _send(msg)
        if ok:
            logger.info("Watchdog alert sent successfully")
        else:
            logger.error("Watchdog alert failed to send")
    else:
        mins = round(age.total_seconds() / 60)
        logger.info("Scraper last ran %d min ago — OK", mins)


def _send(message: str) -> bool:
    if not NTFY_URL:
        return False
    import requests
    try:
        resp = requests.post(
            NTFY_URL,
            data=message.encode(),
            headers={"Title": "Scraper alert", "Priority": "high", "Tags": "warning"},
            timeout=10,
            verify=NTFY_VERIFY_SSL,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("ntfy POST failed: %s", exc)
        return False


if __name__ == "__main__":
    main()
