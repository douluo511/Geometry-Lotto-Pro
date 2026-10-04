from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

PROJECT_DIR="BeYourOwnMaster"
WORKFLOW=".github/workflows/be-your-own-master-reauthored.yml"
SCHEMA="byom-independent-repository-export-v1"
SOURCE_REPOSITORY="douluo511/Geometry-Lotto-Pro"
EXCLUDED={"dist","build","__pycache__",".pytest_cache",".venv","venv"}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def copy(root:Path,dest:Path,rel:Path):
    src=(root/rel).resolve(); src.relative_to(root.resolve())
    if not src.is_file(): raise FileNotFoundError(rel.as_posix())
    out=dest/rel; out.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,out)

def export(root:Path,dest:Path,commit:str)->dict:
    root=root.resolve(); dest=dest.resolve()
    if dest.exists() and any(dest.iterdir()): raise ValueError("destination must be empty")
    dest.mkdir(parents=True,exist_ok=True)
    for p in sorted((root/PROJECT_DIR).rglob("*")):
        if not p.is_file(): continue
        rel=p.relative_to(root)
        if any(x in EXCLUDED for x in rel.parts) or p.suffix.lower() in {".pyc",".pyo"}: continue
        copy(root,dest,rel)
    copy(root,dest,Path(WORKFLOW))
    rows=[]
    for p in sorted(x for x in dest.rglob("*") if x.is_file()):
        rel=p.relative_to(dest).as_posix()
        rows.append({"path":rel,"sha256":sha256(p),"bytes":p.stat().st_size})
    manifest={"schema":SCHEMA,"source_repository":SOURCE_REPOSITORY,"source_commit":commit,"project_dir":PROJECT_DIR,"workflow":WORKFLOW,"repository_independence":"NOT VERIFIED","files":rows}
    (dest/"MIGRATION_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return verify(dest)

def verify(dest:Path)->dict:
    mp=dest/"MIGRATION_MANIFEST.json"
    if not mp.is_file(): return {"status":"FAIL","error":"manifest missing"}
    m=json.loads(mp.read_text(encoding="utf-8")); rows=m.get("files")
    checks={
      "schema":m.get("schema")==SCHEMA,
      "source_repository":m.get("source_repository")==SOURCE_REPOSITORY,
      "project_dir":m.get("project_dir")==PROJECT_DIR,
      "workflow":m.get("workflow")==WORKFLOW,
      "repo_not_promoted":m.get("repository_independence")=="NOT VERIFIED",
      "source_commit":isinstance(m.get("source_commit"),str) and len(m["source_commit"])==40
    }
    if not isinstance(rows,list) or not rows: return {"status":"FAIL","checks":checks,"error":"empty manifest"}
    expected={r["path"]:r for r in rows}
    actual={p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and p.name!="MIGRATION_MANIFEST.json"}
    checks["inventory"]=actual==set(expected)
    mismatches=[]
    for rel,row in expected.items():
        p=dest/rel
        if not p.is_file() or sha256(p)!=row.get("sha256") or p.stat().st_size!=row.get("bytes"):
            mismatches.append(rel)
    checks["hashes"]=not mismatches
    checks["allowed_roots"]=all(x.startswith(PROJECT_DIR+"/") or x==WORKFLOW for x in actual)
    status="PASS" if all(checks.values()) else "FAIL"
    return {"status":status,"source_commit":m.get("source_commit"),"file_count":len(expected),"checks":checks,"mismatches":mismatches,"manifest_sha256":sha256(mp),"repository_independence":"NOT VERIFIED"}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--destination",required=True,type=Path); p.add_argument("--source-commit"); p.add_argument("--verify-only",action="store_true"); a=p.parse_args()
    proof=verify(a.destination) if a.verify_only else export(Path(__file__).resolve().parents[2],a.destination,a.source_commit)
    print(json.dumps(proof,ensure_ascii=False,sort_keys=True)); return 0 if proof.get("status")=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
