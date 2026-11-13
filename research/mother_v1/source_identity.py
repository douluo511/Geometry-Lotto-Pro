"""Cross-platform exact-Git-source SHA256 with strict checkout-byte comparison.

Git checkout is allowed to translate CRLF/LF, so hashing installed source
bytes naively makes Windows/Linux research identities disagree. Anchor each
source to the actual HEAD Git blob and reject all non-line-ending changes.

This is source REPRODUCIBILITY, not trusted pre-draw publication proof.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


class SourceIdentityBlocked(ValueError):
    pass


def committed_source_sha256(source: str | Path) -> str:
    path = Path(source)
    if path.is_symlink() or not path.is_file():
        raise SourceIdentityBlocked("SOURCE_MISSING_OR_SYMLINK")
    root = ROOT.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise SourceIdentityBlocked("SOURCE_OUTSIDE_REPO")
    rel = resolved.relative_to(root).as_posix()
    if "\x00" in rel or rel.startswith("../") or "\n" in rel:
        raise SourceIdentityBlocked("SOURCE_PATH_INVALID")
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", "HEAD:" + rel],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10, shell=False, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceIdentityBlocked("COMMITTED_GIT_SOURCE_UNAVAILABLE") from exc
    if proc.returncode or not proc.stdout or len(proc.stdout) > 2_000_000:
        raise SourceIdentityBlocked("COMMITTED_GIT_BLOB_MISSING_OR_TOO_LARGE")
    committed = proc.stdout
    installed = resolved.read_bytes()
    # Source semantics cannot change: only Windows checkout CRLF translation.
    normalize = lambda raw: raw.replace(b"\r\n", b"\n")
    if normalize(committed) != normalize(installed):
        raise SourceIdentityBlocked("INSTALLED_BYTES_DIFFER_FROM_GIT_COMMIT")
    return sha256(committed).hexdigest()
