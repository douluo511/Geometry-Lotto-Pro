from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from app.build_info import PRODUCT, SOURCE_SHA, VERSION
from app.service import LegalPhilosophyService
from app.storage import Storage
from app.ui import LegalPhilosophyUI


def exe_hash() -> str | None:
    path = Path(sys.executable)
    if getattr(sys, "frozen", False) and path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--health-report")
    ap.add_argument("--health-nonce")
    ap.add_argument("--ui-self-test", action="store_true")
    args = ap.parse_args()

    root = Path(args.root or os.environ.get("LEGAL_PHILOSOPHY_ROOT", "userdata")).resolve()
    service = LegalPhilosophyService(root)
    if args.self_test:
        result = service.self_test()
        result.update({
            "product": PRODUCT,
            "version": VERSION,
            "source_sha": SOURCE_SHA,
            "exe_sha256": exe_hash(),
            "nonce": args.health_nonce,
        })
        if args.health_report:
            Storage.atomic_json(Path(args.health_report), result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") == "PASS" else 2

    if args.ui_self_test:
        ui = LegalPhilosophyUI(service)
        result = {
            "status": "PASS",
            "title": ui.root.title(),
            "buttons": ["核心研习", "一键更新", "一键修复", "高级分析"],
        }
        ui.root.update_idletasks()
        ui.root.destroy()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    LegalPhilosophyUI(service).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
