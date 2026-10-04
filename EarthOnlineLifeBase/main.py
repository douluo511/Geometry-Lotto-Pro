from __future__ import annotations
import argparse, json
from app.service import Service

def main():
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test:
        s=Service(); advanced=s.advanced()
        out={"status":"PASS" if advanced.get("business_content_import")=="PASS" else "FAIL",
             "repair":s.repair()["status"],"advanced":advanced["status"],
             "final_gate":"FAIL","repository_independence":"BLOCKED",
             "business_content_import":advanced.get("business_content_import")}
        print(json.dumps(out,ensure_ascii=False))
        return 0 if out["status"]=="PASS" else 2
    from app.ui import UI
    UI().run(); return 0
if __name__=="__main__": raise SystemExit(main())
