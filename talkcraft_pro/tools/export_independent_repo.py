from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path

SCHEMA="talkcraft-independent-repo-export-v1"
SOURCE_REPOSITORY="douluo511/Geometry-Lotto-Pro"
TARGET_REPOSITORY="douluo511/TalkCraft-Pro"
PROJECT_DIR=Path("talkcraft_pro")
WORKFLOW_PATH=Path(".github/workflows/talkcraft-pro-windows.yml")
EXCLUDED={"dist","build","evidence","__pycache__",".pytest_cache",".mypy_cache"}
EXCLUDED_SUFFIXES={".pyc",".pyo"}

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def source_commit(root: Path) -> str:
    value=str(os.environ.get("GITHUB_SHA") or "").strip()
    if len(value)==40 and all(c in "0123456789abcdefABCDEF" for c in value):
        return value.lower()
    value=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
    if len(value)!=40:
        raise RuntimeError("source commit unavailable")
    return value.lower()

def project_files(root: Path):
    base=root/PROJECT_DIR
    if not base.is_dir():
        raise FileNotFoundError(PROJECT_DIR)
    for p in sorted(x for x in base.rglob("*") if x.is_file()):
        rel=p.relative_to(root)
        if any(part in EXCLUDED for part in rel.parts) or p.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield rel

def copy_one(root: Path,dst: Path,rel: Path):
    src=(root/rel).resolve()
    src.relative_to(root.resolve())
    if not src.is_file():
        raise FileNotFoundError(rel)
    out=dst/rel
    out.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,out)

def verify(dst: Path) -> dict:
    dst=dst.resolve()
    mp=dst/"MIGRATION_MANIFEST.json"
    if not mp.is_file():
        return {"status":"FAIL","error":"manifest missing"}
    m=json.loads(mp.read_text(encoding="utf-8"))
    checks={
        "schema":m.get("schema")==SCHEMA,
        "source_repository":m.get("source_repository")==SOURCE_REPOSITORY,
        "target_repository":m.get("target_repository")==TARGET_REPOSITORY,
        "source_commit":isinstance(m.get("source_commit"),str) and len(m["source_commit"])==40,
    }
    rows=m.get("files")
    if not isinstance(rows,list) or not rows:
        checks["file_manifest"]=False
        return {"status":"FAIL","checks":checks}
    expected={r["path"]:r for r in rows if isinstance(r,dict) and "path" in r}
    actual={
        p.relative_to(dst).as_posix()
        for p in dst.rglob("*")
        if p.is_file() and p.name not in {"MIGRATION_MANIFEST.json","MIGRATION_SHA256SUMS.txt"}
    }
    checks["no_unmanifested_files"]=actual==set(expected)
    checks["project_only"]=all(x.startswith(PROJECT_DIR.as_posix()+"/") or x==WORKFLOW_PATH.as_posix() for x in actual)
    checks["required_workflow"]=WORKFLOW_PATH.as_posix() in actual
    mismatches=[]
    for rel,row in expected.items():
        p=dst/rel
        if not p.is_file() or sha256_file(p)!=row.get("sha256") or p.stat().st_size!=row.get("bytes"):
            mismatches.append(rel)
    checks["all_hashes_match"]=not mismatches
    return {
        "status":"PASS" if all(checks.values()) else "FAIL",
        "schema":SCHEMA,
        "target_repository":TARGET_REPOSITORY,
        "source_commit":m.get("source_commit"),
        "file_count":len(expected),
        "manifest_sha256":sha256_file(mp),
        "checks":checks,
        "mismatches":mismatches,
    }

def export_repo(root: Path,dst: Path,commit: str|None=None) -> dict:
    root=root.resolve(); dst=dst.resolve()
    if dst==root or root in dst.parents:
        raise ValueError("destination must be outside source")
    if dst.exists() and any(dst.iterdir()):
        raise ValueError("destination must be empty")
    dst.mkdir(parents=True,exist_ok=True)
    for rel in project_files(root):
        copy_one(root,dst,rel)
    copy_one(root,dst,WORKFLOW_PATH)
    commit=(commit or source_commit(root)).lower()
    if len(commit)!=40 or not all(c in "0123456789abcdef" for c in commit):
        raise ValueError("invalid source commit")
    rows=[]
    for p in sorted(x for x in dst.rglob("*") if x.is_file()):
        rel=p.relative_to(dst).as_posix()
        rows.append({"path":rel,"sha256":sha256_file(p),"bytes":p.stat().st_size})
    manifest={
        "schema":SCHEMA,
        "source_repository":SOURCE_REPOSITORY,
        "target_repository":TARGET_REPOSITORY,
        "source_commit":commit,
        "files":rows,
    }
    (dst/"MIGRATION_MANIFEST.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    (dst/"MIGRATION_SHA256SUMS.txt").write_text("".join(f'{r["sha256"]}  {r["path"]}\n' for r in rows),encoding="utf-8")
    proof=verify(dst)
    if proof["status"]!="PASS":
        raise RuntimeError(proof)
    return proof

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--destination",type=Path,required=True)
    ap.add_argument("--source-commit")
    ap.add_argument("--verify-only",action="store_true")
    a=ap.parse_args()
    proof=verify(a.destination) if a.verify_only else export_repo(Path(__file__).resolve().parents[2],a.destination,a.source_commit)
    print(json.dumps(proof,sort_keys=True))
    return 0 if proof.get("status")=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
