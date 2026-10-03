"""Inspect the locally built PyInstaller payload; never execute extracted code.

This is a narrow GUI/test-double isolation check, NOT a full no-shell verdict.
Archive API: PyInstaller 6.22.3 archive/readers.py and loader/pyimod01_archive.py.
"""
from __future__ import annotations

import hashlib
import marshal
import types
from pathlib import Path
from typing import Any


def inspect_gui_code(code: types.CodeType) -> dict[str, Any]:
    if not isinstance(code, types.CodeType):
        raise ValueError("glp.gui did not contain Python code")
    pending = [code]
    names: set[str] = set()
    identifiers: set[str] = set()
    strings: set[str] = set()
    while pending:
        current = pending.pop()
        names.add(current.co_name)
        identifiers.update(current.co_names)
        identifiers.update(current.co_varnames)
        identifiers.add(current.co_name)
        for value in current.co_consts:
            if isinstance(value, types.CodeType):
                pending.append(value)
            elif isinstance(value, str):
                strings.add(value)
    forbidden = sorted(name for name in identifiers if (
        "spy" in name.lower()
        or name in {"Mock", "MagicMock", "AsyncMock", "unittest.mock", "mock"}
    ))
    if forbidden:
        raise ValueError("GUI test doubles remain in payload: " + ", ".join(forbidden))
    if not {"NativeApp", "run_gui", "gui_self_test", "_wndproc", "_drain"}.issubset(names):
        raise ValueError("production GUI code is incomplete")
    if "NATIVE_SURFACE_ONLY" not in strings:
        raise ValueError("GUI surface self-check has no explicit scope boundary")
    if not {"LottoService", "UpdaterClient"}.issubset(identifiers):
        raise ValueError("production service bindings missing")
    return {
        "status": "PASS",
        "scope": "GUI_TEST_DOUBLE_ISOLATION_ONLY",
        "gui_code_sha256": hashlib.sha256(marshal.dumps(code)).hexdigest(),
        "code_object_count": len(names),
        "forbidden_identifiers": forbidden,
        "full_no_shell_status": "PENDING",
    }


def inspect_exe(exe: Path) -> dict[str, Any]:
    # Imported only by the acceptance tools, never by the production GUI.
    from PyInstaller.archive.readers import CArchiveReader

    before = hashlib.sha256(exe.read_bytes()).hexdigest()
    archive = CArchiveReader(str(exe))
    pyz_names = [name for name, row in archive.toc.items() if row[-1] == "z"]
    if len(pyz_names) != 1:
        raise ValueError("expected exactly one embedded Python archive")
    pyz = archive.open_embedded_archive(pyz_names[0])
    forbidden = sorted(name for name in set(archive.toc) | set(pyz.toc) if (
        name == "tests" or name.startswith(("tests.", "tests/", "tests\\", "test_",
                                               "glp.tests", "glp.test_"))
    ))
    if forbidden:
        raise ValueError("application test modules were bundled: " + ", ".join(forbidden))
    proof = inspect_gui_code(pyz.extract("glp.gui"))
    # Hash stored bytes, not a re-marshaled object whose string interning may
    # differ across interpreter processes when Final Gate independently reads it.
    proof.pop("gui_code_sha256")
    proof["gui_payload_sha256"] = hashlib.sha256(pyz.extract("glp.gui", raw=True)).hexdigest()
    after = hashlib.sha256(exe.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("EXE changed while inspecting its payload")
    return {
        **proof,
        "exe_sha256": after,
        "archive": pyz_names[0],
        "forbidden_test_modules": forbidden,
    }
