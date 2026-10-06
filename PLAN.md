# Lodging Finder: plan and status

Last updated October 5, 2026.

## Why build this

The Medora Foundation operates 460 of Medora's 546 hotel rooms and books them only through medora.com. Off-the-shelf lodging widgets (Stay22, Booking.com, Expedia) see about 15% of Medora's hotel rooms, so they cannot answer "is there a room near the Library on my dates." See `claude/lodging_inventory_medora_region.md` in the TRPL project for the full inventory.

## Decisions (Oct 5, 2026)

- Build in-house; serve from GitHub Pages; refresh with GitHub Actions.
- Version one serves both visitors (embeddable widget) and staff (monitor).
- Version one shows live availability by date, not just a directory.
- Availability only. Rates are not collected, stored or shown.
- Add Google Hotels, Guesty and Apify sources now; keys go in `.env` locally and repository secrets on GitHub.

## Status

| Piece | Status |
|---|---|
| Property list (58 properties, 52 public) | Done |
| Widget | Done; tested in a headless browser at desktop and phone widths |
| Monitor | Done |
| Collector: Medora Foundation (`trmf`) | Done; endpoint confirmed with a handful of live requests; switched off |
| Collector: Google Hotels (`google_hotels`) | Built from SearchApi's documentation; needs a key and a `--check` |
| Collector: Airbnb and Vrbo (`airbnb`, `vrbo`) | Built from the Apify actors' documentation; needs a token and a `--check` |
| Vacation Medora cabins | Read from their Airbnb calendars (see below); the `guesty` collector is kept but unused |
| Offline tests | 24 pass; they use canned responses shaped like each service's documentation |
| Daily workflow | Written; not yet run on GitHub |
| Pages site | Not yet enabled |

## To validate once keys are in `.env`

Run `python collector/collect.py --check` and look for:

1. **google_hotels**: every tracked hotel should say "matched". "NOT FOUND" means Google lists it under a different name; fix `live.match` in `data/properties.json`.
2. **airbnb**: "parsed calendars: 1" with about 30 days.
3. **vrbo**: a few items with titles from the Medora area. The actor takes the map area as `bbox:south,west,north,east`; if it returns nothing, that input format is the first thing to check.

## Open decision: the Medora Foundation source

The Foundation's booking engine (bookings.medora.com, run by P3 Hotels) exposes the same JSON price lookup its own pages use:

`/api/dynamic-pricing/company/134/hotel/{id}/arrival/{date}/nights/1/adults/2/children/0`

It returns availability and how many of the first-listed room type remain (along with rates, which the collector discards). No key is needed.

The site's `robots.txt` disallows automated access to everything except `/search-rates`, `/offer` and `/offers`. A scheduled collector would go against that file. The source therefore ships switched off. Options:

1. **Ask the Foundation** to approve the daily check (or provide a feed). With their agreement the robots file is moot, and they gain a booking channel on trlibrary.com.
2. Turn it on without asking. Technically works; carries relationship risk with the Library's closest lodging partner.
3. Leave it off; the widget still lists the Foundation's properties with dated links to their booking site.

To turn it on: add `trmf` to `LODGING_SOURCES`, then run the workflow once with "full" ticked.

## Property list choices to review

Hidden from the public widget (`"public": false`) pending a look: The Roosevelt Hotel (Wibaux), Buckboard Inn (Beach; may now be Patriot Inn), Badlands Inn & Suites, Best Budget Inn and NODAK Motel (Dickinson), Beaver Valley Haven (Wibaux). Reasons: weak reviews, an unconfirmed name, or no working website.

Not listed at all: properties the inventory could not confirm as operating, long-term RV lots, workforce housing, and anything beyond about 45 miles.

## Source costs and cautions

| Source | Daily volume | Rough monthly cost | Caution |
|---|---|---|---|
| Google Hotels (SearchApi) | About 100 to 150 searches | Fits the $40 plan (10,000 searches); the 100-search free trial covers `--check` and a `--limit` test only | "No rate" is treated as unknown, not full |
| Airbnb (Apify, `cirkit/airbnb-availability-scraper`) | One run, 23 calendars | Under $3 | Community-maintained actor with a small user base; scraping is against Airbnb's terms. Only a count is shown, never listing content |
| Vrbo (Apify, `memo23/vrbo-scraper`) | One run, up to 60 listings with calendars | About $5 to $10 | Same cautions as Airbnb |

The Airbnb list is 15 listing IDs from the October inventory, kept in `data/properties.json`. It is not rediscovered automatically; add IDs by hand as listings appear.

### Vacation Medora cabins (Boots and The Crossings)

Guesty credentials are not obtainable, so these cabins are read from their Airbnb calendars, which Guesty keeps in step with the operator's own booking site. Coverage is partial: 2 of 5 Boots units and 6 of 9 Crossings units are on Airbnb. The two Boots cabins that are only on Vrbo are counted under "Vrbo rentals around Medora."

Reading the operator's own booking site (vacationmedora.guestybookings.com) was tried and dropped. Its robots.txt allows crawling, but the data behind it comes from Guesty's servers, which return empty responses to anything that is not a full browser. Getting past that would mean imitating a browser to defeat Guesty's filtering, which this project does not do.

Not planned: recreation.gov and ND Parks (both disallow or block automated checks); Campspot (needs a headless browser); phone-only properties.

## Known limits

- Hotel stays are assembled from one-night checks, so minimum-stay rules and room changes between nights are not reflected. Cabins and rentals are counted only when the same unit is open every night, but minimum-stay rules are still not applied. The booking site has the final word.
- Availability is checked for two adults.
- Nights more than ten days stale are treated as unknown and shown under "check directly."
- The Vrbo dated search link follows Vrbo's usual URL pattern but has not been click-tested.
