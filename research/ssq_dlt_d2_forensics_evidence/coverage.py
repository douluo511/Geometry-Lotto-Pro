"""Strict two-source history coverage, isolated from frozen model code.

This entry never infers missing legal issues and never grants formal admission.
It has no scheduler, mail, cache, SQLite, search, or network side effects.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import traceback

from research.ssq_dlt_v45.sources import URLS, parse_original, validate_history
from research.ssq_dlt_v45.store import canonical, digest
from research.ssq_dlt_v45.workflow import validate_issue_sequence


class CoverageError(ValueError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details or {}


def strict_agree(game, left, right, now):
    """Require equal observed issue sets throughout the shared date range.

    A shorter source may omit an old prefix, but every omitted issue is exposed.
    Agreement cannot discover issues absent from both sources.
    """
    if game not in URLS:
        raise CoverageError('UNKNOWN_GAME')
    for label, supplied in (('left', left), ('right', right)):
        if isinstance(supplied, list):
            for row in supplied:
                if isinstance(row, dict) and row.get('game', game) != game:
                    raise CoverageError('SOURCE_ROW_GAME_MISMATCH', dict(source=label, issue=row.get('issue')))
    left = validate_history(game, left, now)
    right = validate_history(game, right, now)
    # Check identity before normalization can hide a game label or wrong issue
    # width/year. Single-row checks do not yet adjudicate asymmetric gaps.
    for row in left + right:
        validate_issue_sequence(game, [row])
    a, b = {row['issue']: row for row in left}, {row['issue']: row for row in right}
    latest_left, latest_right = left[-1]['issue'], right[-1]['issue']
    base = dict(game=game, left_count=len(left), right_count=len(right),
                left_first=left[0]['issue'], right_first=right[0]['issue'],
                left_last=latest_left, right_last=latest_right,
                left_normalized_sha256=digest(left), right_normalized_sha256=digest(right))
    if latest_left != latest_right:
        raise CoverageError('SOURCE_LATEST_ISSUE_DISAGREEMENT', base)
    lower = max(int(left[0]['issue']), int(right[0]['issue']))
    upper = int(latest_left)
    aa = {issue for issue in a if lower <= int(issue) <= upper}
    bb = {issue for issue in b if lower <= int(issue) <= upper}
    left_only, right_only = sorted(aa-bb, key=int), sorted(bb-aa, key=int)
    base.update(shared_numeric_bounds=[lower, upper],
                left_only_within_shared_range=left_only,
                right_only_within_shared_range=right_only)
    if left_only or right_only:
        raise CoverageError('INTERNAL_SOURCE_COVERAGE_DISAGREEMENT', base)
    common = sorted(aa & bb, key=int)
    if not common:
        raise CoverageError('EMPTY_SHARED_SOURCE_COVERAGE', base)
    conflicts = [issue for issue in common if a[issue] != b[issue]]
    if conflicts:
        raise CoverageError('OFFICIAL_SOURCE_CONFLICT', {**base, 'conflicting_issues': conflicts})
    rows = [a[issue] for issue in common]
    # Both sources can share an observable within-year gap. Preserve the
    # existing staged workflow's guard instead of weakening that path.
    validate_issue_sequence(game, rows)
    receipt = dict(schema='D2_STRICT_HISTORY_COVERAGE_1', status='PASS_OBSERVED_OVERLAP_ONLY',
        **base, common_count=len(rows), common_issues=common, history_sha256=digest(rows),
        excluded_left_prefix=sorted(set(a)-aa, key=int),
        excluded_right_prefix=sorted(set(b)-bb, key=int),
        full_history_completeness='BLOCKED_NO_AUTHORITATIVE_COMPLETE_ISSUE_CATALOG',
        jointly_missing_cross_year_issues_detectable=False,
        observed_within_year_sequence='PASS_CHECKED_NO_CALENDAR_INFERENCE', guessed_issue_numbers=False,
        official_next_legal_issue='BLOCKED', publication_asof_verified=False,
        formal_A=0, decision='NO_EDGE')
    return rows, receipt


def load_raw_pair(game, left_path, left_sha256, right_path, right_sha256, now):
    rows, provenance = [], []
    for index, (path, expected) in enumerate(((left_path, left_sha256), (right_path, right_sha256))):
        path = Path(path).resolve()
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected or len(expected) != 64:
            raise CoverageError('RAW_SOURCE_SHA_MISMATCH', dict(source_index=index, expected=expected, actual=actual))
        rows.append(parse_original(game, index, raw, now))
        provenance.append(dict(source_index=index, path=str(path), sha256=actual,
                               expected_parser_url=URLS[game][index],
                               current_network_fetch=False, authenticity='PINNED_CACHED_BYTES_NOT_NEW_NETWORK_ATTESTATION'))
    agreed, receipt = strict_agree(game, *rows, now)
    return agreed, {**receipt, 'raw_sources': provenance, 'validation_clock': now.isoformat()}


def guarded_preview(game, left, right, now, *, generator=None):
    """A deliberate research-only call: guard before generating any numbers."""
    rows, evidence = strict_agree(game, left, right, now)
    if generator is None:
        from research.ssq_dlt_v45.models import generate
        generator = generate
    preview = generator(game, 'UNASSIGNED', rows)
    return dict(status='RESEARCH_UNASSIGNED_NOT_FORMAL', target=None,
                coverage=evidence, preview=preview, formal_A=0, decision='NO_EDGE',
                qualified_prospective_samples=0)


def _write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n')
        handle.flush()
        os.fsync(handle.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', required=True, choices=tuple(URLS))
    parser.add_argument('--left', required=True, type=Path)
    parser.add_argument('--right', required=True, type=Path)
    parser.add_argument('--left-sha256', required=True)
    parser.add_argument('--right-sha256', required=True)
    parser.add_argument('--at', required=True, help='Timezone-aware validation clock; not historical availability evidence')
    parser.add_argument('--output', required=True, type=Path, help='New external directory, never overwritten')
    parser.add_argument('--research-preview', action='store_true', help='Explicit UNASSIGNED preview only')
    args = parser.parse_args(argv)
    out = args.output.resolve()
    inputs = [args.left.resolve(), args.right.resolve()]
    if any(path.is_relative_to(out) or out.is_relative_to(path.parent) for path in inputs):
        parser.error('output must be outside both raw-source parent trees')
    out.mkdir(parents=False, exist_ok=False)
    _write_new(out/'started.json', dict(status='STARTED_NOT_PASS', arguments=vars(args) | {'output':str(out), 'left':str(inputs[0]), 'right':str(inputs[1])},
        recorded_at_utc=datetime.now(timezone.utc).isoformat(), formal_A=0, decision='NO_EDGE'))
    try:
        now = datetime.fromisoformat(args.at)
        if now.tzinfo is None:
            raise CoverageError('AWARE_CLOCK_REQUIRED')
        rows, receipt = load_raw_pair(args.game, args.left, args.left_sha256, args.right, args.right_sha256, now)
        answer = dict(status=receipt['status'], coverage=receipt, formal_A=0, decision='NO_EDGE',
                      current_network_fetch=False, official_next_legal_issue='BLOCKED')
        if args.research_preview:
            # Recheck exactly the accepted rows; no unguarded cache or old runtime.
            answer['research_preview'] = guarded_preview(args.game, rows, rows, now)
        _write_new(out/'coverage.json', answer)
        print(canonical(dict(status=answer['status'], output=str(out), formal_A=0, decision='NO_EDGE')))
        return 0
    except Exception as exc:
        _write_new(out/'failure.json', dict(status='FAIL', error_type=type(exc).__name__, reason=str(exc),
                   details=getattr(exc,'details',{}), traceback=traceback.format_exc(), formal_A=0, decision='NO_EDGE'))
        print(canonical(dict(status='FAIL', reason=str(exc), output=str(out))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
