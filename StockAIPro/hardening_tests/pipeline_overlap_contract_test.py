from __future__ import annotations
import sys,time
from pathlib import Path
VERSION=Path(__file__).resolve().parents[1]/"staging"/"Stock_AI_Pro"/"versions"/"4.3.0"
sys.path.insert(0,str(VERSION))
from stock_ai.pipeline import _parallel_pair

def main():
    def left():
        time.sleep(.35); return "left"
    def right():
        time.sleep(.35); return "right"
    t=time.monotonic(); a,b=_parallel_pair(left,right); elapsed=time.monotonic()-t
    assert (a,b)==("left","right")
    assert elapsed < .62, f"independent operations did not overlap: {elapsed:.3f}s"
    try:
        _parallel_pair(lambda: (_ for _ in ()).throw(RuntimeError("left-fail")),lambda:"right-ok")
    except RuntimeError as exc:
        assert str(exc)=="left-fail"
    else:
        raise AssertionError("left failure did not fail closed")
    try:
        _parallel_pair(lambda:"left-ok",lambda: (_ for _ in ()).throw(RuntimeError("right-fail")))
    except RuntimeError as exc:
        assert str(exc)=="right-fail"
    else:
        raise AssertionError("right failure did not fail closed")
    print({"status":"PASS","overlap_elapsed_seconds":elapsed,"denominator_change":False,"failure_propagation":"PASS"})
if __name__=="__main__": main()
