import json
from app.netclient import official_reference_gate
if __name__=="__main__":
    out=official_reference_gate()
    print(json.dumps(out))
    raise SystemExit(0 if out["status"]=="PASS" else 2)
