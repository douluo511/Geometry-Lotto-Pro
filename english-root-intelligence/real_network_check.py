from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from service import create_service

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "real_network_evidence.json"

def main() -> int:
    report = {
        "schema": "english-root-real-network-v2",
        "status": "FAIL",
        "github_sha": os.environ.get("GITHUB_SHA"),
        "network_gate": "FAIL",
        "source_count": 0,
        "distinct_source_ids": [],
        "sources": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="eri-net-") as td:
            result = create_service(Path(td)).one_click_update()
            sources = result.get("sources") or []
            distinct = sorted(set(result.get("distinct_source_ids") or []))
            ok = (
                result.get("status") == "PASS"
                and result.get("network_gate") == "PASS"
                and int(result.get("source_count", 0)) >= 4
                and len(distinct) >= 4
                and len(sources) >= 4
                and all(int(s.get("status_code", 0)) == 200 for s in sources)
                and all(bool(s.get("raw_b64")) for s in sources)
                and all(bool(s.get("attempt_ledger")) for s in sources)
            )
            report.update({
                "status": "PASS" if ok else "FAIL",
                "network_gate": "PASS" if ok else "FAIL",
                "version": result.get("version"),
                "roots": result.get("roots"),
                "sha256": result.get("sha256"),
                "source_count": result.get("source_count", 0),
                "distinct_source_ids": distinct,
                "sources": sources,
            })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "network_gate": report["network_gate"],
        "source_count": report["source_count"],
        "distinct_source_ids": report["distinct_source_ids"],
        "error": report.get("error"),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
