import base64
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from research.harness_v46 import official_intake as oi
from research.harness_v46.core import GateError


def _draws(game, n=130):
    rows = []
    start = date(2026, 1, 1)
    base = 2026001 if game == "SSQ" else 26101
    for i in range(n):
        if game == "SSQ":
            front = sorted({(i * 3 + j * 5) % 33 + 1 for j in range(6)})
            back = [i % 16 + 1]
        else:
            front = sorted({(i * 2 + j * 7) % 35 + 1 for j in range(5)})
            back = sorted({i % 12 + 1, (i + 4) % 12 + 1})
        rows.append({
            "issue": str(base + i),
            "draw_date": (start + timedelta(days=i)).isoformat(),
            "front": front,
            "back": back,
        })
    return rows


def _source_urls(game):
    if game == "SSQ":
        return [
            ("national", "cwl.gov.cn", "https://www.cwl.gov.cn/cwl_admin/front/history"),
            ("shanghai", "swlc.net.cn", "https://www.swlc.net.cn/lottery/ssq.html"),
        ]
    return [
        ("national", "sporttery.cn", "https://webapi.sporttery.cn/gateway/history"),
        ("jiangsu", "js-lottery.com", "https://api.js-lottery.com/Lottery/_ListData"),
    ]


def _artifact(url, parser_version, raw):
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "url": url,
        "requested_url": url,
        "raw_sha256": sha,
        "size_bytes": len(raw),
        "content_type": "application/json",
        "http_status": 200,
        "fetched_at": "2026-10-22T08:00:00+00:00",
        "parser_version": parser_version,
        "raw_base64": base64.b64encode(raw).decode("ascii"),
    }


def _payload(game, n=130):
    rows = _draws(game, n)
    parser_version = oi._expected_parser_version(game)
    sources = []
    for source_id, root, url in _source_urls(game):
        raw = ("synthetic raw fixture " + game + " " + source_id).encode()
        sources.append({
            "source_id": source_id,
            "source_name": oi.EXPECTED_SOURCE_NAMES[game][source_id],
            "source_root": root,
            "url": url,
            "draws": copy.deepcopy(rows),
            "receipt": {
                "status": "PASS", "draw_count": len(rows),
                "latest_issue": rows[-1]["issue"], "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "fetched_at": "2026-10-22T08:00:00+00:00",
            },
            "raw_artifacts": [_artifact(url, parser_version, raw)],
            "raw_reparse_status": "PASS",
            "raw_reparse_sha256": oi._rows_sha256(rows),
        })
    return {
        "schema": oi.WORKER_SCHEMA,
        "lottery": game,
        "parser_version": parser_version,
        "source_files_sha256": oi.source_file_hashes(game),
        "collection_started_at_local_untrusted": "2026-10-22T07:59:00+00:00",
        "collection_finished_at_local_untrusted": "2026-10-22T08:01:00+00:00",
        "sources": sources,
        "status": "WORKER_FETCH_COMPLETE",
        "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
    }


