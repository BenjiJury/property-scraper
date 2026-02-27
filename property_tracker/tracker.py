"""
tracker.py — Compares newly scraped listings against stored data.

Responsibilities
----------------
- Call database.upsert_listing() for every scraped property.
- Collect new listings, price drops, and price increases into separate lists.
- Call database.mark_removed() to flag properties that have
  disappeared from Rightmove results; attach days-on-market.
- Apply the PRICE_DROP_THRESHOLD from config so only meaningful
  reductions produce notifications.
"""

import logging
from datetime import datetime, timezone

from config import PRICE_DROP_THRESHOLD
from database import mark_removed, upsert_listing

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
        'new'             — list of newly seen listing dicts
        'price_drops'     — list of (listing_dict, old_price, new_price) tuples
        'price_increases' — list of (listing_dict, old_price, new_price) tuples
        'removed'         — list of removed listing dicts (with 'days_on_market')
        'total_seen'      — int count of unique listings processed this run
    """
    new_listings     = []
    price_drops      = []
    price_increases  = []
    ids_seen: set    = set()

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

        elif result["price_increase"]:
            old_price, new_price = result["price_increase"]
            price_increases.append((listing, old_price, new_price))
            logger.info(
                "RISE %s — £%s → £%s  (↑£%s)",
                listing["address"],
                f"{old_price:,}",
                f"{new_price:,}",
                f"{new_price - old_price:,}",
            )

    # Properties absent from this run's results → mark removed
    removed_listings = []
    try:
        removed_raw = mark_removed(ids_seen)
        now = datetime.now(timezone.utc)
        for lst in removed_raw:
            try:
                ts = lst["first_seen"]
                first = datetime.fromisoformat(ts) if ts.endswith("+00:00") else \
                        datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
                lst["days_on_market"] = (now - first).days
            except Exception:
                lst["days_on_market"] = None
            removed_listings.append(lst)
    except Exception as exc:
        logger.error("Failed to mark removed listings: %s", exc)

    logger.info(
        "Tracker: %d new | %d drops | %d increases | %d removed | %d total seen",
        len(new_listings),
        len(price_drops),
        len(price_increases),
        len(removed_listings),
        len(ids_seen),
    )

    return {
        "new":             new_listings,
        "price_drops":     price_drops,
        "price_increases": price_increases,
        "removed":         removed_listings,
        "total_seen":      len(ids_seen),
    }
