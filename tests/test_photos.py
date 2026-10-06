"""Offline tests for collector/photos.py. No network: page and image lookups are faked."""
import datetime as dt
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))
import photos  # noqa: E402

TODAY = dt.date(2026, 10, 6)


def args(**kw):
    base = dict(all=False, only="", max_age_days=7, no_google=False)
    base.update(kw)
    return SimpleNamespace(**base)


def png(w, h):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", w, h) + b"\x00" * 8


class Sizes(unittest.TestCase):
    def test_reads_png_gif_and_jpeg_sizes(self):
        self.assertEqual(photos.image_size(png(1200, 630)), (1200, 630))
        self.assertEqual(photos.image_size(b"GIF89a" + struct.pack("<HH", 640, 480)), (640, 480))
        jpeg = b"\xff\xd8" + b"\xff\xe0\x00\x04\x00\x00" + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 600, 900) + b"\x00" * 12
        self.assertEqual(photos.image_size(jpeg), (900, 600))
        self.assertIsNone(photos.image_size(b"not an image"))

    def test_small_tall_and_banner_images_are_refused(self):
        self.assertTrue(photos.usable((1200, 630)))
        self.assertFalse(photos.usable((300, 225)))     # too small: usually a logo
        self.assertFalse(photos.usable((879, 2128)))    # tall
        self.assertFalse(photos.usable((2000, 400)))    # banner
        self.assertFalse(photos.usable(None))

    def test_generic_file_names_are_refused(self):
        self.assertTrue(photos.looks_generic("https://www.fs.usda.gov/themes/custom/wfs/img/usfs_placeholder.png"))
        self.assertTrue(photos.looks_generic("https://x.example/files/Capitol_Social_Share.jpg"))
        self.assertTrue(photos.looks_generic("https://x.example/img/site-logo.png"))
        self.assertFalse(photos.looks_generic("https://medora.com/wp-content/uploads/2022/03/Elkhorn-Feature-Image.jpg"))


class MetaTags(unittest.TestCase):
    def test_prefers_og_image_and_ignores_other_tags(self):
        parser = photos.MetaImages()
        parser.feed('<head><meta name="twitter:image" content="https://a.example/t.jpg">'
                    '<meta property="og:image" content="https://a.example/o.jpg">'
                    '<meta property="og:title" content="x"><meta property="og:image" content="https://a.example/second.jpg"></head>')
        self.assertEqual(parser.candidates(), ["https://a.example/o.jpg", "https://a.example/t.jpg"])


