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
| `data-photos="off"` | Never shows photos |
| `data-photos="all"` | Also shows small photos in the "check directly" lists (off by default because too few properties have one) |

The widget renders in a shadow root, so page styles do not leak in or out. It inherits the page's body font and uses the site's heading faces when they are loaded.

## What visitors see

- **Open for your dates**: properties with a live source, when every night of the stay had a room or site at the last check. Each is a card: photo when one is known, name, where it is, "Rooms available" and when that was checked, one Book button that opens the property's booking site on those dates, and the phone number as a plain link beside it. Cabins and rentals show a count ("3 units available", "9 rentals available"). Open Dickinson hotels sit in their own fold. No rates are shown.
- **Places to check directly**: everything else, grouped by area, one line each: name, where it is, season, and a single button (dated link, website or phone).
- **Full or closed on these dates**: live properties with no availability.

The free Medora trolley is seasonal. `trolley_months` in `data/properties.json` lists the months it runs (June through September, per trlibrary.com/visit/trolley). A property marked `"trolley": true` gets "Free summer trolley stop" only when every night of the stay falls in those months. Change the list if the season changes; an empty list removes the mention.

## Files

| Path | Purpose |
|---|---|
| `data/properties.json` | The property list. Edit by hand. `"public": false` hides a property. |
| `collector/collect.py` | Checks live sources and writes `docs/data/availability.json` |
| `collector/photos.py` | Finds a photo address for each property and writes `docs/data/photos.json` |
| `docs/lodging.js` | The widget (single file, no dependencies) |
| `docs/index.html` | Preview page with the embed snippet |
| `docs/monitor.html` | Internal grid of every tracked night, plus a log of nights opening up and selling out |
| `docs/data/availability.json` | Output read by the widget and monitor |
| `docs/data/changes.csv` | Appended whenever a night opens up or sells out |
| `docs/data/photos.json` | Photo addresses read by the widget |
| `docs/data/photo_hints.json` | The photo Google Hotels shows for each tracked hotel, noted by the collector |
| `.github/workflows/collect.yml` | Daily refresh |
| `tests/` | Offline tests for the collector |
| `.env.example` | Template for local keys; copy to `.env` |

## Live sources

Sources are switched on with `LODGING_SOURCES` (comma-separated) and read their keys from the environment. A source that is not listed makes no requests; a listed source whose key is missing is skipped.

| Key | Covers | Needs | Status |
|---|---|---|---|
| `trmf` | Hotel 1883, Rough Riders Hotel and inns, Badlands Motel, Elkhorn Quarters, Medora Campground | Nothing | Tested live Oct 5. Goes against the booking site's robots.txt; see PLAN.md. |
| `google_hotels` | 16 Dickinson hotels, AmericInn Medora, Trapper's Inn | `SEARCHAPI_KEY` | Tested live Oct 5; all 18 hotels matched. Needs SearchApi's $40 plan to run daily. |
| `airbnb` | 15 known Airbnb listings around Medora, shown as one count; plus the Vacation Medora cabins that are on Airbnb (2 at Boots, 6 at The Crossings) | `APIFY_TOKEN` | Tested live Oct 5 |
| `guesty` | Nothing today. Kept for any operator who shares Guesty Booking Engine API credentials | `GUESTY_CLIENT_ID`, `GUESTY_CLIENT_SECRET` | Written from Guesty's documentation; unused |
| `vrbo` | Vrbo listings in a map area around Medora, shown as one count | `APIFY_TOKEN` | Tested live Oct 5 |

How each reads availability:

- **trmf**: one request per property per night. A daily run checks the next 45 nights and one-seventh of the nights beyond, out to 330.
- **google_hotels**: one search per town per night (two pages for Dickinson). A hotel showing a rate is "open"; a hotel with no rate, or missing from the results, is "unknown", never "full". Checks the next 21 nights daily and one-seventh of the rest, out to 120 nights: about 100 to 150 searches a day.
- **guesty**, **airbnb**, **vrbo**: read each listing's calendar for the whole horizon in one pass per day. The widget counts a cabin or rental only if it is open every night of the stay.

Rates returned by these services are discarded; nothing price-related is written to `docs/data/`.

## Photos

`collector/photos.py` records where a photo of each property lives; the widget then shows it straight from that address. No image is copied into this repository.

For each public property it tries, in order:

1. `"photo"` in `data/properties.json`: an address set by hand, for example a Library photograph. `"photo": false` means never show one.
2. The link-preview image the property's own website publishes (the picture that appears when the page is shared). Logos, placeholders, very small or oddly shaped images, and any image that several properties share are passed over.
3. The photo Google Hotels shows for the property, noted by the collector during a `google_hotels` run. This covers tracked hotels and any property with `"photo_match"`. These can be guest photos rather than the hotel's own; run with `--no-google` to leave them out.

Each website is looked at about once a week. Airbnb and Vrbo cards have no photo. Photos appear on the "open for your dates" cards; the "check directly" lists stay text-only unless the embed sets `data-photos="all"`.

```bash
python collector/photos.py                    # weekly refresh (what the workflow runs)
python collector/photos.py --all              # look at every site again now
python collector/photos.py --only hotel-1883  # one property
```

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
python collector/photos.py                    # refresh photo addresses
cd docs && python -m http.server 8000         # preview at http://localhost:8000
```

## GitHub Pages setup

1. Settings → Pages → Deploy from a branch → `main`, folder `/docs`.
2. Custom domain `lodging.labs.trlibrary.com` (already in `docs/CNAME`; the wildcard DNS record covers it).
3. Settings → Actions → General → Workflow permissions → Read and write.
