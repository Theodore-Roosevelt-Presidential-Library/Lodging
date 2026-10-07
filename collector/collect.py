#!/usr/bin/env python3
"""Refresh docs/data/availability.json for the lodging widget.

Availability only: rates are never stored or shown.

Each property in data/properties.json may carry a "live" block naming a source.
A source answers, for each night in its horizon, whether a stay for two adults
could be booked. The widget combines nights into stays.

    python collector/collect.py              # normal run for the enabled sources
    python collector/collect.py --full       # re-check every night (first run, or after a gap)
    python collector/collect.py --dry-run    # show the plan; no network, no writes
    python collector/collect.py --check      # one small request per enabled source; prints what came back

Sources are enabled with LODGING_SOURCES (comma-separated) and read their keys
from the environment. Locally, both come from a .env file in the repo root
(copy .env.example); on GitHub they come from repository variables and secrets.

    trmf           Medora Foundation booking engine. No key.
    google_hotels  Google Hotels through SearchApi. SEARCHAPI_KEY.
    guesty         Guesty Booking Engine API, for an operator who shares credentials. Unused today.
    airbnb         Airbnb listing calendars through Apify, including the Vacation Medora cabins. APIFY_TOKEN.
    vrbo           Vrbo listing calendars through Apify. APIFY_TOKEN.

Standard library only, so the GitHub Action needs no install step.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROPERTIES = ROOT / "data" / "properties.json"
OUT = ROOT / "docs" / "data" / "availability.json"
PHOTO_HINTS = ROOT / "docs" / "data" / "photo_hints.json"
CHANGES = ROOT / "docs" / "data" / "changes.csv"
ENV_FILE = ROOT / ".env"
GUESTY_TOKEN_CACHE = ROOT / ".guesty_token.json"

MAX_HORIZON = 330
SETTINGS = {
    # horizon: nights ahead. near: nights refreshed every run. cycle: far nights refreshed once per this many runs.
    "trmf": {"horizon": 330, "near": 45, "cycle": 7, "delay": 1.0},
    # About 60 nights a run, four searches each: roughly 7,200 searches a month, inside the 10,000 plan.
    # Google Hotels stops answering somewhere past 250 nights out.
    "google_hotels": {"horizon": 240, "near": 30, "cycle": 7, "delay": 0.5},
    # Calendar sources return every night in one pass, so they need no rotation.
    "guesty": {"horizon": 330, "delay": 0.3, "chunk_days": 90},
    "airbnb": {"horizon": 330},
    "vrbo": {"horizon": 330},
    # One request per campground per month, ten seconds apart (the pause recreation.gov's robots file asks for).
    "recgov": {"horizon": 330, "delay": 10.0, "months": 8},
    # North Dakota state parks: one request per campground loop per three weeks of dates.
    "ndparks": {"horizon": 330, "delay": 2.0},
}
SOURCE_ORDER = ["trmf", "google_hotels", "guesty", "airbnb", "vrbo", "recgov", "ndparks"]
NDPARKS_API = "https://ndparksrdr.usedirect.com/rdr/rdr"
# A small Apify scraper that reads recreation.gov month by month, so the requests come from Apify
# rather than from this collector. Set RECGOV_VIA=direct to ask recreation.gov directly instead.
APIFY_RECGOV_ACTOR = "hikemetrics~recreation-gov-permit-tracker"

# How hard the scheduled runs work, chosen with LODGING_PACE (default "standard").
# Per-night sources list (nights ahead, re-check every N days) steps; None means "everything beyond".
# Calendar sources give the number of days between runs.
# Google Hotels is the same in both: its plan is a flat monthly rate, so checking less saves nothing.
PACE = {
    "standard": {},   # filled in below from SETTINGS: near nights daily, the rest once per cycle
    "light": {
        "trmf": [(14, 1), (60, 7), (None, 14)],
        "airbnb": 3, "vrbo": 3, "guesty": 3,
        "recgov": 2, "ndparks": 2,
    },
}
RECGOV_ENDPOINT = "https://www.recreation.gov/api/camps/availability/campground/{facility}/month?start_date={month}-01T00%3A00%3A00.000Z"
RECGOV_OPEN = {"Available"}
RECGOV_TAKEN = {"Reserved", "Not Available", "Not Available Cutoff", "Closed"}
RECGOV_IGNORED = {"Not Reservable", "Not Reservable Management"}   # walk-up or staff sites: neither open nor full
for _source, _cfg in SETTINGS.items():
    PACE["standard"][_source] = [(_cfg["near"], 1), (None, _cfg["cycle"])] if "cycle" in _cfg else 1
TIMEOUT_SECONDS = 30
MAX_CONSECUTIVE_FAILURES = 8
USER_AGENT = "TRPL-Lodging-Finder/1.0 (Theodore Roosevelt Presidential Library; https://www.trlibrary.com)"

TRMF_ENDPOINT = ("https://bookings.medora.com/api/dynamic-pricing/company/134/hotel/{hotel_id}"
                 "/arrival/{night}/nights/1/adults/2/children/0")
SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"
GOOGLE_QUERIES = {
    # key used in properties.json -> (search text, most pages to read)
    "medora": ("hotels in Medora, North Dakota", 1),
    "belfield": ("hotels in Belfield, North Dakota", 1),
    "dickinson": ("hotels in Dickinson, North Dakota", 2),
}
GUESTY_TOKEN_URL = "https://booking.guesty.com/oauth2/token"
GUESTY_API = "https://booking.guesty.com/api"
APIFY_API = "https://api.apify.com/v2"
APIFY_AIRBNB_ACTOR = "cirkit~airbnb-availability-scraper"
APIFY_VRBO_ACTOR = "memo23~vrbo-scraper"
APIFY_MAX_WAIT_SECONDS = 900


class MissingCredentials(Exception):
    pass


class HttpError(Exception):
    pass


# --------------------------------------------------------------------------- plumbing

def load_env(path: Path = ENV_FILE) -> None:
    """Read KEY=VALUE lines from .env into the environment without overriding what is already set."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() and value:
            os.environ.setdefault(key.strip(), value)


