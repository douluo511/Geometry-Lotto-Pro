"""Semantic regressions: accepting decoys or repairing bad evidence is a bug."""
import hashlib
import unittest

from research.harness_v46 import jiangsu_details as jd
from research.harness_v46.core import GateError


INDEX_URL = "https://api.js-lottery.com/Lottery/_ListData?itemType=lo&pageIndex=1&pageSize=100"
EXPECTED = {"issue": "16003", "index_publication_date": "2016-01-07",
            "front": [4, 12, 17, 22, 26], "back": [6, 7],
            "detail_url": "https://api.js-lottery.com/cms/post-70003.html",
            "index_raw_sha256": "a" * 64}
TITLE = "全国联网电脑体育彩票“大乐透”第16003期开奖公告"
DATE = "<p>开奖日期：2016年1月6日<br>本期全国销售额：175,147,656元。</p>"
HEADER = "<thead><tr><th></th><th>前区</th><th>后区</th></tr></thead>"
ORDER = "<tr><td>本期出球顺序：</td><td>04 12 22 17 26</td><td>07 06</td></tr>"
WIN = "<tr><td>本期开奖结果：</td><td>04 12 17 22 26</td><td>06 07</td></tr>"
TABLE = "<table>" + HEADER + "<tbody>" + ORDER + WIN + "</tbody></table>"
BODY = DATE + TABLE


def detail(body=BODY, title=TITLE):
    return ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
            '<div><div><h1>' + title + '</h1><ul><li>发布时间: 2016-01-06</li></ul>'
            '</div><div class="content-text-area">' + body + '</div></div></body></html>')


ROW = '<tr><td>2016-01-07</td><td>16003</td><td>04 12 17 22 26 06 07</td><td><a href="/cms/post-70003.html">详细</a></td></tr>'


def index(row=ROW, total=1, page=1):
    return ('<table><tr><td>发布日期</td><td>期号</td><td>开奖号码</td><td>详细</td></tr>'
            + row + '</table><div data-sum="' + str(total) + '" data-pageindex="'
            + str(page) + '" data-size="100"></div>')


def raw(text):
    return text.encode("utf-8")


