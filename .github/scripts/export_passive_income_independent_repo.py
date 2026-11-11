from __future__ import annotations
import argparse,hashlib,json,shutil
from pathlib import Path

PROJECT="PassiveIncomePipelineOS"
WORKFLOW=".github/workflows/passive-income-pipeline-reauthored.yml"
SCHEMA="passive-income-independent-export-v1"
SOURCE_REPO="douluo511/Geometry-Lotto-Pro"
EXCLUDED={"dist","build","__pycache__",".pytest_cache",".venv","venv"}

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def cp(root,dest,rel):
    src=(root/rel).resolve()
    src.relative_to(root.resolve())
    if not src.is_file():
        raise FileNotFoundError(rel.as_posix())
    out=dest/rel
    out.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,out)

def verify(dest):
    mp=dest/"MIGRATION_MANIFEST.json"
    if not mp.is_file():
        return {"status":"FAIL","error":"manifest missing"}
    m=json.loads(mp.read_text(encoding="utf-8"))
    rows=m.get("files")
    checks={
        "schema":m.get("schema")==SCHEMA,
        "source_repo":m.get("source_repository")==SOURCE_REPO,
        "project":m.get("project_dir")==PROJECT,
        "workflow":m.get("workflow")==WORKFLOW,
        "repo_not_promoted":m.get("repository_independence")=="NOT VERIFIED",
        "source_commit":isinstance(m.get("source_commit"),str) and len(m["source_commit"])==40,
    }
    if not isinstance(rows,list) or not rows:
        return {"status":"FAIL","checks":checks,"error":"empty manifest"}
    expected={r["path"]:r for r in rows}
    actual={p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and p.name!="MIGRATION_MANIFEST.json"}
    checks["inventory"]=actual==set(expected)
    checks["allowed_roots"]=all(x.startswith(PROJECT+"/") or x==WORKFLOW for x in actual)
    bad=[]
    for rel,row in expected.items():
        p=dest/rel
        if not p.is_file() or sha(p)!=row["sha256"] or p.stat().st_size!=row["bytes"]:
            bad.append(rel)
    checks["hashes"]=not bad
    return {
        "status":"PASS" if all(checks.values()) else "FAIL",
        "file_count":len(expected),
        "source_commit":m.get("source_commit"),
        "checks":checks,
        "mismatches":bad,
        "manifest_sha256":sha(mp),
        "repository_independence":"NOT VERIFIED",
    }

def export(root,dest,commit):
    root=root.resolve()
    dest=dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("destination must be empty")
    dest.mkdir(parents=True,exist_ok=True)
    for p in sorted((root/PROJECT).rglob("*")):
        if not p.is_file():
            continue
        rel=p.relative_to(root)
        if any(x in EXCLUDED for x in rel.parts) or p.suffix.lower() in {".pyc",".pyo"}:
            continue
        cp(root,dest,rel)
    cp(root,dest,Path(WORKFLOW))
    rows=[]
    for p in sorted(x for x in dest.rglob("*") if x.is_file()):
        rel=p.relative_to(dest).as_posix()
        rows.append({"path":rel,"sha256":sha(p),"bytes":p.stat().st_size})
    m={
        "schema":SCHEMA,
        "source_repository":SOURCE_REPO,
        "source_commit":commit,
        "project_dir":PROJECT,
        "workflow":WORKFLOW,
        "repository_independence":"NOT VERIFIED",
        "files":rows,
    }
    (dest/"MIGRATION_MANIFEST.json").write_text(json.dumps(m,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return verify(dest)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--destination",required=True,type=Path)
    p.add_argument("--source-commit")
    p.add_argument("--verify-only",action="store_true")
    a=p.parse_args()
    proof=verify(a.destination) if a.verify_only else export(Path(__file__).resolve().parents[2],a.destination,a.source_commit)
    print(json.dumps(proof,ensure_ascii=False,sort_keys=True))
    return 0 if proof.get("status")=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
