"""Official-byte research adapters. Observed time is never historical availability."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
from pathlib import Path
import re

from research.ssq_dlt_d2_v44.network import fetch_official
from .store import parse

RULES = {'SSQ': (6,33,1,16), 'DLT': (5,35,2,12)}
URLS = {
    'SSQ': (
        'https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq&issueCount=100',
        'https://www.swlc.net.cn/lottery/ssq.html'),
    'DLT': (
        'https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&provinceId=0&pageSize=100&isVerify=1&pageNo=1',
        'https://api.js-lottery.com/wfzq/dlt/data')}


def validate_history(game, rows, now):
    if game not in RULES or now.tzinfo is None or not isinstance(rows,list) or not rows:
        raise ValueError('INVALID_HISTORY_OR_CLOCK')
    today = now.astimezone(timezone(timedelta(hours=8))).date()
    fc, fn, bc, bn = RULES[game]
    result, seen = [], set()
    for row in rows:
        issue, day = row.get('issue'), row.get('draw_date', row.get('date'))
        if not isinstance(issue,str) or not re.fullmatch(r'[0-9]{5,7}',issue) or issue in seen:
            raise ValueError('DUPLICATE_OR_INVALID_ISSUE')
        if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or date.fromisoformat(day) >= today:
            raise ValueError('F01_FUTURE_OR_INTRADAY_UNPROVEN_DRAW')
        for field,count,upper in (('front',fc,fn),('back',bc,bn)):
            nums = row.get(field)
            if type(nums) is not list or len(nums)!=count or len(set(nums))!=count or any(type(x) is not int or not 1<=x<=upper for x in nums):
                raise ValueError('INVALID_DRAW_NUMBERS')
        result.append(dict(game=game,issue=issue,draw_date=day,front=sorted(row['front']),back=sorted(row['back'])))
        seen.add(issue)
    result.sort(key=lambda r:(r['draw_date'],r['issue']))
    if any(int(a['issue']) >= int(b['issue']) for a,b in zip(result,result[1:])):
        raise ValueError('ISSUE_CHRONOLOGY')
    return result


def agree(game, left, right):
    # Validation of individual rows is performed at the caller's frozen clock.
    a, b = {x['issue']:x for x in left}, {x['issue']:x for x in right}
    if len(a)!=len(left) or len(b)!=len(right) or not a or not b:
        raise ValueError('DUPLICATE_OR_EMPTY_SOURCE')
    if max(a,key=int)!=max(b,key=int):
        raise ValueError('SOURCE_LATEST_ISSUE_DISAGREEMENT')
    common = set(a)&set(b)
    for issue in common:
        if any(a[issue][k]!=b[issue][k] for k in ('front','back','draw_date')):
            raise ValueError('OFFICIAL_SOURCE_CONFLICT')
    return sorted([a[i] for i in common],key=lambda r:(r['draw_date'],r['issue']))


def parse_original(game, source_index, raw, now):
    rows=[]
    if source_index==0:
        doc=parse(raw)
        if game=='SSQ':
            if doc.get('state') != 0:
                raise ValueError('OFFICIAL_API_ERROR')
            for r in doc['result']:
                rows.append(dict(issue=r['code'],draw_date=r['date'][:10],front=[int(x) for x in r['red'].split(',')],back=[int(r['blue'])]))
        else:
            if doc.get('success') is not True:
                raise ValueError('OFFICIAL_API_ERROR')
            for r in doc['value']['list']:
                nums=[int(x) for x in r['lotteryDrawResult'].split()]
                rows.append(dict(issue=r['lotteryDrawNum'],draw_date=r['lotteryDrawTime'],front=nums[:5],back=nums[5:]))
    else:
        text=raw.decode('utf-8')
        if game=='SSQ':
            # Bind balls to the exact third/fourth cells. Other cells contain
            # sales/prize integers and must never enter the number parser.
            for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',text,re.I|re.S):
                cells=re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.I|re.S)
                clean=lambda v: html.unescape(re.sub(r'<[^>]+>',' ',v)).strip()
                if not cells or not re.fullmatch(r'20\d{5}',clean(cells[0])):
                    continue
                if len(cells)<4 or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}(?:\([^)]*\))?',clean(cells[1])):
                    raise ValueError('OFFICIAL_HTML_PARTIAL_PARSE')
                front_text,back_text=clean(cells[2]),clean(cells[3])
                if re.fullmatch(r'\d{12}',front_text):
                    front=[int(front_text[i:i+2]) for i in range(0,12,2)]
                elif re.fullmatch(r'\d{1,2}(?:\s+\d{1,2}){5}',front_text):
                    front=[int(x) for x in front_text.split()]
                else:
                    raise ValueError('OFFICIAL_HTML_BALL_CELL')
                if not re.fullmatch(r'\d{1,2}',back_text):
                    raise ValueError('OFFICIAL_HTML_BALL_CELL')
                rows.append(dict(issue=clean(cells[0]),draw_date=clean(cells[1])[:10],front=front,back=[int(back_text)]))
            if not rows:
                raise ValueError('OFFICIAL_HTML_PARTIAL_PARSE')
        else:
            anchors=re.findall(r'<tr[^>]*>\s*<td[^>]*>\s*\d{4}-\d{2}-\d{2}',text,re.I)
            matches=list(re.finditer(r'<tr[^>]*>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*<td[^>]*>\s*(\d{5})\s*</td>\s*<td[^>]*>\s*([\d\s]+?)\s*</td>',html.unescape(text),re.I|re.S))
            if len(matches)!=len(anchors) or not matches:
                raise ValueError('OFFICIAL_HTML_PARTIAL_PARSE')
            for m in matches:
                nums=[int(x) for x in m[3].split()]
                rows.append(dict(issue=m[2],draw_date=m[1],front=nums[:5],back=nums[5:]))
    return validate_history(game,rows,now)


def capture_pair(game, directory, now):
    from concurrent.futures import ThreadPoolExecutor
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    def fetch(item):
        index,url=item
        raw,receipt=fetch_official(game,url,timeout=5,attempts=2)
        path=directory/(receipt['sha256']+'.bin')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['sha256']:
                raise ValueError('CAPTURE_SHA_MISMATCH')
        else:
            with path.open('xb') as f:
                f.write(raw)
        return parse_original(game,index,raw,now),receipt
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(fetch,enumerate(URLS[game])))
    history=agree(game,values[0][0],values[1][0])
    return history,[x[1] for x in values]


def load_pinned(game, spec, now):
    path=Path(spec['path'])
    if not path.is_absolute():
        raise ValueError('ABSOLUTE_HISTORY_REQUIRED')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec['sha256']:
        raise ValueError('HISTORY_SHA_MISMATCH')
    document=parse(raw)
    if document.get('game') != game:
        raise ValueError('HISTORY_GAME_MISMATCH')
    return validate_history(game,document['draws'],now)
