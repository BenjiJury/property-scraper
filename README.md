# Property Tracker

A Rightmove scraper that runs entirely on Android via Termux.

Watches South and South West London for 3–4 bedroom freehold houses
priced £900k–£1.1m, stores results in SQLite, sends Android push
notifications for new listings and price reductions, and renders a
Rich terminal dashboard.

---

## Project layout

```
property_tracker/
├── config.py      # Search parameters and settings
├── database.py    # SQLite schema and query helpers
├── scraper.py     # Rightmove scraper (requests + BeautifulSoup4)
├── tracker.py     # Change detection (new listings, price drops)
├── notifier.py    # Termux push notifications
├── dashboard.py   # Rich terminal table
└── main.py        # Cron entry point: scrape → track → notify
```

---

## Prerequisites

### 1 — Install Termux

**Use the F-Droid version only.**
The Google Play version is no longer maintained and has an outdated
package repository.

1. Install [F-Droid](https://f-droid.org/) on your Android device.
2. Search for **Termux** in F-Droid and install it.
3. Open Termux and run the initial update:

```bash
pkg update && pkg upgrade -y
```

### 2 — Install Termux:API

Notifications require two things installed from the same F-Droid
session so their signatures match:

1. In F-Droid, search for **Termux:API** and install the companion app.
2. Inside Termux, install the command-line bridge:

```bash
pkg install termux-api -y
```

Test it works:

```bash
termux-notification --title "Test" --content "Termux:API is working"
```

You should see an Android notification appear.

### 3 — Install Python and dependencies

```bash
pkg install python -y
pip install requests beautifulsoup4 rich
```

### 4 — Clone the repository

```bash
pkg install git -y
git clone <repo-url> ~/property_tracker
cd ~/property_tracker/property_tracker
```

---

## Configuration

Open `config.py` in a text editor (e.g. `nano config.py`) and review:

| Setting | Default | Notes |
|---|---|---|
| `MIN_BEDROOMS` / `MAX_BEDROOMS` | 3 / 4 | Bedroom range |
| `MIN_PRICE` / `MAX_PRICE` | 900,000 / 1,100,000 | GBP |
| `PRICE_DROP_THRESHOLD` | 0 | Minimum £ drop to notify (0 = any) |
| `FILTER_FREEHOLD` | True | Skip explicit leasehold listings |
| `TERMUX_API_AVAILABLE` | True | Set False to disable notifications |

### Verifying location identifiers

Rightmove uses internal numeric IDs for every region.  The defaults in
`config.py` cover the six boroughs.  To verify or update any of them:

```bash
# Option 1 — built-in lookup helper
python3 -c "
from scraper import lookup_location
for r in lookup_location('Wandsworth'):
    print(r)
"

# Option 2 — search on rightmove.co.uk and copy the locationIdentifier
# from the URL, e.g.:
# https://www.rightmove.co.uk/property-for-sale/find.html?locationIdentifier=REGION%5E93924
#                                                                                     ^^^^^^^
```

---

## First run

```bash
cd ~/property_tracker/property_tracker
python3 main.py
```

The first run populates the database.  All listings found are treated as
new and generate a grouped notification.  Subsequent runs only notify
on genuinely new or price-reduced properties.

After the database is populated, view the dashboard at any time:

```bash
python3 dashboard.py
```

---

## Setting up the cron job (every 2 hours)

### Install cronie

```bash
pkg install cronie -y
```

### Edit your crontab

```bash
crontab -e
```

Add this line (uses `nano` by default; press Ctrl+X, Y, Enter to save):

```
0 */2 * * * cd /data/data/com.termux/files/home/property_tracker/property_tracker && python3 main.py >> tracker.log 2>&1
```

> **Tip:** adjust the path if you cloned the repo elsewhere.
> Run `echo $HOME` in Termux to confirm your home directory.

### Start crond

```bash
crond
```

Verify it is running:

```bash
pgrep crond && echo "crond is running"
```

---

## Keep the phone awake — termux-wake-lock

Android aggressively kills background processes.  Acquire a wake lock
so the cron daemon stays alive when the screen is off:

```bash
termux-wake-lock
```

Run this manually after each reboot, **or** automate it with
Termux:Boot (below).

---

## Auto-start after reboot — Termux:Boot

### Install Termux:Boot

1. In F-Droid, search for **Termux:Boot** and install it.
2. Open the Termux:Boot app once so Android registers it.

### Create the boot script

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-tracker.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Acquire wake lock so crond isn't killed when the screen turns off
termux-wake-lock
# Start the cron daemon
crond
EOF
chmod +x ~/.termux/boot/start-tracker.sh
```

Now `crond` (and the wake lock) will start automatically after every
Android reboot.

---

## Battery and data usage

| Factor | Detail |
|---|---|
| Scrape interval | Every 2 hours = 12 runs/day |
| Pages per run | ~6 areas × ~2 pages = ~12 HTTP requests |
| Request delay | 4–10 s random delay between each request |
| Typical run time | 2–4 minutes |
| Wake lock | Keeps CPU at min frequency; moderate battery impact |

To reduce battery drain further, switch to a less frequent schedule in
crontab (e.g. `0 */4 * * *` for every 4 hours).

---

## Troubleshooting

### No listings returned

1. Check network connectivity from Termux: `curl -I https://www.rightmove.co.uk`
2. Verify location identifiers (see *Verifying location identifiers* above).
3. Rightmove occasionally restructures their pages.  Check `tracker.log`
   for "Could not extract window.jsonModel" warnings.

### Notifications not appearing

- Confirm Termux:API app (from F-Droid) is installed alongside `pkg install termux-api`.
- Make sure Android has not revoked notification permissions for Termux.
  Go to Settings → Apps → Termux → Notifications → Allow.
- Test manually: `termux-notification --title "Test" --content "Hello"`

### crond stops after reboot

- Ensure Termux:Boot is installed and has been opened at least once.
- Check the boot script is executable: `ls -la ~/.termux/boot/`
- Verify crond is running: `pgrep crond`

### "Permission denied" on the DB file

The database is stored inside the `property_tracker/` directory.
If you see permission errors, ensure Python can write there:

```bash
ls -la ~/property_tracker/property_tracker/properties.db
```

---

## Resetting the database

To start fresh (e.g. after changing search criteria):

```bash
rm ~/property_tracker/property_tracker/properties.db
python3 ~/property_tracker/property_tracker/main.py
```

All listings will be re-imported as new on the next run.

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP client for Rightmove requests |
| `beautifulsoup4` | HTML parsing fallback |
| `rich` | Terminal dashboard rendering |
| `sqlite3` | Built-in Python — no install needed |
| `termux-api` (pkg) | Bridge to `termux-notification` |
