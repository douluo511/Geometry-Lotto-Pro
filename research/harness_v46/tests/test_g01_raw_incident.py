"""Offline archive regression tests. These are invented raw HTTP fixture bytes."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46 import g01_raw_incident as incident


def archive_bytes(*, tamper=False, false_pass=False):
    html = (
        "<table>"
        "<tr><td>2016-01-07</td><td>16003</td><td>04 12 17 22 26 06 07</td></tr>"
        "<tr><td>2016-01-11</td><td>16004</td><td>10 20 23 32 35 09 10</td></tr>"
        "<tr><td>2016-01-11</td><td>16005</td><td>06 09 12 15 20 08 11</td></tr>"
        "</table>"
    ).encode("utf-8")
    denied = b"HTTP 567 provider response"
    contents = [
        ("DLT", "jiangsu", html, 200),
        ("DLT", "national", denied, 567),
    ]
    games = {
        "SSQ": {"status": "HISTORY_CROSSCHECK_LIMITED", "sources": [],
                "official_history_admission": "BLOCKED", "formal_A": 0,
                "decision": "NO_EDGE"},
        "DLT": {"status": "SOURCE_FETCH_PARTIAL", "sources": [],
                "official_history_admission": "BLOCKED", "formal_A": 0,
                "decision": "NO_EDGE"}
    }
    files = {}
    for game, source, raw, status in contents:
        sha = hashlib.sha256(raw).hexdigest()
        path = f"raw/{game}/{source}/{sha}.bin"
        artifact = {"artifact_path": path, "source_id": source,
                    "raw_sha256": sha, "size_bytes": len(raw),
                    "http_status": status,
                    "url": f"https://{'api.js-lottery.com' if source == 'jiangsu' else 'webapi.sporttery.cn'}/source",
                    "content_type": "text/html"}
        files[path] = (raw + b"malicious" if tamper and source == "jiangsu" else raw)
        games[game]["sources"].append({
            "source_id": source, "raw_artifacts": [artifact],
            "raw_reparse_status": "FAIL" if source == "jiangsu" else "NOT_RUN_SOURCE_FETCH_FAILED",
            "error": "G01 blocked"
        })
    manifest = {
        "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
        "games": games, "formal_A": 1 if false_pass else 0,
        "decision": "NO_EDGE",
        "official_target_admission": "BLOCKED"
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    audit = {
        "schema": "V47-INTAKE-BUNDLE-AUDIT-1", "status": "PASS",
        "artifact_records": 2, "verified_artifact_records": 2,
        "unique_raw_file_paths": 2,
        "bundle_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "http_raw_evidence_status": "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY",
        "admission_guard": {"formal_A": 0, "official_target_admission": "BLOCKED",
                            "decision": "NO_EDGE"},
        "errors": []
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("intake.json", manifest_bytes)
        z.writestr("intake-audit.json", json.dumps(audit))
        for name, raw in files.items():
            z.writestr(name, raw)
    return output.getvalue()


class SourceIncidentArchiveTests(unittest.TestCase):
    def test_original_zip_bytes_replayed_and_dates_not_corrected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "original.zip"
            original = archive_bytes()
            p.write_bytes(original)
            a = incident.analyze_zip(p)
            b = incident.analyze_zip(p)
            self.assertEqual(a, b)
            self.assertEqual(p.read_bytes(), original)
            self.assertEqual(a["schema"], "V47-G01-RAW-INCIDENT-REPORT-1")
            self.assertEqual(a["raw_artifact_count"], 2)
            self.assertEqual(a["source_status"]["DLT"], "SOURCE_FETCH_PARTIAL")
            self.assertEqual(a["http_incidents"][0]["http_status"], 567)
            self.assertEqual(a["http_incidents"][0]["source_id"], "national")
            jiangsu = a["calendar_incidents"]
            self.assertTrue(any(x["issue"] == "16003" and
                                x["reason"] == "NON_REGULAR_DRAW_WEEKDAY"
                                and x["draw_date"] == "2016-01-07" for x in jiangsu))
            self.assertTrue(any(x["issue"] == "16005" and
                                x["reason"] == "DRAW_DATE_REPEATED_ACROSS_ISSUES"
                                and x["other_issue"] == "16004" for x in jiangsu))
            self.assertEqual(a["raw_integrity"], "PASS_ALL_ARCHIVED_BYTES")
            self.assertEqual(a["official_history_admission"], "BLOCKED")
            self.assertEqual(a["formal_A"], 0)
            self.assertEqual(a["decision"], "NO_EDGE")
            self.assertEqual(a["report_sha256"],
                             core.digest({k:v for k,v in a.items() if k != "report_sha256"}))

    def test_tampered_raw_bytes_block_report_even_if_audit_claims_pass(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "changed.zip"
            p.write_bytes(archive_bytes(tamper=True))
            with self.assertRaisesRegex(core.GateError, "RAW_ARTIFACT_SHA_MISMATCH"):
                incident.analyze_zip(p)

    def test_forged_formal_pass_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "forged.zip"
            p.write_bytes(archive_bytes(false_pass=True))
            with self.assertRaisesRegex(core.GateError, "RAW_ARCHIVE_FORMAL_ADMISSION_FORBIDDEN"):
                incident.analyze_zip(p)

    def test_declared_absent_file_cannot_be_silently_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "missing.zip"
            original = archive_bytes()
            with zipfile.ZipFile(io.BytesIO(original)) as z, zipfile.ZipFile(p, "w") as out:
                for name in z.namelist():
                    if "/jiangsu/" not in name:
                        out.writestr(name, z.read(name))
            with self.assertRaisesRegex(core.GateError, "MISSING_RAW_ARTIFACT"):
                incident.analyze_zip(p)

    def test_cli_report_pins_exact_input_archive(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "original.zip"
            b = archive_bytes()
            p.write_bytes(b)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(incident.main(["--intake-zip", str(p)]), 0)
            value = json.loads(out.getvalue())
            self.assertEqual(value["zip_sha256"], hashlib.sha256(b).hexdigest())
            self.assertEqual(value["decision"], "NO_EDGE")


if __name__ == "__main__":
    unittest.main()
