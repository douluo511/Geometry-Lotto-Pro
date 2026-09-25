from __future__ import annotations
import argparse,json
from pathlib import Path
HARD_GATES=[
    "purpose_model",
    "five_why",
    "risk_boundary",
    "domain_model",
    "architecture",
    "function_contract",
    "interface_contract",
    "data_source",
    "netclient",
    "storage",
    "engine",
    "evidence",
    "service",
    "ui",
    "self_test",
    "contract_test",
    "fault_injection",
    "real_network",
    "windows_build",
    "exact_exe",
    "gui_smoke",
    "same_hash",
    "business_content"
]
def main():
 p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--output",required=True); a=p.parse_args(); d=json.loads(Path(a.input).read_text(encoding="utf-8-sig")); g={k:d.get("gates",{}).get(k,"UNKNOWN") for k in HARD_GATES}; bad={k:v for k,v in g.items() if v!="PASS"}; r={"final_gate":"PASS" if not bad else "FAIL","hard_fail_count":len(bad),"gates":g,"failures":bad}; Path(a.output).write_text(json.dumps(r,indent=2),encoding="utf-8"); print(json.dumps(r)); return 0 if not bad else 2
if __name__=="__main__": raise SystemExit(main())
