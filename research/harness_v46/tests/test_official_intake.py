"""Offline contracts for V4.7 official-history intake; never assert live source authenticity."""
import base64
import copy
import hashlib
import json
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from research.harness_v46 import official_intake as intake
from research.harness_v46.core import GateError


PARSER_VERSION = "offline-fixture-parser-v1"
SOURCE_HASHES = {"research/harness_v46/official_intake.py": "a" * 64}


def make_rows(game, count=120):
    rows = []
    start = date(2025, 1, 1)
    front = [1, 3, 7, 12, 20, 33] if game == "SSQ" else [1, 3, 7, 12, 35]
    back = [5] if game == "SSQ" else [2, 12]
    for i in range(count):
        rows.append({
            "issue": str(2025001 + i),
            "draw_date": (start + timedelta(days=i)).isoformat(),
            "front": list(front),
            "back": list(back),
        })
    return rows


def source_specs(game):
    if game == "SSQ":
        return [
            ("national", "cwl.gov.cn", "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"),
            ("shanghai", "swlc.net.cn", "https://www.swlc.net.cn/lottery/ssq.html"),
        ]
    return [
        ("national", "sporttery.cn", "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"),
        ("jiangsu", "js-lottery.com", "https://api.js-lottery.com/Lottery/_ListData"),
    ]


def make_payload(game):
    rows = make_rows(game)
    sources = []
    for idx, (source_id, root, url) in enumerate(source_specs(game)):
        raw = ("offline-raw-" + game + "-" + source_id).encode()
        artifact = {
            "url": url, "requested_url": url,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw), "content_type": "application/octet-stream",
            "http_status": 200, "fetched_at": "2026-10-22T07:00:00+00:00",
            "parser_version": PARSER_VERSION,
            "raw_base64": base64.b64encode(raw).decode("ascii"),
        }
        sources.append({
            "source_id": source_id, "source_name": source_id,
            "source_root": root, "url": url, "draws": copy.deepcopy(rows),
            "raw_artifacts": [artifact],
            "raw_reparse_status": "PASS",
            "raw_reparse_sha256": intake._rows_sha256(rows),
            "receipt": {"status": "PASS", "draw_count": len(rows),
                        "latest_issue": rows[-1]["issue"]},
        })
    return {
        "schema": intake.WORKER_SCHEMA, "lottery": game,
        "parser_version": PARSER_VERSION, "source_files_sha256": dict(SOURCE_HASHES),
        "collection_started_at_local_untrusted": "2026-10-22T06:59:00+00:00",
        "collection_finished_at_local_untrusted": "2026-10-22T07:00:00+00:00",
        "sources": sources, "status": "WORKER_FETCH_COMPLETE",
        "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
    }


