from __future__ import annotations
import importlib.util, json, re, hashlib
from collections import Counter
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
CORPUS=HERE/"stock_bse_risk_warning_marketwide_corpus.py"
OUT=Path("stock_bse_exhaustive_title_taxonomy.json")

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def classify(title:str)->str:
    t="".join((title or "").split())
    if re.search(r"(撤销|取消|解除|终止实施).{0,16}(退市|其他)?风险警示",t) or re.search(r"(退市|其他)?风险警示.{0,16}(撤销|取消|解除|终止实施)",t):
        if re.search(r"(申请|拟申请|计划申请|关于申请)",t):
            return "removal_application"
        return "actual_removal_candidate"
    if re.search(r"(继续|叠加).{0,12}实施.{0,12}(退市|其他)?风险警示",t):
        return "continuation_or_overlay"
    if re.search(r"(可能|预计|拟|风险提示).{0,18}实施.{0,12}(退市|其他)?风险警示",t):
        return "prospective_or_risk_notice"
    if re.search(r"(被|将被|决定|予以|开始|正式)?.{0,8}实施.{0,12}(退市|其他)?风险警示",t):
        return "actual_implementation_candidate"
    if "风险警示" in t:
        return "risk_warning_other"
    return "other"

def main():
    mod=load("bsec",CORPUS)
    # Reuse the current exact implementation by running its main once to produce the exhaustive corpus.
    rc=mod.main()
    if rc not in (0,None):
        raise SystemExit(f"corpus diagnostic failed rc={rc}")
    path=Path("stock_bse_risk_warning_marketwide_corpus.json")
    if not path.exists():
        raise SystemExit("missing corpus json")
    corpus=json.loads(path.read_text(encoding="utf-8"))
    rows=corpus.get("combined_events") or []
    out=[]
    for r in rows:
        title=str(r.get("title") or "")
        klass=classify(title)
        out.append({
            "canonical_company_code":r.get("canonical_company_code"),
            "raw_company_code":r.get("raw_company_code"),
            "publishDate":r.get("publishDate"),
            "title":title,
            "destFilePath":r.get("destFilePath"),
            "class":klass,
        })
    counts=Counter(x["class"] for x in out)
    removals=[x for x in out if x["class"]=="actual_removal_candidate"]
    apps=[x for x in out if x["class"]=="removal_application"]
    implementation=[x for x in out if x["class"]=="actual_implementation_candidate"]
    canonical=hashlib.sha256(json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    corpus_supported=corpus.get("adjudication",{}).get("exhaustive_bse_risk_warning_title_event_corpus")=="SUPPORTED"
    report={
      "schema":"stock-bse-exhaustive-title-taxonomy-v1",
      "source_corpus_sha256":corpus.get("combined_canonical_sha256"),
      "source_event_count":len(rows),
      "taxonomy_sha256":canonical,
      "class_counts":dict(sorted(counts.items())),
      "actual_removal_candidate_count":len(removals),
      "removal_application_count":len(apps),
      "actual_implementation_candidate_count":len(implementation),
      "actual_removal_candidates":removals,
      "removal_applications":apps,
      "implementation_candidates":implementation,
      "records":out,
      "adjudication":{
        "exhaustive_title_taxonomy":"PASS" if corpus_supported and len(out)==len(rows) and len(rows)>0 else "NOT VERIFIED",
        "risk_warning_title_corpus_removal_events":"SUPPORTED_ZERO_WITHIN_FROZEN_SURFACE" if corpus_supported and len(removals)==0 else ("SUPPORTED_PRESENT" if corpus_supported else "NOT VERIFIED"),
        "bse_removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL"
      },
      "boundary":"Zero actual-removal titles in the exhaustive frozen risk-warning title corpus is stronger than a narrow synonym query, but it remains source-surface-bounded. It does not by itself prove complete removal history or historical daily ST state."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"source_event_count":len(rows),"class_counts":report["class_counts"],"actual_removal_candidate_count":len(removals),"removal_application_count":len(apps),"actual_implementation_candidate_count":len(implementation),"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if report["adjudication"]["exhaustive_title_taxonomy"]=="PASS" else 2
if __name__=="__main__":
    raise SystemExit(main())
