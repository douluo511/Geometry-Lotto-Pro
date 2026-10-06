from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
PKG = ROOT / "SSQ" / "glp"
SPEC = ROOT / "ENGINEERING_SPEC.md"
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
REQUIRED = [
    SPEC,
    ROOT / "BUSINESS_SPEC.md",
    PKG / "domain.py",
    PKG / "net_client.py",
    PKG / "storage.py",
    PKG / "engine.py",
    PKG / "evidence.py",
    PKG / "service.py",
    PKG / "gui.py",
    PKG / "sources.py",
]

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
    path = repo_root / ".github" / "workflows" / "ssq-windows-build-acceptance.yml"
    failures: list[str] = []
    if not path.is_file():
        return False, [f"missing workflow: {path.relative_to(repo_root)}"]
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


def main() -> int:
    checks = {f"exists:{p.name}": p.exists() for p in REQUIRED}
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    gui = (PKG / "gui.py").read_text(encoding="utf-8")
    sources = (PKG / "sources.py").read_text(encoding="utf-8")
    service = (PKG / "service.py").read_text(encoding="utf-8")
    net = (PKG / "net_client.py").read_text(encoding="utf-8")

    gates = {
        "purpose_model": "PASS" if "## Requirement / Purpose Model" in spec else "FAIL",
        "five_why": "PASS" if "## 5 Why" in spec else "FAIL",
        "risk_boundary": "PASS" if "## Risk Boundary" in spec else "FAIL",
        "domain_model": "PASS" if "## Domain Model" in spec and "CanonicalDataset" in spec else "FAIL",
        "architecture": "PASS" if "## Architecture" in spec and "LottoService" in gui else "FAIL",
        "function_contract": "PASS" if "## Function / Interface Contract" in spec else "FAIL",
        "interface_contract": "PASS" if "predict / update / repair / audit" in spec else "FAIL",
        "data_source": "PASS" if "## Data Sources" in spec and "official" in sources.lower() else "FAIL",
        "netclient": "PASS" if (
            "NET.get(" in sources
            and "requests.get(" not in sources
            and "class NetClient" in net
            and "glp_attempts" in net
            and "_require_https" in net
            and "_timeout_pair" in net
            and "_retry_delay" in net
            and "allow_redirects=False" in net
        ) else "FAIL",
        "storage": "PASS" if "from glp.storage import" in service else "FAIL",
        "engine": "PASS" if "from glp.engine import" in service else "FAIL",
        "evidence": "PASS" if "from glp.evidence import" in service else "FAIL",
        "service": "PASS" if "class LottoService" in service else "FAIL",
        "ui": "PASS" if "LottoService" in gui else "FAIL",
    }
    checks["sources_use_netclient"] = gates["netclient"] == "PASS"
    checks["ui_uses_service"] = gates["ui"] == "PASS"
    checks["service_uses_engine"] = gates["engine"] == "PASS"
    checks["service_uses_storage"] = gates["storage"] == "PASS"
    checks["service_uses_evidence"] = gates["evidence"] == "PASS"

    actions_pinned, action_failures = workflow_actions_are_sha_pinned(REPO_ROOT)
    checks["workflow_actions_sha_pinned"] = actions_pinned
    checks["workflow_actions_sha_pin_failures"] = not action_failures

    requirements_frozen, requirement_failures = build_requirements_are_frozen(ROOT, REPO_ROOT)
    checks["build_dependency_closure_frozen"] = requirements_frozen
    checks["build_dependency_closure_failures"] = not requirement_failures

    status = "PASS" if all(checks.values()) and all(v == "PASS" for v in gates.values()) else "FAIL"
    report = {
        "schema": "ssq-architecture-gate-v2",
        "status": status,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "gates": gates,
        "checks": checks,
    }
    out = ROOT / "evidence" / "SSQ" / "ARCHITECTURE_GATE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
