"""Workflow ordering contracts, not proof of a real GitHub Release."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ssq-windows-build-acceptance.yml"


class PublicationContractTests(unittest.TestCase):
    def test_promotion_follows_durable_audit_and_exe_uploads(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        audit = text.index("- name: Upload final audit evidence before release artifact")
        exe = text.index("- name: Upload final EXE only after all hard gates and audit upload pass")
        promotion = text.index("- name: Promote independent release only after Final Gate and evidence uploads PASS")
        self.assertLess(audit, exe)
        self.assertLess(exe, promotion)
        clause = text[promotion:]
        self.assertIn("steps.final_audit_upload.outcome == 'success'", clause)
        self.assertIn("steps.final_exe_upload.outcome == 'success'", clause)
        self.assertIn("steps.final_audit_upload.outputs.artifact-id", clause)
        self.assertIn("steps.final_exe_upload.outputs.artifact-id", clause)

    def test_prerelease_is_bound_to_tested_commit(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        create_lines = [line for line in text.splitlines() if "gh release create " in line]
        self.assertEqual(len(create_lines), 1)
        self.assertIn("--target $env:GITHUB_SHA", create_lines[0])
        self.assertIn("--prerelease", create_lines[0])


if __name__ == "__main__":
    unittest.main()
