"""Offline TEST_ONLY history and synthetic transport, never source authentication."""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from research.harness_v46 import official_intake as oi
from research.harness_v46 import raw_semantic_replay as replay
from research.harness_v46.audit_intake_bundle import audit_bundle
from research.harness_v46.tests.test_bundle_audit import make_bundle

FIXTURES = Path(__file__).parent / 'fixtures/gansu_post_TEST_ONLY'
URL = 'https://www.gstc.org.cn/workapi/prize_history_list'
FIELDS = ('request_method', 'request_body_base64', 'request_body_sha256')
JSON_TYPES = ('application/json', ' Application/JSON ; Charset=UTF-8 ',
              'APPLICATION/PROBLEM+JSON; CHARSET=UTF-8', ' application/vnd.api+json\t; charset=utf-8')

WORKER = r'''
import sys,json,base64,pathlib
from unittest.mock import patch
import requests
from research.harness_v46 import official_intake as oi
scenario=sys.argv[1]; fixtures=pathlib.Path(sys.argv[2]); seen=[]; html=[]
URL='https://www.gstc.org.cn/workapi/prize_history_list'
def result(raw,status,url,method,body=None):
 r=requests.Response();r.status_code=status;r._content=raw;r.url=url
 r.headers['Content-Type']='application/json' if method=='POST' else 'text/html'
 r.request=requests.Request(method,url,data=body).prepare();return r
def post(url,**kwargs):
 body=kwargs['data'];page=json.loads(body)['page_no'];seen.append(page)
 if scenario=='transport':raise requests.ConnectionError('first unavailable')
 status=503 if scenario=='first503' or (scenario=='later503' and page==2) else 200
 raw=(fixtures/('page_%d.bin'%page)).read_bytes()
 if scenario=='invalid200' or (scenario=='laterbad' and page==2):raw=b'{broken'
 if scenario=='empty200':raw=b''
 if scenario=='forbidden403':status=403;raw=b'Forbidden'
 r=result(raw,status,url,'POST',body)
 if scenario=='redirect':r.status_code=307;r.headers['Location']='https://evil.invalid/body'
 return r
def get(url,*args,**kwargs):
 if 'gstc.org.cn' not in url:raise requests.ConnectionError('synthetic provincial/national unavailable')
 if scenario=='forbidden403':raise requests.ConnectionError('synthetic HTML fallback unavailable')
 html.append(url);p=json.loads((fixtures/'page_1.bin').read_bytes())
 text='<html>'+''.join(row['prize_time']+' '+row['issue_num']+' '+' '.join(row['prize_num'])+'<br>' for row in p['data']['prize_history_list'])+'</html>'
 return result(text.encode(),200,url,'GET')
with patch('requests.get',side_effect=get),patch('requests.post',side_effect=post):
 sys.path.insert(0,str(oi.REPO_ROOT/'DLT/src'));import glp.sources as src
 src.NET.sleeper=lambda _:None
 original=src.fetch_gansu_history_json
 if scenario=='manifest_tamper':
  def fetch(limit=140):
   draws,receipt,manifest=original(limit)
   body=b'{"type_id":"001","page_no":2,"page_size":20}'
   import hashlib
   manifest[0]['request_body_base64']=base64.b64encode(body).decode();manifest[0]['request_body_sha256']=hashlib.sha256(body).hexdigest()
   return draws,receipt,manifest
  src.fetch_gansu_history_json=fetch
 if scenario=='extra_capture':
  def fetch(limit=140):
   requests.post(URL,data=b'{"type_id":"001","page_no":1,"page_size":20}')
   return original(limit)
  src.fetch_gansu_history_json=fetch
 try:out={'payload':oi._worker('DLT'),'posts':seen,'html':html}
 except Exception as exc:out={'error':type(exc).__name__+':'+str(exc),'posts':seen,'html':html}
print(json.dumps(out,ensure_ascii=True))
'''


def worker(scenario):
    process=subprocess.run([sys.executable,'-B','-c',WORKER,scenario,str(FIXTURES)],
                           cwd=oi.REPO_ROOT,capture_output=True,timeout=30)
    if process.returncode:raise AssertionError(process.stderr.decode(errors='replace'))
    return json.loads(process.stdout)


