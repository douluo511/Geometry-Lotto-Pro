from pathlib import Path

from head_intelligence.domain import RawDocument, Source
from head_intelligence.net_client import NetClient, NetworkPolicy
from head_intelligence.storage import AtomicStorage


class FakeResponse:
    def __init__(self, status_code=200, content=b"<rss><channel></channel></rss>", content_type="application/rss+xml"):
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


def test_netclient_contract_success():
    session = FakeSession([FakeResponse()])
    client = NetClient(
        policy=NetworkPolicy(max_attempts=1),
        session=session,
        sleeper=lambda _: None,
        random_fn=lambda: 0.0,
    )
    source = Source(id="test", name="Test", url="https://example.test/feed.xml")
    doc = client.fetch(source)
    assert doc.source_id == "test"
    assert doc.http_status == 200
    assert doc.payload_hash
    assert doc.payload.startswith(b"<rss")


def test_storage_contract_round_trip(tmp_path: Path):
    storage = AtomicStorage(tmp_path)
    doc = RawDocument(
        source_id="x",
        source_name="X",
        url="https://example.test/x",
        fetched_at="2026-09-24T00:00:00+00:00",
        http_status=200,
        content_type="application/xml",
        payload_hash="a" * 64,
        payload=b"<rss/>",
    )
    raw_path = storage.save_raw(doc)
    assert raw_path.exists()
    storage.save_json_atomic("sample.json", {"ok": True})
    assert storage.read_json("sample.json") == {"ok": True}
