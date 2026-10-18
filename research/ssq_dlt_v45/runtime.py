"""One bounded Windows/catch-up research cycle. Never buys tickets or grants A."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import uuid

from .store import Store, canonical, digest, parse
from .sources import capture_pair, load_pinned
from . import delivery

JST=timezone(timedelta(hours=9))
BOUNDARY=dict(R2='BLOCKED',formal_A=0,decision='NO_EDGE',repository_independence='FAIL',final_gate='FAIL')
BLOCKERS=['OFFICIAL_EXPLICIT_NEXT_ISSUE_AND_SALE_DEADLINE','01_02_03_04_APPROVAL_AND_KEY_CUSTODY','TRUSTED_PRE_DRAW_TIMESTAMP','ORIGINAL_EIGHT_MODEL_PRODUCERS','ORIGINAL_FORMAL_TWELVE_FAMILY_AND_PROSPECTIVE_REPLICATION']


def latest_due(now):
    if now.tzinfo is None:
        raise ValueError('AWARE_CLOCK_REQUIRED')
    local=now.astimezone(JST)
    for offset in range(8):
        candidate=(local-timedelta(days=offset)).replace(hour=16,minute=0,second=0,microsecond=0)
        if candidate.weekday() in (0,2,5) and candidate<=local:
            return candidate.isoformat()
    raise ValueError('NO_DUE_SLOT')


def render(report):
    pieces=['<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>SSQ＋DLT V4.5</title>',
            '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #bbb;padding:8px;text-align:left}.blocked{color:#a13020}</style>',
            '<h1>SSQ＋DLT V4.5 非正式研究報表</h1>',
            '<p class="blocked">下一合法期：BLOCKED。未取得官方明示期號及截止時間。以下為未綁定期次的研究預覽，不能計為正式事前預測。</p>',
            '<p>formal_A=0 · NO_EDGE · 事前唯一主 D2：固定 R45-PAIRWISE-D2 · 正式 M04/M05-1～5/M06/M07：BLOCKED</p>',
            '<p>排程時槽：'+html.escape(report['due_slot'])+'；報表建立：'+html.escape(report['created_at'])+'</p>']
    for game,data in report['games'].items():
        pieces.append('<h2>'+game+'</h2><p>狀態：'+html.escape(data['status'])+'；官方下一期核驗：BLOCKED</p>')
        if 'preview' not in data:
            pieces.append('<p>'+html.escape(data.get('reason',''))+'</p>'); continue
        pieces.append('<p>歷史截止期：'+html.escape(data['history_last_issue'])+'；歷史 SHA：'+data['history_sha256']+'</p>')
        pieces.append('<table><tr><th>研究模型</th><th>D1–D5</th><th>主 D2</th><th>完整合法單式</th></tr>')
        for name,model in data['preview']['models'].items():
            ds=' / '.join('D'+str(k)+': '+','.join(f'{n:02}' for n in model['dan'][str(k)]) for k in range(1,6))
            ticket=model['ticket']
            pieces.append('<tr><td>'+html.escape(name)+'<br>'+html.escape(model['version'])+'</td><td>'+html.escape(ds)+'</td><td>'+html.escape(str(model['primary_d2']))+'</td><td>'+html.escape(' '.join(f'{n:02}' for n in ticket['front'])+' + '+' '.join(f'{n:02}' for n in ticket['back']))+'</td></tr>')
        pieces.append('</table>')
    pieces.append('<h2>模型與證據狀態</h2><p>公平 D2 基準：SSQ=15/528；DLT=10/595。研究競賽要求同期 Random NULL、固定事前試驗計畫、完整獨立期次及 Holm 校正。未有合格前瞻樣本，維持 NO_EDGE。</p>')
    pieces.append('<p>Replay：BLOCKED（無已核驗目標期凍結）；外部 TSA、正式十二項檢驗、真開機／斷電驗收未完成。</p><ul>')
    pieces.extend('<li>'+html.escape(x)+'</li>' for x in report['blockers'])
    pieces.append('</ul></html>')
    return ''.join(pieces)


def write_report(directory, report):
    directory.mkdir(parents=True,exist_ok=True)
    data=canonical(report).encode('utf-8')
    report_id=hashlib.sha256(data).hexdigest()
    folder=directory/report_id
    def verify_existing():
        if (folder/'report.json').read_bytes()!=data:
            raise ValueError('REPORT_HASH_CONFLICT')
        saved=parse((folder/'SHA256.json').read_bytes())
        if set(saved)!={'report.json','report.html','report.csv'}:
            raise ValueError('REPORT_MANIFEST_INVALID')
        for name,expected in saved.items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('REPORT_ARTIFACT_SHA_MISMATCH')
    if folder.exists():
        verify_existing()
        return folder
    # Unique staging name; concurrent exact retries may race only on rename.
    staging=directory/('.'+uuid.uuid4().hex); staging.mkdir()
    (staging/'report.json').write_bytes(data)
    (staging/'report.html').write_text(render(report),encoding='utf-8')
    stream=io.StringIO(newline=''); writer=csv.writer(stream)
    writer.writerow(['game','model','version','D1','D2','D3','D4','D5','ticket_front','ticket_back','scope','formal_A'])
    for game,value in report['games'].items():
        for name,model in value.get('preview',{}).get('models',{}).items():
            writer.writerow([game,name,model['version'],*[model['dan'][str(k)] for k in range(1,6)],model['ticket']['front'],model['ticket']['back'],'RESEARCH_UNASSIGNED',0])
    (staging/'report.csv').write_text(stream.getvalue(),encoding='utf-8-sig',newline='')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in staging.iterdir()}
    (staging/'SHA256.json').write_text(canonical(manifest),encoding='utf-8')
    try: staging.rename(folder)
    except FileExistsError:
        verify_existing()
        # Preserve redundant staging artifact for diagnosis; never replace output.
    return folder


def run(config, now=None):
    from .models import generate, validate_prediction
    from .replay import replay_ready, write_replay_report
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('AWARE_CLOCK_REQUIRED')
    root=Path(config['state_dir'])
    if not root.is_absolute():
        raise ValueError('ABSOLUTE_STATE_REQUIRED')
    if config.get('formal') or config.get('authorized') or config.get('tsa_verified'):
        raise ValueError('CALLER_BOOLEAN_IS_NOT_AUTHORIZATION')
    store=Store(root/'research.sqlite3')
    slot=latest_due(now)
    report=store.read('cycle',slot)
    reused=report is not None
    if reused:
        for data in report['games'].values():
            if 'preview' in data:
                validate_prediction(data['preview'])
    if report is None:
        report=dict(schema='GLP_V45_RESEARCH_REPORT_1',created_at=now.isoformat(),due_slot=slot,scope='RESEARCH_UNASSIGNED',games={},blockers=BLOCKERS,**BOUNDARY)
        for game in ('SSQ','DLT'):
            try:
                history=load_pinned(game,config['history'][game],now)
                receipts=[]
                if config.get('live_sources',True):
                    recent,receipts=capture_pair(game,root/'sources',now)
                    # Every overlap must agree; no latest-source fallback.
                    cached={r['issue']:r for r in history}
                    for row in recent:
                        if row['issue'] in cached and row!=cached[row['issue']]:
                            raise ValueError('OFFICIAL_VS_PINNED_CONFLICT')
                        cached[row['issue']]=row
                    if int(recent[-1]['issue']) < int(history[-1]['issue']):
                        raise ValueError('OFFICIAL_SOURCE_BEHIND_PINNED_LATEST')
                    history=sorted(cached.values(),key=lambda r:(r['draw_date'],r['issue']))
                preview=generate(game,'UNASSIGNED',history) if config.get('preview',False) else None
                data=dict(status='RESEARCH_UNASSIGNED' if preview else 'BLOCKED',target=None,history_rows=len(history),history_last_issue=history[-1]['issue'],history_sha256=digest(history),receipts=receipts,publication_asof_verified=False)
                if preview: data['preview']=preview
                report['games'][game]=data
            except Exception as exc:
                report['games'][game]=dict(status='BLOCKED',reason=str(exc),error=type(exc).__name__,target=None)
        # A failed attempt must not poison the due slot: the next 30-minute
        # catch-up rereads sources. Only complete research previews are fixed.
        if all(g['status']=='RESEARCH_UNASSIGNED' for g in report['games'].values()):
            try: store.append('cycle',slot,report)
            except ValueError as exc:
                if str(exc)!='IMMUTABLE_CONFLICT': raise
                report=store.read('cycle',slot); reused=True
        else:
            store.append('failed_attempt',uuid.uuid4().hex,report)
    folder=write_report(root/'reports',report)
    outbox_id=None
    if config.get('recipient'):
        outbox_id=delivery.prepare(store,root/'outbox',config['recipient'],report,render(report))
    mail=delivery.flush(store,config.get('smtp'))
    replay=replay_ready(store)
    replay_directory=write_replay_report(root/'replays',replay)
    receipt=dict(run_id=uuid.uuid4().hex,at=now.isoformat(),cycle_sha256=digest(report),reused=reused,report_directory=str(folder),outbox_id=outbox_id,mail=mail,publication='BLOCKED',replay=replay['status'],replay_directory=str(replay_directory),**BOUNDARY)
    store.append('heartbeat',receipt['run_id'],receipt)
    with (root/('run-'+receipt['run_id']+'.json')).open('x',encoding='utf-8') as f:
        json.dump(receipt,f,ensure_ascii=False,indent=2)
    return {**report,'run_receipt':receipt}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args(argv)
    if not args.config.is_absolute():
        parser.error('absolute config path required')
    try:
        result=run(parse(args.config.read_bytes()))
        print(canonical(result['run_receipt']))
        # A bounded research cycle completed; this is not formal publication success.
        return 0 if all(g['status']=='RESEARCH_UNASSIGNED' for g in result['games'].values()) else 2
    except Exception as exc:
        print(canonical(dict(status='FAIL',error=type(exc).__name__,reason=str(exc),**BOUNDARY)))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
