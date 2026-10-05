#!/usr/bin/env python3
"""Refresh docs/data/availability.json for the lodging widget.

For every property in data/properties.json that has a "live" source, ask that
source whether a one-night stay for two adults is available on each night in
the horizon. Availability only: rates are not stored or shown. The widget
combines nights into stays.

Standard library only, so the GitHub Action needs no install step.

    python collector/collect.py            # daily run: near nights + a rotating slice of far nights
    python collector/collect.py --full     # every night in the horizon (first run, or after a gap)
    python collector/collect.py --dry-run  # show what would be requested; no network, no writes

Sources are switched on with the LODGING_SOURCES environment variable
(comma-separated, e.g. "trmf"). With nothing switched on the run still
rebuilds the file from data/properties.json and prunes past nights.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROPERTIES = ROOT / "data" / "properties.json"
OUT = ROOT / "docs" / "data" / "availability.json"
CHANGES = ROOT / "docs" / "data" / "changes.csv"

HORIZON_NIGHTS = 330   # how far ahead to look; the booking engine allows 365
NEAR_NIGHTS = 45       # refreshed on every run
FAR_CYCLE_DAYS = 7     # each far night is refreshed once per this many runs
DELAY_SECONDS = 1.0    # pause between requests to one source
TIMEOUT_SECONDS = 25
MAX_CONSECUTIVE_FAILURES = 8
USER_AGENT = "TRPL-Lodging-Finder/1.0 (Theodore Roosevelt Presidential Library; https://www.trlibrary.com)"

TRMF_ENDPOINT = ("https://bookings.medora.com/api/dynamic-pricing/company/134/hotel/{hotel_id}"
                 "/arrival/{night}/nights/1/adults/2/children/0")


# --------------------------------------------------------------------------- sources

def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_trmf(payload: dict) -> dict:
    """Turn one dynamic-pricing response into a compact night record.

    Available:   {"a": 1, "q": 4}
    Unavailable: {"a": 0}
    "q" is how many of the first-listed room type remain, when the engine says.
    Rates are deliberately not kept: the tool shows availability only.
    """
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


def fetch_trmf(live: dict, night: str) -> dict:
    url = TRMF_ENDPOINT.format(hotel_id=int(live["hotel_id"]), night=night)
    return parse_trmf(http_get_json(url))


SOURCES = {"trmf": fetch_trmf}


# --------------------------------------------------------------------------- planning

def nights_to_refresh(today: dt.date, full: bool, known: set[str]) -> list[str]:
    """Near nights every run; far nights on a weekly rotation; anything never seen."""
    out = []
    for offset in range(HORIZON_NIGHTS):
        night = today + dt.timedelta(days=offset)
        iso = night.isoformat()
        due = (
            full
            or offset < NEAR_NIGHTS
            or night.toordinal() % FAR_CYCLE_DAYS == today.toordinal() % FAR_CYCLE_DAYS
            or iso not in known
        )
        if due:
            out.append(iso)
    return out


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


def describe_change(old: dict | None, new: dict) -> str | None:
    if old is None:
        return None  # first sighting is not a change
    if old.get("a") == 1 and new.get("a") == 0:
        return "sold_out_or_closed"
    if old.get("a") == 0 and new.get("a") == 1:
        return "opened"
    return None


def run(args, fetchers=None, today: dt.date | None = None, sleep=time.sleep) -> dict:
    fetchers = SOURCES if fetchers is None else fetchers
    today = today or dt.datetime.now(dt.timezone.utc).date()
    stamp = today.isoformat()
    enabled = {s.strip() for s in (args.sources or "").split(",") if s.strip()}

    props = load_json(PROPERTIES, {"properties": []})["properties"]
    previous = load_json(OUT, {})
    nights: dict[str, dict] = {
        n: recs for n, recs in (previous.get("nights") or {}).items() if n >= stamp
    }

    live_props = [p for p in props if p.get("live") and p["live"].get("source") in enabled
                  and p["live"]["source"] in fetchers]
    summary = {"requested": 0, "ok": 0, "failed": 0, "changes": 0}
    changes: list[list] = []

    for prop in live_props:
        pid, live = prop["id"], prop["live"]
        known = {n for n, recs in nights.items() if pid in recs}
        todo = nights_to_refresh(today, args.full, known)
        if args.limit:
            todo = todo[: args.limit]
        if args.dry_run:
            print(f"{pid}: would request {len(todo)} nights ({todo[0]} to {todo[-1]})" if todo else f"{pid}: nothing due")
            summary["requested"] += len(todo)
            continue
        streak = 0
        for night in todo:
            summary["requested"] += 1
            try:
                rec = fetchers[live["source"]](live, night)
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
                summary["failed"] += 1
                streak += 1
                print(f"  {pid} {night}: {type(exc).__name__}: {exc}", file=sys.stderr)
                if streak >= MAX_CONSECUTIVE_FAILURES:
                    print(f"  {pid}: {streak} failures in a row, skipping the rest of this property", file=sys.stderr)
                    break
                sleep(DELAY_SECONDS * 3)
                continue
            streak = 0
            summary["ok"] += 1
            rec["t"] = stamp
            old = nights.get(night, {}).get(pid)
            change = describe_change(old, rec)
            if change:
                changes.append([stamp, night, pid, change])
            nights.setdefault(night, {})[pid] = rec
            sleep(DELAY_SECONDS)
        print(f"{pid}: {len(todo)} nights checked")

    summary["changes"] = len(changes)
    if args.dry_run:
        return summary

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "horizon_nights": HORIZON_NIGHTS,
        "basis": "Whether a one-night stay for two adults could be booked when checked. Rates are not collected.",
        "sources_enabled": sorted(enabled),
        "properties": [p for p in props if p.get("public", True)],
        "nights": {n: nights[n] for n in sorted(nights) if nights[n]},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    append_changes(changes)
    print(json.dumps(summary))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="refresh every night in the horizon")
    ap.add_argument("--dry-run", action="store_true", help="plan only; no network and no writes")
    ap.add_argument("--limit", type=int, default=0, help="cap nights per property (testing)")
    ap.add_argument("--sources", default=os.environ.get("LODGING_SOURCES", ""),
                    help="comma-separated live sources to query (default: $LODGING_SOURCES)")
    args = ap.parse_args(argv)
    summary = run(args)
    # A run where every request failed should fail the workflow so someone looks.
    if summary["requested"] and not summary["ok"] and not args.dry_run:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
