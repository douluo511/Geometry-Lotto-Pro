from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from head_intelligence.gate_evidence import current_binding, untracked

SHARED = "douluo511/Geometry-Lotto-Pro"
REQUIRED = {"app.py", "service.py", "engine.py", "net_client.py", "storage.py", "domain.py", "updater.py", "software_update.py", "repair.py"}


def evaluate_inventory(repository, files):
    own = {path.split("/", 1)[1] for path in files if path.startswith("head_intelligence/")}
    unrelated = [path for path in files if not (path.startswith("head_intelligence/") or path in {"README.md", "LICENSE", "LICENSE.md", ".gitignore", ".github/workflows/head-intelligence-windows.yml", ".github/scripts/head_physical_gui_click_smoke.ps1", ".github/scripts/tk_button_points.py"})]
    if repository == SHARED:
        return "BLOCKED", "dedicated Head Intelligence repository is unavailable; a seed inside the shared repository is not independent"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repository)) or unrelated or not REQUIRED.issubset(own):
        return "FAIL", "dedicated repository inventory invalid"
    return "PASS", "dedicated repository contains only the Head Intelligence project and private workflow dependencies"


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--out", required=True); args = parser.parse_args()
    binding = current_binding()
    output = Path(args.out)
    if not untracked(output):raise RuntimeError("tracked repository evidence is forbidden")
    repository = os.environ.get("GITHUB_REPOSITORY")
    raw = subprocess.check_output(["git", "ls-files", "-z"])
    files = raw.decode("utf-8").rstrip("\x00").split("\x00")
    status, detail = evaluate_inventory(repository, files)
    inventory = [{"path": name, "sha256": hashlib.sha256(Path(name).read_bytes()).hexdigest()} for name in files if Path(name).is_file()]
    report = {"schema":"head-intelligence-repository-independence-v1", "status":status, **binding,
              "repository":repository, "files":inventory, "detail":detail}
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key:value for key,value in report.items() if key!="files"}, ensure_ascii=True))
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":raise SystemExit(main())
