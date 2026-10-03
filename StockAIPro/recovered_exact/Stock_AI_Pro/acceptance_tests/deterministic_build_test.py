import sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from release_tools.build_deterministic_zip import build
with tempfile.TemporaryDirectory() as td:
    t=Path(td);src=t/'X';src.mkdir();(src/'b.txt').write_text('B');(src/'a.txt').write_text('A');(src/'sub').mkdir();(src/'sub'/'c.txt').write_text('C')
    a=build(src,t/'one.zip');b=build(src,t/'two.zip')
    assert a['sha256']==b['sha256'] and (t/'one.zip').read_bytes()==(t/'two.zip').read_bytes()
print('DETERMINISTIC RELEASE BUILD TEST PASS')
