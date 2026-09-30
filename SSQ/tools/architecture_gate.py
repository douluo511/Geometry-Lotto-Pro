from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "SSQ" / "glp"
SPEC = ROOT / "ENGINEERING_SPEC.md"
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
    PKG / "updater_client.py",
    ROOT / "updater.py",
]


def main() -> int:
    checks = {f"exists:{p.name}": p.exists() for p in REQUIRED}
    spec = SPEC.read_text(encoding="utf-8") if SPEC.exists() else ""
    gui = (PKG / "gui.py").read_text(encoding="utf-8")
    sources = (PKG / "sources.py").read_text(encoding="utf-8")
    service = (PKG / "service.py").read_text(encoding="utf-8")
    net = (PKG / "net_client.py").read_text(encoding="utf-8")
    updater = (ROOT / "updater.py").read_text(encoding="utf-8")
    updater_client = (PKG / "updater_client.py").read_text(encoding="utf-8")

    gates = {
        "purpose_model": "PASS" if "## Requirement / Purpose Model" in spec else "FAIL",
        "five_why": "PASS" if "## 5 Why" in spec else "FAIL",
        "risk_boundary": "PASS" if "## Risk Boundary" in spec else "FAIL",
        "domain_model": "PASS" if "## Domain Model" in spec and "CanonicalDataset" in spec else "FAIL",
        "architecture": "PASS" if (
            "## Architecture" in spec
            and "LottoService" in gui
            and "UpdaterClient" in gui
            and "## Independent Updater / Repair Process" in spec
        ) else "FAIL",
        "function_contract": "PASS" if "## Function / Interface Contract" in spec else "FAIL",
        "interface_contract": "PASS" if all(token in spec for token in (
            "LottoService.predict",
            "UpdaterClient.update",
            "UpdaterClient.repair",
            "LottoService.audit",
            "software-update",
        )) else "FAIL",
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
    checks["independent_updater_client"] = (
        "class UpdaterClient" in updater_client
        and "subprocess.run(" in updater_client
        and "GLP_UPDATER_PARENT_PID" in updater_client
        and "updater_exe_sha256" in updater_client
    )
    checks["updater_exact_artifact_transaction"] = (
        "SOFTWARE_MANIFEST_SCHEMA" in updater
        and "TRUSTED_RELEASE_REPOSITORY" in updater
        and "_trusted_release_request" in updater
        and "_trusted_redirect_target" in updater
        and "_apply_verified_artifact" in updater
        and "os.replace(target, rollback)" in updater
        and "rolled_back" in updater
        and "_exact_main_self_test" in updater
        and "software-update" in updater
    )
    checks["gui_update_repair_route_to_updater"] = (
        "UpdaterClient" in gui
        and "self.updater.update" in gui
        and "self.updater.repair" in gui
    )
    checks["software_update_handoff_contract"] = (
        "launch_software_update" in updater_client
        and "HANDOFF_READY" in updater_client
        and "--wait-pid" in updater_client
        and "read_software_update_result" in updater_client
        and "DETACHED_PROCESS" in updater_client
    )

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
