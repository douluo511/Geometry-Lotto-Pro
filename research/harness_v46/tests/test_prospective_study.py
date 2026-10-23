"""Synthetic-only integration of449 study replay with451/452/465 safeguards."""
import copy
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.harness_v46 import core, prospective_cycle as cycle
from research.harness_v46.tests.test_core import fixture


class ProspectiveStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'synthetic.sqlite3'
        self.before = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
        self.after = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)

    def freeze(self, issue):
        snaps = {g: {**fixture(g), 'target_issue': str(issue)} for g in core.RULES}
        record = cycle.forecast_on_demand(snaps, self.db, now=self.before)
        results = {g: {
            'lottery': g, 'issue': str(issue),
            'front': list(s['draws'][-2]['front']),
            'back': list(s['draws'][-2]['back']),
            'drawn_at': '2026-10-23T21:05:00+08:00',
        } for g, s in snaps.items()}
        return record['run_id'], results

    def score(self, issue):
        run_id, results = self.freeze(issue)
        return cycle.evaluate_after_draw(self.db, run_id, results, observed_at=self.after)

    def study(self, receipts, *, observed_at=None):
        method = getattr(cycle, 'summarize_prospective_receipts', None)
        self.assertTrue(callable(method), 'missing guarded prospective receipt study API')
        return method(self.db, receipts, observed_at=self.after if observed_at is None else observed_at)

    def inputs(self, report):
        self.assertIn('scoring_inputs', report, 'missing hash-bound complete caller outcome preimages')
        return report['scoring_inputs']['result_bundle']

    def rehash(self, report):
        if 'scoring_inputs' in report:
            report['scoring_inputs']['result_bundle_sha256'] = core.digest(
                report['scoring_inputs']['result_bundle'])
        report['score_receipt_sha256'] = core.digest({
            k: v for k, v in report.items() if k != 'score_receipt_sha256'})
        return report

    def test_score_hash_binds_both_full_outcomes_including_claimed_draw_time(self):
        report = self.score('29999')
        inputs = self.inputs(report)
        for game in core.RULES:
            self.assertEqual(set(inputs[game]), {'lottery', 'issue', 'front', 'back', 'drawn_at'})
            self.assertEqual(inputs[game]['drawn_at'], '2026-10-23T21:05:00+08:00')
            self.assertEqual(report['shadow_feedback_receipts'][game]['outcome_sha256'],
                             core.digest(inputs[game]))
        self.assertEqual(report['scoring_inputs']['result_bundle_sha256'], core.digest(inputs))
        self.assertEqual(report['score_receipt_sha256'], core.digest({
            k: v for k, v in report.items() if k != 'score_receipt_sha256'}))
        self.assertFalse(report['scoring_inputs']['authenticated_official_source'])
        self.assertEqual(report['scoring_inputs']['timestamp_trust'], 'NONE')

    def test_all_receipts_are_replayed_readonly_independent_of_order(self):
        first, second = self.score('29999'), self.score('30000')
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        report = self.study([second, first])
        self.assertEqual(report, self.study([first, second]))
        self.assertEqual(report['draws_by_game'], {'SSQ': 2, 'DLT': 2})
        self.assertEqual(report['local_ledger_roster']['run_count'], 2)
        self.assertEqual(report['local_ledger_roster']['run_ids_sha256'],
                         core.digest(sorted([first['run_id'], second['run_id']])))
        self.assertEqual(report['local_ledger_roster']['status'],
                         'ALL_LOCAL_FROZEN_RUNS_PRESENT_NOT_OFFICIAL_SCHEDULE')
        self.assertEqual(report['coverage'], 'CALLER_SUBMITTED_RECEIPTS_ONLY')
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_missing_scored_run_cannot_be_selected_out(self):
        first = self.score('29999')
        self.score('30000')
        with self.assertRaisesRegex(core.GateError, 'STUDY_COVERAGE_MISSING_FROZEN_RUNS'):
            self.study([first])

    def test_unscored_registered_freeze_blocks_complete_study(self):
        first = self.score('29999')
        self.freeze('30000')
        with self.assertRaisesRegex(core.GateError, 'STUDY_COVERAGE_MISSING_FROZEN_RUNS'):
            self.study([first])

    def test_numeric_issue_aliases_cannot_double_the_same_draw(self):
        first, alias = self.score('29999'), self.score('029999')
        with self.assertRaisesRegex(core.GateError, 'DUPLICATE_STUDY_GAME_ISSUE'):
            self.study([first, alias])

    def test_duplicate_run_and_empty_inputs_are_rejected(self):
        first = self.score('29999')
        with self.assertRaisesRegex(core.GateError, 'DUPLICATE_STUDY_RUN'):
            self.study([first, first])
        for value in ([], {}, None):
            with self.subTest(value=value), self.assertRaisesRegex(core.GateError, 'EMPTY_STUDY_RECEIPTS'):
                self.study(value)

    def test_rehashed_changed_d2_is_not_ledger_evidence(self):
        fake = self.score('29999')
        cell = fake['games']['SSQ']['scores']['hot60']
        cell['D2'] = 1 - cell['D2']
        self.rehash(fake)
        with self.assertRaisesRegex(core.GateError, 'SCORE_RECEIPT_REPLAY_MISMATCH'):
            self.study([fake])

    def test_rehashed_changed_outcome_time_is_not_original_receipt(self):
        fake = self.score('29999')
        self.inputs(fake)['SSQ']['drawn_at'] = '2026-10-23T21:06:00+08:00'
        self.rehash(fake)
        with self.assertRaisesRegex(core.GateError, 'SCORE_RECEIPT_REPLAY_MISMATCH'):
            self.study([fake])

    def test_future_claimed_outcome_still_fails_on_study_replay(self):
        fake = self.score('29999')
        self.inputs(fake)['DLT']['drawn_at'] = (self.after + timedelta(seconds=1)).isoformat()
        self.rehash(fake)
        with self.assertRaisesRegex(core.GateError, 'OUTCOME_CLAIMED_DRAW_TIME_IN_FUTURE'):
            self.study([fake])

    def test_study_observation_before_target_or_naive_clock_fails(self):
        first = self.score('29999')
        with self.assertRaisesRegex(core.GateError, 'SCORE_BEFORE_LOCKED_TARGET_DRAW_TIME'):
            self.study([first], observed_at=self.before)
        with self.assertRaisesRegex(core.GateError, 'SCORING_OBSERVATION_CLOCK_MUST_BE_AWARE'):
            self.study([first], observed_at=self.after.replace(tzinfo=None))

    def test_missing_draw_time_never_uses_a_legacy_four_field_fallback(self):
        fake = self.score('29999')
        del self.inputs(fake)['SSQ']['drawn_at']
        self.rehash(fake)
        with self.assertRaisesRegex(core.GateError, 'STRICT_UNVERIFIED_OUTCOME_SCHEMA_REQUIRED'):
            self.study([fake])

    def test_self_rehashed_authority_and_model_vector_changes_are_refused(self):
        good = self.score('29999')
        authority = copy.deepcopy(good)
        authority['formal_A'] = 1
        vector = copy.deepcopy(good)
        del vector['games']['SSQ']['scores']['random_null']
        for fake in (authority, vector):
            self.rehash(fake)
            with self.subTest(keys=list(fake)), self.assertRaisesRegex(
                    core.GateError, 'SCORE_RECEIPT_REPLAY_MISMATCH'):
                self.study([fake])

    def test_receipt_hash_is_required_even_for_legal_looking_scores(self):
        good = self.score('29999')
        good.pop('score_receipt_sha256', None)
        with self.assertRaisesRegex(core.GateError, 'INVALID_SCORE_RECEIPT_HASH'):
            self.study([good])

    def test_complete_twelve_model_stats_use_original_frozen_d2_bits(self):
        receipts = [self.score('29999'), self.score('30000')]
        report = self.study(receipts)
        analysis = report['statistical_analysis']
        self.assertEqual(analysis['family_size'], 12)
        self.assertEqual(len(analysis['results']), 12)
        for result in analysis['results']:
            game, model = result['lottery'], result['model']
            bits = [r['games'][game]['scores'][model]['D2'] for r in receipts]
            nulls = [r['games'][game]['scores']['random_null']['D2'] for r in receipts]
            self.assertEqual(result['hits'], sum(bits))
            self.assertEqual(result['draws'], 2)
            if model != 'random_null':
                self.assertEqual(result['paired_wins_vs_null'],
                                 sum(a == 1 and b == 0 for a, b in zip(bits, nulls)))
                self.assertEqual(result['paired_losses_vs_null'],
                                 sum(a == 0 and b == 1 for a, b in zip(bits, nulls)))
        for value in (report, analysis):
            self.assertEqual(value['formal_A'], 0)
            self.assertEqual(value['decision'], 'NO_EDGE')
            self.assertFalse(value['preregistration_verified'])
        self.assertFalse(report['official_results_authenticated'])
        self.assertFalse(report['independent_predraw_timestamp_verified'])

    def test_completely_recomputed_other_caller_outcome_remains_unverified(self):
        original = self.score('29999')
        alternate_inputs = copy.deepcopy(self.inputs(original))
        old_front = alternate_inputs['SSQ']['front']
        replacement = sorted(set(range(1, 34)) - set(old_front))[:6]
        alternate_inputs['SSQ']['front'] = replacement
        other = cycle.evaluate_after_draw(
            self.db, original['run_id'], alternate_inputs, observed_at=self.after)
        self.assertNotEqual(original['score_receipt_sha256'], other['score_receipt_sha256'])
        report = self.study([other])
        self.assertFalse(report['official_results_authenticated'])
        self.assertEqual(report['source_authenticity'], 'CALLER_UNVERIFIED')
        self.assertEqual(report['formal_A'], 0)
        self.assertEqual(report['decision'], 'NO_EDGE')


if __name__ == '__main__':
    unittest.main()
