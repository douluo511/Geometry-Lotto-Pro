from pathlib import Path
import json,subprocess,sys
import pandas as pd
import streamlit as st
from stock_ai.config import ROOT,CODE_ROOT

def j(path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def main():
    st.set_page_config(page_title='Stock AI Pro 4.2',layout='wide')
    st.title('Stock AI Pro 4.2 · 闭环A股研究与自研发系统')
    st.caption('评分是相对排序，不是上涨概率；软件不保证收益。')
    latest=ROOT/'predictions'/'latest'; last=j(ROOT/'state'/'last_run.json',{}) or {}; bootstrap=j(ROOT/'cache'/'bootstrap_status.json',{}) or {}; audit=j(ROOT/'reports'/'audit_report.json',{}) or {}; drift=j(ROOT/'reports'/'drift_report.json',{}) or {}; update=j(ROOT/'cache'/'last_update_status.json',{}) or {}; vs=j(ROOT/'cache'/'valuation_status.json',{}) or {}; rnd=j(ROOT/'reports'/'rnd_report.json',{}) or {}; chain=j(ROOT/'state'/'prediction_chain.json',{}) or {}; rnd_evidence=j(ROOT/'reports'/'rnd_evidence.json',{}) or {}; rnd_registry=j(ROOT/'reports'/'rnd_candidate_registry.json',{}) or {}
    if last.get('status')=='FAIL': st.error('最近一次自动流程失败：'+str(last.get('error','未知错误'))+'。当前显示最后一次有效冻结预测。')
    if not latest.exists(): st.warning('尚无冻结预测。请运行 ONE_CLICK_START.bat 或 RUN_DAILY.bat。'); st.stop()
    summary=j(latest/'summary.json',{}) or {}; regime=j(latest/'market_regime.json',{}) or {}; metrics=j(latest/'model_metrics.json',{}) or {}; dq=j(latest/'data_quality.json',{}) or {}; decision=j(latest/'decision.json',{}) or {}; pred=pd.read_csv(latest/'predictions.csv',dtype={'code':str})
    cols=st.columns(8); vals=[('交易日',summary.get('asof','-')),('决策',decision.get('decision',summary.get('decision','-'))),('市场',regime.get('regime','-')),('MODEL TRUST',decision.get('model_trust',audit.get('trust','待审计'))),('Rank IC',f"{metrics.get('rank_ic',0):.3f}" if metrics.get('rank_ic') is not None else '-'),('漂移',drift.get('status','待检查')),('研究池',f"{float(bootstrap.get('coverage',0))*100:.1f}%"),('估值PIT',f"{float(vs.get('coverage',0))*100:.1f}%")]
    for c,(k,v) in zip(cols,vals): c.metric(k,v)
    tabs=st.tabs(['今日Top20','股票诊断','三套组合','回测','估值与成本','模型审计','研发闭环','证据链','系统健康'])
    with tabs[0]:
        show=[x for x in ['code','name','industry','final_score','confidence','signal','expected_alpha','expected_net_alpha','estimated_roundtrip_cost_bps','score_valuation','score_cost','score_ml','score_momentum','score_risk','score_robustness','pe_ttm','pe_dynamic','pb','valuation_source'] if x in pred]
        st.dataframe(pred[show].head(20),use_container_width=True,hide_index=True); st.info(summary.get('note',''))
    with tabs[1]:
        options=(pred['code'].astype(str)+' '+pred.get('name','').astype(str)).tolist(); sel=st.selectbox('股票',options)
        row=pred[pred['code'].astype(str)==sel.split()[0]].head(1)
        if not row.empty: st.dataframe(row.T,use_container_width=True)
    with tabs[2]:
        choice=st.radio('组合',['balanced','offense','defense'],horizontal=True); p=latest/f'portfolio_{choice}.csv'
        if p.exists():st.dataframe(pd.read_csv(p,dtype={'code':str}),use_container_width=True,hide_index=True)
        st.json(decision)
    with tabs[3]:
        bs=j(ROOT/'reports'/'backtest_summary.json')
        if bs: st.json(bs)
        bp=ROOT/'reports'/'backtest.csv'
        if bp.exists():
            b=pd.read_csv(bp);b['date']=pd.to_datetime(b['date']); eq=[c for c in ['equity','random_equity','momentum_equity','value_equity'] if c in b]
            if eq:st.line_chart(b.set_index('date')[eq]);st.dataframe(b.tail(40),use_container_width=True,hide_index=True)
    with tabs[4]:
        show=[x for x in ['code','name','industry','pe_ttm','pe_dynamic','pb','valuation_source','score_pe','score_pb','score_valuation','valuation_penalty','estimated_roundtrip_cost_bps','estimated_roundtrip_cost_cny','score_cost','expected_net_alpha'] if x in pred]
        st.dataframe(pred[show].head(60),use_container_width=True,hide_index=True); st.json({'valuation_status':vs,'cost_assumptions':j(latest/'cost_assumptions.json',{}) or {}})
    with tabs[5]:
        if audit:
            st.metric('MODEL TRUST',audit.get('trust'));st.dataframe(pd.DataFrame(audit.get('checks',[])),use_container_width=True,hide_index=True)
            st.subheader('5 Why');st.json(audit.get('five_why',[]));st.subheader('逆转验证');st.write(audit.get('reverse_validation',[]))
        else: st.info('尚无完整审计；系统周期性自动运行，也可手动 RUN_AUDIT.bat。')
    with tabs[6]:
        if rnd:
            st.metric('R&D 状态',rnd.get('status','-'))
            st.caption('只评价结果出现前已经冻结的 Champion/Challenger；不使用结果倒推历史，也不会自动修改生产模型。')
            st.json({'degradation':rnd.get('degradation',{}),'promotion_gates':rnd.get('promotion_gates',[]),'promotable_candidates':rnd.get('promotable_candidates',[]),'five_why':rnd.get('five_why',[]),'reverse_validation':rnd.get('reverse_validation',[])})
            hp=ROOT/'reports'/'rnd_shadow_history.csv'
            if hp.exists():
                h=pd.read_csv(hp); st.dataframe(h.tail(80),use_container_width=True,hide_index=True)
        else: st.info('尚无研发闭环报告；先冻结预测，未来结果可用后才会形成真实比较。')
    with tabs[7]:
        st.subheader('预测跨期哈希证据链')
        st.json(chain or {'status':'尚未形成预测链'})
        st.subheader('R&D 可复核证据')
        st.json({'evidence_id':rnd.get('evidence_id'),'evidence':rnd_evidence,'candidate_registry':rnd_registry})
        st.caption('每期冻结清单链接上一期 Manifest SHA-256；R&D 候选同时记录配置、冻结样本和审计指纹。')
    with tabs[8]:
        st.json({'last_run':last,'last_update':update,'bootstrap':bootstrap,'valuation':vs,'rnd_status':rnd.get('status'),'data_quality':dq,'model_metrics':metrics,'feature_drift':drift,'prediction_chain':chain,'data_root':str(ROOT),'code_root':str(CODE_ROOT)})
        st.caption('程序代码和用户数据分离；Windows 默认数据目录为 %APPDATA%\\StockAIPro。')
if __name__=='__main__':main()
