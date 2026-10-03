from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .domain import Draw
from .net_client import NetClient
from .services import Happy8Service
from .ui import Happy8Window, source_ui_contract, ui_contract

APP_VERSION = "0.2.0-staging"


def default_data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "GeometryLottoPro" / "Happy8"
    return Path.home() / ".geometry_lotto_pro" / "happy8"


def source_self_test() -> dict:
    checks = {}
    draw = Draw.from_values(
        "2026261",
        "2026-09-28",
        [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    )
    checks["domain"] = "PASS" if len(draw.numbers) == 20 else "FAIL"
    try:
        NetClient().get("http://example.invalid")
        checks["https_only"] = "FAIL"
    except ValueError:
        checks["https_only"] = "PASS"
    status = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
    return {
        "schema": "happy8-app-self-test-v1",
        "status": status,
        "version": APP_VERSION,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root")
    parser.add_argument("--result-file")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ui-contract", action="store_true")
    parser.add_argument("--ui-self-test", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--predict", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--advanced", action="store_true")
    args = parser.parse_args(argv)

    def emit(report: dict) -> None:
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.result_file:
            path = Path(args.result_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)

    if args.self_test:
        report = source_self_test()
        emit(report)
        return 0 if report["status"] == "PASS" else 2

    root = Path(args.data_root) if args.data_root else default_data_root()
    service = Happy8Service(root)

    if args.ui_contract:
        report = source_ui_contract()
        emit(report)
        return 0 if report["status"] == "PASS" else 2

    if args.ui_self_test:
        window = Happy8Window(service)
        window.withdraw()
        try:
            report = ui_contract(window)
        finally:
            window.destroy()
        emit(report)
        return 0 if report["status"] == "PASS" else 2

    operations = [
        (args.status, service.status),
        (args.update, service.update_data),
        (args.predict, service.predict_next),
        (args.repair, service.repair),
        (args.advanced, service.advanced_analysis),
    ]
    selected = [operation for enabled, operation in operations if enabled]
    if len(selected) > 1:
        parser.error("select at most one operation flag")
    if selected:
        try:
            result = selected[0]()
        except Exception as exc:
            result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        emit(result)
        return 0 if result.get("status") == "PASS" else 2

    window = Happy8Window(service)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
