"""Offline component contracts. Process termination is tested by the fault lab."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.ssq_dlt_process_faults.publication import durable_publish
from research.ssq_dlt_process_faults.workflow_recovery import code_pin
from research.ssq_dlt_v45 import delivery, runtime
from research.ssq_dlt_v45.store import Store, digest


def report_at(seconds=0, metric=0):
    at = datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return dict(
        schema='GLP_V45_RESEARCH_REPORT_1',
        due_slot='2026-10-21T16:00:00+09:00', created_at=at.isoformat(),
        scope='RESEARCH_UNASSIGNED',
        games={g: dict(status='BLOCKED', target=None, reason='OFFLINE_SYNTHETIC_FIXTURE')
               for g in ('SSQ', 'DLT')},
        blockers=runtime.BLOCKERS,
        workflow=dict(metrics=dict(observed=metric)), **runtime.BOUNDARY)


def publication_key(report):
    return digest(dict(due_slot=report['due_slot'], games=report['games']))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='glp-publication-component-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'workflow.sqlite3')

    def publish(self, report, good=False, recipient='fixture@example.invalid', key=None):
        return durable_publish(self.store, self.root, key or publication_key(report),
                               report, good, recipient)

    def assert_bound(self, result):
        intent = self.store.read('workflow_publish_intent', publication_key(result['report']))
        outbox = self.store.read('outbox', result['outbox_id'])
        self.assertEqual(intent['report'], result['report'])
        self.assertEqual(outbox['report_sha256'], digest(intent['report']))
        self.assertEqual(outbox['recipient'], intent['recipient'])

    def test_committed_outbox_retry_reuses_first_report_time_metrics_and_recipient(self):
        class SimulatedExit(BaseException):
            pass
        original_append = self.store.append

        def append_and_exit(kind, key, value):
            result = original_append(kind, key, value)
            if kind == 'outbox':
                raise SimulatedExit()
            return result

        first = report_at()
        key = publication_key(first)
        self.store.append = append_and_exit
        try:
            with self.assertRaises(SimulatedExit):
                self.publish(first)
        finally:
            self.store.append = original_append
        self.assertIsNone(self.store.read('workflow_publish', key))
        result = self.publish(report_at(60, 5), True, 'changed@example.invalid')
        self.assertEqual(result['report'], first)
        self.assertEqual(result['created_at'], first['created_at'])
        self.assertFalse(result['research_ready'])
        self.assert_bound(result)
        self.assertEqual(len(self.store.rows('outbox')), 1)
        self.assertEqual(len(self.store.rows('workflow_publish')), 1)

    def test_concurrent_first_intent_wins(self):
        candidates = [report_at(i, i) for i in range(12)]

        def publish_index(i):
            return self.publish(candidates[i], bool(i % 2), f'fixture{i}@example.invalid')

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(publish_index, range(len(candidates))))
        self.assertTrue(all(result == results[0] for result in results))
        winner = candidates.index(results[0]['report'])
        self.assertEqual(results[0]['research_ready'], bool(winner % 2))
        self.assertEqual(self.store.rows('outbox')[0]['recipient'],
                         f'fixture{winner}@example.invalid')
        for kind in ('workflow_publish_intent', 'outbox', 'workflow_publish'):
            self.assertEqual(len(self.store.rows(kind)), 1)
        self.assert_bound(results[0])

    def test_legacy_orphan_mismatch_is_blocked_without_rewriting_old_row(self):
        old_report = report_at()
        old_id = delivery.prepare(self.store, self.root / 'outbox',
                                  'fixture@example.invalid', old_report, runtime.render(old_report))
        old_outbox = deepcopy(self.store.read('outbox', old_id))
        with self.assertRaisesRegex(ValueError, '^BLOCKED_OUTBOX_PUBLICATION_INTENT_MISMATCH$'):
            self.publish(report_at(60, 3))
        self.assertEqual(self.store.read('outbox', old_id), old_outbox)
        self.assertIsNone(self.store.read('workflow_publish', publication_key(old_report)))
        self.assertEqual(len(self.store.rows('outbox')), 1)

    def test_key_alias_cannot_bind_different_games(self):
        first = report_at()
        original_key = publication_key(first)
        self.publish(first)
        changed = report_at(60)
        changed['games']['SSQ']['reason'] = 'DIFFERENT_STATE'
        with self.assertRaisesRegex(ValueError, '^BLOCKED_PUBLICATION_KEY_REPORT_IDENTITY_MISMATCH$'):
            self.publish(changed, key=original_key)
        self.assertEqual(len(self.store.rows('workflow_publish_intent')), 1)
        self.assertEqual(self.store.rows('workflow_publish_intent')[0]['report'], first)

    def test_formal_edge_scope_and_assigned_targets_are_rejected_before_intent(self):
        mutations = (
            lambda report: report.update(formal_A=1),
            lambda report: report.update(formal_A=False),
            lambda report: report.update(decision='EDGE'),
            lambda report: report.update(scope='FORMAL'),
            lambda report: report['games']['SSQ'].update(target='2026123'),
            lambda report: report['games']['DLT'].pop('target'),
            lambda report: report['games']['SSQ'].update(status='FORMAL_PREDICTION'),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                report = report_at()
                mutate(report)
                with self.assertRaisesRegex(ValueError, '^BLOCKED_'):
                    self.publish(report)
        self.assertEqual(self.store.rows('workflow_publish_intent'), [])
        self.assertEqual(self.store.rows('outbox'), [])
        self.assertEqual(self.store.rows('workflow_publish'), [])

    def test_stored_intent_identity_cannot_alias_another_report(self):
        report = report_at()
        key = publication_key(report)
        aliased = deepcopy(report)
        aliased['games']['SSQ']['reason'] = 'DIFFERENT_STORED_STATE'
        self.store.append('workflow_publish_intent', key, dict(
            schema='GLP_WORKFLOW_PUBLISH_INTENT_1', publication_key=key,
            due_slot=report['due_slot'], created_at=report['created_at'],
            research_ready=False, recipient='fixture@example.invalid',
            report_sha256=digest(aliased), report=aliased))
        with self.assertRaisesRegex(ValueError, '^BLOCKED_PUBLICATION_INTENT_REPORT_INTEGRITY$'):
            self.publish(report)
        self.assertEqual(self.store.rows('outbox'), [])
        self.assertEqual(self.store.rows('workflow_publish'), [])

    def test_stored_intent_cannot_promote_formal_a(self):
        report = report_at()
        key = publication_key(report)
        promoted = dict(report, formal_A=1)
        self.store.append('workflow_publish_intent', key, dict(
            schema='GLP_WORKFLOW_PUBLISH_INTENT_1', publication_key=key,
            due_slot=report['due_slot'], created_at=report['created_at'],
            research_ready=False, recipient='fixture@example.invalid',
            report_sha256=digest(promoted), report=promoted))
        with self.assertRaisesRegex(ValueError, '^BLOCKED_PUBLICATION_INTENT_REPORT_INTEGRITY$'):
            self.publish(report)
        self.assertEqual(self.store.rows('outbox'), [])
        self.assertEqual(self.store.rows('workflow_publish'), [])

    def test_both_recovery_files_are_in_code_pin(self):
        pin = code_pin()
        self.assertIn('ssq_dlt_process_faults/publication.py', pin)
        self.assertIn('ssq_dlt_process_faults/workflow_recovery.py', pin)


if __name__ == '__main__':
    unittest.main()
