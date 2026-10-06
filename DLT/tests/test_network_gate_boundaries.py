"""A negative test must fail for its intended reason, not any exception."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NetworkGateBoundaryTests(unittest.TestCase):
    def assert_transport_error_cannot_pass_parser_gate(self, script, check):
        path = Path(__file__).resolve().parents[1] / "scripts" / (script + ".py")
        spec = importlib.util.spec_from_file_location(script, path)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        with tempfile.TemporaryDirectory(prefix="dlt-negative-gate-") as td:
            with patch.object(gate, "ROOT", Path(td)), patch.object(
                gate.sources, "fetch_national_page",
                side_effect=gate.SourceError("unrelated transport failure"),
            ), contextlib.redirect_stdout(io.StringIO()):
                result = gate.main()
            report = json.loads((Path(td) / "artifacts" / (script + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(report["checks"][check]["status"], "FAIL")
            self.assertFalse(report["real_network_evidence"])

    def test_malformed_row_check_rejects_unrelated_transport_error(self):
        self.assert_transport_error_cannot_pass_parser_gate(
            "network_contract_gate", "malformed_row_fail_closed"
        )

    def test_duplicate_row_check_rejects_unrelated_transport_error(self):
        self.assert_transport_error_cannot_pass_parser_gate(
            "network_fault_gate", "duplicate_issue_fail_closed"
        )


if __name__ == "__main__":
    unittest.main()
