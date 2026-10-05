from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.software_update import UPDATE_CONFIG_FILENAME, launch_independent_updater


class FakeProcess:
    pid = 424242


def main() -> int:
    checks: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="happy8-software-update-gate-") as td:
        root = Path(td)
        main_exe = root / "Geometry_Lotto_Pro_Happy8.exe"
        updater_exe = root / "Geometry_Lotto_Pro_Happy8_Updater.exe"
        main_exe.write_bytes(b"main-fixture")
        updater_exe.write_bytes(b"updater-fixture")

        try:
            launch_independent_updater(
                data_root=root / "data",
                current_version="0.2.0",
                main_exe=main_exe,
                updater_exe=updater_exe,
                parent_pid=123,
            )
            checks["missing_release_config_fail_closed"] = {"status": "FAIL"}
        except RuntimeError:
            checks["missing_release_config_fail_closed"] = {"status": "PASS"}

        (root / UPDATE_CONFIG_FILENAME).write_text(
            json.dumps({
                "schema": "happy8-update-config-v1",
                "manifest_url": "http://updates.example/manifest.json",
                "trusted_hosts": ["updates.example"],
            }),
            encoding="utf-8",
        )
        try:
            launch_independent_updater(
                data_root=root / "data",
                current_version="0.2.0",
                main_exe=main_exe,
                updater_exe=updater_exe,
                parent_pid=123,
            )
            checks["http_release_config_fail_closed"] = {"status": "FAIL"}
        except RuntimeError:
            checks["http_release_config_fail_closed"] = {"status": "PASS"}

        (root / UPDATE_CONFIG_FILENAME).write_text(
            json.dumps({
                "schema": "happy8-update-config-v1",
                "manifest_url": "https://updates.example/manifest.json",
                "trusted_hosts": ["updates.example"],
            }),
            encoding="utf-8",
        )
        captured: dict[str, object] = {}

        def fake_popen(args, **kwargs):
            captured["args"] = list(args)
            captured["kwargs"] = dict(kwargs)
            return FakeProcess()

        with patch("happy8.software_update.subprocess.Popen", side_effect=fake_popen):
            report = launch_independent_updater(
                data_root=root / "data",
                current_version="0.2.0",
                main_exe=main_exe,
                updater_exe=updater_exe,
                parent_pid=123,
            )

        args = captured.get("args") or []
        checks["independent_handoff"] = {
            "status": "PASS"
            if (
                report.get("status") == "PASS"
                and report.get("action") == "UPDATER_HANDOFF"
                and report.get("requires_parent_exit") is True
                and str(updater_exe.resolve()) == args[0]
                and "--manifest-url" in args
                and "https://updates.example/manifest.json" in args
                and "--trusted-host" in args
                and "updates.example" in args
                and "--target-exe" in args
                and str(main_exe.resolve()) in args
                and "--parent-pid" in args
                and "123" in args
            )
            else "FAIL"
        }

    status = "PASS" if checks and all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-software-update-handoff-gate-v1", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
