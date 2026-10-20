"""Native-host integration tests using explicitly synthetic legal fixtures."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.ssq_dlt_agent_graph.host import LegacyHost
from research.ssq_dlt_agent_graph.journal import GraphBlocked
from research.ssq_dlt_agent_v1.policy import AgentBlocked, BOUNDARY, canonical, digest


NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def fixture_config(root):
    """Tiny fabricated histories; never represented as official draw evidence."""
    inputs = root / 'inputs'
    inputs.mkdir(exist_ok=True)
    history = {}
    for game, prefix, count, back in (('SSQ', '2025', 6, [1]), ('DLT', '25', 5, [1, 2])):
        rows = [dict(game=game, issue=prefix + f'{i+1:03}',
                     draw_date=(date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                     front=list(range(1, count + 1)), back=back) for i in range(60)]
        raw = (canonical(dict(game=game, draws=rows)) + '\n').encode('utf-8')
        path = inputs / (game + '.json')
        path.write_bytes(raw)
        history[game] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    return dict(state_dir=str(root / 'state'), history=history,
                live_sources=False, recipient=None)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = fixture_config(self.root)
        self.host = LegacyHost(self.config, 'graph-fixture', clock=lambda: NOW)

    def tearDown(self):
        self.temp.cleanup()

    def complete_three(self):
        expected = [('verify_official_sources', {}, 'HISTORY_CHECKED'),
                    ('run_frozen_models', {}, 'NON_FORMAL_RESEARCH_UNASSIGNED'),
                    ('audit_experiment', {}, 'AUDIT_CHECKED')]
        for name, args, status in expected:
            self.assertEqual(self.host.call_tool(name, args)['status'], status)

    def test_native_tools_preserve_boundary_and_restart_reuses(self):
        self.assertEqual(self.host.lookup('verify_official_sources', {})['state'], 'NOT_STARTED')
        first = self.host.call_tool('verify_official_sources', {})
        restart = LegacyHost(self.config, 'graph-fixture', clock=lambda: NOW)
        with patch('research.ssq_dlt_agent_v1.core.workflow.history_stage', side_effect=AssertionError('No rerun')):
            self.assertEqual(restart.call_tool('verify_official_sources', {}), first)
        self.assertEqual(len(restart.ctx._rows('tool_claim')), 1)
        for key, value in BOUNDARY.items():
            self.assertEqual(first[key], value)

    def test_pin_is_stable_serializable_and_detects_drift(self):
        first = self.host.pin()
        self.assertIn('code_manifest', first)
        self.assertEqual(canonical(first), canonical(self.host.pin()))
        self.host.ctx.config['limits']['max_tool_calls'] += 1
        with self.assertRaisesRegex(GraphBlocked, 'HOST_CONFIG_CHANGED'):
            self.host.lookup('verify_official_sources', {})

    def test_code_drift_blocks_before_dependency(self):
        with patch('research.ssq_dlt_agent_graph.host.code_manifest', return_value={}):
            with self.assertRaisesRegex(GraphBlocked, 'HOST_CODE_CHANGED'):
                self.host.lookup('verify_official_sources', {})

    def test_recipient_and_live_sources_rejected_without_native_construction(self):
        for changes, reason in (({'recipient': 'fixture@example.com'}, 'RECIPIENT'),
                                ({'live_sources': True}, 'LIVE_SOURCES')):
            with patch('research.ssq_dlt_agent_graph.host.AgentContext') as context:
                with self.assertRaisesRegex(GraphBlocked, reason):
                    LegacyHost(dict(self.config, **changes), 'invalid', clock=lambda: NOW)
                context.assert_not_called()

    def test_discovery_does_not_invoke_network(self):
        with patch('research.ssq_dlt_agent_v1.core.discovery.run_discovery') as discovery:
            with self.assertRaisesRegex(GraphBlocked, 'DISCOVERY_NETWORK_NOT_ENABLED'):
                self.host.call_tool('discover_sources', {})
        discovery.assert_not_called()
        self.assertEqual(self.host.ctx._rows('tool_claim'), [])

    def test_unknown_claim_never_retries_and_lists_pending(self):
        claim, _ = self.host.ctx._claim_tool('verify_official_sources', {})
        self.assertEqual(self.host.lookup('verify_official_sources', {}), dict(state='UNKNOWN', result=None))
        self.assertEqual(self.host.pending_unknown()[0]['evidence_id'], claim['claim_id'])
        with patch.object(self.host.ctx, 'call_tool') as invoke:
            with self.assertRaisesRegex(GraphBlocked, 'UNKNOWN_TOOL_OUTCOME'):
                self.host.call_tool('verify_official_sources', {})
            with self.assertRaisesRegex(GraphBlocked, 'UNKNOWN_TOOL_OUTCOME'):
                self.host.call_tool('audit_experiment', {})
        invoke.assert_not_called()

    def test_different_arguments_have_different_native_identities(self):
        self.host.call_tool('audit_experiment', {'action': 'inspect'})
        self.assertEqual(self.host.lookup('audit_experiment', {})['state'], 'KNOWN')
        self.assertEqual(self.host.lookup('audit_experiment', {'action': 'run_registered_experiment'})['state'], 'NOT_STARTED')

    def test_unknown_other_run_does_not_contaminate_this_run(self):
        other = LegacyHost(self.config, 'other-fixture', clock=lambda: NOW)
        other.ctx._claim_tool('verify_official_sources', {})
        self.assertEqual(self.host.pending_unknown(), [])
        self.assertEqual(self.host.call_tool('audit_experiment', {})['status'], 'AUDIT_CHECKED')

    def test_unsupported_tool_arguments_rejected_before_claim(self):
        for name, args in [('shell', {}), ('verify_official_sources', {'force': True}),
                           ('audit_experiment', {'action': 'inspect', 'hypothesis_json': '{}'})]:
            with self.assertRaises(AgentBlocked):
                self.host.call_tool(name, args)
        self.assertEqual(self.host.ctx._rows('tool_claim'), [])

    def test_fake_public_success_without_receipt_is_rejected(self):
        fake = dict(status='HISTORY_CHECKED', evidence_id='fake', **BOUNDARY)
        with patch.object(self.host.ctx, 'call_tool', return_value=fake):
            with self.assertRaisesRegex(GraphBlocked, 'UNBACKED_TOOL_RESULT'):
                self.host.call_tool('verify_official_sources', {})

    def test_fake_reference_to_other_run_is_rejected(self):
        other = LegacyHost(self.config, 'other-fixture', clock=lambda: NOW)
        fake = other.call_tool('verify_official_sources', {})
        with patch.object(self.host.ctx, 'call_tool', return_value=fake):
            with self.assertRaisesRegex(GraphBlocked, 'UNBACKED_TOOL_RESULT'):
                self.host.call_tool('verify_official_sources', {})

    def test_payload_sha_corruption_rejected_on_read(self):
        first = self.host.call_tool('audit_experiment', {})
        with self.host.ctx.ledger.connect() as db:
            db.execute('DROP TRIGGER immutable_UPDATE')
            db.execute("UPDATE events SET sha256=? WHERE kind='tool_result' AND key=?", ('0' * 64, first['evidence_id']))
        with self.assertRaisesRegex(AgentBlocked, 'LEDGER_SHA_MISMATCH'):
            self.host.lookup('audit_experiment', {})

    def test_semantically_wrong_evidence_sha_rejected(self):
        claim, _ = self.host.ctx._claim_tool('audit_experiment', {'action': 'inspect', 'hypothesis_json': ''})
        evidence = dict(status='AUDIT_CHECKED')
        public = dict(status='AUDIT_CHECKED', evidence_id=claim['claim_id'], **BOUNDARY)
        row = dict(claim, evidence=evidence, evidence_sha256='0' * 64, public=public, completed_at=NOW.isoformat())
        self.host.ctx.ledger.append('tool_result', claim['claim_id'], row)
        with self.assertRaisesRegex(GraphBlocked, 'EVIDENCE_SHA_MISMATCH'):
            self.host.lookup('audit_experiment', {})

    def test_prepare_requires_three_successful_receipts(self):
        with self.assertRaisesRegex(GraphBlocked, 'PREREQUISITE'):
            self.host.prepare_delivery()
        self.assertIsNone(self.host.ctx.ledger.read('execution_result', self.host.ctx.run_id))

    def test_prepare_is_immutable_replay_and_never_claims_whole_execution(self):
        self.complete_three()
        first = self.host.prepare_delivery()
        restart = LegacyHost(self.config, 'graph-fixture', clock=lambda: NOW + timedelta(seconds=1))
        self.assertEqual(restart.prepare_delivery(), first)
        self.assertEqual(first['result']['status'], 'GRAPH_TOOL_PIPELINE_COMPLETED')
        self.assertEqual(self.host.ctx._rows('execution'), [])
        self.assertEqual(len(self.host.ctx._rows('execution_result')), 1)

    def test_prepare_rejects_existing_conflicting_execution(self):
        self.complete_three()
        self.host.ctx.finish_execution(dict(status='DIFFERENT'))
        with self.assertRaisesRegex(GraphBlocked, 'EXECUTION_RESULT_CONFLICT'):
            self.host.prepare_delivery()

    def test_delivery_identity_changes_when_finalization_changes(self):
        self.complete_three()
        before = self.host.call_tool('deliver_report', {})
        self.host.prepare_delivery()
        self.assertEqual(self.host.lookup('deliver_report', {})['state'], 'NOT_STARTED')
        after = self.host.call_tool('deliver_report', {})
        self.assertNotEqual(before['evidence_id'], after['evidence_id'])
        self.assertEqual(self.host.lookup('deliver_report', {})['result'], after)

    def test_final_report_is_native_byte_verified_and_no_mail(self):
        self.complete_three()
        self.host.prepare_delivery()
        with patch('research.ssq_dlt_v45.delivery.flush', side_effect=AssertionError('No SMTP')):
            first = self.host.call_tool('deliver_report', {})
            second = self.host.call_tool('deliver_report', {})
        self.assertEqual(first, second)
        report = self.host.read_report()
        self.assertEqual(set(report['files']), {'report.json', 'report.html'})
        for spec in report['files'].values():
            self.assertEqual(hashlib.sha256(Path(spec['path']).read_bytes()).hexdigest(), spec['sha256'])
        self.assertEqual(self.host.ctx.ledger.rows('outbox'), [])
        self.assertFalse((self.host.ctx.root / 'mail').exists())
        self.assertEqual(first['delivery'], 'NOT_CONFIGURED')

    def test_report_byte_tamper_is_rejected(self):
        self.complete_three()
        self.host.prepare_delivery()
        self.host.call_tool('deliver_report', {})
        report = self.host.read_report()
        Path(report['report_html']).write_bytes(b'changed')
        with self.assertRaisesRegex(GraphBlocked, 'FILE_SHA_MISMATCH'):
            self.host.read_report()

    def test_report_before_final_metadata_is_not_accepted(self):
        self.complete_three()
        self.host.call_tool('deliver_report', {})
        with self.assertRaisesRegex(GraphBlocked, 'CONTENT_MISMATCH'):
            self.host.read_report()

    def test_tool_budget_does_not_reset_across_restart(self):
        cfg = deepcopy(self.config)
        cfg['limits'] = {'max_tool_calls': 1}
        host = LegacyHost(cfg, 'budget-fixture', clock=lambda: NOW)
        host.call_tool('verify_official_sources', {})
        restart = LegacyHost(cfg, 'budget-fixture', clock=lambda: NOW)
        with self.assertRaisesRegex(GraphBlocked, 'TOOL_CALL_BUDGET_EXHAUSTED'):
            restart.call_tool('run_frozen_models', {})


if __name__ == '__main__':
    unittest.main()