def source_module():
    name = '_gansu_test_glp'
    if name + '.sources' not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, oi.REPO_ROOT / 'DLT/src/glp/__init__.py',
            submodule_search_locations=[str(oi.REPO_ROOT / 'DLT/src/glp')])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        __import__(name + '.sources')
    return sys.modules[name + '.sources']


def response(raw, *, status=200, body=b'{"type_id":"001","page_no":1,"page_size":20}', url=URL):
    result = requests.Response()
    result.status_code, result._content, result.url = status, raw, url
    result.headers['Content-Type'] = 'application/json'
    result.request = requests.Request('POST', url, data=body).prepare()
    return result


def artifact(page, raw=None):
    raw = (FIXTURES / ('page_%d.bin' % page)).read_bytes() if raw is None else raw
    # These request bytes are reconstructed TEST_ONLY, unlike response bytes.
    body = json.dumps({'type_id':'001','page_no':page,'page_size':20}, separators=(',',':')).encode()
    return {'url':URL, 'requested_url':URL, 'raw_sha256':hashlib.sha256(raw).hexdigest(),
            'size_bytes':len(raw), 'content_type':'application/json', 'http_status':200,
            'fetched_at':'2026-10-24T10:56:45+00:00', 'parser_version':oi._expected_parser_version('DLT'),
            'raw_base64':base64.b64encode(raw).decode(), 'request_method':'POST',
            'request_body_base64':base64.b64encode(body).decode(),
            'request_body_sha256':hashlib.sha256(body).hexdigest()}


