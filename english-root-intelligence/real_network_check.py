from __future__ import annotations
import json,tempfile
from pathlib import Path
from service import create_service
def main():
 with tempfile.TemporaryDirectory(prefix="eri-net-") as td:
  try: r=create_service(Path(td)).one_click_update(); ok=r.get("status")=="PASS" and bool(r.get("source",{}).get("sha256")); print(json.dumps(r,ensure_ascii=False)); return 0 if ok else 2
  except Exception as e: print(json.dumps({"status":"FAIL","error":str(e)},ensure_ascii=False)); return 3
if __name__=="__main__": raise SystemExit(main())
