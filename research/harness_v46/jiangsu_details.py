"""Pure, fail-closed HTML5 semantics for observed Jiangsu DLT article schemas.

This establishes bindings within retained bytes, never source authenticity,
publication-time trust, complete issuance history, or forecast admission.
"""
from datetime import date
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

import html5lib

from .core import GateError


_ORIGIN = 'https://api.js-lottery.com'
_TITLE_FAMILIES = ('中国体育彩票超级大乐透', '全国联网电脑体育彩票“大乐透”',
                   '全国联网电脑体育彩票“超级大乐透”')
_WIN_LABELS = ('本期开奖号码', '本期开奖结果')
_IGNORED = frozenset(('head', 'nav', 'footer', 'script', 'style'))
_INERT = frozenset(('template', 'noscript', 'textarea', 'iframe', 'xmp',
                    'noembed', 'noframes', 'plaintext', 'object', 'embed'))
_STRUCTURAL = frozenset(('table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'))
_BLOCKS = frozenset(('p', 'div', 'br', 'table', 'tr', 'li', 'section', 'article'))
def _metadata():
    return {'parser': {'name': 'html5lib', 'version': '1.1'}, 'formal_A': 0,
            'decision': 'NO_EDGE'}


def _fail(code):
    raise GateError('JIANGSU_' + code)


def _url(value, *, detail=False):
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        _fail('URL')
    try:
        parsed = urlsplit(value)
    except ValueError:
        _fail('URL')
    if parsed.scheme != 'https' or parsed.netloc != 'api.js-lottery.com' or parsed.fragment:
        _fail('URL')
    if detail:
        if parsed.query or not re.fullmatch(r'/cms/post-[1-9][0-9]*\.html', parsed.path):
            _fail('DETAIL_URL')
        if value != _ORIGIN + parsed.path:
            _fail('DETAIL_URL')
    elif parsed.path != '/Lottery/_ListData':
        _fail('INDEX_URL')
    return parsed


def _dom(raw):
    if html5lib.__version__ != '1.1':
        _fail('PARSER_VERSION')
    if not isinstance(raw, bytes) or not raw:
        _fail('RAW_BYTES')
    try:
        # The retained source declares UTF-8. Reject broken bytes rather than
        # silently replacing a digit or label; HTML5 handles entities itself.
        text = raw.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError:
        _fail('ENCODING')
    parser = html5lib.HTMLParser(namespaceHTMLElements=False)
    root = parser.parse(text, scripting=True)
    # html5lib1.1 can foster-parent an unsupported inert tag out of a table,
    # leaving its rows active. Never accept evidence through that repair.
    if any(error[2].get('name') in _INERT for error in parser.errors):
        _fail('HTML5_INERT_CONTEXT_REPAIR')
    parents = {child: parent for parent in root.iter() for child in parent}
    return root, parents


def _ancestors(node, parents):
    while node is not None:
        yield node
        node = parents.get(node)


def _hidden(node):
    attrs = node.attrib
    if 'hidden' in attrs or 'inert' in attrs or attrs.get('aria-hidden', '').strip().lower() == 'true':
        return True
    # Inline visibility only. No external CSS or computed visibility claim.
    for declaration in attrs.get('style', '').lower().split(';'):
        key, sep, value = declaration.partition(':')
        value = value.split('!')[0].strip()
        if sep and ((key.strip() == 'display' and value == 'none') or
                    (key.strip() == 'visibility' and value in ('hidden', 'collapse'))):
            return True
    return False


def _unsafe(node, parents):
    return any(n.tag in _INERT or n.tag in _IGNORED or _hidden(n)
               for n in _ancestors(node, parents))


def _eligible(node, parents):
    return not any(n.tag in _IGNORED or n.tag in _INERT for n in _ancestors(node, parents))


def _text(node, parents, *, strict=True, boundaries=False):
    if strict and (_unsafe(node, parents) or any(
            n.tag in _INERT or _hidden(n) for n in node.iter())):
        _fail('HIDDEN_OR_INERT_EVIDENCE')
    def visit(n):
        if (not isinstance(n.tag, str) or n.tag in _IGNORED or
                (not strict and (n.tag in _INERT or _hidden(n)))):
            return ''
        result = n.text or ''
        for child in n:
            result += visit(child) + (child.tail or '')
        if boundaries and n.tag in _BLOCKS:
            result = '\n' + result + '\n'
        return result
    return re.sub(r'\s+', ' ', visit(node)).strip()


