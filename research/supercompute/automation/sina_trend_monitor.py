"""Read-only Sina secondary-source observation monitor for SSQ/DLT.

No tickets, predictions, raw outcome histories, or official-authentication claims
are persisted. This script does not interact with formal V4.7 or its ledgers.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SCHEMA = 'SSQDLT_SINA_SECONDARY_SOURCE_MONITOR_V1'
SOURCES = {
    'SSQ': {
        'url': 'https://lotto.sina.cn/trend/qxc_qlc_proxy.d.html?lottoType=ssq&actionType=chzs&type=50&dpc=1',
        'seed': 'SSQ/SSQ/resources/official_seed.json',
        'issue_len': 7, 'front_max': 33, 'front_n': 6, 'back_max': 16, 'back_n': 1,
    },
    'DLT': {
        'url': 'https://lotto.sina.cn/trend/qxc_qlc_proxy.d.html?lottoType=dlt&actionType=chzs&type=50',
        'seed': 'DLT/src/resources/official_seed.json',
        'issue_len': 5, 'front_max': 35, 'front_n': 5, 'back_max': 12, 'back_n': 2,
    },
}
MAX_BYTES = 1_500_000


class SourceBlocked(ValueError):
    pass


@dataclass(frozen=True)
class Draw:
    issue: str
    draw_at: str
    front: tuple[int, ...]
    back: tuple[int, ...]


class IssueParser(HTMLParser):
    """Only consider explicit div.issue/span.issue-no,time,red-ball,blue-ball."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.current = None
        self.field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set(a.get('class', '').split())
        if tag == 'div' and 'issue' in cls:
            if self.current is not None:
                raise SourceBlocked('NESTED_ISSUE')
            self.current = {'issue-no': [], 'time': [], 'red-ball': [], 'blue-ball': []}
            self.field = None
        elif tag == 'span' and self.current is not None:
            keys = ('issue-no', 'time', 'red-ball', 'blue-ball')
            self.field = next((x for x in keys if x in cls), None)
            if self.field in ('red-ball', 'blue-ball'):
                self.current[self.field].append('')

    def handle_data(self, data):
        if self.current is not None and self.field:
            if self.field in ('red-ball', 'blue-ball'):
                self.current[self.field][-1] += data

            else:
                self.current[self.field].append(data)

    def handle_endtag(self, tag):
        if tag == 'span':
            self.field = None
        if tag == 'div' and self.current is not None:
            self.rows.append(self.current)
            self.current = None
            self.field = None


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _hash(obj):
    return sha256(_canonical(obj)).hexdigest()


def _year_and_seq(issue, game):
    if game == 'SSQ':
        return int(issue[:4]), int(issue[4:])
    return 2000 + int(issue[:2]), int(issue[2:])


def _validate_ballset(numbers, max_number, count):
    if len(numbers) != count or any(type(x) is not int or not 1 <= x <= max_number for x in numbers):
        raise SourceBlocked('BALL_DOMAIN_OR_COUNT_INVALID')
    if sorted(set(numbers)) != list(numbers):
        raise SourceBlocked('BALLS_NOT_UNIQUE_SORTED')


def parse_trend_html(raw: bytes | str, game: str, *, now_utc=None) -> list[Draw]:
    if game not in SOURCES:
        raise ValueError('invalid game')
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8', errors='strict')
        except UnicodeError as e:
            raise SourceBlocked('SOURCE_UTF8_INVALID') from e
    p = IssueParser()
    try:
        p.feed(raw)
        p.close()
    except (ValueError, AssertionError) as e:
        raise SourceBlocked('SOURCE_HTML_STRUCTURE_INVALID') from e
    if not 20 <= len(p.rows) <= 500 or p.current is not None:
        raise SourceBlocked('SOURCE_ROW_COUNT_INVALID')
    spec = SOURCES[game]
    now_utc = now_utc or datetime.now(timezone.utc)
    rows = []
    seen = set()
    for row in p.rows:
        issue = ''.join(row['issue-no']).strip()
        timestamp = ''.join(row['time']).strip()
        if not re.fullmatch(r'[0-9]{%d}' % spec['issue_len'], issue):
            raise SourceBlocked('ISSUE_FORMAT_INVALID')
        try:
            local = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            fronts = tuple(int(x) for x in row['red-ball'])
            backs = tuple(int(x) for x in row['blue-ball'])
        except (ValueError, TypeError) as e:
            raise SourceBlocked('DRAW_FORMAT_INVALID') from e
        issue_year, seq = _year_and_seq(issue, game)
        if issue_year != local.year or not 1 <= seq <= 200:
            raise SourceBlocked('ISSUE_DATE_MISMATCH')
        if local.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc) > now_utc + timedelta(minutes=2):
            raise SourceBlocked('FUTURE_DRAW_DATE')
        _validate_ballset(fronts, spec['front_max'], spec['front_n'])
        _validate_ballset(backs, spec['back_max'], spec['back_n'])
        if issue in seen:
            raise SourceBlocked('DUPLICATE_ISSUE')
        seen.add(issue)
        rows.append(Draw(issue, local.isoformat(sep=' '), fronts, backs))
    for newer, older in zip(rows, rows[1:]):
        if newer.issue <= older.issue or newer.draw_at <= older.draw_at:
            raise SourceBlocked('SOURCE_NOT_DESCENDING')
        y1, n1 = _year_and_seq(newer.issue, game)
        y0, n0 = _year_and_seq(older.issue, game)
        if y1 == y0 and n1 != n0 + 1:
            raise SourceBlocked('ISSUE_GAP_WITHIN_YEAR')
        if y1 != y0 and (y1 != y0 + 1 or n1 != 1):
            raise SourceBlocked('ISSUE_YEAR_ROLLOVER_INVALID')
    return rows


