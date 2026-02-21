"""
dashboard.py — Rich terminal table showing all tracked listings.

Run directly:
    python3 dashboard.py

Columns
-------
  Address       — display address (tap/click to open listing on Rightmove)
  Area          — search area the listing was found in
  Price         — current asking price
  Change        — total reduction from first recorded price (red ↓)
                  or increase (green ↑); dash if unchanged
  Beds          — bedroom count
  Type          — property sub-type (Detached / Semi-Detached / Terraced)
  DOM           — days on market since first_seen in our database
                  green < 14 days, white 14–59 days, yellow ≥ 60 days
  First Seen    — date the tracker first recorded this listing
  Status        — ● active (green) / ✕ removed (dim red)

Active listings are shown first, sorted newest-first by first_seen.
Removed listings are shown below a section break, dimmed.
"""

import sys
from datetime import datetime, timezone

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Ensure the package directory is on the path when run directly
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SHOW_REMOVED_LISTINGS
from database import get_all_listings

console = Console()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _days_on_market(first_seen: str) -> int:
    """Return whole days between first_seen (ISO string) and now (UTC)."""
    try:
        dt = datetime.fromisoformat(first_seen)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (_now_utc() - dt).days)
    except (ValueError, TypeError):
        return 0


def _dom_text(dom: int) -> Text:
    if dom < 14:
        style = "bright_green"
    elif dom < 60:
        style = "white"
    else:
        style = "yellow"
    return Text(str(dom), style=style)


def _price_change_text(current: int, initial: int | None) -> Text:
    """Show total reduction / increase from first recorded price."""
    if initial is None or initial == current:
        return Text("—", style="dim")
    delta = initial - current          # positive = reduction
    if delta > 0:
        return Text(f"↓ £{delta:,}", style="bold red")
    return Text(f"↑ £{abs(delta):,}", style="bold bright_green")


def _fmt_price(price: int) -> str:
    return f"£{price:,}"


def _fmt_date(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso_str[:10] if iso_str else "—"


def _address_link(address: str, url: str | None) -> Text:
    """Return address text, hyperlinked to the Rightmove URL if available."""
    if url:
        return Text(address, style=f"link {url}")
    return Text(address)


# ── Stats panel ────────────────────────────────────────────────────────────────

def _build_stats(active: list, removed: list) -> None:
    """Print a row of summary panels above the table."""
    prices = [l["price"] for l in active]

    # Per-area counts
    area_counts: dict[str, int] = {}
    for l in active:
        area = l.get("area") or "Unknown"
        area_counts[area] = area_counts.get(area, 0) + 1

    # Price stats
    if prices:
        avg   = sum(prices) // len(prices)
        lo    = min(prices)
        hi    = max(prices)
        price_text = (
            f"[bold]£{lo:,}[/bold] – [bold]£{hi:,}[/bold]\n"
            f"avg [cyan]£{avg:,}[/cyan]"
        )
    else:
        price_text = "[dim]no data[/dim]"

    # Area breakdown
    area_lines = "\n".join(
        f"[cyan]{area}[/cyan]  [bold]{count}[/bold]"
        for area, count in sorted(area_counts.items(), key=lambda x: -x[1])
    ) or "[dim]none[/dim]"

    panels = [
        Panel(
            f"[bold bright_green]{len(active)}[/bold bright_green] active\n"
            f"[dim]{len(removed)} removed[/dim]",
            title="Listings",
            border_style="cyan",
            expand=True,
        ),
        Panel(price_text, title="Price range", border_style="cyan", expand=True),
        Panel(area_lines,  title="By area",    border_style="cyan", expand=True),
    ]
    console.print(Columns(panels, expand=True))
    console.print()


# ── Table ──────────────────────────────────────────────────────────────────────

def _build_table() -> Table:
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
    )
    table.add_column("Address",    no_wrap=False, ratio=5)
    table.add_column("Area",       no_wrap=True,  ratio=2)
    table.add_column("Price",      no_wrap=True,  ratio=2, justify="right")
    table.add_column("Change",     no_wrap=True,  ratio=2, justify="right")
    table.add_column("Beds",       no_wrap=True,  ratio=1, justify="center")
    table.add_column("Type",       no_wrap=True,  ratio=2)
    table.add_column("DOM",        no_wrap=True,  ratio=1, justify="center")
    table.add_column("First Seen", no_wrap=True,  ratio=2)
    table.add_column("",           no_wrap=True,  ratio=1, justify="center")  # status icon
    return table


# ── Main render ────────────────────────────────────────────────────────────────

def show_dashboard() -> None:
    listings = get_all_listings(include_removed=SHOW_REMOVED_LISTINGS)

    active  = [l for l in listings if l["status"] == "active"]
    removed = [l for l in listings if l["status"] == "removed"]

    console.print()
    console.rule("[bold blue]Property Tracker — South & South West London[/bold blue]")
    console.print(
        f"  [cyan]{len(active)} active[/cyan]"
        f"  [dim]{len(removed)} removed[/dim]"
        f"  [dim]Updated {_now_utc().strftime('%d %b %Y %H:%M')} UTC[/dim]"
    )
    console.print()

    if not listings:
        console.print(
            "[yellow]No listings in the database yet.  "
            "Run main.py to fetch.[/yellow]"
        )
        return

    _build_stats(active, removed)

    table = _build_table()

    # ── Active listings ────────────────────────────────────────────────────────
    for l in active:
        dom    = _days_on_market(l["first_seen"])
        change = _price_change_text(l["price"], l.get("initial_price"))

        table.add_row(
            _address_link(l.get("address", ""), l.get("listing_url")),
            l.get("area", ""),
            _fmt_price(l["price"]),
            change,
            str(l.get("bedrooms") or "?"),
            l.get("property_type") or "—",
            _dom_text(dom),
            _fmt_date(l.get("first_seen", "")),
            Text("●", style="bright_green"),
        )

    # ── Removed listings (dimmed) ──────────────────────────────────────────────
    if SHOW_REMOVED_LISTINGS and removed:
        table.add_section()
        for l in removed:
            dom    = _days_on_market(l["first_seen"])
            change = _price_change_text(l["price"], l.get("initial_price"))

            table.add_row(
                Text(l.get("address", ""), style="dim"),
                Text(l.get("area", ""), style="dim"),
                Text(_fmt_price(l["price"]), style="dim"),
                change,
                Text(str(l.get("bedrooms") or "?"), style="dim"),
                Text(l.get("property_type") or "—", style="dim"),
                Text(str(dom), style="dim"),
                Text(_fmt_date(l.get("first_seen", "")), style="dim"),
                Text("✕", style="dim red"),
            )

    console.print(table)
    console.print()

    # ── Legend ─────────────────────────────────────────────────────────────────
    legend_parts = [
        Text("Legend: ", style="bold"),
        Text("↓ price drop", style="bold red"),
        Text("  "),
        Text("↑ price rise", style="bold bright_green"),
        Text("  DOM: "),
        Text("< 14d", style="bright_green"),
        Text(" / "),
        Text("14–59d", style="white"),
        Text(" / "),
        Text("≥ 60d", style="yellow"),
        Text("  "),
        Text("● active", style="bright_green"),
        Text("  "),
        Text("✕ removed", style="dim red"),
        Text("  "),
        Text("Address is a hyperlink — tap to open in browser", style="dim"),
    ]
    line = Text()
    for part in legend_parts:
        line.append_text(part)
    console.print(line)
    console.print()


if __name__ == "__main__":
    show_dashboard()
