#!/usr/bin/env bash
# run.sh — Activate the venv, run the scraper, then optionally sync the
# latest CSV to a remote destination via rclone (e.g. Google Drive).
#
# Called by the systemd service unit.  Can also be run manually:
#   bash deploy/run.sh
#
# Google Drive sync
# -----------------
# Install rclone and run `rclone config` to set up a remote named "gdrive".
# Then set RCLONE_DEST below (or export it before calling this script):
#
#   RCLONE_DEST="gdrive:PropertyTracker"
#
# Leave empty to skip the sync step.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$REPO_DIR/.venv/bin/python3"

# ── Scrape ────────────────────────────────────────────────────────────────────
"$PYTHON" "$REPO_DIR/property_tracker/main.py"

# ── Google Drive sync (optional) ──────────────────────────────────────────────
RCLONE_DEST="${RCLONE_DEST:-}"

if [ -n "$RCLONE_DEST" ] && command -v rclone &>/dev/null; then
    CSV="$REPO_DIR/property_tracker/properties_latest.csv"
    if [ -f "$CSV" ]; then
        rclone copy "$CSV" "$RCLONE_DEST" --quiet
        echo "CSV synced to $RCLONE_DEST"
    fi
elif [ -n "$RCLONE_DEST" ]; then
    echo "Warning: RCLONE_DEST is set but rclone is not installed. Skipping sync." >&2
fi
