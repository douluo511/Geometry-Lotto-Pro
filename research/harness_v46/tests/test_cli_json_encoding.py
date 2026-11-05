"""Structured CLI stdout must survive strict UTF-8 readers on every locale.

Business results are synthetic; public mains, process stdout, serialization,
and the strict workspace JSON reader are real. No collector or forecast runs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.harness_v46 import closed_loop


ROOT = Path(__file__).resolve().parents[3]
ENCODINGS = ("cp936", "cp1252", "ascii", "utf-8")
MESSAGES = {
    "chinese": "\u56fd\u5bb6\u4f53\u5f69\u4e2d\u5fc3\u8fd4\u56de\u5185\u5bb9\u7c7b\u578b\u9519\u8bef",
    "mixed_non_bmp": "\u4f53\u5f69\u6e90 \u2014 caf\u00e9 \U0001f680 \U00020000",
}
RUN_MAIN = """
import json
import sys
from unittest.mock import patch
from research.harness_v46 import closed_loop, desktop

mode, fixture, location = sys.argv[1:]
result = json.loads(fixture)
if mode == "desktop":
    with patch.object(desktop.DesktopController, "read_status", return_value=result):
        raise SystemExit(desktop.main(["--config", location, "--status-json"]))
else:
    boundary = "operational_tick" if mode == "operational" else "advance_workspace"
    args = ["--workspace", location]
    if mode == "operational":
        args.append("--operational-tick")
    with patch.object(closed_loop, boundary, return_value=result):
        raise SystemExit(closed_loop.main(args))
"""


class CliJsonEncodingTests(unittest.TestCase):
    def assert_json_stdout(self, mode, expected, encoding):
        with tempfile.TemporaryDirectory(prefix="v47-cli-encoding-") as folder:
            base = Path(folder).resolve()
            workspace = base / "workspace"
            workspace.mkdir()
            location = workspace
            if mode == "desktop":
                # Validate real paths before the inert status boundary. Resolve
                # the interpreter for CI hosts that expose it through a symlink.
                location = base / "config.json"
                location.write_text(json.dumps({
                    "repository_root": str(ROOT),
                    "python_exe": str(Path(sys.executable).resolve(strict=True)),
                    "workspace": str(workspace),
                    "log_path": str(base / "bot.log"),
                    "operational_tick": True,
                    "intake_timeout_seconds": 30,
                }), encoding="utf-8")
            env = dict(os.environ, PYTHONIOENCODING=encoding,
                       PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, "-B", "-c", RUN_MAIN, mode,
                 json.dumps(expected, ensure_ascii=True), str(location)],
                cwd=ROOT, env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0,
                             result.stderr.decode("ascii", errors="backslashreplace"))
            self.assertEqual(result.stderr, b"")
            try:
                text = result.stdout.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                self.fail(f"CLI stdout violates strict UTF-8 under {encoding}: {exc}")
            self.assertEqual(json.loads(text), expected)
            output = base / "stdout.json"
            output.write_bytes(result.stdout)
            self.assertEqual(closed_loop._read_json(output), expected)

    def test_operational_main_json_is_utf8_and_preserves_unicode(self):
        for encoding in ENCODINGS:
            for case, message in MESSAGES.items():
                with self.subTest(encoding=encoding, case=case):
                    expected = {
                        "schema": "V47-OPERATIONAL-TICK-SHADOW-1",
                        "tick_id": "V47T-0123456789abcdef0123456789abcdef",
                        "games": {"DLT": {"source_status": "BLOCKED",
                                          "source_errors": {"national": message}}},
                        "formal_A": 0, "decision": "NO_EDGE",
                    }
                    self.assert_json_stdout("operational", expected, encoding)

    def test_normal_main_json_is_utf8_and_preserves_unicode(self):
        for encoding in ENCODINGS:
            for case, message in MESSAGES.items():
                with self.subTest(encoding=encoding, case=case):
                    expected = {
                        "schema": "V47-SHADOW-CLOSED-LOOP-1",
                        "status": "WAITING_FOR_OUTCOME",
                        "pending_run_count": 1, "source_error": message,
                        "formal_A": 0, "decision": "NO_EDGE",
                    }
                    self.assert_json_stdout("normal", expected, encoding)

    def test_desktop_status_json_is_utf8_and_preserves_unicode(self):
        for encoding in ENCODINGS:
            for case, message in MESSAGES.items():
                with self.subTest(encoding=encoding, case=case):
                    expected = {
                        "status": "READY", "latest_complete_tick": {
                            "tick_id": "V47T-0123456789abcdef0123456789abcdef",
                            "games": {"DLT": {"source_errors": {"national": message}}}},
                        "unfinished_tick_ids": [], "operational_attempt_count": 1,
                        "formal_future_denominator": "NOT_VERIFIED",
                        "formal_A": 0, "decision": "NO_EDGE",
                    }
                    self.assert_json_stdout("desktop", expected, encoding)


if __name__ == "__main__":
    unittest.main()
