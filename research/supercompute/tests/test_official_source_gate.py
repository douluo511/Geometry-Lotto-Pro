"""Offline issuer/Sina cross-check tests; never contact the public internet."""
from datetime import datetime, timedelta, timezone
import unittest

from research.supercompute.automation.official_source_gate import (
    OFFICIAL, SourceBlocked, crosscheck, official_rows, live_crosscheck,
)
from research.supercompute.automation.sina_trend_monitor import Draw, SOURCES, parse_trend_html


def data(game, n=10):
    is_ssq = game == 'SSQ'
    last = 2026130 if is_ssq else 26129
    front = (1, 2, 6, 16, 20, 28) if is_ssq else (2, 12, 14, 17, 33)
    back = (2,) if is_ssq else (7, 8)
    today = datetime(2026, 11, 12 if is_ssq else 11, 21, 15)
    return [Draw(str(last - i), (today - timedelta(days=i)).strftime('%Y-%m-%d %H:%M:%S'),
                 front, back) for i in range(n)]


def fake_official(game, rows):
    if game == 'SSQ':
        parts = ['<table class="lottery-history-table lottery-history-table--ssq"><thead><tr>'
                 '<th>期号</th><th>开奖日期</th></tr></thead><tbody>']
        for r in rows:
            parts.append('<tr><td>%s</td><td>%s(四)</td><td><span class="red">%s</span></td>'
                         '<td><span class="blue">%s</span></td></tr>' % (
                             r.issue, r.draw_at[:10],
                             ''.join('<i>%02d</i>' % n for n in r.front),
                             ''.join('<i>%02d</i>' % n for n in r.back)))
    else:
        parts = ['<div><table class="table table-border"><tr><td>发布日期</td>'
                 '<td>期号</td><td>开奖号码</td><td>详细</td></tr>']
        for r in rows:
            parts.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>详细</td></tr>' % (
                r.draw_at[:10], r.issue,
                ' '.join('%02d' % n for n in r.front + r.back)))
    return ''.join(parts) + '</tbody></table>'


def fake_sina(game, rows):
    parts = ['<html><body>']
    for r in rows:
        parts.append('<div class="issue"><span class="issue-no">%s</span>'
                     '<span class="time">%s</span>' % (r.issue, r.draw_at))
        parts.extend('<span class="red-ball">%02d</span>' % n for n in r.front)
        parts.extend('<span class="blue-ball">%02d</span>' % n for n in r.back)
        parts.append('</div>')
    parts.append('</body></html>')
    return ''.join(parts)


class OfficialTableTest(unittest.TestCase):
    def test_parse_both_issuers(self):
        for game in OFFICIAL:
            with self.subTest(game=game):
                rows = data(game, 10)
                decoded = official_rows(fake_official(game, rows), game)
                self.assertEqual(len(rows), len(decoded))
                self.assertEqual(rows[0].front, decoded[0].front)
                self.assertEqual(rows[-1].issue, decoded[-1].issue)

    def test_full_match_and_metadata(self):
        for game in OFFICIAL:
            with self.subTest(game=game):
                rows = data(game, 10)
                self.assertEqual(10, crosscheck(rows, rows, game)['matched_issues'])

    def test_official_issue_not_latest(self):
        rows = data('SSQ', 10)
        with self.assertRaisesRegex(SourceBlocked, 'LATEST_MISMATCH'):
            crosscheck(rows, rows[1:], 'SSQ')

    def test_official_conflicting_balls(self):
        rows = data('DLT', 10)
        altered = Draw(rows[0].issue, rows[0].draw_at, (2, 12, 14, 17, 34), rows[0].back)
        with self.assertRaisesRegex(SourceBlocked, 'DRAW_CONFLICT'):
            crosscheck(rows, [altered] + rows[1:], 'DLT')

    def test_official_conflicting_date(self):
        rows = data('SSQ', 10)
        altered = Draw(rows[0].issue, '2026-11-10', rows[0].front, rows[0].back)
        with self.assertRaisesRegex(SourceBlocked, 'DRAW_CONFLICT'):
            crosscheck(rows, [altered] + rows[1:], 'SSQ')

    def test_missing_official_table_blocks(self):
        with self.assertRaisesRegex(SourceBlocked, 'OFFICIAL_ROW_COUNT_INVALID'):
            official_rows('<html>pending loading</html>', 'SSQ')

    def test_official_duplicate_blocks(self):
        rows = data('DLT', 10)
        rows[1] = rows[0]
        with self.assertRaisesRegex(SourceBlocked, 'DUPLICATE_OFFICIAL_ISSUE'):
            official_rows(fake_official('DLT', rows), 'DLT')

    def test_official_out_of_order_blocks(self):
        rows = data('SSQ', 10)
        rows[0], rows[1] = rows[1], rows[0]
        with self.assertRaisesRegex(SourceBlocked, 'OFFICIAL_ISSUE_ORDER_INVALID'):
            official_rows(fake_official('SSQ', rows), 'SSQ')

    def test_official_ball_count_blocks(self):
        rows = data('DLT', 10)
        r = rows[0]
        rows[0] = Draw(r.issue, r.draw_at, r.front[:-1], r.back)
        with self.assertRaisesRegex(SourceBlocked, 'OFFICIAL_DRAW_DOMAIN_INVALID'):
            official_rows(fake_official('DLT', rows), 'DLT')

    def test_live_path_mocked(self):
        game = 'DLT'
        rows = data(game, 25)
        official = rows[:10]
        audit, decoded, verified = live_crosscheck(
            game, official_fetch=lambda x: fake_official(x, official).encode(),
            sina_fetch=lambda url: fake_sina(game, rows).encode(),
            now_utc=datetime(2026, 11, 13, tzinfo=timezone.utc),
        )
        self.assertEqual('26129', audit['latest_issue'])
        self.assertEqual(10, audit['matched_issues'])
        self.assertEqual(25, len(decoded))
        self.assertEqual(10, len(verified))
        self.assertNotEqual(audit['sina_html_sha256'], audit['official_html_sha256'])

    def test_sina_latest_mismatch_blocks(self):
        game = 'SSQ'
        rows = data(game, 25)
        with self.assertRaisesRegex(SourceBlocked, 'LATEST_MISMATCH'):
            live_crosscheck(
                game, official_fetch=lambda x: fake_official(x, rows[1:]).encode(),
                sina_fetch=lambda url: fake_sina(game, rows).encode(),
                now_utc=datetime(2026, 11, 13, tzinfo=timezone.utc),
            )


if __name__ == '__main__':
    unittest.main()
