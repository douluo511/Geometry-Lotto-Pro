
from __future__ import annotations
from datetime import date, datetime, timedelta
from pathlib import Path
import shutil
from .config import ROOT
from .utils import read_json, write_json, now_iso

def maybe_snapshot(cfg: dict, logger=None) -> dict:
    bc = cfg.get("backup", {})
    if not bc.get("enabled", True):
        return {"enabled":False}

    state_path = ROOT / "state" / "backup.json"
    state = read_json(state_path, {}) or {}
    last = state.get("last_snapshot_date")
    every = int(bc.get("snapshot_every_days",7))
    due = True
    if last:
        try:
            due = (date.today() - date.fromisoformat(last)).days >= every
        except Exception:
            due = True
    if not due:
        return {"enabled":True,"due":False}

    backup_root = ROOT / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    target = backup_root / stamp
    target.mkdir(parents=True, exist_ok=True)

    copied = []
    for rel in [
        "config.json",
        "state/last_run.json",
        "state/maintenance.json",
        "reports/backtest_summary.json",
        "reports/audit_report.json",
        "cache/bootstrap_status.json"
    ]:
        src = ROOT / rel
        if src.exists():
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)

    latest = ROOT / "predictions" / "latest"
    if latest.exists():
        dst = target / "predictions_latest"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(latest, dst)
        copied.append("predictions/latest")

    keep = int(bc.get("keep_days",90))
    cutoff = date.today() - timedelta(days=keep)
    removed = []
    for p in backup_root.iterdir():
        if not p.is_dir():
            continue
        try:
            d = date.fromisoformat(p.name)
        except Exception:
            continue
        if d < cutoff:
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)

    write_json(state_path, {
        "last_snapshot_date":stamp,
        "updated_at":now_iso(),
        "copied":copied
    })
    if logger:
        logger.info("状态快照完成: %s", target)
    return {
        "enabled":True,"due":True,"path":str(target),
        "copied":copied,"removed":removed
    }
