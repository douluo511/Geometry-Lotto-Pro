"""Local real-Git/bootstrap integrity tests; never claim GitHub creation PASS."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/bootstrap_independent_repo.ps1"
REPO = "douluo511/Geometry-Lotto-Pro-SSQ"
SHA = "a" * 40


class BootstrapIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "export"
        self.root.mkdir()
        self.shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(self.shell, "PowerShell required; do not silently skip deployment contracts")
        self.assertIsNotNone(shutil.which("git"), "real Git required")
        (self.root / "app.py").write_bytes(b"print('real export fixture')\n")
        self.manifest()

    def manifest(self, extra=()):
        rows = []
        for rel in ("app.py", *extra):
            raw = (self.root / rel).read_bytes()
            rows.append({"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        (self.root / "MIGRATION_MANIFEST.json").write_text(json.dumps({
            "schema": "ssq-independent-repo-export-v1",
            "source_repository": "douluo511/Geometry-Lotto-Pro",
            "target_repository": REPO, "source_commit": SHA, "files": rows,
        }), encoding="utf-8")
        (self.root / "MIGRATION_SHA256SUMS.txt").write_text(
            "".join(f"{r['sha256']}  {r['path']}\n" for r in rows), encoding="utf-8")

    def verify(self, root=None, allow_git=False):
        env = dict(os.environ, BOOTSTRAP_SCRIPT=str(SCRIPT), EXPORT_TEST_ROOT=str(root or self.root))
        # Load ONLY function definitions. Do not execute the bootstrap main,
        # authenticate, create a remote, push, or invoke cleanup in these tests.
        command = r'''
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:BOOTSTRAP_SCRIPT,[ref]$tokens,[ref]$errors)
if($errors.Count -ne 0){throw ($errors | Out-String)}
foreach($f in $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]},$false)){
  Invoke-Expression $f.Extent.Text
}
Write-Output 'BOOTSTRAP_FUNCTIONS_LOADED'
Assert-ExportIntegrity -Root $env:EXPORT_TEST_ROOT -Repo 'douluo511/Geometry-Lotto-Pro-SSQ' -ExpectedCommit ('a'*40) ALLOW_GIT | ConvertTo-Json -Compress
'''.replace("ALLOW_GIT", "-AllowGitMetadata" if allow_git else "")
        result = subprocess.run([self.shell, "-NoProfile", "-NonInteractive", "-Command", command],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertIn("BOOTSTRAP_FUNCTIONS_LOADED", result.stdout,
                      "Bootstrap execution UNAVAILABLE before test assertion: " + result.stderr)
        result.stdout = result.stdout.replace("BOOTSTRAP_FUNCTIONS_LOADED\n", "")
        return result

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", *args], cwd=cwd or self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plain_export_passes(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["file_count"], 1)

    def test_actual_reclone_metadata_ignored_but_extra_payload_rejected(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        cloned = Path(self.temp.name) / "remote-verification"
        self.git("clone", "--no-hardlinks", str(self.root), str(cloned))
        result = self.verify(cloned, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        (cloned / "unexpected.exe").write_bytes(b"unapproved")
        self.assertNotEqual(self.verify(cloned, True).returncode, 0)
        # A local export carrying metadata remains forbidden.
        self.assertNotEqual(self.verify().returncode, 0)

    def test_fake_metadata_is_not_a_clone(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("fake", encoding="utf-8")
        self.assertNotEqual(self.verify(allow_git=True).returncode, 0)

    def test_nested_git_cannot_be_hidden_even_when_manifested(self):
        (self.root / "payload/.git").mkdir(parents=True)
        (self.root / "payload/.git/config").write_bytes(b"hidden")
        self.manifest(("payload/.git/config",))
        self.assertNotEqual(self.verify().returncode, 0)

    def test_changed_bytes_fail(self):
        (self.root / "app.py").write_bytes(b"tampered")
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