class OfficialIntakeTests(unittest.TestCase):
    def test_intake_source_file_is_in_hash_lock(self):
        hashes = intake.source_file_hashes("SSQ")
        self.assertIn("research/harness_v46/official_intake.py", hashes)
        self.assertEqual(len(hashes["research/harness_v46/official_intake.py"]), 64)

    def test_two_source_consensus_is_history_only_not_target_admission(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game), patch.object(intake, "source_file_hashes", return_value=SOURCE_HASHES):
                report = intake.validate_worker_payload(make_payload(game), expected_game=game)
                self.assertEqual(report["status"], "HISTORY_CROSSCHECK_PASS")
                self.assertEqual(report["consensus_draw_count"], 120)
                self.assertEqual(report["raw_byte_sha_validation"], "PASS")
                self.assertEqual(report["official_history_admission"], "SHADOW_HISTORY_ONLY")
                self.assertEqual(report["official_target_admission"], "BLOCKED")
                self.assertEqual(report["source_origin_authenticity"], "NOT_CRYPTOGRAPHICALLY_VERIFIED")
                self.assertEqual(report["formal_A"], 0)
                self.assertEqual(report["decision"], "NO_EDGE")

    def test_tampered_raw_bytes_fail_sha_gate(self):
        payload = make_payload("SSQ")
        payload["sources"][0]["raw_artifacts"][0]["raw_base64"] = base64.b64encode(b"tampered").decode()
        with patch.object(intake, "source_file_hashes", return_value=SOURCE_HASHES):
            with self.assertRaisesRegex(GateError, "RAW_ARTIFACT_BYTES_SHA_MISMATCH"):
                intake.validate_worker_payload(payload)

    def test_two_sources_with_same_root_are_rejected(self):
        payload = make_payload("SSQ")
        first = payload["sources"][0]
        second = payload["sources"][1]
        second["url"] = first["url"]
        second["source_root"] = first["source_root"]
        second["raw_artifacts"][0]["url"] = first["url"]
        second["raw_artifacts"][0]["requested_url"] = first["url"]
        with patch.object(intake, "source_file_hashes", return_value=SOURCE_HASHES):
            with self.assertRaisesRegex(GateError, "TWO_DISTINCT_OFFICIAL_SOURCE_ROOTS_REQUIRED"):
                intake.validate_worker_payload(payload)

    def test_cross_source_draw_conflict_is_rejected(self):
        payload = make_payload("DLT")
        payload["sources"][1]["draws"][10]["front"] = [2, 4, 8, 13, 35]
        payload["sources"][1]["raw_reparse_sha256"] = intake._rows_sha256(payload["sources"][1]["draws"])
        with patch.object(intake, "source_file_hashes", return_value=SOURCE_HASHES):
            with self.assertRaisesRegex(GateError, "OFFICIAL_SOURCE_DRAW_CONFLICT"):
                intake.validate_worker_payload(payload)

    def test_latest_issue_mismatch_is_rejected(self):
        payload = make_payload("SSQ")
        payload["sources"][1]["draws"][-1]["issue"] = "2025121"
        payload["sources"][1]["raw_reparse_sha256"] = intake._rows_sha256(payload["sources"][1]["draws"])
        payload["sources"][1]["receipt"]["latest_issue"] = "2025121"
        with patch.object(intake, "source_file_hashes", return_value=SOURCE_HASHES):
            with self.assertRaisesRegex(GateError, "OFFICIAL_SOURCE_LATEST_ISSUE_MISMATCH"):
                intake.validate_worker_payload(payload)

    def test_raw_reparse_routes_national_ssq_bytes_to_parser(self):
        rows = make_rows("SSQ")
        records = [{
            "code": row["issue"], "date": row["draw_date"],
            "red": " ".join(f"{n:02d}" for n in row["front"]),
            "blue": f"{row['back'][0]:02d}",
        } for row in rows]
        raw = json.dumps({"result": records}).encode("utf-8")

        def draw(issue, day, reds, blue):
            return SimpleNamespace(
                issue=str(issue), draw_date=str(day)[:10],
                front=tuple(sorted(int(x) for x in str(reds).split())),
                back=(int(blue),),
            )

        module = SimpleNamespace(_draw=draw)
        artifact = {"raw_base64": base64.b64encode(raw).decode("ascii")}
        parsed = intake._reparse_raw_history("SSQ", module, "national", [artifact])
        self.assertEqual(parsed, rows)
        self.assertEqual(intake._rows_sha256(parsed), intake._rows_sha256(rows))

    def test_empty_raw_body_cannot_be_a_parsed_history(self):
        module = SimpleNamespace()
        artifact = {"raw_base64": ""}
        with self.assertRaisesRegex(GateError, "SOURCE_HISTORY_REQUIRES_AT_LEAST_120_DRAWS"):
            intake._reparse_raw_history("SSQ", module, "national", [artifact])

    def test_worker_game_identity_mismatch_is_rejected(self):
        payload = make_payload("SSQ")
        with patch.object(intake, "source_file_hashes", return_value=SOURCE_HASHES):
            with self.assertRaisesRegex(GateError, "OFFICIAL_INTAKE_GAME_MISMATCH"):
                intake.validate_worker_payload(payload, expected_game="DLT")


if __name__ == "__main__":
    unittest.main()
