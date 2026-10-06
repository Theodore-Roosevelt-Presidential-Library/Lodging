# Lodging Finder

An embeddable widget that helps Theodore Roosevelt Presidential Library visitors find a place to stay near Medora, North Dakota, plus an internal availability monitor. Served from GitHub Pages at `lodging.labs.trlibrary.com`; data is refreshed by a GitHub Action.

## Embed

```html
<div id="trpl-lodging"></div>
<script src="https://lodging.labs.trlibrary.com/lodging.js" defer></script>
```

Optional attributes on the script tag:

| Attribute | Effect |
|---|---|
| `data-heading="off"` | Hides the built-in heading and intro, for pages that have their own |
| `data-target="#id"` | Mounts in a different element |
| `data-area="medora"` | Shows only Medora-area lodging (`medora`, `nearby` or `dickinson`) |

The widget renders in a shadow root, so page styles do not leak in or out. It inherits the page's body font and uses the site's heading faces when they are loaded.

## What visitors see

- **Open for your dates**: properties with a live source, when every night of the stay had a room or site at the last check. Shows that rooms or sites were available and a Book button that opens the property's booking site on those dates. Cabins and rentals show a count ("3 units available", "9 rentals available"). Open Dickinson hotels sit in their own fold. No rates are shown.
- **Places to check directly**: everything else, grouped by area, with a dated link where the booking site supports one, or a phone number.
- **Full or closed on these dates**: live properties with no availability.

## Files

| Path | Purpose |
|---|---|
| `data/properties.json` | The property list. Edit by hand. `"public": false` hides a property. |
| `collector/collect.py` | Checks live sources and writes `docs/data/availability.json` |
| `docs/lodging.js` | The widget (single file, no dependencies) |
| `docs/index.html` | Preview page with the embed snippet |
| `docs/monitor.html` | Internal grid of every tracked night, plus a log of nights opening up and selling out |
| `docs/data/availability.json` | Output read by the widget and monitor |
| `docs/data/changes.csv` | Appended whenever a night opens up or sells out |
| `.github/workflows/collect.yml` | Daily refresh |
| `tests/` | Offline tests for the collector |
| `.env.example` | Template for local keys; copy to `.env` |

## Live sources

Sources are switched on with `LODGING_SOURCES` (comma-separated) and read their keys from the environment. A source that is not listed makes no requests; a listed source whose key is missing is skipped.

| Key | Covers | Needs | Status |
|---|---|---|---|
| `trmf` | Hotel 1883, Rough Riders Hotel and inns, Badlands Motel, Elkhorn Quarters, Medora Campground | Nothing | Confirmed against the live booking engine. **Off pending the Medora Foundation's agreement**; see PLAN.md. |
| `google_hotels` | 16 Dickinson hotels, AmericInn Medora, Trapper's Inn | `SEARCHAPI_KEY` | Written from SearchApi's documentation; not yet run live |
| `airbnb` | 15 known Airbnb listings around Medora, shown as one count; plus the Vacation Medora cabins that are on Airbnb (2 at Boots, 6 at The Crossings) | `APIFY_TOKEN` | Written from the Apify actor's documentation; not yet run live |
| `guesty` | Nothing today. Kept for any operator who shares Guesty Booking Engine API credentials | `GUESTY_CLIENT_ID`, `GUESTY_CLIENT_SECRET` | Written from Guesty's documentation; unused |
| `vrbo` | Vrbo listings in a map area around Medora, shown as one count | `APIFY_TOKEN` | Written from the Apify actor's documentation; not yet run live |

How each reads availability:

- **trmf**: one request per property per night. A daily run checks the next 45 nights and one-seventh of the nights beyond, out to 330.
- **google_hotels**: one search per town per night (two pages for Dickinson). A hotel showing a rate is "open"; a hotel with no rate, or missing from the results, is "unknown", never "full". Checks the next 21 nights daily and one-seventh of the rest, out to 120 nights: about 100 to 150 searches a day.
- **guesty**, **airbnb**, **vrbo**: read each listing's calendar for the whole horizon in one pass per day. The widget counts a cabin or rental only if it is open every night of the stay.

Rates returned by these services are discarded; nothing price-related is written to `docs/data/`.

## Keys

Locally, copy `.env.example` to `.env` and fill it in. `.env` is ignored by git.

On GitHub: Settings → Secrets and variables → Actions. `LODGING_SOURCES` is a Variable; `SEARCHAPI_KEY` and `APIFY_TOKEN` are Secrets.

After adding a key, confirm it before the first real run:

```bash
python collector/collect.py --check
```

This makes one small request per enabled source and prints what came back: which hotels matched and the fields each service returned. It writes nothing. The Airbnb and Vrbo checks each start a small paid Apify run (a few cents).

## Run locally

```bash
python -m unittest discover -s tests          # offline tests, no network
python collector/collect.py --dry-run         # show the plan, no requests
python collector/collect.py --check           # test each enabled source's connection
python collector/collect.py --limit 3         # real run, first 3 nights only for per-night sources
python collector/collect.py                   # normal run
cd docs && python -m http.server 8000         # preview at http://localhost:8000
```

## GitHub Pages setup

1. Settings → Pages → Deploy from a branch → `main`, folder `/docs`.
2. Custom domain `lodging.labs.trlibrary.com` (already in `docs/CNAME`; the wildcard DNS record covers it).
3. Settings → Actions → General → Workflow permissions → Read and write.
