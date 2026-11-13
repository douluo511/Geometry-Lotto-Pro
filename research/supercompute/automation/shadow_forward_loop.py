"""GitHub-backed research-only live forecasting, matching, sealing and scoring.

Sources must agree on latest game/date/balls before any new forecast or score.
Every receipt is create-only on a branch separate from formal V4.7. No paid
model calls. Git runner clock/Git commit are NOT RFC3161 trusted timestamps.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, time, timezone, date
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
from zoneinfo import ZoneInfo

from research.supercompute.automation.official_source_gate import live_crosscheck
from research.supercompute.automation.sina_trend_monitor import (
    Draw, SOURCES, SourceBlocked, snapshot_overlap
)

CHINA = ZoneInfo('Asia/Shanghai')
PREFIX = Path('research/forward_shadow_v1')
SCHEMA_TICKET = 'SSQDLT_OFFICIAL_CROSSCHECK_SHADOW_FORECAST_V1'
SCHEMA_SCORE = 'SSQDLT_OFFICIAL_CROSSCHECK_SHADOW_SCORE_V1'
MODEL_NAME = 'HISTORICAL_MARGINAL_SELECTION_V1'
SETTINGS = {
    'SSQ': {'schedule': {1, 3, 6}, 'last_hour': 21, 'last_minute': 15},
    'DLT': {'schedule': {0, 2, 5}, 'last_hour': 21, 'last_minute': 25},
}


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def fingerprint(x):
    return sha256(canonical(x)).hexdigest()


def load_json(path):
    if path.is_symlink():
        raise SourceBlocked('UNSAFE_LEDGER_SYMLINK')
    return json.loads(path.read_text(encoding='utf-8'))


def immutable_write(ledger, path, record):
    filename = ledger / PREFIX / path
    filename.parent.mkdir(parents=True, exist_ok=True)
    if filename.exists() or filename.is_symlink():
        if load_json(filename) != record:
            raise SourceBlocked('IMMUTABLE_LEDGER_CONFLICT')
        return False
    with filename.open('x', encoding='utf-8') as f:
        json.dump(record, f, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    return True


def seal_record(record):
    return {**record, 'content_sha256': fingerprint(record)}


def verify_record(record):
    dig = record.get('content_sha256')
    if not isinstance(dig, str) or len(dig) != 64:
        raise SourceBlocked('RECEIPT_DIGEST_MISSING')
    if fingerprint({k: v for k, v in record.items() if k != 'content_sha256'}) != dig:
        raise SourceBlocked('RECEIPT_TAMPERED')


def verify_ledger(ledger):
    root = ledger / PREFIX
    forecasts = {}
    scores = {}
    for directory, schema, sink in (
        ('forecasts', SCHEMA_TICKET, forecasts),
        ('scores', SCHEMA_SCORE, scores),
    ):
        for path in sorted((root / directory).glob('*.json')):
            rec = load_json(path)
            verify_record(rec)
            if rec.get('schema') != schema or rec.get('game') not in SETTINGS:
                raise SourceBlocked('LEDGER_SCHEMA_INVALID')
            key = (rec['game'], rec['target_issue'])
            if key in sink:
                raise SourceBlocked('DUPLICATE_LEDGER_ISSUE')
            sink[key] = rec
    for key, rec in scores.items():
        if key not in forecasts:
            raise SourceBlocked('SCORE_WITHOUT_FORECAST')
        if rec['original_forecast_sha256'] != forecasts[key]['content_sha256']:
            raise SourceBlocked('SCORE_NOT_BOUND_TO_FORECAST')
        if rec['scored_at_utc'] <= forecasts[key]['created_at_utc']:
            raise SourceBlocked('SCORE_TIME_NOT_AFTER_FORECAST')
    return {'forecasts': len(forecasts), 'scores': len(scores),
            'unscored': len(forecasts) - len(scores),
            'formal_A': 0, 'edge': 'NO_EDGE'}


def merged_history(root: Path, game: str, sina: list[Draw]) -> list[Draw]:
    seed = load_json(root / SOURCES[game]['seed'])['draws']
    last = seed[-1]['issue']
    snapshot_overlap(sina, game, root)
    from_seed = [Draw(str(x['issue']), x['draw_date'],
                      tuple(x['front']), tuple(x['back'])) for x in seed]
    unseen = [x for x in reversed(sina) if x.issue > last]
    if unseen and int(unseen[0].issue) != int(last) + 1:
        raise SourceBlocked('UNRESOLVED_HISTORY_GAP')
    for a, b in zip(unseen, unseen[1:]):
        if int(b.issue) != int(a.issue) + 1:
            raise SourceBlocked('UNRESOLVED_HISTORY_GAP')
    merged = from_seed + unseen
    if len({x.issue for x in merged}) != len(merged):
        raise SourceBlocked('HISTORY_DUPLICATE_ISSUE')
    if not all(a.issue < b.issue and a.draw_at[:10] < b.draw_at[:10]
               for a, b in zip(merged, merged[1:])):
        raise SourceBlocked('HISTORY_NOT_CHRONOLOGICAL')
    return merged


def marginal_probs(history: list[Draw], game: str, area: str,
                   method: str) -> list[float]:
    specs = SOURCES[game]
    maximum = specs['front_max' if area == 'front' else 'back_max']
    k = specs['front_n' if area == 'front' else 'back_n']
    baseline = k / maximum
    if method == 'UNIFORM':
        return [baseline] * maximum
    if method == 'HOT60':
        rows = history[-60:]
        weights = [1.0] * len(rows)
        alpha = 40.0
    elif method == 'EWMA30':
        rows = history[-120:]
        weights = [math.exp(-math.log(2) * (len(rows) - i - 1) / 30)
                   for i in range(len(rows))]
        alpha = 40.0
    else:
        raise ValueError('UNKNOWN_MODEL')
    den = sum(weights) + alpha
    counts = [alpha * baseline] * maximum
    for row, w in zip(rows, weights):
        for n in getattr(row, area):
            counts[n - 1] += w
    out = [x / den for x in counts]
    if abs(sum(out) - k) > 1e-8:
        raise AssertionError('MARGINAL_NORMALIZATION_FAILURE')
    return out


def model_evaluation(history: list[Draw], game: str):
    options = ('UNIFORM', 'HOT60', 'EWMA30')
    score = {m: 0.0 for m in options}
    # 60 time-ordered one-step-ahead log scores; every prediction uses prior rows.
    start = max(120, len(history) - 60)
    for idx in range(start, len(history)):
        prior = history[:idx]
        actual = history[idx]
        for m in options:
            for area in ('front', 'back'):
                probs = marginal_probs(prior, game, area, m)
                selected = set(getattr(actual, area))
                for j, p in enumerate(probs, start=1):
                    y = j in selected
                    score[m] += math.log(p) if y else math.log1p(-p)
    # Do not choose a flexible model on tiny or negative evidence. Improvement
    # threshold is a pre-set regularizer, not selected on future target draws.
    base = score['UNIFORM']
    winner = 'UNIFORM'
    for m in ('HOT60', 'EWMA30'):
        if score[m] > score[winner] + 1.0 and score[m] > base + 1.0:
            winner = m
    return winner, {k: round(v - base, 5) for k, v in score.items()}


def deterministic_ticket(history: list[Draw], game: str, model: str,
                         target: str):
    if model == 'UNIFORM':
        tag = 'MODEL_UNIFORM_V1'
        seed = int.from_bytes(sha256(f'{game}:{target}:{tag}'.encode()).digest()[:8],
                              'big')
        rng = random.Random(seed)
        return {
            'front': sorted(rng.sample(range(1, SOURCES[game]['front_max'] + 1),
                                      SOURCES[game]['front_n'])),
            'back': sorted(rng.sample(range(1, SOURCES[game]['back_max'] + 1),
                                     SOURCES[game]['back_n'])),
        }
    return {
        area: sorted(sorted(range(1, SOURCES[game][area + '_max'] + 1),
                            key=lambda x: (-marginal_probs(history, game, area, model)[x - 1], x))
                     [:SOURCES[game][area + '_n']])
        for area in ('front', 'back')
    }


def random_null(game: str, target: str):
    seed = int.from_bytes(sha256(f'{game}:{target}:INDEPENDENT_RANDOM_NULL_V1'.encode()).digest()[:8],
                          'big')
    rng = random.Random(seed)
    return {
        'front': sorted(rng.sample(range(1, SOURCES[game]['front_max'] + 1),
                                  SOURCES[game]['front_n'])),
        'back': sorted(rng.sample(range(1, SOURCES[game]['back_max'] + 1),
                                 SOURCES[game]['back_n'])),
    }


def target_next_date(game: str, last: str) -> date:
    d = date.fromisoformat(last)
    for i in range(1, 20):
        nxt = d + timedelta(days=i)
        if nxt.weekday() in SETTINGS[game]['schedule']:
            return nxt
    raise AssertionError('SCHEDULE_DATE_FAILURE')


def target_issue(game: str, issue: str, next_day: date):
    if game == 'SSQ':
        return str(next_day.year) + ('001' if str(next_day.year) != issue[:4]
                                    else f'{int(issue[4:]) + 1:03d}')
    return str(next_day.year % 100).zfill(2) + (
        '001' if str(next_day.year % 100).zfill(2) != issue[:2]
        else f'{int(issue[2:]) + 1:03d}')


def create_candidate(history, game, audit, ledger, now):
    latest = history[-1]
    nxt = target_next_date(game, latest.draw_at[:10])
    target = target_issue(game, latest.issue, nxt)
    if now.astimezone(CHINA) >= datetime.combine(nxt, time(19), tzinfo=CHINA):
        return {'status': 'AFTER_CONSERVATIVE_RESEARCH_CUTOFF', 'target_issue': target}
    if any(int(x.issue) >= int(target) for x in history):
        raise SourceBlocked('FUTURE_TARGET_ALREADY_IN_HISTORY')
    path = f'forecasts/{game}-{target}.json'
    existing = ledger / PREFIX / path
    if existing.exists():
        verify_record(load_json(existing))
        return {'status': 'ALREADY_FROZEN', 'target_issue': target}
    model, validation = model_evaluation(history, game)
    forecast = deterministic_ticket(history, game, model, target)
    baseline = random_null(game, target)
    payload = seal_record({
        'schema': SCHEMA_TICKET, 'game': game, 'target_issue': target,
        'target_date_estimate_not_official': nxt.isoformat(),
        'source_latest_issue': latest.issue,
        'history_sha256': fingerprint([r.__dict__ for r in history]),
        'source_crosscheck': {
            'official_url': audit['official_site'],
            'sina_url': audit['sina_site'],
            'official_html_sha256': audit['official_html_sha256'],
            'sina_html_sha256': audit['sina_html_sha256'],
            'official_window': audit['official_window'],
            'matched_issues': audit['matched_issues'],
        },
        'selection': {'algorithm': MODEL_NAME, 'chosen': model,
                      'validation_log_score_delta': validation,
                      'validation_last_60_only': True},
        'prediction': forecast, 'independent_random_null': baseline,
        'fable_review': {'model': 'claude-fable-5-2',
                         'status': 'NOT_CALLED_NO_AUTHORIZED_API_CREDENTIALS',
                         'model_result_sha256': None},
        'created_at_utc': now.astimezone(timezone.utc).isoformat(timespec='seconds'),
        'claimed_timestamp_trust': 'GITHUB_RUNNER_CLOCK_NOT_EXTERNAL_TSA',
        'formal_A': 0, 'edge': 'NO_EDGE', 'purchased': False,
    })
    immutable_write(ledger, path, payload)
    return {'status': 'NEW_SHADOW_FORECAST_SEALED_LOCALLY',
            'target_issue': target, 'chosen_model': model,
            'forecast_sha256': payload['content_sha256']}


def score_existing(game, official, ledger, now):
    matches = {x.issue: x for x in official}
    scored = []
    blocked = []
    for path in sorted((ledger / PREFIX / 'forecasts').glob(game + '-*.json')):
        saved = load_json(path)
        verify_record(saved)
        issue = saved['target_issue']
        scorepath = f'scores/{game}-{issue}.json'
        if (ledger / PREFIX / scorepath).exists():
            existing = load_json(ledger / PREFIX / scorepath)
            verify_record(existing)
            if existing['original_forecast_sha256'] != saved['content_sha256']:
                raise SourceBlocked('SCORE_FORECAST_LINK_CONFLICT')
            continue
        if issue not in matches:
            continue  # Can't score a result without issuer confirmation.
        result = matches[issue]
        # Only score a ticket allegedly issued before the observed draw.
        draw_utc = datetime.combine(
            date.fromisoformat(result.draw_at[:10]),
            time(SETTINGS[game]['last_hour'], SETTINGS[game]['last_minute']),
            tzinfo=CHINA).astimezone(timezone.utc)
        if datetime.fromisoformat(saved['created_at_utc']) >= draw_utc:
            blocked.append(issue)
            continue
        def hit(ticket):
            a = len(set(ticket['front']) & set(result.front))
            b = len(set(ticket['back']) & set(result.back))
            return {'front_hits': a, 'back_hits': b,
                    'full_jackpot': int(a == SOURCES[game]['front_n']
                                        and b == SOURCES[game]['back_n'])}
        payload = seal_record({
            'schema': SCHEMA_SCORE, 'game': game, 'target_issue': issue,
            'official_outcome': {'front': list(result.front),
                                 'back': list(result.back)},
            'official_public_table': OFFICIAL_URLS[game],
            'original_forecast_sha256': saved['content_sha256'],
            'model': hit(saved['prediction']),
            'random_null': hit(saved['independent_random_null']),
            'scored_at_utc': now.astimezone(timezone.utc).isoformat(timespec='seconds'),
            'research_only': True, 'formal_A': 0, 'edge': 'NO_EDGE',
        })
        immutable_write(ledger, scorepath, payload)
        scored.append(issue)
    return {'scored': scored, 'blocked_late_forecasts': blocked}


OFFICIAL_URLS = {
    'SSQ': 'https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous',
    'DLT': 'https://api.js-lottery.com/wfzq/dlt/data',
}


def process_game(game, repo_root, ledger, now, *, source=None):
    audit, sina, official = source or live_crosscheck(game, now_utc=now)
    history = merged_history(repo_root, game, sina)
    current = history[-1]
    official_issues = set(x.issue for x in official)
    # The rolling archive is a research working DB. Non-issuer-checked
    # historical records remain explicitly labeled and are not promoted.
    window = seal_record({
        'schema': 'SSQDLT_SHADOW_SOURCE_WINDOW_V1',
        'game': game, 'asof_issue': current.issue,
        'sina_records': [r.__dict__ for r in sina],
        'official_verified_issues': sorted(official_issues),
        'official_crosscheck_summary': audit,
        'contains_unverified_third_party_rows': len(official_issues) < len(sina),
        'formal_A': 0, 'edge': 'NO_EDGE',
    })
    immutable_write(ledger, f'draw_windows/{game}-{current.issue}.json', window)
    score = score_existing(game, official, ledger, now)
    new = create_candidate(history, game, audit, ledger, now)
    return {'game': game, 'status': 'PASS_RESEARCH_ONLY', 'latest': current.issue,
            'official_window': audit['official_window'],
            'official_match_count': audit['matched_issues'],
            'source_rows': len(sina), 'score': score, 'candidate': new,
            'formal_A': 0, 'edge': 'NO_EDGE'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo-root', type=Path, default=Path('.'))
    p.add_argument('--ledger', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--verify-ledger-only', action='store_true')
    args = p.parse_args()
    if args.verify_ledger_only:
        print(json.dumps(verify_ledger(args.ledger), sort_keys=True))
        return 0
    if not args.output:
        p.error('--output required')
    if args.output.exists():
        raise FileExistsError('OUTPUT_CREATE_ONLY')
    now = datetime.now(timezone.utc)
    verify_ledger(args.ledger)
    decisions = []
    for game in ('SSQ', 'DLT'):
        try:
            decisions.append(process_game(game, args.repo_root, args.ledger, now))
        except Exception as exc:
            decisions.append({'game': game, 'status': 'BLOCKED',
                              'reason': str(exc) if isinstance(exc, SourceBlocked)
                              else 'UNEXPECTED_RESEARCH_FAILURE',
                              'formal_A': 0, 'edge': 'NO_EDGE'})
    tick = {
        'schema': 'SSQDLT_SHADOW_END_TO_END_TICK_V1',
        'checked_at_utc': now.isoformat(timespec='seconds'),
        'fable_reviews_performed': 0,
        'official_issuer_signatures_verified': False,
        'external_trusted_timestamp_verified': False,
        'formal_A': 0, 'edge': 'NO_EDGE', 'results': decisions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(tick, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    for row in decisions:
        print(row['game'], row['status'], row.get('latest'),
              row.get('candidate', {}).get('status'), row.get('reason', ''))
    return int(any(x['status'] == 'BLOCKED' for x in decisions))


if __name__ == '__main__':
    raise SystemExit(main())
