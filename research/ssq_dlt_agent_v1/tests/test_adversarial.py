"""Independent adversarial host checks; no network, API or real history reads."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from research.ssq_dlt_agent_v1.core import AgentContext
from research.ssq_dlt_agent_v1.policy import AgentBlocked


class AdversarialHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glp-agent-adversarial-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = dict(state_dir=str(root / "state"), live_sources=False,
            history={game:dict(path=str(root / "inputs" / (game + ".json")),
                               sha256="0" * 64) for game in ("SSQ", "DLT")})
        self.now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)

    def context(self, **kwargs):
        return AgentContext(self.config, "adversarial-fixed-run", clock=lambda:self.now, **kwargs)

    def test_concurrent_identical_execution_claim_has_one_owner(self):
        first, second = self.context(), self.context()
        barrier = threading.Barrier(2)

        def claimant(ctx):
            original = ctx.ledger.read
            def read(kind, key):
                result = original(kind, key)
                if kind == "execution":
                    barrier.wait(timeout=10)
                return result
            try:
                with patch.object(ctx, "_guard"), patch.object(ctx.ledger, "read", side_effect=read):
                    return ("OWNER" if ctx.claim_execution() is None else "REUSED")
            except AgentBlocked as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claimant, (first, second)))
        self.assertEqual(results.count("OWNER"), 1, results)
        self.assertIn("UNKNOWN_EXECUTION_OUTCOME_REQUIRES_RECONCILIATION", results)
        self.assertEqual(len(first.ledger.rows("execution")), 1)

    def test_concurrent_identical_tool_does_not_repeat_an_inflight_effect(self):
        first, second = self.context(), self.context()
        started, release = threading.Event(), threading.Event()
        effects = []
        def perform(name, arguments):
            effects.append(name)
            started.set()
            self.assertTrue(release.wait(timeout=10))
            return {"status":"SUCCESS"}, {"status":"SUCCESS"}
        with patch.object(first, "_guard"), patch.object(second, "_guard"), \
             patch.object(first, "_perform", side_effect=perform), \
             patch.object(second, "_perform", side_effect=perform):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(first.call_tool, "discover_sources", {})
                self.assertTrue(started.wait(timeout=10))
                try:
                    with self.assertRaisesRegex(AgentBlocked, "UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION"):
                        second.call_tool("discover_sources", {})
                finally:
                    release.set()
                completed = future.result(timeout=10)
            self.assertEqual(second.call_tool("discover_sources", {}), completed)
        self.assertEqual(effects, ["discover_sources"])

    def test_recipient_configuration_is_not_queue_execution_evidence(self):
        self.config["recipient"] = "offline@example.test"
        context = self.context()
        report = context.evidence_report()
        self.assertEqual(context.ledger.rows("outbox"), [])
        self.assertNotEqual(report["mail_status"], "QUEUED_ONLY")

    def test_invalid_arguments_have_no_new_ledger_rows_or_files(self):
        context = self.context()
        with context.ledger.connect(True) as db:
            before = db.execute("SELECT count(*) FROM events").fetchone()[0]
        before_files = {path.relative_to(context.root) for path in context.root.rglob("*") if path.is_file()}
        for name, arguments in (
            ("discover_sources", {"url":"https://invalid.example/exfil"}),
            ("verify_official_sources", {"path":"C:/private.txt"}),
            ("run_frozen_models", {"target":"2099999"}),
            ("deliver_report", {"recipient":"victim@example.test"}),
            ("audit_experiment", {"action":"execute_study"}),
        ):
            with self.subTest(name=name), self.assertRaises(AgentBlocked):
                context.call_tool(name, arguments)
        with context.ledger.connect(True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], before)
        after_files = {path.relative_to(context.root) for path in context.root.rglob("*") if path.is_file()}
        self.assertEqual(after_files, before_files)

    def test_unknown_model_outcome_blocks_fresh_context_reservation(self):
        context = self.context(mode="SDK_SIMULATED_MODEL")
        context.begin_model_call(10, 20)
        context.mark_model_call_unknown()
        restarted = self.context(mode="SDK_SIMULATED_MODEL")
        with self.assertRaisesRegex(AgentBlocked, "UNKNOWN_MODEL_OUTCOME_REQUIRES_RECONCILIATION"):
            restarted.begin_model_call(10, 20)
        self.assertEqual(len(context.ledger.rows("model_claim")), 1)

    def test_final_report_queue_contains_completed_runtime_not_earlier_model_report(self):
        self.config["recipient"] = "offline@example.test"
        context = self.context()
        context.claim_execution()
        early = context.call_tool("deliver_report", {})
        context.finish_execution(dict(status="SDK_COMPLETED", mode=context.mode,
                                      paid_api_calls=0, model_calls=8))
        final = context.call_tool("deliver_report", {})
        self.assertNotEqual(early["report_id"], final["report_id"])
        saved = context.ledger.read("report", final["report_id"])
        queued = context.ledger.read("outbox", saved["outbox_id"])
        self.assertEqual(queued["report_sha256"], final["report_id"])
        self.assertIn("SDK_COMPLETED", queued["html"])

    def test_host_finalizes_after_model_consumes_the_tool_budget(self):
        from research.ssq_dlt_agent_v1.__main__ import execute
        self.config["limits"] = {"max_tool_calls":1}
        def exhausted_smoke(context):
            context.call_tool("audit_experiment", {"action":"inspect"})
            return dict(status="TOOLS_SMOKE_WITH_BLOCKS", mode=context.mode,
                        paid_api_calls=0, model_calls=0)
        with patch("research.ssq_dlt_agent_v1.__main__.smoke", side_effect=exhausted_smoke):
            receipt = execute(self.config, "tools-smoke", "adversarial-budget-run")
        self.assertEqual(receipt["delivery"]["status"], "REPORT_SAVED")
        self.assertIsNotNone(receipt["report_dir"])

    def test_host_finalizes_after_timeout_but_still_refuses_code_drift(self):
        tick = [0]
        context = self.context(monotonic=lambda:tick[0])
        context.claim_execution()
        context.finish_execution(dict(status="SDK_TIMED_OUT", mode=context.mode))
        tick[0] = 601
        with self.assertRaisesRegex(AgentBlocked, "TIME_BUDGET"):
            context.call_tool("audit_experiment", {"action":"inspect"})
        with patch("research.ssq_dlt_agent_v1.core.code_manifest", return_value={}):
            with self.assertRaisesRegex(AgentBlocked, "CODE_CHANGED"):
                context.finalize_report()
        self.assertEqual(context.ledger.rows("report"), [])
        finalized = context.finalize_report()
        self.assertEqual(finalized["status"], "REPORT_SAVED")
        self.assertEqual(len(context.ledger.rows("report")), 1)


if __name__ == "__main__":
    unittest.main()