def _compact(node, parents):
    return re.sub(r'\s+', '', _text(node, parents))


def _one(items, code):
    if len(items) != 1:
        _fail(code)
    return items[0]


def _iso(value, code):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        _fail(code)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        _fail(code)


def _zone(values, count, limit, *, canonical=True):
    if (not isinstance(values, list) or len(values) != count or
            any(type(n) is not int or not 1 <= n <= limit for n in values) or
            len(set(values)) != count or (canonical and values != sorted(values))):
        _fail('NUMBERS')
    return values


def _numbers(text, count, limit, *, canonical=True):
    if not re.fullmatch(r'[0-9]{1,2}(?:\s+[0-9]{1,2}){' + str(count - 1) + '}', text):
        _fail('NUMBER_LEXEMES')
    return _zone([int(n) for n in text.split()], count, limit, canonical=canonical)


def _rows(table, parents):
    return [n for n in table.iter('tr')
            if next((p for p in _ancestors(parents.get(n), parents) if p.tag == 'table'), None) is table]


def _cells(row, parents, count):
    cells = [n for n in row if n.tag in ('td', 'th')]
    if len(cells) != count or len([n for n in row if isinstance(n.tag, str)]) != count:
        _fail('ROW_CELLS')
    for cell in cells:
        if ('colspan' in cell.attrib or 'rowspan' in cell.attrib or
                any(n.tag in _STRUCTURAL for n in cell.iter() if n is not cell)):
            _fail('NESTED_OR_MERGED_CELLS')
        _text(cell, parents)
    return cells


def _unique_records(records):
    if (len({r['issue'] for r in records}) != len(records) or
            len({r['detail_url'] for r in records}) != len(records)):
        _fail('DUPLICATE_IDENTITY')


def parse_index_page(raw: bytes, source_url: str) -> dict:
    """Return publication-only canonical records and byte-derived pagination."""
    source = _url(source_url)
    root, parents = _dom(raw)
    tables = []
    for table in root.iter('table'):
        if not _eligible(table, parents):
            continue
        rows = _rows(table, parents)
        if rows and [_compact(c, parents) for c in rows[0] if c.tag in ('td', 'th')] == ['发布日期', '期号', '开奖号码', '详细']:
            tables.append(table)
    table = _one(tables, 'INDEX_SCHEMA')
    rows = _rows(table, parents)
    _cells(rows[0], parents, 4)
    paging = _one([n for n in root.iter() if 'data-sum' in n.attrib and _eligible(n, parents)], 'INDEX_PAGINATION')
    if _unsafe(paging, parents):
        _fail('HIDDEN_OR_INERT_EVIDENCE')
    attrs = paging.attrib
    if any(not re.fullmatch(r'[1-9][0-9]*', attrs.get(k, '')) for k in ('data-sum', 'data-pageindex', 'data-size')):
        _fail('INDEX_PAGINATION')
    total, page_index, page_size = (int(attrs[k]) for k in ('data-sum', 'data-pageindex', 'data-size'))
    query = parse_qs(source.query, keep_blank_values=True)
    # A bare endpoint is allowed for local callers. If pagination is supplied,
    # it must identify the retained page exactly and without repeated values.
    for key, expected_value in (('pageIndex', page_index), ('pageSize', page_size)):
        if key in query and query[key] != [str(expected_value)]:
            _fail('INDEX_PAGE_URL_MISMATCH')
    sha = hashlib.sha256(raw).hexdigest()
    records = []
    for row in rows[1:]:
        cells = _cells(row, parents, 4)
        publication, issue, numbers, label = [_text(c, parents) for c in cells]
        _iso(publication, 'INDEX_PUBLICATION_DATE')
        if not re.fullmatch(r'[0-9]{5}', issue):
            _fail('ISSUE')
        lexemes = numbers.split()
        if len(lexemes) != 7:
            _fail('NUMBER_LEXEMES')
        front = _numbers(' '.join(lexemes[:5]), 5, 35)
        back = _numbers(' '.join(lexemes[5:]), 2, 12)
        anchors = list(row.iter('a'))
        anchor = _one(anchors, 'INDEX_DETAIL_ANCHOR')
        if anchor not in list(cells[3].iter()) or label != '详细' or _text(anchor, parents) != '详细':
            _fail('INDEX_DETAIL_ANCHOR')
        href = anchor.attrib.get('href', '')
        url = _ORIGIN + href if href.startswith('/cms/post-') else href
        _url(url, detail=True)
        records.append({'issue': issue, 'index_publication_date': publication,
                        'front': front, 'back': back, 'detail_url': url,
                        'index_raw_sha256': sha})
    if not records or len(records) > page_size or page_index > (total + page_size - 1) // page_size:
        _fail('INDEX_PAGE_COUNT')
    _unique_records(records)
    return {'raw_sha256': sha, 'declared_total': total, 'records': records,
            'page_index': page_index, 'page_size': page_size, **_metadata()}


