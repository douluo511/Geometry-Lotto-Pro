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
    cases = []
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
        cases.append({"name":"bounded_retry_then_success","status":"PASS","attempts":meta.attempts})

        bad_type=NetClient(Path(td)/"badtype.jsonl", max_attempts=1, backoff_base=0)
        bad_type.session=SequenceSession([Resp(200, ctype="text/html", obj={"x": 1})])
        expect_fail(lambda: bad_type.get_json("https://example.invalid/data", {}), "content-type")
        cases.append({"name":"wrong_content_type_fail_closed","status":"PASS"})

        mislabeled=NetClient(Path(td)/"mislabeled.jsonl", max_attempts=1, backoff_base=0)
        good_json = Resp(200, ctype="text/html", obj={"x": 1})
        good_json.content = b'{"x":1}'
        mislabeled.session=SequenceSession([good_json])
        obj, meta = mislabeled.get_json(
            "https://example.invalid/data", {}, allow_mislabeled_json=True
        )
        assert obj == {"x": 1}
        assert meta.content_type_policy == "provider-mislabeled-strict-json-body"
        cases.append({"name":"provider_mislabeled_strict_json_body","status":"PASS"})

        jsonp=NetClient(Path(td)/"jsonp.jsonl", max_attempts=1, backoff_base=0)
        good_assignment=Resp(200, ctype="application/javascript", obj={})
        good_assignment.content=b'kline_dayqfq2025={"data":{"ok":true}};'
        jsonp.session=SequenceSession([good_assignment])
        obj, meta=jsonp.get_jsonp_object(
            "https://example.invalid/data", {}, "kline_dayqfq2025"
        )
        assert obj["data"]["ok"] is True
        assert meta.content_type_policy == "strict-assignment-json"
        cases.append({"name":"strict_jsonp_assignment","status":"PASS"})

        wrong_prefix=NetClient(Path(td)/"jsonp-prefix.jsonl", max_attempts=1, backoff_base=0)
        prefix_resp=Resp(200, ctype="application/javascript", obj={})
        prefix_resp.content=b'evil={"data":{"ok":true}};'
        wrong_prefix.session=SequenceSession([prefix_resp])
        expect_fail(
            lambda: wrong_prefix.get_jsonp_object(
                "https://example.invalid/data", {}, "kline_dayqfq2025"
            ),
            "jsonp-prefix",
        )
        cases.append({"name":"jsonp_wrong_variable_fail_closed","status":"PASS"})

        trailing_script=NetClient(Path(td)/"jsonp-script.jsonl", max_attempts=1, backoff_base=0)
        script_resp=Resp(200, ctype="application/javascript", obj={})
        script_resp.content=b'kline_dayqfq2025={"data":{"ok":true}};alert(1)'
        trailing_script.session=SequenceSession([script_resp])
        expect_fail(
            lambda: trailing_script.get_jsonp_object(
                "https://example.invalid/data", {}, "kline_dayqfq2025"
            ),
            "jsonp-trailing-script",
        )
        cases.append({"name":"jsonp_trailing_script_fail_closed","status":"PASS"})

        empty_schema=NetClient(Path(td)/"schema.jsonl", max_attempts=1, backoff_base=0)
        empty_schema.session=SequenceSession([Resp(200, obj={"data": {"klines": []}})])
        expect_fail(lambda: fetch_daily_bars(empty_schema, "600000", 40), "schema")
        cases.append({"name":"empty_schema_fail_closed","status":"PASS"})

        expect_fail(lambda: client.get_json("http://example.invalid/data", {}), "non-HTTPS")
        cases.append({"name":"non_https_rejected","status":"PASS"})

    evidence={"status":"PASS","cases":cases,"case_count":len(cases)}
    Path("fault_injection_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
