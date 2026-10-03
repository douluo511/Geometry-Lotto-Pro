from __future__ import annotations

from pathlib import Path
import ast
import json
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop_native"
PACKAGE = ROOT / "staging" / "Stock_AI_Pro"


def fail(msg: str) -> None:
    raise AssertionError(msg)


def check_ast_contracts() -> dict:
    app = (DESKTOP / "app.py").read_text(encoding="utf-8")
    service = (DESKTOP / "service.py").read_text(encoding="utf-8")
    repair = (DESKTOP / "repair_entry.py").read_text(encoding="utf-8")
    updater = (DESKTOP / "updater_entry.py").read_text(encoding="utf-8")

    for text in ("核心功能", "一键更新", "一键修复", "高级分析"):
        if text not in app:
            fail("missing desktop entry: " + text)
    if "streamlit" in app.lower():
        fail("native desktop UI must not depend on Streamlit")
    if "StockAIService" not in app:
        fail("UI must call Service boundary")
    if "shell=False" not in service:
        fail("service subprocesses must explicitly use shell=False")
    if "StockAIUpdater.exe" not in service:
        fail("frozen UI must invoke independent updater executable")
    if "shutil.rmtree" in repair or "rmtree(" in repair:
        fail("repair entry must not wipe user directories")
    if '"status": "BLOCKED"' not in updater:
        fail("updater must expose missing production release context as BLOCKED")

    for path in DESKTOP.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    return {
        "four_entries": True,
        "ui_service_boundary": True,
        "native_ui_no_streamlit": True,
        "bounded_subprocess_contract": True,
        "independent_updater_contract": True,
        "non_destructive_repair_contract": True,
    }


def check_service_source_mode() -> dict:
    env = os.environ.copy()
    env["STOCK_AI_PACKAGE_ROOT"] = str(PACKAGE.resolve())
    code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(DESKTOP.resolve())!r});"
        "from service import StockAIService;"
        "s=StockAIService(timeout_seconds=30);"
        "print(json.dumps({'active_version':s.active_version,'root':str(s.package_root)}))"
    )
    p = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        shell=False,
    )
    if p.returncode != 0:
        fail("service source-mode construction failed: " + p.stderr)
    obj = json.loads(p.stdout.strip().splitlines()[-1])
    if not obj.get("active_version"):
        fail("active version missing")
    return obj


def check_repair_isolated_data() -> dict:
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        env["STOCK_AI_DATA_ROOT"] = td
        p = subprocess.run(
            [
                sys.executable,
                str(DESKTOP / "repair_entry.py"),
                "--package-root",
                str(PACKAGE),
            ],
            cwd=DESKTOP,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=300,
            shell=False,
        )
        if p.returncode != 0:
            fail("isolated repair failed: " + p.stderr[-5000:])
        evidence = Path(td) / "evidence" / "last_repair.json"
        if not evidence.exists():
            fail("repair evidence missing")
        obj = json.loads(evidence.read_text(encoding="utf-8"))
        if obj.get("status") != "PASS":
            fail("repair evidence did not PASS")
        if not (Path(td) / "config.json").exists():
            fail("repair did not seed/repair user config")
        return {
            "repair_status": obj["status"],
            "doctor_returncode": obj["doctor_returncode"],
            "data_root": td,
        }


def main() -> int:
    evidence = {
        "ast_contracts": check_ast_contracts(),
        "service_source_mode": check_service_source_mode(),
        "isolated_repair": check_repair_isolated_data(),
        "desktop_final_boundary": {
            "windows_native_build": "NOT VERIFIED",
            "exact_exe": "NOT VERIFIED",
            "physical_gui": "NOT VERIFIED",
            "same_hash": "NOT VERIFIED",
            "real_updater_release": "BLOCKED",
            "repository_independence": "BLOCKED",
            "final_gate": "FAIL",
        },
    }
    out = ROOT / "desktop_native_contract_evidence.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
