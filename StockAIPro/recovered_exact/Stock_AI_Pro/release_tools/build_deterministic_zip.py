from __future__ import annotations
from pathlib import Path
import argparse,hashlib,os,stat,zipfile

FIXED_DT=(2026,1,1,0,0,0)
EXCLUDE_DIRS={'.venvs','.runtime_venv','staging','userdata','__pycache__','.git'}
EXCLUDE_SUFFIXES={'.pyc','.pyo'}

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def iter_files(root:Path):
    for p in sorted(root.rglob('*'),key=lambda x:x.as_posix()):
        rel=p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):continue
        if p.is_file() and p.suffix not in EXCLUDE_SUFFIXES:
            # Nested ZIPs may be legitimate signed/test fixtures. Generated release archives live outside root.
            yield p,rel

def build(root:Path,out:Path):
    root=root.resolve();out=out.resolve();out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+'.tmp')
    if tmp.exists():tmp.unlink()
    with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9,strict_timestamps=True) as z:
        for p,rel in iter_files(root):
            zi=zipfile.ZipInfo((root.name+'/'+rel.as_posix()),date_time=FIXED_DT)
            zi.create_system=3;zi.compress_type=zipfile.ZIP_DEFLATED
            mode=0o755 if os.access(p,os.X_OK) else 0o644
            zi.external_attr=(stat.S_IFREG|mode)<<16
            z.writestr(zi,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    os.replace(tmp,out)
    return {'path':str(out),'sha256':sha256(out),'bytes':out.stat().st_size,'files':sum(1 for _ in iter_files(root))}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('root');ap.add_argument('output');a=ap.parse_args();print(build(Path(a.root),Path(a.output)))
if __name__=='__main__':main()
