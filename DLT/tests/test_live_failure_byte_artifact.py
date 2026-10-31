"""P0 G00/G01: native DLT real-network gate must export its *own* failed HTTP bytes.

Only HTTP is substituted. The original build_canonical, Jiangsu parser,
exception propagation and receipt writer are exercised. This is not official
source authentication, an as-of proof, or prospective forecasting.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from glp import sources
import real_network_check as gate


class LiveFailureByteArtifactTests(unittest.TestCase):
    def test_actual_jiangsu_parser_failure_exposes_original_response_and_create_only_receipt(self):
        raw = ("<table><tr><th>发布日期</th><th>期号</th>"
               "<th>开奖号码</th></tr><tr><td>2026-10-28</td>"
               "<td>26123</td><td>01 02 03 04 05 06 07</td>"
               "</tr></table>").encode("utf-8")
        calls = []
        def network_get(url, **kwargs):
            calls.append((url, kwargs.get("params")))
            return SimpleNamespace(
                status_code=200, url=url, content=raw,
                headers={"Content-Type": "text/html; charset=utf-8"},
                glp_attempts=(),
            )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (patch.object(gate, "ROOT", root),
                  patch.object(sources, "fetch_national_history",
                               side_effect=sources.SourceError("SYNTHETIC_NATIONAL_UNAVAILABLE")),
                  patch.object(sources.NET, "get", side_effect=network_get),
                  contextlib.redirect_stdout(io.StringIO())):
                code = gate.main()
            self.assertEqual(code, 2)
            self.assertEqual(len(calls), 1)
            report = json.loads((root / "artifacts" / "real_network_check.json").read_bytes())
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE", report["error"])
            self.assertEqual(report["formal_A"], 0)
            self.assertEqual(report["official_target_admission"], "BLOCKED")
            self.assertEqual(report["decision"], "NO_EDGE")

            reference = report["failure_receipt"]
            self.assertEqual(reference["evidence_class"], "SHADOW")
            manifest_path = (root / "artifacts" / reference["path"]).resolve(strict=True)
            self.assertTrue(manifest_path.is_relative_to((root / "artifacts").resolve()))
            manifest_raw = manifest_path.read_bytes()
            self.assertEqual(hashlib.sha256(manifest_raw).hexdigest(), reference["sha256"])
            receipt = json.loads(manifest_raw)
            self.assertEqual(receipt["schema"], "DLT-G00-G01-LIVE-FAILURE-RAW-1")
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["parser_version"], sources.PARSER_VERSION)
            self.assertEqual(len(receipt["raw_responses"]), 1)
            response = receipt["raw_responses"][0]
            self.assertEqual(response["http_status"], 200)
            self.assertEqual(response["requested_url"], sources.JIANGSU_LIST_URL)
            self.assertEqual(response["url"], sources.JIANGSU_LIST_URL)
            self.assertEqual(response["parser_version"], sources.PARSER_VERSION)
            self.assertRegex(response["fetched_at_local_untrusted"], r"\d{4}-\d{2}-\d{2}T")
            self.assertEqual(response["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(response["bytes"], len(raw))
            body_path = manifest_path.parent / response["artifact"]
            self.assertEqual(body_path.read_bytes(), raw)
            with self.assertRaises(FileExistsError):
                with manifest_path.open("xb") as handle:
                    handle.write(b"unauthorized overwrite")
            self.assertEqual(manifest_path.read_bytes(), manifest_raw)


if __name__ == "__main__":
    unittest.main()
