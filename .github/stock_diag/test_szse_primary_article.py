"""Offline regression: boilerplate is not first-party suspension evidence."""
import importlib.util
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT = Path(__file__).resolve().with_name("stock_szse_suspension_detail_corpus.py")
spec = importlib.util.spec_from_file_location("szse_detail", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def check(label, html, expected_status, expected_selector=None):
    body, selector = module.extract_primary_article(BeautifulSoup(html, "html.parser"))
    assert (bool(body), selector) == (expected_status, expected_selector), (
        label, len(body), selector
    )
    return label


checks = []
checks.append(check(
    "global page chrome is not article evidence",
    '<html><head><title>停牌及复牌查询</title></head><body>'
    '<nav>证券代码 000001 停牌 复牌 新闻导览</nav>'
    '<footer>停牌公告信息查询 日期搜索 导航链接 股票代码 000001</footer>'
    '</body></html>',
    False,
))
checks.append(check(
    "primary article scope is accepted",
    '<html><body><nav>000002 停牌</nav><article>'
    '关于上市公司股票停牌安排的正式公告，股票代码000001，'
    '公司股票自2026年07月23日开市起停牌，具体原因详见公告。'
    '</article></body></html>',
    True,
    "article",
))
checks.append(check(
    "footer article-shaped block is never authoritative",
    '<html><body><footer><div class="content">'
    '关于上市公司股票停牌安排的正式公告，股票代码000001，'
    '公司股票自2026年07月23日开市起停牌，具体原因详见公告。'
    '</div></footer></body></html>',
    False,
))
checks.append(check(
    "nested navigation is never authoritative",
    '<html><body><nav><div class="content">'
    '关于上市公司股票停牌安排的正式公告，股票代码000001，'
    '公司股票自2026年07月23日开市起停牌，具体原因详见公告。'
    '</div></nav></body></html>',
    False,
))
checks.append(check(
    "article with only navigation removed fails closed",
    '<html><body><article><nav>'
    '公司股票自2026年07月23日起停牌，股票代码000001，'
    '详细情况请关注本公司临时公告内容与上市规则规定。'
    '</nav><p>目录</p></article></body></html>',
    False,
))
assert len(checks) == 5

# Retry success must retain the original failure ledger; PASS is never invented.
fetched = []
slept = []
def successful_retry(item):
    fetched.append(item["url"])
    return {"url": item["url"], "archive_date": item["date"], "status": "PASS",
            "transport": {"status": "PASS", "sha256": "real-source-byte-hash"}}
original = [
    {"url": "https://www.szse.cn/detail/a", "archive_date": "2025-12-09",
     "status": "NOT VERIFIED", "errors": [{"error": "Network is unreachable"}]},
]
replayed, meta = module.retry_unverified(
    original, fetch_fn=successful_retry, sleep_fn=slept.append)
assert meta["second_pass_recovered"] == 1 and len(fetched) == 1
assert replayed[0]["first_pass"]["errors"][0]["error"] == "Network is unreachable"
assert replayed[0]["recovery_attempted"] is True and replayed[0]["status"] == "PASS"
checks.append("recovered request retains original failure")

# A second network failure may never become a PASS.
def failed_retry(item):
    return {"url": item["url"], "archive_date": item["date"],
            "status": "NOT VERIFIED", "errors": [{"error": "Network still unreachable"}]}
again, status = module.retry_unverified(
    [{"url": "https://www.szse.cn/detail/b", "archive_date": "2026-01-02",
      "status": "NOT VERIFIED", "errors": [{"error": "initial error"}]}],
    fetch_fn=failed_retry, sleep_fn=lambda _: None)
assert status["second_pass_recovered"] == 0
assert again[0]["status"] == "NOT VERIFIED"
assert again[0]["first_pass"]["errors"][0]["error"] == "initial error"
checks.append("unresolved retry is still NOT VERIFIED")

# Reaching the bounded retry budget fails closed, rather than dropping rows.
never_called = lambda item: (_ for _ in ()).throw(AssertionError("must not retry"))
skipped, cap = module.retry_unverified([
    {"url": "https://www.szse.cn/detail/1", "status": "NOT VERIFIED"},
    {"url": "https://www.szse.cn/detail/2", "status": "NOT VERIFIED"},
], fetch_fn=never_called, sleep_fn=lambda _: None, max_retry_items=1)
assert cap["retry_cap_exceeded"] and cap["second_pass_attempted"] == 0
assert all(row["status"] == "NOT VERIFIED" for row in skipped)
checks.append("retry budget exhausted fails closed")

assert len(checks) == 8
print("SZSE PRIMARY ARTICLE + NETWORK REPLAY 8/8 OFFLINE REGRESSIONS PASS")
