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
| `data-fonts="off"` | Does not load the brand fonts |
| `data-url="on"` | Keeps the chosen dates, tab and filter in the page address, so a view can be copied and shared. On for the preview page |
| `data-sticky-top="94"` | Pixels to leave above the pinned tab bar. By default the widget measures the page's own fixed header and sits just below it |

The widget renders in a shadow root, so page styles do not leak in or out.

Fonts are the brand faces trlibrary.com uses: Dharma Gothic E for the heading, Clearface for names and descriptions, Frutiger for labels, tabs and buttons. On trlibrary.com the page already has them. Anywhere else (including lodging.labs) the widget loads the five font files from `www.trlibrary.com/themes/custom/trpl/css/`, which serves them to any site. No font files are stored in this repository.

### Linking to a view

The page address can open the finder on a particular view. All parts are optional:

`?checkin=2027-06-18&nights=2&tab=rentals&type=cabin&place=hotel-1883`

| Part | Values |
|---|---|
| `checkin` | A date, `YYYY-MM-DD`. Past dates are ignored |
| `nights` | 1 to 7 |
| `tab` | `medora`, `rentals`, `nearby`, `dickinson` |
| `type` | `all`, `hotel`, `cabin`, `camping` |
| `place` | A property id from `data/properties.json`. Its card is scrolled into view and outlined. If `tab` is left out, the tab that place is in opens |

This works wherever the widget is embedded, so staff can send a visitor a link to trlibrary.com with dates already chosen.

## Staff monitor

`monitor.html` is a grid of every tracked night against every tracked property, using the full width of the window and scrolling with the page (the header row stays in view). Each cell is a link: it opens the finder in a second tab on that night, on the right tab, with that property outlined. The night in the first column opens the finder on that night; the Dickinson count opens the Dickinson tab. Rows in "Recent changes" link the same way.

## What visitors see

Every place is a card: photo, name, where it is, a one-line description, a status, one button, and the phone number as a plain link.

A tab bar splits the cards into four groups, and only one group shows at a time: **Medora**, **Vacation rentals**, **Nearby towns** and **Dickinson**. Each tab shows how many places are open for the chosen dates. The bar stays pinned under the site header while the visitor scrolls, and switching tabs brings the top of the new group into view. Arrow keys move between tabs.

Inside a tab the cards are grouped by status:

- **Open for your dates**: every night of the stay had a room or site at the last check. The button opens the booking site on those dates. No rates are shown.
- **Check directly**: availability is not tracked, or the last check is more than ten days old. The button is a dated link where the booking site supports one, the website, or the phone number.
- **Full or closed on these dates**: checked, and nothing available.

### Vacation rentals

Each Airbnb and Vrbo listing gets its own card with its photo, the host's title and a "View on Airbnb" or "View on Vrbo" button that opens that listing on the chosen dates. A listing that appears on both sites under the same name becomes one card with a button for each. Two cards at the end link to the full Airbnb and Vrbo searches.

Controls in `data/properties.json`:

| Setting | Effect |
|---|---|
| `"list_units": true` | Shows each listing as its own card. Remove it to go back to one card with a count |
| `live.hide` | Listing IDs never to show |
| `live.min_rating` | Listings whose guest rating is under this share of the scale are left out (default `0.7`: under 7 of 10 on Vrbo with at least three reviews, under 3.5 stars on Airbnb). Ratings are used only for this and are not stored or shown |
| `live.listings` (Airbnb) | The Airbnb listing IDs to track. This list is kept by hand: a new Airbnb listing does not appear until its ID is added |
| `live.start` (Vrbo) | The map area searched on every run. New Vrbo listings inside it appear on their own |

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

Every public property has a photo as of October 2026. For each one the step tries, in order:

1. `"photo"` in `data/properties.json`: an address set by hand, for example a Library photograph. `"photo": false` means never show one.
2. The link-preview image the property's own website publishes (the picture that appears when the page is shared). Logos, placeholders, small or oddly shaped images, and any image that several properties share are passed over.
3. The first large landscape image in the body of the property's own page.
4. The photo Google Hotels shows for the property, noted by the collector during a `google_hotels` run. This covers tracked hotels and any property with `"photo_match"`.
5. For cabins read from Airbnb calendars, the photo of their first Airbnb listing.
6. The photo Google Maps shows for the search named in `"photo_search"`. This costs one SearchApi search, and only when no photo is on file or the old one has stopped loading.

Airbnb listing cards take their title and photo from each listing page's link preview. Vrbo listing cards take theirs from the same Apify run that reads the calendars.

Google's photos (steps 4 and 6) can be guest-contributed rather than the property's own; `python collector/photos.py --no-google` leaves them out. Each website is looked at about once a week. A card with no photo, or whose photo stops loading, shows a plain panel with a small icon.

```bash
python collector/photos.py                    # weekly refresh (what the workflow runs)
python collector/photos.py --all              # look at every site again now
python collector/photos.py --only hotel-1883  # one property
```

## Keys

Locally, copy `.env.example` to `.env` and fill it in. `.env` is ignored by git.

On GitHub: Settings → Secrets and variables → Actions. `LODGING_SOURCES` is a Variable; `SEARCHAPI_KEY` and `APIFY_TOKEN` are Secrets. The photo step also reads `SEARCHAPI_KEY`, for the Google Maps fallback only.

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
