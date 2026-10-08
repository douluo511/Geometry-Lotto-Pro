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
print("SZSE PRIMARY ARTICLE 5/5 OFFLINE REGRESSION PASS")
