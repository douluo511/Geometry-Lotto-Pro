from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path

SCHEMA="legal-philosophy-independent-repository-export-v1"
SOURCE_REPOSITORY="douluo511/Geometry-Lotto-Pro"
PROJECT_DIR="LegalPhilosophy"
WORKFLOW=".github/workflows/legal-philosophy-reauthored.yml"
EXCLUDED={"dist","build","evidence","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache",".venv","venv"}
BAD_SUFFIXES={".pyc",".pyo"}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def source_sha(root:Path)->str:
    value=str(os.environ.get("GITHUB_SHA") or "").strip().lower()
    if not (len(value)==40 and all(c in "0123456789abcdef" for c in value)):
        value=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip().lower()
    if len(value)!=40 or any(c not in "0123456789abcdef" for c in value): raise RuntimeError("source SHA unavailable")
    return value

def safe_files(root:Path):
    base=root/PROJECT_DIR
    if not base.is_dir(): raise FileNotFoundError(PROJECT_DIR)
    for p in sorted(x for x in base.rglob("*") if x.is_file()):
        rel=p.relative_to(root)
        if any(part in EXCLUDED for part in rel.parts) or p.suffix.lower() in BAD_SUFFIXES: continue
        yield rel

def copy(root:Path,dest:Path,rel:Path):
    src=(root/rel).resolve(); src.relative_to(root.resolve())
    if not src.is_file(): raise FileNotFoundError(rel.as_posix())
    out=dest/rel; out.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,out)

def verify(dest:Path)->dict:
    mpath=dest/"MIGRATION_MANIFEST.json"
    if not mpath.is_file(): return {"status":"FAIL","error":"manifest missing"}
    try: manifest=json.loads(mpath.read_text(encoding="utf-8"))
    except Exception as exc: return {"status":"FAIL","error":f"invalid manifest: {exc}"}
    checks={
      "schema":manifest.get("schema")==SCHEMA,
      "source_repository":manifest.get("source_repository")==SOURCE_REPOSITORY,
      "project_dir":manifest.get("project_dir")==PROJECT_DIR,
      "workflow":manifest.get("workflow")==WORKFLOW,
      "repository_not_claimed_independent":manifest.get("repository_independence_status")=="NOT VERIFIED",
      "source_commit":isinstance(manifest.get("source_commit"),str) and len(manifest.get("source_commit",""))==40,
    }
    rows=manifest.get("files")
    if not isinstance(rows,list) or not rows: return {"status":"FAIL","checks":checks,"error":"empty file manifest"}
    expected={}
    for row in rows:
        if not isinstance(row,dict): return {"status":"FAIL","checks":checks,"error":"invalid manifest row"}
        rel=str(row.get("path") or "")
        try:(dest/rel).resolve().relative_to(dest.resolve())
        except ValueError:return {"status":"FAIL","checks":checks,"error":"manifest path escape"}
        expected[rel]=row
    actual={p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and p.name not in {"MIGRATION_MANIFEST.json","MIGRATION_SHA256SUMS.txt"}}
    checks["no_unmanifested_files"]=actual==set(expected)
    checks["project_present"]=any(x.startswith(PROJECT_DIR+"/") for x in actual)
    checks["workflow_present"]=WORKFLOW in actual
    checks["only_allowed_roots"]=all(x.startswith(PROJECT_DIR+"/") or x==WORKFLOW for x in actual)
    checks["no_generated_artifacts"]=not any(any(part in EXCLUDED for part in Path(x).parts) or Path(x).suffix.lower() in BAD_SUFFIXES for x in actual)
    mismatches=[]
    for rel,row in expected.items():
        p=dest/rel
        if not p.is_file(): mismatches.append({"path":rel,"reason":"missing"}); continue
        got=sha256(p); size=p.stat().st_size
        if got!=row.get("sha256") or size!=row.get("bytes"):
            mismatches.append({"path":rel,"expected_sha256":row.get("sha256"),"actual_sha256":got,"expected_bytes":row.get("bytes"),"actual_bytes":size})
    checks["all_hashes_match"]=not mismatches
    return {"status":"PASS" if all(checks.values()) else "FAIL","schema":SCHEMA,"source_commit":manifest.get("source_commit"),"file_count":len(expected),"checks":checks,"mismatches":mismatches,"manifest_sha256":sha256(mpath),"repository_independence":"NOT VERIFIED"}

def export(root:Path,dest:Path,commit:str|None=None)->dict:
    root=root.resolve(); dest=dest.resolve()
    if dest==root or root in dest.parents: raise ValueError("destination must be outside source repository")
    if dest.exists() and any(dest.iterdir()): raise ValueError("destination must be empty")
    dest.mkdir(parents=True,exist_ok=True)
    for rel in safe_files(root): copy(root,dest,rel)
    copy(root,dest,Path(WORKFLOW))
    commit=(commit or source_sha(root)).lower()
    if len(commit)!=40 or any(c not in "0123456789abcdef" for c in commit): raise ValueError("source commit must be full SHA")
    files=[]
    for p in sorted(x for x in dest.rglob("*") if x.is_file()):
        rel=p.relative_to(dest).as_posix()
        files.append({"path":rel,"sha256":sha256(p),"bytes":p.stat().st_size})
    manifest={"schema":SCHEMA,"source_repository":SOURCE_REPOSITORY,"source_commit":commit,"project_dir":PROJECT_DIR,"workflow":WORKFLOW,"repository_independence_status":"NOT VERIFIED","destination_requirement":"dedicated independent repository; exact repository name is not frozen by this export","files":files}
    (dest/"MIGRATION_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    (dest/"MIGRATION_SHA256SUMS.txt").write_text("".join(f'{r["sha256"]}  {r["path"]}\n' for r in files),encoding="utf-8")
    proof=verify(dest)
    if proof["status"]!="PASS": raise RuntimeError(proof)
    return proof

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--destination",type=Path,required=True); ap.add_argument("--source-commit"); ap.add_argument("--verify-only",action="store_true"); a=ap.parse_args()
    proof=verify(a.destination) if a.verify_only else export(Path(__file__).resolve().parents[2],a.destination,a.source_commit)
    print(json.dumps(proof,ensure_ascii=False,sort_keys=True)); return 0 if proof.get("status")=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())
