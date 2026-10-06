from __future__ import annotations

import inspect
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import updater as updater_module
from glp.delivery import UPDATER_NAME, UpdaterClient
from glp.gui import NativeApp
from glp.service import LottoService


class RestoredUpdaterContractTests(unittest.TestCase):
    def test_atomic_updater_self_test_passes_without_network(self) -> None:
        result = updater_module.software_self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["checks"]["atomic_replace_success"])
        self.assertTrue(result["checks"]["forced_validation_failure_rolls_back"])
        self.assertTrue(result["checks"]["rollback_hash_restored"])

    def test_gui_routes_update_and_repair_to_independent_updater(self) -> None:
        source = inspect.getsource(NativeApp.__init__)
        self.assertIn("self.updater = updater or UpdaterClient", source)
        self.assertIn("self.updater.update", source)
        self.assertIn("self.updater.repair", source)
        self.assertNotIn('BTN_UPDATE: ("一键更新", self.service.update', source)
        self.assertNotIn('BTN_REPAIR: ("一键修复", self.service.repair', source)

    def test_updater_client_uses_independent_binary_name_when_frozen(self) -> None:
        self.assertEqual(UPDATER_NAME, "Geometry_Lotto_Pro_DLT_Updater.exe")

    def test_source_mode_updater_path_exists_on_current_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dlt-updater-client-") as td:
            client = UpdaterClient(
                updater_path=Path(__file__).resolve().parents[1] / "src" / "updater.py",
                data_dir=Path(td),
            )
            prefix = client._command_prefix()
            self.assertGreaterEqual(len(prefix), 2)
            self.assertTrue(prefix[-1].endswith("updater.py"))

    def test_repair_failure_is_persisted_without_false_pass(self) -> None:
        class FakeStore:
            def __init__(self) -> None:
                self.experiments = []

            def integrity_check(self):
                return {
                    "status": "FAIL",
                    "checks": [
                        {"name": "SQLite integrity", "status": "PASS"},
                        {"name": "Freeze archive", "status": "PASS"},
                        {"name": "Canonical hash", "status": "FAIL"},
                        {"name": "Source evidence", "status": "PASS"},
                    ],
                }

            def append_experiment(self, *args):
                self.experiments.append(args)

        store = FakeStore()
        service = LottoService(store=store)
        service.update = lambda progress=None: (_ for _ in ()).throw(
            RuntimeError("injected offline source failure")
        )

        with self.assertRaisesRegex(RuntimeError, "injected offline source failure"):
            service.repair()

        repair_rows = [row for row in store.experiments if row[0] == "repair"]
        self.assertEqual(len(repair_rows), 1)
        kind, status, _input_hash, _version, payload = repair_rows[0]
        self.assertEqual(kind, "repair")
        self.assertEqual(status, "FAIL")
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertIn("injected offline source failure", payload["error"])
        self.assertNotEqual(status, "PASS")

    def test_audit_is_observational_and_never_writes_formal_freeze(self) -> None:
        class FakeStore:
            def __init__(self) -> None:
                self._freezes = [object(), object()]
                self.experiments = []

            def integrity_check(self):
                return {"status": "PASS"}

            def load_draws(self):
                return [], "canonical-hash"

            def prospective_replays(self, selector_hash):
                self.selector_hash = selector_hash
                return []

            def freezes(self):
                return list(self._freezes)

            def append_experiment(self, *args):
                self.experiments.append(args)

        store = FakeStore()
        service = LottoService(store=store)
        service.ensure_seed = lambda: None

        court = {
            "software_verdict": "PASS",
            "scientific_gate": "PASS",
            "model_hash": "model-hash",
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
        }
        with patch("glp.service.model_identity", return_value={"selector_hash": "selector"}), \
             patch("glp.service.run_evidence_court", return_value=court), \
             patch("glp.service.make_prediction", return_value=(object(), {"trace": "shadow"})), \
             patch("glp.service.build_ors_record", return_value={"ors": "PASS"}):
            result = service.audit()

        self.assertFalse(result["formal_freeze_written"])
        self.assertEqual(result["freeze_before"], 2)
        self.assertEqual(result["freeze_after"], 2)
        self.assertEqual(len(store.freezes()), 2)
        self.assertEqual(result["court"]["edge_state"], "NO_EDGE")
        self.assertEqual(result["court"]["software_verdict"], "PASS")
        self.assertEqual(len(store.experiments), 1)


if __name__ == "__main__":
    unittest.main()
