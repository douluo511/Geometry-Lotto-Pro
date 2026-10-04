from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
VERSION=ROOT/"staging"/"Stock_AI_Pro"/"versions"/"4.3.0"
sys.path.insert(0,str(VERSION))
from stock_ai import valuation as mod

def write_pit(root,code,date="2026-01-15"):
    out=root/"data"/"valuation"/f"{code}.csv";out.parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame([{"date":date,"code":str(code),"pe_ttm":12.0,"pb":1.5}]).to_csv(out,index=False,encoding="utf-8-sig")

def main():
    original_root=mod.ROOT
    report={"schema":"stock-ai-valuation-qualification-contract-v1","status":"FAIL"}
    try:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mod.ROOT=root
            codes=[f"{i:06d}" for i in range(1,11)]
            write_pit(root,"000001")
            attempts=[]
            def fake_update(code,cfg,logger=None):
                attempts.append(str(code))
                if str(code)=="000002":raise RuntimeError("forced provider failure")
                write_pit(root,str(code));return mod._read(str(code))
            cfg={"network":{"qualification_history_workers":3}}
            with patch.object(mod,"update_valuation_history",new=fake_update):
                got=mod.qualify_backtest_valuation_histories(codes,cfg,"2026-06-30",0.4)
            assert got["status"]=="PASS",got
            assert got["requested_count"]==10 and got["required_count"]==4,got
            assert got["starting_valid_count"]==1,got
            assert got["ending_valid_count"]>=4 and got["coverage"]>=0.4,got
            assert any(x["code"]=="000002" for x in got["failed"]),got
            assert "000001" not in attempts
            # Future-only valuation must not count as PIT coverage.
            future_root=root/"future";mod.ROOT=future_root
            write_pit(future_root,"000001","2026-12-31")
            assert not mod._has_pit_valuation("000001","2026-06-30")
            # Counterexample: provider failures cannot be converted to PASS.
            fail_root=root/"fail";mod.ROOT=fail_root
            with patch.object(mod,"update_valuation_history",side_effect=RuntimeError("forced all-fail")):
                failed=mod.qualify_backtest_valuation_histories(codes[:5],cfg,"2026-06-30",0.4)
            assert failed["status"]=="FAIL" and failed["ending_valid_count"]<failed["required_count"],failed
            report={"schema":"stock-ai-valuation-qualification-contract-v1","status":"PASS","required_formula":"ceil(test_universe * frozen_backtest_min_coverage)","selection_order":"lexicographic_code_only_no_outcome_selection","provider_failure_replacement":"PASS","future_only_value_rejected":"PASS","all_provider_failure_fail_closed":"PASS"}
    finally:
        mod.ROOT=original_root
    out=ROOT/"valuation_qualification_contract_evidence.json"
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":
    main()