class GansuPostHistoryTests(unittest.TestCase):
    def parser(self):
        parser = getattr(source_module(), 'parse_gansu_json_page', None)
        self.assertTrue(callable(parser), 'strict literal Gansu JSON parser is missing')
        return parser

    def fetcher(self):
        fetcher = getattr(source_module(), 'fetch_gansu_history_json', None)
        self.assertTrue(callable(fetcher), 'bounded Gansu POST fetcher is missing')
        return fetcher

    def test_seven_preserved_response_pages_reconstruct_literal_140_rows(self):
        parser = self.parser()
        metadata = json.loads((FIXTURES/'metadata.json').read_text())
        rows=[]
        for page in metadata['pages']:
            raw=(FIXTURES/page['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),page['sha256'])
            draws, totals=parser(raw)
            self.assertEqual(totals, {'pages':58, 'total':1145})
            rows.extend(d.to_dict() for d in draws)
        rows.sort(key=lambda row:(row['draw_date'],row['issue']))
        self.assertEqual(len(rows),140)
        self.assertEqual(rows[0],{'issue':'25131','draw_date':'2025-11-17','front':[3,8,25,29,32],'back':[9,12]})
        self.assertEqual(rows[-1],{'issue':'26120','draw_date':'2026-10-21','front':[1,6,10,15,32],'back':[3,4]})
        self.assertEqual(hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest(), metadata['rows_sha256'])

    def test_literal_schema_rejects_coercion_duplicate_keys_and_inferred_dates(self):
        parser=self.parser(); original=json.loads((FIXTURES/'page_1.bin').read_bytes())
        variants=[]
        for field,value in [('prize_time','2026-10-21T00:00:00'),('prize_time','2026-02-30'),('issue_num',26120),('issue_num',True),('prize_num',[1,6,10,15,32,3,4]),('prize_num',['06','01','10','15','32','03','04'])]:
            obj=copy.deepcopy(original);obj['data']['prize_history_list'][0][field]=value;variants.append(json.dumps(obj).encode())
        for field in ('prize_time','issue_num','prize_num'):
            obj=copy.deepcopy(original);del obj['data']['prize_history_list'][0][field];variants.append(json.dumps(obj).encode())
        obj=copy.deepcopy(original);obj['data']['prize_history_list'][1]=obj['data']['prize_history_list'][0];variants.append(json.dumps(obj).encode())
        obj=copy.deepcopy(original);obj['data']['total_page_count']=True;variants.append(json.dumps(obj).encode())
        variants.extend([b'{"code":"000000","code":"999999","data":{}}',b'{broken',b''])
        for raw in variants:
            with self.subTest(raw=raw[:60]),self.assertRaises(source_module().SourceError): parser(raw)

    def test_fetch_uses_exact_fixed_requests_and_full_seven_pages(self):
        fetch=self.fetcher(); observed=[]
        def post(url, **kwargs):
            body=kwargs['data']; observed.append((url,body,kwargs['allow_redirects']))
            page=len(observed)
            return response((FIXTURES/('page_%d.bin'%page)).read_bytes(),body=body)
        with patch('requests.post',side_effect=post): draws,receipt,manifest=fetch()
        self.assertEqual((len(draws),receipt.draw_count,len(manifest)),(140,140,7))
        self.assertEqual([json.loads(body) for _,body,_ in observed],[{'type_id':'001','page_no':p,'page_size':20} for p in range(1,8)])
        self.assertTrue(all(url==URL and redirects is False for url,_,redirects in observed))
        for entry,(_,body,_) in zip(manifest,observed):
            self.assertEqual(entry['request_method'],'POST')
            self.assertEqual(base64.b64decode(entry['request_body_base64']),body)
            self.assertEqual(entry['request_body_sha256'],hashlib.sha256(body).hexdigest())
        for limit in (True,10,21,139,141,'140'):
            with self.subTest(limit=limit),self.assertRaises(source_module().SourceError):fetch(limit)

    def test_only_first_transport_or_non200_can_signal_html_fallback(self):
        fetch=self.fetcher(); src=source_module()
        for failure in (requests.ConnectionError('offline'),response(b'no',status=503)):
            with patch('requests.post',side_effect=[failure]),self.assertRaises(src.GansuApiUnavailable):fetch()
        for failure in (response(b''),response(b'{broken'),response(b'{}')):
            with patch('requests.post',return_value=failure),self.assertRaises(src.SourceError) as raised:fetch()
            self.assertNotIsInstance(raised.exception,src.GansuApiUnavailable)
        first=response((FIXTURES/'page_1.bin').read_bytes())
        with patch('requests.post',side_effect=[first,requests.ConnectionError('later')]),self.assertRaises(src.SourceError) as raised:fetch()
        self.assertNotIsInstance(raised.exception,src.GansuApiUnavailable)

    def test_repeated_shifted_short_and_conflicting_pages_fail_closed(self):
        fetch=self.fetcher(); first=(FIXTURES/'page_1.bin').read_bytes(); second=json.loads((FIXTURES/'page_2.bin').read_bytes())
        variants=[first]
        obj=copy.deepcopy(second);obj['data']['total_record_count']='1146';variants.append(json.dumps(obj).encode())
        obj=copy.deepcopy(second);obj['data']['prize_history_list'].pop();variants.append(json.dumps(obj).encode())
        obj=copy.deepcopy(second);obj['data']['prize_history_list'].reverse();variants.append(json.dumps(obj).encode())
        for raw in variants:
            with self.subTest(raw=raw[:50]),patch('requests.post',side_effect=[response(first),response(raw)]),self.assertRaises(source_module().SourceError):fetch()

    def test_missing_issue_within_page_is_not_accepted_as_recent_history(self):
        parser=self.parser(); first=json.loads((FIXTURES/'page_1.bin').read_bytes())
        # A descending, otherwise valid page silently skips one issue.
        for row in first['data']['prize_history_list'][1:]:row['issue_num']=str(int(row['issue_num'])-1)
        with self.assertRaises(source_module().SourceError):parser(json.dumps(first).encode())

    def test_shifted_page_is_rejected_before_fetching_the_next_page(self):
        second=json.loads((FIXTURES/'page_2.bin').read_bytes())
        for row in second['data']['prize_history_list']:row['issue_num']=str(int(row['issue_num'])-1)
        seen=[]
        def post(url,**kwargs):
            page=json.loads(kwargs['data'])['page_no'];seen.append(page)
            raw=json.dumps(second).encode() if page==2 else (FIXTURES/('page_%d.bin'%page)).read_bytes()
            return response(raw,body=kwargs['data'])
        with patch('requests.post',side_effect=post),self.assertRaises(source_module().SourceError):self.fetcher()()
        self.assertEqual(seen,[1,2],'shifted page was not rejected at its boundary')

    def test_guard_captures_every_post_response_before_validation_and_refuses_redirect(self):
        original=requests.get; original_post=requests.post
        for status,raw in ((200,b'{broken'),(503,b'failed'),(307,b'redirect')):
            captures=[];result=response(raw,status=status);result.headers['Location']='https://evil.invalid/steal'
            try:
                with patch('requests.post',return_value=result) as network:
                    oi._install_dlt_redirect_guard('DLT',lambda s,m,b:captures.append((s,m,b)))
                    if status==307:
                        with self.assertRaises(oi.GateError):requests.post(URL,data=result.request.body,allow_redirects=True)
                    else:requests.post(URL,data=result.request.body,allow_redirects=False)
                    self.assertEqual(network.call_count,1)
                self.assertEqual(len(captures),1,'POST returned body was not preserved')
                source,meta,body=captures[0]
                self.assertEqual((source,body,meta['http_status']),('gansu',raw,status))
                self.assertEqual(meta['request_method'],'POST')
                self.assertEqual(base64.b64decode(meta['request_body_base64']),result.request.body)
                if status==307:self.assertEqual(meta['response_location'],'https://evil.invalid/steal')
            finally:requests.get=original;requests.post=original_post

    def test_post_artifact_request_binding_and_json_downgrade_are_rejected(self):
        valid=artifact(1); source={'source_id':'gansu','source_root':'gstc.org.cn','raw_artifacts':[valid]}
        try:checked=oi._validate_artifacts('DLT',source,valid['parser_version'])
        except oi.GateError as exc:self.fail('valid request-bound POST artifact rejected: '+str(exc))
        self.assertEqual(checked[0]['request_body_sha256'],valid['request_body_sha256'])
        mutations=[]
        for key in FIELDS:
            obj=copy.deepcopy(valid);del obj[key];mutations.append(obj)
        obj=copy.deepcopy(valid)
        for key in FIELDS:del obj[key]
        mutations.append(obj)
        obj=copy.deepcopy(valid);obj['request_method']='GET';mutations.append(obj)
        obj=copy.deepcopy(valid);obj['request_body_sha256']='0'*64;mutations.append(obj)
        obj=copy.deepcopy(valid);obj['url']=obj['requested_url']='https://www.gstc.org.cn/wanfa/dlt_history'
        for key in FIELDS:del obj[key]
        mutations.append(obj)
        obj=copy.deepcopy(valid);body=b'{"type_id":"002","page_no":1,"page_size":20}';obj['request_body_base64']=base64.b64encode(body).decode();obj['request_body_sha256']=hashlib.sha256(body).hexdigest();mutations.append(obj)
        for item in mutations:
            source['raw_artifacts']=[item]
            with self.subTest(item=item.get('request_method')),self.assertRaises(oi.GateError):oi._validate_artifacts('DLT',source,valid['parser_version'])

    def test_raw_replay_requires_exact_page_coverage_without_deduplication(self):
        artifacts=[artifact(p) for p in range(1,8)]
        try:rows=oi._reparse_raw_history('DLT',source_module(),'gansu',artifacts)
        except oi.GateError as exc:self.fail('literal JSON history cannot replay: '+str(exc))
        self.assertEqual((len(rows),rows[-1]['issue']),(140,'26120'))
        for items in (artifacts[:-1],list(reversed(artifacts)),artifacts+[artifacts[0]],artifacts[:1]+artifacts[:1]+artifacts[2:]):
            with self.subTest(count=len(items)),self.assertRaises(oi.GateError):oi._reparse_raw_history('DLT',source_module(),'gansu',items)

    def test_saved_byte_auditor_checks_request_tampering_even_for_failed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,old,_=make_bundle(root)
            # Keep saved response bytes exact while altering only request evidence.
            item=artifact(1);raw=base64.b64decode(item.pop('raw_base64'))
            target=root/'raw/DLT/gansu'/ (item['raw_sha256']+'.bin');target.parent.mkdir();target.write_bytes(raw)
            old_path=root/old['artifact_path'];old_path.unlink()
            item['artifact_path']=target.relative_to(root).as_posix()
            bundle['games']['DLT']['sources']=[{'source_id':'gansu','draws':[],'raw_reparse_status':'NOT_RUN_SOURCE_FETCH_FAILED','raw_artifacts':[item]}]
            (root/'intake.json').write_text(json.dumps(bundle))
            self.assertEqual(audit_bundle(root)['status'],'PASS')
            item['request_body_sha256']='0'*64
            (root/'intake.json').write_text(json.dumps(bundle))
            self.assertEqual(audit_bundle(root)['status'],'FAIL','failed source request tamper escaped byte audit')

    def test_original_worker_uses_post_140_and_real_second_process_replay(self):
        data=worker('good');payload=data['payload'];gansu=payload['sources'][-1]
        self.assertEqual((data['posts'],data['html']),(list(range(1,8)),[]))
        self.assertEqual((len(gansu['draws']),len(gansu['raw_artifacts']),gansu['raw_reparse_status']),(140,7,'PASS'))
        run=subprocess.run([sys.executable,'-B','-m','research.harness_v46.raw_semantic_replay','--game','DLT'],
                           input=json.dumps(payload).encode(),cwd=oi.REPO_ROOT,capture_output=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr.decode(errors='replace'))
        self.assertEqual(json.loads(run.stdout)['verified_source_ids'],['gansu'])
        checked=oi.validate_worker_payload(payload)
        with tempfile.TemporaryDirectory() as tmp:
            bundle={'schema':'V47-OFFICIAL-INTAKE-BUNDLE-1','games':{'DLT':checked},'errors':{},'formal_A':0,
                    'decision':'NO_EDGE','official_target_admission':'BLOCKED','external_tsa':'NOT_RUN'}
            path=oi.write_bundle(bundle,Path(tmp)/'saved')
            self.assertEqual(audit_bundle(path.parent)['verified_artifact_records'],7)
            saved=json.loads(path.read_text(encoding='utf-8'));item=saved['games']['DLT']['sources'][-1]['raw_artifacts'][0]
            self.assertTrue(all(key in item for key in FIELDS))

    def test_original_worker_narrow_fallback_keeps_failure_and_original_html20(self):
        for scenario,count in (('first503',2),('transport',1)):
            data=worker(scenario);payload=data['payload'];gansu=payload['sources'][-1]
            self.assertEqual((data['posts'],len(data['html'])),([1],1))
            self.assertEqual((len(gansu['draws']),len(gansu['raw_artifacts']),gansu['raw_reparse_status']),(20,count,'PASS'))
            checked=oi.validate_worker_payload(payload)
            self.assertIn('api_fallback_error',checked['sources'][-1],'fallback transport diagnostic lost during handoff')

    def test_original_worker_retains_invalid_or_later_failed_pages_without_html(self):
        for scenario,count in (('invalid200',1),('empty200',1),('laterbad',2),('later503',2),('redirect',1)):
            data=worker(scenario);gansu=data['payload']['sources'][-1]
            self.assertEqual(data['html'],[])
            self.assertEqual((gansu['draws'],len(gansu['raw_artifacts'])),([],count))
            self.assertEqual(gansu['raw_reparse_status'],'NOT_RUN_SOURCE_FETCH_FAILED')

    def test_original_worker_cannot_bind_a_different_request_or_dedup_extra_post(self):
        data=worker('manifest_tamper')
        self.assertIn('DLT_MANIFEST_NOT_BOUND_TO_CAPTURED_RESPONSE',data.get('error',''))
        data=worker('extra_capture');gansu=data['payload']['sources'][-1]
        self.assertEqual(len(gansu['raw_artifacts']),8)
        self.assertEqual(gansu['raw_reparse_status'],'FAIL')

    def test_second_process_validates_failed_source_post_request_metadata(self):
        payload=worker('invalid200')['payload'];gansu=payload['sources'][-1]
        gansu['raw_artifacts'][0]['request_body_sha256']='0'*64
        with self.assertRaisesRegex(oi.GateError,'RAW_POST_REQUEST_BYTES_INVALID'):
            replay.verify_sources(payload,source_module())

    def test_empty_and_nonjson_failed_post_cannot_downgrade_at_parent_handoff(self):
        for scenario,raw in (('empty200',b''),('forbidden403',b'Forbidden')):
            original=worker(scenario)['payload']
            checked=oi.validate_worker_payload(original)
            self.assertEqual(checked['status'],'SOURCE_FETCH_PARTIAL')
            self.assertEqual(base64.b64decode(original['sources'][-1]['raw_artifacts'][0]['raw_base64']),raw)
            for content_type in JSON_TYPES:
                payload=copy.deepcopy(original);item=payload['sources'][-1]['raw_artifacts'][0]
                for field in FIELDS:del item[field]
                item['url']=item['requested_url']='https://www.gstc.org.cn/wanfa/dlt_history'
                item['content_type']=content_type
                with self.subTest(scenario=scenario,content_type=content_type),self.assertRaisesRegex(oi.GateError,'RAW_POST_REQUEST_IDENTITY_INVALID'):
                    oi.validate_worker_payload(payload)

    def test_saved_empty_and_nonjson_failed_post_cannot_downgrade_to_legacy_html(self):
        for scenario in ('empty200','forbidden403'):
            checked=oi.validate_worker_payload(worker(scenario)['payload'])
            with tempfile.TemporaryDirectory() as tmp:
                bundle={'schema':'V47-OFFICIAL-INTAKE-BUNDLE-1','games':{'DLT':checked},'errors':{},'formal_A':0,
                        'decision':'NO_EDGE','official_target_admission':'BLOCKED','external_tsa':'NOT_RUN'}
                path=oi.write_bundle(bundle,Path(tmp)/'saved')
                self.assertEqual(audit_bundle(path.parent)['status'],'PASS')
                original=json.loads(path.read_text(encoding='utf-8'))
                for content_type in JSON_TYPES:
                    saved=copy.deepcopy(original);item=saved['games']['DLT']['sources'][-1]['raw_artifacts'][0]
                    for field in FIELDS:del item[field]
                    item['url']=item['requested_url']='https://www.gstc.org.cn/wanfa/dlt_history'
                    item['content_type']=content_type
                    path.write_text(json.dumps(saved),encoding='utf-8')
                    with self.subTest(scenario=scenario,content_type=content_type):
                        result=audit_bundle(path.parent)
                        self.assertEqual(result['status'],'FAIL','failed JSON response lost POST identity while keeping its bytes/SHA')
                        self.assertTrue(any('RAW_ARTIFACT_POST_REQUEST_INVALID' in error for error in result['errors']))
                        self.assertEqual(hashlib.sha256((path.parent/item['artifact_path']).read_bytes()).hexdigest(),item['raw_sha256'])

    def test_saved_html_artifact_rejects_orphan_response_location_like_parent(self):
        original=worker('transport')['payload']
        checked=oi.validate_worker_payload(original)
        for location in ('https://www.gstc.org.cn/redirect', ['malformed']):
            payload=copy.deepcopy(original);payload['sources'][-1]['raw_artifacts'][0]['response_location']=location
            with self.assertRaisesRegex(oi.GateError,'RAW_POST_RESPONSE_LOCATION_INVALID'):
                oi.validate_worker_payload(payload)
            with tempfile.TemporaryDirectory() as tmp:
                bundle={'schema':'V47-OFFICIAL-INTAKE-BUNDLE-1','games':{'DLT':checked},'errors':{},'formal_A':0,
                        'decision':'NO_EDGE','official_target_admission':'BLOCKED','external_tsa':'NOT_RUN'}
                path=oi.write_bundle(bundle,Path(tmp)/'saved')
                self.assertEqual(audit_bundle(path.parent)['status'],'PASS')
                saved=json.loads(path.read_text(encoding='utf-8'))
                saved['games']['DLT']['sources'][-1]['raw_artifacts'][0]['response_location']=location
                path.write_text(json.dumps(saved),encoding='utf-8')
                with self.subTest(location=location):
                    self.assertEqual(audit_bundle(path.parent)['status'],'FAIL','orphan redirect metadata escaped saved-byte validation')
