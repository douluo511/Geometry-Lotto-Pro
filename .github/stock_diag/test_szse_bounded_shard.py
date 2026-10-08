"""No-live-network source shard contracts, including fail-closed raw bytes."""
import copy
import importlib.util
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("stock_szse_bounded_shard.py")
spec = importlib.util.spec_from_file_location("stock_shard", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
checks = []


def check(name, fn):
    try:
        fn()
        checks.append(name)
    except Exception as e:
        raise AssertionError(name) from e


def fake_archive():
    rows = [{
        "url": f"https://www.szse.cn/disclosure/notice/temp/t20200930_{i}.html",
        "date": "20200930",
        "identity_source": "literal_template_identifier",
    } for i in range(m.ARCHIVE_COUNT)]
    archive = {
        "schema": "stock-szse-suspension-static-archive-v1",
        "frozen_window": {"start": "20180101", "end": "20260930"},
        "corpus": {
            "event_rows": len(rows), "unique_article_links": len(rows),
            "canonical_sha256": m.canonical(rows), "events": rows,
        },
        "adjudication": {"official_static_archive_pagination": "PASS"},
    }
    return archive


class Response:
    def __init__(self, url, content, status=200, ctype="text/html; charset=utf-8"):
        self.url = url
        self.status_code = status
        self.content = content
        self.headers = {"Content-Type": ctype}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


VALID = ('<html><div class="news-detail-con"><div id="desContent" class="des-content">'
         '股票000001公告：证券代码000001于2020年9月30日开市起停牌，具体安排请等待正式公告。'
         '</div></div></html>').encode("utf-8")


def one(folder, getter):
    return m.capture(0, fake_archive()["corpus"]["events"][0], folder, getter=getter, sleep=lambda _: None)


def positive(folder):
    record = one(folder, lambda url, **kwargs: Response(url, VALID))
    assert record["status"] == "PASS"
    assert record["source_sha256"] == m.digest(VALID)
    assert Path(record["raw_path"]).read_bytes() == VALID
    assert record["article_selector"] == ".news-detail-con #desContent"
    assert record["attempts"][0]["status"] == "PASS"
    assert record["source_type"] == "fresh_official_HTTP"
    return record


def negative_http(folder):
    bad = b"temporarily unavailable from official host"
    result = one(folder, lambda url, **kwargs: Response(url, bad, 429))
    assert result["status"] == "NOT VERIFIED" and len(result["attempts"]) == 3
    assert all(a["http_status"] == 429 for a in result["attempts"])
    assert all(Path(a["raw_path"]).read_bytes() == bad for a in result["attempts"])
    assert "raw_path" not in result
    return result


def negative_nav(folder):
    html = b"<html><nav>000001 temporary suspension and trading information</nav></html>"
    result = one(folder, lambda url, **kwargs: Response(url, html))
    assert result["status"] == "NOT VERIFIED" and len(result["attempts"]) == 3
    assert all(Path(a["raw_path"]).read_bytes() == html for a in result["attempts"])
    return result


def negative_off_host(folder):
    result = one(folder, lambda url, **kwargs: Response("https://example.org/notice", VALID))
    assert result["status"] == "NOT VERIFIED"
    assert all("off-host" in a["error"] for a in result["attempts"])
    assert not folder.exists()
    return result


def negative_type(folder):
    result = one(folder, lambda url, **kwargs: Response(url, VALID, ctype="application/json"))
    assert result["status"] == "NOT VERIFIED"
    assert all("Content-Type" in a["error"] for a in result["attempts"])
    assert all(Path(a["raw_path"]).read_bytes() == VALID for a in result["attempts"])
    return result


def negative_network(folder):
    def err(url, **kwargs):
        raise ConnectionError("Network is unreachable")
    result = one(folder, err)
    assert result["status"] == "NOT VERIFIED"
    assert len(result["attempts"]) == 3 and "raw_path" not in result
    return result


def replay_100(archive, folder):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return Response(url, VALID)
    report = m.run(archive, 0, folder, getter=get, sleep=lambda _: None)
    assert len(calls) == 100
    assert report["requested"] == report["verified"] == 100
    assert report["start"] == 0 and report["end_exclusive"] == 100
    assert report["adjudication"]["shard_http_primary_body"] == "PASS"
    assert report["adjudication"]["entire_1849_current_network"] == "NOT VERIFIED"
    assert report["adjudication"]["final_gate"] == "FAIL"
    assert len({r["index"] for r in report["records"]}) == 100


def final_49(archive, folder):
    report = m.run(archive, 18, folder, getter=lambda url, **k: Response(url, VALID), sleep=lambda _: None)
    assert report["start"] == 1800
    assert report["end_exclusive"] == 1849
    assert report["requested"] == report["verified"] == 49
    assert report["full_frozen_denominator"] == 1849
    assert report["adjudication"]["historical_daily_st_suspension_pit_sse_szse_bse"] == "NOT VERIFIED"


def reject_archive(source, expected_error=None):
    try:
        m.validate_archive(source)
    except ValueError as exc:
        if expected_error:
            assert expected_error in str(exc)
        return
    raise AssertionError("untrusted archive unexpectedly accepted")


def reject_bad_index(source, idx):
    try:
        m.run(source, idx, Path("no_write"), getter=None)
    except ValueError:
        return
    raise AssertionError("invalid index accepted")


original = m.ARCHIVE_SHA256
archive = fake_archive()
m.ARCHIVE_SHA256 = archive["corpus"]["canonical_sha256"]
try:
    check("frozen 1849 source integrity positive", lambda: m.validate_archive(archive))
    tampered = copy.deepcopy(archive)
    tampered["corpus"]["events"][9]["url"] = tampered["corpus"]["events"][8]["url"]
    check("duplicate URL cannot reduce denominator", lambda: reject_archive(tampered))
    tampered = copy.deepcopy(archive)
    tampered["corpus"]["events"][9]["url"] = "https://example.org/disclosure/notice/temp/t20200930_9.html"
    check("non-official link fail closed", lambda: reject_archive(tampered))
    tampered = copy.deepcopy(archive)
    tampered["corpus"]["events"][9]["date"] = "20201001"
    check("URL effective publication identity mismatch", lambda: reject_archive(tampered))
    tampered = copy.deepcopy(archive)
    tampered["corpus"]["events"] = tampered["corpus"]["events"][:-1]
    check("truncated full denominator rejected", lambda: reject_archive(tampered, "1849"))
    tampered = copy.deepcopy(archive)
    tampered["corpus"]["canonical_sha256"] = "0" * 64
    check("hash substitution rejected", lambda: reject_archive(tampered))
    tampered = copy.deepcopy(archive)
    tampered["adjudication"]["official_static_archive_pagination"] = "NOT VERIFIED"
    check("unqualified archived pagination rejected", lambda: reject_archive(tampered))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        check("positive 200 exact bytes", lambda: positive(root / "positive"))
        check("429 response bytes preserved, not promoted", lambda: negative_http(root / "http"))
        check("navigation cannot be article", lambda: negative_nav(root / "nav"))
        check("redirect off SZSE cannot qualify", lambda: negative_off_host(root / "off"))
        check("invalid Content-Type raw preserved", lambda: negative_type(root / "type"))
        check("network failure not synthetic positive", lambda: negative_network(root / "net"))
        check("100 first shard complete but global non-PASS", lambda: replay_100(archive, root / "shard0"))
        check("last shard always 49 of fixed 1849", lambda: final_49(archive, root / "shard18"))
        check("negative shard index rejected", lambda: reject_bad_index(archive, -1))
finally:
    m.ARCHIVE_SHA256 = original

assert len(checks) == 16, checks
print(f"STOCK SZSE BOUNDED SHARD CONTRACTS {len(checks)}/16 PASS")
