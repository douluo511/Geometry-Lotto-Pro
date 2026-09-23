from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

REMOTE_KB = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/human-nature-pro-v1/Human-Nature-Pro/knowledge_base.json"


def app_data_dir() -> Path:
    import os
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "HumanNaturePro"
    root.mkdir(parents=True, exist_ok=True)
    return root


def local_kb_path() -> Path:
    return app_data_dir() / "knowledge_base.json"


def update_knowledge(timeout: int = 12) -> dict:
    req = urllib.request.Request(REMOTE_KB, headers={"User-Agent": "Human-Nature-Pro/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("rules"), list):
        raise ValueError("远程知识库格式不合法")
    target = local_kb_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(target)
    return {"ok": True, "knowledge_version": data.get("knowledge_version", "unknown"), "path": str(target)}


def repair_knowledge(bundled_path: Path) -> dict:
    target = local_kb_path()
    try:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("schema_version") == 1 and isinstance(data.get("rules"), list):
                return {"ok": True, "action": "checked", "path": str(target)}
    except Exception:
        pass
    shutil.copyfile(bundled_path, target)
    return {"ok": True, "action": "restored", "path": str(target)}
