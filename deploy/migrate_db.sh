#!/usr/bin/env bash
# migrate_db.sh — Copy properties.db from your Android phone to the Pi.
#
# Run this once during initial setup so you don't lose your historical data.
#
# Usage
# -----
#   Option A — via ADB (phone connected by USB with USB debugging enabled):
#     bash deploy/migrate_db.sh --adb
#
#   Option B — from a local file (e.g. copied via Google Drive or SCP):
#     bash deploy/migrate_db.sh /path/to/properties.db
#
#   Option C — from another host over SSH:
#     scp user@192.168.x.x:/path/to/properties.db /tmp/properties.db
#     bash deploy/migrate_db.sh /tmp/properties.db

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEST="$REPO_DIR/property_tracker/properties.db"

# Path to the DB inside Termux on Android (adjust if your Termux home differs)
TERMUX_DB_PATH="/data/data/com.termux/files/home/property-scraper/property_tracker/properties.db"

if [ "${1:-}" = "--adb" ]; then
    echo "Pulling properties.db from Android via ADB …"
    if ! command -v adb &>/dev/null; then
        echo "Error: adb not found. Install android-tools: sudo apt install android-tools-adb" >&2
        exit 1
    fi
    adb pull "$TERMUX_DB_PATH" "$DEST"
    echo "Done. Database written to: $DEST"

elif [ -n "${1:-}" ] && [ -f "$1" ]; then
    cp "$1" "$DEST"
    echo "Done. Database copied from $1 to $DEST"

else
    echo "Usage:"
    echo "  bash deploy/migrate_db.sh --adb               # pull from phone via ADB"
    echo "  bash deploy/migrate_db.sh /path/to/properties.db"
    echo ""
    echo "The database will be written to:"
    echo "  $DEST"
    exit 1
fi
