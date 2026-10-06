#!/usr/bin/env python3
"""Find a photo for each property and write docs/data/photos.json.

For every public property with a website, this reads the page's own link-preview
image (the og:image or twitter:image tag a site publishes so that links to it can
be shown with a picture) and records its address. The widget then shows that image
straight from the property's server. Nothing is downloaded into this repository.

Logos, placeholders and images that several properties share are passed over. When a
property's site offers nothing usable and collect.py has noted the photo Google Hotels
shows for it (docs/data/photo_hints.json), that address is used instead.

    python collector/photos.py                 # refresh entries older than 7 days
    python collector/photos.py --all           # re-check every property
    python collector/photos.py --only hotel-1883,amble-inn
    python collector/photos.py --no-google     # link-preview images only

Per-property overrides in data/properties.json:
    "photo": "https://..."     use this image instead (for example one of the Library's own)
    "photo": false             never show a photo for this property
    "photo_page": "https://..." read the preview image from this page instead of "url"
    "photo_match": "hotel 1883" take the Google Hotels photo of the result whose name contains this

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
KEEP_FAILED_DAYS = 30      # keep a previously found photo this long if the site stops answering
MIN_WIDTH = 400            # smaller images are usually logos or icons
MIN_RATIO, MAX_RATIO = 0.6, 2.6   # width / height; outside this it is usually a banner or a logo
PAGE_BYTES = 700_000
IMAGE_BYTES = 262_144
GENERIC = re.compile(r"placeholder|logo|default|social[-_ ]?shar|favicon|sprite|/icons?/", re.I)


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


def run(args, today: dt.date | None = None, finder=find_photo, checker=check_image, sleep=time.sleep) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    stamp = today.isoformat()
    props = [p for p in json.loads(PROPERTIES.read_text(encoding="utf-8"))["properties"] if p.get("public", True)]
    try:
        saved = json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    previous, old_misses = saved.get("photos", {}), saved.get("misses", {})
    try:
        hints = {} if args.no_google else json.loads(HINTS.read_text(encoding="utf-8")).get("hints", {})
    except (FileNotFoundError, json.JSONDecodeError):
        hints = {}
    only = {x.strip() for x in (args.only or "").split(",") if x.strip()}
    photos, misses = {}, {}
    counts = {"manual": 0, "found": 0, "google": 0, "kept": 0, "none": 0, "skipped": 0}

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
        if prop.get("type") == "rentals" or not (page or pid in hints):
            counts["skipped"] += 1
            continue
        wanted.append(pid)
        if old and old.get("from") != "preview":
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
            photos[pid] = {**hit, "page": page, "from": "preview", "checked": stamp}
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
            found = [pid for pid in pids if photos[pid].get("from") == "preview"]
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

    for entry in photos.values():
        if entry.get("from") == "manual":
            continue
        if entry.get("checked") != stamp:
            counts["kept"] += 1
        elif entry.get("from") == "preview":
            counts["found"] += 1
        elif entry.get("from") == "google":
            counts["google"] += 1
    counts["none"] = len([pid for pid in wanted if pid not in photos])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "note": "Images published by each property's own website (or, failing that, the one Google Hotels shows), "
                "displayed from their servers. Not stored here.",
        "photos": dict(sorted(photos.items())),
        "misses": dict(sorted((pid, when) for pid, when in misses.items()
                              if photos.get(pid, {}).get("from") not in ("preview", "manual"))),
    }
    if body["photos"] != previous or body["misses"] != old_misses or "generated_at" not in saved:
        body = {"generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"), **body}
        OUT.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts))
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="re-check every property, not only stale entries")
    ap.add_argument("--only", default="", help="comma-separated property ids to re-check")
    ap.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    ap.add_argument("--no-google", action="store_true", help="do not fall back to Google Hotels photos")
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    run(ap.parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
