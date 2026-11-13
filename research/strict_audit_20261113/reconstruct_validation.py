"""Fill the validation-event omission in PR 492, once; never rewrite its archive."""
import gzip
import json
from pathlib import Path
from research.mother_v1 import rolling_audit as old
from . import audit

def main():
    prior,_,_=audit.load_prior_bytes((audit.HERE/"evidence/prior-rolling-14-arm.zip").read_bytes())
    history=audit.load_history()
    out=audit.HERE/"evidence/validation_events.json.gz"
    if out.exists(): raise FileExistsError("CREATE_ONLY_RECONSTRUCTION_EXISTS")
    result={}
    for game in ("SSQ","DLT"):
        rows=history[game]; n=old.WINDOWS[game]
        reconstructed=old._score_period(rows,game,len(rows)-2*n,len(rows)-n,details=True)
        expected=prior["games"][game]["validation"]
        for key in expected:
            if key!="events" and reconstructed[key]!=expected[key]:
                raise ValueError("VALIDATION_RECONSTRUCTION_DIFFERS:"+game+":"+key)
        result[game]=reconstructed["events"]
        print(game,"PASS original validation aggregates match; new events",len(result[game]),flush=True)
    raw=gzip.compress(json.dumps(result,sort_keys=True,separators=(",",":")).encode(),mtime=0)
    with out.open("xb") as f: f.write(raw)
    print("validation_events_sha256",audit.digest(raw),flush=True)

if __name__=="__main__":main()
