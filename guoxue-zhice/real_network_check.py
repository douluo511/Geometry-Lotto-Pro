from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from service import create_service
ROOT=Path(__file__).resolve().parent
def main()->int:
    report={"schema":"guoxue-real-network-v1","status":"FAIL","github_sha":(os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),"network_gate":"FAIL"}
    try:
        with tempfile.TemporaryDirectory(prefix="guoxue-net-") as td:
            svc=create_service(Path(td))
            result=svc.one_click_update()
            evidence=result.get("evidence") or {}
            ms=evidence.get("manifest_source") or {}
            ks=evidence.get("knowledge_source") or {}
            ma=evidence.get("manifest_distribution_attempts") or []
            ka=evidence.get("knowledge_distribution_attempts") or []
            ok=(
                result.get("status")=="PASS"
                and evidence.get("status")=="PASS"
                and bool(ms.get("raw_b64")) and bool(ms.get("attempts"))
                and bool(ks.get("raw_b64")) and bool(ks.get("attempts"))
                and len(ma)>=1 and len(ka)>=1
                and bool(evidence.get("selected_manifest_source_id"))
                and bool(evidence.get("selected_knowledge_source_id"))
                and svc.store.evidence_path.exists()
            )
            report.update({
                "status":"PASS" if ok else "FAIL",
                "network_gate":"PASS" if ok else "FAIL",
                "version":result.get("version"),
                "classics":result.get("classics"),
                "sha256":result.get("sha256"),
                "selected_manifest_source_id":evidence.get("selected_manifest_source_id"),
                "selected_knowledge_source_id":evidence.get("selected_knowledge_source_id"),
                "manifest_distribution_attempts":ma,
                "knowledge_distribution_attempts":ka,
                "manifest_source":ms,
                "knowledge_source":ks,
            })
    except Exception as exc:
        report["error"]=f"{type(exc).__name__}: {exc}"
    (ROOT/"real_network_evidence.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":report["status"],"network_gate":report["network_gate"],"error":report.get("error")},ensure_ascii=False))
    return 0 if report["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
