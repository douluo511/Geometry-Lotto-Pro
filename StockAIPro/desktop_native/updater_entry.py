from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import os
import sys


def _data_root() -> Path:
    explicit = os.environ.get("STOCK_AI_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "StockAIPro"
    return Path.cwd() / "userdata"


def _load_config(root: Path) -> dict:
    data = _data_root()
    data.mkdir(parents=True, exist_ok=True)
    user = data / "updater.json"
    if not user.exists():
        default = root / "updater_config.default.json"
        user.write_text(default.read_text(encoding="utf-8"), encoding="utf-8")
    obj = json.loads(user.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("updater config must be a JSON object")
    return obj


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--package-root", required=True)
    args = parser.parse_args()
    root = Path(args.package_root).resolve()
    sys.path.insert(0, str(root))

    from updater_runtime.updater import (  # noqa: E402
        activate_pending,
        check_and_stage,
        read_current,
        recover_interrupted_update,
    )

    try:
        recover_interrupted_update(root)
        cfg = _load_config(root)
        if not cfg.get("enabled"):
            print(json.dumps({
                "status": "BLOCKED",
                "reason": "production updater is disabled; real manifest/release context is not configured",
                "active_version": read_current(root).get("active_version"),
            }, ensure_ascii=False))
            return 3
        candidate = check_and_stage(root, cfg)
        if candidate is None:
            print(json.dumps({
                "status": "PASS",
                "result": "NO_UPDATE",
                "active_version": read_current(root).get("active_version"),
            }, ensure_ascii=False))
            return 0
        previous = activate_pending(root, candidate)
        print(json.dumps({
            "status": "PASS",
            "result": "STAGED_AND_ACTIVATED_PENDING_HEALTH",
            "previous_version": previous,
            "candidate_version": candidate,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": repr(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
