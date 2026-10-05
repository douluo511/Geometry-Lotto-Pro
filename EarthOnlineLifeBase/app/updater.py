from __future__ import annotations
from pathlib import Path
import json, os, sys, urllib.request
from .storage import data_root, atomic_json

def run(package_root:Path)->dict:
    cfg=package_root/"release_config.json"
    if not cfg.is_file():
        out={"status":"BLOCKED","reason":"independent production repository/release/signing context unavailable"}
        atomic_json(data_root()/"evidence"/"updater.json",out); return out
    obj=json.loads(cfg.read_text(encoding="utf-8"))
    manifest=str(obj.get("manifest_url") or "")
    if not manifest.startswith("https://"):
        out={"status":"FAIL","reason":"trusted HTTPS manifest URL required"}
        atomic_json(data_root()/"evidence"/"updater.json",out); return out
    out={"status":"NOT VERIFIED","reason":"production signed release verification not implemented in reauthored candidate"}
    atomic_json(data_root()/"evidence"/"updater.json",out); return out
