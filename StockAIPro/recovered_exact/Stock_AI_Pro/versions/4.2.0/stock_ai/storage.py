from __future__ import annotations
import json, shutil
from pathlib import Path
from .config import ROOT
from .utils import write_json, sha256_file, now_iso


def _dated_prediction_dirs():
    p = ROOT / "predictions"
    if not p.exists():
        return []
    return sorted([
        d for d in p.iterdir()
        if d.is_dir() and d.name not in {"latest", "_forced_backups"} and (d / "manifest.json").exists()
    ], key=lambda x: x.name)


def _previous_chain_link(asof: str):
    prev = [d for d in _dated_prediction_dirs() if d.name < str(asof)]
    if not prev:
        return None, 1
    last = prev[-1]
    try:
        m = json.loads((last / "manifest.json").read_text(encoding="utf-8"))
        seq = int(m.get("chain_sequence", 0)) + 1
    except Exception:
        seq = len(prev) + 1
    return sha256_file(last / "manifest.json"), seq


def verify_prediction_chain(root: Path | None = None):
    base = (root or ROOT) / "predictions"
    if not base.exists():
        return True, "尚无预测链", 0
    dirs = sorted([
        d for d in base.iterdir()
        if d.is_dir() and d.name not in {"latest", "_forced_backups"} and (d / "manifest.json").exists()
    ], key=lambda x: x.name)
    prev_hash = None
    expected_seq = 1
    for d in dirs:
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"{d.name} manifest 无法读取: {e}", expected_seq - 1
        for name, expected in (m.get("files") or {}).items():
            p = d / name
            if not p.exists() or sha256_file(p) != expected:
                return False, f"{d.name}/{name} 文件哈希不一致", expected_seq - 1
        if int(m.get("chain_sequence", expected_seq)) != expected_seq:
            return False, f"{d.name} chain_sequence 不连续", expected_seq - 1
        linked = m.get("previous_manifest_sha256")
        if linked != prev_hash:
            return False, f"{d.name} 前向哈希链断裂", expected_seq - 1
        prev_hash = sha256_file(d / "manifest.json")
        expected_seq += 1
    return True, f"预测哈希链连续，共 {len(dirs)} 期", len(dirs)


def freeze_prediction(asof, scored, portfolios, summary, metrics, regime, data_quality,
                      force=False, valuation_status=None, cost_assumptions=None,
                      decision=None, rnd_shadow=None):
    target = ROOT / "predictions" / asof
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"{asof} 的预测已冻结，默认禁止覆盖。")
    if target.exists() and force:
        backup = ROOT / "predictions" / "_forced_backups" / f"{asof}_{now_iso().replace(':','-')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))
    target.mkdir(parents=True, exist_ok=True)
    scored.to_csv(target / "predictions.csv", index=False, encoding="utf-8-sig")
    for name, df in portfolios.items():
        df.to_csv(target / f"portfolio_{name}.csv", index=False, encoding="utf-8-sig")
    write_json(target / "summary.json", summary)
    write_json(target / "model_metrics.json", metrics)
    write_json(target / "market_regime.json", regime)
    write_json(target / "data_quality.json", data_quality)
    write_json(target / "valuation_status.json", valuation_status or {})
    write_json(target / "cost_assumptions.json", cost_assumptions or {})
    write_json(target / "decision.json", decision or {})
    if rnd_shadow is not None and not rnd_shadow.empty:
        rnd_shadow.to_csv(target / "rnd_shadow.csv", index=False, encoding="utf-8-sig")

    prev_hash, seq = _previous_chain_link(asof)
    manifest = {
        "schema_version": 2,
        "created_at": now_iso(),
        "asof": str(asof),
        "chain_sequence": seq,
        "previous_manifest_sha256": prev_hash,
        "files": {},
    }
    for p in sorted(target.glob("*")):
        if p.is_file() and p.name != "manifest.json":
            manifest["files"][p.name] = sha256_file(p)
    write_json(target / "manifest.json", manifest)
    head_hash = sha256_file(target / "manifest.json")
    write_json(ROOT / "state" / "prediction_chain.json", {
        "schema_version": 1,
        "head_date": str(asof),
        "head_manifest_sha256": head_hash,
        "sequence": seq,
        "updated_at": now_iso(),
    })

    latest = ROOT / "predictions" / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(target, latest)
    return target
