"""
tracker.py — Compares newly scraped listings against stored data.

Responsibilities
----------------
- Call database.upsert_listing() for every scraped property.
- Collect new listings and price drops into separate lists.
- Call database.mark_removed() to flag properties that have
  disappeared from Rightmove results.
- Apply the PRICE_DROP_THRESHOLD from config so only meaningful
  reductions produce notifications.
"""

import logging

from config import PRICE_DROP_THRESHOLD, PRICE_RISE_THRESHOLD, STALE_LISTING_DAYS
from database import get_stale_listings, mark_removed, upsert_listing

logger = logging.getLogger(__name__)


def process_listings(scraped: list) -> dict:
    """
    Persist scraped listings and detect changes.

    Parameters
    ----------
    scraped : list of listing dicts (as returned by scraper.scrape_all)

    Returns
    -------
    dict with keys:
        'new'         — list of newly seen listing dicts
        'price_drops' — list of (listing_dict, old_price, new_price) tuples
        'total_seen'  — int count of unique listings processed this run
    """
    new_listings  = []
    price_drops   = []
    price_rises   = []
    ids_seen: set = set()

    for listing in scraped:
        lid = listing["listing_id"]
        ids_seen.add(lid)

        try:
            result = upsert_listing(listing)
        except Exception as exc:
            logger.error("DB error upserting listing %s: %s", lid, exc)
            continue

        if result["is_new"]:
            new_listings.append(listing)
            logger.info(
                "NEW  %s — £%s  (%s beds, %s, %s)",
                listing["address"],
                f"{listing['price']:,}",
                listing.get("bedrooms", "?"),
                listing.get("property_type", ""),
                listing.get("area", ""),
            )

        elif result["price_drop"]:
            old_price, new_price = result["price_drop"]
            reduction = old_price - new_price
            if reduction >= PRICE_DROP_THRESHOLD:
                price_drops.append((listing, old_price, new_price))
                logger.info(
                    "DROP %s — £%s → £%s  (↓£%s)",
                    listing["address"],
                    f"{old_price:,}",
                    f"{new_price:,}",
                    f"{reduction:,}",
                )

        elif result["price_rise"]:
            old_price, new_price = result["price_rise"]
            increase = new_price - old_price
            if increase >= PRICE_RISE_THRESHOLD:
                price_rises.append((listing, old_price, new_price))
                logger.info(
                    "RISE %s — £%s → £%s  (↑£%s)",
                    listing["address"],
                    f"{old_price:,}",
                    f"{new_price:,}",
                    f"{increase:,}",
                )

    # Properties absent from this run's results → mark removed
    try:
        mark_removed(ids_seen)
    except Exception as exc:
        logger.error("Failed to mark removed listings: %s", exc)

    # Stale listing detection — active listings with no price change for N+ days.
    # "Newly stale" = just crossed the threshold this run (used for push alerts).
    try:
        all_stale = get_stale_listings(STALE_LISTING_DAYS)
        newly_stale = [
            l for l in all_stale
            if STALE_LISTING_DAYS <= l.get("days_on_market", 0) < STALE_LISTING_DAYS + 2
        ]
    except Exception as exc:
        logger.error("Stale listing detection failed: %s", exc)
        all_stale = []
        newly_stale = []

    logger.info(
        "Tracker: %d new | %d drops | %d rises | %d stale | %d total seen",
        len(new_listings),
        len(price_drops),
        len(price_rises),
        len(all_stale),
        len(ids_seen),
    )

    return {
        "new":          new_listings,
        "price_drops":  price_drops,
        "price_rises":  price_rises,
        "stale":        all_stale,
        "newly_stale":  newly_stale,
        "total_seen":   len(ids_seen),
    }