def build_inventory(pages: list[dict]) -> dict:
    """Require every declared page and row; never silently drop a bad row."""
    if not isinstance(pages, list) or not pages:
        _fail('INDEX_SCOPE_EMPTY')
    parsed = []
    for page in pages:
        if not isinstance(page, dict) or 'raw_bytes' not in page or 'source_url' not in page:
            _fail('INDEX_PAGE_INPUT')
        parsed.append(parse_index_page(page['raw_bytes'], page['source_url']))
    if len({p['declared_total'] for p in parsed}) != 1 or len({p['page_size'] for p in parsed}) != 1:
        _fail('INDEX_SCOPE_CONFLICT')
    total, size = parsed[0]['declared_total'], parsed[0]['page_size']
    count = (total + size - 1) // size
    if sorted(p['page_index'] for p in parsed) != list(range(1, count + 1)):
        _fail('INDEX_SCOPE_PAGES')
    for page in parsed:
        expected_count = min(size, total - (page['page_index'] - 1) * size)
        if len(page['records']) != expected_count:
            _fail('INDEX_SCOPE_ROWS')
    records = [record for page in parsed for record in page['records']]
    _unique_records(records)
    if len(records) != total:
        _fail('INDEX_SCOPE_TOTAL')
    parsed.sort(key=lambda p: p['page_index'])
    return {'records': sorted(records, key=lambda r: int(r['issue'])),
            'declared_total': total,
            'index_raw_sha256s': [p['raw_sha256'] for p in parsed],
            'pages': [{'page_index': p['page_index'], 'page_size': size,
                       'raw_sha256': p['raw_sha256'], 'record_count': len(p['records'])} for p in parsed],
            **_metadata()}


