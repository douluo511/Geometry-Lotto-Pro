"""Validate actual frozen-worker outputs without conflating execution and qualification."""
from pathlib import Path
import argparse
import hashlib
import json
import os
from desktop_gui_physical_click_gate import validate_advanced


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"action": "advanced_analysis", "source_commit": os.environ.get("STOCK_SOURCE_SHA"),
              "execution_status": "PASS", "technical_validation": "PASS",
              "status": "NOT VERIFIED",
              "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest()}
    try:
        audit = json.loads((args.data_root / "reports/audit_report.json").read_text(encoding="utf-8"))
        backtest = json.loads((args.data_root / "reports/backtest_summary.json").read_text(encoding="utf-8"))
        report["business_validation"] = validate_advanced(audit, backtest)
        report["status"] = report["business_validation"]["status"]
    except Exception as exc:
        report["status"] = "FAIL"
        report["technical_validation"] = "FAIL"
        report["validation_error_type"] = type(exc).__name__
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    # Business qualification is evidence, not the Windows execution status.
    # A valid FAIL/NOT VERIFIED business result must survive unchanged so the
    # Final Gate can fail closed, while the desktop chain continues to prove
    # Physical GUI / Same Hash. Only malformed/missing advanced evidence is a
    # technical validation failure for this step.
    return 1 if report["technical_validation"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
