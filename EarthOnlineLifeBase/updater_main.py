from pathlib import Path
import json, sys
from app.updater import run

if __name__=="__main__":
    out=run(Path(__file__).resolve().parent)
    print(json.dumps(out,ensure_ascii=False))
    raise SystemExit(3 if out["status"]=="BLOCKED" else (0 if out["status"]=="PASS" else 2))
