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
                "1417897b6c2dc4d6fc69f7db05b0f159990f0764afdb3eacb38db70a4e9c4eaf",
            )


if __name__ == "__main__":
    unittest.main()
