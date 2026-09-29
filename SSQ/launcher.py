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
import re
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


def _preserve_live_evidence(store, result_file: str) -> dict:
    """Keep exact network bytes after the acceptance Store tempdir is removed."""
    from glp.util import atomic_write

    source_evidence = store.evidence_path.read_bytes()
    evidence = json.loads(source_evidence.decode("utf-8"))
    if evidence.get("raw_response_status") != "PASS":
        raise ValueError("raw response persistence did not PASS")
    records = evidence.get("raw_responses")
    if not isinstance(records, list) or not records:
        raise ValueError("raw response manifest is missing")
    lineage = evidence.get("baseline_lineage")
    baseline_records = lineage.get("raw_responses", []) if isinstance(lineage, dict) else []
    if not isinstance(baseline_records, list):
        raise ValueError("fallback baseline raw response manifest is malformed")
    result_path = Path(result_file).resolve()
    evidence_dir = result_path.parent
    for record in [*records, *baseline_records]:
        digest = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid raw response digest")
        raw = (store.raw_root / f"{digest}.bin").read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest or len(raw) != record.get("bytes"):
            raise ValueError("raw response bytes do not match manifest")
        preserved = evidence_dir / "raw_responses" / f"{digest}.bin"
        if preserved.exists():
            if _sha256_file(preserved) != digest:
                raise ValueError("existing acceptance raw artifact is corrupt")
        else:
            atomic_write(preserved, raw)
        if _sha256_file(preserved) != digest:
            raise ValueError("acceptance raw artifact failed read-back hash")
    manifest_path = evidence_dir / f"{result_path.stem}-source-evidence.json"
    atomic_write(manifest_path, source_evidence)
    canonical_path = evidence_dir / f"{result_path.stem}-canonical-history.json"
    atomic_write(canonical_path, store.history_path.read_bytes())
    return {
        "status": "PASS",
        "manifest": manifest_path.name,
        "manifest_sha256": _sha256_file(manifest_path),
        "canonical": canonical_path.name,
        "canonical_sha256": _sha256_file(canonical_path),
        "raw_response_count": len(records),
        "baseline_raw_response_count": len(baseline_records),
    }


def _preserve_failed_network_evidence(store, result_file: str) -> dict:
    """Export exact FAIL manifests/raw bytes before the temporary Store vanishes."""
    from glp.util import atomic_write

    failures = sorted(store.failure_root.glob("*/failure_evidence.json"))
    if not failures:
        return {"status": "UNAVAILABLE", "reason": "no failed response bundle was persisted"}
    destination_root = Path(result_file).resolve().parent / "failed"
    exported = []
    for manifest in failures:
        source_bytes = manifest.read_bytes()
        payload = json.loads(source_bytes.decode("utf-8"))
        if payload.get("status") != "FAIL" or payload.get("crosscheck_status") != "FAIL":
            raise ValueError("failed network bundle falsely claims PASS")
        records = payload.get("raw_responses")
        if not isinstance(records, list):
            raise ValueError("failed network raw response list is malformed")
        leaf = manifest.parent.name
        if not re.fullmatch(r"[0-9a-f]{24}", leaf):
            raise ValueError("failed network bundle directory is not an opaque ID")
        (destination_root / "raw_responses").mkdir(parents=True, exist_ok=True)
        for record in records:
            digest = record.get("sha256") if isinstance(record, dict) else None
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or record.get("artifact") != f"raw_responses/{digest}.bin"):
                raise ValueError("failed network response metadata is malformed")
            raw = (manifest.parent / "raw_responses" / f"{digest}.bin").read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest or len(raw) != record.get("bytes"):
                raise ValueError("failed network raw response is hash-mismatched")
            target = destination_root / "raw_responses" / f"{digest}.bin"
            if not target.exists():
                atomic_write(target, raw)
            if _sha256_file(target) != digest:
                raise ValueError("exported failed network response failed read-back")
        exported_manifest = destination_root / f"{leaf}.json"
        atomic_write(exported_manifest, source_bytes)
        if _sha256_file(exported_manifest) != hashlib.sha256(source_bytes).hexdigest():
            raise ValueError("exported failed network manifest failed read-back")
        exported.append({
            "manifest": str(exported_manifest.relative_to(Path(result_file).resolve().parent)).replace("\\", "/"),
            "manifest_sha256": _sha256_file(exported_manifest),
            "raw_response_count": len(records),
        })
    return {"status": "FAIL", "bundles": exported}


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
        'github_sha': os.environ.get('GITHUB_SHA'),
        'github_run_id': os.environ.get('GITHUB_RUN_ID'),
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
                try:
                    r = svc.update()
                except Exception:
                    out['failed_network_evidence'] = _preserve_failed_network_evidence(svc.store, args.result_file)
                    raise
                status = 'PASS' if r.get('crosscheck_status') == 'PASS' else 'FAIL'
                if status == 'PASS':
                    r['preserved_live_evidence'] = _preserve_live_evidence(svc.store, args.result_file)
                else:
                    out['failed_network_evidence'] = _preserve_failed_network_evidence(svc.store, args.result_file)

            elif args.check == 'predict':
                from glp.engine import _next_target
                r = svc.predict()
                pred = r.get('prediction') or {}
                gate = r.get('final_gate') or {}
                auto = r.get('auto_update')
                draws = svc._load_draws()
                expected_issue, expected_date = _next_target(draws)
                front = [int(x) for x in pred.get('front', [])]
                back = [int(x) for x in pred.get('back', [])]
                autonomous_contract = {
                    'current_official_canonical_pass': (
                        isinstance(auto, dict)
                        and auto.get('crosscheck_status') == 'PASS'
                        and auto.get('source') == 'official-source-quorum'
                    ),
                    'target_from_updated_canonical': pred.get('target_issue') == expected_issue and pred.get('target_date') == expected_date,
                    'front_shape_valid': len(front) == 6 and len(set(front)) == 6 and all(1 <= x <= 33 for x in front),
                    'back_shape_valid': len(back) == 1 and all(1 <= x <= 16 for x in back),
                    'lineage_bound': bool(pred.get('prediction_id') and pred.get('freeze_hash') and pred.get('score_hash') and pred.get('model_hash') and pred.get('selector_hash')),
                    'final_gate_pass': gate.get('status') == 'PASS',
                    'no_manual_input': True,
                }
                r['acceptance_autonomous_contract'] = autonomous_contract
                status = 'PASS' if all(autonomous_contract.values()) else 'FAIL'

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
                leak_count = int(court.get('leakage_violations', 0) or 0)
                r = {
                    'seed': seed,
                    'edge_state': court.get('edge_state'),
                    'dan_state': court.get('dan_state'),
                    'software_verdict': court.get('software_verdict'),
                    'leakage_violations': leak_count,
                    'court_hash': court.get('court_hash'),
                }
                status = 'PASS' if court.get('software_verdict') == 'PASS' and court.get('edge_state') == 'NO_EDGE' and court.get('dan_state') == 'NULL_DAN' and leak_count == 0 else 'FAIL'

            else:
                raise RuntimeError('unknown check')

            if (status != 'PASS' and 'failed_network_evidence' not in out
                    and svc.store.failure_root.is_dir()):
                out['failed_network_evidence'] = _preserve_failed_network_evidence(
                    svc.store, args.result_file)
            out.update(status=status, result=r)

    except Exception as exc:
        out.update(status='FAIL', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())

    _write_result(args.result_file, out)
    return 0 if out.get('status') == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
