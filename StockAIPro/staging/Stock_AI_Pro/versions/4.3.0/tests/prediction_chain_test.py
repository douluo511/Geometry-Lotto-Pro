import sys,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.storage as st
import stock_ai.audit as au

def frame():return pd.DataFrame({'code':['000001','000002'],'final_score':[80,70]})

def freeze(data,date):
    with patch.object(st,'ROOT',data):
        return st.freeze_prediction(date,frame(),
            {'balanced':frame(),'offense':frame(),'defense':frame()},
            {'asof':date},{},{},{},False,{}, {}, {}, None)

def save_manifest(folder,manifest):
    (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')

def rejected(data,folder,label):
    ok,msg=au.verify_manifest(folder)
    assert not ok,(label,'audit accepted incomplete payload',msg)
    ok,msg,n=st.verify_prediction_chain(data)
    assert not ok and n==0,(label,'chain accepted incomplete payload',msg,n)

cases=[
    ('missing files',lambda m,p:m.pop('files')),
    ('null files',lambda m,p:m.update(files=None)),
    ('empty files',lambda m,p:m.update(files={})),
    ('list files',lambda m,p:m.update(files=[])),
    ('string files',lambda m,p:m.update(files='invalid')),
    ('missing required offense',lambda m,p:m['files'].pop('portfolio_offense.csv')),
]
for value in [None,1,'','f'*63,'z'*64]:
    cases.append((f'invalid digest {value!r}',
        lambda m,p,value=value:m['files'].update({'predictions.csv':value})))
def traversal(m,p):
    outside=p.parent.parent/'outside.bin';outside.write_bytes(b'actual outside bytes')
    m['files']['../../outside.bin']=hashlib.sha256(outside.read_bytes()).hexdigest()
def absolute(m,p):
    outside=p.parent.parent/'outside.bin';outside.write_bytes(b'actual outside bytes')
    m['files'][str(outside.resolve())]=hashlib.sha256(outside.read_bytes()).hexdigest()
cases.extend([
    ('traversal with correct outside hash',traversal),
    ('absolute with correct outside hash',absolute),
    ('manifest self reference',lambda m,p:m['files'].update({'manifest.json':'f'*64})),
    ('empty filename',lambda m,p:m['files'].update({'':'f'*64})),
    ('invalid NUL path',lambda m,p:m['files'].update({'\x00outside':'f'*64})),
    ('directory payload',lambda m,p:m['files'].update({'directory':'f'*64}) or (p/'directory').mkdir()),
    ('missing physical payload',lambda m,p:(p/'decision.json').unlink()),
    ('payload hash mismatch',lambda m,p:(p/'predictions.csv').write_bytes(b'tampered')),
])
for label,mutate in cases:
    with tempfile.TemporaryDirectory() as td:
        data=Path(td);folder=freeze(data,'2026-09-01')
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        mutate(manifest,folder);save_manifest(folder,manifest)
        rejected(data,folder,label)

for raw in ['[]','null','{malformed JSON']:
    with tempfile.TemporaryDirectory() as td:
        data=Path(td);folder=freeze(data,'2026-09-01')
        (folder/'manifest.json').write_text(raw,encoding='utf-8')
        rejected(data,folder,'malformed top level '+raw)
with tempfile.TemporaryDirectory() as td:
    data=Path(td);folder=freeze(data,'2026-09-01')
    (folder/'manifest.json').unlink()
    rejected(data,folder,'missing manifest must not disappear from chain')

# A valid complete freeze, including uppercase hex, still passes both verifiers.
with tempfile.TemporaryDirectory() as td:
    data=Path(td);folder=freeze(data,'2026-09-01')
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    manifest['files']={name:digest.upper() for name,digest in manifest['files'].items()}
    save_manifest(folder,manifest)
    assert au.verify_manifest(folder)[0]
    assert st.verify_prediction_chain(data)[0]

# Payload integrity alone cannot replace sequence and previous-manifest linkage.
metadata_cases=[
    ('missing sequence',lambda m:m.pop('chain_sequence')),
    ('wrong sequence',lambda m:m.update(chain_sequence=2)),
    ('boolean sequence',lambda m:m.update(chain_sequence=True)),
    ('string sequence',lambda m:m.update(chain_sequence='1')),
    ('missing previous hash',lambda m:m.pop('previous_manifest_sha256')),
    ('wrong previous hash',lambda m:m.update(previous_manifest_sha256='f'*64)),
]
for label,mutate in metadata_cases:
    with tempfile.TemporaryDirectory() as td:
        data=Path(td);folder=freeze(data,'2026-09-01')
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        mutate(manifest);save_manifest(folder,manifest)
        assert au.verify_manifest(folder)[0],(label,'payloads remain intact')
        ok,msg,n=st.verify_prediction_chain(data)
        assert not ok and n==0,(label,msg,n)

with tempfile.TemporaryDirectory() as td:
    data=Path(td);first=freeze(data,'2026-09-01');second=freeze(data,'2026-09-02')
    ok,msg,n=st.verify_prediction_chain(data);assert ok and n==2,msg
    head=json.loads((data/'state'/'prediction_chain.json').read_text(encoding='utf-8'))
    assert head['sequence']==2 and head['head_date']=='2026-09-02'
    # Rebind the old payload's hash: local freeze checks pass but historical
    # manifest bytes change, so the unchanged next-period previous hash fails.
    p=first/'predictions.csv';p.write_bytes(p.read_bytes()+b'\nTAMPER')
    manifest=json.loads((first/'manifest.json').read_text(encoding='utf-8'))
    manifest['files']['predictions.csv']=hashlib.sha256(p.read_bytes()).hexdigest()
    save_manifest(first,manifest)
    assert au.verify_manifest(first)[0] and au.verify_manifest(second)[0]
    ok,msg,n=st.verify_prediction_chain(data)
    assert not ok and n==1 and '哈希链断裂' in msg,(msg,n)
print('PREDICTION PAYLOAD / CROSS-PERIOD HASH CHAIN TEST PASS',
    len(cases)+4+len(metadata_cases),'negative scenarios')
