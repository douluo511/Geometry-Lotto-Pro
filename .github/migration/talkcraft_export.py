#!/usr/bin/env python3
import argparse, hashlib, json, os, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PROJECT=ROOT/"talkcraft_pro"
SUPPORT=[
 ROOT/".github/workflows/talkcraft-pro-windows.yml",
 ROOT/".github/scripts/physical_gui_click_smoke.ps1",
 ROOT/".github/scripts/tk_button_points.py",
]
EXCLUDE_PARTS={"__pycache__",".pytest_cache","runtime","dist","build","evidence"}
EXCLUDE_SUFFIXES={".pyc",".pyo"}

def keep(p:Path)->bool:
    rel=p.relative_to(PROJECT)
    if any(x in EXCLUDE_PARTS for x in rel.parts): return False
    if p.suffix.lower() in EXCLUDE_SUFFIXES: return False
    if p.name in {"architecture_gate.json","business_gate.json","final_gate.json","gate_input.json","FINAL_ACCEPTANCE.json","sha256.txt","physical_gui_click.json","real_network.log"}: return False
    return p.is_file()

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out",required=True); a=ap.parse_args()
    out=Path(a.out).resolve()
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    rows=[]
    files=[p for p in PROJECT.rglob("*") if keep(p)] + [p for p in SUPPORT if p.is_file()]
    for src in sorted(files,key=lambda p:p.as_posix()):
        rel=src.relative_to(PROJECT) if src.is_relative_to(PROJECT) else src.relative_to(ROOT)
        dst=out/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        rows.append({"path":rel.as_posix(),"size":dst.stat().st_size,"sha256":sha(dst)})
    manifest={"schema":"talkcraft-independent-export-v1","source_commit":os.environ.get("GITHUB_SHA","unknown"),"file_count":len(rows),"repository_independence":"NOT VERIFIED","files":rows}
    mp=out/"MIGRATION_MANIFEST.json"; mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"file_count":len(rows),"manifest_sha256":sha(mp),"repository_independence":"NOT VERIFIED"}))

if __name__=="__main__": main()
