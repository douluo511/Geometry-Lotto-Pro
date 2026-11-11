from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main()->int:
    k=json.loads((ROOT/"knowledge_base.json").read_text(encoding="utf-8"))
    e=(ROOT/"engine.py").read_text(encoding="utf-8")
    c=(ROOT/"core.py").read_text(encoding="utf-8")
    s=(ROOT/"service.py").read_text(encoding="utf-8")
    n=(ROOT/"net_client.py").read_text(encoding="utf-8")
    ev=(ROOT/"evidence.py").read_text(encoding="utf-8")
    up=(ROOT/"updater.py").read_text(encoding="utf-8")
    rules=k.get("rules",[])
    hyp=k.get("hypothesis_templates",[])
    checks={
        "rule_depth":len(rules)>=24,
        "hypothesis_depth":len(hyp)>=8,
        "sources":len(k.get("sources",[]))>=3,
        "rule_boundaries":all(x.get("boundary") for x in rules),
        "engine_reads_knowledge":"self.knowledge" in e and "_analyze(text, goal, self.knowledge)" in e,
        "core_uses_templates":"hypothesis_templates" in c and "knowledge_rules" in c,
        "five_why_reverse":"five_why" in c and "reverse_validation" in c,
        "guardrails":set(k.get("guardrails",[]))>={"hypotheses_not_facts","no_coercion","no_deception","no_vulnerability_exploitation","direct_verification_preferred"},
        "no_downgrade":"NOOP_OLDER_REMOTE" in s,
        "strict_network_ledger":all(x in n for x in ["FINAL_INSECURE_REDIRECT","RETRY_HTTP","RETRY_EXCEPTION","requested_url","final_url","body_b64"]),
        "raw_evidence_persistence":all(x in ev for x in ["raw_dir","raw_sha256","body_b64"]),
        "no_urllib_bypass":"urllib.request" not in up and "urlopen(" not in up,
        "research_boundary":"不把推测当事实" in c and "不提供欺骗" in c,
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={
        "schema":"human-nature-business-gate-v2",
        "version":k.get("knowledge_version"),
        "status":status,
        "rule_count":len(rules),
        "hypothesis_count":len(hyp),
        "checks":checks,
    }
    (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
