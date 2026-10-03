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

    def run_functions(self, statement, root=None):
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
''' + statement
        result = subprocess.run([self.shell, "-NoProfile", "-NonInteractive", "-Command", command],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertIn("BOOTSTRAP_FUNCTIONS_LOADED", result.stdout,
                      "Bootstrap execution UNAVAILABLE before test assertion: " + result.stderr)
        result.stdout = result.stdout.replace("BOOTSTRAP_FUNCTIONS_LOADED\n", "")
        return result

    def verify(self, root=None, allow_git=False):
        return self.run_functions(
            "Assert-ExportIntegrity -Root $env:EXPORT_TEST_ROOT "
            "-Repo 'douluo511/Geometry-Lotto-Pro-SSQ' -ExpectedCommit ('a'*40) "
            + ("-AllowGitMetadata " if allow_git else "") + "| ConvertTo-Json -Compress", root)

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", *args], cwd=cwd or self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_wrapper_forwards_arguments_and_preserves_single_line(self):
        result = self.run_functions(r'''
$version = Invoke-Git -Arguments @('--version')
if ($version -isnot [array] -or $version.Count -ne 1 -or $version[-1] -notmatch '^git version ') {
  throw 'single-line Git output was not preserved as an array'
}
Invoke-Git -WorkingDirectory $env:EXPORT_TEST_ROOT -Arguments @('init','-q') | Out-Null
Invoke-Git -WorkingDirectory $env:EXPORT_TEST_ROOT -Arguments @('config','test.bootstrap','value with spaces') | Out-Null
$value = Invoke-Git -WorkingDirectory $env:EXPORT_TEST_ROOT -Arguments @('config','--get','test.bootstrap')
if ($value[-1] -cne 'value with spaces') { throw 'Git argument boundary lost' }
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_wrapper_propagates_native_failure(self):
        result = self.run_functions("Invoke-Git -Arguments @('bootstrap-command-does-not-exist')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git command failed with exit code", result.stderr)

    def test_gh_wrapper_arguments_and_failure_contract_with_controlled_double(self):
        # Unit contract only. This double never proves real GitHub access.
        result = self.run_functions(r'''
function gh {
  $global:LASTEXITCODE = 0
  if ($args[0] -eq 'failure') { $global:LASTEXITCODE = 7 }
  ConvertTo-Json -InputObject @($args) -Compress
}
$reply = Invoke-Gh -Arguments @('repo','view','owner/name with spaces')
$actual = @($reply.Output[0] | ConvertFrom-Json)
if ($reply.ExitCode -ne 0 -or $actual.Count -ne 3 -or $actual[2] -cne 'owner/name with spaces') {
  throw 'GitHub CLI arguments not forwarded intact'
}
$failed = Invoke-Gh -Arguments @('failure') -AllowFailure
if ($failed.ExitCode -ne 7) { throw 'native failure code lost' }
$caught = $false
try { Invoke-Gh -Arguments @('failure') | Out-Null } catch {
  if ($_.Exception.Message -notmatch 'gh command failed with exit code 7') { throw }
  $caught = $true
}
if (-not $caught) { throw 'GitHub CLI failure swallowed' }
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_arguments_fail_closed(self):
        for name in ("Invoke-Git", "Invoke-Gh"):
            with self.subTest(wrapper=name):
                result = self.run_functions(name + " -Arguments @()")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("arguments required", result.stderr)

    def test_plain_export_passes(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["file_count"], 1)

    def test_actual_reclone_metadata_ignored_but_extra_payload_rejected(self):
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        cloned = Path(self.temp.name) / "remote verification with spaces"
        self.git("-c", "core.autocrlf=false", "clone", "--no-hardlinks", str(self.root), str(cloned))
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
