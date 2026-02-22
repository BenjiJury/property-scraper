"""
export_csv.py — Export the listings database to properties.csv.

Run automatically by deploy/run.sh after each scrape so that
rclone can sync the CSV to Google Drive.
"""

import csv
import os
import sqlite3

from config import BASE_DIR, DB_PATH

CSV_PATH = os.path.join(BASE_DIR, "properties.csv")

COLUMNS = [
    "listing_id",
    "address",
    "price",
    "initial_price",
    "bedrooms",
    "bathrooms",
    "property_type",
    "tenure",
    "area",
    "listing_url",
    "listing_date",
    "first_seen",
    "last_seen",
    "status",
    "latitude",
    "longitude",
    "sq_footage",
]


def export() -> int:
    """Write all listings to CSV. Returns the number of rows written."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
            l.listing_id,
            l.address,
            l.price,
            ph_first.price  AS initial_price,
            l.bedrooms,
            l.bathrooms,
            l.property_type,
            l.tenure,
            l.area,
            l.listing_url,
            l.listing_date,
            l.first_seen,
            l.last_seen,
            l.status,
            l.latitude,
            l.longitude,
            l.sq_footage
        FROM listings l
        LEFT JOIN (
            SELECT listing_id, price
            FROM price_history
            WHERE id IN (
                SELECT MIN(id) FROM price_history GROUP BY listing_id
            )
        ) ph_first ON ph_first.listing_id = l.listing_id
        ORDER BY
            CASE l.status WHEN 'active' THEN 0 ELSE 1 END ASC,
            l.first_seen DESC
    """).fetchall()
    conn.close()

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    print(f"Exported {len(rows)} listing(s) to {CSV_PATH}")
    return len(rows)


if __name__ == "__main__":
    export()