class JiangsuDetailsTests(unittest.TestCase):
    def test_explicit_detail_date_is_not_index_publication_date(self):
        # Returning metadata as the draw date must fail this literal assertion.
        self.assertEqual(jd.parse_detail(raw(detail()), EXPECTED), {
            "draw": {"issue": "16003", "draw_date": "2016-01-06", "front": [4, 12, 17, 22, 26], "back": [6, 7]},
            "publication_date": "2016-01-06", "draw_order": {"front": [4, 12, 22, 17, 26], "back": [7, 6]},
            "detail_raw_sha256": hashlib.sha256(raw(detail())).hexdigest(),
            "contract_variant": {"title_family": "全国联网电脑体育彩票“大乐透”", "winning_label": "本期开奖结果"},
            "parser": {"name": "html5lib", "version": "1.1"},
            "formal_A": 0, "decision": "NO_EDGE"})

    def test_modern_variant_entities_formatting_and_no_order(self):
        text = detail((DATE + '<table>' + HEADER + '<tbody>' + WIN + '</tbody></table>')
                      .replace('本期开奖结果', '本期开奖号码').replace('04 12', '<b>04</b>&nbsp;12'),
                      '中国体育彩票超级大乐透第16003期开奖公告')
        result = jd.parse_detail(raw(text), EXPECTED)
        self.assertEqual(result["draw"]["front"], [4, 12, 17, 22, 26])
        self.assertIsNone(result["draw_order"])
        self.assertEqual(result["contract_variant"]["winning_label"], "本期开奖号码")

    def test_unrelated_head_navigation_script_footer_do_not_supply_fields(self):
        decoy = '<h1>中国体育彩票超级大乐透第99999期开奖公告</h1><p>开奖日期：2020年1月1日</p>'
        text = detail().replace('<body>', '<body><nav>' + decoy + '</nav><script>' + decoy + '</script>')
        text = text.replace('</body>', '<footer>' + decoy + '</footer></body>')
        self.assertEqual(jd.parse_detail(raw(text), EXPECTED)["draw"]["issue"], "16003")

    def test_required_detail_semantics_reject_missing_duplicate_conflicting_or_invalid_fields(self):
        cases = {
            "missing_date": detail(BODY.replace(DATE, '')),
            "invalid_date": detail(BODY.replace('2016年1月6日', '2016年2月30日')),
            "duplicate_date": detail(DATE + BODY),
            "conflicting_date": detail('<p>开奖日期：2016年1月7日</p>' + BODY),
            "missing_title": detail().replace('<h1>' + TITLE + '</h1>', ''),
            "duplicate_title": detail().replace('</h1>', '</h1><h1>' + TITLE + '</h1>'),
            "wrong_issue": detail(title=TITLE.replace('16003', '16004')),
            "unsupported_title": detail(title=TITLE.replace('全国联网电脑体育彩票“大乐透”', '大乐透')),
            "duplicate_body": detail().replace('</body>', '<div class="content-text-area">' + BODY + '</div></body>'),
            "duplicate_result": detail(BODY.replace(WIN, WIN + WIN)),
            "two_labels": detail(BODY.replace(WIN, WIN + WIN.replace('本期开奖结果', '本期开奖号码'))),
            "missing_result": detail(BODY.replace(WIN, '')),
            "result_before_headers": detail(DATE + '<table>' + WIN + HEADER + '</table>'),
            "wrong_headers": detail(BODY.replace('前区', '号码')),
            "split_tables": detail(BODY.replace(WIN, '</tbody></table><table><tbody>' + WIN)),
            "nested_cell": detail(BODY.replace('04 12 17 22 26', '<table><tr><td>04 12 17 22 26</td></tr></table>')),
            "merged_cell": detail(BODY.replace('<td>04 12 17', '<td colspan="2">04 12 17')),
            "extra_cell": detail(BODY.replace('06 07</td>', '06 07</td><td>99</td>')),
            "not_canonical": detail(BODY.replace('04 12 17 22 26', '12 04 17 22 26')),
            "wrong_numbers": detail(BODY.replace('04 12 17 22 26', '04 12 17 22 27')),
            "repeat_numbers": detail(BODY.replace('04 12 17 22 26', '04 12 17 22 22')),
            "out_of_range": detail(BODY.replace('04 12 17 22 26', '04 12 17 22 36')),
            "unicode_digits": detail(BODY.replace('04 12 17 22 26', '０４ 12 17 22 26')),
            "extra_token": detail(BODY.replace('04 12 17 22 26', '04 12 17 22 26 x')),
            "bad_order": detail(BODY.replace('04 12 22 17 26', '04 12 22 17 27')),
            "duplicate_order": detail(BODY.replace(ORDER, ORDER + ORDER)),
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(GateError):
                jd.parse_detail(raw(text), EXPECTED)

    def test_detail_rejects_required_hidden_or_inert_evidence(self):
        for attr in ('hidden', 'inert', 'aria-hidden="true"', 'style="display:none"',
                     'style="visibility: hidden !important"', 'style="DISPLAY : none"'):
            for marker in ('<h1>', '<p>', '<table>', '<td>04 12 17 22 26', '<div class="content-text-area">'):
                replacement = marker.replace('>', ' ' + attr + '>', 1)
                with self.subTest(attr=attr, marker=marker), self.assertRaises(GateError):
                    jd.parse_detail(raw(detail().replace(marker, replacement)), EXPECTED)
        for tag in ('template', 'noscript', 'textarea', 'iframe', 'xmp', 'style', 'script', 'noembed', 'noframes'):
            with self.subTest(tag=tag), self.assertRaises(GateError):
                jd.parse_detail(raw(detail('<' + tag + '>' + BODY + '</' + tag + '>')), EXPECTED)

    def test_html5_rawtext_endtags_and_escaped_structure_do_not_bypass_binding(self):
        import html
        for text in (detail(html.escape(BODY)),
                     detail('<textarea>' + BODY + '</textarea bogus>'),
                     detail('<script>' + BODY + '</script bogus>'),
                     '<textarea>' + detail() + '</textarea>',
                     detail(BODY.replace(TABLE, '<textarea>' + TABLE + '</textarea>')),
                     detail(BODY.replace(TABLE, html.escape(TABLE)))):
            with self.subTest(text=text[:80]), self.assertRaises(GateError):
                jd.parse_detail(raw(text), EXPECTED)

    def test_expected_record_must_be_canonical_and_url_clean(self):
        for field, value in [('issue', '１６００３'), ('front', [12, 4, 17, 22, 26]),
                             ('back', [6, 6]), ('detail_url', 'https://evil.test/cms/post-70003.html'),
                             ('detail_url', 'https://api.js-lottery.com:443/cms/post-70003.html'),
                             ('detail_url', 'https://api.js-lottery.com/cms/post-70003.html?q=1')]:
            with self.subTest(field=field, value=value), self.assertRaises(GateError):
                jd.parse_detail(raw(detail()), {**EXPECTED, field: value})

    def test_index_canonical_record_and_inventory(self):
        page = jd.parse_index_page(raw(index()), INDEX_URL)
        record = {**EXPECTED, 'index_raw_sha256': hashlib.sha256(raw(index())).hexdigest()}
        self.assertEqual(page['records'], [record])
        self.assertEqual(page['declared_total'], 1)
        self.assertEqual(jd.build_inventory([{'raw_bytes': raw(index()), 'source_url': INDEX_URL}])['records'], [record])

    def test_index_rejects_bad_dates_rows_numbers_links_and_contexts(self):
        cases = [index().replace('2016-01-07', '2016-02-30'), index().replace('16003', '１６００３'),
                 index().replace('04 12 17 22 26 06 07', '12 04 17 22 26 06 07'),
                 index().replace('<td>16003', '<td colspan="2">16003'),
                 index().replace('<td>16003', '<td hidden>16003'),
                 index().replace(ROW, ROW + ROW), index().replace('data-sum="1"', 'data-sum="x"'),
                 index().replace('发布日期', '开奖日期'), index().replace('<a href=', '<a hidden href='),
                 index().replace('</a>', '</a><a href="/cms/post-2.html">详细</a>'),
                 index().replace('<td>16003</td>', '<td><table><tr><td>16003</td></tr></table></td>')]
        for url in ('http://api.js-lottery.com/cms/post-1.html', '//evil.test/cms/post-1.html',
                    'https://api.js-lottery.com@evil.test/cms/post-1.html', '/cms/post-01.html',
                    '/cms/post-1.html#x', '/cms/post-1.html?x=1', '/cms/../cms/post-1.html',
                    'https://api.js-lottery.com:443/cms/post-1.html'):
            cases.append(index().replace('/cms/post-70003.html', url))
        for tag in ('template', 'noscript', 'textarea', 'iframe'):
            cases.append('<' + tag + '>' + index() + '</' + tag + '>')
        for text in cases:
            with self.subTest(text=text[:90]), self.assertRaises(GateError):
                jd.parse_index_page(raw(text), INDEX_URL)
        for url in ('https://evil.test/Lottery/_ListData', 'http://api.js-lottery.com/Lottery/_ListData',
                    'https://api.js-lottery.com/Lottery/_ListData#x'):
            with self.subTest(url=url), self.assertRaises(GateError):
                jd.parse_index_page(raw(index()), url)

    def test_inventory_rejects_missing_scope_duplicates_and_total_conflicts(self):
        def page(text, url=INDEX_URL):
            return {'raw_bytes': raw(text), 'source_url': url}
        for pages in ([], [page(index(total=2))], [page(index()), page(index())],
                      [page(index(total=2)), page(index(ROW.replace('16003', '16004'), total=3, page=2), INDEX_URL.replace('pageIndex=1', 'pageIndex=2'))]):
            with self.subTest(pages=len(pages)), self.assertRaises(GateError):
                jd.build_inventory(pages)

    def test_inventory_full_count_and_numeric_issue_sort(self):
        # Scope size is independent of history admission; every byte-derived row counts.
        pages = []
        for page in range(1, 7):
            rows = ''.join(ROW.replace('16003', f'{7000+i:05d}').replace('post-70003', f'post-{i}') for i in range((page-1)*100+1, page*100+1))
            pages.append({'raw_bytes': raw(index(rows, total=600, page=page)), 'source_url': INDEX_URL.replace('pageIndex=1', f'pageIndex={page}')})
        result = jd.build_inventory(list(reversed(pages)))
        self.assertEqual(len(result['records']), 600)
        self.assertEqual(result['records'][0]['issue'], '07001')
        self.assertEqual(result['records'][-1]['issue'], '07600')

    def test_unpinned_runtime_is_rejected(self):
        from unittest.mock import patch
        with patch.object(jd.html5lib, '__version__', '0.999'):
            with self.assertRaisesRegex(GateError, 'JIANGSU_PARSER_VERSION'):
                jd.parse_detail(raw(detail()), EXPECTED)

    def test_escaped_duplicate_and_nested_result_table_are_ambiguous(self):
        import html
        for text in (detail(BODY + html.escape(WIN)),
                     detail(DATE + '<table><tr><td>' + TABLE + '</td></tr></table>'),
                     detail(BODY.replace(HEADER, HEADER + HEADER)),
                     detail(BODY.replace('本期开奖结果：', '本期开奖结果：：'))):
            with self.subTest(text=text[-80:]), self.assertRaises(GateError):
                jd.parse_detail(raw(text), EXPECTED)

    def test_article_title_must_be_outside_content_body(self):
        text = detail('<h1>' + TITLE + '</h1>' + BODY).replace('<h1>' + TITLE + '</h1>', '', 1)
        with self.assertRaises(GateError):
            jd.parse_detail(raw(text), EXPECTED)

    def test_detail_index_issue_must_be_a_string(self):
        with self.assertRaises(GateError):
            jd.parse_detail(raw(detail()), {**EXPECTED, 'issue': 16003})

    def test_duplicate_urls_across_otherwise_complete_pages_reject_scope(self):
        pages = []
        for page in (1, 2):
            rows = ''.join(ROW.replace('16003', f'{7000+i:05d}').replace('post-70003', f'post-{i if page == 1 else i-100}') for i in range((page-1)*100+1, page*100+1))
            pages.append({'raw_bytes': raw(index(rows, total=200, page=page)), 'source_url': INDEX_URL.replace('pageIndex=1', f'pageIndex={page}')})
        with self.assertRaises(GateError):
            jd.build_inventory(pages)

    def test_body_scripts_and_styles_do_not_contribute_evidence(self):
        text = detail('<script>开奖日期：2020年2月30日</script><style>.x { content: "本期开奖结果" }</style>' + BODY)
        self.assertEqual(jd.parse_detail(raw(text), EXPECTED)['draw']['draw_date'], '2016-01-06')
        text = detail(BODY.replace('04 12 17 22 26', '04 <script>99</script>12 17 22 26'))
        self.assertEqual(jd.parse_detail(raw(text), EXPECTED)['draw']['front'], [4, 12, 17, 22, 26])

    def test_html5_escaped_tags_cannot_open_close_real_contexts(self):
        cases = [detail('<textarea>&lt;/textarea&gt;' + BODY + '</textarea>'),
                 detail('<script>&lt;/script&gt;' + BODY + '</script>'),
                 detail('<xmp>' + BODY + '</xmp bogus>'),
                 detail('<textarea></textareax>' + BODY + '</textarea>'),
                 detail('<textarea></textarea x="' + BODY + '">'),
                 detail(BODY.replace(WIN, '<template>' + WIN + '</template>'))]
        for text in cases:
            with self.subTest(text=text[:60]), self.assertRaises(GateError):
                jd.parse_detail(raw(text), EXPECTED)

    def test_independently_observed_super_dlt_title_family(self):
        parsed = jd.parse_detail(raw(detail(title='全国联网电脑体育彩票“超级大乐透”第16003期开奖公告')), EXPECTED)
        self.assertEqual(parsed['contract_variant']['title_family'], '全国联网电脑体育彩票“超级大乐透”')

    def test_html_comments_cannot_supply_numbers_or_duplicate_semantics(self):
        with self.assertRaises(GateError):
            jd.parse_detail(raw(detail(BODY.replace('04 12 17 22 26', '<!--04 12 17 22 26-->'))), EXPECTED)
        parsed = jd.parse_detail(raw(detail('<!--开奖日期：2016年1月7日-->' + BODY)), EXPECTED)
        self.assertEqual(parsed['draw']['draw_date'], '2016-01-06')
        parsed = jd.parse_detail(raw(detail(BODY.replace('<td>', '<!--formatting--><td>'))), EXPECTED)
        self.assertEqual(parsed['draw']['back'], [6, 7])


if __name__ == '__main__':
    unittest.main()
