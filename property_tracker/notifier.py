"""
notifier.py — Push notifications with pluggable backends.

Backends
--------
ntfy   (default / recommended for Pi)
    Sends an HTTP POST to an ntfy topic.  Run ntfy on the Pi itself and install
    the ntfy Android app to receive notifications on your phone.
    Configure NTFY_URL and NOTIFICATION_BACKEND = "ntfy" in config.py.

termux (Android / Termux only)
    Sends via the termux-notification CLI.  Requires Termux:API to be installed.
    Configure NOTIFICATION_BACKEND = "termux" in config.py.

none
    Disables push notifications entirely.  Discord reports still run.
    Set NOTIFICATION_BACKEND = "none" in config.py.
"""

import logging
import subprocess

import requests

from config import (
    NOTIFICATION_BACKEND,
    NOTIFICATION_ID_DROP,
    NOTIFICATION_ID_NEW,
    NOTIFICATION_ID_RISE,
    NOTIFICATION_ID_STALE,
    NTFY_URL,
)

logger = logging.getLogger(__name__)


# ── Backend implementations ────────────────────────────────────────────────────

def _send_ntfy(title: str, content: str) -> bool:
    """POST a notification to an ntfy topic via HTTP."""
    try:
        resp = requests.post(
            NTFY_URL,
            data=content.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": "high",
                "Tags":     "house",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("ntfy notification failed (%s): %s", NTFY_URL, exc)
        return False


def _send_termux(title: str, content: str, notification_id: int) -> bool:
    """Send a notification via termux-notification (Android / Termux only)."""
    cmd = [
        "termux-notification",
        "--title",     title,
        "--content",   content,
        "--id",        str(notification_id),
        "--priority",  "high",
        "--led-color", "FF4500",
        "--vibrate",   "0,250,100,250",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.wait(timeout=10)
            if proc.returncode != 0:
                logger.error("termux-notification returned %d", proc.returncode)
                return False
        except subprocess.TimeoutExpired:
            logger.debug("termux-notification IPC in progress (background)")
        return True
    except FileNotFoundError:
        logger.error(
            "termux-notification not found. "
            "Run: pkg install termux-api  and install the Termux:API app."
        )
        return False
    except Exception as exc:
        logger.error("Unexpected termux notification error: %s", exc)
        return False


def _send(title: str, content: str, notification_id: int) -> bool:
    """Dispatch a notification via the configured backend."""
    if NOTIFICATION_BACKEND == "ntfy":
        return _send_ntfy(title, content)
    elif NOTIFICATION_BACKEND == "termux":
        return _send_termux(title, content, notification_id)
    else:
        logger.debug("Notifications disabled — would send: [%s] %s", title, content)
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
            f"£{lst['price']:,}  ·  {lst.get('bedrooms', '?')} bed  "
            f"·  {lst.get('property_type', '')}  ·  {lst.get('area', '')}"
        )
    else:
        prices  = [l["price"] for l in new_listings]
        areas   = sorted({l.get("area", "") for l in new_listings if l.get("area")})
        title   = f"{count} new properties listed"
        content = (
            f"£{min(prices):,} – £{max(prices):,}\n"
            f"{', '.join(areas)}"
        )

    if _send(title, content, NOTIFICATION_ID_NEW):
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
            f"£{old_price:,}  →  £{new_price:,}   (↓ £{reduction:,})"
        )
    else:
        reductions = [op - np for _, op, np in price_drops]
        title      = f"{count} price reductions"
        content    = (
            f"Largest drop: £{max(reductions):,}\n"
            f"Across {count} properties"
        )

    if _send(title, content, NOTIFICATION_ID_DROP):
        logger.info("Sent price-drop notification (%d drop(s))", count)


def notify_price_rises(price_rises: list) -> None:
    """Send one grouped notification for all price increases found this run."""
    if not price_rises:
        return

    count = len(price_rises)

    if count == 1:
        lst, old_price, new_price = price_rises[0]
        increase = new_price - old_price
        title    = "Price increase"
        content  = (
            f"{lst['address']}\n"
            f"£{old_price:,}  →  £{new_price:,}   (↑ £{increase:,})"
        )
    else:
        increases = [np - op for _, op, np in price_rises]
        title     = f"{count} price increases"
        content   = (
            f"Largest rise: £{max(increases):,}\n"
            f"Across {count} properties"
        )

    if _send(title, content, NOTIFICATION_ID_RISE):
        logger.info("Sent price-rise notification (%d rise(s))", count)


def notify_stale_listings(newly_stale: list) -> None:
    """
    Send one notification for listings that have just crossed the stale
    threshold (no price change for STALE_LISTING_DAYS days).
    """
    if not newly_stale:
        return

    count = len(newly_stale)

    if count == 1:
        lst     = newly_stale[0]
        dom     = lst.get("days_on_market", "?")
        title   = "Stale listing"
        content = (
            f"{lst['address']}\n"
            f"£{lst['price']:,}  ·  {dom} days on market  ·  no price change"
        )
    else:
        title   = f"{count} listings now stale"
        content = f"{count} properties with no price change for 60+ days"

    if _send(title, content, NOTIFICATION_ID_STALE):
        logger.info("Sent stale-listing notification (%d listing(s))", count)
