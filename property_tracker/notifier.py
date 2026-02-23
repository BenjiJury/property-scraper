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

def _send(title: str, content: str, tags: str = "", click_url: str = "") -> bool:
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
    if click_url:
        headers["Click"] = click_url

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
        url     = lst.get("listing_url", "")
        title   = "New property listed"
        content = (
            f"{lst['address']}\n"
            f"£{lst['price']:,}  ·  {lst.get('bedrooms', '?')} bed"
            f"  ·  {lst.get('property_type', '')}  ·  {lst.get('area', '')}\n"
            f"{url}"
        )
        _send(title, content, tags="house", click_url=url)
    else:
        lines = []
        for lst in new_listings:
            lines.append(
                f"• {lst['address']} — £{lst['price']:,}"
                f" ({lst.get('bedrooms', '?')} bed {lst.get('property_type', '')}, {lst.get('area', '')})"
            )
        title   = f"{count} new properties listed"
        content = "\n".join(lines)
        _send(title, content, tags="house")

    logger.info("Sent new-listing notification (%d listing(s))", count)


def notify_price_drops(price_drops: list) -> None:
    """Send one grouped notification for all price reductions found this run."""
    if not price_drops:
        return

    count = len(price_drops)

    if count == 1:
        lst, old_price, new_price = price_drops[0]
        reduction = old_price - new_price
        url       = lst.get("listing_url", "")
        title     = "Price reduction"
        content   = (
            f"{lst['address']}\n"
            f"{lst.get('bedrooms', '?')} bed {lst.get('property_type', '')}  ·  {lst.get('area', '')}\n"
            f"£{old_price:,}  →  £{new_price:,}   (saving £{reduction:,})\n"
            f"{url}"
        )
        _send(title, content, tags="chart_with_downwards_trend", click_url=url)
    else:
        lines = []
        for lst, old_price, new_price in price_drops:
            reduction = old_price - new_price
            lines.append(
                f"• {lst['address']} — £{old_price:,} → £{new_price:,} (↓ £{reduction:,})"
            )
        title   = f"{count} price reductions"
        content = "\n".join(lines)
        _send(title, content, tags="chart_with_downwards_trend")

    logger.info("Sent price-drop notification (%d drop(s))", count)
