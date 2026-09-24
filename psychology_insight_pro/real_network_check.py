from __future__ import annotations

import sys

from contracts import validate_knowledge
from net_client import NetClient

URL = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/psychology_insight_pro/knowledge.json"


def main() -> int:
    payload, source = NetClient(timeout=15.0, retries=2).get_json(URL, validate_knowledge)
    print(f"REAL_NETWORK_PASS version={payload['version']} status={source.http_status} sha256={source.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