def http_json(method: str, url: str, headers: dict | None = None, json_body=None, form: dict | None = None):
    """One HTTP call returning parsed JSON. Errors name the host only, never the URL or any key."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    host = urllib.parse.urlsplit(url).netloc
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200].decode("utf-8", "replace").replace("\n", " ")
        raise HttpError(f"HTTP {exc.code} from {host}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(f"could not reach {host}: {getattr(exc, 'reason', exc)}") from None
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except json.JSONDecodeError:
        raise HttpError(f"{host} did not return JSON") from None


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def describe_change(old: dict | None, new: dict) -> str | None:
    if old is None:
        return None  # first sighting is not a change
    if old.get("a") == 1 and new.get("a") == 0:
        return "sold_out_or_closed"
    if old.get("a") == 0 and new.get("a") == 1:
        return "opened"
    return None


class Run:
    """State shared by the sources during one run."""

    def __init__(self, today: dt.date, args, nights: dict, checked: dict, sleep=time.sleep, env=None):
        self.today = today
        self.stamp = today.isoformat()
        self.args = args
        self.nights = nights
        self.checked = checked
        self.sleep = sleep
        self.env = os.environ if env is None else env
        self.changes: list[list] = []
        self.stats: dict[str, dict] = {}
        self.units: dict[str, list[dict]] = {}   # property id -> its listings, in the order of the "u" characters
        budget = getattr(args, "max_seconds", 0) or 0
        self.deadline = time.time() + budget if budget else None
        self.pace_name = str(self.env.get("LODGING_PACE") or "standard").strip().lower()
        if self.pace_name not in PACE:
            self.pace_name = "standard"

    def out_of_time(self) -> bool:
        """True once --max-seconds has passed. Per-night sources stop cleanly and the next run carries on."""
        return self.deadline is not None and time.time() >= self.deadline

    def pace(self, source: str):
        """This source's schedule: the chosen pace, falling back to standard where it says nothing."""
        return PACE[self.pace_name].get(source, PACE["standard"][source])

    def every(self, source: str, offset: int) -> int:
        """How many days may pass between checks of the night `offset` days ahead."""
        for upto, days in self.pace(source):
            if upto is None or offset < upto:
                return days
        return 1

    def stat(self, source: str) -> dict:
        return self.stats.setdefault(source, {"requests": 0, "failed": 0, "note": ""})

    def horizon(self, source: str) -> list[str]:
        days = min(SETTINGS[source]["horizon"], MAX_HORIZON)
        return [(self.today + dt.timedelta(days=i)).isoformat() for i in range(days)]

    def due(self, source: str) -> list[str]:
        """Per-night sources: which nights to check on this run.

        Never-checked nights always. Otherwise each night is re-checked every N days (N from the pace):
        on its own day of the rotation, which spreads the work evenly across daily runs, or as soon as
        it is N days old, which catches up after skipped runs.
        """
        seen, out, today_ord = self.checked.get(source, {}), [], self.today.toordinal()
        for offset, iso in enumerate(self.horizon(source)):
            last = seen.get(iso)
            if last == self.stamp and not self.args.full:
                continue   # already checked today, so a second run the same day picks up where the first stopped
            every = self.every(source, offset)
            age = (self.today - dt.date.fromisoformat(last)).days if last else None
            if (self.args.full or last is None or every <= 1 or age >= every
                    or (today_ord + offset) % every == today_ord % every):
                out.append(iso)
        return out[: self.args.limit] if self.args.limit else out

    def mark(self, source: str, night: str) -> None:
        self.checked.setdefault(source, {})[night] = self.stamp

    def put(self, night: str, pid: str, rec: dict | None) -> None:
        """Store a night record, or clear it when rec is None (availability unknown)."""
        day = self.nights.setdefault(night, {})
        if rec is None:
            day.pop(pid, None)
            return
        rec = dict(rec)
        rec["t"] = self.stamp
        change = describe_change(day.get(pid), rec)
        if change:
            self.changes.append([self.stamp, night, pid, change])
        day[pid] = rec

    def put_units(self, pid: str, unit_ids: list[str], calendars: dict[str, dict[str, bool]], source: str) -> int:
        """Write one record per night for a group of units (cabins, rentals).

        "u" has one character per unit, in a fixed order for the whole run: 1 open, 0 not.
        The widget ANDs these across the nights of a stay to count units open throughout.
        """
        written = 0
        for night in self.horizon(source):
            if not any(night in calendars.get(uid, {}) for uid in unit_ids):
                continue
            bits = "".join("1" if calendars.get(uid, {}).get(night) else "0" for uid in unit_ids)
            self.put(night, pid, {"a": 1 if "1" in bits else 0, "u": bits, "of": len(unit_ids)})
            written += 1
        return written


# --------------------------------------------------------------------------- trmf

def parse_trmf(payload: dict) -> dict:
    """{"a": 1, "q": 4} when bookable ("q" = how many of the first-listed room type remain), else {"a": 0}."""
    price = payload.get("price")
    if payload.get("available") in (1, True) and isinstance(price, (int, float)) and price > 0:
        rec = {"a": 1}
        qty = (payload.get("roomDetails") or {}).get("quantityAvailable")
        if isinstance(qty, int) and qty > 0:
            rec["q"] = qty
        return rec
    if payload.get("available") in (0, False) or payload.get("errors"):
        return {"a": 0}
    raise ValueError("unrecognised response shape")


def collect_trmf(run: Run, props: list[dict]) -> None:
    stat, cfg, streak = run.stat("trmf"), SETTINGS["trmf"], 0
    for night in run.due("trmf"):
        if run.out_of_time():
            stat["note"] = "stopped at the time limit; run again to carry on"
            return
        complete = True
        for prop in props:
            stat["requests"] += 1
            try:
                url = TRMF_ENDPOINT.format(hotel_id=int(prop["live"]["hotel_id"]), night=night)
                run.put(night, prop["id"], parse_trmf(http_json("GET", url)))
                streak = 0
            except (HttpError, ValueError) as exc:
                stat["failed"] += 1
                streak += 1
                complete = False
                print(f"  trmf {prop['id']} {night}: {exc}", file=sys.stderr)
                if streak >= MAX_CONSECUTIVE_FAILURES:
                    stat["note"] = f"stopped after {streak} failures in a row"
                    return
            run.sleep(cfg["delay"])
        if complete:
            run.mark("trmf", night)


# --------------------------------------------------------------------------- google hotels (SearchApi)

