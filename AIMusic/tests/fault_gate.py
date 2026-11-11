from __future__ import annotations
import json, tempfile
from pathlib import Path
from app.domain import CompositionRequest
from app.service import Service

def main()->int:
    bad=[
        CompositionRequest(title="",duration_seconds=3),
        CompositionRequest(style="cloud-ai",duration_seconds=3),
        CompositionRequest(bpm=5,duration_seconds=3),
        CompositionRequest(duration_seconds=1),
    ]
    for x in bad:
        try:x.validate()
        except ValueError:pass
        else:raise AssertionError("invalid request admitted")
    with tempfile.TemporaryDirectory() as td:
        s=Service(Path(td))
        assert s.repair()["status"]=="PASS"
        upd=s.update()
        assert upd["status"]=="BLOCKED" and upd["returncode"]==3
    print(json.dumps({"status":"PASS","invalid_requests_fail_closed":"PASS","update_without_release_context":"BLOCKED"}))
    return 0
if __name__=="__main__": raise SystemExit(main())
