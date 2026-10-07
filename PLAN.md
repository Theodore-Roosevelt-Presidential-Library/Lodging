# Lodging Finder: plan and status

Last updated October 7, 2026.

## Why build this

The Medora Foundation operates 460 of Medora's 546 hotel rooms and books them only through medora.com. Off-the-shelf lodging widgets (Stay22, Booking.com, Expedia) see about 15% of Medora's hotel rooms, so they cannot answer "is there a room near the Library on my dates." See `claude/lodging_inventory_medora_region.md` in the TRPL project for the full inventory.

## Decisions (Oct 5, 2026)

- Build in-house; serve from GitHub Pages; refresh with GitHub Actions.
- Version one serves both visitors (embeddable widget) and staff (monitor).
- Version one shows live availability by date, not just a directory.
- Availability only. Rates are not collected, stored or shown.
- Add Google Hotels, Guesty and Apify sources now; keys go in `.env` locally and repository secrets on GitHub.
- `LODGING_SOURCES` is `google_hotels,trmf,airbnb,vrbo`.
- Oct 6: photos come from each property's own website (link-preview image), then Google Hotels; shown from those addresses, never copied.
- Oct 6: the trolley is mentioned only for stays inside its season (June through September).
- Oct 6: compact layout. One button per property, phone number as a text link, one-line rows for places to check directly.
- Oct 7: the one-line rows were too little. Every place is now a card, in four tabs (Medora, Vacation rentals, Nearby towns, Dickinson) on a bar that stays pinned while scrolling.
- Oct 7: each Airbnb and Vrbo listing is shown as its own card with its photo, instead of one grouped count.
- Oct 7: every property should have a photo; brand fonts are loaded from trlibrary.com.
- Oct 7: the monitor uses the full window with no inner scroll box, and every cell opens the finder on that night and property. The finder reads `checkin`, `nights`, `tab`, `type` and `place` from the page address.

## Status

| Piece | Status |
|---|---|
| Property list (58 properties, 52 public) | Done |
| Widget | Done; tested in a headless browser at desktop and phone widths |
| Monitor | Done |
| Collector: Medora Foundation (`trmf`) | Tested live Oct 5 (three nights) |
| Collector: Google Hotels (`google_hotels`) | Tested live Oct 5; 18 of 18 hotels matched |
| Collector: Airbnb and Vrbo (`airbnb`, `vrbo`) | Tested live Oct 5; full 330-night calendars |
| Vacation Medora cabins | Read from their Airbnb calendars (see below); the `guesty` collector is kept but unused |
| Photos (`collector/photos.py`) | Done; see "Photos" below |
| Collector: recreation.gov campgrounds (`recgov`) | Tested live Oct 7; three campgrounds, through Apify |
| Collector: ND state parks (`ndparks`) | Tested live Oct 7; Rough Rider State Park |
| Offline tests | 69 pass; they use canned responses shaped like each service's documentation |
| Daily workflow | Written; `.github/workflows/collect.yml` is not in the repository yet, so nothing refreshes on its own |
| Pages site | Live at lodging.labs.trlibrary.com |

## To validate once keys are in `.env`

Run `python collector/collect.py --check` and look for:

1. **google_hotels**: every tracked hotel should say "matched". "NOT FOUND" means Google lists it under a different name; fix `live.match` in `data/properties.json`.
2. **airbnb**: "parsed calendars: 1" with about 30 days.
3. **vrbo**: a few items with titles from the Medora area. The actor takes the map area as `bbox:south,west,north,east`; if it returns nothing, that input format is the first thing to check.

## Photos

All 50 public properties with a card of their own have a photo (Oct 7), plus all 15 Airbnb and 12 Vrbo listings. Where they come from: 2 set by hand, 7 from the property's own website, 32 from Google Hotels, 8 from Google Maps, 1 from an Airbnb listing, and the listing photos from Airbnb and Vrbo themselves. The README lists the order tried.

Why so many come from Google: most chain-hotel sites refuse automated requests, several small properties have no website, and some sites publish only a logo or one image shared across every page (medora.com gives Hotel 1883 the Rough Riders Hotel picture, so that one is ignored for Hotel 1883 and set by hand for Rough Riders).

Cautions:

- Google's photos can be guest-contributed. They carry more rights risk than a property's own image. `python collector/photos.py --no-google` leaves them out.
- Airbnb and Vrbo listing photos and titles belong to the hosts, and both sites' terms forbid scraping. Showing them one by one is more exposed than showing a count. Remove `"list_units": true` to go back to the count.
- Photos were checked by eye on Oct 7. Two automatic picks were wrong and are now ruled out: an app advertisement on a National Park Service page and a restaurant interior for a campground.

Best long-term fix: Library-shot or partner-supplied photos set with `"photo"` in `data/properties.json`. Those override everything else.

## New listings

- Vrbo: found automatically. Every run searches the map area in `live.start`, so a new listing inside it appears on its own, subject to the rating floor.
- Airbnb: not found automatically. The 15 listing IDs are kept by hand in `data/properties.json`.
- Hotels, cabins and campgrounds: kept by hand.

Option not built: a weekly Airbnb search that proposes new listing IDs for review rather than publishing them unseen.

## SearchApi plan

Upgraded Oct 7 to the Developer plan: $40 a month, 10,000 searches. The Google Hotels window was widened to use it: the next 30 nights daily and the rest weekly, out to 240 nights, about 7,200 searches a month.

