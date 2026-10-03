from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

def record_gui_result(label: str, status: str, detail: dict) -> None:
    target = os.environ.get('GUOXUE_GUI_AUDIT_FILE')
    if not target:
        return
    if status not in {'PASS', 'FAIL', 'BLOCKED', 'NOT VERIFIED'}:
        raise ValueError('invalid GUI backend state')
    exe = Path(sys.executable).resolve()
    report = {'schema': 'guoxue-gui-operation-v1', 'label': label, 'status': status,
        'detail': detail, 'pid': os.getpid(), 'frozen': bool(getattr(sys, 'frozen', False)),
        'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
        'nonce': os.environ.get('GUOXUE_GUI_AUDIT_NONCE'),
        'github_sha': os.environ.get('GUOXUE_SOURCE_SHA'),
        'github_run_id': os.environ.get('GITHUB_RUN_ID'),
        'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'recorded_at': datetime.now(timezone.utc).isoformat()}
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(tmp, path)
