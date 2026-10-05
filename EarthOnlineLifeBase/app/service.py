from __future__ import annotations
from pathlib import Path
import json, subprocess, sys
from .domain import DecisionInput
from .engine import analyze, reversal_score
from .storage import append_record, list_records, health
from .evidence import record
from .netclient import official_reference_gate
from .content import corpus_metrics, content_import_status, search_corpus

def sample_input()->DecisionInput:
    return DecisionInput(
        question="Should I continue a project when evidence is weak?",
        facts=["The current test produced one measurable result."],
        interpretations=["The project may work if the mechanism is real."],
        unknowns=["External repeatability is unknown."],
        evidence_grade="C",
        dimensions={"history":"Compare prior attempts.","power":"Map decision rights.","economics":"Bound cost and opportunity cost.",
                    "execution":"Choose a reversible test.","philosophy":"Define what outcome is worth pursuing."},
        five_why=["Why continue? To learn whether value exists.","Why is that uncertain? Evidence is limited.","Why limited? Only one test exists."],
        reversal_hypothesis="The apparent result is noise and the project should stop.",
        falsifying_signals=["No repeatable outcome in the next bounded test.","Cost exceeds the written stop condition."],
        options=[{"name":"small test","max_loss":100},{"name":"stop","max_loss":0}],
        small_action="Run one bounded repeat test and record the result.",
        stop_condition="Stop if the repeat test produces no measurable outcome."
    )

class Service:
    def core(self)->dict:
        rec=analyze(sample_input()); path=append_record(rec.__dict__)
        out={"status":"PASS","record_id":rec.record_id,"warnings":rec.warnings,"path":str(path)}
        record("service_core.json",out); return out
    def repair(self)->dict:
        out=health(); out["user_data_deleted"]=False; record("service_repair.json",out); return out
    def advanced(self)->dict:
        records=list_records(); inp=sample_input(); metrics=corpus_metrics(); imported=content_import_status()
        out={"status":"PASS" if imported=="PASS" else "FAIL","record_count":len(records),"reversal":reversal_score(inp),
             "business_content_import":imported,"corpus_metrics":metrics,
             "sample_content_search":search_corpus("逆转验证",limit=2)}
        record("service_advanced.json",out); return out
    def update(self)->dict:
        if getattr(sys,"frozen",False):
            exe=Path(sys.executable).resolve().parent/"EarthOnlineUpdater.exe"
            if not exe.is_file():
                out={"status":"FAIL","reason":"independent updater executable missing"}; record("service_update.json",out); return out
            proc=subprocess.run([str(exe)],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120,shell=False)
        else:
            proc=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"updater_main.py")],
                                capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120,shell=False)
        status="BLOCKED" if proc.returncode==3 and '"status": "BLOCKED"' in proc.stdout else ("PASS" if proc.returncode==0 else "FAIL")
        out={"status":status,"returncode":proc.returncode,"stdout":proc.stdout[-4000:]}
        record("service_update.json",out); return out
    def real_network(self)->dict: return official_reference_gate()
