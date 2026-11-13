"""One isolated native application engine in its OWN Python interpreter.

Both the historical SSQ and DLT applications publish a top-level package
named 'glp' with incompatible module APIs. Never import both in one process.
This adapter reads JSON from stdin and writes model ranks to stdout; no GUI,
network, storage, or app service is called.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
FEATURES = (
    "simple_frequency", "recency", "gap", "transition", "pair_graph",
    "geometry_state", "geometry_transition", "research_ensemble",
)


def run(game: str, rows: list[dict]) -> dict:
    if game not in ("SSQ", "DLT"):
        raise ValueError("NATIVE_GAME_INVALID")
    relative = "SSQ/SSQ" if game == "SSQ" else "DLT/src"
    app_root = ROOT / relative
    if not (app_root / "glp" / "engine.py").is_file():
        raise ValueError("NATIVE_ENGINE_MISSING")
    sys.path.insert(0, str(app_root))
    from glp.domain import Draw
    from glp import engine
    draws = [Draw.from_dict(row) for row in rows]
    front = engine.individual_model_rankings(draws, "front")
    back = engine.individual_model_rankings(draws, "back")
    if set(front) != set(back) or set(front) != set(FEATURES):
        raise ValueError("NATIVE_EXPECTED_FEATURE_SET_CONFLICT")
    fmax, bmax = (33, 16) if game == "SSQ" else (35, 12)
    for name in FEATURES:
        for nums, high in ((front[name], fmax), (back[name], bmax)):
            if len(nums) != high or len(set(nums)) != high or set(nums) != set(range(1, high+1)):
                raise ValueError("NATIVE_RANKING_INVALID")
    return {
        "game": game, "provider": relative + "/glp/engine.py",
        "source_sha256": sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        "identity": engine.model_identity(),
        "front_rankings": front, "back_rankings": back,
        "research_only": True, "formal_A": 0, "decision": "NO_EDGE",
    }


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("SSQ", "DLT"):
        raise SystemExit("usage: python -m research.mother_v1.native_worker SSQ|DLT")
    raw = sys.stdin.buffer.read(3_000_001)
    if not raw or len(raw) > 3_000_000:
        raise ValueError("NATIVE_INPUT_EMPTY_OR_TOO_LARGE")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("NATIVE_HISTORY_INVALID")
    output = run(sys.argv[1], rows)
    sys.stdout.write(json.dumps(output, ensure_ascii=False, sort_keys=True, allow_nan=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
