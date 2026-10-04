from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
from .domain import CompositionRequest
from .engine import ENGINE_ID, render_wav, deterministic_check
from .storage import Storage
from .evidence import write_receipt
from .netclient import official_reference_gate

class Service:
    def __init__(self,root:Path|None=None):
        self.root=Path(root or os.environ.get("AI_MUSIC_DATA_ROOT","userdata")).resolve()
        self.storage=Storage(self.root)

    def compose(self,req:CompositionRequest|None=None)->dict:
        req=(req or CompositionRequest()).validate()
        out=self.storage.audio/"latest.wav"
        meta=render_wav(req,out)
        project={"status":"PASS","project_version":1,"engine_id":ENGINE_ID,
                 "provider_mode":"LOCAL_PROCEDURAL","cloud_ai_provider":"NOT VERIFIED",
                 "request":req.to_dict(),"audio_path":str(out),"audio_sha256":meta["wav_sha256"],
                 "license_boundary":"Locally synthesized tones only; no third-party audio asset is embedded."}
        self.storage.atomic_json(self.storage.projects/"latest.json",project)
        write_receipt(self.storage.evidence,"compose.json",{"status":"PASS","payload":meta})
        return {"status":"PASS","project":project,"audio":meta}

    def repair(self)->dict:
        out=self.storage.health()
        write_receipt(self.storage.evidence,"repair.json",out)
        return out

    def advanced(self)->dict:
        with tempfile.TemporaryDirectory() as td:
            det=deterministic_check(CompositionRequest(),Path(td))
        latest={}
        p=self.storage.projects/"latest.json"
        if p.is_file():
            latest=json.loads(p.read_text(encoding="utf-8"))
        out={
            "status":"PASS" if det["status"]=="PASS" else "FAIL",
            "local_engine":ENGINE_ID,
            "deterministic_audio":det,
            "latest_project":latest,
            "cloud_ai_provider_generation":"NOT VERIFIED",
            "provider_output_quality":"NOT VERIFIED",
            "provider_license_provenance":"NOT VERIFIED",
            "identity_boundary":"Local procedural composition must never be described as cloud generative AI."
        }
        write_receipt(self.storage.evidence,"advanced.json",out)
        return out

    def reference_network(self)->dict:
        return official_reference_gate(self.storage.evidence)

    def update(self)->dict:
        if getattr(sys,"frozen",False):
            updater=Path(sys.executable).resolve().parent/"AIMusicUpdater.exe"
            if not updater.is_file():
                out={"status":"FAIL","reason":"independent updater executable missing"}
                write_receipt(self.storage.evidence,"update.json",out); return out
            proc=subprocess.run([str(updater)],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120,shell=False)
        else:
            proc=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"updater_main.py")],
                                capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120,shell=False)
        status="BLOCKED" if proc.returncode==3 else ("PASS" if proc.returncode==0 else "FAIL")
        out={"status":status,"returncode":proc.returncode,"stdout":proc.stdout[-3000:]}
        write_receipt(self.storage.evidence,"update.json",out)
        return out
