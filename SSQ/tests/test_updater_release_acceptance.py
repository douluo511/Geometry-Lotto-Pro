from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import updater_release_acceptance as release_acceptance  # noqa: E402


class UpdaterReleaseAcceptanceTests(unittest.TestCase):
    def test_shared_repository_is_rejected(self) -> None:
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "12345",
            "RUNNER_OS": "Windows",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeError, "independent SSQ repository"):
                release_acceptance._require_independent_actions_context()

    def test_non_actions_environment_is_rejected(self) -> None:
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "false",
            "GITHUB_REPOSITORY": release_acceptance.EXPECTED_REPOSITORY,
            "GITHUB_SERVER_URL": release_acceptance.EXPECTED_SERVER,
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "12345",
            "RUNNER_OS": "Windows",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeError, "GitHub Actions"):
                release_acceptance._require_independent_actions_context()

    def test_exact_independent_windows_context_is_accepted(self) -> None:
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": release_acceptance.EXPECTED_REPOSITORY,
            "GITHUB_SERVER_URL": release_acceptance.EXPECTED_SERVER,
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "12345",
            "RUNNER_OS": "Windows",
        }, clear=False):
            context = release_acceptance._require_independent_actions_context()
        self.assertEqual(context["repository"], release_acceptance.EXPECTED_REPOSITORY)
        self.assertEqual(context["runner_os"], "Windows")

    def test_sha256_reads_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "candidate.exe"
            path.write_bytes(b"exact-bytes")
            self.assertEqual(
                release_acceptance._sha256(path),
                "c48dd9523b01ec38f2df720790fcbfa72bdf00c7b6c71611126720bbc6a9b967",
            )

    def test_wait_proof_requires_actual_live_pid_wait(self) -> None:
        good = {
            "wait_for_main": {
                "status": "PASS", "waited": True, "pid": 4321, "elapsed": 1.25,
            }
        }
        proof = release_acceptance._require_wait_proof(good, 4321)
        self.assertTrue(proof["waited"])

        bad_cases = [
            {"status": "PASS", "waited": False},
            {"status": "PASS", "waited": True, "pid": 9999, "elapsed": 1.0},
            {"status": "PASS", "waited": True, "pid": 4321, "elapsed": 0},
            {"status": "PASS", "waited": True, "pid": 4321, "elapsed": False},
            {"status": "FAIL", "waited": True, "pid": 4321, "elapsed": 1.0},
        ]
        for wait in bad_cases:
            with self.subTest(wait=wait):
                with self.assertRaisesRegex(RuntimeError, "waiting for a live main-process PID"):
                    release_acceptance._require_wait_proof({"wait_for_main": wait}, 4321)

    def test_exact_base_main_exit_scheduler_rejects_nonpositive_delay(self) -> None:
        class Dummy:
            pid = 4321
            def poll(self):
                return None
        with self.assertRaisesRegex(ValueError, "exit delay"):
            release_acceptance._schedule_exact_base_main_exit(Dummy(), 0)

if __name__ == "__main__":
    unittest.main()
