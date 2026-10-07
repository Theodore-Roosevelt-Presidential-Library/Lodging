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
        self.assertFalse(photos.usable((489, 200)))     # thin banner
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


class PageBody(unittest.TestCase):
    def test_images_are_read_in_page_order_with_lazy_and_srcset_forms(self):
        parser = photos.PageImages()
        parser.feed('<img src="/a.jpg"><img src="data:image/gif;base64,AAAA" data-src="/lazy.jpg">'
                    '<source srcset="/s-400.jpg 400w, /s-1200.jpg 1200w"><img src="/a.jpg"><p>text</p>')
        self.assertEqual(parser.found, ["/a.jpg", "/lazy.jpg", "/s-1200.jpg"])

    def test_page_furniture_is_skipped(self):
        for path in ("/img/menu-stay.png", "/tripadvisor-award.jpg", "/social/facebook.png", "/img/usda-shield.png",
                     "/common/uploads/nps-app-promo.jpg"):
            self.assertTrue(photos.FURNITURE.search(path), path)
        self.assertFalse(photos.FURNITURE.search("/uploads/2024/cabin-porch-sunset.jpg"))

    def test_google_addresses_are_asked_for_a_card_sized_image(self):
        self.assertEqual(photos.google_size("https://lh3.googleusercontent.com/p/ABC=s287-w287-h192-n-k-no-v1"),
                         "https://lh3.googleusercontent.com/p/ABC=w640-h360-n-k-no")
        self.assertEqual(photos.google_size("https://lh3.googleusercontent.com/grass-cs/ABC_def-1"),
                         "https://lh3.googleusercontent.com/grass-cs/ABC_def-1=w640-h360-n-k-no")
        self.assertEqual(photos.google_size("https://inn.example/a.jpg"), "https://inn.example/a.jpg")


