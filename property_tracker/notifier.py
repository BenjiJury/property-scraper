"""
notifier.py — Sends Android notifications via Termux:API.

Requirements
------------
  1. Termux:API app installed from F-Droid.
  2. termux-api package:  pkg install termux-api
  3. TERMUX_API_AVAILABLE = True in config.py

Notification IDs
----------------
  NOTIFICATION_ID_NEW  (1001) — new listing alert
  NOTIFICATION_ID_DROP (1002) — price reduction alert

Both IDs are stable so that Android replaces (rather than stacks)
the previous notification of each type on every run.

Testing without Termux
----------------------
Set TERMUX_API_AVAILABLE = False in config.py.  The module will log
what it would have sent without calling termux-notification.
"""

import logging
import subprocess

from config import (
    NOTIFICATION_ID_DROP,
    NOTIFICATION_ID_NEW,
    NOTIFICATION_ID_RISE,
    NOTIFICATION_ID_STALE,
    TERMUX_API_AVAILABLE,
)

logger = logging.getLogger(__name__)


# ── Internal send ──────────────────────────────────────────────────────────────

def _send(title: str, content: str, notification_id: int) -> bool:
    """
    Call `termux-notification` in a subprocess.
    Returns True on success, False on any error.
    """
    if not TERMUX_API_AVAILABLE:
        logger.debug(
            "Notifications disabled — would send: [%s] %s", title, content
        )
        return False

    cmd = [
        "termux-notification",
        "--title",    title,
        "--content",  content,
        "--id",       str(notification_id),
        "--priority", "high",
        "--led-color", "FF4500",     # orange-red LED
        "--vibrate",  "0,250,100,250",
    ]

    try:
        # Run in a detached session so the IPC handshake with the Termux:API
        # service doesn't block our process.  We wait up to 10 s for a quick
        # result; if it's still running after that the notification is being
        # delivered in the background and we move on.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.wait(timeout=10)
            if proc.returncode != 0:
                logger.error(
                    "termux-notification returned %d", proc.returncode
                )
                return False
        except subprocess.TimeoutExpired:
            logger.debug("termux-notification IPC in progress (background)")
        return True

    except FileNotFoundError:
        logger.error(
            "termux-notification not found.  "
            "Run: pkg install termux-api  and install the Termux:API app."
        )
        return False
    except Exception as exc:
        logger.error("Unexpected notification error: %s", exc)
        return False


# ── Public API ─────────────────────────────────────────────────────────────────

def notify_new_listings(new_listings: list) -> None:
    """
    Send one grouped notification for all new listings found this run.
    If there is exactly one new listing, include its full details.
    """
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
    """
    Send one grouped notification for all price reductions found this run.
    If there is exactly one drop, include full detail.
    """
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
    """
    Send one grouped notification for all price increases found this run.
    """
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
    threshold (i.e. no price change for STALE_LISTING_DAYS days).
    """
    if not newly_stale:
        return

    count = len(newly_stale)

    if count == 1:
        lst  = newly_stale[0]
        dom  = lst.get("days_on_market", "?")
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
