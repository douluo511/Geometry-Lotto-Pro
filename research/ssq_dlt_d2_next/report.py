"""Read verified outputs into an explicit, static research report."""
from pathlib import Path
import html
import json
from research.ssq_dlt_v45.study_stats import holm_adjust
from .models import MODEL_IDS


def interpret(plan,development,synthetic):
    rules=plan['synthetic_control_rules'];negative={};positive=[]
    for cell in synthetic['summaries']:
        for model in MODEL_IDS:
            m=cell['metrics'][model];key='|'.join((cell['scenario'],cell['game'],model))
            if cell['scenario'] in rules['negative_scenarios']:negative[key]=m['p_fair_one_sided']
            if cell['scenario'] in rules['positive_scenarios']:
                passed=m['paired_delta']>0
                if model==MODEL_IDS[0]:passed=passed and cell['mean_cbpair_brier']<cell['uniform_pair_brier']
                positive.append(dict(key=key,status='PASS_POINT_DIAGNOSTIC' if passed else 'FAIL_POINT_DIAGNOSTIC',
                    paired_delta=m['paired_delta'],brier_delta=cell['mean_cbpair_brier']-cell['uniform_pair_brier'],
                    significance_claim=False))
    if len(negative)!=12 or len(positive)!=12:raise ValueError('COMPLETE_PREDECLARED_CONTROL_FAMILIES_REQUIRED')
    adjusted=holm_adjust(negative)
    return dict(negative_controls={k:dict(p_fair=negative[k],holm_p=v,
        status='FALSIFIED_NEGATIVE_CONTROL' if v<=.05 else 'NOT_FALSIFIED') for k,v in adjusted.items()},
        positive_controls=positive,positive_diagnostic_passes=sum(x['status']=='PASS_POINT_DIAGNOSTIC' for x in positive),
        historical_scope='EXPOSED_DEVELOPMENT_NOT_HOLDOUT',selected_model=None,
        conclusion='NO_PROVEN_D2_IMPROVEMENT',formal_A=0,decision='NO_EDGE')


