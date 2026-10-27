"""Synthetic response-boundary tests; never official or prospective evidence."""
from __future__ import annotations
import base64
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from research.harness_v46 import official_intake as oi

# Use the original source parser/NetClient in an isolated child, mocking only
# requests.get. A real requests.Response supplies content/json/url behavior.
WORKER = r"""
import json,sys,datetime
from unittest.mock import patch
import requests
from research.harness_v46 import official_intake as oi
scenario=sys.argv[1]; seen=[]
dates=[]; day=datetime.date(2025,1,1)
while len(dates)<120:
    if day.weekday() in (0,2,5): dates.append(day.isoformat())
    day+=datetime.timedelta(days=1)
items=[{'lotteryDrawNum':str(25001+i),'lotteryDrawTime':day,
        'lotteryDrawResult':'01 02 03 04 05 01 02'} for i,day in enumerate(dates)]
def response(url,params,status,ctype,raw):
    r=requests.Response();r.status_code=status;r._content=raw
    r.url=requests.Request('GET',url,params=params).prepare().url
    r.headers['Content-Type']=ctype
    seen.append({'url':r.url,'raw':base64.b64encode(raw).decode('ascii')})
    return r
import base64
def getter(url,*args,params=None,**kwargs):
    if 'sporttery.cn' not in url: raise requests.ConnectionError('synthetic unavailable provincial source')
    if scenario=='no_response': raise requests.ConnectionError('synthetic no response')
    call=len(seen); page=int((params or {}).get('pageNo','1'))
    if scenario=='nonjson' or (scenario=='bad_then_good' and call==0):
        return response(url,params,200,'text/plain;charset=utf-8',b'diagnostic\r\n\xff')
    if scenario=='malformed': return response(url,params,200,'application/json',b'{broken json')
    if scenario=='later_bad' and page==2:
        return response(url,params,200,'application/json',b'{broken second page')
    payload={'success':True,'value':{'list':items[:100] if page==1 else items[100:],
                                    'pages':2,'total':120}}
    return response(url,params,200,'Application/JSON;charset=utf-8',
                    json.dumps(payload,separators=(',',':')).encode())
with patch('requests.get',side_effect=getter),patch('requests.post',side_effect=requests.ConnectionError('synthetic unavailable Gansu JSON')):
    # Remove backoff waits, never the real retry logic or validation.
    sys.path.insert(0,str(oi.REPO_ROOT/'DLT/src'))
    import glp.sources as src
    src.NET.sleeper=lambda seconds:None
    if scenario=='manifest_tamper':
        original=src.fetch_national_history
        def tampered():
            draws,receipt,manifest=original()
            manifest[0]['final_url']=manifest[0]['final_url']+'&invented=1'
            return draws,receipt,manifest
        src.fetch_national_history=tampered
    try: result={'payload':oi._worker('DLT'),'observed':seen}
    except Exception as exc: result={'error':type(exc).__name__+':'+str(exc),'observed':seen}
print(json.dumps(result,ensure_ascii=True))
"""

def original_worker(scenario):
    process=subprocess.run([sys.executable,'-B','-c',WORKER,scenario],
                           cwd=oi.REPO_ROOT,capture_output=True,timeout=60)
    if process.returncode:
        raise AssertionError(process.stderr.decode('utf-8',errors='replace'))
    return json.loads(process.stdout)

