"""Offline tests for the collector. Run: python -m unittest discover -s tests

No test touches the network: collect.http_json is replaced with a router over canned responses.
The Google Hotels, Guesty and Apify shapes follow those services' published documentation.
"""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))
import collect  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 10, 5)


def args(**kw):
    base = dict(full=False, dry_run=False, check=False, limit=0, sources="")
    base.update(kw)
    return SimpleNamespace(**base)


def make_run(**kw):
    return collect.Run(TODAY, args(**kw), {}, {}, sleep=lambda s: None, env=kw.pop("env", {}) if "env" in kw else {})


class Sandbox(unittest.TestCase):
    """Points the collector at a temp folder and swaps in a fake http_json."""

    PROPS: list = []

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "properties.json").write_text(json.dumps({"properties": self.PROPS}))
        self._saved = (collect.PROPERTIES, collect.OUT, collect.CHANGES, collect.GUESTY_TOKEN_CACHE, collect.http_json)
        collect.PROPERTIES = tmp / "properties.json"
        collect.OUT = tmp / "out.json"
        collect.CHANGES = tmp / "changes.csv"
        collect.GUESTY_TOKEN_CACHE = tmp / "token.json"
        self.calls = []
        collect.http_json = self.http

    def tearDown(self):
        (collect.PROPERTIES, collect.OUT, collect.CHANGES, collect.GUESTY_TOKEN_CACHE, collect.http_json) = self._saved
        self.tmp.cleanup()

    def http(self, method, url, headers=None, json_body=None, form=None):
        self.calls.append((method, url, headers or {}, json_body, form))
        return self.respond(method, url, headers or {}, json_body, form)

    def respond(self, method, url, headers, json_body, form):
        raise AssertionError(f"unexpected request to {url}")

    def out(self):
        return json.loads(collect.OUT.read_text())


# ----------------------------------------------------------------------------- trmf

class TrmfParse(unittest.TestCase):
    def test_available_keeps_no_rate(self):
        rec = collect.parse_trmf(json.loads((FIX / "available.json").read_text()))
        self.assertEqual(rec, {"a": 1, "q": 1})

    def test_unavailable(self):
        self.assertEqual(collect.parse_trmf(json.loads((FIX / "unavailable.json").read_text())), {"a": 0})

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            collect.parse_trmf({"hello": "world"})


class TrmfRun(Sandbox):
    PROPS = [{"id": "h", "name": "H", "public": True, "live": {"source": "trmf", "hotel_id": 62704}},
             {"id": "plain", "name": "Plain", "public": True},
             {"id": "hidden", "name": "Hidden", "public": False}]
    open_ = True

    def respond(self, method, url, headers, json_body, form):
        self.assertIn("/hotel/62704/arrival/", url)
        return {"available": 1, "price": 100} if self.open_ else {"available": False, "errors": [1]}

    def test_writes_prunes_logs_changes_and_never_stores_rates(self):
        collect.run(args(sources="trmf", limit=3), today=TODAY, sleep=lambda s: None, env={})
        out = self.out()
        self.assertEqual([p["id"] for p in out["properties"]], ["h", "plain"])
        self.assertEqual(sorted(out["nights"]), ["2026-10-05", "2026-10-06", "2026-10-07"])
        self.assertEqual(out["nights"]["2026-10-05"]["h"], {"a": 1, "t": "2026-10-05"})
        self.assertNotIn("100", collect.OUT.read_text())
        self.assertFalse(collect.CHANGES.exists())

        self.open_ = False
        collect.run(args(sources="trmf", limit=3), today=TODAY + dt.timedelta(days=1), sleep=lambda s: None, env={})
        out = self.out()
        self.assertNotIn("2026-10-05", out["nights"])
        self.assertEqual(out["nights"]["2026-10-06"]["h"]["a"], 0)
        rows = collect.CHANGES.read_text().strip().splitlines()
        self.assertEqual(rows[0], "checked,night,property,change")
        self.assertEqual(rows[1], "2026-10-06,2026-10-06,h,sold_out_or_closed")

    def test_disabled_source_makes_no_requests(self):
        collect.run(args(sources=""), today=TODAY, sleep=lambda s: None, env={})
        self.assertEqual(self.calls, [])
        self.assertTrue(collect.OUT.exists())

    def test_failures_keep_old_values_and_do_not_mark_checked(self):
        collect.run(args(sources="trmf", limit=2), today=TODAY, sleep=lambda s: None, env={})

        def boom(*a, **k):
            raise collect.HttpError("HTTP 500 from bookings.medora.com")
        collect.http_json = boom
        collect.run(args(sources="trmf", limit=2, full=True), today=TODAY, sleep=lambda s: None, env={})
        out = self.out()
        self.assertEqual(out["nights"]["2026-10-06"]["h"]["a"], 1)
        self.assertEqual(out["checked"]["trmf"]["2026-10-06"], "2026-10-05")


