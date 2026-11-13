"""Read-only static reference audit for SSQ/DLT physical evidence modules.

This scanner never authorizes deletion by itself. Runtime reflection, external
callers, shell invocations and source-hash contracts require human review.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHYSICAL = (
    "research/supercompute/automation/dlt_physical_source.py",
    "research/supercompute/automation/ssq_physical_source.py",
    "research/supercompute/automation/physical_transport.py",
    "research/supercompute/automation/physical_ledger_db.py",
    "research/supercompute/automation/physical_tick.py",
)
EXCLUDE = {".git", "__pycache__", ".venv", "venv", "dist", "build"}


def main():
    seen = Counter()
    definitions = []
    unused_imports = []
    scanned = 0
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDE for part in path.relative_to(ROOT).parts):
            continue
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        if relative in PHYSICAL:
            definitions.extend((relative, node.name, node.lineno)
                               for node in parsed.body
                               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
        module_reads = Counter()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                module_reads[node.id] += 1
        if relative in PHYSICAL:
            for node in ast.walk(parsed):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                        continue
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        binding = alias.asname or alias.name.split(".")[0]
                        if module_reads[binding] == 0:
                            unused_imports.append((relative, node.lineno, alias.name))
        for node in ast.walk(parsed):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                seen[node.id] += 1
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                seen[node.attr] += 1
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.isidentifier():
                    seen[node.value] += 1
    print("PYTHON_SCANNED", scanned)
    print("PHYSICAL_FUNCTIONS", len(definitions))
    candidates = []
    for path, name, lineno in definitions:
        if name == "main" or name.startswith("__"):
            continue
        if seen[name] == 0:
            candidates.append((path, name, lineno))
    print("NO_STATIC_REFERENCE_COUNT", len(candidates))
    for path, name, line in candidates:
        print(f"NO_STATIC_REFERENCE {path}:{line} {name}")
    print("UNUSED_IMPORT_COUNT", len(unused_imports))
    for path, line, name in unused_imports:
        print(f"UNUSED_IMPORT {path}:{line} {name}")
    print("NOTE: private dynamic and external references are not proved absent")
    return 1 if candidates or unused_imports else 0


if __name__ == "__main__":
    raise SystemExit(main())
