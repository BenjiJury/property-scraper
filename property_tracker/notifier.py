"""
notifier.py — Sends push notifications via ntfy.

NTFY_URL in config.py controls the endpoint, e.g.:
  http://localhost/keng-kxm29       (self-hosted Docker/apt)
  https://ntfy.sh/keng-kxm29       (cloud)

Set NTFY_URL = "" to disable notifications entirely.
"""

import logging

import requests

from config import NTFY_URL

logger = logging.getLogger(__name__)


# ── Internal send ──────────────────────────────────────────────────────────────

def _send(title: str, content: str, tags: str = "") -> bool:
    """POST a notification to the ntfy server. Returns True on success."""
    if not NTFY_URL:
        logger.debug("NTFY_URL not set — skipping notification")
        return False

    headers: dict = {
        "Title":    title,
        "Priority": "high",
    }
    if tags:
        headers["Tags"] = tags

    try:
        resp = requests.post(
            NTFY_URL,
            data=content.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("ntfy POST failed: %s", exc)
        return False


# ── Public API ─────────────────────────────────────────────────────────────────

def notify_new_listings(new_listings: list) -> None:
    """Send one grouped notification for all new listings found this run."""
    if not new_listings:
        return

    count = len(new_listings)

    if count == 1:
        lst     = new_listings[0]
        title   = "New property listed"
        content = (
            f"{lst['address']}\n"
            f"£{lst['price']:,}  ·  {lst.get('bedrooms', '?')} bed"
            f"  ·  {lst.get('property_type', '')}  ·  {lst.get('area', '')}\n"
            f"{lst.get('listing_url', '')}"
        )
    else:
        prices = [l["price"] for l in new_listings]
        areas  = sorted({l.get("area", "") for l in new_listings if l.get("area")})
        title  = f"{count} new properties listed"
        content = (
            f"£{min(prices):,} – £{max(prices):,}\n"
            f"{', '.join(areas)}"
        )

    if _send(title, content, tags="house"):
        logger.info("Sent new-listing notification (%d listing(s))", count)


def notify_price_drops(price_drops: list) -> None:
    """Send one grouped notification for all price reductions found this run."""
    if not price_drops:
        return

    count = len(price_drops)

    if count == 1:
        lst, old_price, new_price = price_drops[0]
        reduction = old_price - new_price
        title     = "Price reduction"
        content   = (
            f"{lst['address']}\n"
            f"£{old_price:,}  →  £{new_price:,}   (↓ £{reduction:,})\n"
            f"{lst.get('listing_url', '')}"
        )
    else:
        reductions = [op - np for _, op, np in price_drops]
        title      = f"{count} price reductions"
        content    = (
            f"Largest drop: £{max(reductions):,}\n"
            f"Across {count} properties"
        )

    if _send(title, content, tags="chart_with_downwards_trend"):
        logger.info("Sent price-drop notification (%d drop(s))", count)
