from __future__ import annotations
import json
from service import create_service

def main() -> int:
    report = create_service().network_smoke()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
