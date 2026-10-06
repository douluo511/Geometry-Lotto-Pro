from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse

from talkcraft.service.training_service import TrainingService

ROOT=Path(__file__).resolve().parent
def main()->int:
    svc=TrainingService(ROOT)
    result=svc.update_all_sources()
    domains={urlparse(x["final_url"] or x["requested_url"]).netloc.lower() for x in result.get("sources",[]) if x.get("ok")}
    checks={
      "overall":result.get("ok") is True,
      "three_sources":len(result.get("sources",[]))>=3,
      "independent_domains":len(domains)>=3,
      "all_https":all((x.get("final_url") or x.get("requested_url") or "").startswith("https://") for x in result.get("sources",[])),
      "all_have_hash":all(bool(x.get("sha256")) for x in result.get("sources",[])),
      "attempt_ledgers":all(bool(x.get("attempts")) for x in result.get("sources",[])),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"talkcraft-real-network-v1","status":status,"checks":checks,"domains":sorted(domains),"sources":result.get("sources",[])}
    (ROOT/"real_network.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 4
if __name__=="__main__": raise SystemExit(main())
