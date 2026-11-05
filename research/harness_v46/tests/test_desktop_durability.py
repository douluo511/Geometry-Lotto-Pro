"""Disposable real children exercise evidence survival, never operational CLI."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from research.harness_v46 import desktop


REAL_POPEN = subprocess.Popen
ROOT = Path(__file__).resolve().parents[3]
OUT = b"emitted\xff\n"
ERR = b"diagnostic\xfe\n"


class ControllerInterrupted(BaseException):
    """A controlled interruption of the caller path, not whole-process death."""


class InterruptOnce:
    def __init__(self, process, ready):
        self.process, self.ready, self.interrupted = process, ready, False

    def __getattr__(self, name):
        return getattr(self.process, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _interrupt(self):
        if not self.interrupted:
            deadline = time.monotonic() + 5
            while not self.ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if not self.ready.exists():
                raise AssertionError("fixture child never emitted its sentinel")
            self.interrupted = True
            raise ControllerInterrupted("controlled caller interruption after emission")

    def wait(self, timeout=None):
        self._interrupt()
        return self.process.wait(timeout=timeout)

    def communicate(self, *args, **kwargs):
        self._interrupt()
        return self.process.communicate(*args, **kwargs)


class DesktopDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v47-durable-")
        self.base = Path(self.tmp.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        cfg = self.base / "config.json"
        cfg.write_text(json.dumps({"repository_root": str(ROOT),
            "python_exe": str(Path(sys.executable).resolve()),
            "workspace": str(self.workspace), "log_path": str(self.base / "bot.log"),
            "operational_tick": True}), encoding="utf-8")
        self.controller = desktop.DesktopController(cfg)
        self.children = []
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.reap_fixtures)

    def reap_fixtures(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    stream.close()

    def command(self, *, sleep=0, code=0):
        self.ready = self.base / "emitted.ready"
        script = ("import os,time,pathlib;os.write(1,b'emitted\\xff\\n');"
                  "os.write(2,b'diagnostic\\xfe\\n');"
                  f"pathlib.Path({str(self.ready)!r}).write_bytes(b'ready');"
                  f"time.sleep({sleep!r});raise SystemExit({code!r})")
        return [str(Path(sys.executable).resolve()), "-B", "-c", script]

    def spawn(self, command, **kwargs):
        self.assertEqual(Path(command[0]), Path(sys.executable).resolve())
        self.assertIn("emitted", command[-1], "only the literal fixture child may run")
        child = REAL_POPEN(command, **kwargs)
        self.children.append(child)
        return child

    def read_json(self, folder, name):
        return json.loads((folder / name).read_text(encoding="utf-8"))

    def test_interrupted_caller_retains_prelaunch_intent_and_emitted_binary_bytes(self):
        # Removing prelaunch/file-backed persistence must lose this real output.
        command = self.command(sleep=30)
        folder = self.workspace / "interrupted"
        def spawn(command, **kwargs):
            return InterruptOnce(self.spawn(command, **kwargs), self.ready)
        with patch.object(subprocess, "Popen", spawn):
            with self.assertRaises(ControllerInterrupted):
                self.controller._execute(command, folder, timeout=10)
        self.assertTrue((folder / "launch-intent.json").exists(), "launch intent lost")
        self.assertEqual((folder / "stdout.bin").read_bytes(), OUT)
        self.assertEqual((folder / "stderr.bin").read_bytes(), ERR)
        self.assertFalse((folder / "receipt.json").exists(), "interruption fabricated a terminal receipt")
        identity = self.read_json(folder, "child-identity.json")
        self.assertEqual(identity["pid"], self.children[0].pid)

    def test_normal_and_nonzero_exit_publish_only_actually_observed_codes(self):
        for code, status in [(0, "COMPLETED"), (7, "FAILED")]:
            with self.subTest(code=code):
                folder = self.workspace / str(code)
                with patch.object(subprocess, "Popen", self.spawn):
                    result = self.controller._execute(self.command(code=code), folder, timeout=5)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["returncode"], code)
                self.assertIs(result.get("process_started"), True)
                self.assertIs(result.get("exit_observed"), True)
                self.assertEqual(result.get("observed_child_returncode"), code)
                self.assertEqual(result.get("process_state"), "EXIT_OBSERVED")
                self.assertEqual((folder / "stdout.bin").read_bytes(), OUT)
                self.assertEqual((folder / "stderr.bin").read_bytes(), ERR)
                intent = self.read_json(folder, "launch-intent.json")
                self.assertEqual(intent["schema"], "V47-CONTROLLER-LAUNCH-INTENT-1")
                self.assertEqual(intent["command"], result["command"])
                self.assertEqual(intent["formal_A"], 0)
                self.assertEqual(intent["decision"], "NO_EDGE")

    def test_child_creation_identity_comes_from_the_owned_windows_handle(self):
        folder = self.workspace / "identity"
        with patch.object(subprocess, "Popen", self.spawn):
            self.controller._execute(self.command(), folder, timeout=5)
        self.assertTrue((folder / "child-identity.json").exists(), "child identity not persisted")
        saved = self.read_json(folder, "child-identity.json")
        self.assertEqual(saved["schema"], "V47-CONTROLLER-CHILD-IDENTITY-1")
        self.assertEqual(saved["pid"], self.children[0].pid)
        if os.name == "nt":
            from ctypes import wintypes
            stamp, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            get_times = ctypes.WinDLL("kernel32", use_last_error=True).GetProcessTimes
            get_times.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            get_times.restype = wintypes.BOOL
            self.assertTrue(get_times(int(self.children[0]._handle), ctypes.byref(stamp),
                                     ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)))
            expected = (stamp.dwHighDateTime << 32) | stamp.dwLowDateTime
            self.assertEqual(saved["identity_status"], "VERIFIED_LOCAL_OS_HANDLE")
            self.assertEqual(saved["creation_filetime_100ns"], expected)
        else:
            self.assertEqual(saved["identity_status"], "NOT_VERIFIED")
            self.assertIsNone(saved["creation_filetime_100ns"])

    def test_timeout_keeps_legacy_null_code_and_records_owned_cleanup_separately(self):
        folder = self.workspace / "timeout"
        with patch.object(subprocess, "Popen", self.spawn):
            result = self.controller._execute(self.command(sleep=30), folder, timeout=.5)
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIs(result["timed_out"], True)
        self.assertIsNone(result["returncode"])
        self.assertIs(result.get("process_started"), True)
        self.assertIs(result.get("exit_observed"), True)
        self.assertEqual(result.get("observed_child_returncode"), self.children[0].returncode)
        self.assertIsNotNone(self.children[0].poll())
        self.assertEqual((folder / "stdout.bin").read_bytes(), OUT)
        self.assertEqual((folder / "stderr.bin").read_bytes(), ERR)

    def test_each_existing_evidence_artifact_prevents_a_new_launch(self):
        for name in ["launch-intent.json", "child-identity.json", "stdout.bin", "stderr.bin", "receipt.json"]:
            with self.subTest(name=name):
                folder = self.workspace / name.replace(".", "-")
                folder.mkdir()
                old = folder / name
                old.write_bytes(b"immutable old evidence")
                calls = []
                def reject(*args, **kwargs):
                    calls.append(args)
                    raise AssertionError("collision launched a child")
                caught = None
                with patch.object(subprocess, "Popen", reject):
                    try:
                        self.controller._execute(self.command(), folder, timeout=5)
                    except BaseException as exc:
                        caught = exc
                self.assertEqual(calls, [], "existing evidence was checked only after launch")
                self.assertIsInstance(caught, FileExistsError)
                self.assertEqual(old.read_bytes(), b"immutable old evidence")

    def test_collision_after_intent_setup_is_rejected_before_starting_child(self):
        # An initial preflight alone misses files created during intent fsync.
        for name in ("child-identity.json", "receipt.json"):
            with self.subTest(name=name):
                folder = self.workspace / ("late-" + name.replace(".", "-"))
                old = folder / name
                old_bytes = b"pre-spawn competing evidence\xff\n"
                calls = []
                original = desktop._write_json
                def write(path, value):
                    original(path, value)
                    if path.name == "launch-intent.json":
                        old.write_bytes(old_bytes)
                def spawn(command, **kwargs):
                    self.assertEqual(old.read_bytes(), old_bytes)
                    calls.append(command)
                    return self.spawn(command, **kwargs)
                with patch.object(desktop, "_write_json", write), \
                        patch.object(subprocess, "Popen", spawn):
                    try:
                        result = self.controller._execute(self.command(sleep=30), folder, timeout=.2)
                    except FileExistsError:
                        result = None
                self.assertEqual(calls, [], "pre-spawn collision still launched a real child")
                self.assertEqual(old.read_bytes(), old_bytes)
                if result is not None:
                    self.assertIs(result["process_started"], False)
                    self.assertIs(result["exit_observed"], False)

    def test_spawn_failure_is_an_attempt_without_an_observed_child_exit(self):
        folder = self.workspace / "spawn-failure"
        with patch.object(subprocess, "Popen", side_effect=OSError("fixture spawn rejected")):
            result = self.controller._execute(self.command(), folder, timeout=5)
        self.assertEqual(result["status"], "FAILED")
        self.assertIs(result.get("process_started"), False)
        self.assertIs(result.get("exit_observed"), False)
        self.assertIsNone(result.get("observed_child_returncode"))
        self.assertEqual(result.get("process_state"), "NOT_STARTED")
        self.assertTrue((folder / "receipt.json").exists())
        self.assertTrue((folder / "launch-intent.json").exists())
        self.assertEqual((folder / "stdout.bin").read_bytes(), b"")

    def test_identity_persistence_failure_after_spawn_preserves_process_ownership(self):
        folder = self.workspace / "identity-write-failure"
        original = desktop._write_json
        def write(path, value):
            if path.name == "child-identity.json":
                raise OSError("fixture identity persistence failure")
            return original(path, value)
        def spawn(command, **kwargs):
            child = self.spawn(command, **kwargs)
            deadline = time.monotonic() + 5
            while not self.ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(self.ready.exists())
            return child
        with patch.object(subprocess, "Popen", spawn), patch.object(desktop, "_write_json", write):
            result = self.controller._execute(self.command(sleep=30), folder, timeout=.5)
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("identity persistence failure", result["error"])
        self.assertIs(result.get("process_started"), True)
        self.assertIs(result.get("exit_observed"), True)
        self.assertIsNone(result["returncode"], "cleanup code is not a normal observed operation result")
        self.assertIsNotNone(self.children[0].poll(), "owned child was leaked")
        self.assertEqual((folder / "stdout.bin").read_bytes(), OUT)

    def test_interruption_before_identity_file_keeps_intent_without_false_exit(self):
        folder = self.workspace / "identity-interrupted"
        original = desktop._write_json
        def write(path, value):
            if path.name == "child-identity.json":
                raise ControllerInterrupted("before child identity persistence")
            return original(path, value)
        with patch.object(subprocess, "Popen", self.spawn), patch.object(desktop, "_write_json", write):
            interrupted = False
            try:
                self.controller._execute(self.command(), folder, timeout=5)
            except ControllerInterrupted:
                interrupted = True
        self.assertTrue(interrupted, "child identity boundary was never persisted")
        self.assertTrue((folder / "launch-intent.json").exists())
        self.assertFalse((folder / "receipt.json").exists())

    def test_interruption_at_spawn_boundary_keeps_intent_without_claiming_a_child(self):
        folder = self.workspace / "before-spawn-interrupted"
        def interrupted(command, **kwargs):
            self.assertTrue((folder / "launch-intent.json").exists())
            raise ControllerInterrupted("fixture interruption before process creation")
        with patch.object(subprocess, "Popen", interrupted):
            with self.assertRaises(ControllerInterrupted):
                self.controller._execute(self.command(), folder, timeout=5)
        self.assertEqual(self.children, [])
        self.assertEqual((folder / "stdout.bin").read_bytes(), b"")
        self.assertFalse((folder / "child-identity.json").exists())
        self.assertFalse((folder / "receipt.json").exists())

    def test_unavailable_windows_identity_is_recorded_without_inventing_creation_time(self):
        folder = self.workspace / "identity-unavailable"
        with patch.object(subprocess, "Popen", self.spawn), patch.object(ctypes, "WinDLL",
                side_effect=OSError("fixture handle query unavailable"), create=True):
            result = self.controller._execute(self.command(), folder, timeout=5)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue((folder / "child-identity.json").exists())
        saved = self.read_json(folder, "child-identity.json")
        self.assertEqual(saved["identity_status"], "NOT_VERIFIED")
        self.assertIsNone(saved["creation_filetime_100ns"])

    def test_failed_bounded_reap_retains_timeout_and_unknown_running(self):
        folder = self.workspace / "unreaped"
        waits = []
        class Unreaped:
            pid = 987654
            returncode = None
            _handle = None
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def communicate(self, *args, **kwargs):
                raise subprocess.TimeoutExpired("fixture", .1)
            def poll(self): return None
            def kill(self): raise OSError("fixture owned handle cannot terminate")
            def wait(self, timeout=None):
                waits.append(timeout)
                raise subprocess.TimeoutExpired("fixture", timeout)
        def spawn(command, **kwargs):
            if hasattr(kwargs.get("stdout"), "write"):
                kwargs["stdout"].write(OUT)
                kwargs["stderr"].write(ERR)
            return Unreaped()
        with patch.object(subprocess, "Popen", spawn):
            result = self.controller._execute(self.command(), folder, timeout=.1)
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIsNone(result["returncode"])
        self.assertIs(result.get("exit_observed"), False)
        self.assertEqual(result.get("process_state"), "UNKNOWN_RUNNING")
        self.assertIsNone(result.get("observed_child_returncode"))
        self.assertTrue(waits and all(t is not None and 0 <= t <= 5 for t in waits))
        self.assertEqual((folder / "stdout.bin").read_bytes(), OUT)

    def test_fsync_failure_cannot_publish_a_completed_attempt(self):
        folder = self.workspace / "output-fsync-failure"
        original = os.fsync
        injected = []
        def fsync(fd):
            path = folder / "stdout.bin"
            if path.exists() and not injected and os.fstat(fd) == path.stat():
                injected.append(True)
                raise OSError("fixture output fsync failure")
            return original(fd)
        with patch.object(subprocess, "Popen", self.spawn), patch.object(os, "fsync", fsync):
            caught = None
            result = None
            try:
                result = self.controller._execute(self.command(), folder, timeout=5)
            except OSError as exc:
                caught = exc
        self.assertTrue(injected, "raw output was not fsynced")
        self.assertIsNone(caught, "failed evidence must retain an explicit failed attempt receipt")
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("output fsync failure", result["error"])
        self.assertIs(result["exit_observed"], True)
        self.assertEqual(self.read_json(folder, "receipt.json")["status"], "FAILED")

    def test_output_fsync_failure_does_not_erase_an_already_observed_timeout(self):
        folder = self.workspace / "timeout-and-fsync-failure"
        original = os.fsync
        injected = []
        def fsync(fd):
            path = folder / "stdout.bin"
            if path.exists() and not injected and os.fstat(fd) == path.stat():
                injected.append(True)
                raise OSError("fixture timeout output fsync failure")
            return original(fd)
        with patch.object(subprocess, "Popen", self.spawn), patch.object(os, "fsync", fsync):
            result = self.controller._execute(self.command(sleep=30), folder, timeout=.5)
        self.assertEqual(result["status"], "TIMEOUT", "persistence failure erased timeout classification")
        self.assertIs(result["timed_out"], True)
        self.assertIsNone(result["returncode"])
        self.assertIn("timed out", result["error"])
        self.assertIn("timeout output fsync failure", str(result["evidence_errors"]))


if __name__ == "__main__":
    unittest.main()
