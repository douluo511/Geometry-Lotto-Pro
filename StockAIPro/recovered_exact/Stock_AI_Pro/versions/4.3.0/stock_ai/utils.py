
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
import hashlib, json, logging, os, sys, time

def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("stock_ai")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(log_dir / "stock_ai.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)

def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

@contextmanager
def process_lock(path: Path, stale_hours: float = 4):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            info = read_json(path, {})
            started = datetime.fromisoformat(info.get("started_at"))
            age = datetime.now().astimezone() - started
            if age < timedelta(hours=float(stale_hours)):
                raise RuntimeError(
                    f"已有流程正在运行（PID={info.get('pid')}，启动于 {info.get('started_at')}）。"
                )
        except RuntimeError:
            raise
        except Exception:
            pass
        try:
            path.unlink()
        except Exception:
            pass
    write_json(path, {"pid": os.getpid(), "started_at": now_iso()})
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
