import json, tempfile
from pathlib import Path
from service import GuoxueService
def main():
    with tempfile.TemporaryDirectory() as tmp:
        result=GuoxueService(Path(tmp)).one_click_update()
        checks={"status":result.get("status")=="PASS","https_source":str(result.get("source","")).startswith("https://"),"http_2xx":200<=int(result.get("http_status",0))<300,"hash_match":result.get("sha256")==result.get("payload_hash"),"classics":int(result.get("classics",0))>=15}
        status="PASS" if all(checks.values()) else "FAIL"; print(json.dumps({"status":status,"checks":checks,"result":result},ensure_ascii=False)); return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
