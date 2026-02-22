#!/usr/bin/env bash
# install.sh — Set up the property tracker on a Raspberry Pi (or any Debian/
# Ubuntu Linux system).
#
# Usage:
#   bash deploy/install.sh            # run service as the current user
#   bash deploy/install.sh myuser     # run service as a specific user
#
# What this does:
#   1. Creates a Python virtual environment and installs dependencies
#   2. Installs and enables the systemd service + timer units
#   3. Prints ntfy setup instructions if ntfy is not yet installed
#
# Prerequisites:
#   - Python 3.10+  (sudo apt install python3 python3-venv)
#   - sudo access   (to install systemd units)
#   - Git repo already cloned to this machine

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$REPO_DIR/.venv"
SERVICE_USER="${1:-$(whoami)}"
SERVICE_NAME="property-tracker"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Property Tracker — Raspberry Pi Setup              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Repo:    $REPO_DIR"
echo "  Venv:    $VENV_DIR"
echo "  User:    $SERVICE_USER"
echo ""

# ── 1. Python virtual environment ─────────────────────────────────────────────
echo "▸ [1/4] Creating Python virtual environment …"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
echo "  ✓ venv ready at $VENV_DIR"

# ── 2. Systemd units ──────────────────────────────────────────────────────────
echo "▸ [2/4] Installing systemd units …"

# Substitute {REPO_DIR} and {USER} placeholders in the service template.
sed \
    -e "s|{REPO_DIR}|$REPO_DIR|g" \
    -e "s|{USER}|$SERVICE_USER|g" \
    "$SCRIPT_DIR/$SERVICE_NAME.service" \
    | sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null

sudo cp "$SCRIPT_DIR/$SERVICE_NAME.timer" /etc/systemd/system/$SERVICE_NAME.timer
sudo systemctl daemon-reload
echo "  ✓ units installed (/etc/systemd/system/$SERVICE_NAME.*)"

# ── 3. Enable timer ───────────────────────────────────────────────────────────
echo "▸ [3/4] Enabling and starting timer …"
sudo systemctl enable --now $SERVICE_NAME.timer
echo "  ✓ timer active — will run at 08:00 and 18:00 daily"

# ── 4. ntfy push notifications ───────────────────────────────────────────────
echo "▸ [4/4] Checking for ntfy …"

if command -v ntfy &>/dev/null; then
    echo "  ✓ ntfy already installed ($(ntfy version 2>/dev/null || echo 'version unknown'))"
elif command -v docker &>/dev/null; then
    echo ""
    echo "  Docker found. To run ntfy as a container:"
    echo ""
    echo "    docker run -d --name ntfy \\"
    echo "      -p 80:80 \\"
    echo "      -v /data/ntfy:/etc/ntfy \\"
    echo "      --restart unless-stopped \\"
    echo "      binwiederhier/ntfy serve"
    echo ""
    echo "  Then set NTFY_URL in property_tracker/config.py, e.g.:"
    echo "    NTFY_URL = \"http://localhost/property-tracker-abc123\""
else
    echo ""
    echo "  ntfy not found. Install it (arm64 / Pi):"
    echo ""
    echo "    sudo mkdir -p /etc/apt/keyrings"
    echo "    curl -fsSL https://archive.heckel.io/apt/pubkey.txt \\"
    echo "      | sudo gpg --dearmor -o /etc/apt/keyrings/archive.heckel.io.gpg"
    echo "    sudo sh -c \"echo 'deb [arch=arm64 signed-by=/etc/apt/keyrings/archive.heckel.io.gpg]"
    echo "      https://archive.heckel.io/apt debian main'"
    echo "      > /etc/apt/sources.list.d/archive.heckel.io.list\""
    echo "    sudo apt update && sudo apt install ntfy"
    echo "    sudo systemctl enable --now ntfy"
    echo ""
    echo "  Or use ntfy.sh cloud (no self-hosting needed):"
    echo "    Set NTFY_URL = \"https://ntfy.sh/your-secret-topic\" in config.py"
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit config:   $REPO_DIR/property_tracker/config.py"
echo "     — set NTFY_URL to your ntfy topic URL"
echo "     — verify DISCORD_WEBHOOK_URL is correct"
echo ""
echo "  2. (Optional) Copy your existing database from Android:"
echo "     bash $SCRIPT_DIR/migrate_db.sh --adb"
echo "     or manually copy properties.db to:"
echo "     $REPO_DIR/property_tracker/properties.db"
echo ""
echo "  3. Test a run:    sudo systemctl start $SERVICE_NAME.service"
echo "     Live logs:     journalctl -u $SERVICE_NAME -f"
echo "     Timer status:  systemctl list-timers $SERVICE_NAME.timer"
echo ""
echo "  4. ntfy Android:  install the ntfy app → subscribe to your topic"
echo "══════════════════════════════════════════════════════"
