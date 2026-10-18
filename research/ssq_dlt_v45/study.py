"""One registered retrospective D2 study; never formal historical/as-of evidence.

prepare seals design, split, source code and input bytes before execute scores
any historical outcome. These already-existing data are not a new independent
holdout. A local seal is not a trusted prospective candidate timestamp.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import platform
import sys
import uuid

from .models import DEFAULT_SEED, NULL_MODEL, PRIMARY_MODEL, REGISTRY_SHA256
from .sources import load_pinned
from .store import Store, canonical, digest, parse

MODEL_IDS = ('R45-HOT60','R45-EWMA','R45-SHRINKMIX','R45-PAIRWISE-D2',
             'R45-RANDOM-NULL','R45-PAIR-RESIDUAL')
STAGES = ('development','validation','locked_historical_test')
BOUNDARY = dict(scope='RETROSPECTIVE_RECONSTRUCTION_NOT_ASOF',formal_A=0,
                decision='NO_EDGE',independent_prospective_samples=0,
                historical_availability='BLOCKED_MISSING_PUBLICATION_TIME_PROOF',
                official_next_legal_issue='BLOCKED',repository_independence='FAIL',final_gate='FAIL')
REFERENCES = [
    {'title':'Chronological forecast validation','url':'https://otexts.com/fpp3/tscv.html'},
    {'title':'NIST Wilson and exact binomial intervals','url':'https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm'},
    {'title':'Exact paired binary comparison','url':'https://www.statsmodels.org/dev/generated/statsmodels.stats.contingency_tables.mcnemar.html'},
    {'title':'R Holm adjustment','url':'https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html'}]


def source_hashes():
    base=Path(__file__).resolve().parent
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest()
            for name in ('study.py','study_engine.py','study_stats.py','models.py','sources.py','store.py')}


def _write_new(path, raw):
    with Path(path).open('xb') as f:
        f.write(raw)


def prepare(config, output, *, now=None, warmup=120):
    from .study_stats import power_report
    if type(warmup) is not int or warmup<60:
        raise ValueError('MINIMUM_60_PRIOR_DRAWS_REQUIRED')
    current=now or datetime.now(timezone.utc)
    output=Path(output)
    if not output.is_absolute():
        raise ValueError('ABSOLUTE_STUDY_DIRECTORY_REQUIRED')
    games={}
    for game in ('SSQ','DLT'):
        history=load_pinned(game,config['history'][game],current)
        if len(history)-warmup<20:
            raise ValueError('INSUFFICIENT_HISTORY_FOR_THREE_PARTITIONS')
        eligible=len(history)-warmup
        dev=eligible*3//5
        val=eligible//5
        indices=((warmup,warmup+dev),(warmup+dev,warmup+dev+val),(warmup+dev+val,len(history)))
        stages={name:dict(start=start,stop=stop,n=stop-start,
                          expected_issues=[r['issue'] for r in history[start:stop]],
                          first_date=history[start]['draw_date'],last_date=history[stop-1]['draw_date'])
                for name,(start,stop) in zip(STAGES,indices)}
        games[game]=dict(input_sha256=config['history'][game]['sha256'],n_total=len(history),
                         warmup=warmup,first_issue=history[0]['issue'],last_issue=history[-1]['issue'],stages=stages)
    # No selection/search is performed by preparation. Power is determined from
    # hypothetical marginal probabilities, not from observed study outcomes.
    power=power_report(family_size=10,alpha=.05,power=.8,primary_delta=.01)
    plan=dict(schema='V45_D2_STUDY_PLAN_1',created_at=current.isoformat(),
              local_seal_only=True,model_ids=list(MODEL_IDS),original_registry_sha256=REGISTRY_SHA256,
              primary_model=PRIMARY_MODEL,null_model=NULL_MODEL,seed=DEFAULT_SEED,
              ticket_count_per_model_per_issue=1,d2_size=2,
              code_sha256=source_hashes(),games=games,
              hypotheses={
                  'R45-HOT60':'Last-60 marginal popularity improves D2 over the same-period fixed-seed NULL.',
                  'R45-EWMA':'Fixed half-life20 recency improves D2 over the same-period NULL.',
                  'R45-SHRINKMIX':'The fixed 50/50 marginal mixture improves D2 over the same-period NULL.',
                  'R45-PAIRWISE-D2':'Last-60 raw pair counts improve D2 over the same-period NULL.',
                  'R45-PAIR-RESIDUAL':'Removing count(a)*count(b)/60 from last-60 pair count improves D2 over NULL and reduces marginal-hotness confounding.'},
              improvement_spec=dict(model='R45-PAIR-RESIDUAL',version='1.0.0',window=60,
                    score='count_pair - count_a * count_b / 60',
                    ties=['higher_raw_pair_count','higher_marginal_sum','ascending_pair'],
                    parameter_search=False,predecessor='R45-PAIRWISE-D2',
                    predecessor_contrast='Descriptive rate difference only; not an additional confirmatory hypothesis'),
              family=dict(size=10,alpha=.05,method='Holm',
                    identities=[g+':'+m for g in ('SSQ','DLT') for m in MODEL_IDS if m!=NULL_MODEL],
                    outcome='both predicted front-area numbers occur in the draw',
                    primary_endpoint='one pre-fixed D2 per model per draw',
                    primary_inference_stage='locked_historical_test',
                    assumptions='Paired exact and interval calculations assume IID pairs; adaptive joint-pair dependence is not established.'),
              secondary_inference='Fixed-lambda fair-null mixture e-process, separate globally adjusted family; never used to choose a different winner.',
              challenger_selection=dict(stage='validation',criterion='largest positive paired_delta_vs_null',
                    ties=list(MODEL_IDS),automatic_primary_replacement=False),
              stopping_rule='One final historical analysis after every planned issue; no outcome-driven extension, seed change, or repeated fitting to this audit-test.',
              future_trial=dict(status='BLOCKED_NOT_STARTED',expected_issues=None,accepted_samples=0,
                    required_effect_absolute=.01,target_power=.8,
                    planned_n_approx_per_game={g:max(s['n_approx'] for s in p['sample_size_scenarios'] if s['primary_specification']) for g,p in power['games'].items()},
                    enrollment='Requires explicit official issue/deadline, authority, external pre-draw seal and an independent new registered issue cohort.',
                    stopping='Fixed N final analysis. Missing issues block completion; no early winner selection.'),
              power=power,method_references=REFERENCES,**BOUNDARY)
    output.mkdir(parents=True,exist_ok=False)
    raw=canonical(plan).encode('utf-8')
    _write_new(output/'plan.json',raw)
    _write_new(output/'plan.sha256',(digest(plan)+'\n').encode('ascii'))
    Store(output/'study.sqlite3').append('study_plan',digest(plan),plan)
    return plan


def _load_registered(output):
    plan=parse((output/'plan.json').read_bytes())
    expected=(output/'plan.sha256').read_text('ascii').strip()
    if digest(plan)!=expected or canonical(plan).encode()!=(output/'plan.json').read_bytes():
        raise ValueError('REGISTERED_PLAN_SHA_MISMATCH')
    if plan['code_sha256']!=source_hashes():
        raise ValueError('STUDY_SOURCE_CHANGED_NEW_DESIGN_REQUIRED')
    if (plan['model_ids']!=list(MODEL_IDS) or plan['primary_model']!=PRIMARY_MODEL
            or plan['null_model']!=NULL_MODEL or plan['seed']!=DEFAULT_SEED
            or plan['family']['size']!=10 or plan['family']['identities']!=
            [g+':'+m for g in ('SSQ','DLT') for m in MODEL_IDS if m!=NULL_MODEL]):
        raise ValueError('REGISTERED_FAMILY_OR_PRIMARY_REPLACED')
    store=Store(output/'study.sqlite3')
    if store.read('study_plan',expected)!=plan:
        raise ValueError('INDEPENDENT_LEDGER_PLAN_MISMATCH')
    return plan,store,expected


def execute(config, output):
    from .study_engine import walk_forward
    from .study_stats import paired_summary, wilson_interval, holm_adjust, fair_null_eprocess
    output=Path(output)
    plan,store,plan_sha=_load_registered(output)
    if store.read('study_started',plan_sha):
        raise ValueError('STUDY_ALREADY_STARTED_REUSE_SAVED_RESULTS_NO_HIDDEN_RETEST')
    histories={}
    for game in ('SSQ','DLT'):
        spec=config['history'][game]
        if spec['sha256']!=plan['games'][game]['input_sha256']:
            raise ValueError('STUDY_INPUT_PIN_CHANGED')
        histories[game]=load_pinned(game,spec,datetime.now(timezone.utc))
        ids=[r['issue'] for r in histories[game]]
        gp=plan['games'][game]
        if len(ids)!=gp['n_total']:
            raise ValueError('STUDY_ISSUE_COUNT_CHANGED')
        for stage in gp['stages'].values():
            if ids[stage['start']:stage['stop']]!=stage['expected_issues']:
                raise ValueError('MISSING_DUPLICATE_OR_REPLACED_REGISTERED_ISSUE')
    claim=dict(plan_sha256=plan_sha,at=datetime.now(timezone.utc).isoformat(),run_id=uuid.uuid4().hex)
    if not store.append('study_started',plan_sha,claim):
        raise ValueError('ANALYSIS_ALREADY_CLAIMED')
    summaries=[]
    all_periods=[]
    for game,history in histories.items():
        gp=plan['games'][game]
        periods=walk_forward(game,history,start=gp['warmup'])
        if [r['issue'] for r in periods]!=[r['issue'] for r in history[gp['warmup']:]]:
            raise ValueError('ENGINE_MISSING_PERIODS')
        upper=33 if game=='SSQ' else 35
        for index,row in enumerate(periods,gp['warmup']):
            if (row['game']!=game or row['draw_front']!=history[index]['front']
                    or row['draw_date']!=history[index]['draw_date']
                    or row['training_size']!=index or row['training_end_issue']!=history[index-1]['issue']):
                raise ValueError('ENGINE_DRAW_OR_PREFIX_IDENTITY_MISMATCH')
            for pair in row['predictions'].values():
                if type(pair) is not list or len(pair)!=2 or len(set(pair))!=2 or any(type(v) is not int or not 1<=v<=upper for v in pair):
                    raise ValueError('FIXED_COST_EXACTLY_TWO_NUMBERS_REQUIRED')
        for stage_name,split in gp['stages'].items():
            current=periods[split['start']-gp['warmup']:split['stop']-gp['warmup']]
            null_hits=[int(set(r['predictions'][NULL_MODEL]).issubset(r['draw_front'])) for r in current]
            for row in current:
                if set(row['predictions'])!=set(MODEL_IDS):
                    raise ValueError('MISSING_MODEL_OR_POST_HOC_REPLACEMENT')
                row['stage']=stage_name
                row['full_d2']={m:int(set(pair).issubset(row['draw_front'])) for m,pair in row['predictions'].items()}
                all_periods.append(row)
            for model in MODEL_IDS:
                hits=[r['full_d2'][model] for r in current]
                stat=paired_summary(hits,null_hits)
                p0=15/528 if game=='SSQ' else 10/595
                rate=sum(hits)/len(hits)
                interval=wilson_interval(sum(hits),len(hits))
                record=dict(game=game,stage=stage_name,model=model,n=len(hits),hits=sum(hits),
                    rate=rate,rate_ci95=interval,fair_d2_p0=p0,delta_vs_fair=rate-p0,
                    delta_vs_fair_ci95=[x-p0 for x in interval],null_hits=sum(null_hits),
                    null_rate=sum(null_hits)/len(null_hits),paired=stat,p_holm=None,
                    inference='DESCRIPTIVE_IID_ASSUMPTION_NOT_PROSPECTIVE',
                    **BOUNDARY)
                if model!=NULL_MODEL:
                    record['fair_null_robustness']=fair_null_eprocess(game,
                        [r['predictions'][model] for r in current],
                        [r['predictions'][NULL_MODEL] for r in current],hits,null_hits)
                summaries.append(record)
    tests={r['game']+':'+r['model']:r['paired']['p_one_sided'] for r in summaries
           if r['stage']=='locked_historical_test' and r['model']!=NULL_MODEL}
    if set(tests)!=set(plan['family']['identities']):
        raise ValueError('INCOMPLETE_MULTIPLE_TESTING_FAMILY')
    adjusted=holm_adjust(tests)
    robust_tests={r['game']+':'+r['model']:r['fair_null_robustness']['fixed_final_p_markov'] for r in summaries
           if r['stage']=='locked_historical_test' and r['model']!=NULL_MODEL}
    robust_adjusted=holm_adjust(robust_tests)
    nominations={}
    for game in ('SSQ','DLT'):
        vals=[r for r in summaries if r['game']==game and r['stage']=='validation' and r['model']!=NULL_MODEL]
        best=min(vals,key=lambda r:(-r['paired']['paired_delta'],MODEL_IDS.index(r['model'])))
        nominations[game]=best['model'] if best['paired']['paired_delta']>0 else None
    for r in summaries:
        if r['stage']=='locked_historical_test' and r['model']!=NULL_MODEL:
            key=r['game']+':'+r['model']
            r['p_holm']=adjusted[key]
            r['p_holm_fair_null_robustness']=robust_adjusted[key]
            r['iid_historical_reject_only']=adjusted[key]<=plan['family']['alpha']
            r['meets_prespecified_effect']=r['paired']['paired_delta']>=.01
    result=dict(schema='V45_D2_STUDY_RESULT_1',plan_sha256=plan_sha,
        evaluated_at=datetime.now(timezone.utc).isoformat(),code_sha256=plan['code_sha256'],
        period_rows=len(all_periods),summaries=summaries,nominations_from_validation=nominations,
        frozen_primary=PRIMARY_MODEL,automatic_primary_replacement=False,
        claim_categories=dict(confirmed_improvement='NONE_NO_INDEPENDENT_PROSPECTIVE_EVIDENCE',
            retrospective_comparisons='EXECUTED_CONDITIONAL_RECONSTRUCTION',
            prospective_replication='NOT_RUN_BLOCKED',formal_original_eight='BLOCKED'),
        inference_caveats=['All historical outcomes already existed; the locked slice is not a genuinely new independent holdout.',
            'Per-row historical availability is not proven. Prefix order is a code property, not an as-of certificate.',
            'IID paired p values and intervals are conditional method outputs; adaptive paired dependence is not established.',
            'The secondary e-process requires fair independent draws and genuinely predictable forecasts; retrospective reconstruction does not establish those premises.',
            'No model or parameter is changed after this locked test. Every registered period remains visible.'],
        environment=dict(python=sys.version,os=platform.platform()),**BOUNDARY)
    if source_hashes()!=plan['code_sha256']:
        raise ValueError('STUDY_SOURCE_CHANGED_DURING_EXECUTION')
    _write_new(output/'results.json',canonical(result).encode('utf-8'))
    _write_new(output/'periods.json',canonical(all_periods).encode('utf-8'))
    text=io.StringIO(newline=''); writer=csv.writer(text)
    writer.writerow(['game','stage','issue','draw_date','training_end_issue','training_size','model','D2','draw_front','full_d2','scope'])
    for row in all_periods:
        for model in MODEL_IDS:
            writer.writerow([row['game'],row['stage'],row['issue'],row['draw_date'],row['training_end_issue'],row['training_size'],model,
                ' '.join(f'{n:02}' for n in row['predictions'][model]),' '.join(f'{n:02}' for n in row['draw_front']),row['full_d2'][model],BOUNDARY['scope']])
    _write_new(output/'periods.csv',text.getvalue().encode('utf-8-sig'))
    _write_new(output/'report.html',render(plan,result,all_periods).encode('utf-8'))
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()
              if p.is_file() and p.suffix in ('.json','.html','.csv','.sha256')}
    _write_new(output/'SHA256.json',canonical(manifest).encode())
    store.append('study_completed',plan_sha,dict(plan_sha256=plan_sha,result_sha256=digest(result),
                 periods_sha256=digest(all_periods),manifest=manifest,**BOUNDARY))
    return result


def verify(output):
    output=Path(output)
    plan,store,key=_load_registered(output)
    completed=store.read('study_completed',key)
    if not completed:
        raise ValueError('STUDY_INCOMPLETE')
    manifest=parse((output/'SHA256.json').read_bytes())
    if manifest!=completed['manifest']:
        raise ValueError('STUDY_ARTIFACT_MANIFEST_CHANGED')
    for name,expected in manifest.items():
        if Path(name).name!=name or hashlib.sha256((output/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('STUDY_ARTIFACT_SHA_MISMATCH')
    result=parse((output/'results.json').read_bytes())
    periods=parse((output/'periods.json').read_bytes())
    if digest(result)!=completed['result_sha256'] or digest(periods)!=completed['periods_sha256']:
        raise ValueError('STUDY_RESULT_LEDGER_MISMATCH')
    return dict(status='PASS',plan_sha256=key,periods=len(periods),**BOUNDARY)


def render(plan,result,periods):
    esc=html.escape
    def pct(v): return f'{100*v:.3f}%'
    def ci(v): return f'[{100*v[0]:.3f}, {100*v[1]:.3f}]'
    rows=[]
    for r in result['summaries']:
        paired=r['paired']
        ph='—' if r['p_holm'] is None else f"{r['p_holm']:.4g}"
        robust='—' if 'p_holm_fair_null_robustness' not in r else f"{r['p_holm_fair_null_robustness']:.4g}"
        rows.append(f'<tr data-game="{r["game"]}" data-stage="{r["stage"]}"><td>{esc(r["model"])}</td><td>{r["hits"]}/{r["n"]}</td><td>{pct(r["rate"])}</td><td>{ci(r["rate_ci95"])}</td><td>{100*r["delta_vs_fair"]:+.3f}</td><td>{100*paired["paired_delta"]:+.3f}</td><td>{ci(paired["paired_delta_ci"])}</td><td>{ph}</td><td>{robust}</td></tr>')
    split_rows=''.join(f'<tr><td>{g}</td><td>{s}</td><td>{x["n"]}</td><td>{x["expected_issues"][0]}–{x["expected_issues"][-1]}</td></tr>'
                       for g,p in plan['games'].items() for s,x in p['stages'].items())
    ref=''.join(f'<li><a href="{esc(r["url"],quote=True)}">{esc(r["title"])}</a></li>' for r in REFERENCES)
    data=json.dumps(periods,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    nominations=esc(canonical(result['nominations_from_validation']))
    power=esc(json.dumps(plan['power'],ensure_ascii=False,indent=2))
    power_rows=''.join(f'<tr><td>{g}</td><td>{p["stages"]["locked_historical_test"]["n"]}</td><td>{plan["future_trial"]["planned_n_approx_per_game"][g]}</td></tr>' for g,p in plan['games'].items())
    return '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SSQ＋DLT V4.5 D2 比較研究</title>
<style>body{font:15px/1.65 system-ui,sans-serif;max-width:1450px;margin:28px auto;padding:0 22px;color:#182d3d;background:#f5f7f9}h1,h2{line-height:1.3}.notice{background:#fff0dc;border-left:5px solid #b56313;padding:16px}section{background:white;border:1px solid #dbe2e7;border-radius:8px;padding:20px;margin:18px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:9px;border-bottom:1px solid #dbe2e7;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#edf2f6}select,input,button{padding:8px;margin:6px}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}.muted{color:#536878}a{color:#155da1}strong{color:#8f3811}</style>
<h1>SSQ＋DLT V4.5：唯一 D2 全中率比較</h1><div class="notice"><strong>尚無證據證明提高命中率 · A=0 · NO_EDGE</strong><br>本次為歷史資料按時間向前重建。最後一段為本次程式鎖定的歷史稽核區，並非獨立前瞻樣本。歷史可用時間、官方下一合法期、正式批准及可信事前封存仍 BLOCKED。</div>
<section><h2>本次已執行與尚未執行</h2><p>已執行：五個既有研究模型／基準與一個固定改進候選的逐期比較；每模型每期只預測同一組兩膽，不增加注數。正式八槽未替換。主模型固定 R45-PAIRWISE-D2。</p><p>改進假設：把最近60期的原始配對次數，扣除 count(a)×count(b)/60，檢查去除熱門單號效應後是否更好。只測這個公式，沒有窗口、權重或種子搜尋。</p><p>未執行：新前瞻獨立期次、正式十二項檢驗與正式模型批准。歷史結果不能用來宣告未來優勢。</p><p>驗證段依事前規則選出的研究提名：<code>'''+nominations+'''</code>。此提名不更換既有主模型，亦不等於通過新前瞻驗證。</p></section>
<section><h2>模型比較</h2><label>彩種 <select id="game"><option>SSQ</option><option>DLT</option></select></label><label>資料區段 <select id="stage"><option value="locked_historical_test">鎖定歷史稽核區</option><option value="validation">驗證區</option><option value="development">開發區</option></select></label><p>理論公平基準：SSQ=15/528（2.841%），DLT=10/595（1.681%）。差值以百分點表示；率區間為95% Wilson，配對差值為保守95%區間。這些區間及配對檢驗有 IID 假設，未據此授予正式資格。</p><div class="scroll"><table id="summary"><thead><tr><th>模型</th><th>全中／期數</th><th>命中率</th><th>率95%區間（%）</th><th>差理論基準（百分點）</th><th>差同期NULL（百分點）</th><th>差值95%區間（百分點）</th><th>配對Holm p</th><th>公平NULL穩健Holm p</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div><p class="muted">主要 Holm 家族固定為兩彩各5個非NULL模型，共10項，只對鎖定稽核區做這一次校正。公平NULL e-process為另一個預先固定的次要檢查，不用它挑選另一個贏家。開發／驗證區僅描述。</p></section>
<section><h2>逐期明細</h2><label>模型 <select id="model">'''+''.join(f'<option{(" selected" if m==PRIMARY_MODEL else "")}>{m}</option>' for m in MODEL_IDS)+'''</select></label><label>搜尋期號 <input id="issue" placeholder="輸入期號"></label><button id="prev">上一頁</button><span id="page"></span><button id="next">下一頁</button><p><a href="periods.csv" download>下載完整逐期 CSV</a> · <a href="results.json" download>比較結果 JSON</a> · <a href="plan.json" download>事前研究設計</a> · <a href="SHA256.json">檔案 SHA</a></p><div class="scroll"><table><thead><tr><th>期號／日期</th><th>訓練截止／筆數</th><th>模型兩膽</th><th>同期NULL兩膽</th><th>實際前區</th><th>模型／NULL全中</th></tr></thead><tbody id="periods"></tbody></table></div></section>
<section><h2>時間切分與樣本數</h2><p>每彩前120期只作初始訓練；其餘按60%／20%／20%分為開發、驗證及鎖定歷史稽核。每一期都只用嚴格更早的資料。歷史原文一致性不等於證明當時可用。</p><table><thead><tr><th>彩種</th><th>區段</th><th>期數</th><th>期號範圍</th></tr></thead><tbody>'''+split_rows+'''</tbody></table><h3>要檢驗1個百分點提升，現有最後區段不足</h3><table><thead><tr><th>彩種</th><th>鎖定歷史稽核期數</th><th>未來固定試驗規劃期數（近似、較保守情景）</th></tr></thead><tbody>'''+power_rows+'''</tbody></table><details><summary>完整事前檢驗力估算：80% power，10項家族</summary><p>這是指定成功率／discordance假設下的近似規劃，並非保證有80% power，也不代表真有可預測優勢。另列0.5與2百分點情景。真正前瞻期次清單仍缺官方核驗，未開始收樣。</p><pre>'''+power+'''</pre></details></section>
<section><h2>證據限制及參考方法</h2><ul>'''+''.join('<li>'+esc(x)+'</li>' for x in result['inference_caveats'])+'''</ul><p>Plan SHA256：<code>'''+result['plan_sha256']+'''</code>；本地時間封存不等於外部可信 TSA。</p><ul>'''+ref+'''</ul></section>
<script id="data" type="application/json">'''+data+'''</script><script>
const data=JSON.parse(document.getElementById('data').textContent);let offset=0;const size=50;
const el=id=>document.getElementById(id);const fmt=a=>a.map(x=>String(x).padStart(2,'0')).join(' ');
function update(reset=true){if(reset)offset=0;const g=el('game').value,s=el('stage').value,m=el('model').value,q=el('issue').value;
document.querySelectorAll('#summary tbody tr').forEach(r=>r.hidden=r.dataset.game!==g||r.dataset.stage!==s);
const rows=data.filter(r=>r.game===g&&r.stage===s&&r.issue.includes(q));offset=Math.max(0,Math.min(offset,Math.max(0,Math.ceil(rows.length/size)-1)*size));
el('page').textContent=` ${offset+1}–${Math.min(offset+size,rows.length)} / ${rows.length} `;el('periods').replaceChildren();
rows.slice(offset,offset+size).forEach(r=>{const tr=document.createElement('tr');[r.issue+' / '+r.draw_date,r.training_end_issue+' / '+r.training_size,fmt(r.predictions[m]),fmt(r.predictions['R45-RANDOM-NULL']),fmt(r.draw_front),r.full_d2[m]+' / '+r.full_d2['R45-RANDOM-NULL']].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.appendChild(td)});el('periods').appendChild(tr)});}
['game','stage','model'].forEach(id=>el(id).addEventListener('change',()=>update()));el('issue').addEventListener('input',()=>update());el('prev').onclick=()=>{offset-=size;update(false)};el('next').onclick=()=>{offset+=size;update(false)};update();
</script></html>'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','execute','verify'))
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.action=='verify': value=verify(args.output)
    else:
        if args.config is None: parser.error('--config is required')
        config=parse(args.config.read_bytes())
        value=prepare(config,args.output) if args.action=='prepare' else execute(config,args.output)
    print(canonical(dict(action=args.action,plan_sha256=digest(value) if args.action=='prepare' else value['plan_sha256'],status='COMPLETED',**BOUNDARY)))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
