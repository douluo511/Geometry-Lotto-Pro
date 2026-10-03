from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient
from happy8.services import Happy8Service
from happy8.software_update import software_update_environment_status
from happy8.updater import Updater, _atomic_json


class FakeResponse:
    def __init__(self, status_code=200, content=b"", *, url="https://updates.example/latest.json", content_type="application/json", headers=None):
        self.status_code = int(status_code)
        self.content = bytes(content)
        self.url = url
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)


class QueueSession:
    def __init__(self, events):
        self.events = list(events)

    def get(self, *args, **kwargs):
        if not self.events:
            raise AssertionError("fake session exhausted")
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def make_client(events, attempts=1):
    return NetClient(
        connect_timeout=0.1,
        read_timeout=0.1,
        max_attempts=attempts,
        backoff_base=0,
        session=QueueSession(events),
        sleeper=lambda _: None,
    )


def updater_for(events, attempts=1):
    return Updater(
        manifest_url="https://updates.example/latest.json",
        trusted_hosts={"updates.example"},
        net=make_client(events, attempts=attempts),
    )


def valid_manifest_bytes(artifact=b"MZ-candidate"):
    return json.dumps({
        "schema": "happy8-update-manifest-v1",
        "version": "0.2.1",
        "artifact_url": "https://updates.example/Happy8.exe",
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "artifact_bytes": len(artifact),
    }).encode("utf-8")


def must_raise(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


def exception_injection(exc) -> bool:
    client = make_client([exc, type(exc)(str(exc))], attempts=2)
    try:
        client.get("https://official.example/data")
    except type(exc) as caught:
        ledger = list(getattr(caught, "happy8_attempts", ()))
        return len(ledger) == 2 and ledger[-1].get("outcome") == "FINAL_EXCEPTION"
    return False


def main() -> int:
    checks = {}

    checks["offline_fail_closed"] = {
        "status": "PASS" if exception_injection(requests.ConnectionError("offline")) else "FAIL"
    }
    checks["dns_failure_fail_closed"] = {
        "status": "PASS" if exception_injection(requests.ConnectionError("dns resolution failed")) else "FAIL"
    }
    checks["timeout_fail_closed"] = {
        "status": "PASS" if exception_injection(requests.Timeout("read timeout")) else "FAIL"
    }

    for code in (429, 500, 502, 503):
        response = FakeResponse(code, b"{}", headers={"Retry-After": "0"})
        updater = updater_for([response], attempts=1)
        checks[f"http_{code}_fail_closed"] = {
            "status": "PASS" if must_raise(updater.fetch_manifest) else "FAIL"
        }

    malformed_cases = {
        "non_json": FakeResponse(200, b"<html>not json</html>", content_type="text/plain"),
        "empty_response": FakeResponse(200, b"", content_type="application/json"),
        "schema_change": FakeResponse(200, json.dumps({"schema": "happy8-update-manifest-v999"}).encode()),
        "missing_fields": FakeResponse(200, json.dumps({"schema": "happy8-update-manifest-v1", "version": "0.2.1"}).encode()),
        "bad_content_type": FakeResponse(200, valid_manifest_bytes(), content_type="text/html"),
    }
    for name, response in malformed_cases.items():
        updater = updater_for([response], attempts=1)
        checks[f"{name}_fail_closed"] = {
            "status": "PASS" if must_raise(updater.fetch_manifest) else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-fault-data-") as td:
        root = Path(td)
        root.mkdir(parents=True, exist_ok=True)
        corrupt_store = root / "store"
        corrupt_store.mkdir(parents=True, exist_ok=True)
        (corrupt_store / "CURRENT.json").write_text("{corrupt", encoding="utf-8")
        service = Happy8Service(
            root,
            repair_environment_probe=lambda: {
                "status": "PASS",
                "checks": {
                    "release_config": {"status": "PASS"},
                    "network_config": {"status": "PASS"},
                    "version_contract": {"status": "PASS"},
                },
            },
        )
        service.cache.mkdir(parents=True, exist_ok=True)
        poison = service.cache / "poison.bin"
        poison.write_bytes(b"cache-pollution")
        repaired = service.repair()
        checks["data_corruption_not_false_success"] = {
            "status": "PASS"
            if repaired.get("status") == "FAIL"
            and repaired.get("components", {}).get("data_integrity", {}).get("status") == "FAIL"
            else "FAIL"
        }
        checks["cache_pollution_cleared"] = {
            "status": "PASS"
            if repaired.get("components", {}).get("cache", {}).get("status") == "PASS"
            and not poison.exists()
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-fault-fs-") as td:
        target = Path(td) / "evidence.json"
        with patch("happy8.updater._durable_sync_path", side_effect=PermissionError("write denied")):
            checks["file_unwritable_fail_closed"] = {
                "status": "PASS"
                if must_raise(lambda: _atomic_json(target, {"status": "PASS"}))
                and not target.exists()
                else "FAIL"
            }
        with patch("happy8.updater._durable_sync_path", side_effect=OSError("disk full")):
            checks["disk_anomaly_fail_closed"] = {
                "status": "PASS"
                if must_raise(lambda: _atomic_json(target, {"status": "PASS"}))
                and not target.exists()
                else "FAIL"
            }

    with tempfile.TemporaryDirectory(prefix="happy8-fault-config-") as td:
        td = Path(td)
        main_exe = td / "Geometry_Lotto_Pro_Happy8.exe"
        updater_exe = td / "Geometry_Lotto_Pro_Happy8_Updater.exe"
        main_exe.write_bytes(b"MZ-main")
        updater_exe.write_bytes(b"MZ-updater")
        (td / "Happy8_Update_Config.json").write_text("{broken", encoding="utf-8")
        env = software_update_environment_status(
            main_exe=main_exe,
            current_version="0.2.0",
            updater_exe=updater_exe,
        )
        checks["configuration_error_explicit_blocked"] = {
            "status": "PASS"
            if env.get("status") == "BLOCKED"
            and env.get("checks", {}).get("release_config", {}).get("status") == "BLOCKED"
            and env.get("checks", {}).get("network_config", {}).get("status") == "BLOCKED"
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-fault-update-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe"
        target.write_bytes(original)
        updater = updater_for([requests.ConnectionError("offline")], attempts=1)
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["update_failure_preserves_target"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ABORTED_BEFORE_REPLACE"
            and target.read_bytes() == original
            else "FAIL"
        }

    status = "PASS" if checks and all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-fault-injection-gate-v1", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
