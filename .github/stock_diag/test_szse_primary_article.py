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
# Live first-party HTML layout: observed on three SZSE pages covering
# 2018, 2020 and 2026. A matching id without this wrapper/header is NOT proof.
szse_body = (
    '<div class="news-detail-con g-conbox">'
    '<div class="des-header"><h2 class="title">关于股票临时停牌的公告</h2></div>'
    '<div class="des-content" id="desContent"><p class="MsoNormal">'
    '证券代码002628，成都路桥公司股票自2018年1月2日开市起临时停牌，'
    '公告内容明确，待指定媒体披露后复牌。'
    '</p></div><div class="des-footer">打印 收藏</div></div>'
)
checks.append(check(
    "real official desContent in verified article wrapper is accepted",
    '<html><body><nav>虚构代码000001 停牌</nav>' + szse_body + '</body></html>',
    True, "#desContent",
))
checks.append(check(
    "fake desContent outside primary detail wrapper cannot pass",
    '<html><body><div id="desContent" class="des-content">'
    '导航栏目包含证券代码000001，股票临时停牌信息，以及对应的复牌查询入口。'
    '</div></body></html>',
    False,
))
checks.append(check(
    "wrapper without separately identified official title is not enough",
    '<html><body><div class="news-detail-con g-conbox">'
    '<div id="desContent" class="des-content">'
    '导航栏目包含证券代码000001，股票临时停牌信息，以及对应的复牌查询入口。'
    '</div></div></body></html>',
    False,
))
checks.append(check(
    "desContent embedded in footer is never primary evidence",
    '<html><body><footer>' + szse_body + '</footer></body></html>',
    False,
))
checks.append(check(
    "verified container without stop or resume terms fails closed",
    '<html><body><div class="news-detail-con g-conbox">'
    '<div class="des-header"><h2 class="title">关于股票交易的信息公告</h2></div>'
    '<div id="desContent" class="des-content">'
    '证券代码002628，正式信息披露原文内容，但没有任何交易状态的确认。'
    '</div></div></body></html>',
    False,
))
assert len(checks) == 10

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

assert len(checks) == 13
print("SZSE PRIMARY ARTICLE + NETWORK REPLAY 13/13 OFFLINE REGRESSIONS PASS")