Google Hotels shows rates for AmericInn Medora, Trapper's Inn and the Dickinson hotels only. The other Medora-area inns, ranches and campgrounds are listed there without rates, so the paid plan cannot make them live.

## Getting more live answers (Oct 7)

What decides whether a card says "Open", "Full" or "Check dates directly":

1. Whether the daily refresh runs. Until `.github/workflows/collect.yml` is in the repository, the only data is from hand runs. On Oct 7 the whole horizon was filled by hand from Matt's computer. Anything older than ten days (sixteen for nights more than two months out) is shown as "check directly".
2. Whether the property has a source. Of 50 property cards, 31 can now show a live answer: 5 Medora Foundation, 18 through Google Hotels, 3 on recreation.gov, 1 state park, 2 Vacation Medora cabin groups, and 2 (Dakota Place Lodge, King's Guest Ranch) through their own Airbnb and Vrbo listings. All 27 rental listings are live.
3. The other 19: three campgrounds on Campspot (decided against); two Forest Service campgrounds that are first come, first served (and now say so); the rest take bookings by phone or through their own website.

## Rule for new sources (Matt, Oct 7)

1. Wherever a property has a booking system, look for real-time availability before settling for "check dates directly".
2. Before reading a site directly, check whether a scraper for it already exists on Apify, so the requests do not come from the Library.

How each source stands against that rule:

| Source | Apify scraper? | What is used |
|---|---|---|
| recreation.gov | Three exist. `hikemetrics/recreation-gov-permit-tracker` charges $0.0025 per campground-month, about 6 cents a run. (`jungle_synthesizer/...` charges per site per day, about $8 a run, so it was not used.) | The Apify scraper. `RECGOV_VIA=direct` switches to direct requests. |
| Airbnb, Vrbo | Yes | Apify scrapers (since Oct 5) |
| ND state parks | None | Direct. The site has no robots.txt; about 20 requests a run. |
| Campspot | None | Not built, by decision. See below. |
| Medora Foundation | None | Direct, labeled as the Library (confirmed by Matt, Oct 7). Still worth telling the Foundation; a visible partner is a better look than anonymous traffic. |

## recreation.gov

Cottonwood Campground (251160), Roundup Group Horse Camp (251161) and Buffalo Gap Campground (246796). recreation.gov's official data service (RIDB) does not include availability, so every route reads the month-by-month lookup the site's own pages use, which sits under `/api` (disallowed by the site's `robots.txt`). By default that is done by the Apify scraper. The scraper counts "Open" nights (shown but not yet on sale) as bookable; the collector does not, and treats only "Available" as open.

Nights more than about six months out are not released for booking and show as "check directly". Buffalo Gap shows nothing until its season is released.

## ND state parks

Rough Rider State Park is place 63 in the state reservation system (reservendparks.com), with three loops: 113 Rustler, 133 Rancher, 134 Wrangler. Booking opens about six months ahead. No other state park is within reach of Medora.

## Campspot (decided against, Oct 7)

Boots Campground (`bootsbarmedora`, park 165), The Crossings Campground (`thecrossingscampground`) and Whispering Pines (`whisperingpinescampground`) all book through Campspot. Its robots.txt allows the booking pages, but its servers answer 403 to anything that is not a real browser, including this collector under its own name. Disguising the collector as a browser is out. The route that fits the Apify rule: Apify's general-purpose browser scraper (`apify/playwright-scraper`) with a short script that opens each booking page and reads the availability the page itself loads. Matt decided against it on Oct 7: the Library does not want to maintain a custom scraper. These three campgrounds stay "check dates directly", with links that open Campspot on the chosen dates.

## Ferris Inn, Wooly Boys Inn, Hyde House

These share the Rough Riders booking engine (hotel 62700, named "Rough Riders Hotel, Ferris Inn, Wooly Boys Inn, & Hyde House"). For every date sampled on Oct 7 (October, November, June and July) the lookup returned only Rough Riders room types (codes starting `RR`). So the "Rough Riders Hotel and historic inns" card currently reflects Rough Riders rooms only. Either the inn rooms are not on sale yet for next season or the quick lookup does not list them. Re-check in spring; if inn room codes appear, each inn can get its own card.

## The Medora Foundation source

The Foundation's booking engine (bookings.medora.com, run by P3 Hotels) exposes the same JSON price lookup its own pages use:

`/api/dynamic-pricing/company/134/hotel/{id}/arrival/{date}/nights/1/adults/2/children/0`

It returns availability and how many of the first-listed room type remain (along with rates, which the collector discards). No key is needed.

The site's `robots.txt` disallows automated access to everything except `/search-rates`, `/offer` and `/offers`. A scheduled collector goes against that file. `trmf` is included in `LODGING_SOURCES` by the CCMO's decision. Still worth doing: ask the Foundation to approve the daily check (or provide a feed). With their agreement the robots file is moot, and they gain a booking channel on trlibrary.com. Until then this carries relationship risk with the Library's closest lodging partner.

The first full run makes about 1,650 requests, one a second.

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

Not planned: phone-only properties.

## Known limits

- Hotel stays are assembled from one-night checks, so minimum-stay rules and room changes between nights are not reflected. Cabins and rentals are counted only when the same unit is open every night, but minimum-stay rules are still not applied. The booking site has the final word.
- Availability is checked for two adults.
- Nights more than ten days stale are treated as unknown and shown under "check directly."
- The Vrbo dated search link follows Vrbo's usual URL pattern but has not been click-tested.
