
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for name in [
    "ONE_CLICK_START.bat","RUN_DAILY.bat","START_APP.bat",
    "RUN_BACKTEST.bat","RUN_AUDIT.bat","RUN_RND.bat","SETUP_AUTO_UPDATE.bat"
]:
    text=(ROOT/name).read_text(encoding="utf-8")
    assert "ENSURE_ENV.bat" in text, name
ensure=(ROOT/"ENSURE_ENV.bat").read_text(encoding="utf-8")
assert "doctor.py" in ensure and "BOOTSTRAP.ps1" in ensure
print("ENTRYPOINT SELF-HEAL TEST PASS")
