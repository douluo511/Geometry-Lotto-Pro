"""Contract tests for research-only, strict past-only issue sealing and scoring."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.automation.shadow_forward_loop import (
    PREFIX, SCHEMA_TICKET, CHINA, SourceBlocked, create_candidate,
    deterministic_ticket, marginal_probs, model_evaluation,
    random_null, score_existing, seal_record, target_issue, target_next_date,
    verify_ledger, verify_record, immutable_write, process_game,
)
from research.supercompute.automation.sina_trend_monitor import SOURCES, Draw
from research.supercompute.automation.official_source_gate import OFFICIAL


def history(game, count=170):
    last = 2026130 if game == 'SSQ' else 26129
    base = datetime(2026, 11, 12 if game == 'SSQ' else 11, 21, 15, 0)
    arr = []
    spec = SOURCES[game]
    for i in reversed(range(count)):
        seed = int(str(last - i)[-3:])
        front = sorted(((seed * 7 + j * 11) % spec['front_max']) + 1 for j in range(spec['front_n']))
        back = sorted(((seed * 5 + j * 3) % spec['back_max']) + 1 for j in range(spec['back_n']))
        # Avoid invalid unique scenarios by falling back to a legal deterministic set.
        if len(set(front)) != len(front):
            front = list(range(1, spec['front_n'] + 1))
        if len(set(back)) != len(back):
            back = list(range(1, spec['back_n'] + 1))
        arr.append(Draw(str(last - i),
                        (base - timedelta(days=i)).strftime('%Y-%m-%d %H:%M:%S'),
                        tuple(front), tuple(back)))
    return arr


def audit(game):
    return {'official_site': OFFICIAL[game]['url'],
            'sina_site': SOURCES[game]['url'],
            'official_html_sha256': 'a' * 64,
            'sina_html_sha256': 'b' * 64,
            'official_window': 10, 'matched_issues': 10}


class ShadowForwardTests(unittest.TestCase):
    def test_random_null_stable_and_legal(self):
        for game in SOURCES:
            x = random_null(game, '2099999')
            self.assertEqual(x, random_null(game, '2099999'))
            self.assertEqual(len(x['front']), SOURCES[game]['front_n'])
            self.assertEqual(len(x['back']), SOURCES[game]['back_n'])
            self.assertEqual(len(set(x['front'])), len(x['front']))

    def test_marginal_normalization_all_models(self):
        for game in SOURCES:
            rows = history(game)
            for method in ['UNIFORM', 'HOT60', 'EWMA30']:
                for area in ('front', 'back'):
                    p = marginal_probs(rows, game, area, method)
                    self.assertAlmostEqual(sum(p), SOURCES[game][area + '_n'])
                    self.assertTrue(all(0 < x < 1 for x in p))

    def test_model_select_runs_and_produces_ticket(self):
        for game in SOURCES:
            rows = history(game)
            chosen, score = model_evaluation(rows, game)
            self.assertIn(chosen, ('UNIFORM', 'HOT60', 'EWMA30'))
            self.assertEqual(0, score['UNIFORM'])
            t = deterministic_ticket(rows, game, chosen, '2099999')
            for area in ('front', 'back'):
                self.assertEqual(len(t[area]), SOURCES[game][area + '_n'])
                self.assertEqual(t[area], sorted(set(t[area])))

    def test_calendar_next_date(self):
        self.assertEqual('2026-11-15', target_next_date('SSQ', '2026-11-12').isoformat())
        self.assertEqual('2026-11-14', target_next_date('DLT', '2026-11-11').isoformat())
        self.assertEqual('2026131', target_issue('SSQ', '2026130',
                         target_next_date('SSQ', '2026-11-12')))
        self.assertEqual('26130', target_issue('DLT', '26129',
                         target_next_date('DLT', '2026-11-11')))

    def test_issue_year_rollover(self):
        self.assertEqual('2027001', target_issue('SSQ', '2026153',
                         datetime(2027, 1, 3).date()))
        self.assertEqual('27001', target_issue('DLT', '26152',
                         datetime(2027, 1, 2).date()))

    def test_local_seal_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = history('SSQ')
            now = datetime(2026, 11, 13, 3, tzinfo=timezone.utc)
            first = create_candidate(rows, 'SSQ', audit('SSQ'), base, now)
            self.assertEqual('NEW_SHADOW_FORECAST_SEALED_LOCALLY', first['status'])
            second = create_candidate(rows, 'SSQ', audit('SSQ'), base, now)
            self.assertEqual('ALREADY_FROZEN', second['status'])
            self.assertEqual(1, verify_ledger(base)['forecasts'])
            path = base / PREFIX / 'forecasts/SSQ-2026131.json'
            issued = json.loads(path.read_text())
            self.assertEqual(SCHEMA_TICKET, issued['schema'])
            self.assertEqual('NOT_CALLED_NO_AUTHORIZED_API_CREDENTIALS',
                             issued['fable_review']['status'])
            self.assertEqual(issued['content_sha256'], first['forecast_sha256'])
            self.assertEqual(0, issued['formal_A'])

    def test_never_issue_after_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
            result = create_candidate(history('SSQ'), 'SSQ', audit('SSQ'),
                                      Path(tmp), now)
            self.assertEqual('AFTER_CONSERVATIVE_RESEARCH_CUTOFF', result['status'])
            self.assertEqual(0, verify_ledger(Path(tmp))['forecasts'])

    def test_mutation_rejected_and_digest_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            obj = seal_record({'schema': SCHEMA_TICKET, 'game': 'SSQ',
                               'target_issue': '2026131', 'created_at_utc': '2026-11-13T00:00:00+00:00'})
            self.assertTrue(immutable_write(base, 'forecasts/SSQ-2026131.json', obj))
            self.assertFalse(immutable_write(base, 'forecasts/SSQ-2026131.json', obj))
            bad = {**obj, 'target_issue': '2026132'}
            with self.assertRaisesRegex(SourceBlocked, 'IMMUTABLE_LEDGER_CONFLICT'):
                immutable_write(base, 'forecasts/SSQ-2026131.json', bad)
            with self.assertRaisesRegex(SourceBlocked, 'RECEIPT_TAMPERED'):
                verify_record(bad)

    def test_postdraw_score_requires_issuer_confirmed_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = history('DLT')
            create_candidate(rows, 'DLT', audit('DLT'), base,
                             datetime(2026, 11, 13, tzinfo=timezone.utc))
            future = Draw('26130', '2026-11-14', (1, 5, 8, 12, 25), (2, 8))
            no = score_existing('DLT', [], base, datetime(2026, 11, 15, tzinfo=timezone.utc))
            self.assertEqual([], no['scored'])
            yes = score_existing('DLT', [future], base,
                                 datetime(2026, 11, 15, tzinfo=timezone.utc))
            self.assertEqual(['26130'], yes['scored'])
            self.assertEqual(1, verify_ledger(base)['scores'])
            self.assertEqual([], score_existing(
                'DLT', [future], base, datetime(2026, 11, 16, tzinfo=timezone.utc))['scored'])

    def test_blocks_retroactive_fake_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = history('DLT')
            create_candidate(rows, 'DLT', audit('DLT'), base,
                             datetime(2026, 11, 13, tzinfo=timezone.utc))
            path = base / PREFIX / 'forecasts/DLT-26130.json'
            old = json.loads(path.read_text())
            forged = {k: v for k, v in old.items() if k != 'content_sha256'}
            forged['created_at_utc'] = '2026-11-14T13:50:00+00:00'
            path.write_text(json.dumps(seal_record(forged)), encoding='utf8')
            future = Draw('26130', '2026-11-14', (1, 5, 8, 12, 25), (2, 8))
            no = score_existing('DLT', [future], base,
                                datetime(2026, 11, 15, tzinfo=timezone.utc))
            self.assertEqual(['26130'], no['blocked_late_forecasts'])
            self.assertEqual([], no['scored'])

    def test_score_cannot_be_detached_from_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = history('SSQ')
            create_candidate(rows, 'SSQ', audit('SSQ'), base,
                             datetime(2026, 11, 13, tzinfo=timezone.utc))
            target = '2026131'
            fake = seal_record({
                'schema': 'SSQDLT_OFFICIAL_CROSSCHECK_SHADOW_SCORE_V1',
                'game': 'SSQ', 'target_issue': target,
                'original_forecast_sha256': 'f' * 64,
                'scored_at_utc': '2026-11-16T00:00:00+00:00'})
            immutable_write(base, 'scores/SSQ-' + target + '.json', fake)
            with self.assertRaisesRegex(SourceBlocked, 'SCORE_NOT_BOUND_TO_FORECAST'):
                verify_ledger(base)


if __name__ == '__main__':
    unittest.main()
