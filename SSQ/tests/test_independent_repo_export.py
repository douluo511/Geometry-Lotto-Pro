from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from export_independent_repo import export_repository, verify_export  # noqa: E402


def write(root: Path, rel: str, data: bytes = b"x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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
