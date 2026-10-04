from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core import advanced_analysis, create_project, inspect_wav, repair, sha256_file, update_status


class CoreTests(unittest.TestCase):
    def test_real_audio_is_deterministic_and_non_silent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            a = create_project(base / "a", "hope at night", 99, 2.0)
            b = create_project(base / "b", "hope at night", 99, 2.0)
            wa = Path(a["project_dir"]) / "master.wav"
            wb = Path(b["project_dir"]) / "master.wav"
            self.assertEqual(sha256_file(wa), sha256_file(wb))
            metrics = inspect_wav(wa)
            self.assertGreater(metrics["rms"], 0.01)
            self.assertGreater(metrics["peak"], 0.05)
            self.assertAlmostEqual(metrics["duration_seconds"], 2.0, places=3)

    def test_repair_never_deletes_user_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            created = create_project(root, "preserve me", 7, 2.0)
            wav = Path(created["project_dir"]) / "master.wav"
            before = sha256_file(wav)
            result = repair(root)
            self.assertIn(result["status"], {"PASS", "WARN"})
            self.assertFalse(result["user_projects_deleted"])
            self.assertEqual(before, sha256_file(wav))

    def test_advanced_analysis_preserves_provider_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_project(root, "analysis", 1, 2.0)
            result = advanced_analysis(root)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(1, result["project_count"])
            joined = " ".join(result["business_gaps"])
            self.assertIn("NOT VERIFIED", joined)

    def test_update_fails_closed_without_release_context(self):
        with tempfile.TemporaryDirectory() as td:
            result = update_status(Path(td))
            self.assertEqual("BLOCKED", result["status"])
            self.assertFalse(result["user_projects_modified"])


if __name__ == "__main__":
    unittest.main()
