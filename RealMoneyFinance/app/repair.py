from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
from datetime import datetime

from .storage import Storage

DEFAULT_CONFIG = {
    "schema_version": 1,
    "default_symbol": "600000",
    "risk_boundary": {
        "allow_personalized_investment_advice": False,
        "allow_true_capital_identity_from_public_l1": False,
        "allow_capital_deployment": False,
    },
}


def repair_user_state(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    backup_dir = root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    config = root / "config.json"
    default = root / "config.default.json"
    if not default.exists():
        tmp_default = default.with_suffix(".json.tmp")
        tmp_default.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_default, default)

    repaired: list[str] = []
    if config.exists():
        try:
            obj = json.loads(config.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("config root must be object")
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(config, backup_dir / f"config_corrupt_{stamp}.json")
            if not default.exists():
                raise RuntimeError("default config unavailable; refusing destructive repair")
            shutil.copy2(default, config)
            repaired.append("config_restored_from_default")
    elif default.exists():
        shutil.copy2(default, config)
        repaired.append("config_seeded")
    else:
        raise RuntimeError("default config unavailable")

    storage = Storage(root)
    integrity = storage.integrity_check()
    if integrity != "ok":
        raise RuntimeError(f"database integrity_check failed: {integrity}")

    evidence = {
        "status": "PASS",
        "database_integrity": integrity,
        "repaired": repaired,
        "user_data_deleted": False,
    }
    path = root / "evidence" / "repair.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return evidence
