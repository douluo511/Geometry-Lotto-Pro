from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path

LABELS = ['目标推演', '一键更新', '一键修复', '高级分析']

def validate_gui(report: dict, expected_hash: str, full_release: bool = False) -> bool:
    current = os.environ.get('GUOXUE_SOURCE_SHA') or os.environ.get('GITHUB_SHA')
    run = os.environ.get('GITHUB_RUN_ID')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT')
    buttons = report.get('buttons') or []
    if (not current or not run or not attempt or report.get('status') != 'PASS'
        or report.get('github_sha') != current or report.get('github_run_id') != run
        or report.get('github_run_attempt') != attempt
        or report.get('exe_sha256_before') != expected_hash
        or report.get('exe_sha256_after') != expected_hash or len(buttons) != 4):
        return False
    for index, (button, label) in enumerate(zip(buttons, LABELS), 1):
        backend = button.get('backend') or {}
        if (button.get('button_index') != index or button.get('label') != label
            or button.get('status') != 'PASS' or button.get('visual_changed') is not True
            or button.get('before_sha256') == button.get('after_sha256')
            or not all(isinstance(button.get(k), str) and len(button[k]) == 64 for k in ('before_sha256', 'after_sha256'))
            or backend.get('schema') != 'guoxue-gui-operation-v1'
            or backend.get('label') != label or backend.get('frozen') is not True
            or not isinstance(backend.get('pid'), int) or backend['pid'] <= 0
            or not isinstance(backend.get('nonce'), str) or len(backend['nonce']) != 32
            or backend.get('exe_sha256') != expected_hash or backend.get('github_sha') != current
            or backend.get('github_run_id') != run or backend.get('github_run_attempt') != attempt):
            return False
        detail = backend.get('detail') or {}
        if label == '一键更新':
            if full_release:
                if (report.get('gui_mode') != 'ConfiguredRelease' or backend.get('status') != 'PASS'
                    or detail.get('action') != 'UPDATER_HANDOFF' or not isinstance(detail.get('updater_pid'), int)):
                    return False
            elif not (backend.get('status') == 'BLOCKED' and detail.get('action') == 'RELEASE_CONFIG_UNAVAILABLE'
                      and str(detail.get('error', '')).startswith('RuntimeError: real software-update release config is unavailable;')):
                return False
        elif backend.get('status') != 'PASS':
            return False
        elif label == '目标推演':
            result = detail.get('result') or {}
            if detail.get('action') != 'GOAL_ANALYSIS' or not all(result.get(k) for k in ('methods', 'five_whys', 'reverse_validation')):
                return False
        elif label == '一键修复':
            result = detail.get('result') or {}
            if detail.get('action') != 'REPAIR_COMPLETE' or result.get('status') != 'PASS' or not result.get('checks'):
                return False
        elif label == '高级分析':
            stats = detail.get('stats') or {}
            if detail.get('action') != 'ADVANCED_ANALYSIS' or not all(isinstance(stats.get(k), int) and stats[k] >= 0 for k in ('classics', 'analyses', 'reviews', 'disputed')):
                return False
    return True
def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--exe",required=True); p.add_argument("--evidence",required=True); a=p.parse_args()
    exe=Path(a.exe); path=Path(a.evidence); report=json.loads(path.read_text(encoding="utf-8-sig")); buttons=report.get("buttons") or []
    ok=validate_gui(report, sha256(exe))
    if not ok: return 2
    report["schema"]="guoxue-physical-gui-bound-v1"; report["github_sha"]=(os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA")); report["exe_sha256"]=sha256(exe)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({"status":"PASS","github_sha":report["github_sha"],"exe_sha256":report["exe_sha256"],"button_count":4}))
    return 0
if __name__=="__main__": raise SystemExit(main())