class Runs(unittest.TestCase):
    PROPS = [
        {"id": "inn", "name": "Inn", "type": "hotel", "url": "https://inn.example/"},
        {"id": "twin-a", "name": "Twin A", "type": "cabin", "url": "https://twins.example/a"},
        {"id": "twin-b", "name": "Twin B", "type": "cabin", "url": "https://twins.example/b"},
        {"id": "chain", "name": "Chain Hotel", "type": "hotel", "url": "https://chain.example/"},
        {"id": "ours", "name": "Ours", "type": "hotel", "url": "https://ours.example/", "photo": "https://trlibrary.example/ours.jpg", "photo_credit": "TRPL"},
        {"id": "never", "name": "Never", "type": "hotel", "url": "https://never.example/", "photo": False},
        {"id": "rentals", "name": "Rentals", "type": "rentals", "url": "https://rentals.example/"},
        {"id": "hidden", "name": "Hidden", "type": "hotel", "url": "https://hidden.example/", "public": False},
        {"id": "phone-only", "name": "Phone only", "type": "hotel"},
    ]
    PAGES = {
        "https://inn.example/": {"src": "https://inn.example/front.jpg", "w": 1200, "h": 630},
        "https://twins.example/a": {"src": "https://twins.example/shared.jpg", "w": 1500, "h": 1125},
        "https://twins.example/b": {"src": "https://twins.example/shared.jpg", "w": 1500, "h": 1125},
        "https://chain.example/": None,
    }
    HINTS = {"chain": {"src": "https://img.example/chain", "name": "Chain Hotel Dickinson"},
             "inn": {"src": "https://img.example/inn", "name": "Inn"}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._saved = (photos.PROPERTIES, photos.OUT, photos.HINTS)
        photos.PROPERTIES, photos.OUT, photos.HINTS = tmp / "properties.json", tmp / "photos.json", tmp / "photo_hints.json"
        photos.PROPERTIES.write_text(json.dumps({"properties": self.PROPS}))
        photos.HINTS.write_text(json.dumps({"hints": self.HINTS}))
        self.fetched, self.checked = [], []

    def tearDown(self):
        photos.PROPERTIES, photos.OUT, photos.HINTS = self._saved
        self.tmp.cleanup()

    def finder(self, page):
        self.fetched.append(page)
        return self.PAGES[page]

    def checker(self, src):
        self.checked.append(src)
        return {"src": src, "w": 800, "h": 600}

    def go(self, today=TODAY, **kw):
        photos.run(args(**kw), today=today, finder=self.finder, checker=self.checker, sleep=lambda s: None)
        return json.loads(photos.OUT.read_text())

    def test_each_kind_of_property(self):
        out = self.go()
        got = out["photos"]
        self.assertEqual(got["inn"]["from"], "preview")                  # its own site wins over Google
        self.assertEqual(got["inn"]["src"], "https://inn.example/front.jpg")
        self.assertEqual(got["chain"], {"src": "https://img.example/chain", "w": 800, "h": 600, "from": "google", "checked": "2026-10-06"})
        self.assertEqual(got["ours"], {"src": "https://trlibrary.example/ours.jpg", "from": "manual", "checked": "2026-10-06", "credit": "TRPL"})
        self.assertNotIn("twin-a", got)                                   # one image, two properties: neither
        self.assertNotIn("twin-b", got)
        for pid in ("never", "rentals", "hidden", "phone-only"):
            self.assertNotIn(pid, got)
        self.assertNotIn("https://hidden.example/", self.fetched)
        self.assertNotIn("https://never.example/", self.fetched)
        self.assertEqual(set(out["misses"]), {"twin-a", "twin-b", "chain"})

    def test_hand_set_photo_is_kept_when_another_page_offers_the_same_image(self):
        self.PAGES = dict(self.PAGES, **{"https://inn.example/": {"src": "https://trlibrary.example/ours.jpg", "w": 800, "h": 600}})
        got = self.go(no_google=True)["photos"]
        self.assertEqual(got["ours"]["from"], "manual")
        self.assertNotIn("inn", got)

    def test_google_can_be_switched_off(self):
        self.assertNotIn("chain", self.go(no_google=True)["photos"])
        self.assertEqual(self.checked, [])

    def test_second_run_the_same_week_fetches_nothing(self):
        self.go()
        before = photos.OUT.read_text()
        self.fetched.clear(); self.checked.clear()
        self.go(today=TODAY + dt.timedelta(days=3))
        self.assertEqual((self.fetched, self.checked), ([], []))
        self.assertEqual(photos.OUT.read_text(), before)                  # no change, so no new commit

    def test_everything_is_looked_at_again_after_a_week(self):
        self.go()
        self.fetched.clear()
        self.go(today=TODAY + dt.timedelta(days=8))
        self.assertEqual(len(self.fetched), 4)

    def test_a_site_that_stops_answering_keeps_its_photo_for_a_while(self):
        self.go()

        def down(page):
            raise TimeoutError("timed out")
        photos.run(args(all=True), today=TODAY + dt.timedelta(days=8), finder=down, checker=self.checker, sleep=lambda s: None)
        self.assertEqual(json.loads(photos.OUT.read_text())["photos"]["inn"]["src"], "https://inn.example/front.jpg")
        photos.run(args(all=True), today=TODAY + dt.timedelta(days=40), finder=down, checker=self.checker, sleep=lambda s: None)
        self.assertEqual(json.loads(photos.OUT.read_text())["photos"]["inn"]["from"], "google")   # falls back once the old one lapses

    def test_generic_preview_is_ignored(self):
        self.PAGES = dict(self.PAGES, **{"https://inn.example/": {"src": "https://inn.example/img/placeholder.png", "w": 800, "h": 600}})
        self.assertEqual(self.go()["photos"]["inn"]["from"], "google")


if __name__ == "__main__":
    unittest.main()
