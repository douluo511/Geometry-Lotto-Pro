#!/usr/bin/env python3
import argparse, hashlib, json, os, re, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PROJECT=ROOT/"DLT"
WORKFLOW=ROOT/".github/workflows/dlt-windows-build-acceptance.yml"
TARGET="douluo511/Geometry-Lotto-Pro-DLT"
EXCLUDE_PARTS={"__pycache__",".pytest_cache","runtime","dist","build","evidence"}
EXCLUDE_SUFFIXES={".pyc",".pyo"}
SCRIPT_PATTERN=re.compile(r"\.github/scripts/[A-Za-z0-9_.-]+")

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def keep(p):
    rel=p.relative_to(PROJECT)
    return p.is_file() and not any(x in EXCLUDE_PARTS for x in rel.parts) and p.suffix.lower() not in EXCLUDE_SUFFIXES

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    out=Path(a.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    files=[p for p in PROJECT.rglob("*") if keep(p)]
    files.append(WORKFLOW)
    if WORKFLOW.is_file():
        for m in sorted(set(SCRIPT_PATTERN.findall(WORKFLOW.read_text(encoding="utf-8")))):
            p=ROOT/m
            if p.is_file():
                files.append(p)

    rows=[]
    for src in sorted(set(files),key=lambda p:p.as_posix()):
        rel=src.relative_to(PROJECT) if src.is_relative_to(PROJECT) else src.relative_to(ROOT)
        dst=out/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
        rows.append({"path":rel.as_posix(),"size":dst.stat().st_size,"sha256":sha(dst)})

    source_sha=os.environ.get("SOURCE_SHA") or os.environ.get("GITHUB_SHA","unknown")
    manifest={
        "schema":"dlt-independent-export-v1",
        "source_commit":source_sha,
        "target_repository":TARGET,
        "file_count":len(rows),
        "repository_independence":"NOT VERIFIED",
        "files":rows,
    }
    mp=out/"MIGRATION_MANIFEST.json"
    mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"source_commit":source_sha,"file_count":len(rows),"manifest_sha256":sha(mp),"repository_independence":"NOT VERIFIED"}))

if __name__=="__main__":
    main()