class Listings(unittest.TestCase):
    TAGS = {
        "og:title": "Cabin in Medora · ★4.7 · Studio · 4 beds · No bathroom",
        "og:description": "Boots Badlands Cabin Medora ND 2 BR 1 B Sleeps 6",
        "og:image": "https://a0.muscache.com/im/pictures/x/original/abc.jpeg?im_w=720&width=720",
        "twitter:title": "Boots Badlands Cabin - Medora ND - Cabins for Rent in Medora, North Dakota, United States - Airbnb",
    }

    def test_name_summary_and_photo_come_from_the_preview(self):
        got = photos.parse_listing(self.TAGS)
        self.assertEqual(got["name"], "Boots Badlands Cabin - Medora ND")     # a dash inside the name survives
        self.assertEqual(got["summary"], "Cabin in Medora · Studio · 4 beds · No bathroom")
        self.assertTrue(got["src"].startswith("https://a0.muscache.com/"))
        self.assertNotIn("4.7", json.dumps(got))                              # the rating is not kept
        self.assertNotIn("hidden", got)

    def test_low_rating_is_left_out_and_new_listings_are_not(self):
        self.assertTrue(photos.parse_listing(dict(self.TAGS, **{"og:title": "Home in Medora · ★3.2 · 2 beds"}))["hidden"])
        self.assertNotIn("hidden", photos.parse_listing(dict(self.TAGS, **{"og:title": "Home in Medora · ★New · 2 beds"})))

    def test_falls_back_to_the_description_and_gives_up_without_a_name(self):
        self.assertEqual(photos.parse_listing({"og:description": "  Prairie   House "})["name"], "Prairie House")
        self.assertIsNone(photos.parse_listing({"og:title": "Home in Medora"}))

    def test_meta_tags_first_value_wins(self):
        parser = photos.MetaTags()
        parser.feed('<meta property="og:title" content="A &amp; B"><meta property="og:title" content="second"><meta name="Description" content="d">')
        self.assertEqual(parser.tags, {"og:title": "A & B", "description": "d"})


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
        {"id": "camp", "name": "Lone Tree Campground", "type": "camping", "photo_search": "Lone Tree Campground, ND"},
        {"id": "nowhere", "name": "Nowhere Camp", "type": "camping", "photo_search": "Nowhere Camp, ND"},
        {"id": "bnb", "name": "Airbnb rentals", "type": "rentals", "list_units": True, "url": "https://www.airbnb.com/x",
         "live": {"source": "airbnb", "listings": ["11", "22", "33", "44"], "hide": ["44"]}},
        {"id": "grouped", "name": "Grouped cabins", "type": "cabin",
         "live": {"source": "airbnb", "listings": ["55"]}},
    ]
    ROOMS = {
        "https://www.airbnb.com/rooms/11": {"name": "Prairie House", "summary": "Home in Medora · 3 beds", "src": "https://img.example/11.jpg"},
        "https://www.airbnb.com/rooms/22": {"name": "Rough One", "hidden": True},
        "https://www.airbnb.com/rooms/33": None,
        "https://www.airbnb.com/rooms/55": {"name": "Cabin 55", "src": "https://img.example/55.jpg"},
    }
    PLACES = {"Lone Tree Campground, ND": {"src": "https://lh3.googleusercontent.com/p/TREE=w640-h360-n-k-no", "name": "Lone Tree Camp"},
              "Nowhere Camp, ND": None}
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
        self.fetched, self.checked, self.listed, self.searched = [], [], [], []

    def tearDown(self):
        photos.PROPERTIES, photos.OUT, photos.HINTS = self._saved
        self.tmp.cleanup()

    def finder(self, page):
        self.fetched.append(page)
        return self.PAGES[page]

    def checker(self, src):
        self.checked.append(src)
        return {"src": src, "w": 800, "h": 600}

    def lister(self, url, floor):
        self.listed.append(url)
        return self.ROOMS[url]

    def mapper(self, query, key):
        self.assertEqual(key, "KEY")
        self.searched.append(query)
        return self.PLACES[query]

    def go(self, today=TODAY, env=None, **kw):
        photos.run(args(**kw), today=today, finder=self.finder, checker=self.checker, sleep=lambda s: None,
                   lister=self.lister, mapper=self.mapper, env={"SEARCHAPI_KEY": "KEY"} if env is None else env)
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
        self.assertEqual(got["grouped"], {"src": "https://img.example/55.jpg", "from": "listing", "checked": "2026-10-06"})

    def test_hand_set_photo_is_kept_when_another_page_offers_the_same_image(self):
        self.PAGES = dict(self.PAGES, **{"https://inn.example/": {"src": "https://trlibrary.example/ours.jpg", "w": 800, "h": 600}})
        got = self.go(no_google=True)["photos"]
        self.assertEqual(got["ours"]["from"], "manual")
        self.assertNotIn("inn", got)

    def test_airbnb_listings_shown_one_by_one(self):
        got = self.go()["listings"]
        self.assertEqual(got["airbnb:11"], {"name": "Prairie House", "summary": "Home in Medora · 3 beds", "src": "https://img.example/11.jpg", "checked": "2026-10-06"})
        self.assertTrue(got["airbnb:22"]["hidden"])
        self.assertEqual(got["airbnb:33"], {"missing": True, "checked": "2026-10-06"})
        self.assertNotIn("airbnb:44", got)                                  # on the hide list: never fetched
        self.assertNotIn("airbnb:55", got)                                  # that property stays one grouped card
        self.assertEqual(sorted(self.listed), ["https://www.airbnb.com/rooms/11", "https://www.airbnb.com/rooms/22", "https://www.airbnb.com/rooms/33",
                                               "https://www.airbnb.com/rooms/55"])
        self.listed.clear()
        self.go(today=TODAY + dt.timedelta(days=2))
        self.assertEqual(self.listed, [])                                   # nothing is fetched again within the week

    def test_google_maps_is_the_last_resort_and_is_searched_once(self):
        out = self.go()
        self.assertEqual(out["photos"]["camp"], {"src": "https://lh3.googleusercontent.com/p/TREE=w640-h360-n-k-no", "w": 800, "h": 600,
                                                 "from": "maps", "place": "Lone Tree Camp", "checked": "2026-10-06"})
        self.assertNotIn("nowhere", out["photos"])
        self.assertEqual(out["searched"], {"nowhere": "2026-10-06"})
        self.assertEqual(sorted(self.searched), ["Lone Tree Campground, ND", "Nowhere Camp, ND"])
        self.assertNotIn("KEY", photos.OUT.read_text())
        self.searched.clear()
        self.go(today=TODAY + dt.timedelta(days=10))                        # photo still loads: no new search for either
        self.assertEqual(self.searched, [])
        self.go(today=TODAY + dt.timedelta(days=45))                        # a month on, the miss is tried again
        self.assertEqual(self.searched, ["Nowhere Camp, ND"])

    def test_no_key_means_no_map_searches(self):
        out = self.go(env={})
        self.assertNotIn("camp", out["photos"])
        self.assertEqual(self.searched, [])

    def test_google_can_be_switched_off(self):
        got = self.go(no_google=True)["photos"]
        self.assertNotIn("chain", got)
        self.assertNotIn("camp", got)
        self.assertEqual((self.checked, self.searched), ([], []))

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
        photos.run(args(all=True), today=TODAY + dt.timedelta(days=8), finder=down, checker=self.checker, sleep=lambda s: None, lister=self.lister, env={})
        self.assertEqual(json.loads(photos.OUT.read_text())["photos"]["inn"]["src"], "https://inn.example/front.jpg")
        photos.run(args(all=True), today=TODAY + dt.timedelta(days=200), finder=down, checker=self.checker, sleep=lambda s: None, lister=self.lister, env={})
        self.assertEqual(json.loads(photos.OUT.read_text())["photos"]["inn"]["from"], "google")   # falls back once the old one lapses

    def test_generic_preview_is_ignored(self):
        self.PAGES = dict(self.PAGES, **{"https://inn.example/": {"src": "https://inn.example/img/placeholder.png", "w": 800, "h": 600}})
        self.assertEqual(self.go()["photos"]["inn"]["from"], "google")


if __name__ == "__main__":
    unittest.main()
