"""Offline tests for the collector. Run: python -m unittest discover -s tests"""
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


class ParseTests(unittest.TestCase):
    def test_available(self):
        rec = collect.parse_trmf(json.loads((FIX / "available.json").read_text()))
        self.assertEqual(rec, {"a": 1, "q": 1})  # no rate, no room name

    def test_unavailable(self):
        rec = collect.parse_trmf(json.loads((FIX / "unavailable.json").read_text()))
        self.assertEqual(rec, {"a": 0})

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            collect.parse_trmf({"hello": "world"})


class PlanTests(unittest.TestCase):
    def test_full_covers_horizon(self):
        today = dt.date(2026, 10, 5)
        nights = collect.nights_to_refresh(today, True, set())
        self.assertEqual(len(nights), collect.HORIZON_NIGHTS)
        self.assertEqual(nights[0], "2026-10-05")

    def test_daily_is_near_plus_a_seventh(self):
        today = dt.date(2026, 10, 5)
        known = {(today + dt.timedelta(days=i)).isoformat() for i in range(collect.HORIZON_NIGHTS)}
        nights = collect.nights_to_refresh(today, False, known)
        far = collect.HORIZON_NIGHTS - collect.NEAR_NIGHTS
        self.assertGreaterEqual(len(nights), collect.NEAR_NIGHTS + far // collect.FAR_CYCLE_DAYS)
        self.assertLessEqual(len(nights), collect.NEAR_NIGHTS + far // collect.FAR_CYCLE_DAYS + 1)

    def test_every_far_night_is_hit_within_a_cycle(self):
        start = dt.date(2026, 10, 5)
        known = {(start + dt.timedelta(days=i)).isoformat() for i in range(collect.HORIZON_NIGHTS + 10)}
        target = (start + dt.timedelta(days=200)).isoformat()
        hits = sum(target in collect.nights_to_refresh(start + dt.timedelta(days=d), False, known)
                   for d in range(collect.FAR_CYCLE_DAYS))
        self.assertEqual(hits, 1)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.props = tmp / "properties.json"
        self.props.write_text(json.dumps({"properties": [
            {"id": "a", "name": "A", "public": True, "live": {"source": "fake", "hotel_id": 1}},
            {"id": "b", "name": "B", "public": True},
            {"id": "c", "name": "C", "public": False},
        ]}))
        self._saved = (collect.PROPERTIES, collect.OUT, collect.CHANGES)
        collect.PROPERTIES, collect.OUT, collect.CHANGES = self.props, tmp / "out.json", tmp / "changes.csv"

    def tearDown(self):
        collect.PROPERTIES, collect.OUT, collect.CHANGES = self._saved
        self.tmp.cleanup()

    def args(self, **kw):
        base = dict(full=False, dry_run=False, limit=3, sources="fake")
        base.update(kw)
        return SimpleNamespace(**base)

    def test_writes_prunes_and_logs_changes(self):
        day1 = dt.date(2026, 10, 5)
        calls = []

        def open_fetch(live, night):
            calls.append(night)
            return {"a": 1}

        collect.run(self.args(), fetchers={"fake": open_fetch}, today=day1, sleep=lambda s: None)
        out = json.loads(collect.OUT.read_text())
        self.assertEqual([p["id"] for p in out["properties"]], ["a", "b"])  # non-public dropped
        self.assertEqual(sorted(out["nights"]), ["2026-10-05", "2026-10-06", "2026-10-07"])
        self.assertEqual(out["nights"]["2026-10-05"]["a"], {"a": 1, "t": "2026-10-05"})
        self.assertFalse(collect.CHANGES.exists())  # first sighting is not a change

        def sold_fetch(live, night):
            return {"a": 0}

        collect.run(self.args(), fetchers={"fake": sold_fetch}, today=day1 + dt.timedelta(days=1), sleep=lambda s: None)
        out = json.loads(collect.OUT.read_text())
        self.assertNotIn("2026-10-05", out["nights"])  # past night pruned
        self.assertEqual(out["nights"]["2026-10-06"]["a"]["a"], 0)
        rows = collect.CHANGES.read_text().strip().splitlines()
        self.assertEqual(rows[0], "checked,night,property,change")
        self.assertEqual(rows[1], "2026-10-06,2026-10-06,a,sold_out_or_closed")

    def test_failures_keep_old_values(self):
        day1 = dt.date(2026, 10, 5)
        collect.run(self.args(), fetchers={"fake": lambda l, n: {"a": 1}}, today=day1, sleep=lambda s: None)

        def boom(live, night):
            raise ValueError("bad payload")

        summary = collect.run(self.args(), fetchers={"fake": boom}, today=day1, sleep=lambda s: None)
        self.assertEqual(summary["ok"], 0)
        out = json.loads(collect.OUT.read_text())
        self.assertEqual(out["nights"]["2026-10-06"]["a"]["a"], 1)

    def test_disabled_source_makes_no_requests(self):
        def never(live, night):
            raise AssertionError("should not be called")

        summary = collect.run(self.args(sources=""), fetchers={"fake": never}, today=dt.date(2026, 10, 5),
                              sleep=lambda s: None)
        self.assertEqual(summary["requested"], 0)
        self.assertTrue(collect.OUT.exists())


if __name__ == "__main__":
    unittest.main()
