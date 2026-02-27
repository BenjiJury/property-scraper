"""
notifier.py — Sends push notifications via ntfy.

NTFY_URL in config.py controls the endpoint, e.g.:
  http://localhost/keng-kxm29       (self-hosted Docker/apt)
  https://ntfy.sh/keng-kxm29       (cloud)

Set NTFY_URL = "" to disable notifications entirely.
"""

import logging

import requests

from config import NTFY_URL, NTFY_VERIFY_SSL

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
            verify=NTFY_VERIFY_SSL,
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
        journey = lst.get("journey_mins")
        journey_str = f"  ·  ~{journey} min to Bank" if journey is not None else ""
        title   = "New property listed"
        content = (
            f"{lst['address']}\n"
            f"£{lst['price']:,}  ·  {lst.get('bedrooms', '?')} bed"
            f"  ·  {lst.get('property_type', '')}  ·  {lst.get('area', '')}{journey_str}\n"
            f"{url}"
        )
        ok = _send(title, content, tags="house", click_url=url)
    else:
        lines = []
        for lst in new_listings:
            journey = lst.get("journey_mins")
            journey_str = f" ~{journey}min" if journey is not None else ""
            lines.append(
                f"• {lst['address']} — £{lst['price']:,}"
                f" ({lst.get('bedrooms', '?')} bed {lst.get('property_type', '')}, {lst.get('area', '')}{journey_str})"
            )
        title   = f"{count} new properties listed"
        content = "\n".join(lines)
        ok = _send(title, content, tags="house")

    if ok:
        logger.info("Sent new-listing notification (%d listing(s))", count)
    else:
        logger.warning("Failed to send new-listing notification (%d listing(s))", count)


def notify_price_drops(price_drops: list) -> None:
    """Send one grouped notification for all price reductions found this run."""
    if not price_drops:
        return

    count = len(price_drops)

    if count == 1:
        lst, old_price, new_price = price_drops[0]
        reduction = old_price - new_price
        pct       = round((old_price - new_price) / old_price * 100, 1)
        url       = lst.get("listing_url", "")
        title     = "Price reduction"
        content   = (
            f"{lst['address']}\n"
            f"{lst.get('bedrooms', '?')} bed {lst.get('property_type', '')}  ·  {lst.get('area', '')}\n"
            f"£{old_price:,}  →  £{new_price:,}   (↓ £{reduction:,} / -{pct}%)\n"
            f"{url}"
        )
        ok = _send(title, content, tags="chart_with_downwards_trend", click_url=url)
    else:
        lines = []
        for lst, old_price, new_price in price_drops:
            reduction = old_price - new_price
            pct = round((old_price - new_price) / old_price * 100, 1)
            lines.append(
                f"• {lst['address']} — £{old_price:,} → £{new_price:,} (↓ £{reduction:,} / -{pct}%)"
            )
        title   = f"{count} price reductions"
        content = "\n".join(lines)
        ok = _send(title, content, tags="chart_with_downwards_trend")

    if ok:
        logger.info("Sent price-drop notification (%d drop(s))", count)
    else:
        logger.warning("Failed to send price-drop notification (%d drop(s))", count)


def notify_price_increases(price_increases: list) -> None:
    """Send one grouped notification for all price increases found this run."""
    if not price_increases:
        return

    count = len(price_increases)

    if count == 1:
        lst, old_price, new_price = price_increases[0]
        increase = new_price - old_price
        pct      = round((new_price - old_price) / old_price * 100, 1)
        url      = lst.get("listing_url", "")
        title    = "Price increase"
        content  = (
            f"{lst['address']}\n"
            f"{lst.get('bedrooms', '?')} bed {lst.get('property_type', '')}  ·  {lst.get('area', '')}\n"
            f"£{old_price:,}  →  £{new_price:,}   (↑ £{increase:,} / +{pct}%)\n"
            f"{url}"
        )
        ok = _send(title, content, tags="chart_with_upwards_trend", click_url=url)
    else:
        lines = []
        for lst, old_price, new_price in price_increases:
            increase = new_price - old_price
            pct = round((new_price - old_price) / old_price * 100, 1)
            lines.append(
                f"• {lst['address']} — £{old_price:,} → £{new_price:,} (↑ £{increase:,} / +{pct}%)"
            )
        title   = f"{count} price increases"
        content = "\n".join(lines)
        ok = _send(title, content, tags="chart_with_upwards_trend")

    if ok:
        logger.info("Sent price-increase notification (%d increase(s))", count)
    else:
        logger.warning("Failed to send price-increase notification (%d increase(s))", count)


def notify_removed_listings(removed: list) -> None:
    """Send one grouped notification for all listings removed this run."""
    if not removed:
        return

    count = len(removed)

    if count == 1:
        lst = removed[0]
        dom = lst.get("days_on_market")
        dom_str = f"\nOn market {dom} days" if dom is not None else ""
        url = lst.get("listing_url", "")
        title   = "Property removed"
        content = (
            f"{lst['address']}\n"
            f"£{lst['price']:,}  ·  {lst.get('bedrooms', '?')} bed"
            f"  ·  {lst.get('property_type', '')}  ·  {lst.get('area', '')}"
            f"{dom_str}\n"
            f"{url}"
        )
        ok = _send(title, content, tags="house_with_garden", click_url=url)
    else:
        lines = []
        for lst in removed:
            dom = lst.get("days_on_market")
            dom_str = f" {dom}d" if dom is not None else ""
            lines.append(
                f"• {lst['address']} — £{lst['price']:,} ({lst.get('area', '')}{dom_str})"
            )
        title   = f"{count} properties removed"
        content = "\n".join(lines)
        ok = _send(title, content, tags="house_with_garden")

    if ok:
        logger.info("Sent removed-listing notification (%d listing(s))", count)
    else:
        logger.warning("Failed to send removed-listing notification (%d listing(s))", count)
