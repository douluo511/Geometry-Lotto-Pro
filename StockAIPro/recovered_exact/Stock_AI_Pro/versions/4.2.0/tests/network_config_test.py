
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cfg=json.loads((ROOT/"config.default.json").read_text(encoding="utf-8"))
n=cfg["network"]
assert n["timeout_seconds"]>0
assert n["retry_attempts"]>=2
assert n["request_delay_seconds"]>0
assert n["retry_backoff_seconds"]>0
silent=(ROOT/"RUN_DAILY_SILENT.bat").read_text(encoding="utf-8")
assert "doctor.py" in silent and "BOOTSTRAP.ps1" in silent
print("NETWORK/SELF-HEAL CONFIG TEST PASS")

doctor=(ROOT/'doctor.py').read_text(encoding='utf-8')
assert 'stock_zh_valuation_baidu' in doctor and 'stock_value_em' in doctor
