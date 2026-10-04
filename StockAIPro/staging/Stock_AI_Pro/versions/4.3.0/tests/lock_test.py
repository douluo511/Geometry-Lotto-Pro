
import sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stock_ai.utils import process_lock
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/"x.lock"
    with process_lock(p,4):
        assert p.exists()
        try:
            with process_lock(p,4): pass
            raise AssertionError("nested lock should fail")
        except RuntimeError:
            pass
    assert not p.exists()
print("PROCESS LOCK TEST PASS")
