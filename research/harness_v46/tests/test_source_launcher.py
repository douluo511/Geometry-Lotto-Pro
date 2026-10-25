"""Black-box regression coverage for launching the SSQ source acceptance CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPOSITORY_ROOT / "SSQ" / "launcher.py"


class SourceLauncherTests(unittest.TestCase):
    def test_corrupt_repair_acceptance_runs_from_unrelated_spaced_cwd(self):
        """The source launcher must import glp without cwd or PYTHONPATH help."""
        # Regression target: removing the launcher's source-package bootstrap
        # makes `import glp` fail because the package lives in SSQ/SSQ/glp.
        # This invokes the real synthetic acceptance path; its checks establish
        # corruption detection, isolated repair, and integrity restoration.
        evidence_result = os.environ.get("SSQ_SOURCE_LAUNCHER_RESULT_FILE")
        result_owner = None
        if evidence_result:
            result_file = Path(evidence_result)
            result_file.parent.mkdir(parents=True, exist_ok=True)
            temp_parent = result_file.parent
        else:
            result_owner = tempfile.TemporaryDirectory(prefix="ssq launcher result ")
            result_file = Path(result_owner.name) / "acceptance.json"
            temp_parent = None

        try:
            with tempfile.TemporaryDirectory(
                prefix="unrelated spaced cwd ", dir=temp_parent
            ) as cwd:
                env = os.environ.copy()
                env.pop("PYTHONPATH", None)
                # The CLI uses TemporaryDirectory for its synthetic store.
                # Keep that scratch space in the isolated unrelated cwd.
                env["TEMP"] = cwd
                env["TMP"] = cwd
                env["TMPDIR"] = cwd
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        str(LAUNCHER),
                        "--check",
                        "corrupt-repair",
                        "--result-file",
                        str(result_file),
                    ],
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )

            raw_result = result_file.read_text(encoding="utf-8") if result_file.exists() else "<missing>"
            self.assertEqual(
                completed.returncode,
                0,
                msg=(
                    f"launcher exit={completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}\n"
                    f"result:\n{raw_result}"
                ),
            )
            payload = json.loads(raw_result)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["scope"], "corrupt-repair")
            self.assertEqual(payload["test_data_classification"], "TEST_ONLY_SYNTHETIC")
            self.assertFalse(payload["real_network_tested"])
            self.assertEqual(payload["production_repair_status"], "PENDING")
            self.assertEqual(
                payload["result"]["checks"],
                {
                    "corruption_detected": True,
                    "synthetic_repair_succeeded": True,
                    "integrity_restored_in_temporary_store": True,
                    "synthetic_raw_hashes_match": True,
                    "synthetic_canonical_verified": True,
                    "two_source_fixture_quorum": True,
                    "transport_isolation": True,
                },
            )
        finally:
            if result_owner is not None:
                result_owner.cleanup()


if __name__ == "__main__":
    unittest.main()
