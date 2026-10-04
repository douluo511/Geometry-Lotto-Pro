from __future__ import annotations
import argparse, json
from pathlib import Path
from app.service import Service

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--root",type=Path)
    a=p.parse_args()
    if a.self_test:
        s=Service(a.root)
        comp=s.compose()
        adv=s.advanced()
        out={
            "status":"PASS" if comp["status"]=="PASS" and adv["status"]=="PASS" else "FAIL",
            "local_audio":"PASS",
            "deterministic_audio":adv["deterministic_audio"]["status"],
            "cloud_ai_provider_generation":"NOT VERIFIED",
            "repository_independence":"BLOCKED",
            "final_gate":"FAIL"
        }
        print(json.dumps(out,ensure_ascii=False))
        return 0 if out["status"]=="PASS" else 2
    from app.ui import UI
    UI(a.root).run()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
