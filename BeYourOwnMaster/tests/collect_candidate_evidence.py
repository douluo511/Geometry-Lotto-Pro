from __future__ import annotations
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(name):
    p=ROOT/name
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def coverage(required,statuses):
    passed=sum(statuses.get(x)=="PASS" for x in required)
    return {"passed":passed,"total":len(required),"percent":round(100*passed/len(required),4),"status":"PASS" if passed==len(required) else "NOT VERIFIED","gate_statuses":statuses}
def main():
    c=read("ACCEPTANCE_CONTRACT.json");g=read("governance_evidence.json");con=read("contract_evidence.json");fault=read("fault_injection_evidence.json");up=read("updater_contract_evidence.json");net=read("real_network_evidence.json");biz=read("business_evidence.json");build=read("windows_build_evidence.json");exact=read("exact_exe_evidence.json");gui=read("gui_click_evidence.json")
    source=os.environ.get("SOURCE_SHA");exe=ROOT/"dist"/"BeYourOwnMaster.exe";current=sha(exe)
    same="PASS" if current and exact.get("exe_sha256_before")==current==exact.get("exe_sha256_after") and gui.get("exe_sha256_before")==current==gui.get("exe_sha256_after") else "NOT VERIFIED"
    eng={
      "requirements_purpose_model":g.get("requirements_purpose_model","NOT VERIFIED"),"five_why":g.get("five_why","NOT VERIFIED"),"risk_boundary":g.get("risk_boundary","NOT VERIFIED"),"domain_model":g.get("domain_model","NOT VERIFIED"),"architecture":g.get("architecture","NOT VERIFIED"),"function_inventory":g.get("function_inventory","NOT VERIFIED"),
      "interface_contracts":con.get("interface_contracts","NOT VERIFIED"),"data_sources":net.get("status","NOT VERIFIED"),"netclient":"PASS" if fault.get("https_fail_closed")=="PASS" and net.get("status")=="PASS" else "NOT VERIFIED","storage":fault.get("corrupt_record_quarantine","NOT VERIFIED"),"engine":con.get("engine_boundary","NOT VERIFIED"),"validation":biz.get("status","NOT VERIFIED"),"evidence":"PASS" if all(read(x) for x in ["governance_evidence.json","contract_evidence.json","fault_injection_evidence.json","real_network_evidence.json","business_evidence.json"]) else "NOT VERIFIED","service":net.get("study_service","NOT VERIFIED"),"ui":gui.get("physical_gui","NOT VERIFIED"),"self_test":exact.get("status","NOT VERIFIED"),"contract_test":con.get("status","NOT VERIFIED"),"fault_injection":fault.get("status","NOT VERIFIED"),"real_network":net.get("status","NOT VERIFIED"),"windows_build":build.get("status","NOT VERIFIED") if build.get("source_sha")==source else "NOT VERIFIED","exact_exe":exact.get("status","NOT VERIFIED") if exact.get("source_sha")==source else "NOT VERIFIED","physical_gui":gui.get("physical_gui","NOT VERIFIED"),"updater_contract":up.get("status","NOT VERIFIED"),"positive_production_update":"BLOCKED","repository_independence":"BLOCKED","real_release_n_to_n_plus_1":"BLOCKED","same_hash_current_bytes":same,"formal_release_redownload_same_hash":"NOT VERIFIED"
    }
    ec=coverage(c["engineering_required"],eng);bc=coverage(c["business_required"],biz.get("gate_statuses",{}));final="PASS" if ec["status"]=="PASS" and bc["status"]=="PASS" else "FAIL"
    report={"status":"CANDIDATE_ONLY","source_sha":source,"main_sha256":current,"updater_sha256":sha(ROOT/"dist"/"BeYourOwnMasterUpdater.exe"),"engineering_completion":ec,"business_completion":bc,"overall_completion_percent":min(ec["percent"],bc["percent"]),"final_gate":final,"delivery_allowed":False,"note":"New re-authored lineage; historical application acceptance not inherited. 30/90-day effectiveness cannot be pre-declared."}
    (ROOT/"candidate_manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report,ensure_ascii=True));return 0
if __name__=="__main__":raise SystemExit(main())