def parse_detail(raw: bytes, expected: dict) -> dict:
    """Bind explicit draw date and winning cells to one indexed announcement."""
    if (not isinstance(expected, dict) or not isinstance(expected.get('issue'), str) or
            not re.fullmatch(r'[0-9]{5}', expected['issue'])):
        _fail('EXPECTED_RECORD')
    _url(expected.get('detail_url'), detail=True)
    _iso(expected.get('index_publication_date'), 'INDEX_PUBLICATION_DATE')
    if not re.fullmatch(r'[0-9a-f]{64}', str(expected.get('index_raw_sha256', ''))):
        _fail('EXPECTED_INDEX_HASH')
    front = _zone(expected.get('front'), 5, 35)
    back = _zone(expected.get('back'), 2, 12)
    root, parents = _dom(raw)
    body = _one([n for n in root.iter('div') if 'content-text-area' in n.attrib.get('class', '').split()
                 and _eligible(n, parents)], 'DETAIL_BODY')
    if _unsafe(body, parents):
        _fail('HIDDEN_OR_INERT_EVIDENCE')
    wrapper = parents.get(body)
    if wrapper is None or wrapper.tag in ('body', 'html'):
        _fail('ARTICLE_WRAPPER')
    title = _one([n for n in wrapper.iter('h1') if _eligible(n, parents)], 'ARTICLE_TITLE')
    if title in set(body.iter()):
        _fail('ARTICLE_TITLE_IN_BODY')
    title_text = _compact(title, parents)
    family = _one([f for f in _TITLE_FAMILIES if title_text == f + '第' + expected['issue'] + '期开奖公告'], 'ARTICLE_TITLE_MISMATCH')
    # Hidden copies of semantic fields cannot disappear during text filtering.
    for node in body.iter():
        blocked = any(n.tag in _INERT or _hidden(n) for n in _ancestors(node, parents))
        if blocked and any(marker in ''.join(node.itertext()) for marker in ('开奖日期', *_WIN_LABELS, '出球顺序', '前区', '后区')):
            _fail('HIDDEN_OR_INERT_EVIDENCE')
    body_text = _text(body, parents, strict=False, boundaries=True)
    if body_text.count('开奖日期') != 1:
        _fail('DRAW_DATE_COUNT')
    matches = re.findall(r'开奖日期\s*[：:]\s*([0-9]{4})年\s*([0-9]{1,2})月\s*([0-9]{1,2})日', body_text)
    year, month, day = _one(matches, 'DRAW_DATE_FORMAT')
    try:
        draw_date = date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        _fail('DRAW_DATE_INVALID')
    publications = []
    for node in wrapper.iter('li'):
        if node in list(body.iter()) or not _eligible(node, parents):
            continue
        text = _text(node, parents)
        if '发布时间' in text:
            match = re.fullmatch(r'发布时间\s*[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', text)
            if not match:
                _fail('PUBLICATION_DATE_FORMAT')
            publications.append(_iso(match[1], 'PUBLICATION_DATE_INVALID'))
    publication = _one(publications, 'PUBLICATION_DATE_COUNT') if publications else None
    candidates = []
    all_winners = []
    all_orders = []
    for table in body.iter('table'):
        if not _eligible(table, parents):
            continue
        rows = _rows(table, parents)
        table_winners, table_orders = [], []
        for position, row in enumerate(rows):
            cells = [c for c in row if c.tag in ('td', 'th')]
            if not cells:
                continue
            label_text = _compact(cells[0], parents)
            label = label_text[:-1] if label_text.endswith(('：', ':')) else label_text
            if label in _WIN_LABELS:
                table_winners.append((position, row, label))
            elif label == '本期出球顺序':
                table_orders.append((position, row))
        all_winners.extend(table_winners)
        all_orders.extend(table_orders)
        if table_winners:
            if not rows:
                _fail('RESULT_HEADERS')
            header = _cells(rows[0], parents, 3)
            if [_compact(c, parents) for c in header] != ['', '前区', '后区']:
                _fail('RESULT_HEADERS')
            if any(p.tag == 'table' for p in _ancestors(parents.get(table), parents)):
                _fail('NESTED_RESULT_TABLE')
            for extra in rows[1:]:
                if [_compact(c, parents) for c in extra if c.tag in ('td', 'th')] == ['', '前区', '后区']:
                    _fail('DUPLICATE_RESULT_HEADERS')
            candidates.append((table, rows, table_winners, table_orders))
    _one(all_winners, 'WINNING_ROW_COUNT')
    if sum(body_text.count(label) for label in _WIN_LABELS) != 1:
        _fail('WINNING_LABEL_COUNT')
    table, rows, winners, orders = _one(candidates, 'RESULT_TABLE_COUNT')
    if len(all_orders) != len(orders) or len(orders) > 1:
        _fail('ORDER_ROW_COUNT')
    if body_text.count('本期出球顺序') != len(orders):
        _fail('ORDER_LABEL_COUNT')
    position, winning, winning_label = winners[0]
    if position == 0:
        _fail('RESULT_HEADERS')
    cells = _cells(winning, parents, 3)
    found_front = _numbers(_text(cells[1], parents), 5, 35)
    found_back = _numbers(_text(cells[2], parents), 2, 12)
    if found_front != front or found_back != back:
        _fail('INDEX_DETAIL_NUMBERS_MISMATCH')
    order = None
    if orders:
        order_cells = _cells(orders[0][1], parents, 3)
        order = {'front': _numbers(_text(order_cells[1], parents), 5, 35, canonical=False),
                 'back': _numbers(_text(order_cells[2], parents), 2, 12, canonical=False)}
        if set(order['front']) != set(front) or set(order['back']) != set(back):
            _fail('ORDER_NUMBERS_MISMATCH')
    return {'draw': {'issue': expected['issue'], 'draw_date': draw_date,
                     'front': found_front, 'back': found_back},
            'publication_date': publication, 'draw_order': order,
            'detail_raw_sha256': hashlib.sha256(raw).hexdigest(),
            'contract_variant': {'title_family': family, 'winning_label': winning_label}, **_metadata()}
