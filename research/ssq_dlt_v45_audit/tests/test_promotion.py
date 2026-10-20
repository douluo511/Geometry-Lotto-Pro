"""The known failed source cohort cannot be laundered by local PASS fields."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from research.ssq_dlt_v45_audit import promotion as gate
from research.ssq_dlt_agent_v1 import core
from research.ssq_dlt_agent_v1.policy import AgentBlocked
from research.ssq_dlt_agent_v1.tests import test_core as fixtures


def lineage(*, plan=gate.ORIGINAL_PLAN_SHA256, semantic=None, ancestors=(), synthetic=None):
    return dict(experiment_plan_sha256=plan, canonical_plan_sha256=semantic,
                ancestor_plan_sha256=list(ancestors), synthetic_sha256=synthetic)


def proposal(source=None):
    return dict(model_id="R46-REPLICATED-PAIR", version="1.0.0", lineage=source)


class QuarantineTests(unittest.TestCase):
    def test_original_exact_source_blocked(self):
        result = gate.cohort_status(lineage())
        self.assertTrue(result["quarantined"])
        self.assertIn("ORIGINAL_FAILED_PLAN", result["reasons"])
        self.assertFalse(result["promotion_allowed"])

    def test_format_independent_identity_blocked(self):
        result = gate.cohort_status(lineage(plan="a"*64, semantic=gate.ORIGINAL_SEMANTIC_SHA256))
        self.assertIn("SAME_PLAN_WITH_DIFFERENT_SERIALIZATION", result["reasons"])

    def test_derived_cohort_blocked(self):
        result = gate.cohort_status(lineage(plan="b"*64, ancestors=[gate.ORIGINAL_PLAN_SHA256]))
        self.assertIn("DESCENDANT_OF_FAILED_PLAN", result["reasons"])

    def test_reused_exposed_synthetic_blocked(self):
        result = gate.cohort_status(lineage(plan="b"*64, synthetic=gate.ORIGINAL_SYNTHETIC_SHA256))
        self.assertIn("REUSED_EXPOSED_SYNTHETIC_EVIDENCE", result["reasons"])

    def test_no_global_ban_by_model_name(self):
        unrelated = gate.selection_result([proposal(lineage(plan="c"*64))])
        source = unrelated["proposals"][0]["source_gate"]
        self.assertFalse(source["quarantined"])
        self.assertEqual(source["status"], "NO_KNOWN_QUARANTINE_MATCH_NOT_ADMITTED")
        self.assertFalse(unrelated["promotion_allowed"])

    def test_missing_lineage_not_exonerated(self):
        result = gate.selection_result([proposal()])
        self.assertIsNone(result["proposals"][0]["source_gate"]["quarantined"])
        self.assertIsNone(result["selected_candidate"])

    def test_integrity_pass_cannot_clear_quarantine(self):
        source = lineage()
        source["integrity_pass"] = True
        with self.assertRaises(gate.PromotionBlocked):
            gate.cohort_status(source)

    def test_new_seed_and_larger_family_cannot_clear_original(self):
        for field in ("seed", "holm_family", "cause", "clearance", "status"):
            source = lineage()
            source[field] = "PASS"
            with self.subTest(field=field), self.assertRaises(gate.PromotionBlocked):
                gate.cohort_status(source)

    def test_one_new_primary_is_round_wide(self):
        with self.assertRaisesRegex(gate.PromotionBlocked, "AT_MOST_ONE"):
            gate.selection_result([proposal(lineage()), proposal(lineage(plan="d"*64))])

    def test_registry_copy_cannot_change_policy(self):
        value = gate.registry()
        value["cohorts"][0]["status"] = "PASS"
        value["cohorts"].clear()
        self.assertEqual(gate.registry()["cohorts"][0]["status"], "QUARANTINED_SOURCE_COHORT")

    def test_plan_bytes_are_bound_and_not_executed(self):
        raw = b'{"do_not_execute":"raise SystemExit()","seed":1}\n'
        result = gate.lineage_from_bytes(raw)
        self.assertEqual(result["experiment_plan_sha256"], hashlib.sha256(raw).hexdigest())
        other = gate.lineage_from_bytes(b'{ "seed": 1, "do_not_execute": "raise SystemExit()" }')
        self.assertEqual(result["canonical_plan_sha256"], other["canonical_plan_sha256"])
        self.assertNotEqual(result["experiment_plan_sha256"], other["experiment_plan_sha256"])

    def test_duplicate_or_nonfinite_plan_refused(self):
        for raw in (b'{"seed":1,"seed":2}', b'{"seed":NaN}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(gate.PromotionBlocked):
                gate.lineage_from_bytes(raw)

    def test_invalid_ancestry_and_hash_refused(self):
        for source in (lineage(plan="bad"), lineage(ancestors=["z"*64]),
                       lineage(ancestors=["e"*64,"e"*64])):
            with self.subTest(source=source), self.assertRaises(gate.PromotionBlocked):
                gate.cohort_status(source)

    def test_original_synthetic_twelve_never_formal_twelve(self):
        value = gate.registry()
        self.assertEqual(value["cohorts"][0]["family_namespace"], "ORIGINAL_SYNTHETIC_NEGATIVE_12_NOT_FORMAL_12")
        result = gate.selection_result([proposal(lineage())])
        self.assertTrue(result["original_formal_twelve"].startswith("BLOCKED"))
        self.assertEqual(result["new_primary_challengers_activated"], 0)


class ExistingEntryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctx = core.AgentContext(fixtures.setup_config(self.root), "quarantine-integration",
                                     clock=lambda: fixtures.NOW)

    def test_existing_audit_tool_exposes_retained_failure(self):
        result = self.ctx.call_tool("audit_experiment", {"action":"inspect", "hypothesis_json":""})
        self.assertEqual(result["status"], "AUDIT_CHECKED")
        evidence = self.ctx._result("audit_experiment")["evidence"]
        self.assertEqual(evidence["known_quarantines"], gate.registry())
        self.assertEqual(evidence["model_selection"]["selected_candidate"], None)

    def test_existing_json_html_report_entry_contains_gate(self):
        report = self.ctx.evidence_report()
        self.assertEqual(report["model_selection"], gate.selection_result([]))
        page = core.render_html(report)
        self.assertIn("69／2880", page)
        self.assertIn("UNRESOLVED", page)
        self.assertIn(gate.ORIGINAL_PLAN_SHA256, page)
        delivery = self.ctx.call_tool("deliver_report", {})
        self.assertEqual(delivery["status"], "REPORT_SAVED")
        self.assertEqual(report["formal_A"], 0)

    def test_report_cannot_hide_failure_or_select_candidate(self):
        for field in ("known_quarantines", "model_selection"):
            report = self.ctx.evidence_report()
            report[field] = {"status":"PASS", "selected_candidate":"R46-REPLICATED-PAIR"}
            with self.subTest(field=field), self.assertRaisesRegex(AgentBlocked, "QUARANTINE_REPORT"):
                core.render_html(report)

    def test_gate_sources_part_of_existing_code_pin(self):
        manifest = core.code_manifest()
        relative = "ssq_dlt_v45_audit/promotion.py"
        self.assertIn(relative, manifest)
        raw = Path(gate.__file__).read_bytes()
        self.assertEqual(manifest[relative], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
