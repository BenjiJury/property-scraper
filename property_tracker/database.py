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
from datetime import datetime
from typing import Iterator

from config import DB_PATH

logger = logging.getLogger(__name__)


# ── Connection helpers ─────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
                status        TEXT    NOT NULL DEFAULT 'active',
                watchlist     INTEGER NOT NULL DEFAULT 0
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

    # Migrate existing databases that pre-date the watchlist column.
    with db_connection() as conn:
        try:
            conn.execute(
                "ALTER TABLE listings ADD COLUMN watchlist INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass  # column already exists

    logger.info("Database ready: %s", DB_PATH)


# ── Write helpers ──────────────────────────────────────────────────────────────

def upsert_listing(listing: dict) -> dict:
    """
    Insert a new listing or update an existing one.

    Returns
    -------
    dict with keys:
        'is_new'      — True if this listing_id was not seen before
        'price_drop'  — (old_price, new_price) tuple, or None
    """
    now    = datetime.utcnow().isoformat()
    result = {"is_new": False, "price_drop": None, "price_rise": None}

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
                     first_seen, last_seen, status)
                VALUES
                    (:listing_id, :address, :price, :bedrooms, :bathrooms,
                     :property_type, :tenure, :area, :listing_url, :listing_date,
                     :first_seen, :last_seen, 'active')
                """,
                {**listing, "first_seen": now, "last_seen": now},
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
                    result["price_rise"] = (old_price, new_price)

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
                    listing_url   = ?
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
                    listing.get("listing_url"),
                    listing["listing_id"],
                ),
            )

    return result


def mark_removed(listing_ids_seen: set) -> None:
    """
    Any listing previously active but absent from listing_ids_seen is
    marked as 'removed'.
    """
    now = datetime.utcnow().isoformat()
    with db_connection() as conn:
        active_rows = conn.execute(
            "SELECT listing_id FROM listings WHERE status = 'active'"
        ).fetchall()
        active_ids = {row["listing_id"] for row in active_rows}
        to_remove  = active_ids - listing_ids_seen

        if to_remove:
            placeholders = ",".join("?" * len(to_remove))
            conn.execute(
                f"UPDATE listings SET status='removed', last_seen=? "
                f"WHERE listing_id IN ({placeholders})",
                [now, *to_remove],
            )
            logger.info("Marked %d listing(s) as removed", len(to_remove))


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
            ph_first.price  AS initial_price,
            ph_count.n      AS price_history_count
        FROM listings l
        LEFT JOIN (
            SELECT listing_id, price
            FROM price_history
            WHERE id IN (
                SELECT MIN(id) FROM price_history GROUP BY listing_id
            )
        ) ph_first ON ph_first.listing_id = l.listing_id
        LEFT JOIN (
            SELECT listing_id, COUNT(*) AS n
            FROM price_history
            GROUP BY listing_id
        ) ph_count ON ph_count.listing_id = l.listing_id
        {status_filter}
        ORDER BY
            CASE l.status WHEN 'active' THEN 0 ELSE 1 END ASC,
            l.first_seen DESC
    """
    with db_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def set_watchlist(listing_id: str, on: bool) -> bool:
    """
    Add or remove a listing from the watchlist.
    Returns True if the listing was found, False if it does not exist.
    """
    with db_connection() as conn:
        rows_affected = conn.execute(
            "UPDATE listings SET watchlist = ? WHERE listing_id = ?",
            (1 if on else 0, listing_id),
        ).rowcount
    return rows_affected > 0


def get_watchlist_listings() -> list:
    """Return all watchlisted listings joined with their initial price."""
    query = """
        SELECT
            l.*,
            ph_first.price AS initial_price
        FROM listings l
        LEFT JOIN (
            SELECT listing_id, price
            FROM price_history
            WHERE id IN (SELECT MIN(id) FROM price_history GROUP BY listing_id)
        ) ph_first ON ph_first.listing_id = l.listing_id
        WHERE l.watchlist = 1
        ORDER BY l.first_seen DESC
    """
    with db_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def get_stale_listings(min_days: int) -> list:
    """
    Return active listings whose price has never changed and that have been
    on the market for at least min_days days, ordered oldest-first.

    The computed column ``days_on_market`` is included in each row dict so
    callers can detect whether a listing *just* crossed the threshold.
    """
    query = """
        SELECT
            l.*,
            ph_first.price AS initial_price,
            CAST(julianday('now') - julianday(l.first_seen) AS INTEGER)
                AS days_on_market
        FROM listings l
        LEFT JOIN (
            SELECT listing_id, price
            FROM price_history
            WHERE id IN (SELECT MIN(id) FROM price_history GROUP BY listing_id)
        ) ph_first ON ph_first.listing_id = l.listing_id
        WHERE l.status = 'active'
          AND l.price = COALESCE(ph_first.price, l.price)
          AND CAST(julianday('now') - julianday(l.first_seen) AS INTEGER) >= ?
        ORDER BY l.first_seen ASC
    """
    with db_connection() as conn:
        rows = conn.execute(query, (min_days,)).fetchall()
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


# ── Watchlist CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    def _usage() -> None:
        print("Manage the property watchlist.\n")
        print("Usage:")
        print("  python3 database.py watchlist list")
        print("  python3 database.py watchlist add <listing_id>")
        print("  python3 database.py watchlist remove <listing_id>")
        print("\nThe listing_id is the numeric Rightmove property ID, visible")
        print("in the URL:  rightmove.co.uk/properties/<listing_id>")
        sys.exit(1)

    args = sys.argv[1:]
    if len(args) < 2 or args[0] != "watchlist":
        _usage()

    init_db()
    sub = args[1]

    if sub == "list":
        items = get_watchlist_listings()
        if not items:
            print("Watchlist is empty.")
        else:
            print(f"{'Listing ID':<14} {'Price':>12}  {'Beds':>4}  Address")
            print("─" * 70)
            for l in items:
                status = "" if l["status"] == "active" else " [removed]"
                print(
                    f"{l['listing_id']:<14} £{l['price']:>11,}"
                    f"  {str(l.get('bedrooms') or '?'):>4}  "
                    f"{l.get('address', '')[:40]}{status}"
                )

    elif sub == "add" and len(args) == 3:
        if set_watchlist(args[2], True):
            print(f"Added {args[2]} to watchlist.")
        else:
            print(f"Listing {args[2]} not found in database.")
            sys.exit(1)

    elif sub == "remove" and len(args) == 3:
        if set_watchlist(args[2], False):
            print(f"Removed {args[2]} from watchlist.")
        else:
            print(f"Listing {args[2]} not found in database.")
            sys.exit(1)

    else:
        _usage()
