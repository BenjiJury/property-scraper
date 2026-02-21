"""
export.py — Export tracked listings to CSV, PDF, or Discord.

Usage
-----
    # CSV (opens in Google Sheets / Excel)
    python3 export.py --csv

    # PDF snapshot
    python3 export.py --pdf

    # Post summary to Discord webhook
    python3 export.py --discord

    # All three at once
    python3 export.py --csv --pdf --discord

Discord setup
-------------
  1. Open your Discord server → Edit Channel → Integrations → Webhooks → New Webhook
  2. Copy the URL and paste it into config.py as DISCORD_WEBHOOK_URL

Google Sheets setup
-------------------
  1. Run:  python3 export.py --csv
  2. Open Google Sheets → File → Import → Upload the generated .csv file
  3. (Optional) Schedule this in cron and upload via Google Drive CLI / rclone
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

# Ensure the package directory is on the path when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from config import DISCORD_WEBHOOK_URL, EXPORT_DIR
from database import get_all_listings


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _days_on_market(first_seen: str) -> int:
    try:
        dt = datetime.fromisoformat(first_seen)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (_now_utc() - dt).days)
    except (ValueError, TypeError):
        return 0


def _price_change(current: int, initial: int | None) -> str:
    """Return a human-readable price change string, e.g. '↓ £10,000' or '—'."""
    if initial is None or initial == current:
        return "—"
    delta = initial - current
    return f"↓ £{delta:,}" if delta > 0 else f"↑ £{abs(delta):,}"


def _fmt_date(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso_str[:10] if iso_str else ""


# ── CSV export ─────────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "address", "area", "price", "price_change", "bedrooms",
    "property_type", "tenure", "days_on_market", "first_seen",
    "listing_date", "status", "listing_url",
]


def export_csv(path: str | None = None) -> str:
    """
    Write all listings to a CSV file and return the file path.

    Parameters
    ----------
    path : str, optional
        Destination file path.  Defaults to ``EXPORT_DIR/properties_YYYYMMDD.csv``.
    """
    if path is None:
        stamp = _now_utc().strftime("%Y%m%d")
        path = os.path.join(EXPORT_DIR, f"properties_{stamp}.csv")

    listings = get_all_listings(include_removed=True)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for l in listings:
            writer.writerow({
                "address":        l.get("address", ""),
                "area":           l.get("area", ""),
                "price":          l.get("price", ""),
                "price_change":   _price_change(l["price"], l.get("initial_price")),
                "bedrooms":       l.get("bedrooms") or "",
                "property_type":  l.get("property_type", ""),
                "tenure":         l.get("tenure", ""),
                "days_on_market": _days_on_market(l.get("first_seen", "")),
                "first_seen":     _fmt_date(l.get("first_seen", "")),
                "listing_date":   l.get("listing_date", ""),
                "status":         l.get("status", ""),
                "listing_url":    l.get("listing_url", ""),
            })

    return path


# ── PDF export ─────────────────────────────────────────────────────────────────

def export_pdf(path: str | None = None) -> str:
    """
    Generate a formatted PDF report and return the file path.

    Requires ``reportlab``:  pip install reportlab
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        )
    except ImportError:
        raise ImportError(
            "reportlab is required for PDF export.  "
            "Install it with:  pip install reportlab"
        )

    if path is None:
        stamp = _now_utc().strftime("%Y%m%d")
        path = os.path.join(EXPORT_DIR, f"properties_{stamp}.pdf")

    listings = get_all_listings(include_removed=True)
    active  = [l for l in listings if l["status"] == "active"]
    removed = [l for l in listings if l["status"] == "removed"]

    prices = [l["price"] for l in active]
    price_summary = (
        f"£{min(prices):,} – £{max(prices):,}  |  avg £{sum(prices)//len(prices):,}"
        if prices else "no data"
    )

    area_counts: dict[str, int] = {}
    for l in active:
        area = l.get("area") or "Unknown"
        area_counts[area] = area_counts.get(area, 0) + 1

    # ── reportlab styles ──────────────────────────────────────────────────────
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title2", parent=styles["Title"], fontSize=18, spaceAfter=4
    )
    h2_style = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4
    )
    body_style = styles["Normal"]

    BLUE  = colors.HexColor("#1E6EBE")
    WHITE = colors.white
    ALT   = colors.HexColor("#F0F5FF")

    story = []

    # Title
    story.append(Paragraph("Property Tracker — South &amp; SW London", title_style))
    story.append(Paragraph(
        f"Generated {_now_utc().strftime('%d %b %Y %H:%M')} UTC",
        body_style,
    ))
    story.append(Spacer(1, 6 * mm))

    # Summary table
    story.append(Paragraph("Summary", h2_style))
    area_str = "  |  ".join(
        f"{a}: {c}"
        for a, c in sorted(area_counts.items(), key=lambda x: -x[1])
    ) or "—"
    summary_data = [
        ["Active listings", str(len(active))],
        ["Removed listings", str(len(removed))],
        ["Price range", price_summary],
        ["By area", area_str],
    ]
    summary_table = Table(summary_data, colWidths=[45 * mm, None])
    summary_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",  (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), BLUE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 8 * mm))

    # Active listings table
    story.append(Paragraph(f"Active Listings ({len(active)})", h2_style))

    col_widths = [75 * mm, 32 * mm, 24 * mm, 24 * mm, 10 * mm, 12 * mm]
    headers = [["Address", "Area", "Price", "Change", "Beds", "DOM"]]
    rows = headers[:]
    for l in active:
        change = _price_change(l["price"], l.get("initial_price"))
        dom    = _days_on_market(l.get("first_seen", ""))
        rows.append([
            l.get("address", "")[:60],
            l.get("area", ""),
            f"£{l['price']:,}",
            change,
            str(l.get("bedrooms") or "?"),
            str(dom),
        ])

    active_table = Table(rows, colWidths=col_widths, repeatRows=1)
    row_styles = [
        ("BACKGROUND",   (0, 0), (-1, 0),  BLUE),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  WHITE),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ALT]),
        ("ALIGN",        (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN",        (4, 0), (5, -1),  "CENTER"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("GRID",         (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]
    # Highlight price drops in red
    for i, l in enumerate(active, start=1):
        if (l.get("initial_price") or 0) > l["price"]:
            row_styles.append(("TEXTCOLOR", (3, i), (3, i), colors.red))
            row_styles.append(("FONTNAME",  (3, i), (3, i), "Helvetica-Bold"))
    active_table.setStyle(TableStyle(row_styles))
    story.append(active_table)

    # Removed listings
    if removed:
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph(f"Removed Listings ({len(removed)})", h2_style))
        rem_rows = [["Address", "Area", "Last Price", "Change"]]
        for l in removed:
            change = _price_change(l["price"], l.get("initial_price"))
            rem_rows.append([
                l.get("address", "")[:60],
                l.get("area", ""),
                f"£{l['price']:,}",
                change,
            ])
        rem_table = Table(rem_rows, colWidths=[95 * mm, 35 * mm, 28 * mm, 28 * mm], repeatRows=1)
        rem_table.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("TEXTCOLOR",   (0, 1), (-1, -1), colors.grey),
            ("TOPPADDING",  (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",(0,0), (-1, -1), 3),
            ("GRID",        (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ]))
        story.append(rem_table)

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    doc.build(story)
    return path


# ── Discord export ─────────────────────────────────────────────────────────────

def _listing_field(l: dict, *, prefix: str = "") -> dict:
    """Return a single Discord embed field dict for one listing."""
    change   = _price_change(l["price"], l.get("initial_price"))
    dom      = _days_on_market(l.get("first_seen", ""))
    beds     = l.get("bedrooms") or "?"
    area     = l.get("area", "")
    addr     = l.get("address", "Unknown")
    url_link = l.get("listing_url", "")

    name = f"{prefix}£{l['price']:,}  ·  {beds}bed  ·  {area}"
    addr_md = f"[{addr}]({url_link})" if url_link else addr
    value_parts = [f"**{addr_md}**"]
    if change != "—":
        value_parts.append(f"Price change: {change}")
    value_parts.append(f"DOM: {dom}d  ·  First seen: {_fmt_date(l.get('first_seen', ''))}")
    return {"name": name, "value": "\n".join(value_parts), "inline": False}


def _stats_fields(active: list) -> list[dict]:
    """Return price-range and by-area embed fields."""
    fields = []
    prices = [l["price"] for l in active]
    if prices:
        fields.append({
            "name": "📊 Price range",
            "value": (
                f"£{min(prices):,} – £{max(prices):,}\n"
                f"avg £{sum(prices) // len(prices):,}"
            ),
            "inline": True,
        })

    area_counts: dict[str, int] = {}
    for l in active:
        area = l.get("area") or "Unknown"
        area_counts[area] = area_counts.get(area, 0) + 1
    if area_counts:
        fields.append({
            "name": "📍 By area",
            "value": "\n".join(
                f"{a}: **{c}**"
                for a, c in sorted(area_counts.items(), key=lambda x: -x[1])
            ),
            "inline": True,
        })
    return fields


def _post_webhook(url: str, payload: dict) -> None:
    resp = requests.post(
        url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()


def export_discord(
    webhook_url: str | None = None,
    changes: dict | None = None,
) -> None:
    """
    Post to a Discord channel via webhook.

    Parameters
    ----------
    webhook_url : str, optional
        Overrides ``DISCORD_WEBHOOK_URL`` from config.
    changes : dict, optional
        The dict returned by ``tracker.process_listings()``, containing keys
        ``new`` (list of listing dicts), ``price_drops`` (list of
        (listing, old_price, new_price) tuples), and ``total_seen`` (int).
        When provided the message is a "run report" showing what changed this
        scrape.  When omitted the message shows the full dashboard.
    """
    url = webhook_url or DISCORD_WEBHOOK_URL
    if not url:
        raise ValueError(
            "No Discord webhook URL configured.  "
            "Set DISCORD_WEBHOOK_URL in config.py or pass it as an argument."
        )

    active = get_all_listings(include_removed=False)
    now_str = _now_utc().strftime("%d %b %Y %H:%M") + " UTC"

    # ── Run-report mode (called from main.py after a scrape) ──────────────────
    if changes is not None:
        new_listings  = changes.get("new", [])
        price_drops   = changes.get("price_drops", [])   # list of (l, old, new)
        total_seen    = changes.get("total_seen", len(active))

        n_new   = len(new_listings)
        n_drops = len(price_drops)

        # Colour: red if drops, green if new only, grey if nothing changed
        if n_drops:
            color = 0xCC2200   # red
        elif n_new:
            color = 0x00AA55   # green
        else:
            color = 0x7289DA   # discord blurple — quiet run

        desc = (
            f"Scraped **{total_seen}** properties  ·  "
            f"**{n_new}** new  ·  "
            f"**{n_drops}** price {'drop' if n_drops == 1 else 'drops'}  ·  "
            f"**{len(active)}** active total"
        )

        fields: list[dict] = []

        # New listings section (up to 5)
        if new_listings:
            fields.append({
                "name": f"🆕  New listings  ({n_new})",
                "value": "─" * 30,
                "inline": False,
            })
            for l in new_listings[:5]:
                fields.append(_listing_field(l, prefix=""))
            if n_new > 5:
                fields.append({
                    "name": "\u200b",
                    "value": f"…and {n_new - 5} more new listings",
                    "inline": False,
                })

        # Price drops section (up to 5)
        if price_drops:
            fields.append({
                "name": f"💸  Price drops  ({n_drops})",
                "value": "─" * 30,
                "inline": False,
            })
            for l, old_price, new_price in price_drops[:5]:
                drop = old_price - new_price
                field = _listing_field(l, prefix="")
                # Prepend was/now line
                field["value"] = (
                    f"~~£{old_price:,}~~  →  **£{new_price:,}**  *(↓ £{drop:,})*\n"
                    + field["value"]
                )
                fields.append(field)
            if n_drops > 5:
                fields.append({
                    "name": "\u200b",
                    "value": f"…and {n_drops - 5} more price drops",
                    "inline": False,
                })

        # Stats
        fields.extend(_stats_fields(active))

        # Clamp to Discord's 25-field limit
        fields = fields[:25]

        embeds = [{
            "title": f"🏠 Property Tracker — South & SW London",
            "description": desc,
            "color": color,
            "fields": fields,
            "footer": {"text": now_str},
        }]

    # ── Dashboard mode (manual CLI call — no changes context) ─────────────────
    else:
        def _sort_key(l):
            has_drop = (l.get("initial_price") or 0) > l["price"]
            return (not has_drop, l.get("first_seen", ""))

        top = sorted(active, key=_sort_key)[:10]
        fields = _stats_fields(active)
        for l in top:
            fields.append(_listing_field(
                l,
                prefix="🔴 " if (l.get("initial_price") or 0) > l["price"] else "",
            ))
        fields = fields[:25]

        footer_note = (
            f"  ·  {len(active) - 10} more — run `export.py --csv` for full list"
            if len(active) > 10 else ""
        )

        embeds = [{
            "title": "🏠 Property Tracker — South & SW London",
            "description": f"**{len(active)} active listings**{footer_note}",
            "color": 0x1E6EBE,
            "fields": fields,
            "footer": {"text": now_str},
        }]

    _post_webhook(url, {"embeds": embeds})


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export tracked property listings to CSV, PDF, or Discord."
    )
    parser.add_argument("--csv",     action="store_true", help="Export to CSV file")
    parser.add_argument("--pdf",     action="store_true", help="Export to PDF file")
    parser.add_argument("--discord", action="store_true", help="Post to Discord webhook")
    parser.add_argument(
        "--webhook",
        metavar="URL",
        help="Discord webhook URL (overrides DISCORD_WEBHOOK_URL in config.py)",
    )
    args = parser.parse_args()

    if not any([args.csv, args.pdf, args.discord]):
        parser.print_help()
        sys.exit(0)

    if args.csv:
        path = export_csv()
        print(f"CSV exported → {path}")

    if args.pdf:
        path = export_pdf()
        print(f"PDF exported → {path}")

    if args.discord:
        try:
            export_discord(webhook_url=args.webhook)
            print("Discord message sent successfully.")
        except ValueError as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        except requests.HTTPError as exc:
            print(f"Discord webhook error {exc.response.status_code}: {exc.response.text}")
            sys.exit(1)


if __name__ == "__main__":
    main()
