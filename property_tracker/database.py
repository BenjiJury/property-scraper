"""
database.py — SQLite setup and query helpers.

Schema
------
listings        — one row per unique Rightmove property ID
price_history   — append-only log of every price recorded for a listing

The initial_price column in SELECT queries is derived from the first
price_history entry so that the dashboard can highlight reductions.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from config import DB_PATH

logger = logging.getLogger(__name__)


# ── Connection helpers ─────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    """Yield a connection, committing on success or rolling back on error."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ─────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables and indexes if they do not already exist."""
    with db_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                listing_id    TEXT    PRIMARY KEY,
                address       TEXT    NOT NULL,
                price         INTEGER NOT NULL,
                bedrooms      INTEGER,
                bathrooms     INTEGER,
                property_type TEXT,
                tenure        TEXT,
                area          TEXT,
                listing_url   TEXT,
                listing_date  TEXT,
                first_seen    TEXT    NOT NULL,
                last_seen     TEXT    NOT NULL,
                status        TEXT    NOT NULL DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id   TEXT    NOT NULL,
                price        INTEGER NOT NULL,
                recorded_at  TEXT    NOT NULL,
                FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
            );

            CREATE INDEX IF NOT EXISTS idx_listings_status
                ON listings(status);

            CREATE INDEX IF NOT EXISTS idx_price_history_listing
                ON price_history(listing_id);
        """)

        # Add new columns to existing DBs — safe to re-run (ignore if already present)
        for col_def in [
            "ALTER TABLE listings ADD COLUMN latitude    REAL",
            "ALTER TABLE listings ADD COLUMN longitude   REAL",
            "ALTER TABLE listings ADD COLUMN sq_footage  INTEGER",
            "ALTER TABLE listings ADD COLUMN journey_mins INTEGER",
        ]:
            try:
                conn.execute(col_def)
            except sqlite3.OperationalError:
                pass  # column already exists

    logger.info("Database ready: %s", DB_PATH)


# ── Write helpers ──────────────────────────────────────────────────────────────

def upsert_listing(listing: dict) -> dict:
    """
    Insert a new listing or update an existing one.

    Returns
    -------
    dict with keys:
        'is_new'         — True if this listing_id was not seen before
        'price_drop'     — (old_price, new_price) tuple, or None
        'price_increase' — (old_price, new_price) tuple, or None
    """
    now    = datetime.now(timezone.utc).isoformat()
    result = {"is_new": False, "price_drop": None, "price_increase": None}

    with db_connection() as conn:
        existing = conn.execute(
            "SELECT listing_id, price FROM listings WHERE listing_id = ?",
            (listing["listing_id"],),
        ).fetchone()

        if existing is None:
            # ── New listing ────────────────────────────────────────────────
            conn.execute(
                """
                INSERT INTO listings
                    (listing_id, address, price, bedrooms, bathrooms,
                     property_type, tenure, area, listing_url, listing_date,
                     first_seen, last_seen, status,
                     latitude, longitude, sq_footage, journey_mins)
                VALUES
                    (:listing_id, :address, :price, :bedrooms, :bathrooms,
                     :property_type, :tenure, :area, :listing_url, :listing_date,
                     :first_seen, :last_seen, 'active',
                     :latitude, :longitude, :sq_footage, :journey_mins)
                """,
                {
                    **listing,
                    "first_seen": now,
                    "last_seen": now,
                    "latitude":    listing.get("latitude"),
                    "longitude":   listing.get("longitude"),
                    "sq_footage":  listing.get("sq_footage"),
                    "journey_mins": listing.get("journey_mins"),
                },
            )
            conn.execute(
                "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?,?,?)",
                (listing["listing_id"], listing["price"], now),
            )
            result["is_new"] = True

        else:
            # ── Existing listing ───────────────────────────────────────────
            old_price = existing["price"]
            new_price = listing["price"]

            if new_price != old_price:
                conn.execute(
                    "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?,?,?)",
                    (listing["listing_id"], new_price, now),
                )
                if new_price < old_price:
                    result["price_drop"] = (old_price, new_price)
                elif new_price > old_price:
                    result["price_increase"] = (old_price, new_price)

            conn.execute(
                """
                UPDATE listings
                SET price         = ?,
                    address       = ?,
                    last_seen     = ?,
                    status        = 'active',
                    bedrooms      = ?,
                    bathrooms     = ?,
                    property_type = ?,
                    tenure        = ?,
                    area          = ?,
                    listing_url   = ?,
                    latitude      = COALESCE(?, latitude),
                    longitude     = COALESCE(?, longitude),
                    sq_footage    = COALESCE(?, sq_footage),
                    journey_mins  = COALESCE(?, journey_mins)
                WHERE listing_id = ?
                """,
                (
                    new_price,
                    listing["address"],
                    now,
                    listing.get("bedrooms"),
                    listing.get("bathrooms"),
                    listing.get("property_type"),
                    listing.get("tenure"),
                    listing.get("area"),
                    listing.get("listing_url"),
                    listing.get("latitude"),
                    listing.get("longitude"),
                    listing.get("sq_footage"),
                    listing.get("journey_mins"),
                    listing["listing_id"],
                ),
            )

    return result


def mark_removed(listing_ids_seen: set) -> list:
    """
    Any listing previously active but absent from listing_ids_seen is
    marked as 'removed'.

    Returns a list of dicts for the removed listings (address, price,
    first_seen, area, listing_url, bedrooms, property_type).
    """
    now = datetime.now(timezone.utc).isoformat()
    removed_listings = []

    with db_connection() as conn:
        active_rows = conn.execute(
            """SELECT listing_id, address, price, first_seen, area,
                      listing_url, bedrooms, property_type
               FROM listings WHERE status = 'active'"""
        ).fetchall()
        active_map = {row["listing_id"]: dict(row) for row in active_rows}
        to_remove  = set(active_map.keys()) - listing_ids_seen

        if to_remove:
            removed_listings = [active_map[lid] for lid in to_remove]
            placeholders = ",".join("?" * len(to_remove))
            conn.execute(
                f"UPDATE listings SET status='removed', last_seen=? "
                f"WHERE listing_id IN ({placeholders})",
                [now, *to_remove],
            )
            logger.info("Marked %d listing(s) as removed", len(to_remove))

    return removed_listings


# ── Read helpers ───────────────────────────────────────────────────────────────

def get_all_listings(include_removed: bool = True) -> list:
    """
    Return all listings joined with their initial (first-ever) price so the
    dashboard can calculate the total price reduction for each property.

    Ordering: active first (newest first_seen), then removed (also newest first).
    """
    status_filter = "" if include_removed else "WHERE l.status = 'active'"

    query = f"""
        SELECT
            l.*,
            ph_first.price AS initial_price
        FROM listings l
        LEFT JOIN (
            SELECT listing_id, price
            FROM price_history
            WHERE id IN (
                SELECT MIN(id) FROM price_history GROUP BY listing_id
            )
        ) ph_first ON ph_first.listing_id = l.listing_id
        {status_filter}
        ORDER BY
            CASE l.status WHEN 'active' THEN 0 ELSE 1 END ASC,
            l.first_seen DESC
    """
    with db_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def get_price_history(listing_id: str) -> list:
    """Return the full price history for a single listing, oldest first."""
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT price, recorded_at
            FROM price_history
            WHERE listing_id = ?
            ORDER BY recorded_at ASC
            """,
            (listing_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_listings_needing_journey(limit: int) -> list:
    """Return active listings with lat/lng but no journey_mins, up to limit."""
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT listing_id, latitude, longitude
               FROM listings
               WHERE status='active'
                 AND latitude IS NOT NULL
                 AND journey_mins IS NULL
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_journey_mins(listing_id: str, mins: int) -> None:
    """Update journey_mins for a single listing."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE listings SET journey_mins = ? WHERE listing_id = ?",
            (mins, listing_id),
        )


def get_listings_needing_sqft(limit: int) -> list:
    """Return active listings without sq_footage, up to limit."""
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT listing_id
               FROM listings
               WHERE status='active'
                 AND sq_footage IS NULL
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_sq_footage(listing_id: str, sqft: int) -> None:
    """Update sq_footage for a single listing."""
    with db_connection() as conn:
        conn.execute(
            "UPDATE listings SET sq_footage = ? WHERE listing_id = ?",
            (sqft, listing_id),
        )
