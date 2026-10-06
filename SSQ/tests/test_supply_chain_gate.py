from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from architecture_gate import (  # noqa: E402
    EXPECTED_BUILD_REQUIREMENTS,
    build_requirements_are_frozen,
    workflow_actions_are_sha_pinned,
)


# CI synchronize marker: exact-head hardening validation\nclass SupplyChainGateTests(unittest.TestCase):
    def write_workflow(self, root: Path, body: str) -> None:
        path = root / ".github" / "workflows" / "ssq-windows-build-acceptance.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def write_requirements(self, ssq: Path, rows: list[str]) -> None:
        ssq.mkdir(parents=True, exist_ok=True)
        (ssq / "requirements-build.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def test_unpinned_official_action_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_workflow(root, "steps:\n  - uses: actions/checkout@v4\n")
            ok, failures = workflow_actions_are_sha_pinned(root)
            self.assertFalse(ok)
            self.assertTrue(any("checkout@v4" in row for row in failures))

    def test_full_sha_official_action_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_workflow(root, "steps:\n  - uses: actions/checkout@" + "a" * 40 + " # v4\n")
            ok, failures = workflow_actions_are_sha_pinned(root)
            self.assertTrue(ok)
            self.assertEqual(failures, [])

    def test_non_exact_requirement_and_resolver_install_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ssq = root / "SSQ"
            rows = [f"{name}=={version}" for name, version in EXPECTED_BUILD_REQUIREMENTS.items()]
            rows[0] = "pyinstaller>=6.22.3"
            self.write_requirements(ssq, rows)
            self.write_workflow(root, "run: python -m pip install -r requirements-build.txt\n")
            ok, failures = build_requirements_are_frozen(ssq, root)
            self.assertFalse(ok)
            self.assertTrue(any("not exact pinned" in row for row in failures))
            self.assertTrue(any("dependency closure differs" in row for row in failures))
            self.assertTrue(any("no-deps" in row for row in failures))

    def test_exact_closure_and_no_deps_binary_only_install_are_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ssq = root / "SSQ"
            rows = [f"{name}=={version}" for name, version in EXPECTED_BUILD_REQUIREMENTS.items()]
            self.write_requirements(ssq, rows)
            self.write_workflow(
                root,
                "run: python -m pip install --no-deps --only-binary=:all: -r requirements-build.txt\n",
            )
            ok, failures = build_requirements_are_frozen(ssq, root)
            self.assertTrue(ok)
            self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
