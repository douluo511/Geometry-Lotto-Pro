"""Offline contract tests: fake Sina HTML and local fixture snapshots only."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.automation.sina_trend_monitor import (
    SCHEMA, SOURCES, SourceBlocked, _row_hash,
    parse_trend_html, run,
)

NOW = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)


def fixtures(game, count=100, first=None):
    spec = SOURCES[game]
    if first is None:
        first = 2026130 if game == 'SSQ' else 26130
    out = []
    for i in range(count):
        issue = str(first - i)
        d = (datetime(2026, 11, 12, 21, 15, 0) - timedelta(days=i)).strftime('%Y-%m-%d %H:%M:%S')
        front = list(range(1, spec['front_n'] + 1))
        back = list(range(1, spec['back_n'] + 1))
        out.append(dict(issue=issue, draw_at=d, front=front, back=back))
    return out


def html(rows):
    parts = ['<html><body><div style="display:none!important">']
    for r in rows:
        parts += ['<div class="issue"><span class="issue-no">', r['issue'],
                  '</span><span class="time">', r['draw_at'], '</span>']
        for n in r['front']:
            parts.append('<span class="red-ball">%02d</span>' % n)
        for n in r['back']:
            parts.append('<span class="blue-ball">%02d</span>' % n)
        parts.append('</div>')
    parts.append('</div></body></html>')
    return ''.join(parts).encode('utf-8')


class FakeResponse:
    status = 200
    def __init__(self, b):
        self.data = io.BytesIO(b)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.data.close()
    def geturl(self):
        return 'https://lotto.sina.cn/trend/qxc_qlc_proxy.d.html'
    def read(self, n):
        return self.data.read(n)


class TrendMonitorTest(unittest.TestCase):
    def test_both_games_100_rows(self):
        for game in SOURCES:
            with self.subTest(game=game):
                data = fixtures(game)
                parsed = parse_trend_html(html(data), game, now_utc=NOW)
                self.assertEqual(100, len(parsed))
                self.assertEqual(data[0]['issue'], parsed[0].issue)
                self.assertEqual(tuple(data[0]['front']), parsed[0].front)

    def test_reject_ball_out_of_range(self):
        a = fixtures('SSQ')
        a[0]['front'][-1] = 34
        with self.assertRaisesRegex(SourceBlocked, 'BALL'):
            parse_trend_html(html(a), 'SSQ', now_utc=NOW)

    def test_reject_ball_duplicate_and_ordering(self):
        for v in ([1, 1, 2, 3, 4, 5], [2, 1, 3, 4, 5, 6]):
            a = fixtures('SSQ')
            a[0]['front'] = v
            with self.assertRaisesRegex(SourceBlocked, 'BALL'):
                parse_trend_html(html(a), 'SSQ', now_utc=NOW)

    def test_reject_duplicate_issue(self):
        a = fixtures('SSQ')
        a[1]['issue'] = a[0]['issue']
        with self.assertRaises(SourceBlocked):
            parse_trend_html(html(a), 'SSQ', now_utc=NOW)

    def test_reject_future_issues(self):
        a = fixtures('SSQ')
        a[0]['draw_at'] = '2026-11-18 21:15:00'
        with self.assertRaisesRegex(SourceBlocked, 'FUTURE_DRAW_DATE'):
            parse_trend_html(html(a), 'SSQ', now_utc=NOW)

    def test_reject_missing_issues(self):
        a = fixtures('SSQ')
        a.pop(11)
        with self.assertRaisesRegex(SourceBlocked, 'ISSUE_GAP'):
            parse_trend_html(html(a), 'SSQ', now_utc=NOW)

    def test_reject_empty_html(self):
        with self.assertRaisesRegex(SourceBlocked, 'SOURCE_ROW_COUNT_INVALID'):
            parse_trend_html('<div>Loading</div>', 'SSQ', now_utc=NOW)

    def test_reject_invalid_unicode(self):
        with self.assertRaisesRegex(SourceBlocked, 'SOURCE_UTF8_INVALID'):
            parse_trend_html(b'\xff', 'SSQ', now_utc=NOW)

    def test_reject_untrusted_redirect(self):
        class Bad(FakeResponse):
            def geturl(self): return 'https://evil.example/x'
        with self.assertRaisesRegex(SourceBlocked, 'SOURCE_REDIRECT_UNTRUSTED'):
            from research.supercompute.automation.sina_trend_monitor import fetch_html
            fetch_html(SOURCES['SSQ']['url'], opener=lambda request, timeout: Bad(html(fixtures('SSQ'))))

    def _temp_seed(self, base):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        for game in SOURCES:
            path = root / SOURCES[game]['seed']
            path.parent.mkdir(parents=True, exist_ok=True)
            baseline = base[game][5:]
            path.write_text(json.dumps({'draws': [
                {'issue': r['issue'], 'front': r['front'], 'back': r['back']}
                for r in baseline
            ]}), encoding='utf8')
        return tmp, root

    def test_bootstrap_overlap_metadata_only_and_unverified(self):
        base = {g: fixtures(g) for g in SOURCES}
        temp, root = self._temp_seed(base)
        with temp:
            def op(req, timeout):
                game = 'SSQ' if 'lottoType=ssq' in req.full_url else 'DLT'
                return FakeResponse(html(base[game]))
            result = run(root, None, opener=op, now_utc=NOW)
            self.assertEqual(SCHEMA, result['schema'])
            for item in result['games']:
                self.assertEqual('PASS_SECONDARY', item['status'])
                self.assertEqual(95, item['seed_overlap'])
                self.assertEqual(5, item['untracked_since_old_seed'])
                self.assertFalse(item['official_source_authenticated'])
                self.assertEqual(0, item['formal_A'])
                self.assertEqual('NO_EDGE', item['edge'])
                self.assertNotIn('front', str(item))
                self.assertNotIn('back', str(item))

    def test_detect_snapshot_conflict_fail_closed(self):
        base = {g: fixtures(g) for g in SOURCES}
        temp, root = self._temp_seed(base)
        with temp:
            a = base['SSQ']
            a[7]['front'] = [1, 2, 3, 4, 5, 8]
            result = run(root, None, opener=lambda req, timeout: FakeResponse(html(
                base['SSQ' if 'ssq' in req.full_url else 'DLT'])), now_utc=NOW)
            self.assertEqual('BLOCKED', result['games'][0]['status'])
            self.assertEqual('SINA_SEED_CONFLICT', result['games'][0]['error_code'])
            self.assertEqual('PASS_SECONDARY', result['games'][1]['status'])

    def test_previous_receipt_unchanged_then_rollback_blocked(self):
        base = {g: fixtures(g) for g in SOURCES}
        temp, root = self._temp_seed(base)
        with temp:
            state = root / 'receipts'
            state.mkdir()
            latest = base['SSQ'][0]
            from research.supercompute.automation.sina_trend_monitor import Draw
            row = Draw(latest['issue'], latest['draw_at'], tuple(latest['front']), tuple(latest['back']))
            prior = {'schema': SCHEMA, 'games': [{
                'game': 'SSQ', 'status': 'PASS_SECONDARY',
                'latest_issue': latest['issue'], 'latest_draw_sha256': _row_hash('SSQ', row),
            }]}
            (state / 'old.json').write_text(json.dumps(prior))
            def op(req, timeout):
                game = 'SSQ' if 'ssq' in req.full_url else 'DLT'
                return FakeResponse(html(base[game]))
            result = run(root, state, opener=op, now_utc=NOW)
            self.assertEqual('UNCHANGED', result['games'][0]['status'])
            self.assertEqual(0, result['games'][0]['new_since_prior_monitor'])
            base['SSQ'].pop(0)
            older = dict(base['SSQ'][-1]); older['issue'] = str(int(older['issue'])-1)
            older['draw_at'] = '2026-08-04 21:15:00'
            base['SSQ'].append(older)
            result = run(root, state, opener=op, now_utc=NOW)
            self.assertEqual('BLOCKED', result['games'][0]['status'])
            self.assertEqual('SOURCE_ROLLBACK', result['games'][0]['error_code'])

    def test_previous_receipt_hash_changed_blocked(self):
        base = {g: fixtures(g) for g in SOURCES}
        temp, root = self._temp_seed(base)
        with temp:
            state = root / 'receipts'; state.mkdir()
            old = base['SSQ'][3]
            (state / 'old.json').write_text(json.dumps({'schema': SCHEMA, 'games': [{
                'game': 'SSQ', 'status': 'PASS_SECONDARY', 'latest_issue': old['issue'],
                'latest_draw_sha256': '0'*64,
            }]}))
            result = run(root, state, opener=lambda req, timeout: FakeResponse(html(
                base['SSQ' if 'ssq' in req.full_url else 'DLT'])), now_utc=NOW)
            self.assertEqual('SOURCE_PRIOR_ISSUE_CHANGED_OR_MISSING', result['games'][0]['error_code'])

    def test_source_down_receipt_not_forecast(self):
        def op(req, timeout):
            raise OSError('no network')
        result = run(Path('.'), None, opener=op, now_utc=NOW)
        self.assertTrue(all(x['status'] == 'BLOCKED' for x in result['games']))
        self.assertTrue(all(x['formal_A'] == 0 for x in result['games']))
        self.assertTrue(all('front' not in x and 'back' not in x for x in result['games']))


if __name__ == '__main__':
    unittest.main()
