
import sys,tempfile,json,hashlib
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.storage as st

with tempfile.TemporaryDirectory() as td:
    tmp=Path(td);(tmp/"predictions").mkdir()
    old=st.ROOT;st.ROOT=tmp
    try:
        df=pd.DataFrame({"code":["000001"],"final_score":[88.0]})
        out=st.freeze_prediction("2026-08-25",df,{"balanced":df,"offense":df,"defense":df},
                                 {"asof":"2026-08-25"},{"rank_ic":.1},{"regime":"NEUTRAL"},
                                 {"good_ratio":1.0},False,rnd_shadow=pd.DataFrame({"code":["000001"],"production_rank":[1]}))
        manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
        assert "predictions.csv" in manifest["files"] and "rnd_shadow.csv" in manifest["files"]
        try:
            st.freeze_prediction("2026-08-25",df,{"balanced":df,"offense":df,"defense":df},
                                 {},{},{},{},False)
            raise AssertionError("should reject overwrite")
        except FileExistsError:
            pass
        # tamper must change hash
        p=out/"predictions.csv";orig=manifest["files"]["predictions.csv"]
        p.write_text("tampered",encoding="utf-8")
        new=hashlib.sha256(p.read_bytes()).hexdigest()
        assert new!=orig
    finally:st.ROOT=old
print("STORAGE FREEZE TEST PASS")
