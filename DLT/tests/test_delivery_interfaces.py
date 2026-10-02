from __future__ import annotations

import base64
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from glp.delivery import (
    UpdaterClient, create_backup, export_evidence, launch_software_update,
    read_software_update_result, restore_backup, source_health, verify_export,
)
from glp.domain import CanonicalDataset, Draw
from glp.net_client import NetClient
from glp.service import LottoService
from glp.storage import Store
from glp.util import sha256_bytes, sha256_json
import updater as updater_module


def seeded_store(root: Path) -> Store:
    store = Store(root)
    draw = Draw(issue="26001", draw_date="2026-01-03", front=(1, 2, 3, 4, 5), back=(1, 2))
    digest = sha256_json([draw.to_dict()])
    dataset = CanonicalDataset(
        draws=[draw],
        canonical_hash=digest,
        receipts=[],
        crosscheck_count=1,
        crosscheck_status="PASS",
    )
    raw = b'{"official":true,"issue":"26001"}'
    evidence = {
        "canonical_hash": digest,
        "crosscheck_status": "PASS",
        "crosscheck_count": 1,
        "draw_count": 1,
        "latest": {"issue": "26001"},
        "raw_responses": [{
            "http_status": 200,
            "body_b64": base64.b64encode(raw).decode("ascii"),
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
            "final_url": "https://example.invalid/official",
            "fetched_at": "2026-01-03T12:00:00Z",
            "parser_version": "test-parser-v1",
            "validation_result": "PASS",
        }],
    }
    store.save_dataset(dataset, evidence)
    return store


class FrozenInterfaceTests(unittest.TestCase):
    def test_netclient_get_contract_parameter_order(self):
        params = list(inspect.signature(NetClient.get).parameters)
        self.assertEqual(
            params,
            ["self", "url", "params", "headers", "timeout", "allow_redirects"],
        )

    def test_required_interfaces_are_real_callables(self):
        self.assertTrue(callable(Draw.from_dict))
        self.assertTrue(callable(Draw.validate))
        for name in (
            "save_dataset", "load_draws", "integrity_check",
            "baseline_integrity_check", "validate_raw_evidence",
        ):
            self.assertTrue(callable(getattr(Store, name)))
        for name in ("update", "predict", "audit", "repair", "self_test"):
            self.assertTrue(callable(getattr(LottoService, name)))
        for name in ("update", "repair"):
            self.assertTrue(callable(getattr(UpdaterClient, name)))
        for fn in (
            launch_software_update, read_software_update_result,
            create_backup, restore_backup, export_evidence, verify_export,
            source_health,
        ):
            self.assertTrue(callable(fn))

    def test_updater_console_summary_is_cp1252_safe_and_excludes_raw_payload(self):
        huge = "中文原始证据" * 10000
        value = {
            "schema": "dlt-independent-updater-v1",
            "status": "PASS",
            "mode": "data-update",
            "pid": 123,
            "parent_pid": 45,
            "parent_pid_match": True,
            "updater_exe_sha256": "a" * 64,
            "github_sha": "b" * 40,
            "github_run_id": "999",
            "version": "2.1.2",
            "service_result": {
                "status": "PASS",
                "network_gate": "PASS",
                "crosscheck_status": "PASS",
                "latest": {"issue": "26112"},
                "draw_count": 2926,
                "raw_responses": [{"body_b64": huge}],
            },
        }
        line = updater_module._console_line(value)
        line.encode("cp1252")
        self.assertLess(len(line), 5000)
        self.assertNotIn("raw_responses", line)
        self.assertNotIn("body_b64", line)
        self.assertIn('"network_gate": "PASS"', line)
        self.assertIn('"latest_issue": "26112"', line)

    def test_service_self_test_never_modifies_user_store(self):
        with tempfile.TemporaryDirectory(prefix="dlt-service-selftest-contract-") as td:
            root = Path(td) / "user-data"
            store = Store(root)
            before = {
                p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()
            }
            result = LottoService(store).self_test()
            after = {
                p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()
            }
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["production_store_modified"])
            self.assertEqual(before, after)

    def test_raw_evidence_reloads_bytes_and_fails_on_tamper(self):
        with tempfile.TemporaryDirectory(prefix="dlt-raw-contract-") as td:
            store = seeded_store(Path(td))
            self.assertEqual(store.baseline_integrity_check()["status"], "PASS")
            self.assertEqual(store.validate_raw_evidence()["status"], "PASS")
            evidence = json.loads(store.evidence_path.read_text(encoding="utf-8"))
            evidence["raw_responses"][0]["sha256"] = "0" * 64
            self.assertEqual(store.validate_raw_evidence(evidence)["status"], "FAIL")

    def test_backup_restore_is_verified_and_rolls_forward_only_valid_bytes(self):
        with tempfile.TemporaryDirectory(prefix="dlt-backup-contract-") as td:
            root = Path(td) / "data"
            store = seeded_store(root)
            backup = create_backup(root, Path(td) / "backup")
            self.assertEqual(backup["status"], "PASS")
            original = store.history_path.read_bytes()
            store.history_path.write_bytes(b'{"corrupt":true}\n')
            self.assertEqual(Store(root).integrity_check()["status"], "FAIL")
            restored = restore_backup(Path(backup["backup_dir"]), root)
            self.assertEqual(restored["status"], "PASS")
            self.assertEqual((root / "canonical_history.json").read_bytes(), original)
            self.assertEqual(Store(root).integrity_check()["status"], "PASS")

    def test_evidence_export_is_hash_bound_and_reverified(self):
        with tempfile.TemporaryDirectory(prefix="dlt-export-contract-") as td:
            root = Path(td) / "data"
            seeded_store(root)
            exported = export_evidence(root, Path(td) / "export")
            self.assertEqual(exported["status"], "PASS")
            checked = verify_export(Path(exported["export_dir"]))
            self.assertEqual(checked["status"], "PASS")
            history = Path(exported["export_dir"]) / "canonical_history.json"
            history.write_bytes(history.read_bytes() + b"tamper")
            with self.assertRaises(ValueError):
                verify_export(Path(exported["export_dir"]))


if __name__ == "__main__":
    unittest.main()