def photo_size(src: str) -> str:
    """Google serves its hotel photos at whatever size the address asks for; ask for a card-sized one."""
    if "googleusercontent.com/" in src:
        return re.sub(r"=[a-z0-9-]+$", "", src) + "=w640-h360-n-k-no"
    return src


def note_photos(run: Run, results: list[dict], query: str) -> None:
    """Remember the first Google Hotels image for each property that wants one (see collector/photos.py).

    A tracked hotel is matched only in its own town's results, so two hotels of one brand cannot swap photos.
    """
    names = [(norm(r.get("name", "")), r) for r in results]
    for pid, (want, where) in getattr(run, "photo_targets", {}).items():
        if where not in (None, query):
            continue
        hit = next((r for name, r in names if want and want in name), None)
        first = ((hit or {}).get("images") or [None])[0]
        src = (first.get("thumbnail") or first.get("original")) if isinstance(first, dict) else first
        if not (isinstance(src, str) and src.startswith("https://")):
            continue
        src = photo_size(src)
        if (run.photo_hints.get(pid) or {}).get("src") != src:
            run.photo_hints[pid] = {"src": src, "name": hit.get("name", ""), "seen": run.stamp}


def google_search(key: str, query: str, night: str, max_pages: int, run: Run) -> list[dict]:
    checkout = (dt.date.fromisoformat(night) + dt.timedelta(days=1)).isoformat()
    found, token = [], None
    for _ in range(max_pages):
        params = {"engine": "google_hotels", "q": query, "check_in_date": night, "check_out_date": checkout,
                  "adults": "2", "gl": "us", "hl": "en", "currency": "USD"}
        if token:
            params["next_page_token"] = token
        run.stat("google_hotels")["requests"] += 1
        payload = http_json("GET", SEARCHAPI_ENDPOINT + "?" + urllib.parse.urlencode(params),
                            headers={"Authorization": f"Bearer {key}"}) or {}
        if payload.get("error"):
            if "return any results" in str(payload["error"]):
                break   # nothing listed for that town and night (or the night is past Google's range): not a failure
            raise HttpError(f"SearchApi error: {str(payload['error'])[:160]}")
        found.extend(payload.get("properties") or [])
        token = (payload.get("pagination") or {}).get("next_page_token")
        if not token:
            break
        run.sleep(SETTINGS["google_hotels"]["delay"])
    return found


def match_google(results: list[dict], props: list[dict]) -> dict[str, dict | None]:
    """A matched hotel showing a nightly price is open. Anything else is unknown, never "full"."""
    out: dict[str, dict | None] = {}
    names = [(norm(r.get("name", "")), r) for r in results]
    for prop in props:
        want = norm(prop["live"]["match"])
        hit = next((r for name, r in names if want and want in name), None)
        priced = bool(hit and ((hit.get("price_per_night") or {}).get("extracted_price")
                               or (hit.get("total_price") or {}).get("extracted_price")))
        out[prop["id"]] = {"a": 1} if priced else None
    return out


def collect_google_hotels(run: Run, props: list[dict]) -> None:
    key = run.env.get("SEARCHAPI_KEY")
    if not key:
        raise MissingCredentials("SEARCHAPI_KEY is not set")
    stat, streak = run.stat("google_hotels"), 0
    by_query: dict[str, list[dict]] = {}
    for prop in props:
        by_query.setdefault(prop["live"]["query"], []).append(prop)
    for night in run.due("google_hotels"):
        if run.out_of_time():
            stat["note"] = "stopped at the time limit; run again to carry on"
            return
        complete = True
        for qkey, qprops in by_query.items():
            text, pages = GOOGLE_QUERIES[qkey]
            try:
                results = google_search(key, text, night, pages, run)
                note_photos(run, results, qkey)
                for pid, rec in match_google(results, qprops).items():
                    run.put(night, pid, rec)
                streak = 0
            except HttpError as exc:
                stat["failed"] += 1
                streak += 1
                complete = False
                print(f"  google_hotels {qkey} {night}: {exc}", file=sys.stderr)
                if streak >= 3:
                    stat["note"] = f"stopped after {streak} failures in a row: {exc}"
                    return
            run.sleep(SETTINGS["google_hotels"]["delay"])
        if complete:
            run.mark("google_hotels", night)


# --------------------------------------------------------------------------- guesty (Vacation Medora)

