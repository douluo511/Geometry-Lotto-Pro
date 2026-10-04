from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import json
import hashlib
import os
import sys
import traceback


@contextmanager
def windowed_worker_streams(action: str):
    """AkShare/tqdm need writable streams even in a windowed frozen EXE."""
    original_stdout, original_stderr = sys.stdout, sys.stderr
    log = None
    try:
        if original_stdout is None or original_stderr is None:
            data_root = Path(os.environ.get("STOCK_AI_DATA_ROOT") or Path.cwd() / "userdata")
            log_dir = data_root / "evidence"
            log_dir.mkdir(parents=True, exist_ok=True)
            log = (log_dir / f"worker_{action}.log").open("a", encoding="utf-8", buffering=1)
            if original_stdout is None:
                sys.stdout = log
            if original_stderr is None:
                sys.stderr = log
        yield
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        if log is not None:
            log.close()


def _version_root(package_root: Path) -> tuple[str, Path]:
    cur = json.loads((package_root / "current.json").read_text(encoding="utf-8"))
    version = str(cur["active_version"])
    root = package_root / "versions" / version
    if not root.exists():
        raise FileNotFoundError(f"active version missing: {root}")
    return version, root


def run_worker(action: str, package_root: Path) -> int:
    package_root = package_root.resolve()
    os.environ["STOCK_AI_PACKAGE_ROOT"] = str(package_root)
    version, version_root = _version_root(package_root)
    sys.path.insert(0, str(version_root))

    if action == "core":
        from stock_ai.pipeline import run as pipeline_run
        pipeline_run(force=False, run_maintenance=True)
        return 0

    if action == "advanced":
        import math
        import pandas as pd
        from stock_ai.audit import run_audit
        from stock_ai.backtest import run_backtest
        from stock_ai.config import ROOT, load_config
        from stock_ai.data_source import qualify_research_pool_coverage
        from stock_ai.valuation import refresh_valuation_histories, valuation_history_coverage

        cfg = load_config()
        master_path = ROOT / "cache" / "universe_master.csv"
        predictions_path = ROOT / "predictions" / "latest" / "predictions.csv"
        if not master_path.is_file() or not predictions_path.is_file():
            raise RuntimeError("advanced qualification requires a completed current core run")

        master = pd.read_csv(master_path, dtype={"code": str})
        research_coverage = qualify_research_pool_coverage(master, cfg)

        predictions = pd.read_csv(predictions_path, dtype={"code": str})
        if "code" not in predictions or predictions.empty:
            raise RuntimeError("advanced qualification has no current prediction universe")
        valuation_codes = list(dict.fromkeys(predictions["code"].dropna().astype(str).tolist()))[:120]
        valuation_target = max(
            0.40, float((cfg.get("valuation", {}) or {}).get("backtest_min_coverage", 0.40))
        )
        valuation_status = {
            "coverage": valuation_history_coverage(valuation_codes),
            "target": valuation_target,
        }
        batch = max(1, int((cfg.get("valuation", {}) or {}).get("history_refresh_batch", 20)))
        max_passes = math.ceil(len(valuation_codes) / batch) + 2
        for _ in range(max_passes):
            if float(valuation_status.get("coverage", 0) or 0) >= valuation_target:
                break
            before = float(valuation_status.get("coverage", 0) or 0)
            valuation_status = refresh_valuation_histories(valuation_codes, cfg)
            if float(valuation_status.get("coverage", 0) or 0) <= before and not valuation_status.get("due"):
                break

        preparation = {
            "status": "PASS" if (
                float(research_coverage.get("coverage", 0) or 0) >= 0.90
                and float(research_coverage.get("delisted_coverage", 0) or 0) >= 0.90
                and float(valuation_status.get("coverage", 0) or 0) >= valuation_target
            ) else "NOT VERIFIED",
            "research_coverage": research_coverage,
            "valuation_coverage": valuation_status,
        }
        evidence_path = ROOT / "evidence" / "advanced_preparation.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(preparation, ensure_ascii=True, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"advanced_preparation": preparation}, ensure_ascii=True, default=str))

        _, summary = run_backtest()
        audit = run_audit()
        print(json.dumps({
            "execution_status": "PASS",
            "business_qualification": "NOT VERIFIED",
            "active_version": version,
            "audit_trust": audit.get("trust") if isinstance(audit, dict) else None,
            "backtest": summary,
            "advanced_preparation": preparation,
        }, ensure_ascii=True, default=str))
        return 0

    if action == "repair":
        from repair_entry import repair
        evidence = repair(package_root)
        print(json.dumps(evidence, ensure_ascii=False))
        return 0

    raise ValueError(f"unsupported worker action: {action}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] != "--worker":
        print("usage: --worker <core|advanced|repair> [--package-root PATH]", file=sys.stderr)
        return 2
    action = args[1]
    package_root = os.environ.get("STOCK_AI_PACKAGE_ROOT")
    if "--package-root" in args:
        idx = args.index("--package-root")
        if idx + 1 >= len(args):
            return 2
        package_root = args[idx + 1]
    if not package_root:
        print("STOCK_AI_PACKAGE_ROOT is required", file=sys.stderr)
        return 2
    with windowed_worker_streams(action):
        return _execute_worker(action, package_root)


def _execute_worker(action: str, package_root: str) -> int:
    try:
        rc = run_worker(action, Path(package_root))
        receipt = {
            "status": "PASS" if rc == 0 else "FAIL",
            "action": action,
            "returncode": rc,
            "source_commit": os.environ.get("STOCK_SOURCE_SHA"),
            "invocation_id": os.environ.get("STOCK_GUI_INVOCATION_ID"),
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": str(sys.executable),
        }
        data_root = Path(os.environ.get("STOCK_AI_DATA_ROOT") or Path.cwd() / "userdata")
        evidence_dir = data_root / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        if receipt["frozen"]:
            receipt["exe_sha256"] = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        target = evidence_dir / f"worker_{action}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, ensure_ascii=True, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return rc
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "action": action,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "package_root": str(package_root),
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": str(sys.executable),
            "source_commit": os.environ.get("STOCK_SOURCE_SHA"),
            "invocation_id": os.environ.get("STOCK_GUI_INVOCATION_ID"),
        }
        try:
            data_root = Path(os.environ.get("STOCK_AI_DATA_ROOT") or Path.cwd() / "userdata")
            evidence_dir = data_root / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            target = evidence_dir / f"worker_{action}.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(failure, ensure_ascii=True, indent=2), encoding="utf-8")
            os.replace(tmp, target)
        except Exception as evidence_exc:
            failure["evidence_write_error"] = repr(evidence_exc)
        print(json.dumps(failure, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
