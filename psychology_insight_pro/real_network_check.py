from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from app import KNOWLEDGE_URLS
from service import create_service


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "real_network_evidence.json"


def main() -> int:
    report = {
        "schema": "psychology-real-network-v2",
        "status": "FAIL",
        "github_sha": os.environ.get("GITHUB_SHA"),
        "network_gate": "FAIL",
        "source_count": 0,
        "sources": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="psychology_real_network_") as td:
            service = create_service(
                local_path=Path(td) / "knowledge.json",
                bundled_path=ROOT / "knowledge.json",
                knowledge_url=KNOWLEDGE_URLS,
            )
            result = service.update_knowledge()
            sources = [asdict(s) for s in result.sources]
            distinct = {s.get("source_id") for s in sources if s.get("source_id")}
            ok = (
                result.network_gate == "PASS"
                and len(sources) >= 2
                and len(distinct) >= 2
                and all(int(s.get("http_status", 0)) == 200 for s in sources)
                and all(bool(s.get("raw_b64")) for s in sources)
                and all(bool(s.get("attempts")) for s in sources)
            )
            report.update({
                "status": "PASS" if ok else "FAIL",
                "network_gate": result.network_gate,
                "update_status": result.status,
                "version": result.version,
                "source_count": len(sources),
                "distinct_source_ids": sorted(distinct),
                "sources": sources,
            })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "network_gate": report["network_gate"],
        "source_count": report["source_count"],
        "distinct_source_ids": report.get("distinct_source_ids", []),
        "error": report.get("error"),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
