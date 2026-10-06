from __future__ import annotations
import hashlib, importlib.util, json
from datetime import date, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
STATE=HERE/"stock_bse_post_implementation_state_sequence.py"
STATE_OUT=Path("stock_bse_post_implementation_state_sequence.json")
OUT=Path("stock_bse_warning_state_replay.json")

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def day_before(value):
    return (date.fromisoformat(value)-timedelta(days=1)).isoformat()

def main():
    state=load("state",STATE)
    rc=state.main()
    if rc!=0:
        raise RuntimeError("post-implementation state-sequence prerequisite failed")
    src=json.loads(STATE_OUT.read_text(encoding="utf-8"))
    companies=[]
    all_query_pass=True
    all_warning_observed=True
    ordinary_restore_count=0
    for c in src.get("companies") or []:
        code=str(c.get("canonical_code") or "")
        start=str(c.get("effective_date") or "")
        if not start:
            raise RuntimeError(f"missing verified warning start for {code}")
        transitions=c.get("post_warning_transitions") or []
        ordinary=[x for x in transitions if x.get("name_state")=="NON_ST_NAME"]
        delist=[x for x in transitions if x.get("name_state")=="DELISTING_NAME"]
        ordinary_restore_count += len(ordinary)
        first_delist=delist[0] if delist else None
        intervals=[{
            "state":"RISK_WARNING",
            "start_date":start,
            "end_date":day_before(str(first_delist["publishDate"])[:10]) if first_delist else src.get("window_end"),
            "start_source":"independently verified initial implementation effective date",
            "end_source":"day before first observed delisting-name announcement" if first_delist else "frozen window end with ST name still observed",
        }]
        if first_delist:
            intervals.append({
                "state":"DELISTING_NAME",
                "start_date":str(first_delist["publishDate"])[:10],
                "end_date":src.get("window_end"),
                "start_source":"first exhaustive company-announcement observation of delisting name; primary-date confirmation handled separately",
            })
        companies.append({
            "canonical_code":code,
            "initial_warning_effective_date":start,
            "query_status":c.get("query_status"),
            "warning_name_observation_count":c.get("warning_name_observation_count"),
            "ordinary_non_st_transition_count":len(ordinary),
            "delisting_transition_count":len(delist),
            "first_delisting_transition":first_delist,
            "intervals":intervals,
            "announcement_canonical_sha256":c.get("canonical_sha256"),
        })
        all_query_pass=all_query_pass and c.get("query_status")=="PASS"
        all_warning_observed=all_warning_observed and int(c.get("warning_name_observation_count") or 0)>0

    if len(companies)!=5:
        raise RuntimeError(f"expected 5 verified implementation companies, got {len(companies)}")
    if ordinary_restore_count!=0:
        raise RuntimeError("ordinary non-ST restoration observed; targeted primary-document adjudication required before replay")

    canonical={
        "window_end":src.get("window_end"),
        "companies":companies,
    }
    report={
        "schema":"stock-bse-warning-state-replay-v1",
        "source_schema":src.get("schema"),
        "company_count":len(companies),
        "ordinary_non_st_restore_count":ordinary_restore_count,
        "companies":companies,
        "canonical_sha256":sha(canonical),
        "adjudication":{
            "five_company_announcement_pagination":"PASS" if all_query_pass else "NOT VERIFIED",
            "five_company_warning_name_observation":"PASS" if all_warning_observed else "NOT VERIFIED",
            "ordinary_non_st_restoration_observed":"NO",
            "bounded_calendar_state_replay":"SUPPORTED_DIAGNOSTIC" if all_query_pass and all_warning_observed else "NOT VERIFIED",
            "removal_event_history_complete":"NOT VERIFIED",
            "trading_day_aligned_state_replay":"NOT VERIFIED",
            "bse_effective_state_reconstruction":"NOT VERIFIED",
            "bse_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":(
            "This reconstructs calendar-date warning/delisting-name intervals only for the five companies "
            "with independently verified initial BSE warning implementations, using exhaustive official "
            "post-implementation company announcements through the frozen window. It does not claim that "
            "the five-company denominator equals every possible historical BSE warning state, does not "
            "align every interval to independently verified trading days, and does not convert delisting "
            "into ordinary risk-warning removal. Therefore BSE/full historical ST PIT remain NOT VERIFIED."
        )
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "company_count":report["company_count"],
        "ordinary_non_st_restore_count":ordinary_restore_count,
        "companies":[{"canonical_code":x["canonical_code"],"intervals":x["intervals"]} for x in companies],
        "adjudication":report["adjudication"]
    },ensure_ascii=True,sort_keys=True))
    return 0 if all_query_pass and all_warning_observed and ordinary_restore_count==0 else 2

if __name__=="__main__":
    raise SystemExit(main())