class Planning(unittest.TestCase):
    def test_first_run_checks_whole_horizon_then_rotates(self):
        run = make_run()
        self.assertEqual(len(run.due("trmf")), collect.SETTINGS["trmf"]["horizon"])
        for night in run.horizon("trmf"):
            run.mark("trmf", night)
        cfg = collect.SETTINGS["trmf"]
        far = cfg["horizon"] - cfg["near"]
        self.assertIn(len(run.due("trmf")), (cfg["near"] + far // cfg["cycle"], cfg["near"] + far // cfg["cycle"] + 1))

    def test_google_horizon_is_shorter(self):
        self.assertEqual(len(make_run().due("google_hotels")), collect.SETTINGS["google_hotels"]["horizon"])


# ----------------------------------------------------------------------------- google hotels

GOOGLE_PAGE = {
    "properties": [
        {"type": "hotel", "name": "Hampton Inn & Suites Dickinson",
         "price_per_night": {"price": "$201", "extracted_price": 201}},
        {"type": "hotel", "name": "AmericInn by Wyndham Dickinson"},  # listed, no rate
        {"type": "hotel", "name": "Holiday Inn Express & Suites Dickinson by IHG",
         "total_price": {"price": "$174", "extracted_price": 174}},
    ],
    "pagination": {"records_from": 1, "records_to": 20},
}


class GoogleHotels(Sandbox):
    PROPS = [
        {"id": "hampton", "name": "Hampton", "public": True, "live": {"source": "google_hotels", "query": "dickinson", "match": "hampton"}},
        {"id": "americinn", "name": "AmericInn", "public": True, "live": {"source": "google_hotels", "query": "dickinson", "match": "americinn"}},
        {"id": "hie", "name": "HIE", "public": True, "live": {"source": "google_hotels", "query": "dickinson", "match": "holiday inn express"}},
        {"id": "dinn", "name": "Dickinson Inn", "public": True, "live": {"source": "google_hotels", "query": "dickinson", "match": "dickinson inn"}},
    ]

    def respond(self, method, url, headers, json_body, form):
        self.assertTrue(url.startswith("https://www.searchapi.io/api/v1/search?"))
        self.assertEqual(headers.get("Authorization"), "Bearer KEY")
        self.assertNotIn("KEY", url)  # the key travels in a header, never the URL
        self.assertIn("engine=google_hotels", url)
        return GOOGLE_PAGE

    def test_priced_is_open_everything_else_unknown(self):
        collect.run(args(sources="google_hotels", limit=1), today=TODAY, sleep=lambda s: None, env={"SEARCHAPI_KEY": "KEY"})
        night = self.out()["nights"]["2026-10-05"]
        self.assertEqual(night, {"hampton": {"a": 1, "t": "2026-10-05"}, "hie": {"a": 1, "t": "2026-10-05"}})
        self.assertNotIn("201", collect.OUT.read_text())

    def test_a_hotel_that_loses_its_rate_is_cleared_not_left_open(self):
        collect.run(args(sources="google_hotels", limit=1), today=TODAY, sleep=lambda s: None, env={"SEARCHAPI_KEY": "KEY"})
        self.respond = lambda *a, **k: {"properties": [{"name": "Hampton Inn & Suites Dickinson"}]}
        collect.run(args(sources="google_hotels", limit=1, full=True), today=TODAY, sleep=lambda s: None, env={"SEARCHAPI_KEY": "KEY"})
        self.assertNotIn("2026-10-05", self.out()["nights"])

    def test_missing_key_skips_without_requests(self):
        summary = collect.run(args(sources="google_hotels", limit=1), today=TODAY, sleep=lambda s: None, env={})
        self.assertEqual(self.calls, [])
        self.assertTrue(summary["sources"]["google_hotels"]["note"].startswith("skipped"))

    def test_name_matching_does_not_cross_wires(self):
        results = [{"name": "Hampton Inn & Suites Dickinson", "price_per_night": {"extracted_price": 1}}]
        self.assertIsNone(collect.match_google(results, self.PROPS)["dinn"])


# ----------------------------------------------------------------------------- guesty

class GuestyParse(unittest.TestCase):
    def test_status_list(self):
        cal = collect.parse_guesty_calendar([
            {"date": "2026-10-05", "status": "available", "minNights": 2},
            {"date": "2026-10-06", "status": "booked"},
            {"date": "2026-10-07", "status": "unavailable"}])
        self.assertEqual(cal, {"2026-10-05": True, "2026-10-06": False, "2026-10-07": False})

    def test_wrapped_and_boolean(self):
        cal = collect.parse_guesty_calendar({"data": {"days": [{"date": "2026-10-05T00:00:00Z", "available": True}]}})
        self.assertEqual(cal, {"2026-10-05": True})

    def test_unknown_shape_raises(self):
        with self.assertRaises(ValueError):
            collect.parse_guesty_calendar({"message": "nope"})
        with self.assertRaises(ValueError):
            collect.parse_guesty_calendar([{"date": "2026-10-05"}])


class Guesty(Sandbox):
    PROPS = [
        {"id": "boots", "name": "Boots", "public": True, "live": {"source": "guesty", "city": "Medora", "title_contains": "boots"}},
        {"id": "crossings", "name": "Crossings", "public": True, "live": {"source": "guesty", "city": "Belfield", "default": True}},
    ]
    ENV = {"GUESTY_CLIENT_ID": "id", "GUESTY_CLIENT_SECRET": "secret"}

    def respond(self, method, url, headers, json_body, form):
        if url == collect.GUESTY_TOKEN_URL:
            self.assertEqual(form["grant_type"], "client_credentials")
            self.assertEqual(form["scope"], "booking_engine:api")
            return {"token_type": "Bearer", "expires_in": 86400, "access_token": "TOK"}
        self.assertEqual(headers.get("Authorization"), "Bearer TOK")
        if "/listings?" in url:
            return {"results": [
                {"_id": "b2", "title": "Boots Cowboy Cabin"},
                {"_id": "b1", "title": "Boots House", "address": {"city": "Medora"}},
                {"_id": "c1", "title": "Wild Horse Cabin", "address": {"city": "Belfield"}},
                {"_id": "c2", "title": "Cozy House"}],
                "pagination": {"total": 4}}
        listing = url.split("/listings/")[1].split("/")[0]
        start = dt.date.fromisoformat(url.split("from=")[1][:10])
        end = dt.date.fromisoformat(url.split("to=")[1][:10])
        days = []
        while start <= end:
            iso = start.isoformat()
            # b1 is booked on the first night; b2 always open; c1 never open; c2's calendar fails
            status = "booked" if (listing == "b1" and iso == "2026-10-05") or listing == "c1" else "available"
            days.append({"date": iso, "status": status})
            start += dt.timedelta(days=1)
        if listing == "c2":
            raise collect.HttpError("HTTP 500 from booking.guesty.com")
        return days

    def test_groups_units_and_writes_bitstrings(self):
        collect.run(args(sources="guesty"), today=TODAY, sleep=lambda s: None, env=self.ENV)
        nights = self.out()["nights"]
        self.assertEqual(nights["2026-10-05"]["boots"], {"a": 1, "u": "01", "of": 2, "t": "2026-10-05"})
        self.assertEqual(nights["2026-10-06"]["boots"]["u"], "11")
        self.assertEqual(nights["2026-10-05"]["crossings"], {"a": 0, "u": "00", "of": 2, "t": "2026-10-05"})
        self.assertEqual(len(nights), collect.SETTINGS["guesty"]["horizon"])

    def test_token_is_cached_between_runs(self):
        collect.run(args(sources="guesty"), today=TODAY, sleep=lambda s: None, env=self.ENV)
        collect.run(args(sources="guesty"), today=TODAY, sleep=lambda s: None, env=self.ENV)
        self.assertEqual(sum(1 for c in self.calls if c[1] == collect.GUESTY_TOKEN_URL), 1)
        self.assertNotIn("secret", collect.OUT.read_text())

    def test_missing_credentials_skip(self):
        summary = collect.run(args(sources="guesty"), today=TODAY, sleep=lambda s: None, env={})
        self.assertEqual(self.calls, [])
        self.assertIn("skipped", summary["sources"]["guesty"]["note"])


# ----------------------------------------------------------------------------- apify

class Apify(Sandbox):
    PROPS = [
        {"id": "airbnb", "name": "Airbnb", "public": True, "live": {"source": "airbnb", "listings": ["111", "222", "333"]}},
        {"id": "vrbo", "name": "Vrbo", "public": True, "live": {"source": "vrbo", "start": ["bbox:1,2,3,4"], "exclude": ["skip"], "max_items": 10}},
    ]
    status = "SUCCEEDED"

    def respond(self, method, url, headers, json_body, form):
        self.assertEqual(headers.get("Authorization"), "Bearer TOKEN")
        self.assertNotIn("TOKEN", url)
        if method == "POST" and "/acts/cirkit~airbnb-availability-scraper/runs" in url:
            self.assertEqual(json_body, {"listingIds": ["111", "222", "333"], "months": 12})
            return {"data": {"id": "runA", "status": "RUNNING", "defaultDatasetId": "dsA"}}
        if method == "POST" and "/acts/memo23~vrbo-scraper/runs" in url:
            self.assertEqual(json_body["startUrls"], ["bbox:1,2,3,4"])
            self.assertTrue(json_body["scrapeAvailability"])
            return {"data": {"id": "runV", "status": self.status, "defaultDatasetId": "dsV"}}
        if "/actor-runs/runA" in url:
            return {"data": {"id": "runA", "status": self.status, "defaultDatasetId": "dsA"}}
        if "/datasets/dsA/items" in url:
            return [
                {"listingId": "111", "days": [{"calendarDate": "2026-10-05", "available": True, "priceFormatted": "$410"},
                                              {"calendarDate": "2026-10-06", "available": False}]},
                {"listingId": "222", "days": [{"calendarDate": "2026-10-05", "available": False},
                                              {"calendarDate": "2026-10-06", "available": False}]},
                {"listingId": "333", "error": "blocked", "days": []}]
        if "/datasets/dsV/items" in url:
            return [
                {"kind": "property", "vrboId": "v2", "calendar": [{"date": "2026-10-05", "available": True, "pricePerNight": 300}]},
                {"kind": "property", "vrboId": "v1", "calendar": [{"date": "2026-10-05", "available": False}]},
                {"kind": "property", "vrboId": "skip", "calendar": [{"date": "2026-10-05", "available": True}]},
                {"kind": "review", "reviewId": "r"}]
        raise AssertionError(url)

    def test_airbnb_calendars(self):
        collect.run(args(sources="airbnb"), today=TODAY, sleep=lambda s: None, env={"APIFY_TOKEN": "TOKEN"})
        nights = self.out()["nights"]
        self.assertEqual(nights["2026-10-05"]["airbnb"], {"a": 1, "u": "100", "of": 3, "t": "2026-10-05"})
        self.assertEqual(nights["2026-10-06"]["airbnb"]["a"], 0)
        self.assertEqual(sorted(nights), ["2026-10-05", "2026-10-06"])
        self.assertNotIn("410", collect.OUT.read_text())

    def test_airbnb_batches_every_property_into_one_run(self):
        props = json.loads(collect.PROPERTIES.read_text())
        props["properties"].append({"id": "cabins", "name": "Cabins", "public": True,
                                    "live": {"source": "airbnb", "listings": ["222", "444"]}})
        collect.PROPERTIES.write_text(json.dumps(props))
        original = self.respond

        def respond(method, url, headers, json_body, form):
            if method == "POST" and "airbnb-availability-scraper" in url:
                self.assertEqual(json_body["listingIds"], ["111", "222", "333", "444"])
                return {"data": {"id": "runA", "status": "RUNNING", "defaultDatasetId": "dsA"}}
            return original(method, url, headers, json_body, form)
        self.respond = respond
        summary = collect.run(args(sources="airbnb"), today=TODAY, sleep=lambda s: None, env={"APIFY_TOKEN": "TOKEN"})
        self.assertEqual(sum(1 for c in self.calls if c[0] == "POST"), 1)
        night = self.out()["nights"]["2026-10-05"]
        self.assertEqual(night["airbnb"]["u"], "100")
        self.assertEqual(night["cabins"], {"a": 0, "u": "00", "of": 2, "t": "2026-10-05"})
        self.assertIn("cabins: 1 of 2 listings returned no calendar", summary["sources"]["airbnb"]["note"])

    def test_vrbo_calendars_sorted_and_excluded(self):
        collect.run(args(sources="vrbo"), today=TODAY, sleep=lambda s: None, env={"APIFY_TOKEN": "TOKEN"})
        self.assertEqual(self.out()["nights"]["2026-10-05"]["vrbo"], {"a": 1, "u": "01", "of": 2, "t": "2026-10-05"})

    def test_failed_run_writes_nothing_and_reports(self):
        self.status = "FAILED"
        summary = collect.run(args(sources="airbnb,vrbo"), today=TODAY, sleep=lambda s: None, env={"APIFY_TOKEN": "TOKEN"})
        self.assertEqual(self.out()["nights"], {})
        self.assertIn("failed", summary["sources"]["airbnb"]["note"])
        self.assertFalse(summary["sources"]["vrbo"]["ok"])


class EnvFile(unittest.TestCase):
    def test_loads_without_overriding(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# comment\nLODGING_TEST_A=one\nLODGING_TEST_B=\"two\"\nLODGING_TEST_EMPTY=\nnot a line\n")
            os.environ["LODGING_TEST_A"] = "already"
            try:
                collect.load_env(path)
                self.assertEqual(os.environ["LODGING_TEST_A"], "already")
                self.assertEqual(os.environ["LODGING_TEST_B"], "two")
                self.assertNotIn("LODGING_TEST_EMPTY", os.environ)
            finally:
                os.environ.pop("LODGING_TEST_A", None)
                os.environ.pop("LODGING_TEST_B", None)


class RealPropertyFile(unittest.TestCase):
    def test_live_blocks_are_well_formed(self):
        props = json.loads((ROOT / "data" / "properties.json").read_text())["properties"]
        ids = [p["id"] for p in props]
        self.assertEqual(len(ids), len(set(ids)))
        for p in props:
            live = p.get("live")
            if not live:
                continue
            self.assertIn(live["source"], collect.SOURCES, p["id"])
            if live["source"] == "google_hotels":
                self.assertIn(live["query"], collect.GOOGLE_QUERIES, p["id"])
                self.assertTrue(live["match"], p["id"])
            if live["source"] == "trmf":
                self.assertIsInstance(live["hotel_id"], int)
        airbnb_ids = [i for p in props if (p.get("live") or {}).get("source") == "airbnb" for i in p["live"]["listings"]]
        self.assertEqual(len(airbnb_ids), len(set(airbnb_ids)), "an Airbnb listing is assigned to two properties")


if __name__ == "__main__":
    unittest.main()
