import json, tempfile, os
from pathlib import Path
from app.domain import DecisionInput
from app.service import Service, sample_input
from app.engine import analyze

def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["EARTH_ONLINE_DATA_ROOT"]=td
        s=Service()
        assert s.core()["status"]=="PASS"
        assert s.repair()["status"]=="PASS"
        assert s.advanced()["status"]=="PASS"
        bad=sample_input(); bad.falsifying_signals=[]
        try: analyze(bad)
        except ValueError: pass
        else: raise AssertionError("missing reversal evidence admitted")
    print(json.dumps({"status":"PASS","contracts":["domain","storage","evidence","service","reversal-fail-closed"]}))
if __name__=="__main__": main()
