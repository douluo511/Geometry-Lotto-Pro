from __future__ import annotations
from typing import Any
from .util import sha256_json, utc_now

def build_ors_record(court: dict[str, Any], trace: dict[str, Any] | None=None) -> dict[str, Any]:
    hypotheses=[
      {'id':'H_SIMPLE','claim':'简单频率信号可能改善 OOS 排名','test':'walk-forward + random baseline'},
      {'id':'H_GEOMETRY','claim':'Geometry State 可能提供增量','test':'remove/shuffle/random + permutation'},
      {'id':'H_TRANSITION','claim':'跨期 Geometry Transition 可能包含信息','test':'Temporal LOEO + untouched holdout'},
      {'id':'H_PAIR','claim':'Pair 图可能包含信息','test':'remove/shuffle/random'},
      {'id':'H_NULL','claim':'观察提升可能只是多重尝试偶然','test':'Holm + null-world + reality check'},]
    record={'schema':3,'created_at':utc_now(),'objective':'寻找可重复的严格样本外排名增益，并主动拒绝假增益',
      'planner':{'hypotheses':hypotheses,'pre_registered_policy':True},
      'researcher':{'role':'提出候选路径','production_write_permission':False},
      'critics':['Data Red Team','Leakage Red Team','Statistical Skeptic','Model Red Team','Software Path Auditor','Researcher-Overfitting Auditor'],
      'judge':{'type':'deterministic','software_verdict':court.get('software_verdict'),'scientific_gate':court.get('scientific_gate'),'edge_state':court.get('edge_state'),'dan_state':court.get('dan_state'),'override_allowed':False},
      'experiment_ledger':{'court_hash':court.get('court_hash'),'effect_trace_hash':sha256_json(trace or {})}}
    record['ors_hash']=sha256_json(record); return record
