from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import traceback


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
        from stock_ai.pipeline import main as pipeline_main
        pipeline_main()
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
    try:
        return run_worker(action, Path(package_root))
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL",
            "action": action,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
