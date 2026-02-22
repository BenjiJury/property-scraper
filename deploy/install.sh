#!/usr/bin/env bash
# install.sh — sets up the property-tracker on a Raspberry Pi / Linux host.
# Usage: bash deploy/install.sh <username>
# e.g.   bash deploy/install.sh ben

set -euo pipefail

USERNAME="${1:-$(whoami)}"
REPO=/home/$USERNAME/property-tracker
VENV=$REPO/venv
SERVICE_DIR=/etc/systemd/system

echo "=== Property Tracker installer ==="
echo "Repo   : $REPO"
echo "User   : $USERNAME"
echo ""

# ── 1. Python virtual environment ─────────────────────────────────────────────
echo "[1/4] Creating Python venv at $VENV ..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$REPO/requirements.txt"
echo "      Dependencies installed."

# ── 2. Make run.sh executable ──────────────────────────────────────────────────
echo "[2/4] Setting permissions on run.sh ..."
chmod +x "$REPO/deploy/run.sh"

# ── 3. Install systemd units ───────────────────────────────────────────────────
echo "[3/4] Installing systemd units ..."
sudo cp "$REPO/deploy/property-tracker.service" "$SERVICE_DIR/"
sudo cp "$REPO/deploy/property-tracker.timer"   "$SERVICE_DIR/"
sudo systemctl daemon-reload

# ── 4. Enable and start the timer ─────────────────────────────────────────────
echo "[4/4] Enabling property-tracker.timer ..."
sudo systemctl enable --now property-tracker.timer

echo ""
echo "=== Done ==="
echo "Timer status:"
systemctl status property-tracker.timer --no-pager || true
