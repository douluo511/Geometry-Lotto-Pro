"""Actual persisted report hash faults, independent of SMTP and model output."""
from pathlib import Path
import tempfile
import unittest
from research.ssq_dlt_v45.runtime import write_report


class ReportIntegrityTests(unittest.TestCase):
    def test_tampered_html_is_rejected_and_never_repaired_over_original(self):
        report={'due_slot':'2026-10-17T16:00:00+09:00','created_at':'2026-10-17T07:00:00+00:00','games':{},'blockers':[]}
        with tempfile.TemporaryDirectory() as temp:
            folder=write_report(Path(temp),report)
            original=(folder/'report.json').read_bytes()
            (folder/'report.html').write_text('TAMPERED',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'REPORT_ARTIFACT_SHA_MISMATCH'):
                write_report(Path(temp),report)
            self.assertEqual((folder/'report.json').read_bytes(),original)
            self.assertEqual((folder/'report.html').read_text('utf-8'),'TAMPERED')

    def test_exact_retry_verifies_all_existing_artifacts(self):
        report={'due_slot':'2026-10-17T16:00:00+09:00','created_at':'2026-10-17T07:00:00+00:00','games':{},'blockers':[]}
        with tempfile.TemporaryDirectory() as temp:
            first=write_report(Path(temp),report)
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in first.iterdir()}
            self.assertEqual(write_report(Path(temp),report),first)
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in first.iterdir()},before)
