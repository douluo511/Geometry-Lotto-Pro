"""Geometry Lotto Pro SSQ exact-EXE acceptance launcher.

The GUI is the default.  --check modes are machine-readable acceptance paths used
by GitHub Windows runners against the exact built EXE bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
import traceback
from pathlib import Path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _write_result(path: str | None, payload: dict) -> None:
    if not path:
        return
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(dest)


def _random_world(draws, seed: int):
    from glp.domain import Draw
    rng = random.Random(seed)
    result = []
    for d in draws:
        reds = tuple(sorted(rng.sample(range(1, 34), 6)))
        blue = (rng.randint(1, 16),)
        result.append(Draw(d.issue, d.draw_date, reds, blue))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', choices=[
        'self', 'science', 'update', 'predict', 'audit', 'gui',
        'integrity-tamper', 'offline-failclosed', 'corrupt-repair',
        'random-world-101', 'random-world-202', 'random-world-303',
    ])
    parser.add_argument('--result-file')
    args = parser.parse_args()

    if not args.check:
        from glp.gui import run_gui
        return int(run_gui() or 0)

    if not args.result_file:
        parser.error('--result-file required with --check')

    out = {
        'status': 'FAIL',
        'scope': args.check,
        'platform': sys.platform,
        'python': sys.version,
        'final_release_gate': 'PENDING',
    }
    if getattr(sys, 'frozen', False):
        out['exe_sha256'] = _sha256_file(Path(sys.executable))
        out['exe_path'] = str(Path(sys.executable).resolve())

    try:
        from glp.constants import GAME, APP_VERSION
        from glp.service import LottoService
        from glp.storage import Store
        out.update(game=GAME, version=APP_VERSION)

        with tempfile.TemporaryDirectory(prefix='glp-ssq-acceptance-') as td:
            root = Path(td)
            svc = LottoService(Store(root))

            if args.check == 'self':
                r = svc.self_test()
                status = r.get('status', 'FAIL')

            elif args.check == 'science':
                from glp.evidence import run_evidence_court
                svc.ensure_seed()
                draws, _ = svc.store.load_draws()
                r = run_evidence_court(draws)
                status = r.get('software_verdict', 'FAIL')

            elif args.check == 'update':
                r = svc.update()
                status = 'PASS' if r.get('crosscheck_status') == 'PASS' else 'FAIL'

            elif args.check == 'predict':
                r = svc.predict()
                status = (r.get('final_gate') or {}).get('status', 'FAIL')

            elif args.check == 'audit':
                before = svc._freeze_count()
                r = svc.audit()
                after = svc._freeze_count()
                r['acceptance_freeze_before'] = before
                r['acceptance_freeze_after'] = after
                status = 'PASS' if r.get('software_verdict') == 'PASS' and before == after and not r.get('formal_freeze_written') else 'FAIL'

            elif args.check == 'gui':
                if os.name != 'nt':
                    raise RuntimeError('Windows required')
                from glp.gui import gui_self_test
                r = gui_self_test()
                status = r.get('status', 'FAIL')

            elif args.check == 'integrity-tamper':
                svc.ensure_seed()
                payload = json.loads(svc.store.history_path.read_text(encoding='utf-8'))
                payload['draws'][-1]['back'][0] = 1 if int(payload['draws'][-1]['back'][0]) != 1 else 2
                svc.store.history_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                integrity = svc._integrity_check()
                # update must reject before any network call because baseline is corrupt
                import glp.sources as sources
                original_get = sources.requests.get
                network_calls = {'count': 0}
                def forbidden_get(*a, **kw):
                    network_calls['count'] += 1
                    raise RuntimeError('network should not be called for corrupt baseline')
                sources.requests.get = forbidden_get
                try:
                    try:
                        svc.update()
                        update_rejected = False
                    except Exception:
                        update_rejected = True
                finally:
                    sources.requests.get = original_get
                r = {
                    'integrity': integrity,
                    'update_rejected': update_rejected,
                    'network_calls': network_calls['count'],
                }
                status = 'PASS' if not integrity.get('ok') and update_rejected and network_calls['count'] == 0 else 'FAIL'

            elif args.check == 'offline-failclosed':
                svc.ensure_seed()
                before = _sha256_file(svc.store.history_path)
                import glp.sources as sources
                original_get = sources.requests.get
                def offline(*a, **kw):
                    raise sources.requests.ConnectionError('acceptance injected offline')
                sources.requests.get = offline
                try:
                    try:
                        svc.update()
                        rejected = False
                        err = None
                    except Exception as exc:
                        rejected = True
                        err = f'{type(exc).__name__}: {exc}'
                finally:
                    sources.requests.get = original_get
                after = _sha256_file(svc.store.history_path)
                r = {'rejected': rejected, 'error': err, 'history_unchanged': before == after}
                status = 'PASS' if rejected and before == after else 'FAIL'

            elif args.check == 'corrupt-repair':
                svc.ensure_seed()
                payload = json.loads(svc.store.history_path.read_text(encoding='utf-8'))
                payload['draws'][-1]['front'][0] = 1 if int(payload['draws'][-1]['front'][0]) != 1 else 2
                svc.store.history_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                before = svc._integrity_check()
                repair = svc.repair()
                after = svc._integrity_check()
                r = {'before': before, 'repair': repair, 'after': after}
                status = 'PASS' if not before.get('ok') and repair.get('status') == 'PASS' and after.get('ok') else 'FAIL'

            elif args.check.startswith('random-world-'):
                from glp.evidence import run_evidence_court
                seed = int(args.check.rsplit('-', 1)[1])
                svc.ensure_seed()
                draws, _ = svc.store.load_draws()
                random_draws = _random_world(draws, seed)
                court = run_evidence_court(random_draws)
                leakage = court.get('leakage', {})
                r = {
                    'seed': seed,
                    'edge_state': court.get('edge_state'),
                    'dan_state': court.get('dan_state'),
                    'software_verdict': court.get('software_verdict'),
                    'leakage': leakage,
                    'court_hash': court.get('court_hash'),
                }
                leak_count = int(leakage.get('violations', leakage.get('violation_count', 0)) or 0)
                status = 'PASS' if court.get('software_verdict') == 'PASS' and court.get('edge_state') == 'NO_EDGE' and court.get('dan_state') == 'NULL_DAN' and leak_count == 0 else 'FAIL'

            else:
                raise RuntimeError('unknown check')

            out.update(status=status, result=r)

    except Exception as exc:
        out.update(status='FAIL', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())

    _write_result(args.result_file, out)
    return 0 if out.get('status') == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
