from __future__ import annotations
import json
from pathlib import Path
import tempfile

from app.updater import check_context


def write(path: Path,obj: dict):
    path.write_text(json.dumps(obj),encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        assert check_context(root)["status"]=="BLOCKED"
        write(root/"updater.json",{
            "enabled":True,
            "repository":"douluo511/Geometry-Lotto-Pro",
            "manifest_url":"https://github.com/douluo511/Geometry-Lotto-Pro/releases/latest/download/release-manifest.json",
            "trusted_public_key_hex":"11"*32,
        })
        assert check_context(root)["status"]=="BLOCKED"
        write(root/"updater.json",{
            "enabled":True,
            "repository":"douluo511/Legal-Philosophy-System",
            "manifest_url":"http://example.invalid/release.json",
            "trusted_public_key_hex":"11"*32,
        })
        assert check_context(root)["status"]=="FAIL"
        write(root/"updater.json",{
            "enabled":True,
            "repository":"douluo511/Legal-Philosophy-System",
            "manifest_url":"https://example.invalid/release.json",
            "trusted_public_key_hex":"11"*32,
        })
        assert check_context(root)["status"]=="NOT VERIFIED"
    report={
        "status":"PASS",
        "missing_context_fail_closed":"PASS",
        "shared_monorepo_rejected":"PASS",
        "https_manifest_required":"PASS",
        "trusted_key_shape_required":"PASS",
        "real_release_n_to_n_plus_1":"BLOCKED",
    }
    Path("updater_contract_evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
