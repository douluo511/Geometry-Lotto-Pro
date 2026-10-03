from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime
from gate_common import run_identity
from physical_gui_evidence import validate_physical

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--service-actions", required=True)
    a = p.parse_args()
    exe = Path(a.exe)
    path = Path(a.evidence)
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    buttons = report.get("buttons") or []
    ok = (
        str(report.get("status", "")).upper() == "PASS"
        and len(buttons) == 4
        and all(str(x.get("status", "")).upper() == "PASS" and x.get("visual_changed") is True for x in buttons)
    )
    if not ok:
        return 2
    actions = [json.loads(line) for line in Path(a.service_actions).read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = ["今日学习", "一键更新", "一键修复", "高级分析"]
    latest = {row.get("label"): row for row in actions}
    current = os.environ.get("ENGLISH_ROOT_SOURCE_SHA") or os.environ.get("GITHUB_SHA")
    if any(label not in latest or latest[label].get("source_sha") != current
           or any(str(latest[label].get(key)) != str(value) for key, value in run_identity().items())
           for label in expected):
        return 2
    for button in buttons:
        for phase in ("before", "after"):
            screenshot = Path(button.get(phase + "_screenshot") or "")
            if not screenshot.is_file() or sha256(screenshot) != button.get(phase + "_sha256"):
                return 2
    for index, label in enumerate(expected):
        button = buttons[index]
        if int(button.get("button_index") or 0) != index + 1 or int(button.get("target_pid") or 0) <= 0:
            return 2
        completed = datetime.fromisoformat(latest[label]["recorded_at"])
        if not datetime.fromisoformat(button["clicked_at"]) <= completed <= datetime.fromisoformat(button["completed_at"]):
            return 2
        result = latest[label].get("result") or {}
        if label == "一键更新":
            accepted = ((result.get("status") == "PASS" and result.get("action") == "UPDATER_HANDOFF")
                        or (result.get("status") == "BLOCKED" and bool(result.get("error"))))
        else:
            accepted = result.get("status") == "PASS"
        if not accepted:
            return 2
    report["service_actions"] = [latest[label] for label in expected]
    report["schema"] = "english-root-physical-gui-bound-v1"
    report["github_sha"] = (os.environ.get("ENGLISH_ROOT_SOURCE_SHA") or os.environ.get("GITHUB_SHA"))
    report.update(run_identity())
    report["exe_sha256"] = sha256(exe)
    report["update_mode"] = "ConfiguredRelease" if latest["一键更新"]["result"].get("status") == "PASS" else "BlockedRelease"
    if not validate_physical(report, current):
        report["status"] = "FAIL"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "github_sha": report["github_sha"], "exe_sha256": report["exe_sha256"], "button_count": 4}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
