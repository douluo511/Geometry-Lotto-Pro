"""Real LangGraph/SQLite integration, using synthetic histories and no model/network.

Checkpoint forgery and SQL mutation below target only disposable test databases.
They demonstrate that mutable coordination state cannot grant native authority.
"""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver

from research.ssq_dlt_agent_graph import settings
from research.ssq_dlt_agent_graph.host import LegacyHost
from research.ssq_dlt_agent_graph.journal import GraphBlocked, Journal, digest
from research.ssq_dlt_agent_graph.runtime import GraphRunner
from research.ssq_dlt_agent_graph.tests.fixtures import NOW, graph_fixture_config, pin


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-langgraph-')
        self.root = Path(self.temp.name)
        self.config = graph_fixture_config(self.root)
        self.now = NOW

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, thread='fixture', config=None, parent=None):
        return GraphRunner(config or self.config, thread, clock=lambda: self.now,
                           parent_thread_id=parent)

    def journal(self):
        return Journal(Path(self.config['root']) / 'evidence.sqlite3')

    def host(self, thread='fixture'):
        return LegacyHost(self.config['host'], 'GRAPH:' + thread, clock=lambda: self.now)

    def assert_boundary(self, result):
        for key, value in settings.BOUNDARY.items():
            self.assertEqual(result[key], value)
        self.assertEqual(result['paid_api_calls'], 0)
        self.assertEqual(result['model_calls'], 0)

    def test_normal_graph_completes_using_four_native_receipts_and_no_execution_claim(self):
        result = self.runner().run()
        self.assertEqual(result['status'], 'COMPLETED_RESEARCH_ONLY')
        self.assertEqual(result['publication'], 'BLOCKED')
        self.assert_boundary(result)
        host = self.host()
        self.assertEqual(len(host.ctx._rows('tool_claim')), 4)
        self.assertEqual(len(host.ctx._rows('tool_result')), 4)
        self.assertEqual(host.ctx._rows('execution'), [])
        self.assertEqual(len(host.ctx._rows('execution_result')), 1)
        self.assertEqual(len(self.journal().rows('step')), 6)
        self.assertEqual(len(self.journal().rows('reservation')), 6)
        self.assertEqual(host.ctx._rows('model_claim'), [])
        self.assertEqual(host.ctx._rows('outbox'), [])

    def test_new_runner_resumes_real_checkpoint_and_reuses_completed_native_receipts(self):
        paused = self.runner().run(stop_after='verify_official_sources')
        self.assertEqual(paused['status'], 'PAUSED_CHECKPOINT')
        self.assertEqual(paused['next_nodes'], ['run_frozen_models'])
        before = self.host().ctx._rows('tool_claim')
        self.assertEqual(len(before), 1)
        done = self.runner().run(resume=True)
        self.assertEqual(done['status'], 'COMPLETED_RESEARCH_ONLY')
        claims = self.host().ctx._rows('tool_claim')
        self.assertEqual(len(claims), 4)
        self.assertIn(before[0], claims)
        self.assert_boundary(done)

    def test_completed_run_returns_identical_receipts_report_bytes_and_sha_after_restart(self):
        first = self.runner().run()
        host = self.host()
        before_claims = host.ctx._rows('tool_claim')
        before_results = host.ctx._rows('tool_result')
        report = host.read_report()
        actual = {name: Path(spec['path']).read_bytes() for name, spec in report['files'].items()}
        self.now += timedelta(minutes=1)
        second = self.runner().run(resume=True)
        self.assertEqual(first, second)
        restart = self.host()
        self.assertEqual(restart.ctx._rows('tool_claim'), before_claims)
        self.assertEqual(restart.ctx._rows('tool_result'), before_results)
        self.assertEqual(restart.read_report()['report_sha256'], report['report_sha256'])
        for name, spec in report['files'].items():
            self.assertEqual(Path(spec['path']).read_bytes(), actual[name])
            self.assertEqual(hashlib.sha256(actual[name]).hexdigest(), spec['sha256'])

    def test_restart_cannot_reset_persisted_deadline(self):
        self.config['limits']['max_wall_seconds'] = 10
        paused = self.runner().run(stop_after='verify_official_sources')
        self.assertEqual(paused['status'], 'PAUSED_CHECKPOINT')
        deadline = self.journal().read('run', 'fixture')['deadline']
        self.now += timedelta(seconds=11)
        result = self.runner().run(resume=True)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'DURABLE_GRAPH_DEADLINE_EXHAUSTED')
        self.assertEqual(self.journal().read('run', 'fixture')['deadline'], deadline)
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 1)

    def test_restart_cannot_reset_stage_budget_or_repeat_prior_stage(self):
        self.config['limits']['max_stage_calls'] = 3
        paused = self.runner().run(stop_after='verify_official_sources')
        self.assertEqual(paused['status'], 'PAUSED_CHECKPOINT')
        result = self.runner().run(resume=True)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'DURABLE_STAGE_BUDGET_EXHAUSTED')
        self.assertEqual(len(self.journal().rows('reservation')), 3)
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 1)

    def test_checkpoint_resume_requires_explicit_resume_flag(self):
        self.runner().run(stop_after='memory')
        with self.assertRaisesRegex(GraphBlocked, 'EXISTING_CHECKPOINT_REQUIRES_EXPLICIT_RESUME'):
            self.runner().run()
        self.assertEqual(self.host().ctx._rows('tool_claim'), [])

    def test_resume_requires_existing_checkpoint(self):
        with self.assertRaisesRegex(GraphBlocked, 'RESUME_REQUIRES_EXISTING_CHECKPOINT'):
            self.runner().run(resume=True)
        self.assertEqual(self.host().ctx._rows('tool_claim'), [])

    def test_foreign_graph_directory_rejected_without_writing_process_lock(self):
        state = Path(self.config['root'])
        state.mkdir()
        sentinel = state / 'unrelated.txt'
        sentinel.write_bytes(b'preserve this foreign directory')
        with self.assertRaisesRegex(GraphBlocked, 'NEW_GRAPH_ROOT_REQUIRED'):
            self.runner().run()
        self.assertEqual(sentinel.read_bytes(), b'preserve this foreign directory')
        self.assertEqual(sorted(p.name for p in state.iterdir()), ['unrelated.txt'])

    def test_foreign_checkpoint_database_rejected_before_native_call(self):
        self.runner().run(stop_after='memory')
        path = Path(self.config['root']) / 'checkpoints.sqlite3'
        path.unlink()
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE unrelated(value TEXT)')
            db.execute("INSERT INTO unrelated VALUES('foreign data')")
            db.commit()
        with self.assertRaisesRegex(GraphBlocked, 'FOREIGN_GRAPH_CHECKPOINT_DB'):
            self.runner().run(resume=True)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT value FROM unrelated').fetchone()[0], 'foreign data')
        self.assertEqual(self.host().ctx._rows('tool_claim'), [])

    def test_checkpoint_forged_completion_and_missing_receipt_cannot_authorize(self):
        self.runner().run(stop_after='memory')
        path = Path(self.config['root']) / 'checkpoints.sqlite3'
        cfg = {'configurable': {'thread_id': 'fixture'}}
        with closing(sqlite3.connect(str(path), check_same_thread=False)) as db:
            saver = SqliteSaver(db)
            current = saver.get_tuple(cfg)
            forged = deepcopy(current.checkpoint)
            forged['channel_values']['phase'] = 'COMPLETED_RESEARCH_ONLY'
            forged['channel_values']['step_refs']['run_frozen_models'] = '0' * 64
            saver.put(current.config, forged, current.metadata, {})
        with self.assertRaisesRegex(GraphBlocked, 'CHECKPOINT_RECEIPT_MISMATCH'):
            self.runner().run(resume=True)
        self.assertIsNone(self.journal().read('terminal', 'fixture'))
        self.assertEqual(self.host().ctx._rows('tool_claim'), [])

    def test_checkpoint_false_phase_alone_cannot_skip_remaining_native_work(self):
        self.runner().run(stop_after='memory')
        path = Path(self.config['root']) / 'checkpoints.sqlite3'
        cfg = {'configurable': {'thread_id': 'fixture'}}
        with closing(sqlite3.connect(str(path), check_same_thread=False)) as db:
            saver = SqliteSaver(db)
            current = saver.get_tuple(cfg)
            forged = deepcopy(current.checkpoint)
            forged['channel_values']['phase'] = 'COMPLETED_RESEARCH_ONLY'
            saver.put(current.config, forged, current.metadata, {})
        result = self.runner().run(resume=True)
        self.assertEqual(result['status'], 'COMPLETED_RESEARCH_ONLY')
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 4)
        self.assertEqual(len(self.host().ctx._rows('tool_result')), 4)
        self.assert_boundary(result)

    def test_unknown_claim_requires_reconciliation_and_new_thread_id_cannot_bypass(self):
        self.runner().run(stop_after='memory')
        host = self.host()
        host.ctx._claim_tool('verify_official_sources', {})
        with self.assertRaisesRegex(GraphBlocked, 'OTHER_UNFINISHED_THREAD_REQUIRES_RESUME'):
            self.runner('bypass-before-restore').run()
        result = self.runner().run(resume=True)
        self.assertEqual(result['status'], 'RECONCILIATION_REQUIRED')
        self.assertIn('UNKNOWN', result['reason'])
        with self.assertRaisesRegex(GraphBlocked, 'OTHER_UNKNOWN_OUTCOME_REQUIRES_RECONCILIATION'):
            self.runner('bypass-after-restore').run()
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 1)
        self.assertEqual(self.host().ctx._rows('tool_result'), [])
        self.assert_boundary(result)

    def test_native_result_write_failure_is_unknown_and_never_safely_forked(self):
        paused = self.runner().run(stop_after='memory')
        self.assertEqual(paused['status'], 'PAUSED_CHECKPOINT')
        # Execute the actual native verification; fail only its result commit.
        # The verification's existence of a claim cannot prove its final outcome.
        from research.ssq_dlt_agent_v1.core import Ledger
        original_append = Ledger.append

        def fail_result(ledger, kind, key, value):
            if kind == 'tool_result':
                raise OSError('injected synthetic result persistence failure')
            return original_append(ledger, kind, key, value)

        with patch.object(Ledger, 'append', fail_result):
            result = self.runner().run(resume=True)
        self.assertEqual(result['status'], 'RECONCILIATION_REQUIRED')
        self.assertEqual(result['reason'], 'UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION')
        self.assertEqual(result['trigger_reason'], 'OSError')
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 1)
        self.assertEqual(self.host().ctx._rows('tool_result'), [])
        with self.assertRaisesRegex(GraphBlocked, 'OTHER_UNKNOWN_OUTCOME_REQUIRES_RECONCILIATION'):
            self.runner('unsafe-new-thread').run()
        with self.assertRaisesRegex(GraphBlocked, 'OTHER_UNKNOWN_OUTCOME_REQUIRES_RECONCILIATION'):
            self.runner('unsafe-child', parent='fixture').run()
        self.assertEqual(self.runner().run(resume=True), result)
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 1)

    def test_unknown_native_graph_run_without_graph_header_still_blocks_new_identity(self):
        completed = self.runner().run()
        self.assertEqual(completed['status'], 'COMPLETED_RESEARCH_ONLY')
        # An orphaned native run remains in the same dedicated host ledger.
        # The new graph identity must inspect it even without a graph run row.
        orphan = self.host('native-orphan')
        orphan.ctx._claim_tool('verify_official_sources', {})
        self.assertIsNone(self.journal().read('run', 'native-orphan'))
        with self.assertRaisesRegex(GraphBlocked, 'OTHER_UNKNOWN_OUTCOME_REQUIRES_RECONCILIATION'):
            self.runner('unsafe-after-completion').run()
        self.assertIsNone(self.journal().read('run', 'unsafe-after-completion'))
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 4)
        self.assertEqual(len(orphan.pending_unknown()), 1)

    def test_known_blocked_child_requires_new_evidence_and_preserves_parent(self):
        original = deepcopy(self.config)
        raw = Path(self.config['sources']['SSQ'][1]['path'])
        raw.write_text(raw.read_text(encoding='utf-8').replace('01 02 03 04 05 06',
                       '01 02 03 04 05 07', 1), encoding='utf-8')
        self.config['sources']['SSQ'][1] = pin(raw)
        result = self.runner().run()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'OFFICIAL_SOURCE_CONFLICT')
        parent = self.journal().read('terminal', 'fixture')
        with self.assertRaisesRegex(GraphBlocked, 'KNOWN_BLOCKED_REQUIRES_CHILD_VERIFICATION'):
            self.runner('new-family-bypass').run()
        with self.assertRaisesRegex(GraphBlocked, 'NEW_PINNED_SOURCE_EVIDENCE_REQUIRED'):
            self.runner('child-without-evidence', parent='fixture').run()
        corrected = self.root / 'inputs' / 'SSQ-synthetic-corrected.html'
        correct_original = Path(original['sources']['SSQ'][0]['path'])
        rows = json.loads(correct_original.read_bytes())['result']
        corrected.write_text('<table>' + ''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
            r['code'], r['date'], ' '.join(f'{int(n):02}' for n in r['red'].split(',')),
            f"{int(r['blue']):02}") for r in rows) + '</table>', encoding='utf-8')
        child_config = deepcopy(self.config)
        child_config['sources']['SSQ'][1] = pin(corrected)
        child = self.runner('valid-child', config=child_config, parent='fixture').run()
        self.assertEqual(child['status'], 'COMPLETED_RESEARCH_ONLY')
        self.assertEqual(child['parent_thread_id'], 'fixture')
        self.assertEqual(self.journal().read('terminal', 'fixture'), parent)
        self.assertEqual(self.journal().read('run', 'valid-child')['family_id'], 'fixture')
        self.assert_boundary(child)

    def test_changed_pinned_input_on_resume_rejected_before_new_native_work(self):
        self.runner().run(stop_after='verify_official_sources')
        raw = Path(self.config['sources']['SSQ'][1]['path'])
        raw.write_bytes(raw.read_bytes() + b'\n<!-- changed synthetic bytes -->')
        with self.assertRaisesRegex(GraphBlocked, 'GRAPH_INPUT_PIN_MISMATCH'):
            self.runner().run(resume=True)
        self.assertEqual(len(self.host().ctx._rows('tool_claim')), 1)

    def test_clock_rewind_rejected_across_graph_restart(self):
        self.runner().run(stop_after='memory')
        self.now -= timedelta(seconds=1)
        with self.assertRaisesRegex(GraphBlocked, 'GRAPH_CLOCK_REWIND'):
            self.runner().run(resume=True)
        self.now += timedelta(seconds=1)
        self.assertEqual(self.host().ctx._rows('tool_claim'), [])


if __name__ == '__main__':
    unittest.main()
