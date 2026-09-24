from pathlib import Path

import pytest

from head_intelligence.domain import Source
from head_intelligence.engine import InformationEngine
from head_intelligence.net_client import NetClient, NetworkPolicy
from head_intelligence.storage import AtomicStorage


class FakeResponse:
    def __init__(self, status_code=200, content=b"<rss><channel><item><title>A</title></item></channel></rss>", content_type="application/rss+xml"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status={self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class AlwaysFailNet:
    def fetch(self, source):
        raise RuntimeError("injected network failure")


def test_retry_429_then_success():
    session = FakeSession([FakeResponse(429), FakeResponse(200)])
    sleeps = []
    client = NetClient(
        policy=NetworkPolicy(max_attempts=2, base_backoff=0.01),
        session=session,
        sleeper=sleeps.append,
        random_fn=lambda: 0.0,
    )
    source = Source(id="retry", name="Retry", url="https://example.test/feed")
    doc = client.fetch(source)
    assert doc.http_status == 200
    assert session.calls == 2
    assert len(sleeps) == 1


def test_reject_unexpected_content_type():
    session = FakeSession([FakeResponse(200, b"{}", "application/json")])
    client = NetClient(
        policy=NetworkPolicy(max_attempts=1),
        session=session,
        sleeper=lambda _: None,
        random_fn=lambda: 0.0,
    )
    source = Source(id="bad-type", name="Bad Type", url="https://example.test/feed")
    with pytest.raises(ValueError):
        client.fetch(source)


def test_failed_update_never_overwrites_last_good_snapshot(tmp_path: Path):
    storage = AtomicStorage(tmp_path)
    old = {"status": "PASS", "snapshot_id": "known-good"}
    storage.save_json_atomic("latest_snapshot.json", old)

    engine = InformationEngine(
        storage=storage,
        sources=[Source(id="fail", name="Fail", url="https://example.test/fail")],
        net_client=AlwaysFailNet(),
    )
    report = engine.one_click_update()
    assert report.status == "FAIL"
    assert storage.read_json("latest_snapshot.json") == old


def test_corrupted_snapshot_health_fails(tmp_path: Path):
    storage = AtomicStorage(tmp_path)
    (tmp_path / "latest_snapshot.json").write_text("{broken", encoding="utf-8")
    engine = InformationEngine(storage=storage)
    health = engine.health_check()
    assert health["status"] == "FAIL"
    assert health["checks"]["snapshot_readable"] is False
