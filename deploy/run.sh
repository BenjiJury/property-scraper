#!/usr/bin/env bash
# run.sh — wrapper called by systemd each run.
#   1. Runs the scraper.
#   2. Exports a CSV.
#   3. (Optional) Syncs CSV to Google Drive via rclone.
#
# Override RCLONE_DEST via /etc/systemd/system/property-tracker.service
# or an EnvironmentFile.

set -euo pipefail

REPO=/home/ben/property-tracker
VENV=$REPO/venv
APP=$REPO/property_tracker
RCLONE_DEST="${RCLONE_DEST:-gdrive:PropertyTracker}"

# ── 1. Run the scraper ─────────────────────────────────────────────────────────
"$VENV/bin/python3" "$APP/main.py"

# ── 2. Export CSV ──────────────────────────────────────────────────────────────
"$VENV/bin/python3" "$APP/export_csv.py"

# ── 3. Sync to Google Drive ────────────────────────────────────────────────────
if [ -n "$RCLONE_DEST" ] && command -v rclone &>/dev/null; then
    echo "Syncing CSV to $RCLONE_DEST ..."
    rclone copy "$APP/properties.csv" "$RCLONE_DEST" \
        --log-level INFO \
        || echo "rclone sync failed — check: rclone config, rclone listremotes" >&2
fi
