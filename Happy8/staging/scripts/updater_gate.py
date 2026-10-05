from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.updater import Updater


class FakeResponse:
    def __init__(self, *, url: str, content: bytes, content_type: str, status_code: int = 200):
        self.url = url
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.happy8_attempts = ({"attempt": 1, "outcome": "HTTP_RESPONSE", "status_code": status_code},)


class FakeNet:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise RuntimeError("unexpected network request")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def manifest_bytes(*, version: str, artifact: bytes, digest: str | None = None) -> bytes:
    value = {
        "schema": "happy8-update-manifest-v1",
        "version": version,
        "artifact_url": "https://updates.example/Happy8.exe",
        "artifact_sha256": digest or hashlib.sha256(artifact).hexdigest(),
        "artifact_bytes": len(artifact),
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def updater_with(manifest: bytes, artifact: bytes | None = None) -> Updater:
    responses = [
        FakeResponse(
            url="https://updates.example/latest.json",
            content=manifest,
            content_type="application/json",
        )
    ]
    if artifact is not None:
        responses.append(
            FakeResponse(
                url="https://updates.example/Happy8.exe",
                content=artifact,
                content_type="application/octet-stream",
            )
        )
    return Updater(
        manifest_url="https://updates.example/latest.json",
        trusted_hosts={"updates.example"},
        net=FakeNet(responses),
    )


def main() -> int:
    checks = {}

    try:
        Updater(
            manifest_url="http://updates.example/latest.json",
            trusted_hosts={"updates.example"},
            net=FakeNet([]),
        )
        checks["manifest_https_trust_fail_closed"] = {"status": "FAIL"}
    except ValueError:
        checks["manifest_https_trust_fail_closed"] = {"status": "PASS"}

    artifact = b"MZ" + b"candidate" * 500
    manifest = manifest_bytes(version="0.2.1", artifact=artifact)
    updater = updater_with(manifest, artifact)
    parsed, _ = updater.fetch_manifest()
    downloaded, receipt = updater.download_artifact(parsed)
    checks["manifest_and_hash_contract"] = {
        "status": "PASS"
        if downloaded == artifact and receipt.get("sha256") == hashlib.sha256(artifact).hexdigest()
        else "FAIL"
    }

    bad_manifest = manifest_bytes(version="0.2.1", artifact=artifact, digest="0" * 64)
    updater = updater_with(bad_manifest, artifact)
    parsed, _ = updater.fetch_manifest()
    try:
        updater.download_artifact(parsed)
        checks["bad_artifact_hash_fail_closed"] = {"status": "FAIL"}
    except RuntimeError:
        checks["bad_artifact_hash_fail_closed"] = {"status": "PASS"}

    with tempfile.TemporaryDirectory(prefix="happy8-updater-up-to-date-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-bytes"
        target.write_bytes(original)
        same_manifest = manifest_bytes(version="0.2.0", artifact=artifact)
        updater = updater_with(same_manifest)
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["non_monotonic_no_replace"] = {
            "status": "PASS"
            if result.get("status") == "PASS"
            and result.get("action") == "UP_TO_DATE"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-rollback-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-bytes-for-rollback"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["health_failure_atomic_rollback"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ROLLED_BACK"
            and target.read_bytes() == original
            else "FAIL"
        }

    status = "PASS" if all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-updater-gate-v1", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