def render(study,output):
    from .protocol import verify
    verify(study);study=Path(study);output=Path(output)
    read=lambda name:json.loads((study/name).read_bytes())
    plan=read('plan.json');dev=read('development.json');syn=read('synthetic.json');power=read('power-simulation.json')
    verdict=interpret(plan,dev,syn);esc=lambda x:html.escape(str(x),quote=True)
    pct=lambda x:f'{x*100:.3f}%' if x is not None else 'NA'
    ci=lambda x:'['+', '.join(pct(v) for v in x)+']'
    tables=[]
    for game in ('SSQ','DLT'):
        rows=[]
        for key,m in dev['metrics'].items():
            if m['game']!=game:continue
            adjusted=dev['multiplicity']['p_holm_iut'].get(key)
            values=[m['model'],m['n'],m['model_hits'],pct(m['model_rate']),ci(m['model_rate_ci']),
                    pct(m['paired_delta']),ci(m['paired_delta_ci']),f'{adjusted:.5g}' if adjusted is not None else '基準']
            rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
        spec=plan['games'][game]
        tables.append('<h3>'+game+'｜'+esc(spec['first_target'])+'–'+esc(spec['last_target'])+'</h3><div class="scroll"><table><tr><th>模型</th><th>期數</th><th>D2全中</th><th>命中率</th><th>95%率CI</th><th>對同期NULL差值</th><th>95%差值CI</th><th>14項Holm IUT p</th></tr>'+''.join(rows)+'</table></div>')
    control_rows=[]
    for cell in syn['summaries']:
        values=[cell['scenario'],cell['game'],cell['n']]
        for model in MODEL_IDS:
            m=cell['metrics'][model];values.append(f"{m['model_hits']}/{m['n']} ({pct(m['paired_delta'])})")
        values.extend([cell['metrics']['R45-PAIRWISE-D2']['model_hits'],cell['metrics']['R45-RANDOM-NULL']['model_hits'],f"{cell['mean_cbpair_brier']-cell['uniform_pair_brier']:+.7f}"])
        control_rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    planning=plan['future_protocol']['games_planning']
    forecasts=sum(x['evaluation_n'] for x in plan['games'].values())
    page='''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SSQ＋DLT｜D2機制研究閉環</title><style>body{font:16px/1.65 system-ui,'Microsoft JhengHei',sans-serif;background:#f2f5f7;color:#172d3b;margin:0}main{max-width:1250px;margin:auto;padding:32px 24px}h1{font-size:36px;line-height:1.25}h2{font-size:24px}.card{background:white;border:1px solid #dbe5ec;border-radius:15px;padding:24px;margin:18px 0}.badge{display:inline-block;background:#fff0c9;color:#714b0c;padding:6px 12px;border-radius:99px;margin:4px}.lead{color:#4b6374;max-width:950px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid .card{margin:0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;border-bottom:1px solid #dde5ec;padding:9px;white-space:nowrap}th{color:#536978}code{font-size:12px;overflow-wrap:anywhere}pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}details{margin:14px 0}a{color:#0c5870}li{margin:6px 0}.small{font-size:13px;color:#546979}@media(max-width:750px){main{padding:20px 12px}.grid{grid-template-columns:1fr}.card{padding:16px}h1{font-size:28px}}</style></head><body><main><p class="small">SSQ＋DLT V4.5 / 獨立研究模組 R46</p><h1>先測機制，再談命中率。</h1><p class="lead">本輪已完成拆解、假說登記、合成反證、開發資料探索及完整逐期核驗。沒有重評舊 validation／test，也沒有把已看過的歷史資料改稱全新證據。</p><p><span class="badge">A=0 · NO_EDGE</span><span class="badge">真正前瞻樣本0</span><span class="badge">下一合法期 BLOCKED</span></p>
<section class="card"><h2>明確裁決</h2><p><b>本輪沒有證明真實 D2 命中率提升。正式主 D2 與八槽不變。</b></p><p>純粹把單號權重改成精確聯合機率，仍會選最高兩權重，不能算新選號能力。兩個新候選則確實會改變 D2，但必須通過全新前瞻期次才能判定是否勝過 Random NULL。</p><p>預先固定的正控制點診斷通過 <b>'''+str(verdict['positive_diagnostic_passes'])+''' / 12</b>；這只檢查能否恢復注入的訊號，不是實際彩票的效果證據。負控制、弱訊號與反轉結果全部保留，不依結果調參。</p></section>
<div class="grid"><section class="card"><h2>候選一：非均勻配對收縮</h2><p>用240期估計經200期均勻收縮的單號權重，在「固定抽出k個不同號碼」的分布內計算配對機率q，再與最近60期配對次數混合。</p><p><code>score=(h60 + 200×qCB240)/(60+200)</code></p><p>它是一個可實現的固定大小分布混合，會改變配對排序。這是資料重用的估計方法，不能稱作獨立先驗的 Bayesian posterior；輸入odds也不是精確marginal MLE。</p></section><section class="card"><h2>候選二：雙區塊殘差</h2><p>把最近120期分成兩個互不重疊的60期區塊，要求同一配對在兩塊都高於共同基準，選較弱一塊的殘差分數最大者；都不正向時回到固定長期權重。</p><p><code>score=min(z_recent60,z_previous60)</code></p><p>共享基準仍讓兩塊耦合；z只是排序分數，不能當標準常態檢定或獨立重複驗證。</p></section></div>
<section class="card"><h2>開發資料：8模型、同一期、每模型唯一D2</h2><p>僅讀舊開發前綴：SSQ截止2021088、DLT截止19027，統一240期warmup，共'''+str(forecasts)+'''個目標期。所有模型均固定一組兩膽，沒有增加注數或合併覆蓋。</p>'''+''.join(tables)+'''<p class="small">率CI為Wilson；差值CI為四個單側Clopper–Pearson界的保守組合。配對檢定／CI假設IID，滾動訓練未證明該假設。IUT取公平理論基準與同期NULL兩個p的較大值，再對14項Holm校正；這些是已暴露開發資料的描述，不能用來選正式模型。</p></section>
<section class="card"><h2>合成正負控制：不能只測有利情境</h2><p>每格12條獨立種子序列，240期warmup＋240期評分。環狀正控制的所有單號邊際機率相同，只有配對交互作用；每期重排環後則回到公平分布。生成器參考配對沒有交給預測程式。</p><div class="scroll"><table><tr><th>情境</th><th>彩種</th><th>評分期數</th><th>CBPAIR 全中（對NULL差）</th><th>雙塊 全中（對NULL差）</th><th>原Pairwise全中</th><th>NULL全中</th><th>CBPAIR Brier差</th></tr>'''+''.join(control_rows)+'''</table></div><p class="small">Brier差&lt;0較好。每個完整開獎才是一個觀測；528／595個配對高度依賴，不拿來放大樣本數。所有合成結果只測方法機制。</p><details><summary>預先固定的控制判定與完整結果</summary><pre>'''+esc(json.dumps(verdict,ensure_ascii=False,indent=2))+'''</pre></details></section>
<section class="card"><h2>需要多少新期次</h2><p>規劃目標為提升1個百分點、2候選×2彩種共4假說。按較保守的同期配對差異與兩分量IUT功效規劃，固定候選驗證期數為 SSQ <b>'''+str(planning['SSQ']['fixed_n'])+'''期</b>、DLT <b>'''+str(planning['DLT']['fixed_n'])+'''期</b>。這是規劃，不是已證明的效果；沒有根據模擬結果追改期數。</p><p>正式功效模擬每格2000次、3種joint law×4個預定效果配置；只驗統計設計，不代表候選會在真實彩票有效。完整分量功效、Holm拒絕率與FWER區間見下方JSON。</p><p>+1pp只是設計alternative；確認檢定為勝過零差異，不代表已證明至少提升1pp。正式檢定還需可信事前封存、官方合法目標、完整新期次及可辯護的配對模型；目前未啟動。</p><details><summary>完整功效驗算</summary><pre>'''+esc(json.dumps(power,ensure_ascii=False,indent=2))+'''</pre></details></section>
<section class="card"><h2>閉環與證據</h2><ul><li>修正新入口接受同日連續兩期的問題；真實開發資料無此重複。</li><li>修復極端權重下聯合機率下溢；獨立Decimal與完整子集窮舉核對。</li><li>先記錄每期預測，再評分、保存全部命中與未命中；重跑不得覆寫。</li><li>官方下一合法期、可信TSA、01–04批准及全新前瞻均未具備，保持BLOCKED。</li></ul><p><a href="study/plan.json">封存方案</a> · <a href="study/development-periods.csv">逐期CSV</a> · <a href="study/development.json">開發完整JSON</a> · <a href="study/synthetic.json">合成完整JSON</a> · <a href="study/power-simulation.json">功效JSON</a> · <a href="study/execution-receipt.json">實跑回執</a> · <a href="data-audit.md">資料審計</a> · <a href="theory-review.md">理論推導</a> · <a href="validation-design.md">統計設計</a> · <a href="independent-model-audit.json">獨立模型審計</a></p><p class="small">本頁為本地靜態報告。共享儲存庫獨立性及Final Gate仍FAIL。沒有自動購彩，沒有宣稱成功寄信。</p></section></main></body></html>'''
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as f:f.write(page)
    with (output.parent/'interpretation.json').open('x',encoding='utf-8') as f:json.dump(verdict,f,ensure_ascii=False,indent=2)
    return dict(status='REPORT_CREATED',path=str(output),formal_A=0,decision='NO_EDGE')
