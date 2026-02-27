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
from datetime import datetime, timezone

# ── Logging setup (must happen before any module imports that use logging) ─────

def _setup_logging() -> None:
    from config import LOG_PATH

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
    logger.info("Run started  %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))

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

    # 3 — Detect changes (new listings / price drops / increases / removals)
    from tracker import process_listings
    try:
        changes = process_listings(listings)
    except Exception as exc:
        logger.critical("Tracker raised an unhandled exception: %s", exc)
        sys.exit(1)

    # 4 — Enrich new listings with TfL journey time before notification
    #     (no cap — typically only 1–3 new listings per run)
    try:
        import time as _time
        from tfl import get_journey_mins
        from database import set_journey_mins

        new_with_journey = []
        for listing in changes["new"]:
            enriched = dict(listing)
            if listing.get("latitude") and listing.get("longitude"):
                mins = get_journey_mins(listing["latitude"], listing["longitude"])
                if mins is not None:
                    set_journey_mins(listing["listing_id"], mins)
                    enriched["journey_mins"] = mins
                    logger.info(
                        "Journey enriched (new): %s — %d min",
                        listing["address"], mins,
                    )
            new_with_journey.append(enriched)
        changes["new"] = new_with_journey
    except Exception as exc:
        logger.error("New-listing journey enrichment error: %s", exc)

    # 5 — Send notifications
    from notifier import (
        notify_new_listings,
        notify_price_drops,
        notify_price_increases,
        notify_removed_listings,
    )
    try:
        notify_new_listings(changes["new"])
        notify_price_drops(changes["price_drops"])
        notify_price_increases(changes["price_increases"])
        notify_removed_listings(changes["removed"])
    except Exception as exc:
        # Notification failures are non-fatal
        logger.error("Notification error: %s", exc)

    # 6 — Enrich existing listings with TfL journey time (backfill, capped)
    try:
        from database import get_listings_needing_journey
        from config import TFL_ENRICH_MAX_RUN

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

    # 7 — Enrich sq footage from individual listing pages (backfill, capped)
    try:
        import random
        from scraper import scrape_listing_page
        from database import get_listings_needing_sqft, set_sq_footage
        from config import SQFT_ENRICH_MAX_RUN

        to_enrich_sqft = get_listings_needing_sqft(limit=SQFT_ENRICH_MAX_RUN)
        if to_enrich_sqft:
            logger.info("Enriching sq footage for %d listings...", len(to_enrich_sqft))
            session_for_sqft = listings[0].get("_session") if listings else None
            # Use a fresh requests.Session for individual page fetches
            import requests as _requests
            sqft_session = _requests.Session()
            enriched_count = 0
            for row in to_enrich_sqft:
                sqft = scrape_listing_page(row["listing_id"], sqft_session)
                if sqft:
                    set_sq_footage(row["listing_id"], sqft)
                    enriched_count += 1
                _time.sleep(random.uniform(3, 7))
            logger.info("Sq footage enrichment done (%d updated)", enriched_count)
    except Exception as exc:
        logger.error("Sq footage enrichment error: %s", exc)

    logger.info(
        "Run complete — %d new | %d drops | %d increases | %d removed | %d total",
        len(changes["new"]),
        len(changes["price_drops"]),
        len(changes["price_increases"]),
        len(changes["removed"]),
        changes["total_seen"],
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
