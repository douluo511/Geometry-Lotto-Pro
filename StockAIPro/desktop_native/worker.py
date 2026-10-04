from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import traceback


def _ensure_standard_streams() -> dict[str, str]:
    """Guarantee writable text streams for PyInstaller --windowed workers.

    A windowed frozen process can start with sys.stdout/sys.stderr set to None.
    Some provider libraries (including progress reporters) write to those streams;
    leaving them None turns a usable network fallback into a frozen-only crash.
    Source-mode consoles are preserved. Frozen missing streams are redirected to
    an evidence-friendly append-only log under the isolated data root.
    """
    status: dict[str, str] = {}
    missing = [name for name in ("stdout", "stderr") if getattr(sys, name) is None]
    log_path: Path | None = None
    if missing:
        data_root = Path(os.environ.get("STOCK_AI_DATA_ROOT") or Path.cwd() / "userdata")
        log_dir = data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "worker_stdio.log"
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            stream = log_path.open("a", encoding="utf-8", buffering=1)
            setattr(sys, name, stream)
            status[name] = str(log_path)
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
            status[name] = "existing"
    if log_path is not None:
        os.environ["STOCK_AI_WORKER_STDIO_LOG"] = str(log_path)
    return status


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
        from stock_ai.audit import run_audit
        from stock_ai.backtest import run_backtest
        audit = run_audit()
        _, summary = run_backtest()
        print(json.dumps({
            "status": "PASS",
            "active_version": version,
            "audit_trust": audit.get("trust") if isinstance(audit, dict) else None,
            "backtest": summary,
        }, ensure_ascii=True, default=str))
        return 0

    if action == "repair":
        from repair_entry import repair
        evidence = repair(package_root)
        print(json.dumps(evidence, ensure_ascii=False))
        return 0

    raise ValueError(f"unsupported worker action: {action}")


def main(argv: list[str] | None = None) -> int:
    _ensure_standard_streams()
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
    try:
        return run_worker(action, Path(package_root))
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "action": action,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "package_root": str(package_root),
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": str(sys.executable),
            "worker_stdio_log": os.environ.get("STOCK_AI_WORKER_STDIO_LOG"),
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
