"""Conservative static dead-code discovery; never automatically delete symbols.

Reports Python top-level functions in the V4.7 research package with no
observed read/call/import reference in ANY Python source in this repository.
Reflection/external consumers can escape static detection. This is candidate
discovery, not a deletion authorization.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "research" / "harness_v46"
SKIP = {".git", ".venv", "venv", "__pycache__", "build", "dist"}
NEVER_DELETE = {
    "main", "forecast", "validate_forecast", "validate_snapshot",
    "validate_study_snapshot", "model_source_sha256", "parameter_contract",
    "score", "pick_recency_pair", "ablation_rank",
}


def collect():
    reference = Counter()
    calls = Counter()
    import_refs = Counter()
    defs = []
    unparsed = []
    for path in ROOT.rglob("*.py"):
        if any(p in SKIP for p in path.relative_to(ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError, OSError) as exc:
            unparsed.append((str(path.relative_to(ROOT)), type(exc).__name__))
            continue
        short = str(path.relative_to(ROOT))
        if path.parent == TARGET:
            for n in tree.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append((short, n.name, n.lineno, len(n.body),
                                 [getattr(d, "id", getattr(d, "attr", ""))
                                  for d in n.decorator_list]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                reference[node.id] += 1
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                reference[node.attr] += 1
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_refs[alias.name] += 1
                    reference[alias.name] += 1
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    calls[fn.id] += 1
                elif isinstance(fn, ast.Attribute):
                    calls[fn.attr] += 1
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # A literal string matching the symbol may be dynamic lookup.
                if node.value.isidentifier():
                    reference[node.value] += 1
    print("PARSED_PYTHON", len(list(ROOT.rglob("*.py"))) - len(unparsed))
    print("UNPARSED", unparsed[:30])
    print("FUNCTIONS_IN_MODEL", len(defs))
    likely = []
    for path, name, line, stmts, decorators in defs:
        if name.startswith("__") or name in NEVER_DELETE:
            continue
        if reference[name] == 0:
            likely.append((path, line, name, stmts, decorators))
    print("CANDIDATE_NO_STATIC_REFERENCE", len(likely))
    for path, line, name, stmts, decorators in likely:
        print(f"CANDIDATE {path}:{line} {name} statements={stmts} decorators={decorators}")
    print("PRIVATE_WITH_1_OR_2_READS")
    for path, name, line, stmts, decorators in defs:
        if name.startswith("_") and name not in NEVER_DELETE and 0 < reference[name] <= 2:
            print(f"LOW_REFERENCES {path}:{line} {name} refs={reference[name]} calls={calls[name]} import={import_refs[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(collect())
