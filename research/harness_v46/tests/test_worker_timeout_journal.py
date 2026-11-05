
"""A real worker kill must retain the completed response callback as diagnostics."""
import base64
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from research.harness_v46 import official_intake as oi
from research.harness_v46.audit_intake_bundle import audit_bundle


BODY = b"completed fixture response\r\n\xff"
FIXTURE = r"""
import hashlib,sys,time
import requests
from research.harness_v46 import official_intake as oi
game=sys.argv[2]
sys.path.insert(0,str(oi.REPO_ROOT/('SSQ/SSQ' if game=='SSQ' else 'DLT/src')))
import glp.sources as source
raw=b'completed fixture response\r\n\xff'
def fetch(record_raw=None):
    if game=='SSQ':
        record_raw({'source':'official_cwl_L0','url':'https://www.cwl.gov.cn/cwl_admin/front/history',
                    'http_status':200,'content_type':'application/octet-stream',
                    'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                    'fetched_at':'2026-11-05T01:00:00Z','parser_version':source.PARSER_VERSION},raw)
    else:
        requests.get('https://webapi.sporttery.cn/gateway/history')
        requests.post(oi.GANSU_JSON_URL,data=b'{"type_id":"001","page_no":1,"page_size":20}')
    time.sleep(30)
def fixture_get(url,*a,**kw):
    r=requests.Response()
    r.url=url
    r.status_code=200
    r._content=raw
    r.headers['Content-Type']='application/octet-stream'
    return r
requests.get=fixture_get
requests.post=fixture_get
source.fetch_national_history=fetch
raise SystemExit(oi.main(sys.argv[1:]))
"""

def frames(raw):
    """Read complete diagnostic frames only, stopping on a missing or torn tail."""
    output = []
    while raw:
        line, sep, body = raw.partition(b"\n")
        prefix, _, header = line.partition(b"\t")
        if not sep or prefix != b"V47_HTTP_RESPONSE":
            break
        meta = json.loads(header)
        size = meta["size_bytes"]
        if len(body) < size:
            break
        output.append((meta, body[:size]))
        raw = body[size:]
    return output


class WorkerTimeoutJournalTests(unittest.TestCase):
    def test_other_stderr_write_cannot_split_a_response_frame(self):
        class SharedStderr(io.BytesIO):
            def write(self, data):
                size = super().write(data)
                if data.startswith(b"V47_HTTP_RESPONSE\t"):
                    super().write(b"another stderr writer\n")
                return size

        stream = SharedStderr()
        raw = b"raw-response\0\xff"
        meta = {"size_bytes": len(raw)}
        oi._worker_http_journal(stream)(meta, raw)
        self.assertEqual(frames(stream.getvalue()), [(meta, raw)])

    def test_journal_reserves_cap_marker_and_keeps_complete_prefix(self):
        stream = io.BytesIO()
        raw = b"data\n\xff"
        meta = {"size_bytes": len(raw)}
        first = io.BytesIO()
        oi._worker_http_journal(first)(meta, raw)
        cap = len(first.getvalue()) + len(b"V47_HTTP_JOURNAL_LIMIT\n")
        record = oi._worker_http_journal(stream, limit=cap)
        for _ in range(3):
            record(meta, raw)
        self.assertEqual(stream.getvalue(), first.getvalue() + b"V47_HTTP_JOURNAL_LIMIT\n")
        self.assertEqual(frames(stream.getvalue()), [(meta, raw)])

    def test_concurrent_frames_and_partial_tail_remain_separable(self):
        stream = io.BytesIO()
        record = oi._worker_http_journal(stream)
        bodies = [bytes([i]) * 8000 for i in range(12)]
        def emit(raw):
            record({"size_bytes": len(raw)}, raw)
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(emit, bodies))
        self.assertCountEqual([body for _, body in frames(stream.getvalue())], bodies)
        self.assertEqual(len(frames(stream.getvalue()[:-1])), len(bodies)-1)

    def test_completed_response_survives_real_timeout_without_admission(self):
        run = subprocess.run
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as directory:
                def launch(command, **kwargs):
                    return run([sys.executable, "-B", "-c", FIXTURE, *command[3:]], **kwargs)
                with patch.object(oi.subprocess, "run", side_effect=launch):
                    result = oi.collect_live_history(game, timeout_seconds=3)
                self.assertEqual(result["status"], "WORKER_OUTPUT_QUARANTINED")
                self.assertEqual(result["official_history_admission"], "BLOCKED")
                self.assertEqual(result["sources"], [])
                capture=result["worker_output_capture"]
                self.assertFalse(capture["capture_complete"])
                stderr = capture["streams"][1]
                self.assertEqual(stderr["capture_status"], "CAPTURED")
                self.assertEqual(stderr["byte_representation"], "ORIGINAL_PIPE_BYTES")
                framed = base64.b64decode(stderr["bytes_base64"])
                entries = frames(framed)
                self.assertEqual(len(entries), 1 if game == "SSQ" else 2)
                meta, body = entries[0]
                self.assertEqual(meta["_source_id"],"national")
                self.assertEqual(meta["size_bytes"],len(BODY))
                self.assertEqual(meta["raw_sha256"],hashlib.sha256(BODY).hexdigest())
                self.assertEqual(body,BODY)
                if game == "DLT":
                    post, body = entries[1]
                    self.assertEqual(post["_source_id"], "gansu")
                    self.assertEqual(post["request_method"], "POST")
                    request = b'{"type_id":"001","page_no":1,"page_size":20}'
                    self.assertEqual(base64.b64decode(post["request_body_base64"]),request)
                    self.assertEqual(post["request_body_sha256"],hashlib.sha256(request).hexdigest())
                    self.assertEqual(body,BODY)
                bundle={"schema":"V47-OFFICIAL-INTAKE-BUNDLE-1","games":{game:result},
                        "official_target_admission":"BLOCKED","external_tsa":"NOT_RUN",
                        "formal_A":0,"decision":"NO_EDGE"}
                root=Path(directory)/"bundle"
                oi.write_bundle(bundle,root)
                audit=audit_bundle(root)
                self.assertEqual(audit["status"],"PASS",audit["errors"])
                self.assertEqual(audit["artifact_records"],0)
                self.assertIn(game,audit["incomplete_worker_output_games"])

if __name__=="__main__":
    unittest.main()

