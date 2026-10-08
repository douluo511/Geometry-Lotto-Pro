from __future__ import annotations
import json, re, shutil
from pathlib import Path
from .config import ROOT
from .utils import write_json, sha256_file, now_iso


REQUIRED_PREDICTION_PAYLOADS = frozenset({
    "predictions.csv", "summary.json", "model_metrics.json", "data_quality.json",
    "valuation_status.json", "cost_assumptions.json", "decision.json",
    "portfolio_balanced.csv", "portfolio_offense.csv", "portfolio_defense.csv",
})


def verify_prediction_payloads(pred_dir: Path, manifest):
    """Require the complete frozen payload before counting an integrity gate."""
    if not isinstance(manifest, dict):
        return False, "manifest 必须是对象"
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return False, "manifest files 必须是非空对象"
    missing = REQUIRED_PREDICTION_PAYLOADS - files.keys()
    if missing:
        return False, "manifest 缺少冻结文件: " + ", ".join(sorted(missing))
    try:
        folder = Path(pred_dir).resolve()
        manifest_path = (folder / "manifest.json").resolve()
        for name, expected in files.items():
            if not isinstance(name, str) or not name:
                return False, "manifest 文件路径非法"
            relative = Path(name)
            if relative.is_absolute() or relative.drive or relative.root:
                return False, f"{name} 文件路径越界"
            payload = (folder / relative).resolve()
            try:
                payload.relative_to(folder)
            except ValueError:
                return False, f"{name} 文件路径越界"
            if payload == manifest_path:
                return False, "manifest 不能将自身作为冻结payload"
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                return False, f"{name} SHA256 非法"
            if not payload.is_file():
                return False, f"{name} 冻结文件缺失"
            if sha256_file(payload) != expected.lower():
                return False, f"{name} 哈希不一致"
    except (OSError, ValueError, RuntimeError) as exc:
        return False, f"冻结文件无法验证: {type(exc).__name__}: {exc}"
    return True, "冻结文件哈希一致"


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
        if d.is_dir() and d.name not in {"latest", "_forced_backups"}
    ], key=lambda x: x.name)
    prev_hash = None
    expected_seq = 1
    for d in dirs:
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return False, f"{d.name} manifest 无法读取: {e}", expected_seq - 1
        payload_ok, payload_msg = verify_prediction_payloads(d, m)
        if not payload_ok:
            return False, f"{d.name}: {payload_msg}", expected_seq - 1
        sequence = m.get("chain_sequence")
        if type(sequence) is not int or sequence != expected_seq:
            return False, f"{d.name} chain_sequence 不连续", expected_seq - 1
        if "previous_manifest_sha256" not in m:
            return False, f"{d.name} previous_manifest_sha256 缺失", expected_seq - 1
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
