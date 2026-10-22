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

    def test_receipt_count_must_match_parsed_history(self):
        payload = _payload("SSQ")
        payload["sources"][0]["receipt"]["draw_count"] -= 1
        with self.assertRaisesRegex(GateError, "RECEIPT_DOES_NOT_MATCH"):
            oi.validate_worker_payload(payload)

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


    def test_transport_failure_is_preserved_as_untrusted_not_official(self):
        raw = b"network intermediary returned HTTP 567"
        item = oi._transport_failure(
            "DLT", "national",
            "https://webapi.sporttery.cn/gateway/history",
            "https://webapi.sporttery.cn/gateway/history",
            567, "text/plain", raw, "2026-10-22T09:00:00+00:00",
            oi._expected_parser_version("DLT"),
        )
        self.assertEqual(item["http_status"], 567)
        self.assertEqual(item["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(base64.b64decode(item["body_base64"]), raw)
        self.assertEqual(item["body_preserved"], True)
        self.assertIn("UNTRUSTED_NOT_OFFICIAL_SOURCE_EVIDENCE", item["classification"])

    def test_blocked_worker_returns_diagnostics_instead_of_losing_manifest(self):
        source_hashes = oi.source_file_hashes("SSQ")
        payload = {
            "schema": oi.WORKER_SCHEMA, "lottery": "SSQ",
            "source_files_sha256": source_hashes, "status": "WORKER_BLOCKED",
            "source_errors": {"national": "HTTP status 567"},
            "sources": [], "unadmitted_raw_artifacts": [],
            "transport_failures": [{
                "source_id": "national", "expected_source_root": "cwl.gov.cn",
                "requested_url": "https://www.cwl.gov.cn/history",
                "response_url_untrusted": "https://www.cwl.gov.cn/history",
                "http_status": 567, "content_type": "text/plain",
                "fetched_at_local_untrusted": "2026-10-22T09:00:00+00:00",
                "parser_version": oi._expected_parser_version("SSQ"),
                "raw_sha256": hashlib.sha256(b"blocked").hexdigest(),
                "size_bytes": 7, "body_base64": base64.b64encode(b"blocked").decode(),
                "body_preserved": True,
                "classification": "TRANSPORT_FAILURE_UNTRUSTED_NOT_OFFICIAL_SOURCE_EVIDENCE",
            }],
        }
        completed = __import__("subprocess").CompletedProcess(
            args=["python", "-m", "research.harness_v46.official_intake"],
            returncode=0, stdout=json.dumps(payload), stderr="",
        )
        with patch.object(oi.subprocess, "run", return_value=completed), \
             patch.object(oi, "source_file_hashes", return_value=source_hashes):
            result = oi.collect_live_history("SSQ")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["official_target_admission"], "BLOCKED")
        self.assertEqual(result["transport_failures"][0]["http_status"], 567)
        self.assertIn("HTTP status 567", result["error"])

    def test_bundle_persists_transport_failure_bytes_separately(self):
        raw = b"synthetic transport failure body"
        failure = oi._transport_failure(
            "SSQ", "national", "https://www.cwl.gov.cn/history",
            "https://www.cwl.gov.cn/history", 567, "text/plain", raw,
            "2026-10-22T09:00:00+00:00", oi._expected_parser_version("SSQ"),
        )
        bundle = {
            "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
            "games": {"SSQ": {
                "schema": oi.SCHEMA, "lottery": "SSQ", "status": "BLOCKED",
                "sources": [], "unadmitted_raw_artifacts": [],
                "transport_failures": [failure],
                "official_target_admission": "BLOCKED", "formal_A": 0, "decision": "NO_EDGE",
            }},
            "errors": {"SSQ": "HTTP status 567"},
            "official_target_admission": "BLOCKED", "formal_A": 0, "decision": "NO_EDGE",
        }
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = oi.write_bundle(bundle, Path(tmp) / "bundle")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = manifest["games"]["SSQ"]["transport_failures"][0]
            self.assertTrue(record["body_preserved"])
            self.assertNotIn("body_base64", record)
            self.assertTrue((manifest_path.parent / record["artifact_path"]).is_file())
            self.assertEqual(record["classification"],
                             "TRANSPORT_FAILURE_UNTRUSTED_NOT_OFFICIAL_SOURCE_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
