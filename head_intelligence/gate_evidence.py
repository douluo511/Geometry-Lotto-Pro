from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCHEMA = "head-intelligence-process-gate-v1"


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def current_binding() -> dict:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    expected = os.environ.get("HEAD_SOURCE_SHA")
    run = os.environ.get("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    if head != expected or not run or not str(run).isdigit() or not attempt or not str(attempt).isdigit() or int(attempt)<1:
        raise RuntimeError("gate evidence requires the exact checked-out source and current GitHub run")
    if subprocess.check_output(["git", "diff", "--name-only", "HEAD"], text=True).strip():
        raise RuntimeError("tracked source differs from the accepted checkout")
    return {"source_sha": head, "workflow_run": str(run), "workflow_attempt":str(attempt)}


def untracked(path: Path) -> bool:
    result = subprocess.run(["git", "ls-files", "--error-unmatch", "--", str(path)], capture_output=True, text=True)
    return result.returncode == 1


def receipt_valid(value, *, gate, source_sha, workflow_run, workflow_attempt, artifact_hash=None):
    return (isinstance(value, dict) and value.get("schema") == SCHEMA and value.get("gate") == gate
            and value.get("status") == "PASS" and value.get("exit_code") == 0
            and value.get("source_sha") == source_sha and value.get("workflow_run") == str(workflow_run) and value.get("workflow_attempt") == str(workflow_attempt)
            and bool(value.get("command") or value.get("comparison"))
            and (artifact_hash is None or value.get("artifact_sha256") == artifact_hash))


def read_receipt(path, *, gate, source_sha, workflow_run, workflow_attempt, artifact_hash=None, check_untracked=True):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return (not check_untracked or untracked(Path(path))) and receipt_valid(value, gate=gate, source_sha=source_sha, workflow_run=workflow_run, workflow_attempt=workflow_attempt, artifact_hash=artifact_hash)
    except (OSError, ValueError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--artifact")
    parser.add_argument("--proof-json")
    parser.add_argument("--compare")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    output = Path(args.out)
    binding = current_binding()
    if not untracked(output):
        raise RuntimeError("a tracked evidence receipt cannot be reused")
    output.unlink(missing_ok=True)
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    artifact = Path(args.artifact) if args.artifact else None
    report = {"schema": SCHEMA, "gate": args.gate, **binding, "command": command}
    if args.compare:
        if not artifact or command:
            raise ValueError("hash comparison needs one artifact and no command")
        other = Path(args.compare)
        same = artifact.is_file() and other.is_file() and file_sha256(artifact) == file_sha256(other)
        code = 0 if same else 1
        report["comparison"] = {"candidate": str(artifact), "final": str(other)}
    else:
        if not command:
            raise ValueError("an actual gate command is required")
        if artifact and command[0].lower().endswith(".exe") and Path(command[0]).resolve() != artifact.resolve():
            raise ValueError("executed EXE does not match the bound artifact")
        completed = subprocess.run(command, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        code = completed.returncode
    if args.proof_json:
        try:
            proof = json.loads(Path(args.proof_json).read_text(encoding="utf-8-sig"))
            if not isinstance(proof, dict) or proof.get("status") != "PASS":code = code or 1
            report["proof_sha256"] = file_sha256(Path(args.proof_json))
        except (OSError, ValueError):code = code or 1
    if artifact:
        if artifact.is_file():report["artifact_sha256"] = file_sha256(artifact)
        else:code = code or 1
    report.update(status="PASS" if code == 0 else "FAIL", exit_code=code)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return code


if __name__ == "__main__":raise SystemExit(main())
