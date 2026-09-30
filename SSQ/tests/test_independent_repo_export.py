from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from export_independent_repo import export_repository, verify_export  # noqa: E402
from architecture_gate import (  # noqa: E402
    build_requirements_are_frozen,
    workflow_actions_are_sha_pinned,
)


def write(root: Path, rel: str, data: bytes = b"x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class WorkflowSupplyChainTests(unittest.TestCase):
    def test_build_dependency_closure_rejects_unpinned_or_resolver_install(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            ssq = repo / "SSQ"
            ssq.mkdir()
            (ssq / "requirements-build.txt").write_text(
                "pyinstaller==6.22.3\nrequests>=2\n", encoding="utf-8"
            )
            wf = repo / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "ssq-windows-build-acceptance.yml").write_text(
                "run: python -m pip install -r requirements-build.txt\n",
                encoding="utf-8",
            )
            ok, failures = build_requirements_are_frozen(ssq, repo)
            self.assertFalse(ok)
            self.assertTrue(any("not exact pinned" in row for row in failures))
            self.assertTrue(any("dependency closure differs" in row for row in failures))
            self.assertTrue(any("no-deps" in row for row in failures))

    def test_official_actions_must_be_pinned_to_full_commit_sha(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wf = root / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "ssq-windows-build-acceptance.yml").write_text(
                "steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8"
            )
            (wf / "ssq-independent-repo-export.yml").write_text(
                "steps:\n  - uses: actions/setup-python@" + "a" * 40 + " # v5\n",
                encoding="utf-8",
            )
            ok, failures = workflow_actions_are_sha_pinned(root)
            self.assertFalse(ok)
            self.assertTrue(any("checkout@v4" in row for row in failures))

            (wf / "ssq-windows-build-acceptance.yml").write_text(
                "steps:\n  - uses: actions/checkout@" + "b" * 40 + " # v4\n",
                encoding="utf-8",
            )
            ok, failures = workflow_actions_are_sha_pinned(root)
            self.assertTrue(ok)
            self.assertEqual(failures, [])


class IndependentRepoExportTests(unittest.TestCase):
    def make_source(self, root: Path) -> None:
        write(root, "SSQ/README_GITHUB.md", b"# SSQ\n")
        write(root, "SSQ/SSQ/glp/core.py", b"VALUE = 1\n")
        write(root, "SSQ/tests/test_core.py", b"def test_ok(): assert True\n")
        write(root, "SSQ/tools/tool.py", b"pass\n")
        write(root, "SSQ/dist/should-not-export.exe", b"candidate")
        write(root, "SSQ/evidence/SSQ/should-not-export.json", b"{}")
        write(root, "SSQ/build/cache.bin", b"cache")
        write(root, "SSQ/SSQ/glp/__pycache__/core.pyc", b"pyc")
        write(root, ".github/workflows/ssq-windows-build-acceptance.yml", b"name: test\n")
        write(root, ".github/scripts/ssq_physical_gui_click_smoke.ps1", b"Write-Host ok\n")
        write(root, ".gitignore", b"dist/\n")
        write(root, "PORTFOLIO_GOVERNANCE.md", b"independent repo required\n")
        write(root, "DLT/secret.py", b"must-not-export\n")
        write(root, "investment_finance_pro/secret.py", b"must-not-export\n")

    def test_export_is_ssq_only_hash_bound_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)

            proof = export_repository(source, target, "a" * 40)
            self.assertEqual(proof["status"], "PASS")
            self.assertTrue((target / "SSQ/SSQ/glp/core.py").is_file())
            self.assertTrue((target / ".github/workflows/ssq-windows-build-acceptance.yml").is_file())
            self.assertTrue((target / ".github/scripts/ssq_physical_gui_click_smoke.ps1").is_file())
            self.assertTrue((target / "README.md").is_file())
            self.assertFalse((target / "DLT").exists())
            self.assertFalse((target / "investment_finance_pro").exists())
            self.assertFalse((target / "SSQ/dist").exists())
            self.assertFalse((target / "SSQ/evidence").exists())
            self.assertFalse((target / "SSQ/build").exists())
            self.assertEqual(proof["source_commit"], "a" * 40)
            self.assertTrue(all(proof["checks"].values()))

    def test_mutated_export_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "b" * 40)["status"], "PASS")

            (target / "SSQ/SSQ/glp/core.py").write_bytes(b"tampered\n")
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertFalse(proof["checks"]["all_hashes_match"])
            self.assertTrue(any(row["path"] == "SSQ/SSQ/glp/core.py" for row in proof["mismatches"]))

    def test_unmanifested_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "c" * 40)["status"], "PASS")

            write(target, "unexpected.txt", b"not in manifest")
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertFalse(proof["checks"]["no_unmanifested_files"])

    def test_tampered_sha256s_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "9" * 40)["status"], "PASS")

            (target / "MIGRATION_SHA256SUMS.txt").write_text(
                "0" * 64 + "  SSQ/SSQ/glp/core.py\n", encoding="utf-8"
            )
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertFalse(proof["checks"]["sha256sums_match_manifest"])

    def test_duplicate_manifest_path_fails_verification(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "e" * 40)["status"], "PASS")

            manifest_path = target / "MIGRATION_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"].append(dict(manifest["files"][0]))
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertFalse(proof["checks"]["unique_manifest_paths"])
            self.assertTrue(proof["duplicate_paths"])

    def test_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            link = source / "SSQ" / "SSQ" / "glp" / "linked.py"
            try:
                link.symlink_to(source / "SSQ" / "SSQ" / "glp" / "core.py")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this runner")
            with self.assertRaises(ValueError):
                export_repository(source, target, "f" * 40)

    def test_manifest_consistent_unknown_top_level_path_is_rejected(self) -> None:
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "7" * 40)["status"], "PASS")

            payload = b"unexpected-but-self-consistent"
            write(target, "unknown_project/payload.bin", payload)
            manifest_path = target / "MIGRATION_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"].append({
                "path": "unknown_project/payload.bin",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            })
            manifest["files"] = sorted(manifest["files"], key=lambda row: row["path"])
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            sums = "".join(
                f'{row["sha256"]}  {row["path"]}\n' for row in manifest["files"]
            )
            (target / "MIGRATION_SHA256SUMS.txt").write_text(sums, encoding="utf-8")

            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertTrue(proof["checks"]["no_unmanifested_files"])
            self.assertTrue(proof["checks"]["sha256sums_match_manifest"])
            self.assertTrue(proof["checks"]["all_hashes_match"])
            self.assertFalse(proof["checks"]["allowed_paths_only"])

    def test_nonempty_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            self.make_source(source)
            write(target, "keep.txt", b"existing")

            with self.assertRaises(ValueError):
                export_repository(source, target, "d" * 40)


if __name__ == "__main__":
    unittest.main()
