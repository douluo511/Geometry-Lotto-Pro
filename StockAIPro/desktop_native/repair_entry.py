from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace


def _load_current(root: Path) -> dict:
    p = root / "current.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or not obj.get("active_version"):
        raise ValueError("current.json missing active_version")
    return obj


def _data_root() -> Path:
    explicit = os.environ.get("STOCK_AI_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "StockAIPro"
    return Path.cwd() / "userdata"


def _cleanup_stale_temp_files(data_root: Path) -> list[str]:
    removed: list[str] = []
    for p in data_root.rglob("*.tmp"):
        try:
            if p.is_file() and (time.time() - p.stat().st_mtime) > 3600:
                p.unlink()
                removed.append(str(p))
        except OSError:
            continue
    return removed


def repair(package_root: Path) -> dict:
    root = package_root.resolve()
    cur = _load_current(root)
    version = str(cur["active_version"])
    version_root = root / "versions" / version
    required = [
        version_root / "VERSION",
        version_root / "config.default.json",
        version_root / "stock_ai" / "config.py",
        version_root / "doctor.py",
        root / "launcher.py",
        root / "updater_runtime" / "updater.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("application files missing; repair refuses destructive recreation: " + "; ".join(missing))

    data_root = _data_root()
    os.environ["STOCK_AI_DATA_ROOT"] = str(data_root)
    sys.path.insert(0, str(version_root))

    from stock_ai.config import ensure_dirs, ensure_user_config  # noqa: E402

    ensure_dirs()
    cfg = ensure_user_config()
    removed = _cleanup_stale_temp_files(data_root)

    doctor_path = version_root / "doctor.py"
    if getattr(sys, "frozen", False):
        stdout = io.StringIO()
        stderr = io.StringIO()
        spec = importlib.util.spec_from_file_location("stock_ai_doctor_runtime", doctor_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load doctor module")
        module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            spec.loader.exec_module(module)
            rc = int(module.main())
        doctor = SimpleNamespace(returncode=rc, stdout=stdout.getvalue(), stderr=stderr.getvalue())
    else:
        doctor = subprocess.run(
            [sys.executable, str(doctor_path)],
            cwd=str(version_root),
            env=os.environ.copy(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
            shell=False,
        )
    evidence = {
        "status": "PASS" if doctor.returncode == 0 else "FAIL",
        "active_version": version,
        "package_root": str(root),
        "data_root": str(data_root),
        "config_schema_version": cfg.get("schema_version"),
        "stale_temp_removed": removed,
        "doctor_returncode": int(doctor.returncode),
        "doctor_stdout": doctor.stdout[-20000:],
        "doctor_stderr": doctor.stderr[-20000:],
    }
    out = data_root / "evidence" / "last_repair.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, out)
    if doctor.returncode != 0:
        raise RuntimeError("repair completed protective actions but doctor self-check still failed")
    return evidence


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--package-root", required=True)
    args = parser.parse_args()
    try:
        evidence = repair(Path(args.package_root))
        print(json.dumps(evidence, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": repr(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