class OfficialIntakeTests(unittest.TestCase):
    def test_synthetic_ssq_dual_source_match_stays_shadow_only(self):
        report = oi.validate_worker_payload(_payload("SSQ"), expected_game="SSQ")
        self.assertEqual(report["status"], "HISTORY_CROSSCHECK_PASS")
        self.assertEqual(report["consensus_draw_count"], 130)
        self.assertEqual(report["raw_byte_sha_validation"], "PASS")
        self.assertEqual(report["official_target_admission"], "BLOCKED")
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")

    def test_synthetic_dlt_dual_source_match_stays_shadow_only(self):
        report = oi.validate_worker_payload(_payload("DLT"), expected_game="DLT")
        self.assertEqual(report["status"], "HISTORY_CROSSCHECK_PASS")
        self.assertEqual(report["consensus_draw_count"], 130)
        self.assertEqual(report["official_history_admission"], "SHADOW_HISTORY_ONLY")

    def test_raw_bytes_must_match_declared_sha(self):
        payload = _payload("SSQ")
        artifact = payload["sources"][0]["raw_artifacts"][0]
        artifact["raw_base64"] = base64.b64encode(b"changed raw bytes").decode("ascii")
        with self.assertRaisesRegex(GateError, "BYTES_SHA_MISMATCH"):
            oi.validate_worker_payload(payload)

    def test_source_histories_must_match(self):
        payload = _payload("DLT")
        rows = payload["sources"][1]["draws"]
        rows[50]["front"] = sorted([1, 2, 3, 4, 35])
        payload["sources"][1]["raw_reparse_sha256"] = oi._rows_sha256(rows)
        payload["sources"][1]["receipt"]["latest_issue"] = rows[-1]["issue"]
        with self.assertRaisesRegex(GateError, "OFFICIAL_SOURCE_DRAW_CONFLICT"):
            oi.validate_worker_payload(payload)

    def test_latest_issue_must_match(self):
        payload = _payload("SSQ")
        source = payload["sources"][1]
        source["draws"] = source["draws"][:-1]
        source["receipt"]["draw_count"] = len(source["draws"])
        source["receipt"]["latest_issue"] = source["draws"][-1]["issue"]
        source["raw_reparse_sha256"] = oi._rows_sha256(source["draws"])
        with self.assertRaisesRegex(GateError, "LATEST_ISSUE_MISMATCH"):
            oi.validate_worker_payload(payload)

    def test_less_than_120_history_rows_blocks(self):
        payload = _payload("SSQ", 119)
        with self.assertRaisesRegex(GateError, "AT_LEAST_120"):
            oi.validate_worker_payload(payload)

    def test_unallowlisted_host_blocks(self):
        payload = _payload("SSQ")
        payload["sources"][0]["url"] = "https://example.org/lottery"
        payload["sources"][0]["source_root"] = "example.org"
        with self.assertRaisesRegex(GateError, "HOST_NOT_ALLOWLISTED"):
            oi.validate_worker_payload(payload)

    def test_two_pages_from_same_root_do_not_count_as_independent(self):
        payload = _payload("SSQ")
        source = payload["sources"][1]
        source["url"] = "https://api.cwl.gov.cn/lottery"
        source["source_root"] = "cwl.gov.cn"
        artifact = source["raw_artifacts"][0]
        artifact["url"] = source["url"]
        artifact["requested_url"] = source["url"]
        with self.assertRaisesRegex(GateError, "SOURCE_ID_NOT_BOUND_TO_EXPECTED_OFFICIAL_ROOT"):
            oi.validate_worker_payload(payload)

    def test_raw_artifact_parser_version_must_match(self):
        payload = _payload("DLT")
        payload["sources"][0]["raw_artifacts"][0]["parser_version"] = "unreviewed-parser"
        with self.assertRaisesRegex(GateError, "PARSER_VERSION_MISMATCH"):
            oi.validate_worker_payload(payload)

    def test_empty_http_200_body_is_preserved_but_not_used_as_draw_page(self):
        payload = _payload("SSQ")
        source = payload["sources"][0]
        raw = b""
        artifact = _artifact(source["url"], payload["parser_version"], raw)
        source["raw_artifacts"].append(artifact)
        report = oi.validate_worker_payload(payload)
        self.assertEqual(report["status"], "HISTORY_CROSSCHECK_PASS")
        self.assertEqual(report["raw_artifact_count"], 3)
        self.assertEqual(report["formal_A"], 0)

    def test_raw_reparse_uses_exact_preserved_bytes_for_ssq_national(self):
        import json
        from types import SimpleNamespace

        rows = _draws("SSQ", 130)
        raw = json.dumps({"result": [
            {"code": r["issue"], "date": r["draw_date"],
             "red": r["front"], "blue": r["back"]}
            for r in rows
        ]}).encode("utf-8")

        def parse_draw(issue, day, reds, blue):
            return SimpleNamespace(
                issue=str(issue), draw_date=str(day),
                front=tuple(sorted(int(n) for n in reds)),
                back=tuple(int(n) for n in blue),
            )

        fake_parser = SimpleNamespace(_draw=parse_draw)
        artifact = {"http_status": 200, "raw_base64": base64.b64encode(raw).decode("ascii")}
        reparsed = oi._reparse_raw_history("SSQ", fake_parser, "national", [artifact])
        self.assertEqual(reparsed, rows)
        tampered = json.loads(raw.decode("utf-8"))
        tampered["result"][10]["red"] = [1, 2, 3, 4, 5, 6]
        artifact["raw_base64"] = base64.b64encode(
            json.dumps(tampered).encode("utf-8")
        ).decode("ascii")
        observed = oi._reparse_raw_history("SSQ", fake_parser, "national", [artifact])
        self.assertNotEqual(observed, rows)

    def test_source_identity_cannot_be_swapped_between_official_roots(self):
        payload = _payload("DLT")
        source = payload["sources"][0]
        source["url"] = "https://api.js-lottery.com/Lottery/_ListData"
        source["source_root"] = "js-lottery.com"
        source["raw_artifacts"][0]["url"] = source["url"]
        source["raw_artifacts"][0]["requested_url"] = source["url"]
        with self.assertRaisesRegex(GateError, "SOURCE_ID_NOT_BOUND_TO_EXPECTED_OFFICIAL_ROOT"):
            oi.validate_worker_payload(payload)

    def test_receipt_count_must_match_parsed_history(self):
        payload = _payload("SSQ")
        payload["sources"][0]["receipt"]["draw_count"] -= 1
        with self.assertRaisesRegex(GateError, "RECEIPT_DOES_NOT_MATCH"):
            oi.validate_worker_payload(payload)

    def test_partial_intake_preserves_non_200_failure_body_and_stays_blocked(self):
        payload = _payload("DLT")
        payload["status"] = "WORKER_FETCH_PARTIAL"
        payload["errors"] = {"national": "HTTP 567"}
        source = payload["sources"][0]
        source["draws"] = []
        source["receipt"] = None
        source["error"] = "HTTP 567"
        source["raw_reparse_status"] = "NOT_RUN_SOURCE_FETCH_FAILED"
        raw = b"synthetic HTTP 567 block page"
        artifact = source["raw_artifacts"][0]
        artifact.update({
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "content_type": "",
            "http_status": 567,
            "raw_base64": base64.b64encode(raw).decode("ascii"),
        })
        report = oi.validate_worker_payload(payload)
        self.assertEqual(report["status"], "SOURCE_FETCH_PARTIAL")
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["official_history_admission"], "BLOCKED")
        national = next(s for s in report["sources"] if s["source_id"] == "national")
        self.assertEqual(national["raw_artifacts"][0]["http_status"], 567)
        self.assertEqual(base64.b64decode(national["raw_artifacts"][0]["raw_base64"]), raw)
        self.assertEqual(report["consensus_draw_count"], 0)

    def test_dlt_redirect_guard_records_non_200_body_and_blocks_cross_root_redirect(self):
        import sys
        from unittest.mock import Mock, patch
        from types import SimpleNamespace

        captured = []
        def record(source_id, meta, raw):
            captured.append((source_id, meta, raw))
        response = SimpleNamespace(
            status_code=567,
            url="https://webapi.sporttery.cn/gateway/history",
            headers={"Content-Type": "text/html"},
            content=b"waf response",
        )
        fake_requests = SimpleNamespace(get=Mock(return_value=response))
        with patch.dict(sys.modules, {"requests": fake_requests}):
            oi._install_dlt_redirect_guard("DLT", record)
            observed = fake_requests.get("https://webapi.sporttery.cn/gateway/history")
        self.assertEqual(observed.status_code, 567)
        self.assertEqual(captured[0][0], "national")
        self.assertEqual(captured[0][1]["http_status"], 567)
        self.assertEqual(captured[0][2], b"waf response")

        redirect = SimpleNamespace(
            status_code=302,
            url="https://webapi.sporttery.cn/start",
            headers={"Content-Type": "text/html", "Location": "https://attacker.example/landing"},
            content=b"redirect body",
        )
        fake_requests = SimpleNamespace(get=Mock(return_value=redirect))
        with patch.dict(sys.modules, {"requests": fake_requests}):
            oi._install_dlt_redirect_guard("DLT", record)
            with self.assertRaisesRegex(GateError, "HOST_NOT_ALLOWLISTED"):
                fake_requests.get("https://webapi.sporttery.cn/start")

    def test_bundle_writes_raw_files_once_without_overwriting(self):
        report = oi.validate_worker_payload(_payload("SSQ"))
        bundle = {"schema": "V47-OFFICIAL-INTAKE-BUNDLE-1", "games": {"SSQ": report}, "errors": {}}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            manifest_path = oi.write_bundle(bundle, output)
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact = manifest["games"]["SSQ"]["sources"][0]["raw_artifacts"][0]
            raw_path = output / artifact["artifact_path"]
            self.assertTrue(raw_path.is_file())
            self.assertNotIn("raw_base64", artifact)
            with self.assertRaises(FileExistsError):
                oi.write_bundle({"games": {}}, output)


if __name__ == "__main__":
    unittest.main()
