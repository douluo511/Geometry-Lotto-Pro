from __future__ import annotations
import json, os, shutil
from datetime import datetime
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]


def _default_data_root() -> Path:
    explicit = os.environ.get("STOCK_AI_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "StockAIPro"
    return CODE_ROOT


ROOT = _default_data_root()


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"配置必须是 JSON object: {path}")
    return obj


def _write_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _backup_config(path: Path, reason: str) -> Path:
    backup_dir = ROOT / "backups" / "config_migrations"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = backup_dir / f"config_{stamp}_{reason}.json"
    shutil.copy2(path, target)
    return target


def ensure_user_config() -> dict:
    """Seed/repair/migrate editable user config without overwriting user choices.

    - corrupt JSON is backed up before fallback;
    - older schemas are deep-merged with new defaults and backed up first;
    - newer schemas are refused so an old binary cannot silently downgrade config.
    """
    default = _read_json(CODE_ROOT / "config.default.json")
    default_schema = int(default.get("schema_version", 1))
    user_path = ROOT / "config.json"

    if ROOT == CODE_ROOT:
        # Development/source mode: keep repository config editable but validate it.
        if not user_path.exists():
            _write_json_atomic(user_path, default)
            return default
        user = _read_json(user_path)
        if int(user.get("schema_version", 1)) > default_schema:
            raise RuntimeError("配置 Schema 高于当前程序版本，拒绝由旧程序降级读取。")
        return _deep_merge(default, user)

    if not user_path.exists():
        seed = CODE_ROOT / "config.json"
        if seed.exists():
            try:
                user = _read_json(seed)
            except Exception:
                user = default
        else:
            user = default
        merged = _deep_merge(default, user)
        merged["schema_version"] = default_schema
        _write_json_atomic(user_path, merged)
        return merged

    try:
        user = _read_json(user_path)
    except Exception:
        _backup_config(user_path, "corrupt")
        _write_json_atomic(user_path, default)
        return default

    user_schema = int(user.get("schema_version", 1))
    if user_schema > default_schema:
        raise RuntimeError(
            f"用户配置 Schema={user_schema} 高于程序支持 Schema={default_schema}；"
            "拒绝启动以避免配置被旧版本破坏。"
        )
    if user_schema < default_schema:
        _backup_config(user_path, f"schema_{user_schema}_to_{default_schema}")
        migrated = _deep_merge(default, user)
        migrated["schema_version"] = default_schema
        _write_json_atomic(user_path, migrated)
        return migrated
    return _deep_merge(default, user)


def load_config() -> dict:
    default = _read_json(CODE_ROOT / "config.default.json")
    # In separated-data mode ensure migration before reading.
    if ROOT != CODE_ROOT:
        return ensure_user_config()
    candidates = [ROOT / "config.json", CODE_ROOT / "config.json"]
    user = {}
    for p in candidates:
        if p.exists():
            user = _read_json(p)
            break
    if int(user.get("schema_version", 1)) > int(default.get("schema_version", 1)):
        raise RuntimeError("配置 Schema 高于当前程序版本，拒绝降级读取。")
    return _deep_merge(default, user)


def ensure_dirs() -> None:
    for name in [
        "data/history", "data/valuation", "predictions", "reports", "logs",
        "models", "cache", "state", "backups"
    ]:
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    ensure_user_config()
