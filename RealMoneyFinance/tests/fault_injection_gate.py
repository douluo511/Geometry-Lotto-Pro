from __future__ import annotations

from pathlib import Path
import json
import tempfile

from app.netclient import NetClient
from app.source_eastmoney import fetch_daily_bars


class Resp:
    def __init__(self, status=200, ctype="application/json", obj=None, url="https://example.invalid/data"):
        self.status_code=status
        self.headers={"content-type":ctype}
        self._obj=obj if obj is not None else {}
        self.url=url
        self.content=json.dumps(self._obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code), response=self)

    def json(self):
        return self._obj


class SequenceSession:
    def __init__(self, responses):
        self.responses=list(responses)
        self.headers={}

    def get(self, *args, **kwargs):
        if not self.responses:
            raise RuntimeError("no response left")
        return self.responses.pop(0)


def expect_fail(fn, name):
    try:
        fn()
    except Exception:
        return
    raise AssertionError(name + " did not fail closed")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        client=NetClient(Path(td)/"net.jsonl", max_attempts=3, backoff_base=0)
        client.session=SequenceSession([
            Resp(429),
            Resp(503),
            Resp(200, obj={"ok": True}),
        ])
        obj, meta=client.get_json("https://example.invalid/data", {})
        assert obj["ok"] is True
        assert meta.attempts == 3

        bad_type=NetClient(Path(td)/"badtype.jsonl", max_attempts=1, backoff_base=0)
        bad_type.session=SequenceSession([Resp(200, ctype="text/html", obj={"x": 1})])
        expect_fail(lambda: bad_type.get_json("https://example.invalid/data", {}), "content-type")

        mislabeled=NetClient(Path(td)/"mislabeled.jsonl", max_attempts=1, backoff_base=0)
        good_json = Resp(200, ctype="text/html", obj={"x": 1})
        good_json.content = b'{"x":1}'
        mislabeled.session=SequenceSession([good_json])
        obj, meta = mislabeled.get_json(
            "https://example.invalid/data", {}, allow_mislabeled_json=True
        )
        assert obj == {"x": 1}
        assert meta.content_type_policy == "provider-mislabeled-strict-json-body"

        empty_schema=NetClient(Path(td)/"schema.jsonl", max_attempts=1, backoff_base=0)
        empty_schema.session=SequenceSession([Resp(200, obj={"data": {"klines": []}})])
        expect_fail(lambda: fetch_daily_bars(empty_schema, "600000", 40), "schema")

        expect_fail(lambda: client.get_json("http://example.invalid/data", {}), "non-HTTPS")

    print("FAULT_INJECTION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
