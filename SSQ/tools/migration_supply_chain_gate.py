from __future__ import annotations

import re
from pathlib import Path

ACTION_SHA_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}(?:\s+#.*)?$"
)

EXPECTED_BUILD_REQUIREMENTS = {
    "pyinstaller": "6.22.3",
    "pyinstaller-hooks-contrib": "2026.8",
    "altgraph": "0.17.5",
    "packaging": "26.3",
    "pefile": "2024.8.26",
    "pywin32-ctypes": "0.2.3",
    "requests": "2.34.2",
    "certifi": "2026.7.22",
    "charset-normalizer": "3.5.2",
    "idna": "3.20",
    "urllib3": "2.8.0",
    "setuptools": "65.5.0",
}


def build_requirements_are_frozen(root: Path, repo_root: Path) -> tuple[bool, list[str]]:
    failures: list[str] = []
    path = root / "requirements-build.txt"
    if not path.is_file():
        return False, ["requirements-build.txt missing"]
    actual: dict[str, str] = {}
    exact = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$")
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        match = exact.fullmatch(value)
        if match is None:
            failures.append(f"requirements-build.txt:{number}: not exact pinned: {value}")
            continue
        name = match.group(1).lower().replace("_", "-")
        if name in actual:
            failures.append(f"requirements-build.txt:{number}: duplicate package: {name}")
        actual[name] = match.group(2)
    if actual != EXPECTED_BUILD_REQUIREMENTS:
        failures.append("requirements-build.txt dependency closure differs from frozen inventory")

    workflow = repo_root / ".github" / "workflows" / "ssq-windows-build-acceptance.yml"
    text = workflow.read_text(encoding="utf-8") if workflow.is_file() else ""
    install_contract = (
        "--no-deps" in text
        and "--only-binary=:all:" in text
        and "-r requirements-build.txt" in text
    )
    if not install_contract:
        failures.append("Windows workflow does not enforce no-deps binary-only frozen install")
    return not failures, failures


def workflow_actions_are_sha_pinned(repo_root: Path) -> tuple[bool, list[str]]:
    required = repo_root / ".github" / "workflows" / "ssq-windows-build-acceptance.yml"
    optional_export = repo_root / ".github" / "workflows" / "ssq-independent-repo-export.yml"
    workflow_paths = [required]
    if optional_export.is_file():
        workflow_paths.append(optional_export)
    failures: list[str] = []
    if not required.is_file():
        failures.append(f"missing workflow: {required.relative_to(repo_root)}")
    for path in workflow_paths:
        if not path.is_file():
            continue
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw.strip()
            if stripped.startswith("- "):
                stripped = stripped[2:].lstrip()
            if not stripped.startswith("uses: "):
                continue
            value = stripped.removeprefix("uses: ").strip()
            if value.startswith("actions/") and ACTION_SHA_RE.fullmatch(value) is None:
                failures.append(f"{path.relative_to(repo_root)}:{number}: {value}")
    return not failures, failures
