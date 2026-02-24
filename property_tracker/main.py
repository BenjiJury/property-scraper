"""
main.py — Orchestrates the full scrape → track → notify pipeline.

Intended to be called by crond every 2 hours:
    0 */2 * * * cd ~/property_tracker && python3 main.py >> tracker.log 2>&1

Exit codes
----------
  0  — completed (even if no new listings found)
  1  — fatal error (DB init failed, scrape returned nothing recoverable)

All errors are logged to LOG_PATH (config.py) so cron failures are
self-documenting without flooding the terminal.
"""

import logging
import sys
from datetime import datetime

# ── Logging setup (must happen before any module imports that use logging) ─────

def _setup_logging() -> None:
    from config import LOG_PATH, TFL_ENRICH_MAX_RUN

    fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


# ── Pipeline ───────────────────────────────────────────────────────────────────

def main() -> None:
    _setup_logging()
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("Run started  %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))

    # 1 — Initialise database
    from database import init_db
    try:
        init_db()
    except Exception as exc:
        logger.critical("Database initialisation failed: %s", exc)
        sys.exit(1)

    # 2 — Scrape Rightmove
    from scraper import scrape_all
    try:
        listings = scrape_all()
    except Exception as exc:
        logger.critical("Scraper raised an unhandled exception: %s", exc)
        sys.exit(1)

    if not listings:
        logger.warning(
            "Scraper returned zero listings.  "
            "Check SEARCH_LOCATIONS identifiers in config.py and your "
            "network connection."
        )
        sys.exit(0)

    # 3 — Detect changes (new listings / price drops)
    from tracker import process_listings
    try:
        changes = process_listings(listings)
    except Exception as exc:
        logger.critical("Tracker raised an unhandled exception: %s", exc)
        sys.exit(1)

    # 4 — Send Termux notifications
    from notifier import notify_new_listings, notify_price_drops
    try:
        notify_new_listings(changes["new"])
        notify_price_drops(changes["price_drops"])
    except Exception as exc:
        # Notification failures are non-fatal
        logger.error("Notification error: %s", exc)

    # 5 — Enrich journey times (new listings first, then backfill up to cap)
    try:
        import time as _time
        from tfl import get_journey_mins
        from database import get_listings_needing_journey, set_journey_mins

        to_enrich = get_listings_needing_journey(limit=TFL_ENRICH_MAX_RUN)
        if to_enrich:
            logger.info("Enriching journey times for %d listings...", len(to_enrich))
            for row in to_enrich:
                mins = get_journey_mins(row["latitude"], row["longitude"])
                if mins is not None:
                    set_journey_mins(row["listing_id"], mins)
                _time.sleep(0.5)
            logger.info("Journey enrichment done")
    except Exception as exc:
        logger.error("Journey enrichment error: %s", exc)

    logger.info(
        "Run complete — %d new | %d price drops | %d total",
        len(changes["new"]),
        len(changes["price_drops"]),
        changes["total_seen"],
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
