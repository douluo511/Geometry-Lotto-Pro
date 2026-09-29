from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


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
    a = p.parse_args()

    exe = Path(a.exe)
    evidence_path = Path(a.evidence)
    report = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    if str(report.get("status", "")).upper() != "PASS":
        raise SystemExit(2)
    buttons = report.get("buttons") or []
    if len(buttons) != 4 or not all(
        str(x.get("status", "")).upper() == "PASS" and x.get("visual_changed") is True
        for x in buttons
    ):
        raise SystemExit(2)

    report["github_sha"] = os.environ.get("GITHUB_SHA")
    report["exe_sha256"] = sha256(exe)
    report["schema"] = "physical-gui-click-smoke-bound-v2"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "github_sha": report["github_sha"],
        "exe_sha256": report["exe_sha256"],
        "button_count": len(buttons),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
