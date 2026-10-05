import json, tempfile, os
from app.service import Service, sample_input
from app.engine import analyze
from app.content import corpus_metrics, content_import_status

def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["EARTH_ONLINE_DATA_ROOT"]=td
        s=Service()
        assert s.core()["status"]=="PASS"
        assert s.repair()["status"]=="PASS"
        advanced=s.advanced()
        assert advanced["status"]=="PASS"
        assert advanced["business_content_import"]=="PASS"
        m=corpus_metrics()
        assert m["chapter_count"]==21 and m["case_count"]>=43 and m["training_day_count"]==365
        assert content_import_status()=="PASS"
        bad=sample_input(); bad.falsifying_signals=[]
        try: analyze(bad)
        except ValueError: pass
        else: raise AssertionError("missing reversal evidence admitted")
    print(json.dumps({"status":"PASS","contracts":["domain","storage","evidence","service","reversal-fail-closed","full-content-import"]}))
if __name__=="__main__": main()
