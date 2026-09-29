from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import glp.sources as sources
from glp.domain import CanonicalDataset, Draw, SourceReceipt
from glp.net_client import NetClient
from glp.sources import SourceError
from glp.storage import Store
from glp.util import sha256_json, utc_now


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None, url="https://example.invalid/data"):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self.url = url
        self.encoding = "utf-8"

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8")

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.outcomes:
            raise AssertionError("unexpected extra request")
        value = self.outcomes.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _fixture(extra=False):
    draws = [Draw("26001", "2026-01-03", (1, 2, 3, 4, 5), (1, 2))]
    if extra:
        draws.append(Draw("26002", "2026-01-05", (2, 3, 4, 5, 6), (2, 3)))
    digest = sha256_json([d.to_dict() for d in draws])
    receipt = SourceReceipt(
        source="fixture",
        fetched_at=utc_now(),
        http_status=200,
        raw_sha256="0" * 64,
        draw_count=len(draws),
        latest_issue=draws[-1].issue,
        status="PASS",
        detail="fault fixture",
    )
    ds = CanonicalDataset(draws, digest, [receipt], 1, "PASS")
    ev = {
        "schema": "dlt-fault-fixture",
        "canonical_hash": digest,
        "draw_count": len(draws),
        "latest": draws[-1].to_dict(),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
    }
    return ds, ev


def main() -> int:
    checks = {}

    def record(name, ok, detail):
        checks[name] = {"status": "PASS" if ok else "FAIL", "detail": detail}

    sleeps = []
    session = FakeSession([
        requests.Timeout("t1"),
        requests.ConnectionError("c2"),
        requests.Timeout("t3"),
    ])
    client = NetClient(
        connect_timeout=1,
        read_timeout=2,
        max_attempts=3,
        backoff_base=0.1,
        session=session,
        sleeper=sleeps.append,
        rng=random.Random(1),
    )
    try:
        client.get("https://example.invalid/data")
        record("retry_exhaustion_fail_closed", False, "request unexpectedly returned")
    except requests.Timeout as exc:
        ledger = list(getattr(exc, "glp_attempts", ()))
        record(
            "retry_exhaustion_fail_closed",
            len(session.calls) == 3
            and len(sleeps) == 2
            and len(ledger) == 3
            and ledger[-1]["outcome"] == "FINAL_EXCEPTION",
            {"calls": len(session.calls), "sleeps": sleeps, "ledger": ledger},
        )

    duplicate_payload = (
        b'{"success":true,"value":{"pages":1,"total":2,"list":['
        b'{"lotteryDrawNum":"26100","lotteryDrawTime":"2026-09-01","lotteryDrawResult":"01 02 03 04 05 01 02"},'
        b'{"lotteryDrawNum":"26100","lotteryDrawTime":"2026-09-01","lotteryDrawResult":"01 02 03 04 05 01 02"}]}}'
    )
    try:
        sources.fetch_national_page(1, session=FakeSession([
            FakeResponse(200, duplicate_payload, {"Content-Type": "application/json"})
        ]))
        record("duplicate_issue_fail_closed", False, "duplicate issue accepted")
    except SourceError as exc:
        record("duplicate_issue_fail_closed", True, str(exc))

    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td))
        ds1, ev1 = _fixture(False)
        ds2, ev2 = _fixture(True)
        store.save_dataset(ds1, ev1)
        old_history = store.history_path.read_bytes()
        old_evidence = store.evidence_path.read_bytes()
        original_stage = store._stage_bytes

        def fail_evidence(path, data):
            if Path(path) == store.evidence_path:
                raise OSError("injected evidence staging failure")
            return original_stage(path, data)

        store._stage_bytes = fail_evidence
        try:
            store.save_dataset(ds2, ev2)
            record("evidence_stage_failure_atomic", False, "save unexpectedly succeeded")
        except OSError:
            record(
                "evidence_stage_failure_atomic",
                store.history_path.read_bytes() == old_history
                and store.evidence_path.read_bytes() == old_evidence,
                "canonical/evidence bytes compared after injected failure",
            )

    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td))
        ds1, ev1 = _fixture(False)
        ds2, ev2 = _fixture(True)
        store.save_dataset(ds1, ev1)
        old_history = store.history_path.read_bytes()
        old_evidence = store.evidence_path.read_bytes()
        original_commit = store._commit_replace

        def fail_history(staged, target):
            if Path(target) == store.history_path:
                raise OSError("injected history commit failure")
            return original_commit(staged, target)

        store._commit_replace = fail_history
        try:
            store.save_dataset(ds2, ev2)
            record("history_commit_failure_rolls_back", False, "save unexpectedly succeeded")
        except OSError:
            record(
                "history_commit_failure_rolls_back",
                store.history_path.read_bytes() == old_history
                and store.evidence_path.read_bytes() == old_evidence,
                "canonical/evidence bytes compared after rollback",
            )

    failures = [name for name, row in checks.items() if row["status"] != "PASS"]
    report = {
        "schema": "dlt-network-fault-gate-v1",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "failures": failures,
        "checks": checks,
    }
    out = ROOT / "artifacts" / "network_fault_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
