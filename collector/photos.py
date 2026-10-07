#!/usr/bin/env python3
"""Find a photo for each property and write docs/data/photos.json.

For every public property with a website, this reads the page's own link-preview
image (the og:image or twitter:image tag a site publishes so that links to it can
be shown with a picture) and records its address. The widget then shows that image
straight from the property's server. Nothing is downloaded into this repository.

Airbnb listings that are shown one by one (a property with "list_units": true) get their
name, one-line summary and photo the same way, from each listing page's link preview.

Logos, placeholders and images that several properties share are passed over. A property
with nothing usable in its link preview is tried in this order:

    1. the first large landscape image in the body of its own page
    2. the photo Google Hotels shows for it, noted by collect.py (docs/data/photo_hints.json)
    3. for cabins read from Airbnb calendars, the photo of their first Airbnb listing
    4. the photo Google Maps shows for the search named in "photo_search" (one SearchApi
       search, repeated only if that photo stops loading)

    python collector/photos.py                 # refresh entries older than 7 days
    python collector/photos.py --all           # re-check every property
    python collector/photos.py --only hotel-1883,amble-inn
    python collector/photos.py --no-google     # link-preview images only

Per-property overrides in data/properties.json:
    "photo": "https://..."     use this image instead (for example one of the Library's own)
    "photo": false             never show a photo for this property
    "photo_page": "https://..." read the preview image from this page instead of "url"
    "photo_match": "hotel 1883" take the Google Hotels photo of the result whose name contains this
    "photo_search": "Red Trail Campground, Medora, ND"   look the place up on Google Maps if all else fails

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROPERTIES = ROOT / "data" / "properties.json"
OUT = ROOT / "docs" / "data" / "photos.json"
HINTS = ROOT / "docs" / "data" / "photo_hints.json"   # written by collect.py from Google Hotels results

USER_AGENT = "Mozilla/5.0 (compatible; TRPL-Lodging-Finder/1.0; +https://www.trlibrary.com)"
TIMEOUT_SECONDS = 15
DELAY_SECONDS = 1.0
MAX_AGE_DAYS = 7
KEEP_FAILED_DAYS = 180     # keep a previously found photo this long if the site stops answering
MIN_WIDTH = 500            # smaller images are usually logos, icons or thin banners
MIN_PAGE_WIDTH = 600       # an image taken from the page body has to be larger still
MIN_RATIO, MAX_RATIO = 0.6, 2.6   # width / height; outside this it is usually a banner or a logo
PAGE_BYTES = 700_000
IMAGE_BYTES = 262_144
GENERIC = re.compile(r"placeholder|logo|default|social[-_ ]?shar|favicon|sprite|/icons?/", re.I)
# On-page images that are furniture, not a picture of the place.
FURNITURE = re.compile(r"icon|menu|badge|avatar|button|arrow|loader|spinner|pixel|award|tripadvisor|facebook|instagram|"
                       r"twitter|youtube|pinterest|banner-ad|captcha|map[-_.]|staticmap|gravatar|emoji|flag|seal|usda|"
                       r"shield|signature|rating|stars?[-_.]|payment|visa|mastercard|qr[-_.]|app[-_.]|[-_]app|promo|"
                       r"screenshot|iphone|android|download", re.I)
MAX_PAGE_IMAGES = 12       # how many on-page images to try before giving up
OWN_SITE = ("preview", "page")   # photos read from the property's own website
MIN_PAGE_RATIO = 1.2       # and wider than tall, which rules out most portraits and posters
SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"
MAP_RETRY_DAYS = 30        # how long to wait before searching Google Maps again for a place it had no photo for
MAX_MAP_SEARCHES = 15      # most Google Maps searches in one run


class MetaImages(HTMLParser):
    """Collects candidate preview images from <meta> tags, best first."""

    ORDER = ["og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"]

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        if key in self.ORDER and a.get("content", "").strip() and key not in self.found:
            self.found[key] = a["content"].strip()

    def candidates(self) -> list[str]:
        seen, out = set(), []
        for key in self.ORDER:
            url = self.found.get(key)
            if url and url not in seen:
                seen.add(url)
                out.append(url)
        return out


class MetaTags(HTMLParser):
    """Every <meta> property or name on a page, first value wins."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        if key and a.get("content", "").strip():
            self.tags.setdefault(key, a["content"].strip())


