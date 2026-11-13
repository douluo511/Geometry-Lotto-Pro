"""Fail-closed official-issuer cross-check for the SSQ/DLT Sina research monitor.

Official: Shanghai Welfare Lottery Center (SSQ) and Jiangsu Sports Lottery
Center (DLT). Sina is third-party, never an issuer. This only establishes
matching public HTML values at fetch time, NOT a timestamped issuer signature.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from research.supercompute.automation.sina_trend_monitor import (
    SOURCES, Draw, SourceBlocked, fetch_html, parse_trend_html
)

OFFICIAL = {
    'SSQ': {
        'url': 'https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous',
        'table_class': 'lottery-history-table--ssq',
        'host': 'www.swlc.net.cn',
    },
    'DLT': {
        'url': 'https://api.js-lottery.com/wfzq/dlt/data',
        'table_class': 'table-border',
        'host': 'api.js-lottery.com',
    },
}
MAX_OFFICIAL_BYTES = 1_200_000


class TargetTable(HTMLParser):
    def __init__(self, table_class):
        super().__init__(convert_charrefs=True)
        self.table_class = table_class
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []
        self.table_seen = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'table' and self.table_class in attributes.get('class', '').split():
            if self.table_seen:
                raise SourceBlocked('MULTIPLE_OFFICIAL_TABLES')
            self.in_table = True
            self.table_seen = True
        elif self.in_table and tag == 'tr':
            self.in_row = True
            self.row = []
        elif self.in_table and self.in_row and tag == 'td':
            self.in_cell = True
            self.cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.in_cell:
            self.row.append(''.join(self.cell).strip())
            self.in_cell = False
        elif tag == 'tr' and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
        elif tag == 'table' and self.in_table:
            self.in_table = False


def official_rows(html: bytes | str, game: str) -> list[Draw]:
    if game not in OFFICIAL:
        raise ValueError('unknown game')
    if isinstance(html, bytes):
        try:
            html = html.decode('utf-8', errors='strict')
        except UnicodeError as exc:
            raise SourceBlocked('OFFICIAL_ENCODING_INVALID') from exc
    parser = TargetTable(OFFICIAL[game]['table_class'])
    parser.feed(html)
    parser.close()
    if not parser.table_seen or not 5 <= len(parser.rows) <= 200:
        raise SourceBlocked('OFFICIAL_ROW_COUNT_INVALID')
    ans = []
    seen = set()
    spec = SOURCES[game]
    for cells in parser.rows:
        if game == 'SSQ':
            if len(cells) < 4:
                raise SourceBlocked('OFFICIAL_SSQ_COLUMNS_INVALID')
            issue, day = cells[:2]
            front_tokens = re.findall(r'\d\d', re.sub(r'\s+', '', cells[2]))
            back_tokens = re.findall(r'\d\d', re.sub(r'\s+', '', cells[3]))
        else:
            if len(cells) < 3:
                raise SourceBlocked('OFFICIAL_DLT_COLUMNS_INVALID')
            day, issue = cells[:2]
            all_tokens = re.findall(r'\d\d', cells[2])
            front_tokens = all_tokens[:spec['front_n']]
            back_tokens = all_tokens[spec['front_n']:]
        if not re.fullmatch(r'\d{' + str(spec['issue_len']) + r'}', issue):
            raise SourceBlocked('OFFICIAL_ISSUE_INVALID')
        match = re.match(r'(\d{4}-\d{2}-\d{2})', day)
        if not match:
            raise SourceBlocked('OFFICIAL_DATE_INVALID')
        d = match.group(1)
        try:
            date.fromisoformat(d)
            front = tuple(int(n) for n in front_tokens)
            back = tuple(int(n) for n in back_tokens)
        except ValueError as exc:
            raise SourceBlocked('OFFICIAL_DRAW_INVALID') from exc
        if (len(front) != spec['front_n'] or len(back) != spec['back_n']
                or front != tuple(sorted(set(front)))
                or back != tuple(sorted(set(back)))
                or not all(1 <= n <= spec['front_max'] for n in front)
                or not all(1 <= n <= spec['back_max'] for n in back)):
            raise SourceBlocked('OFFICIAL_DRAW_DOMAIN_INVALID')
        if issue in seen:
            raise SourceBlocked('DUPLICATE_OFFICIAL_ISSUE')
        seen.add(issue)
        ans.append(Draw(issue, d, front, back))
    if ans != sorted(ans, key=lambda r: r.issue, reverse=True):
        raise SourceBlocked('OFFICIAL_ISSUE_ORDER_INVALID')
    return ans


def fetch_official(game: str, *, opener=urlopen) -> bytes:
    info = OFFICIAL[game]
    request = Request(info['url'], headers={
        'User-Agent': 'Mozilla/5.0 (compatible; SSQDLT-IssuerCrosscheck/1.0)',
        'Accept': 'text/html,application/xhtml+xml'
    })
    try:
        with opener(request, timeout=20) as response:
            if response.status != 200:
                raise SourceBlocked('OFFICIAL_HTTP_NON_200')
            if urlsplit(response.geturl()).hostname != info['host']:
                raise SourceBlocked('OFFICIAL_UNTRUSTED_REDIRECT')
            data = response.read(MAX_OFFICIAL_BYTES + 1)
    except SourceBlocked:
        raise
    except Exception as exc:
        raise SourceBlocked('OFFICIAL_NETWORK_BLOCKED') from exc
    if not data or len(data) > MAX_OFFICIAL_BYTES:
        raise SourceBlocked('OFFICIAL_HTML_BYTES_INVALID')
    return data


def crosscheck(sina: list[Draw], official: list[Draw], game: str) -> dict:
    if not sina or not official:
        raise SourceBlocked('EMPTY_SOURCE')
    if official[0].issue != sina[0].issue:
        raise SourceBlocked('ISSUER_SINA_LATEST_MISMATCH')
    by_issue = {r.issue: r for r in sina}
    for row in official:
        current = by_issue.get(row.issue)
        if current is None:
            raise SourceBlocked('ISSUER_ISSUE_MISSING_FROM_SINA_WINDOW')
        if (row.front, row.back, row.draw_at[:10]) != (
                current.front, current.back, current.draw_at[:10]):
            raise SourceBlocked('ISSUER_SINA_DRAW_CONFLICT')
    return {
        'game': game,
        'status': 'PASS_OFFICIAL_PUBLIC_TABLE_CROSSCHECK',
        'latest_issue': sina[0].issue,
        'latest_date': sina[0].draw_at[:10],
        'official_window': len(official),
        'sina_window': len(sina),
        'matched_issues': len(official),
        'official_checked_issues': [r.issue for r in official],
        'not_independently_signature_verified': True,
        'official_site': OFFICIAL[game]['url'],
        'sina_site': SOURCES[game]['url'],
    }


def live_crosscheck(game: str, *, official_fetch=fetch_official, sina_fetch=fetch_html,
                    now_utc=None):
    secondary_bytes = sina_fetch(SOURCES[game]['url'])
    official_bytes = official_fetch(game)
    sina = parse_trend_html(secondary_bytes, game, now_utc=now_utc)
    verified = official_rows(official_bytes, game)
    audit = crosscheck(sina, verified, game)
    audit['official_html_sha256'] = sha256(official_bytes).hexdigest()
    audit['sina_html_sha256'] = sha256(secondary_bytes).hexdigest()
    return audit, sina, verified


def main():
    import argparse
    from datetime import datetime, timezone
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    outcome = {
        'schema': 'SSQDLT_OFFICIAL_CROSSCHECK_V1',
        'run_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'games': [], 'formal_A': 0, 'edge': 'NO_EDGE',
        'independent_issuer_signature_verified': False,
    }
    for game in ('SSQ', 'DLT'):
        try:
            audit, _, _ = live_crosscheck(game)
            outcome['games'].append(audit)
        except Exception as exc:
            outcome['games'].append({
                'game': game, 'status': 'BLOCKED',
                'reason': str(exc) if isinstance(exc, SourceBlocked) else 'UNHANDLED_SOURCE_FAILURE',
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(outcome, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write('\n')
    for g in outcome['games']:
        print(g['game'], g['status'], g.get('latest_issue', ''), g.get('reason', ''))
    return int(any(x['status'] == 'BLOCKED' for x in outcome['games']))


if __name__ == '__main__':
    raise SystemExit(main())
