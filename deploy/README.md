# Raspberry Pi Deployment

**Last set up:** 2026-02-22
**Pi address:** `192.168.1.131`
**SSH user:** `ben`
**SSH key:** `~/.ssh/id_ed25519` (key already in `~ben/.ssh/authorized_keys` on the Pi)

---

## What is deployed

| Component | Path / location |
|---|---|
| Repo | `~/property-tracker/` |
| Python venv | `~/property-tracker/venv/` |
| App source | `~/property-tracker/property_tracker/` |
| SQLite database | `~/property-tracker/property_tracker/properties.db` |
| CSV export | `~/property-tracker/property_tracker/properties.csv` |
| Run wrapper | `~/property-tracker/deploy/run.sh` |
| systemd service | `/etc/systemd/system/property-tracker.service` |
| systemd timer | `/etc/systemd/system/property-tracker.timer` |
| ntfy container | Docker — `binwiederhier/ntfy`, internal port `2586` |
| Google Drive sync | `remote:PropertyTracker` (rclone, already authenticated) |

---

## Schedule

The timer fires **every 2 hours**, starting 5 minutes after boot.

```
OnBootSec=5min
OnUnitActiveSec=2h
Persistent=true
```

Each run:
1. Scrapes Rightmove for all configured areas (`config.py → SEARCH_LOCATIONS`)
2. Detects new listings and price drops; sends ntfy push notification
3. Exports `properties.csv`
4. Syncs the CSV to `remote:PropertyTracker` on Google Drive via rclone

---

## Key configuration

### `property_tracker/config.py`

```python
NTFY_URL = "http://localhost:2586/keng-kxm29"
RCLONE_DEST = "remote:PropertyTracker"   # set via systemd service Environment=
```

### Notifications (ntfy)

Topic: **`keng-kxm29`**

The ntfy Docker container is currently bound to **`localhost:2586` only** —
it is not exposed externally. To receive notifications on the Android app you
must do one of the following:

**Option A — Route through Traefik (recommended)**

Add an ntfy service to your existing Traefik/docker-compose setup so that
the Android app can reach `https://ntfy.<your-domain>/keng-kxm29`.
Then update `config.py`:
```python
NTFY_URL = "https://ntfy.<your-domain>/keng-kxm29"
```
And restart the service:
```bash
sudo systemctl daemon-reload
```

**Option B — Switch to ntfy.sh cloud (simplest)**

No server setup needed. Update `config.py` on the Pi:
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "sed -i 's|http://localhost:2586/keng-kxm29|https://ntfy.sh/keng-kxm29|' \
  ~/property-tracker/property_tracker/config.py"
```
In the Android ntfy app: subscribe to topic `keng-kxm29` on server `https://ntfy.sh`.

---

## SSH access

```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131
```

The Pi drops SSH connections briefly after heavy operations (pip install, docker
pull, etc.) — it reconnects within ~20 seconds. Likely a WiFi stability issue.
Worth checking `/var/log/syslog` for OOM or kernel errors if it persists.

---

## Common operations

### Check when the next run fires
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "systemctl list-timers property-tracker.timer --no-pager"
```

### Trigger an immediate run
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "sudo systemctl start property-tracker.service"
```

### Watch live logs
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "journalctl -fu property-tracker"
```

### View last run logs
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "journalctl -u property-tracker --since '2 hours ago' --no-pager"
```

### View the dashboard
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "cd ~/property-tracker/property_tracker && \
   ../venv/bin/python3 dashboard.py"
```

### Re-run install after pulling new code
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 \
  "cd ~/property-tracker && git pull && bash deploy/install.sh ben"
```

---

## Known issue — scraper returning 0 listings

On the first test run (2026-02-22), every area returned:
```
WARNING: Could not extract window.jsonModel from page
```

This means Rightmove's page HTML is not containing the expected JSON data block.
Possible causes:
- Rightmove has changed their page structure (most likely)
- The Pi's IP is being rate-limited or blocked

To debug:
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 bash -s <<'EOF'
cd ~/property-tracker/property_tracker
# Fetch a Rightmove page and check for jsonModel
../venv/bin/python3 -c "
import requests, re
url = 'https://www.rightmove.co.uk/property-for-sale/find.html?locationIdentifier=REGION^93924&minBedrooms=3&maxBedrooms=4&minPrice=900000&maxPrice=1100000&propertyTypes=detached,semi-detached,terraced&primaryDisplayPropertyType=houses'
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
print('Status:', r.status_code)
print('jsonModel found:', bool(re.search(r'window\.jsonModel', r.text)))
print('First 500 chars of body:', r.text[:500])
"
EOF
```

If `jsonModel found: False`, the scraper's extraction logic in `scraper.py`
needs updating to match Rightmove's current page structure.

---

## Google Drive sync

rclone remote name: **`remote`** (type: Google Drive, already authenticated)
Destination folder: **`remote:PropertyTracker`**

The token will auto-refresh. If it ever expires:
```bash
ssh -i ~/.ssh/id_ed25519 ben@192.168.1.131 "rclone config reconnect remote:"
```

---

## Files added by this deployment

```
property-tracker/
├── requirements.txt                        # pip dependencies
├── property_tracker/
│   ├── config.py                           # updated: NTFY_URL added, Termux removed
│   ├── notifier.py                         # replaced: ntfy HTTP instead of termux-notification
│   └── export_csv.py                       # new: exports properties.csv after each run
└── deploy/
    ├── README.md                           # this file
    ├── run.sh                              # systemd ExecStart wrapper
    ├── install.sh                          # re-run to reinstall after git pull
    ├── property-tracker.service            # systemd service unit
    └── property-tracker.timer             # systemd timer unit (every 2h)
```
