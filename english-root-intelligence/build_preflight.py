from __future__ import annotations

import json
import os
from pathlib import Path

from gate_common import run_identity


def main():
    report = {"schema": "english-root-build-preflight-v1", "github_sha": os.environ.get("ENGLISH_ROOT_SOURCE_SHA") or os.environ.get("GITHUB_SHA"),
              **run_identity(), "window_created": False}
    try:
        import tkinter
        interpreter = tkinter.Tcl()
        library = Path(interpreter.eval("info library"))
        if not (library / "init.tcl").is_file():
            raise RuntimeError("Tcl initialization did not bind to usable scripts")
        report.update(status="PASS", tcl_version=interpreter.eval("info patchlevel"))
    except Exception as exc:
        report.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
    Path("build_preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
