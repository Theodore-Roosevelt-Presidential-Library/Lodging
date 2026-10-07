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
| Offline tests | 54 pass; they use canned responses shaped like each service's documentation |
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

The free tier is 100 searches, once (about 45 used by Oct 7, in testing and photo lookups). Daily use is about 140 searches (about 4,200 a month), so running `google_hotels` daily needs the Developer plan, $40 a month for 10,000 searches, the smallest paid tier. Without it, leave `google_hotels` out of `LODGING_SOURCES`: the 16 Dickinson hotels, AmericInn Medora and Trapper's Inn then appear under "check directly," and hotel photos from Google are not refreshed.

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

Not planned: recreation.gov and ND Parks (both disallow or block automated checks); Campspot (needs a headless browser); phone-only properties.

## Known limits

- Hotel stays are assembled from one-night checks, so minimum-stay rules and room changes between nights are not reflected. Cabins and rentals are counted only when the same unit is open every night, but minimum-stay rules are still not applied. The booking site has the final word.
- Availability is checked for two adults.
- Nights more than ten days stale are treated as unknown and shown under "check directly."
- The Vrbo dated search link follows Vrbo's usual URL pattern but has not been click-tested.
