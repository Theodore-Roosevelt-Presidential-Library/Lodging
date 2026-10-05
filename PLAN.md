# Lodging Finder: plan and status

Last updated October 5, 2026.

## Why build this

The Medora Foundation operates 460 of Medora's 546 hotel rooms and books them only through medora.com. Off-the-shelf lodging widgets (Stay22, Booking.com, Expedia) see about 15% of Medora's hotel rooms, so they cannot answer "is there a room near the Library on my dates." See `claude/lodging_inventory_medora_region.md` in the TRPL project for the full inventory.

## Decisions (Oct 5, 2026)

- Build in-house; serve from GitHub Pages; refresh with GitHub Actions.
- Version one serves both visitors (embeddable widget) and staff (monitor).
- Version one shows live availability by date, not just a directory.
- Availability only. Rates are not collected, stored or shown.

## Status

| Piece | Status |
|---|---|
| Property list (58 properties, 52 public) | Done |
| Widget | Done; tested in a headless browser at desktop and phone widths |
| Monitor | Done |
| Collector, Medora Foundation source | Done; offline tests pass; endpoint confirmed with a handful of live requests |
| Daily workflow | Written; not yet run on GitHub |
| Pages site | Not yet enabled |

## Open decision: the Medora Foundation source

The Foundation's booking engine (bookings.medora.com, run by P3 Hotels) exposes the same JSON price lookup its own pages use:

`/api/dynamic-pricing/company/134/hotel/{id}/arrival/{date}/nights/1/adults/2/children/0`

It returns availability and how many of the first-listed room type remain (along with rates, which the collector discards). No key is needed.

The site's `robots.txt` disallows automated access to everything except `/search-rates`, `/offer` and `/offers`. A scheduled collector would go against that file. The source therefore ships switched off. Options:

1. **Ask the Foundation** to approve the daily check (or provide a feed). With their agreement the robots file is moot, and they gain a booking channel on trlibrary.com.
2. Turn it on without asking. Technically works; carries relationship risk with the Library's closest lodging partner.
3. Leave it off; the widget still lists the Foundation's properties with dated links to their booking site.

To turn it on: set the repository variable `LODGING_SOURCES` to `trmf`, then run the workflow once with "full" ticked.

## Property list choices to review

Hidden from the public widget (`"public": false`) pending a look: The Roosevelt Hotel (Wibaux), Buckboard Inn (Beach; may now be Patriot Inn), Badlands Inn & Suites, Best Budget Inn and NODAK Motel (Dickinson), Beaver Valley Haven (Wibaux). Reasons: weak reviews, an unconfirmed name, or no working website.

Not listed at all: properties the inventory could not confirm as operating, long-term RV lots, workforce housing, and anything beyond about 45 miles.

## Next sources

| Source | Covers | Method | Needs | Rough cost |
|---|---|---|---|---|
| Google Hotels through SearchApi or SerpApi | 20 Dickinson hotels, AmericInn Medora, Trapper's Inn | Licensed API, one bounding-box search per date | API key as a repository secret | $40 to $150 a month at daily volume; free tiers cover a pilot |
| Vacation Medora (Guesty) | 14 cabins and houses in Medora and Belfield | Guesty Booking Engine API | Credentials from the owner | None |
| Airbnb and Vrbo | About 25 to 40 rentals around Medora | Apify actors: weekly discovery, daily calendars | Apify token; counsel check before showing listings publicly | About $5 to $15 a month |
| Campspot | Boots, The Crossings, Whispering Pines RV sites | Dated search page (needs a headless browser) | Nothing | None |

Not planned: recreation.gov and ND Parks (both disallow or block automated checks); phone-only properties.

## Known limits

- Stays are assembled from one-night checks, so minimum-stay rules and room changes between nights are not reflected. The Book button opens the exact dates on the booking site, which has the final word.
- Availability is checked for two adults.
- Nights more than ten days stale are treated as unknown and shown under "check directly."
- The Vrbo dated search link follows Vrbo's usual URL pattern but has not been click-tested.
