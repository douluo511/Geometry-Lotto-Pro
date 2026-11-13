"""Git source integrity: Windows/Linux EOL translation vs actual tampering."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from research.mother_v1.source_identity import (
    ROOT, SourceIdentityBlocked, committed_source_sha256,
)


class SourceHashTests(unittest.TestCase):
    def test_real_git_blob_has_repeatable_source_identity(self):
        filename = ROOT / "research/mother_v1/mother.py"
        actual = committed_source_sha256(filename)
        self.assertEqual(64, len(actual))
        self.assertEqual(actual, committed_source_sha256(filename))

    def test_normalize_windows_crlf_when_git_blob_is_lf(self):
        file = ROOT / "research/mother_v1/registry.py"
        installed = file.read_bytes()
        raw = installed.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        proc = subprocess.CompletedProcess(args=["git"], returncode=0, stdout=raw, stderr=b"")
        with patch("research.mother_v1.source_identity.subprocess.run", return_value=proc):
            self.assertEqual(sha256(raw).hexdigest(), committed_source_sha256(file))

    def test_non_eol_content_substitution_is_blocked(self):
        file = ROOT / "research/mother_v1/registry.py"
        proc = subprocess.CompletedProcess(args=["git"], returncode=0,
                                           stdout=b"FAKE REPLACED MODEL SOURCE", stderr=b"")
        with patch("research.mother_v1.source_identity.subprocess.run", return_value=proc):
            with self.assertRaisesRegex(SourceIdentityBlocked, "INSTALLED_BYTES_DIFFER"):
                committed_source_sha256(file)

    def test_files_outside_repo_and_missing_are_blocked(self):
        with self.assertRaises(SourceIdentityBlocked):
            committed_source_sha256(Path(__file__).resolve().parent.parent.parent.parent / "missing.py")


if __name__ == "__main__":
    unittest.main()
