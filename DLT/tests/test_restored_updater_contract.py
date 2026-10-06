from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import updater as updater_module
from glp.delivery import UPDATER_NAME, UpdaterClient
from glp.gui import NativeApp


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


if __name__ == "__main__":
    unittest.main()
