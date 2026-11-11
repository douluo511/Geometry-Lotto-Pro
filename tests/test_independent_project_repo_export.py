from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from export_independent_project_repo import PROJECTS, export_repository, verify_export  # noqa: E402


def write(root: Path, rel: str, data: bytes = b"x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class PortfolioIndependentRepoExportTests(unittest.TestCase):
    def make_source(self, root: Path) -> None:
        write(root, "DLT/README_GITHUB_VALIDATION.md", b"# DLT\n")
        write(root, "DLT/src/app.py", b"VALUE = 1\n")
        write(root, "DLT/tests/test_app.py", b"def test_ok(): assert True\n")
        write(root, "DLT/dist/candidate.exe", b"generated")
        write(root, "DLT/evidence/final_gate.json", b"{}")
        write(root, "DLT/build/cache.bin", b"cache")
        write(root, "DLT/src/__pycache__/app.pyc", b"pyc")
        write(
            root,
            ".github/workflows/dlt-windows-build-acceptance.yml",
            b"name: DLT\nsteps:\n  - run: .github/scripts/physical_gui_click_smoke.ps1\n",
        )
        write(root, ".github/scripts/physical_gui_click_smoke.ps1", b"Write-Host ok\n")
        write(root, ".gitignore", b"dist/\n")
        write(root, "PORTFOLIO_GOVERNANCE.md", b"independent repo required\n")
        write(root, "SSQ/secret.py", b"must-not-export\n")
        write(root, "head_intelligence/secret.py", b"must-not-export\n")

    def test_config_is_unique_and_complete(self) -> None:
        self.assertGreaterEqual(len(PROJECTS), 6)
        dirs = [str(v["project_dir"]) for v in PROJECTS.values()]
        workflows = [str(v["workflow"]) for v in PROJECTS.values()]
        targets = [str(v["target_repository"]) for v in PROJECTS.values()]
        self.assertEqual(len(dirs), len(set(dirs)))
        self.assertEqual(len(workflows), len(set(workflows)))
        self.assertEqual(len(targets), len(set(targets)))
        self.assertTrue(all(t.startswith("douluo511/") for t in targets))

    def test_export_is_project_only_hash_bound_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)

            proof = export_repository(source, target, "dlt", "a" * 40)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["target_repository"], "douluo511/Geometry-Lotto-Pro-DLT")
            self.assertTrue((target / "DLT/src/app.py").is_file())
            self.assertTrue((target / ".github/workflows/dlt-windows-build-acceptance.yml").is_file())
            self.assertTrue((target / ".github/scripts/physical_gui_click_smoke.ps1").is_file())
            self.assertTrue((target / "README.md").is_file())
            self.assertFalse((target / "SSQ").exists())
            self.assertFalse((target / "head_intelligence").exists())
            self.assertFalse((target / "DLT/dist").exists())
            self.assertFalse((target / "DLT/evidence").exists())
            self.assertFalse((target / "DLT/build").exists())
            self.assertTrue(all(proof["checks"].values()))

    def test_mutated_export_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "dlt", "b" * 40)["status"], "PASS")

            (target / "DLT/src/app.py").write_bytes(b"tampered\n")
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertFalse(proof["checks"]["all_hashes_match"])
            self.assertTrue(any(row["path"] == "DLT/src/app.py" for row in proof["mismatches"]))

    def test_unmanifested_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "dlt", "c" * 40)["status"], "PASS")

            write(target, "unexpected.txt", b"not in manifest")
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertFalse(proof["checks"]["no_unmanifested_files"])

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
                export_repository(source, target, "dlt", "d" * 40)

    def test_manifest_path_escape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            self.make_source(source)
            self.assertEqual(export_repository(source, target, "dlt", "e" * 40)["status"], "PASS")

            manifest_path = target / "MIGRATION_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["path"] = "../escape.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            proof = verify_export(target)
            self.assertEqual(proof["status"], "FAIL")
            self.assertEqual(proof.get("error"), "manifest path escape")


if __name__ == "__main__":
    unittest.main()
