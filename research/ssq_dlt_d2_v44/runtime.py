"""One bounded local status check. No prediction, model fitting or network calls."""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import uuid
from pathlib import Path

from .ledger import Ledger, digest, utc_now


def check(db_path, output_path):
    ledger = Ledger(db_path)
    report = ledger.replay()
    report.update(checked_at=utc_now(), run_id=uuid.uuid4().hex,
                  mode="STATUS_CHECK_ONLY", prediction_calls=0,
                  original_G00_G07={f"G{i:02}":"BLOCKED" for i in range(8)},
                  original_gate_admission="Original gate definitions/evidence not independently admitted",
                  next_issue="BLOCKED_UNVERIFIED_TARGET_AND_SALE_DEADLINE",
                  formal_eight_producers="BLOCKED",
                  blocked_reasons=["01/04 cryptographic authorization absent",
                                   "External pre-deadline TSA not admitted",
                                   "Original eight producer identities not independently admitted",
                                   "Independent prospective statistical admission absent"])
    # Exclusive per-run directories preserve every JSON/CSV/HTML generation.
    folder = Path(output_path).resolve() / report["run_id"]
    folder.mkdir(parents=True, exist_ok=False)
    with (folder / "status.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (folder / "scores.csv").open("x", encoding="utf-8", newline="") as stream:
        fields = ["game", "issue", "slot", "version", "dan", "hits", "full", "p0"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report["scores"])
    content = ("<!doctype html><html lang='zh-Hant'><meta charset='utf-8'>"
               "<title>SSQ + DLT V4.4 research status</title><h1>SSQ + DLT V4.4</h1>"
               "<p>R2 BLOCKED · formal A=0 · NO_EDGE · FINAL FAIL</p>"
               "<p>研究狀態檢查：不產生或重寫預測。</p><pre>" +
               html.escape(json.dumps(report, ensure_ascii=False, indent=2)) + "</pre></html>")
    (folder / "status.html").write_text(content, encoding="utf-8")
    ledger.heartbeat(report["run_id"], dict(checked_at=report["checked_at"], report_sha256=digest(report),
                                             mode=report["mode"], R2="BLOCKED", formal_A=0, decision="NO_EDGE"))
    return report, folder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.db.is_absolute() or not args.output.is_absolute():
        parser.error("--db and --output must be absolute paths")
    try:
        report, _ = check(args.db, args.output)
    except Exception as exc:
        print(json.dumps(dict(status="FAIL", error=type(exc).__name__, reason=str(exc),
                              R2="BLOCKED", formal_A=0, decision="NO_EDGE")), file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ("run_id", "status", "R2", "formal_A", "decision", "prediction_calls")}))
    # 0 means the bounded check ran; the report, never this exit code, is admission.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
