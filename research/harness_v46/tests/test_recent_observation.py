"""Synthetic transport fixtures; production parsers run in real child processes."""
import hashlib
import importlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


def rows(game):
    result = []
    day = date(2025, 1, 1)
    for index in range(200):
        if index == 100:
            day = date(2026, 1, 1)
        while day.weekday() not in {0, 2, 5}:
            day += timedelta(days=1)
        year, number = (2025, index + 1) if index < 100 else (2026, index - 99)
        issue = str(year * 1000 + number) if game == "SSQ" else f"{year % 100:02d}{number:03d}"
        result.append({"issue": issue, "draw_date": day.isoformat(),
                       "front": [1, 2, 3, 4, 5, 6] if game == "SSQ" else [1, 2, 3, 4, 5],
                       "back": [7] if game == "SSQ" else [6, 7]})
        day += timedelta(days=1)
    return result


def markup(game, records, malformed=False):
    tags = []
    for index, row in enumerate(reversed(records)):
        if game == "DLT":
            number_text = " ".join(f"{n:02d}" for n in row["front"] + row["back"])
            if malformed and index == 0:
                number_text = "BAD_ROW"
            tags.append(f'<tr><td>{row["draw_date"]}</td><td>{row["issue"]}</td><td>{number_text}</td></tr>')
        else:
            front = "".join(f"{n:02d}" for n in row["front"])
            issue = "BAD_ISSUE" if malformed and index == 0 else row["issue"]
            tags.append(f'<tr><td>{issue}</td><td>{row["draw_date"]}</td><td>{front}</td><td>07</td></tr>')
    schema = ('<tr><th>开奖日期</th><th>期号</th><th>开奖号码</th></tr>'
              if game == "DLT" else '<tr><th>synthetic fixture</th></tr>')
    return ('<html><table><thead>' + schema + '</thead><tbody>'
            + "".join(tags) + '</tbody></table></html>').encode()


class RecentObservationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.ro = importlib.import_module("research.harness_v46.recent_observation")
        except ModuleNotFoundError:
            self.fail("bounded raw observation adapter is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "observation"

    def transport(self, game, bodies=None):
        fixture = rows(game)
        bodies = bodies or [markup(game, fixture[100:]), markup(game, fixture[:100])]
        seen = []

        def get(url, **kwargs):
            if kwargs.get("allow_redirects") is not False:
                raise AssertionError("automatic redirects must be disabled")
            seen.append(url)
            body = bodies[len(seen) - 1]
            return SimpleNamespace(status_code=200, url=url,
                                   content=body, iter_content=lambda chunk_size: iter([body]),
                                   close=lambda: None,
                                   headers={"Content-Type": "text/html; charset=utf-8"})
        return get, seen

    def capture(self, game, bodies=None):
        get, seen = self.transport(game, bodies)
        with patch("requests.get", side_effect=get):
            self.ro.capture(game, self.output)
        return json.loads((self.output / "manifest.json").read_text()), seen

    def test_both_games_capture_all_200_and_select_fixed_latest_120(self):
        for game in ("DLT", "SSQ"):
            with self.subTest(game=game):
                self.output = Path(self.temp.name) / game
                manifest, seen = self.capture(game)
                expected = rows(game)
                self.assertEqual(manifest["all_rows"], expected)
                self.assertEqual(manifest["selected_rows"], expected[80:])
                self.assertEqual(len(seen), 2)
                self.assertEqual(manifest["formal_A"], 0)
                self.assertEqual(manifest["decision"], "NO_EDGE")
                self.assertNotIn("target_issue", manifest)
                self.assertNotIn("published_at", manifest)
                before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
                result = self.ro.verify_observation(self.output)
                after = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
                self.assertEqual(result["selected_rows"], expected[80:])
                self.assertEqual(before, after)

    def test_exact_queries_bound_capture_and_shanghai_second_range(self):
        for game in ("SSQ", "DLT"):
            self.output = Path(self.temp.name) / game
            _, seen = self.capture(game)
            query = [parse_qs(urlsplit(url).query) for url in seen]
            if game == "DLT":
                self.assertEqual(query, [{"itemType": ["lo"], "pageIndex": [str(n)], "pageSize": ["100"]} for n in (1, 2)])
            else:
                self.assertEqual(query[0], {"limit": ["100"], "view": ["previous"]})
                self.assertEqual(query[1], {"view": ["previous"], "limit": ["100"],
                                           "start_issue": ["2025001"], "end_issue": ["2026000"]})

    def test_malformed_regex_skipped_row_fails_entire_page(self):
        for game in ("DLT", "SSQ"):
            self.output = Path(self.temp.name) / game
            fixture = rows(game)
            get, seen = self.transport(game, [markup(game, fixture[100:], malformed=True)])
            with patch("requests.get", side_effect=get), self.assertRaisesRegex(
                    Exception, "COVERAGE|PARSE|ROW|JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED"):
                self.ro.capture(game, self.output)
            self.assertEqual(len(seen), 1)
            self.assertFalse((self.output / "manifest.json").exists())

    def test_data_bearing_th_row_is_never_discarded_as_header(self):
        fixture = rows("DLT")
        extra = b"<tr><th>2024-12-30</th><th>24150</th><th>BAD_ROW</th></tr>"
        first = markup("DLT", fixture[100:]).replace(b"</tbody>", extra + b"</tbody>")
        get, _ = self.transport("DLT", [first, markup("DLT", fixture[:100])])
        with patch("requests.get", side_effect=get), self.assertRaisesRegex(
                Exception, "COVERAGE|ROW|HEADER|JIANGSU_DRAW_DATE_COLUMN_UNVERIFIED"):
            self.ro.capture("DLT", self.output)
        self.assertFalse((self.output / "manifest.json").exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended paths")
    def test_windows_long_output_directory_captures_and_replays(self):
        self.addCleanup(lambda: shutil.rmtree(self.ro.oi._physical_root(self.temp.name), ignore_errors=True))
        self.output = Path(self.temp.name) / ("a" * 100) / ("b" * 100) / ("c" * 80) / "observation"
        self.assertGreater(len(str(self.output)), 315)
        get, _ = self.transport("DLT")
        with patch("requests.get", side_effect=get):
            result = self.ro.capture("DLT", self.output)
        self.assertEqual(self.ro.verify_observation(self.output)["selected_rows"], rows("DLT")[80:])
        self.assertTrue(Path(result).is_file())

    def test_conflicting_duplicate_across_pages_fails(self):
        fixture = rows("DLT")
        older = [dict(row) for row in fixture[:100]]
        older[-1] = dict(fixture[100], front=[2, 3, 4, 5, 6])
        get, _ = self.transport("DLT", [markup("DLT", fixture[100:]), markup("DLT", older)])
        with patch("requests.get", side_effect=get), self.assertRaisesRegex(Exception, "DUPLICATE|CONFLICT|ORDER"):
            self.ro.capture("DLT", self.output)

    def test_bad_calendar_row_cannot_be_removed_to_reach_120(self):
        fixture = rows("DLT")
        fixture[120]["draw_date"] = "2026-01-01"
        get, _ = self.transport("DLT", [markup("DLT", fixture[100:])])
        with patch("requests.get", side_effect=get), self.assertRaisesRegex(Exception, "CALENDAR|DATE"):
            self.ro.capture("DLT", self.output)

    def test_same_china_day_and_future_rows_fail_entire_capture(self):
        # UTC Oct 23 17:00 is China Oct 24; both dates below are valid DLT
        # weekdays, so rejection must come from observation-time chronology.
        for day in ("2026-10-24", "2026-10-26"):
            self.output = Path(self.temp.name) / day
            fixture = rows("DLT")
            fixture[-1]["draw_date"] = day
            get, _ = self.transport("DLT", [markup("DLT", fixture[100:]), markup("DLT", fixture[:100])])
            with patch("requests.get", side_effect=get), patch.object(
                    self.ro, "_now", return_value="2026-10-23T17:00:00+00:00"), self.assertRaisesRegex(
                        Exception, "OBSERVATION.*DATE|OBSERVATION.*FUTURE"):
                self.ro.capture("DLT", self.output)
            self.assertFalse((self.output / "manifest.json").exists())

    def test_failed_second_page_keeps_hash_bound_raw_failure_receipt(self):
        # Two real parser subprocesses, HTTP mocked only. Neither publication
        # headers nor overlapping SSQ issues can be promoted to an as-of history.
        for game in ("DLT", "SSQ"):
            with self.subTest(game=game):
                self.output = Path(self.temp.name) / (game + "-failed-second")
                fixture = rows(game)
                first = markup(game, fixture[100:])
                if game == "DLT":
                    second = markup(game, fixture[:100]).replace(
                        "开奖日期".encode("utf-8"), "发布日期".encode("utf-8"))
                else:
                    older = [dict(row) for row in fixture[:100]]
                    older[-1] = dict(fixture[100])
                    second = markup(game, older)
                get, seen = self.transport(game, [first, second])
                with patch("requests.get", side_effect=get), self.assertRaises(Exception):
                    self.ro.capture(game, self.output)
                self.assertEqual(len(seen), 2)
                failure = json.loads((self.output / "failure.json").read_bytes())
                self.assertEqual(failure["schema"], "V47-RAW-OBSERVATION-FAILURE-1")
                self.assertEqual(failure["status"], "BLOCKED")
                self.assertEqual(failure["lottery"], game)
                self.assertEqual(failure["official_G01"], "BLOCKED")
                self.assertEqual(failure["official_target_admission"], "BLOCKED")
                self.assertEqual(failure["formal_A"], 0)
                self.assertEqual(failure["decision"], "NO_EDGE")
                self.assertEqual(len(failure["pages"]), 2)
                for saved, raw in zip(failure["pages"], (first, second)):
                    self.assertEqual(saved["http_status"], 200)
                    self.assertEqual(saved["raw_sha256"], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(saved["size_bytes"], len(raw))
                    self.assertEqual((self.output / saved["raw_file"]).read_bytes(), raw)
                    self.assertIn("requested_url", saved)
                    self.assertIn("fetch_completed_at_local_untrusted", saved)
                self.assertFalse((self.output / "manifest.json").exists())
                with self.assertRaises(FileNotFoundError):
                    self.ro.make_observation_metadata(self.output)

    def test_http_403_keeps_original_response_bytes_but_never_admits(self):
        # Main SSQ's official 403 cannot be fixed by pretending a forbidden
        # response is a valid draw page; this is a bounded HTTP failure probe.
        for game in ("DLT", "SSQ"):
            with self.subTest(game=game):
                self.output = Path(self.temp.name) / (game + "-http403")
                denied = ("synthetic 403 " + game).encode("ascii")
                seen = []
                def get(url, **kwargs):
                    seen.append(url)
                    self.assertIs(kwargs.get("allow_redirects"), False)
                    self.assertIs(kwargs.get("stream"), True)
                    return SimpleNamespace(
                        status_code=403, url=url,
                        iter_content=lambda chunk_size: iter([denied]),
                        close=lambda: None,
                        headers={"Content-Type": "text/plain; charset=utf-8"})
                with patch("requests.get", side_effect=get), self.assertRaisesRegex(
                        Exception, "OBSERVATION_HTTP_STATUS:403"):
                    self.ro.capture(game, self.output)
                self.assertEqual(len(seen), 1)
                failure = json.loads((self.output / "failure.json").read_bytes())
                self.assertEqual(failure["status"], "BLOCKED")
                self.assertEqual(failure["error"], "OBSERVATION_HTTP_STATUS:403")
                self.assertEqual(failure["source_origin_authenticity"], "NOT_VERIFIED")
                self.assertEqual(failure["publication_time_authenticity"], "NOT_VERIFIED")
                self.assertEqual(failure["external_tsa"], "NOT_RUN")
                self.assertEqual(len(failure["pages"]), 1)
                saved = failure["pages"][0]
                self.assertEqual(saved["http_status"], 403)
                self.assertEqual(saved["raw_sha256"], hashlib.sha256(denied).hexdigest())
                self.assertEqual((self.output / saved["raw_file"]).read_bytes(), denied)
                self.assertFalse((self.output / "manifest.json").exists())

    def test_raw_tampering_blocks_offline_verification(self):
        manifest, _ = self.capture("DLT")
        path = self.output / manifest["pages"][0]["raw_file"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(Exception, "SHA|BYTES"):
            self.ro.verify_observation(self.output)

    def test_row_claim_tampering_is_caught_by_real_subprocess_replay(self):
        manifest, _ = self.capture("DLT")
        manifest["all_rows"][0]["front"] = [2, 3, 4, 5, 6]
        (self.output / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(Exception, "REPLAY|ROWS"):
            self.ro.verify_observation(self.output)

    def test_boolean_number_claim_is_not_equal_to_replayed_integer(self):
        manifest, _ = self.capture("DLT")
        manifest["all_rows"][0]["front"][0] = True
        (self.output / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(Exception, "REPLAY|ROWS"):
            self.ro.verify_observation(self.output)

    def test_injected_publication_claim_is_rejected(self):
        manifest, _ = self.capture("DLT")
        manifest["published_at"] = "2026-10-01T00:00:00Z"
        (self.output / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(Exception, "CONTRACT|SCHEMA"):
            self.ro.verify_observation(self.output)

    def test_parser_pin_tampering_blocks_verification(self):
        manifest, _ = self.capture("SSQ")
        manifest["parser_source_files_sha256"]["research/harness_v46/recent_observation.py"] = "0" * 64
        (self.output / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(Exception, "SOURCE_HASH|PARSER"):
            self.ro.verify_observation(self.output)

    def test_metadata_is_frozen_canonical_manifest_digest_without_self_field(self):
        manifest, _ = self.capture("DLT")
        metadata = self.ro.make_observation_metadata(self.output)
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(metadata["manifest_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(set(metadata), {"schema", "manifest_sha256", "parser_source_sha256",
                                        "raw_sha256s", "observed_at_local_untrusted", "history_policy",
                                        "selected_rows_sha256"})
        self.assertEqual(len(set(metadata["raw_sha256s"])), 2)
        self.assertRegex(metadata["parser_source_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("manifest_sha256", manifest)

    def test_external_redirect_is_blocked_before_next_http_request(self):
        seen = []
        def get(url, **kwargs):
            seen.append(url)
            return SimpleNamespace(status_code=302, url=url, content=b"redirect diagnostic",
                                   close=lambda: None,
                                   headers={"Location": "https://example.com/untrusted"})
        with patch("requests.get", side_effect=get), self.assertRaisesRegex(Exception, "URL|REDIRECT|HOST"):
            self.ro.capture("DLT", self.output)
        self.assertEqual(len(seen), 1)

    def test_oversized_response_is_stream_bounded_and_closed(self):
        class LargeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            chunks = 0
            content_requested = False
            closed = False

            @property
            def content(self):
                self.content_requested = True
                return b"unbounded access must not happen"

            def iter_content(self, chunk_size):
                for _ in range(1000):
                    self.chunks += 1
                    yield b"x" * chunk_size

            def close(self):
                self.closed = True

        response = LargeResponse()
        response.url = "https://api.js-lottery.com/Lottery/_ListData?itemType=lo&pageIndex=1&pageSize=100"
        with patch("requests.get", return_value=response), self.assertRaisesRegex(Exception, "RAW_BYTES"):
            self.ro._fetch_page("DLT", {"itemType": "lo", "pageIndex": "1", "pageSize": "100"}, {})
        self.assertFalse(response.content_requested)
        self.assertLessEqual(response.chunks, 129)
        self.assertTrue(response.closed)

    def test_existing_directory_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.ro.capture("DLT", self.output)
        self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
