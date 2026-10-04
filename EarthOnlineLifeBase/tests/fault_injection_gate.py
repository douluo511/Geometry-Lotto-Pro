import os, tempfile, json
from unittest.mock import patch
from app.netclient import fetch
from app.storage import atomic_json

def main():
    checks={}
    try: fetch("http://example.com"); checks["https_only"]="FAIL"
    except ValueError: checks["https_only"]="PASS"
    with tempfile.TemporaryDirectory() as td:
        p=__import__("pathlib").Path(td)/"x.json"
        with patch("os.replace",side_effect=PermissionError("deny")):
            try: atomic_json(p,{"x":1})
            except PermissionError: checks["atomic_replace_failure"]="PASS"
            else: checks["atomic_replace_failure"]="FAIL"
        assert not p.exists()
    assert all(v=="PASS" for v in checks.values())
    print(json.dumps({"status":"PASS","checks":checks}))
if __name__=="__main__": main()
