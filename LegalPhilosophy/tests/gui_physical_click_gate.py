from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from pywinauto import Application


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_actions(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def wait_action(path: Path, action: str, timeout: float=120.0) -> dict:
    end=time.time()+timeout
    while time.time()<end:
        items=read_actions(path)
        for item in reversed(items):
            if item.get("action")==action:
                return item
        time.sleep(.5)
    raise TimeoutError(f"GUI audit timeout for {action}")


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--exe",required=True)
    ap.add_argument("--root",required=True)
    ap.add_argument("--evidence",required=True)
    args=ap.parse_args()
    exe=Path(args.exe).resolve()
    root=Path(args.root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    before=digest(exe)
    app=Application(backend="uia").start(f'"{exe}" --root "{root}"')
    win=app.window(title_re=".*法哲学.*")
    win.wait("visible ready",timeout=30)
    audit=root/"evidence"/"gui_actions.jsonl"
    results={}
    try:
        for action in ("核心研习","一键更新","一键修复","高级分析"):
            win.child_window(title=action,control_type="Button").click_input()
            item=wait_action(audit,action,180 if action=="核心研习" else 90)
            results[action]=item
        image=win.capture_as_image()
        image.save(str(Path(args.evidence).with_suffix(".png")))
    finally:
        try:
            win.close()
        except Exception:
            pass
    after=digest(exe)
    assert before==after
    assert results["核心研习"]["status"]=="PASS"
    assert results["一键更新"]["status"]=="BLOCKED"
    assert results["一键修复"]["status"]=="PASS"
    assert results["高级分析"]["status"]=="PASS"
    update_payload=results["一键更新"].get("payload",{})
    assert update_payload.get("independent_process_returncode")==3
    assert "Updater" in str(update_payload.get("independent_updater_path",""))
    report={
        "status":"PASS",
        "physical_gui":"PASS",
        "same_hash":"PASS",
        "exe_sha256_before":before,
        "exe_sha256_after":after,
        "actions":results,
        "positive_production_update":"BLOCKED",
    }
    Path(args.evidence).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
