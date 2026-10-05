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

- **Open for your dates**: properties with a live source, when every night of the stay had a room or site at the last check. Shows that rooms or sites were available and a Book button that opens the property's booking site on those dates. No rates are shown.
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

## Live sources

Live sources are switched on with the `LODGING_SOURCES` repository variable (Settings → Secrets and variables → Actions → Variables). It is unset by default, so the daily run makes no outside requests until a source is turned on.

| Key | Covers | Status |
|---|---|---|
| `trmf` | Hotel 1883, Rough Riders Hotel and inns, Badlands Motel, Elkhorn Quarters, Medora Campground (the Medora Foundation's booking engine) | Built and tested. **Off pending the Foundation's agreement**; see PLAN.md. |

A daily run checks the next 45 nights and one-seventh of the nights beyond that, out to 330 nights, one request per property per night with a one-second pause. The first run after switching a source on checks every night.

## Run locally

```bash
python -m unittest discover -s tests          # offline tests
python collector/collect.py --dry-run --sources trmf   # show the plan, no requests
python collector/collect.py                   # rebuild the data file (uses $LODGING_SOURCES)
cd docs && python -m http.server 8000         # preview at http://localhost:8000
```

## GitHub Pages setup

1. Settings → Pages → Deploy from a branch → `main`, folder `/docs`.
2. Custom domain `lodging.labs.trlibrary.com` (already in `docs/CNAME`; the wildcard DNS record covers it).
3. Settings → Actions → General → Workflow permissions → Read and write.
