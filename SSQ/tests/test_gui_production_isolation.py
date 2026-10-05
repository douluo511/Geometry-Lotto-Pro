"""Test-only doubles. These are not live network or physical GUI evidence."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import queue
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "SSQ"))
from verify_gui_payload import inspect_exe, inspect_gui_code
from release_gate_22 import HARD_GATES
from derive_gate_status import derive

if os.name == "nt":
    from glp import gui


def production_code():
    return compile((ROOT / "SSQ" / "glp" / "gui.py").read_text(encoding="utf-8"),
                   "glp/gui.py", "exec")


class PayloadIsolationTests(unittest.TestCase):
    def test_real_gui_source_has_no_doubles_and_only_narrow_scope(self):
        proof = inspect_gui_code(production_code())
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["full_no_shell_status"], "PENDING")
        self.assertEqual(proof["scope"], "GUI_TEST_DOUBLE_ISOLATION_ONLY")

    def test_nested_test_double_is_rejected(self):
        clean = (ROOT / "SSQ" / "glp" / "gui.py").read_text(encoding="utf-8")
        for injected in (
            "\ndef diagnostic():\n    class _ServiceSpy: pass\n",
            "\ndef diagnostic():\n    from unittest.mock import MagicMock\n",
            "\ndef diagnostic():\n    updater_spy = None\n",
        ):
            with self.subTest(injected=injected):
                with self.assertRaisesRegex(ValueError, "test doubles"):
                    inspect_gui_code(compile(clean + injected, "injected.py", "exec"))

    def test_empty_or_scope_less_module_cannot_pass(self):
        with self.assertRaises(ValueError):
            inspect_gui_code(compile("pass", "empty.py", "exec"))
        text = (ROOT / "SSQ" / "glp" / "gui.py").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "scope boundary"):
            inspect_gui_code(compile(text.replace("NATIVE_SURFACE_ONLY", "ALL_PASS"),
                                     "wrong.py", "exec"))
        with self.assertRaises(ValueError):
            inspect_gui_code(b"not a code object")

    def test_archive_inspection_is_hash_bound_and_rejects_packaged_tests(self):
        # Controlled archive-reader seam only; native CI reads the real EXE.
        reader = ModuleType("PyInstaller.archive.readers")
        pyz = SimpleNamespace(toc={"glp.gui": (0, 0, 0)},
                              extract=Mock(side_effect=lambda name, raw=False:
                                           b"TEST_ONLY_PAYLOAD" if raw else production_code()))
        archive = SimpleNamespace(toc={"PYZ.pyz": (0, 0, 0, 0, "z")},
                                  open_embedded_archive=Mock(return_value=pyz))
        reader.CArchiveReader = Mock(return_value=archive)
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "fixture.bin"
            exe.write_bytes(b"TEST_ONLY_NOT_AN_EXE")
            with patch.dict(sys.modules, {"PyInstaller.archive.readers": reader}):
                proof = inspect_exe(exe)
                self.assertEqual(proof["exe_sha256"], hashlib.sha256(exe.read_bytes()).hexdigest())
                self.assertEqual(proof["full_no_shell_status"], "PENDING")
                for name in ("tests.test_gui_production_isolation", "test_routing", "glp.tests.fake"):
                    pyz.toc[name] = (0, 0, 0)
                    with self.assertRaisesRegex(ValueError, "test modules"):
                        inspect_exe(exe)
                    del pyz.toc[name]
                pyz.extract.side_effect = None
                pyz.extract.return_value = None
                with self.assertRaises(ValueError):
                    inspect_exe(exe)
                archive.toc["second.pyz"] = (0, 0, 0, 0, "z")
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    inspect_exe(exe)

    def test_payload_gate_is_mandatory(self):
        self.assertIn("production_gui_payload", HARD_GATES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = derive(root, root / "missing.exe")
        self.assertEqual(report["gates"]["production_gui_payload"], "FAIL")
        self.assertNotEqual(report["gates"]["no_shell"], "PASS")


@unittest.skipUnless(os.name == "nt", "Win32 routing requires Windows; not live GUI acceptance")
class GuiRoutingUnitTests(unittest.TestCase):
    def make_app(self):
        # No real window is created by these deterministic routing unit tests.
        app = gui.NativeApp.__new__(gui.NativeApp)
        app.service = SimpleNamespace(predict=Mock(), audit=Mock())
        app.updater = SimpleNamespace(update=Mock(), repair=Mock())
        app._start = Mock()
        return app

    def test_all_four_button_routes_remain_bound(self):
        app = self.make_app()
        for cid, owner, method, renderer in (
            (gui.BTN_PREDICT, app.service, "predict", "_render_prediction"),
            (gui.BTN_UPDATE, app.updater, "update", "_render_update"),
            (gui.BTN_REPAIR, app.updater, "repair", "_render_repair"),
            (gui.BTN_AUDIT, app.service, "audit", "_render_audit"),
        ):
            with self.subTest(cid=cid):
                self.assertEqual(app._wndproc(None, gui.WM_COMMAND, cid, 0), 0)
                args = app._start.call_args.args
                self.assertIs(args[1], getattr(owner, method))
                self.assertEqual(args[2], getattr(app, renderer))

    def test_error_event_never_displays_completion(self):
        app = self.make_app()
        app.events = queue.Queue()
        app.busy = True
        app._set_text = Mock()
        app._enable_buttons = Mock()
        app.events.put(("error", ("operation", "source quorum failed")))
        app._drain()
        texts = [row.args[1] for row in app._set_text.call_args_list]
        self.assertTrue(any("Fail-Closed" in text for text in texts))
        self.assertTrue(any("FAIL" in text for text in texts))
        self.assertFalse(app.busy)
        app._enable_buttons.assert_called_once_with(True)

    def test_renderer_exception_never_displays_completion(self):
        app = self.make_app()
        app.events = queue.Queue()
        app.busy = True
        app._set_text = Mock()
        app._enable_buttons = Mock()
        app.events.put(("done", ("operation", {}, Mock(side_effect=ValueError("invalid result")))))
        app._drain()
        app._set_text.assert_any_call(gui.STATUS_STATIC, "operation\uff1aFAIL")
        self.assertFalse(app.busy)

    def test_surface_check_rejects_a_test_double(self):
        result = gui.gui_self_test(SimpleNamespace())
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["business_actions_executed"])
        self.assertFalse(result["real_network_tested"])
        self.assertEqual(result["physical_click_status"], "PENDING")
        self.assertEqual(result["full_no_shell_status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