def tidy(text, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,.-") + "…"


def parse_listing(tags: dict[str, str], floor: float = 0.7) -> dict | None:
    """Name, one-line summary and photo from an Airbnb listing page's link-preview tags.

    The guest rating in the preview is used only to leave out poorly rated listings; it is not kept.
    """
    title = tags.get("twitter:title", "")
    if title.endswith(" - Airbnb") and title.count(" - ") >= 2:
        name = title.rsplit(" - ", 2)[0]
    else:
        name = tags.get("og:description", "")
    name = tidy(name)
    if not name:
        return None
    out, facts = {"name": name}, []
    for part in (x.strip() for x in tags.get("og:title", "").split("·")):
        if part.startswith("★"):
            try:
                if float(part[1:].strip()) / 5 < floor:
                    out["hidden"] = True
            except ValueError:
                pass
        elif part:
            facts.append(part)
    if facts:
        out["summary"] = tidy(" · ".join(facts), 90)
    src = tags.get("og:image", "")
    if src.startswith("http://"):
        src = "https://" + src[len("http://"):]
    if src.startswith("https://"):
        out["src"] = src
    return out


def find_listing(page_url: str, floor: float = 0.7) -> dict | None:
    html, ctype, _ = fetch(page_url, PAGE_BYTES, "text/html,application/xhtml+xml")
    if "html" not in ctype.lower() and not html.lstrip().startswith(b"<"):
        return None
    parser = MetaTags()
    parser.feed(html.decode("utf-8", "replace"))
    return parse_listing(parser.tags, floor)


class PageImages(HTMLParser):
    """Images in the body of a page, in page order: <img>, lazy-loading attributes and the largest srcset entry."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []

    @staticmethod
    def largest(srcset: str) -> str:
        best, best_w = "", -1.0
        for part in srcset.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            try:
                width = float(bits[1][:-1]) if len(bits) > 1 and bits[1][-1] in "wx" else 0.0
            except ValueError:
                width = 0.0
            if width > best_w:
                best, best_w = bits[0], width
        return best

    def handle_starttag(self, tag, attrs):
        if tag not in ("img", "source"):
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        picks = [a.get(k, "") for k in ("data-src", "data-lazy-src", "data-original", "data-image", "src")]
        for key in ("data-srcset", "srcset"):
            if a.get(key):
                picks.insert(0, self.largest(a[key]))
        for url in picks:
            url = url.strip()
            if url and not url.startswith("data:") and url not in self.found:
                self.found.append(url)
                break


def fetch(url: str, limit: int, accept: str) -> tuple[bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return resp.read(limit), resp.headers.get("Content-Type", ""), resp.geturl()


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from the first bytes of a PNG, GIF, WebP or JPEG; None if unknown."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
        if kind == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return (w, h)
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def usable(size: tuple[int, int] | None) -> bool:
    if size is None:
        return False
    w, h = size
    return w >= MIN_WIDTH and h > 0 and MIN_RATIO <= w / h <= MAX_RATIO


def find_photo(page_url: str) -> dict | None:
    """The first preview image on the page that loads over https and looks like a photo."""
    html, ctype, final_url = fetch(page_url, PAGE_BYTES, "text/html,application/xhtml+xml")
    if "html" not in ctype.lower() and not html.lstrip().startswith(b"<"):
        return None
    parser = MetaImages()
    parser.feed(html.decode("utf-8", "replace"))
    for raw in parser.candidates():
        src = urllib.parse.urljoin(final_url, raw)
        if src.startswith("http://"):
            src = "https://" + src[len("http://"):]   # the widget is served over https
        if not src.startswith("https://") or looks_generic(src):
            continue
        hit = check_image(src)
        if hit:
            return hit
    # No usable preview image: take the first photo-sized image in the page itself.
    body = PageImages()
    body.feed(html.decode("utf-8", "replace"))
    tried = 0
    for raw in body.found:
        src = urllib.parse.urljoin(final_url, raw)
        if src.startswith("http://"):
            src = "https://" + src[len("http://"):]
        path = urllib.parse.urlsplit(src).path
        if (not src.startswith("https://") or looks_generic(src) or FURNITURE.search(path)
                or path.lower().endswith((".svg", ".gif"))):
            continue
        tried += 1
        if tried > MAX_PAGE_IMAGES:
            break
        hit = check_image(src)
        if hit and hit["w"] >= MIN_PAGE_WIDTH and hit["w"] / hit["h"] >= MIN_PAGE_RATIO:
            return {**hit, "via": "page"}
    return None


def looks_generic(src: str) -> bool:
    """Site-wide stand-ins (logos, placeholders, share cards) say nothing about the property."""
    return bool(GENERIC.search(urllib.parse.urlsplit(src).path))


def check_image(src: str) -> dict | None:
    """Fetch the start of an image and return its address and size if it looks like a photo."""
    try:
        data, itype, _ = fetch(src, IMAGE_BYTES, "image/*")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not itype.lower().startswith("image/") or "svg" in itype.lower():
        return None
    size = image_size(data)
    return {"src": src, "w": size[0], "h": size[1]} if usable(size) else None


def google_size(src: str) -> str:
    """Google serves its photos at whatever size the address asks for; ask for a card-sized one."""
    if "googleusercontent.com/" in src:
        return re.sub(r"=[a-z0-9-]+$", "", src) + "=w640-h360-n-k-no"
    return src


def map_photo(query: str, key: str) -> dict | None:
    """The photo Google Maps shows for a place. One SearchApi search; the key travels in a header."""
    params = urllib.parse.urlencode({"engine": "google_maps", "q": query, "hl": "en", "gl": "us"})
    req = urllib.request.Request(SEARCHAPI_ENDPOINT + "?" + params,
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    first = (payload.get("local_results") or [payload.get("place_result") or {}])[0] or {}
    src = first.get("thumbnail") or ""
    if not src.startswith("https://"):
        return None
    return {"src": google_size(src), "name": tidy(first.get("title"))}


def run(args, today: dt.date | None = None, finder=find_photo, checker=check_image, sleep=time.sleep,
        lister=find_listing, mapper=map_photo, env=None) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    stamp = today.isoformat()
    props = [p for p in json.loads(PROPERTIES.read_text(encoding="utf-8"))["properties"] if p.get("public", True)]
    try:
        saved = json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    previous, old_misses = saved.get("photos", {}), saved.get("misses", {})
    old_listings, old_searched = saved.get("listings", {}), saved.get("searched", {})
    env = os.environ if env is None else env
    try:
        hints = {} if args.no_google else json.loads(HINTS.read_text(encoding="utf-8")).get("hints", {})
    except (FileNotFoundError, json.JSONDecodeError):
        hints = {}
    only = {x.strip() for x in (args.only or "").split(",") if x.strip()}
    photos, misses = {}, {}
    counts = {"manual": 0, "found": 0, "google": 0, "kept": 0, "none": 0, "skipped": 0, "listings": 0, "searches": 0}
    by_id = {p["id"]: p for p in props}

    def age_of(entry) -> int | None:
        when = entry.get("checked") if isinstance(entry, dict) else entry
        return (today - dt.date.fromisoformat(when)).days if when else None

    wanted = []   # properties that take an automatic photo, in list order
    for prop in props:
        pid, old, manual = prop["id"], previous.get(prop["id"]), prop.get("photo")
        if manual is False:
            counts["skipped"] += 1
            continue
        if isinstance(manual, str) and manual:
            same = old and old.get("from") == "manual" and old.get("src") == manual
            photos[pid] = {"src": manual, "from": "manual", "checked": old["checked"] if same else stamp}
            if prop.get("photo_credit"):
                photos[pid]["credit"] = prop["photo_credit"]
            counts["manual"] += 1
            continue
        page = prop.get("photo_page") or prop.get("url")
        if prop.get("type") == "rentals" or not (page or pid in hints or prop.get("photo_search")
                                                 or (prop.get("live") or {}).get("source") == "airbnb"):
            counts["skipped"] += 1
            continue
        wanted.append(pid)
        if old and old.get("from") not in OWN_SITE:
            old = None            # a Google photo is only ever a stand-in; look at the site again when due
        age = age_of(old)
        fresh = old and old.get("page") == page and age is not None and age < args.max_age_days
        missed = age_of(old_misses.get(pid))
        recent_miss = not old and missed is not None and missed < args.max_age_days
        if not page or (only and pid not in only) or ((fresh or recent_miss) and not args.all and not only):
            if old:
                photos[pid] = old
            elif pid in old_misses:
                misses[pid] = old_misses[pid]
            continue
        try:
            hit, error = finder(page), None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            hit, error = None, f"{type(exc).__name__}: {exc}"
        if hit and looks_generic(hit["src"]):
            hit = None
        if hit:
            hit = dict(hit)
            source = "page" if hit.pop("via", None) == "page" else "preview"
            photos[pid] = {**hit, "page": page, "from": source, "checked": stamp}
            print(f"  {pid}: {hit['w']}x{hit['h']}")
        elif error and old and age is not None and age < KEEP_FAILED_DAYS:
            photos[pid] = old   # the site did not answer; keep what we had, and retry next time
            print(f"  {pid}: kept previous ({error})", file=sys.stderr)
        else:
            misses[pid] = stamp
            print(f"  {pid}: no usable preview image" + (f" ({error})" if error else ""))
        sleep(DELAY_SECONDS)

    # One image offered by several properties is a site-wide default, not a picture of any of them.
    uses: dict[str, list[str]] = {}
    # A photo set by hand stays; the same image turning up on another property's page is dropped there.
    for pid, entry in photos.items():
        uses.setdefault(entry["src"], []).append(pid)
    for src, pids in uses.items():
        if len(pids) > 1:
            found = [pid for pid in pids if photos[pid].get("from") in OWN_SITE]
            for pid in found:
                misses[pid] = photos.pop(pid)["checked"]
            if found:
                print(f"  shared image dropped for {', '.join(found)}")

    # Fallback: the photo Google Hotels shows for the property, noted by collect.py.
    for pid in wanted:
        hint = hints.get(pid)
        if pid in photos or not hint:
            continue
        old = previous.get(pid) or {}
        age = age_of(old)
        if old.get("from") == "google" and age is not None and age < args.max_age_days and not args.all:
            photos[pid] = old
            continue
        hit = checker(hint["src"])
        if hit:
            photos[pid] = {**hit, "from": "google", "checked": stamp}
            print(f"  {pid}: Google Hotels photo {hit['w']}x{hit['h']}")

    # Fallback: cabins read from Airbnb calendars can borrow the photo of their first Airbnb listing.
    for pid in wanted:
        live = by_id[pid].get("live") or {}
        ids = [str(x) for x in live.get("listings", [])]
        if pid in photos or live.get("source") != "airbnb" or not ids:
            continue
        old = previous.get(pid) or {}
        age = age_of(old)
        if old.get("from") == "listing" and age is not None and age < args.max_age_days and not args.all:
            photos[pid] = old
            continue
        try:
            hit = lister(f"https://www.airbnb.com/rooms/{ids[0]}", 0.0)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            hit = None
        if hit and hit.get("src"):
            photos[pid] = {"src": hit["src"], "from": "listing", "checked": stamp}
            print(f"  {pid}: photo from its Airbnb listing")
        elif old.get("from") == "listing" and age is not None and age < KEEP_FAILED_DAYS:
            photos[pid] = old
        sleep(DELAY_SECONDS)

    # Last resort: the photo Google Maps shows, for properties that name a search in "photo_search".
    # A found photo is kept for as long as it still loads, so this costs a search only when one is needed.
    key, searched = (None if args.no_google else env.get("SEARCHAPI_KEY")), {}
    for pid in wanted:
        query = by_id[pid].get("photo_search")
        if pid in photos or not query:
            continue
        old = previous.get(pid) or {}
        age = age_of(old)
        if old.get("from") == "maps":
            if (age is not None and age < args.max_age_days and not args.all) or checker(old["src"]):
                photos[pid] = old if age is not None and age < args.max_age_days else {**old, "checked": stamp}
                continue
        tried = age_of(old_searched.get(pid))
        if tried is not None and tried < MAP_RETRY_DAYS and not args.all:
            searched[pid] = old_searched[pid]
            continue
        if not key or counts["searches"] >= MAX_MAP_SEARCHES:
            continue
        counts["searches"] += 1
        try:
            found = mapper(query, key)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  {pid}: Google Maps search failed ({type(exc).__name__})", file=sys.stderr)
            continue
        searched[pid] = stamp
        hit = checker(found["src"]) if found else None
        if hit:
            photos[pid] = {**hit, "from": "maps", "place": found.get("name", ""), "checked": stamp}
            print(f"  {pid}: Google Maps photo of \"{found.get('name', '')}\"")
        else:
            print(f"  {pid}: Google Maps had no photo")
        sleep(DELAY_SECONDS)

    for entry in photos.values():
        if entry.get("from") == "manual":
            continue
        if entry.get("checked") != stamp:
            counts["kept"] += 1
        elif entry.get("from") in OWN_SITE:
            counts["found"] += 1
        elif entry.get("from") in ("google", "maps", "listing"):
            counts["google"] += 1
    counts["none"] = len([pid for pid in wanted if pid not in photos])

    # Airbnb listings shown one by one: name, summary and photo from each listing page's link preview.
    listings = {}
    for prop in props:
        live = prop.get("live") or {}
        if not prop.get("list_units") or live.get("source") != "airbnb":
            continue
        floor, hide = float(live.get("min_rating", 0.7)), {str(x) for x in live.get("hide", [])}
        for lid in (str(x) for x in live.get("listings", [])):
            if lid in hide:
                continue
            key, old = f"airbnb:{lid}", old_listings.get(f"airbnb:{lid}")
            age = age_of(old)
            fresh = old and age is not None and age < args.max_age_days
            if (only and prop["id"] not in only) or (fresh and not args.all and not only):
                if old:
                    listings[key] = old
                continue
            try:
                hit, error = lister(f"https://www.airbnb.com/rooms/{lid}", floor), None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                hit, error = None, f"{type(exc).__name__}: {exc}"
            if hit:
                listings[key] = {**hit, "checked": stamp}
                print(f"  {key}: {hit['name']}" + (" (left out: low rating)" if hit.get("hidden") else ""))
            elif old and old.get("name") and age is not None and age < KEEP_FAILED_DAYS:
                listings[key] = old
                print(f"  {key}: kept previous" + (f" ({error})" if error else ""), file=sys.stderr)
            else:
                listings[key] = {"missing": True, "checked": stamp}
                print(f"  {key}: no preview" + (f" ({error})" if error else ""))
            sleep(DELAY_SECONDS)
    counts["listings"] = len([x for x in listings.values() if x.get("name") and not x.get("hidden")])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "note": "Images published by each property's own website or listing (or, failing that, the one Google "
                "shows for it), displayed from their servers. Not stored here.",
        "photos": dict(sorted(photos.items())),
        "misses": dict(sorted((pid, when) for pid, when in misses.items()
                              if photos.get(pid, {}).get("from") not in OWN_SITE + ("manual",))),
        "listings": dict(sorted(listings.items())),
        "searched": dict(sorted((pid, when) for pid, when in searched.items() if pid not in photos)),
    }
    if (body["photos"] != previous or body["misses"] != old_misses or body["listings"] != old_listings
            or body["searched"] != old_searched or "generated_at" not in saved):
        body = {"generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"), **body}
        OUT.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts))
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="re-check every property, not only stale entries")
    ap.add_argument("--only", default="", help="comma-separated property ids to re-check")
    ap.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    ap.add_argument("--no-google", action="store_true", help="do not fall back to Google Hotels or Google Maps photos")
    try:  # the Google Maps fallback reads SEARCHAPI_KEY; pick it up from .env the way collect.py does
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from collect import load_env
        load_env()
    except Exception:  # noqa: BLE001 - photos still work without the key
        pass
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    run(ap.parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
