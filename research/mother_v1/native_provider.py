"""Bounded subprocess bridge to distinct SSQ/DLT native app feature models."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys

from .registry import NATIVE_FEATURES

ROOT = Path(__file__).resolve().parents[2]
PLAIN = tuple(name.removeprefix("native_") for name in NATIVE_FEATURES)


class NativeBlocked(ValueError):
    pass


@lru_cache(maxsize=8)
def _compute(game: str, history_bytes: bytes) -> dict:
    if game not in ("SSQ", "DLT") or not history_bytes or len(history_bytes) > 3_000_000:
        raise NativeBlocked("NATIVE_GAME_OR_HISTORY_INVALID")
    # Source hashes are read from the real checked-in native engine, and
    # subprocess process boundaries prevent global 'glp' import collisions.
    path = ROOT / ("SSQ/SSQ" if game == "SSQ" else "DLT/src")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + str(path)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "research.mother_v1.native_worker", game],
            input=history_bytes, capture_output=True, timeout=60, cwd=ROOT,
            env=env, check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeBlocked("NATIVE_EXEC_FAILED:" + type(exc).__name__) from exc
    if completed.returncode or len(completed.stdout) > 150_000:
        # Do not echo arbitrary stderr from external code.
        raise NativeBlocked("NATIVE_WORKER_EXIT_OR_OUTPUT_INVALID")
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError) as exc:
        raise NativeBlocked("NATIVE_WORKER_JSON_INVALID") from exc
    if (not isinstance(result, dict) or result.get("game") != game
            or set(result.get("front_rankings", {})) != set(PLAIN)
            or set(result.get("back_rankings", {})) != set(PLAIN)
            or result.get("formal_A") != 0 or result.get("decision") != "NO_EDGE"):
        raise NativeBlocked("NATIVE_WORKER_CONTRACT_INVALID")
    return result


def native_models(game: str, history: list[dict]) -> dict:
    serialized = json.dumps(history, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _compute(game, serialized)
