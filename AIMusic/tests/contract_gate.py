from __future__ import annotations
import json, tempfile, wave
from pathlib import Path
from app.domain import CompositionRequest
from app.service import Service

def main()->int:
    with tempfile.TemporaryDirectory() as td:
        s=Service(Path(td))
        out=s.compose(CompositionRequest(title="Contract",style="cinematic",key="D",bpm=100,duration_seconds=3,seed=7))
        assert out["status"]=="PASS"
        wav=Path(out["project"]["audio_path"])
        assert wav.is_file() and wav.stat().st_size>1000
        with wave.open(str(wav),"rb") as w:
            assert w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==22050
        a=s.advanced()
        assert a["deterministic_audio"]["status"]=="PASS"
        assert a["cloud_ai_provider_generation"]=="NOT VERIFIED"
    print(json.dumps({"status":"PASS","contracts":["domain","audio_export","storage","evidence","identity_boundary"]}))
    return 0
if __name__=="__main__": raise SystemExit(main())