def fetch_html(url: str, *, opener=urlopen):
    req = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; SSQDLT-SourceMonitor/1.0; research-only)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    try:
        with opener(req, timeout=20) as resp:
            if resp.status != 200:
                raise SourceBlocked('SOURCE_HTTP_NON_200')
            if urlsplit(resp.geturl()).hostname != 'lotto.sina.cn':
                raise SourceBlocked('SOURCE_REDIRECT_UNTRUSTED')
            raw = resp.read(MAX_BYTES + 1)
    except HTTPError as e:
        raise SourceBlocked('SOURCE_HTTP_%d' % e.code) from e
    except (URLError, TimeoutError, OSError) as e:
        raise SourceBlocked('SOURCE_NETWORK_FAILURE') from e
    if len(raw) > MAX_BYTES or not raw:
        raise SourceBlocked('SOURCE_BYTE_LENGTH_INVALID')
    return raw


def snapshot_overlap(rows: list[Draw], game: str, root: Path):
    path = root / SOURCES[game]['seed']
    with path.open('r', encoding='utf-8') as f:
        old = json.load(f)['draws']
    seed = {str(r['issue']): r for r in old}
    count = 0
    for row in rows:
        if row.issue not in seed:
            continue
        prior = seed[row.issue]
        if list(row.front) != prior['front'] or list(row.back) != prior['back']:
            raise SourceBlocked('SINA_SEED_CONFLICT')
        count += 1
    if not count:
        raise SourceBlocked('NO_SEED_ANCHOR')
    return count, len([r for r in rows if r.issue not in seed])


def _row_hash(game, row):
    return _hash({'game': game, 'issue': row.issue, 'date': row.draw_at,
                  'front': row.front, 'back': row.back})


def prior_status(game: str, state_dir: Path | None):
    if state_dir is None or not state_dir.is_dir():
        return None
    best = None
    for p in sorted(state_dir.glob('*.json')):
        with p.open('r', encoding='utf-8') as f:
            content = json.load(f)
        if content.get('schema') != SCHEMA:
            raise SourceBlocked('LEDGER_SCHEMA_INVALID')
        for item in content.get('games', []):
            if item.get('game') != game or item.get('status') not in ('PASS_SECONDARY', 'UNCHANGED'):
                continue
            if best is None or int(item['latest_issue']) > int(best['latest_issue']):
                best = item
            elif best['latest_issue'] == item['latest_issue'] and best['latest_draw_sha256'] != item['latest_draw_sha256']:
                raise SourceBlocked('LEDGER_PRIOR_CONFLICT')
    return best


def evaluate(game: str, root: Path, state_dir: Path | None, *, opener=urlopen, now_utc=None):
    spec = SOURCES[game]
    rows = parse_trend_html(fetch_html(spec['url'], opener=opener), game, now_utc=now_utc)
    matched, new_from_seed = snapshot_overlap(rows, game, root)
    newest = rows[0]
    previous = prior_status(game, state_dir)
    status = 'PASS_SECONDARY'
    new_since_prior = None
    if previous is not None:
        if newest.issue < previous['latest_issue']:
            raise SourceBlocked('SOURCE_ROLLBACK')
        old = next((r for r in rows if r.issue == previous['latest_issue']), None)
        if old is None or _row_hash(game, old) != previous['latest_draw_sha256']:
            raise SourceBlocked('SOURCE_PRIOR_ISSUE_CHANGED_OR_MISSING')
        new_since_prior = sum(r.issue > previous['latest_issue'] for r in rows)
        if newest.issue == previous['latest_issue']:
            if new_since_prior:
                raise SourceBlocked('SOURCE_STATE_INCONSISTENT')
            status = 'UNCHANGED'
    return {
        'game': game, 'status': status, 'source_kind': 'SINA_THIRD_PARTY_NOT_OFFICIAL',
        'latest_issue': newest.issue, 'latest_date': newest.draw_at[:10],
        'latest_draw_sha256': _row_hash(game, newest),
        'window_sha256': _hash([r.__dict__ for r in rows]),
        'window_issues': len(rows), 'seed_overlap': matched,
        'untracked_since_old_seed': new_from_seed,
        'new_since_prior_monitor': new_since_prior,
        'official_source_authenticated': False,
        'formal_A': 0, 'edge': 'NO_EDGE',
    }


def run(root: Path, state_dir: Path | None, *, opener=urlopen, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    games = []
    for game in ('SSQ', 'DLT'):
        try:
            games.append(evaluate(game, root, state_dir, opener=opener, now_utc=now_utc))
        except (SourceBlocked, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            code = str(e) if isinstance(e, SourceBlocked) else 'LOCAL_INPUT_OR_LEDGER_FAILURE'
            games.append({'game': game, 'status': 'BLOCKED', 'error_code': code,
                          'official_source_authenticated': False, 'formal_A': 0, 'edge': 'NO_EDGE'})
    return {'schema': SCHEMA, 'checked_at_utc': now_utc.isoformat(timespec='seconds'),
            'formal_A': 0, 'edge': 'NO_EDGE', 'games': games}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--prior-ledger', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.repo_root, args.prior_ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write('\n')
    # Never log draw numbers or HTML; GitHub step summary may consume this metadata.
    for item in report['games']:
        print(item['game'], item['status'], item.get('latest_issue', 'NONE'),
              item.get('new_since_prior_monitor', 'UNKNOWN'), item.get('error_code', ''))
    return 1 if any(item['status'] == 'BLOCKED' for item in report['games']) else 0


if __name__ == '__main__':
    sys.exit(main())