def guesty_token(run: Run) -> str:
    cid, secret = run.env.get("GUESTY_CLIENT_ID"), run.env.get("GUESTY_CLIENT_SECRET")
    if not (cid and secret):
        raise MissingCredentials("GUESTY_CLIENT_ID and GUESTY_CLIENT_SECRET are not set")
    # Guesty issues only a few tokens a day, so reuse a cached one while it is valid.
    try:
        cached = json.loads(GUESTY_TOKEN_CACHE.read_text(encoding="utf-8"))
        if cached.get("client_id") == cid and cached.get("expires_at", 0) > time.time() + 600:
            return cached["access_token"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    run.stat("guesty")["requests"] += 1
    payload = http_json("POST", GUESTY_TOKEN_URL, form={
        "grant_type": "client_credentials", "scope": "booking_engine:api", "client_id": cid, "client_secret": secret})
    token = (payload or {}).get("access_token")
    if not token:
        raise HttpError("Guesty did not return an access token")
    try:
        GUESTY_TOKEN_CACHE.write_text(json.dumps({
            "client_id": cid, "access_token": token,
            "expires_at": time.time() + int(payload.get("expires_in", 86400))}), encoding="utf-8")
        GUESTY_TOKEN_CACHE.chmod(0o600)
    except OSError:
        pass
    return token


def guesty_listings(token: str, run: Run) -> list[dict]:
    listings, cursor = [], None
    for _ in range(10):
        params = {"limit": "100"}
        if cursor:
            params["cursor"] = cursor
        run.stat("guesty")["requests"] += 1
        payload = http_json("GET", f"{GUESTY_API}/listings?" + urllib.parse.urlencode(params),
                            headers={"Authorization": f"Bearer {token}"}) or {}
        batch = payload.get("results") if isinstance(payload, dict) else payload
        listings.extend(batch or [])
        cursor = ((payload.get("pagination") or {}).get("cursor") or {}).get("next") if isinstance(payload, dict) else None
        if not cursor or not batch:
            break
    return listings


def parse_guesty_calendar(payload) -> dict[str, bool]:
    """Map YYYY-MM-DD -> open. Accepts a bare list of days or a wrapper holding one."""
    days = payload
    for key in ("data", "days", "calendar", "results"):
        if isinstance(days, dict) and key in days:
            days = days[key]
    if isinstance(days, dict) and "days" in days:
        days = days["days"]
    if not isinstance(days, list):
        raise ValueError("calendar response is not a list of days")
    out: dict[str, bool] = {}
    for day in days:
        date = str(day.get("date") or day.get("calendarDate") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        if "status" in day:
            out[date] = str(day["status"]).lower() == "available"
        elif "available" in day:
            out[date] = bool(day["available"])
        else:
            raise ValueError("calendar day has neither status nor available")
    return out


def group_guesty(listings: list[dict], props: list[dict]) -> dict[str, list[str]]:
    """Assign each listing to a property: by title keyword first, then by city, then to the default."""
    groups: dict[str, list[str]] = {p["id"]: [] for p in props}
    default = next((p["id"] for p in props if p["live"].get("default")), None)
    for item in listings:
        lid = str(item.get("_id") or item.get("id") or "")
        if not lid:
            continue
        title = norm(f"{item.get('title', '')} {item.get('nickname', '')}")
        city = norm(((item.get("address") or {}).get("city")) or "")
        target = next((p["id"] for p in props if p["live"].get("title_contains")
                       and norm(p["live"]["title_contains"]) in title), None)
        if not target and city:
            target = next((p["id"] for p in props if norm(p["live"].get("city", "")) == city
                           and not p["live"].get("title_contains")), None)
        target = target or default
        if target:
            groups[target].append(lid)
    return {pid: sorted(ids) for pid, ids in groups.items()}


def guesty_calendar(token: str, listing_id: str, run: Run) -> dict[str, bool]:
    cfg, out = SETTINGS["guesty"], {}
    nights = run.horizon("guesty")
    for start in range(0, len(nights), cfg["chunk_days"]):
        chunk = nights[start:start + cfg["chunk_days"]]
        run.stat("guesty")["requests"] += 1
        url = f"{GUESTY_API}/listings/{urllib.parse.quote(listing_id)}/calendar?" + urllib.parse.urlencode(
            {"from": chunk[0], "to": chunk[-1]})
        out.update(parse_guesty_calendar(http_json("GET", url, headers={"Authorization": f"Bearer {token}"})))
        run.sleep(cfg["delay"])
    return out


def collect_guesty(run: Run, props: list[dict]) -> None:
    stat = run.stat("guesty")
    token = guesty_token(run)
    groups = group_guesty(guesty_listings(token, run), props)
    for prop in props:
        ids = groups.get(prop["id"]) or []
        calendars: dict[str, dict[str, bool]] = {}
        for lid in ids:
            try:
                calendars[lid] = guesty_calendar(token, lid, run)
            except (HttpError, ValueError) as exc:
                stat["failed"] += 1
                print(f"  guesty {prop['id']} listing {lid}: {exc}", file=sys.stderr)
        if not calendars:
            stat["note"] = (stat["note"] + f" {prop['id']}: no calendars read ({len(ids)} listings).").strip()
            continue
        run.put_units(prop["id"], ids, calendars, "guesty")
    for night in run.horizon("guesty"):
        run.mark("guesty", night)


# --------------------------------------------------------------------------- apify (Airbnb, Vrbo)

def apify_run(actor: str, actor_input: dict, token: str, run: Run, source: str) -> list[dict]:
    """Start an actor, wait for it to finish, return its dataset items."""
    # waitForFinish must stay below TIMEOUT_SECONDS or every poll would time out.
    auth = {"Authorization": f"Bearer {token}"}
    run.stat(source)["requests"] += 1
    started = (http_json("POST", f"{APIFY_API}/acts/{actor}/runs?waitForFinish=20", headers=auth,
                         json_body=actor_input) or {}).get("data") or {}
    run_id, status = started.get("id"), started.get("status")
    if not run_id:
        raise HttpError("Apify did not start the run")
    deadline = time.time() + APIFY_MAX_WAIT_SECONDS
    while status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
        if time.time() > deadline:
            raise HttpError(f"Apify run did not finish within {APIFY_MAX_WAIT_SECONDS} seconds")
        info = (http_json("GET", f"{APIFY_API}/actor-runs/{run_id}?waitForFinish=20", headers=auth) or {}).get("data") or {}
        status = info.get("status")
        started = info or started
        run.sleep(1)
    if status != "SUCCEEDED":
        raise HttpError(f"Apify run ended with status {status}")
    dataset = started.get("defaultDatasetId")
    items = http_json("GET", f"{APIFY_API}/datasets/{dataset}/items?clean=true&format=json", headers=auth)
    return items if isinstance(items, list) else []


def parse_airbnb_items(items: list[dict]) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for item in items:
        lid = str(item.get("listingId") or "")
        days = item.get("days")
        if not lid or not isinstance(days, list) or item.get("error"):
            continue
        cal = {}
        for day in days:
            date = str(day.get("calendarDate") or day.get("date") or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and "available" in day:
                cal[date] = bool(day["available"])
        if cal:
            out[lid] = cal
    return out


def parse_vrbo_items(items: list[dict], exclude: set[str]) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for item in items:
        if item.get("kind") not in (None, "property"):
            continue
        vid = str(item.get("vrboId") or "")
        days = item.get("calendar")
        if not vid or vid in exclude or not isinstance(days, list):
            continue
        cal = {str(d.get("date"))[:10]: bool(d.get("available")) for d in days
               if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d.get("date"))[:10]) and "available" in d}
        if cal:
            out[vid] = cal
    return out


def clean_title(text, limit: int = 80) -> str:
    """A host-written listing title, tidied: one line, single spaces, not too long."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,.-") + "…"


def rated_below(rating, scale, floor: float, reviews=None) -> bool:
    """True when a listing's guest rating is known and under the floor (a fraction of the scale)."""
    try:
        rating, scale = float(rating), float(scale or 0)
    except (TypeError, ValueError):
        return False
    if scale <= 0 or (reviews is not None and int(reviews or 0) < 3):
        return False
    return rating / scale < floor


def parse_vrbo_details(items: list[dict], floor: float = 0.7) -> tuple[dict[str, dict], set[str]]:
    """Name, link and first photo for each Vrbo listing, plus the IDs to leave out for a low guest rating.

    Rates, ratings, host names and everything else the actor returns are discarded.
    """
    details, low = {}, set()
    for item in items:
        if item.get("kind") not in (None, "property"):
            continue
        vid = str(item.get("vrboId") or "")
        if not vid:
            continue
        if rated_below(item.get("rating"), item.get("ratingScale") or 10, floor, item.get("reviewCount")):
            low.add(vid)
            continue
        entry = {"id": vid, "src": "vrbo", "name": clean_title(item.get("title")),
                 "url": str(item.get("listingUrl") or f"https://www.vrbo.com/{vid}")}
        first = (item.get("photos") or [None])[0]
        photo = first.get("url") if isinstance(first, dict) else first
        if isinstance(photo, str) and photo.startswith("https://"):
            entry["photo"] = photo.split("?")[0] + ("?impolicy=resizecrop&rw=640&ra=fit" if "media.vrbo.com/" in photo else "")
        facts = []
        for key, one, many in (("sleeps", "Sleeps {}", "Sleeps {}"), ("bedrooms", "{} bedroom", "{} bedrooms"),
                               ("bathrooms", "{} bath", "{} baths")):
            value = item.get(key)
            if isinstance(value, (int, float)) and value > 0:
                facts.append((one if value == 1 else many).format(int(value) if float(value).is_integer() else value))
        if facts:
            entry["facts"] = " · ".join(facts)
        details[vid] = entry
    return details, low


def apify_token(run: Run) -> str:
    token = run.env.get("APIFY_TOKEN")
    if not token:
        raise MissingCredentials("APIFY_TOKEN is not set")
    return token


def collect_airbnb(run: Run, props: list[dict]) -> None:
    """One actor run covers every listing ID across all Airbnb-sourced properties."""
    token, stat = apify_token(run), run.stat("airbnb")
    wanted = {p["id"]: [str(i) for i in p["live"].get("listings", [])] for p in props}
    props_by_id = {p["id"]: p for p in props}
    all_ids = sorted({i for ids in wanted.values() for i in ids})
    if not all_ids:
        return
    calendars = parse_airbnb_items(apify_run(APIFY_AIRBNB_ACTOR, {"listingIds": all_ids, "months": 12}, token, run, "airbnb"))
    if not calendars:
        raise HttpError("the Airbnb actor returned no calendars")
    notes = []
    for pid, ids in wanted.items():
        got = {i: calendars[i] for i in ids if i in calendars}
        if not got:
            notes.append(f"{pid}: no calendars")
            continue
        if len(got) < len(ids):
            notes.append(f"{pid}: {len(ids) - len(got)} of {len(ids)} listings returned no calendar")
        hidden = {str(x) for x in props_by_id[pid]["live"].get("hide", [])}
        ids = [i for i in ids if i not in hidden]
        run.put_units(pid, ids, got, "airbnb")
        if props_by_id[pid].get("list_units"):
            run.units[pid] = [{"id": i, "src": "airbnb", "url": f"https://www.airbnb.com/rooms/{i}"} for i in ids]
    stat["note"] = "; ".join(notes)
    for night in run.horizon("airbnb"):
        run.mark("airbnb", night)


def collect_vrbo(run: Run, props: list[dict]) -> None:
    token, stat = apify_token(run), run.stat("vrbo")
    for prop in props:
        live = prop["live"]
        actor_input = {"startUrls": list(live.get("start", [])), "scrapeAvailability": True, "includeReviews": False,
                       "adultsCount": 2, "maxItems": int(live.get("max_items", 60))}
        items = apify_run(APIFY_VRBO_ACTOR, actor_input, token, run, "vrbo")
        details, low = parse_vrbo_details(items, float(live.get("min_rating", 0.7)))
        skip = {str(x) for x in live.get("exclude", [])} | {str(x) for x in live.get("hide", [])} | low
        calendars = parse_vrbo_items(items, skip)
        if not calendars:
            stat["note"] = f"{prop['id']}: the actor returned no calendars"
            continue
        ids = sorted(calendars)
        run.put_units(prop["id"], ids, calendars, "vrbo")
        if prop.get("list_units"):
            run.units[prop["id"]] = [details.get(vid) or {"id": vid, "src": "vrbo", "url": f"https://www.vrbo.com/{vid}"}
                                     for vid in ids]
        if low:
            stat["note"] = f"{prop['id']}: {len(low)} left out for a low guest rating"
    for night in run.horizon("vrbo"):
        run.mark("vrbo", night)


# --------------------------------------------------------------------------- recreation.gov campgrounds

def parse_recgov_month(payload) -> dict[str, dict | None]:
    """Night -> record for one campground-month.

    Open when at least one site is "Available" (q = how many). Full when every reservable site is taken.
    Unknown (None) when the night has not been released for booking yet or has only walk-up sites.
    """
    by_night: dict[str, list[str]] = {}
    for site in ((payload or {}).get("campsites") or {}).values():
        for day, status in ((site or {}).get("availabilities") or {}).items():
            by_night.setdefault(str(day)[:10], []).append(str(status))
    out: dict[str, dict | None] = {}
    for night, statuses in by_night.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", night):
            continue
        out[night] = recgov_night(statuses, sum(1 for s in statuses if s in RECGOV_OPEN))
    return out


def recgov_unreleased(payload) -> bool:
    """True when a month holds nothing but nights not yet released for booking."""
    seen = {str(s) for site in ((payload or {}).get("campsites") or {}).values()
            for s in ((site or {}).get("availabilities") or {}).values()} - RECGOV_IGNORED
    return seen == {"NYR"}


def recgov_months(run: Run) -> list[str]:
    nights = run.horizon("recgov")
    return sorted({n[:7] for n in nights})


def recgov_night(statuses: list[str], open_sites: int) -> dict | None:
    """One night's record from the statuses seen that night and how many sites are open."""
    counted = [s for s in statuses if s not in RECGOV_IGNORED]
    if open_sites:
        return {"a": 1, "q": open_sites}
    if counted and all(s in RECGOV_TAKEN for s in counted):
        return {"a": 0}
    return None


def parse_recgov_actor(items: list[dict]) -> dict[str, dict[str, dict | None]]:
    """Campground id -> night -> record, from the Apify scraper's month-by-month results."""
    out: dict[str, dict[str, dict | None]] = {}
    for item in items:
        fid = str(item.get("targetId") or "")
        if not fid or item.get("success") is False:
            continue
        for day in item.get("availability") or []:
            night = str(day.get("date") or "")[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", night):
                continue
            statuses = [str(s) for s in day.get("statuses") or []]
            count = day.get("bookableCampsiteCount")
            if not isinstance(count, int):
                count = day.get("availableCampsiteCount") if isinstance(day.get("availableCampsiteCount"), int) else 0
            if "Available" not in statuses:
                count = 0   # the scraper also counts "Open" (shown but not yet on sale); only "Available" can be booked
            elif not count:
                count = 1
            out.setdefault(fid, {})[night] = recgov_night(statuses, count)
    return out


def collect_recgov_apify(run: Run, props: list[dict]) -> None:
    token, stat = apify_token(run), run.stat("recgov")
    months = recgov_months(run)[: SETTINGS["recgov"]["months"]]   # booking opens about six months ahead
    targets = [{"checkType": "campground-month", "facilityId": str(int(p["live"]["facility"])), "name": p["name"],
                "months": months} for p in props]
    found = parse_recgov_actor(apify_run(APIFY_RECGOV_ACTOR, {"targets": targets}, token, run, "recgov"))
    horizon, missing = set(run.horizon("recgov")), []
    for prop in props:
        nights = found.get(str(int(prop["live"]["facility"])))
        if nights is None:
            missing.append(prop["id"])
            continue
        for night, rec in nights.items():
            if night in horizon:
                run.put(night, prop["id"], rec)
    if missing:
        stat["note"] = "no answer for " + ", ".join(missing)
    if len(missing) < len(props):
        for night in run.horizon("recgov"):
            run.mark("recgov", night)
    else:
        raise HttpError("the recreation.gov scraper returned nothing")


def collect_recgov(run: Run, props: list[dict]) -> None:
    """Through the Apify scraper by default; straight from recreation.gov when RECGOV_VIA=direct."""
    if str(run.env.get("RECGOV_VIA") or "apify").strip().lower() == "direct":
        collect_recgov_direct(run, props)
    else:
        collect_recgov_apify(run, props)


def collect_recgov_direct(run: Run, props: list[dict]) -> None:
    stat, cfg = run.stat("recgov"), SETTINGS["recgov"]
    horizon, complete = set(run.horizon("recgov")), True
    for prop in props:
        facility = int(prop["live"]["facility"])
        for month in recgov_months(run):
            stat["requests"] += 1
            try:
                payload = http_json("GET", RECGOV_ENDPOINT.format(facility=facility, month=month))
                nights = parse_recgov_month(payload)
            except (HttpError, ValueError) as exc:
                stat["failed"] += 1
                complete = False
                print(f"  recgov {prop['id']} {month}: {exc}", file=sys.stderr)
                run.sleep(cfg["delay"])
                continue
            for night, rec in nights.items():
                if night in horizon:
                    run.put(night, prop["id"], rec)
            run.sleep(cfg["delay"])
            if month > run.stamp[:7] and recgov_unreleased(payload):
                break   # booking has not opened this far out, so later months will say the same
    if complete:
        for night in run.horizon("recgov"):
            run.mark("recgov", night)


# --------------------------------------------------------------------------- North Dakota state parks

def parse_ndparks_grid(payload) -> tuple[dict[str, list[int]], str | None, str | None]:
    """(night -> [free sites, bookable sites]), the last date covered, and the last date open for booking."""
    counts: dict[str, list[int]] = {}
    units = (((payload or {}).get("Facility") or {}).get("Units") or {})
    for unit in units.values():
        if unit.get("AllowWebBooking") is False:
            continue
        for piece in (unit.get("Slices") or {}).values():
            night = str(piece.get("Date") or "")[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", night) or piece.get("IsWalkin"):
                continue
            pair = counts.setdefault(night, [0, 0])
            pair[1] += 1
            if piece.get("IsFree") and not piece.get("IsBlocked"):
                pair[0] += 1
    return counts, str((payload or {}).get("EndDate") or "")[:10] or None, str((payload or {}).get("MaxDate") or "")[:10] or None


def collect_ndparks(run: Run, props: list[dict]) -> None:
    stat, cfg = run.stat("ndparks"), SETTINGS["ndparks"]
    horizon, last_day, complete = set(run.horizon("ndparks")), run.horizon("ndparks")[-1], True
    for prop in props:
        totals: dict[str, list[int]] = {}
        for facility in prop["live"]["facilities"]:
            start = run.today
            for _ in range(30):   # three weeks a request; thirty requests is far past the booking window
                stat["requests"] += 1
                body = {"FacilityId": str(int(facility)), "UnitTypeId": 0, "StartDate": start.strftime("%m-%d-%Y"),
                        "InSeasonOnly": True, "WebOnly": True, "IsADA": False, "SleepingUnitId": 0,
                        "MinVehicleLength": 0, "UnitCategoryId": 0, "UnitTypesGroupIds": []}
                try:
                    counts, end, limit = parse_ndparks_grid(http_json("POST", f"{NDPARKS_API}/search/grid", json_body=body))
                except (HttpError, ValueError) as exc:
                    stat["failed"] += 1
                    complete = False
                    print(f"  ndparks {prop['id']} loop {facility} from {start}: {exc}", file=sys.stderr)
                    break
                for night, (free, bookable) in counts.items():
                    pair = totals.setdefault(night, [0, 0])
                    pair[0] += free
                    pair[1] += bookable
                run.sleep(cfg["delay"])
                if not end or not counts or end >= (limit or last_day) or end >= last_day:
                    break
                start = dt.date.fromisoformat(end) + dt.timedelta(days=1)
        for night in horizon:
            free, bookable = totals.get(night, (0, 0))
            if not free and night == run.stamp:
                bookable = 0   # tonight cannot be booked online, but walk-up sites may be open: say nothing
            run.put(night, prop["id"], {"a": 1, "q": free} if free else ({"a": 0} if bookable else None))
    if complete:
        for night in run.horizon("ndparks"):
            run.mark("ndparks", night)


SOURCES = {"trmf": collect_trmf, "google_hotels": collect_google_hotels, "guesty": collect_guesty,
           "airbnb": collect_airbnb, "vrbo": collect_vrbo, "recgov": collect_recgov, "ndparks": collect_ndparks}


# --------------------------------------------------------------------------- connection check

def check(run: Run, source: str, props: list[dict]) -> None:
    """One small request per source. Prints shapes and names, never keys or rates."""
    night = (run.today + dt.timedelta(days=30)).isoformat()
    if source == "trmf":
        rec = parse_trmf(http_json("GET", TRMF_ENDPOINT.format(hotel_id=int(props[0]["live"]["hotel_id"]), night=night)))
        print(f"  {props[0]['name']} on {night}: {'open' if rec['a'] else 'full or closed'}")
    elif source == "google_hotels":
        key = run.env.get("SEARCHAPI_KEY")
        if not key:
            raise MissingCredentials("SEARCHAPI_KEY is not set")
        for qkey in sorted({p["live"]["query"] for p in props}):
            qprops = [p for p in props if p["live"]["query"] == qkey]
            results = google_search(key, GOOGLE_QUERIES[qkey][0], night, GOOGLE_QUERIES[qkey][1], run)
            matched = match_google(results, qprops)
            names = {norm(r.get("name", "")): r.get("name") for r in results}
            print(f"  {qkey} on {night}: {len(results)} results; {sum(1 for v in matched.values() if v)} of {len(qprops)} tracked hotels open")
            for p in qprops:
                seen = next((n for k, n in names.items() if norm(p["live"]["match"]) in k), None)
                print(f"    {p['name']}: " + (f"matched \"{seen}\", {'open' if matched[p['id']] else 'no rate shown'}" if seen else "NOT FOUND in results"))
    elif source == "guesty":
        token = guesty_token(run)
        listings = guesty_listings(token, run)
        groups = group_guesty(listings, props)
        print(f"  {len(listings)} listings; fields on the first: {sorted(listings[0])[:12] if listings else []}")
        titles = {str(l.get('_id')): l.get("title") or l.get("nickname") for l in listings}
        for p in props:
            print(f"    {p['name']}: {[titles.get(i) for i in groups[p['id']]]}")
        if listings:
            lid = str(listings[0].get("_id"))
            to = (run.today + dt.timedelta(days=6)).isoformat()
            raw = http_json("GET", f"{GUESTY_API}/listings/{lid}/calendar?from={run.stamp}&to={to}",
                            headers={"Authorization": f"Bearer {token}"})
            first = raw[0] if isinstance(raw, list) and raw else raw
            print(f"  calendar response type {type(raw).__name__}; first entry fields: {sorted(first) if isinstance(first, dict) else first}")
            print(f"  parsed 7 days: {parse_guesty_calendar(raw)}")
    elif source == "airbnb":
        ids = [str(i) for i in props[0]["live"].get("listings", [])][:1]
        items = apify_run(APIFY_AIRBNB_ACTOR, {"listingIds": ids, "months": 1}, apify_token(run), run, "airbnb")
        print(f"  {len(items)} item(s); fields on the first: {sorted(items[0])[:15] if items else []}")
        cal = parse_airbnb_items(items)
        print(f"  parsed calendars: {len(cal)}; days in the first: {len(next(iter(cal.values()))) if cal else 0}")
    elif source == "ndparks":
        counts, end, limit = parse_ndparks_grid(http_json("POST", f"{NDPARKS_API}/search/grid", json_body={
            "FacilityId": str(int(props[0]["live"]["facilities"][0])), "UnitTypeId": 0, "StartDate": run.today.strftime("%m-%d-%Y"),
            "InSeasonOnly": True, "WebOnly": True, "IsADA": False, "SleepingUnitId": 0, "MinVehicleLength": 0,
            "UnitCategoryId": 0, "UnitTypesGroupIds": []}))
        print(f"  {props[0]['name']}: {len(counts)} nights through {end}; booking open through {limit}; "
              f"{sum(1 for free, _ in counts.values() if free)} nights with open sites")
    elif source == "recgov":
        nights = parse_recgov_month(http_json("GET", RECGOV_ENDPOINT.format(facility=int(props[0]["live"]["facility"]), month=run.stamp[:7])))
        known = [n for n, r in sorted(nights.items()) if r and n >= run.stamp]
        print(f"  {props[0]['name']}: {len(nights)} nights this month, {sum(1 for r in nights.values() if r and r['a'])} with open sites"
              + (f"; next open or full night {known[0]}" if known else ""))
    elif source == "vrbo":
        live = props[0]["live"]
        items = apify_run(APIFY_VRBO_ACTOR, {"startUrls": list(live.get("start", [])), "scrapeAvailability": True,
                                             "includeReviews": False, "adultsCount": 2, "maxItems": 3},
                          apify_token(run), run, "vrbo")
        print(f"  {len(items)} item(s); fields on the first: {sorted(items[0])[:15] if items else []}")
        cal = parse_vrbo_items(items, set())
        print(f"  parsed calendars: {len(cal)}; titles: {[i.get('title') for i in items][:3]}")


# --------------------------------------------------------------------------- main

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def append_changes(rows: list[list]) -> None:
    if not rows:
        return
    new_file = not CHANGES.exists()
    with CHANGES.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["checked", "night", "property", "change"])
        writer.writerows(rows)


def run(args, sources=None, today: dt.date | None = None, sleep=time.sleep, env=None) -> dict:
    sources = SOURCES if sources is None else sources
    today = today or dt.datetime.now(dt.timezone.utc).date()
    stamp = today.isoformat()
    enabled = [s for s in SOURCE_ORDER + sorted(set(sources) - set(SOURCE_ORDER))
               if s in {x.strip() for x in (args.sources or "").split(",") if x.strip()} and s in sources]

    catalog = load_json(PROPERTIES, {"properties": []})
    props = catalog["properties"]
    previous = load_json(OUT, {})
    nights = {n: recs for n, recs in (previous.get("nights") or {}).items() if n >= stamp}
    checked = {s: {n: t for n, t in seen.items() if n >= stamp}
               for s, seen in (previous.get("checked") or {}).items()}
    # Drop records for properties that are no longer live under an enabled or previously used source.
    live_ids = {p["id"] for p in props if p.get("live")}
    for recs in nights.values():
        for pid in [pid for pid in recs if pid not in live_ids]:
            del recs[pid]

    state = Run(today, args, nights, checked, sleep=sleep, env=env)
    listed = {p["id"] for p in props if p.get("live") and p.get("list_units") and p.get("public", True)}
    state.units = {pid: units for pid, units in (previous.get("units") or {}).items() if pid in listed}
    # Google Hotels results carry a photo; note one for each tracked hotel and for any property that asks
    # for it with "photo_match". photos.py uses these only when a property's own site offers no image.
    state.photo_targets = {}
    for p in props:
        live = p.get("live") or {}
        tracked = live.get("source") == "google_hotels"
        if p.get("public", True) and p.get("photo") is None and (p.get("photo_match") or tracked):
            state.photo_targets[p["id"]] = (norm(p.get("photo_match") or live.get("match") or ""),
                                            live.get("query") if tracked else None)
    state.photo_hints = dict(load_json(PHOTO_HINTS, {}).get("hints") or {})
    hints_before = json.dumps(state.photo_hints, sort_keys=True)
    for source in enabled:
        sprops = [p for p in props if (p.get("live") or {}).get("source") == source]
        only = {x.strip() for x in (getattr(args, "props", "") or "").split(",") if x.strip()}
        if only:
            sprops = [p for p in sprops if p["id"] in only]
        if not sprops:
            continue
        # Calendar sources (rentals, campgrounds) read the whole horizon at once, so their pace is simply
        # how many days to leave between runs.
        gap, last_run = state.pace(source), (previous.get("sources") or {}).get(source, {}).get("at")
        if (isinstance(gap, int) and gap > 1 and last_run and not (args.full or args.check or args.dry_run or only)
                and (today - dt.date.fromisoformat(last_run)).days < gap):
            print(f"{source}: not due (runs every {gap} days, last ran {last_run})")
            continue
        stat = state.stat(source)
        if args.dry_run:
            if "cycle" in SETTINGS.get(source, {}):
                due = state.due(source)
                print(f"{source}: {len(sprops)} properties, {len(due)} nights due" + (f" ({due[0]} to {due[-1]})" if due else ""))
            else:
                print(f"{source}: {len(sprops)} properties, full calendar for {SETTINGS[source]['horizon']} nights")
            continue
        try:
            if args.check:
                print(f"{source}:")
                check(state, source, sprops)
            else:
                sources[source](state, sprops)
            stat["ok"] = not (stat["requests"] and stat["failed"] >= stat["requests"])
        except MissingCredentials as exc:
            stat.update(ok=False, note=f"skipped: {exc}")
        except (HttpError, ValueError, KeyError, TypeError) as exc:
            stat.update(ok=False, note=f"failed: {exc}")
        print(f"{source}: {json.dumps(stat)}")

    summary = {"sources": state.stats, "changes": len(state.changes)}
    if args.dry_run or args.check:
        return summary

    # Another run may have written the file while this one was working (two sources run side by side
    # during a first fill). Take everything this run did not touch from the file as it is now.
    ran = set(state.stats)
    mine = {p["id"] for p in props if (p.get("live") or {}).get("source") in ran}
    latest = load_json(OUT, {})
    if latest and latest != previous:
        fresh = {n: recs for n, recs in (latest.get("nights") or {}).items() if n >= stamp}
        for night in set(nights) | set(fresh):
            day, now = nights.setdefault(night, {}), fresh.get(night, {})
            for pid in [pid for pid in day if pid not in mine]:
                del day[pid]
            day.update({pid: rec for pid, rec in now.items() if pid not in mine and pid in live_ids})
        for source, seen in (latest.get("checked") or {}).items():
            if source not in ran:
                checked[source] = {n: t for n, t in seen.items() if n >= stamp}
        for pid, units in (latest.get("units") or {}).items():
            if pid not in mine and pid in listed:
                state.units[pid] = units
        previous = latest

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "horizon_nights": MAX_HORIZON,
        "basis": "Whether a stay for two adults could be booked when checked. Rates are not collected.",
        "sources_enabled": enabled,
        "pace": state.pace_name,
        # Each source keeps its last result, so a run of one source does not wipe the others off the monitor.
        "sources": {**{s: v for s, v in (previous.get("sources") or {}).items() if s in sources},
                    **{s: {"ok": v.get("ok", False), "note": v.get("note", ""), "at": stamp} for s, v in state.stats.items()}},
        "trolley_months": catalog.get("trolley_months", []),
        "properties": [p for p in props if p.get("public", True)],
        "units": {pid: state.units[pid] for pid in sorted(state.units) if pid in listed},
        "nights": {n: nights[n] for n in sorted(nights) if nights[n]},
        "checked": {s: dict(sorted(v.items())) for s, v in checked.items() if v},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    scratch = OUT.with_suffix(".json.tmp")   # write beside the file, then swap, so a reader never sees half a file
    scratch.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(scratch, OUT)
    append_changes(state.changes)
    hints = {pid: h for pid, h in state.photo_hints.items() if pid in state.photo_targets}
    if json.dumps(hints, sort_keys=True) != hints_before:
        PHOTO_HINTS.write_text(json.dumps({
            "note": "First Google Hotels image for each tracked hotel. Used by collector/photos.py as a fallback.",
            "hints": dict(sorted(hints.items())),
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return summary


def main(argv=None) -> int:
    load_env()
    try:  # show each source's result as it finishes, even when output is piped to a log
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="re-check every night in each source's horizon")
    ap.add_argument("--dry-run", action="store_true", help="plan only; no network and no writes")
    ap.add_argument("--check", action="store_true", help="one small request per enabled source; no writes")
    ap.add_argument("--limit", type=int, default=0, help="cap nights per run for per-night sources (testing)")
    ap.add_argument("--sources", default=os.environ.get("LODGING_SOURCES", ""),
                    help="comma-separated sources to run (default: $LODGING_SOURCES)")
    ap.add_argument("--props", default="", help="comma-separated property ids to limit the run to (testing)")
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="per-night sources stop starting new nights after this long and save what they have")
    args = ap.parse_args(argv)
    summary = run(args)
    ran = [v for v in summary["sources"].values() if "ok" in v and not str(v.get("note", "")).startswith("skipped")]
    # Fail the workflow only when every source that ran failed, so someone looks.
    return 1 if ran and not any(v["ok"] for v in ran) else 0


if __name__ == "__main__":
    sys.exit(main())
