import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.services.takeout_filter import classify, load_records, run_import


def sample(**changes):
    record = {
        "header": "YouTube Music", "title": "예시 곡 을(를) 시청했습니다.",
        "titleUrl": "https://music.youtube.com/watch?v=abcdefghijk",
        "time": "2026-11-07T03:00:00.123+09:00",
        "products": ["YouTube"],
        "subtitles": [{"name": "예시 채널", "url": "https://www.youtube.com/channel/example"}],
    }
    record.update(changes)
    return record


class ClassificationTests(unittest.TestCase):
    def test_valid_watch_and_normalization(self):
        r = sample()
        original = copy.deepcopy(r)
        out = classify(r)
        self.assertEqual(out["status"], "accepted")
        self.assertEqual(out["event"]["played_at"], "2026-11-06T18:00:00.123000Z")
        self.assertEqual(out["event"]["display_title"], "예시 곡")
        self.assertIsNone(out["event"]["listened_ms"])
        self.assertNotIn("artist", out["event"])
        self.assertEqual(r, original)

    def test_equivalent_times_and_urls_share_key(self):
        a = classify(sample())["event"]
        b = classify(sample(time="2026-11-06T18:00:00.123Z",
                            titleUrl="https://music.youtube.com/watch?list=example&v=abcdefghijk"))["event"]
        self.assertEqual(a["source_event_key"], b["source_event_key"])
        c = classify(sample(time="2026-11-06T18:00:00.124Z"))["event"]
        self.assertNotEqual(a["source_event_key"], c["source_event_key"])

    def test_regular_youtube_excluded(self):
        self.assertEqual(classify(sample(header="YouTube"))["reason"], "not_youtube_music")

    def test_search_and_playlist_excluded(self):
        for host, endpoint, reason in (
            ("www.youtube.com", "results?search_query=music", "search_activity"),
            ("music.youtube.com", "playlist?list=example", "playlist_activity"),
        ):
            with self.subTest(endpoint=endpoint):
                result = classify(sample(titleUrl=f"https://{host}/{endpoint}"))
                self.assertEqual((result["status"], result["reason"]), ("excluded", reason))

    def test_unknown_action_and_missing_url_reviewed(self):
        for changes in ({"title": "非標準 action"}, {"titleUrl": None}, {"title": ""},
                        {"title": "Searched for example"}):
            with self.subTest(changes=changes):
                self.assertEqual(classify(sample(**changes))["status"], "review")

    def test_untrusted_hosts_or_credentials_never_accepted(self):
        for url in ("https://music.youtube.com.evil.test/watch?v=abcdefghijk",
                    "https://music.youtube.com@evil.test/watch?v=abcdefghijk",
                    "https://user@music.youtube.com/watch?v=abcdefghijk",
                    "http://music.youtube.com/watch?v=abcdefghijk",
                    "https://music.youtube.com:444/watch?v=abcdefghijk",
                    "https://www.youtube.com/watch?v=abcdefghijk"):
            with self.subTest(url=url):
                self.assertEqual(classify(sample(titleUrl=url))["status"], "review")

    def test_invalid_video_ids_rejected(self):
        for query in ("", "?v=", "?v=short", "?v=abcdefghijk&v=abcdefghijl"):
            with self.subTest(query=query):
                self.assertEqual(classify(sample(titleUrl="https://music.youtube.com/watch"+query))["reason"],
                                 "missing_or_invalid_video_id")

    def test_bad_times_rejected_without_truncation(self):
        for value in (None, "2026-11-07", "2026-11-07T03:00:00", "2026-02-30T03:00:00Z",
                      "2026-11-07T03:00:00.1234567Z", "2026-11-07T03:00:00+01:99"):
            with self.subTest(value=value):
                self.assertEqual(classify(sample(time=value))["reason"], "missing_or_invalid_time")

    def test_null_or_wrong_types(self):
        self.assertEqual(classify(None)["status"], "error")
        self.assertEqual(classify({})["status"], "error")
        self.assertEqual(classify(sample(titleUrl=3))["status"], "error")
        self.assertEqual(classify(sample(titleUrl="https://["))["status"], "error")
        self.assertEqual(classify(sample(titleUrl="\x00https://music.youtube.com/watch?v=abcdefghijk"))["status"], "error")
        self.assertEqual(classify(sample(subtitles=None))["status"], "review")

    def test_english_title_and_optional_channel(self):
        out = classify(sample(title="Watched Example Song", subtitles=[]))
        self.assertEqual(out["event"]["display_title"], "Example Song")
        self.assertEqual(out["event"]["channels"], [])


class InputAndOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, rows):
        p = self.root / "source.json"
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8-sig")
        return p

    def test_status_counts_and_duplicate_preservation(self):
        p = self.write_json([sample(), sample(), sample(header="YouTube"),
                             sample(title="uncertain"), sample(time="bad")])
        out = self.root / "result"
        summary = run_import(p, out)
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["counts"], {"accepted": 2, "excluded": 1, "review": 1, "error": 1})
        self.assertEqual(summary["repeated_accepted_event_keys"], 1)
        lines = (out / "accepted.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["source_index"], 0)
        self.assertTrue((out / "review.jsonl").exists())
        self.assertTrue((out / "errors.jsonl").exists())
        self.assertFalse((out / "excluded.jsonl").exists())

    def test_existing_output_is_not_overwritten(self):
        p = self.write_json([sample()])
        out = self.root / "result"
        run_import(p, out)
        with self.assertRaises(FileExistsError):
            run_import(p, out)

    def test_zip_member_selected_without_extraction(self):
        p = self.root / "archive.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("../outside.json", json.dumps([sample()]))
            z.writestr("other.json", "[]")
        with self.assertRaises(ValueError):
            load_records(p)
        records, metadata = load_records(p, member="../outside.json")
        self.assertEqual(len(records), 1)
        self.assertEqual(metadata["member"], "../outside.json")
        self.assertFalse((self.root.parent / "outside.json").exists())

    def test_malformed_json_never_publishes_results(self):
        p = self.root / "bad.json"
        for content in ('[{', '{}', '[NaN]', '[{"a":1,"a":2}]'):
            with self.subTest(content=content):
                p.write_text(content, encoding="utf-8")
                out = self.root / "result"
                with self.assertRaises(ValueError):
                    run_import(p, out)
                self.assertFalse(out.exists())

    def test_limits(self):
        p = self.write_json([sample(), sample()])
        with self.assertRaises(ValueError):
            load_records(p, max_bytes=10)
        with self.assertRaises(ValueError):
            load_records(p, max_items=1)
        zpath = self.root / "large.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("large.json", p.read_bytes())
        with self.assertRaises(ValueError):
            load_records(zpath, max_bytes=10)

    def test_same_data_zip_and_json_has_same_hash(self):
        p = self.write_json([sample()])
        zpath = self.root / "same.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("history.json", p.read_bytes())
        self.assertEqual(load_records(p)[1]["json_sha256"], load_records(zpath)[1]["json_sha256"])


if __name__ == "__main__":
    unittest.main()
