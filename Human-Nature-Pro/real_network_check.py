from __future__ import annotations
import json
import tempfile
from pathlib import Path
from service import create_service

def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hnp-net-") as td:
        try:
            result = create_service(Path(td)).update_all()
            print(json.dumps(result, ensure_ascii=False))
            ok = result.get("status") == "PASS" and bool(result.get("source", {}).get("payload_hash"))
            return 0 if ok else 2
        except Exception as exc:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
            return 3

if __name__ == "__main__":
    raise SystemExit(main())