class DltResponseCaptureTests(unittest.TestCase):
    def test_returned_200_is_recorded_before_content_type_or_json_validation(self):
        # Mutant: status!=200 capture loses an actual returned diagnostic.
        for ctype,raw in [('text/plain',b'bad\r\n\xff'),
                          ('application/json',b'{invalid'),('',b'')]:
            with self.subTest(ctype=ctype):
                captures=[]
                response=SimpleNamespace(status_code=200,url='https://webapi.sporttery.cn/history?pageNo=1',
                                         headers={'Content-Type':ctype},content=raw)
                fake=SimpleNamespace(get=Mock(return_value=response))
                with patch.dict(sys.modules,{'requests':fake}):
                    oi._install_dlt_redirect_guard('DLT',lambda s,m,b:captures.append((s,m,b)))
                    fake.get('https://webapi.sporttery.cn/history',params={'pageNo':'1'})
                self.assertEqual(len(captures),1)
                source,meta,body=captures[0]
                self.assertEqual(source,'national')
                self.assertEqual(body,raw)
                self.assertEqual(meta['http_status'],200)
                self.assertEqual(meta['content_type'],ctype)
                self.assertEqual(meta['sha256'],hashlib.sha256(raw).hexdigest())

    def test_original_worker_preserves_two_identical_rejected_variant_responses(self):
        data=original_worker('nonjson');payload=data['payload']
        national=next(s for s in payload['sources'] if s['source_id']=='national')
        self.assertEqual(len(data['observed']),2)
        self.assertEqual(len(national['raw_artifacts']),2)
        self.assertEqual([base64.b64decode(a['raw_base64']) for a in national['raw_artifacts']],
                         [b'diagnostic\r\n\xff',b'diagnostic\r\n\xff'])
        self.assertEqual(national['draws'],[])
        self.assertEqual(national['raw_reparse_status'],'NOT_RUN_SOURCE_FETCH_FAILED')
        self.assertIn('Content-Type',national['error'])

    def test_original_worker_keeps_200_json_decode_failure(self):
        data=original_worker('malformed')
        national=next(s for s in data['payload']['sources'] if s['source_id']=='national')
        self.assertEqual(len(national['raw_artifacts']),1)
        self.assertEqual(base64.b64decode(national['raw_artifacts'][0]['raw_base64']),b'{broken json')
        self.assertEqual(national['draws'],[])

    def test_later_page_failure_keeps_both_earlier_and_failed_page(self):
        data=original_worker('later_bad')
        national=next(s for s in data['payload']['sources'] if s['source_id']=='national')
        self.assertEqual(len(national['raw_artifacts']),2)
        self.assertEqual(base64.b64decode(national['raw_artifacts'][-1]['raw_base64']),
                         b'{broken second page')
        self.assertEqual(national['draws'],[])

    def test_success_manifest_does_not_double_count_actual_responses(self):
        data=original_worker('success')
        national=next(s for s in data['payload']['sources'] if s['source_id']=='national')
        self.assertEqual(len(data['observed']),2)
        self.assertEqual(len(national['raw_artifacts']),2)
        self.assertEqual(len(national['draws']),120)
        self.assertEqual(national['raw_reparse_status'],'PASS')

    def test_first_bad_variant_is_retained_even_if_next_variant_fetch_succeeds(self):
        data=original_worker('bad_then_good')
        national=next(s for s in data['payload']['sources'] if s['source_id']=='national')
        self.assertEqual(len(data['observed']),3)
        self.assertEqual(len(national['raw_artifacts']),3)
        self.assertEqual(base64.b64decode(national['raw_artifacts'][0]['raw_base64']),b'diagnostic\r\n\xff')
        # Existing semantic replay stays strict; malformed evidence is not hidden.
        self.assertEqual(national['raw_reparse_status'],'FAIL')
        self.assertIn('RAW_REPARSE_FAILED',national['error'])
        self.assertEqual(data['payload']['status'],'WORKER_FETCH_PARTIAL')

    def test_no_response_does_not_invent_a_body(self):
        data=original_worker('no_response')
        national=next(s for s in data['payload']['sources'] if s['source_id']=='national')
        self.assertEqual(data['observed'],[])
        self.assertEqual(national['raw_artifacts'],[])
        self.assertEqual(national['draws'],[])

    def test_parser_success_manifest_must_match_captured_final_query_url(self):
        data=original_worker('manifest_tamper')
        self.assertIn('DLT_MANIFEST_NOT_BOUND_TO_CAPTURED_RESPONSE',data.get('error',''))

if __name__=='__main__': unittest.main()

