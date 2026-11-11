from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from core import Store, bundled_path
from contracts import validate_roots

class RootStorage:
    def __init__(self, root: Path | None = None):
        self.store = Store(root)

    @property
    def root(self):
        return self.store.root

    def load_roots(self):
        return self.store.load_roots()

    def load_progress(self):
        return self.store.load_progress()

    def mark_practiced(self, mapping):
        return self.store.mark_practiced(mapping)

    def bump_analysis(self):
        return self.store.bump_analysis()

    def save_progress(self, value):
        return self.store.save_progress(value)

    @staticmethod
    def _stage(path: Path, data: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".stage", dir=path.parent)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            return tmp
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _restore(path: Path, old: bytes | None) -> None:
        if old is None:
            path.unlink(missing_ok=True)
            return
        tmp = RootStorage._stage(path, old)
        os.replace(tmp, path)

    def commit_update(self, raw: bytes, fetched_at: str, evidence_path: Path, evidence_row: dict) -> dict:
        value = validate_roots(json.loads(raw.decode("utf-8-sig")))
        progress = self.store.load_progress()
        progress["last_update"] = fetched_at

        roots_path = self.store.roots_path
        progress_path = self.store.progress_path
        evidence_path = Path(evidence_path)

        roots_bytes = raw
        progress_bytes = (json.dumps(progress, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        old_evidence = evidence_path.read_bytes() if evidence_path.exists() else b""
        evidence_bytes = old_evidence + (json.dumps(evidence_row, ensure_ascii=False) + "\n").encode("utf-8")

        old_roots = roots_path.read_bytes() if roots_path.exists() else None
        old_progress = progress_path.read_bytes() if progress_path.exists() else None
        old_evidence_bytes = evidence_path.read_bytes() if evidence_path.exists() else None

        staged_roots = staged_progress = staged_evidence = None
        committed: list[tuple[Path, bytes | None]] = []
        try:
            staged_roots = self._stage(roots_path, roots_bytes)
            staged_progress = self._stage(progress_path, progress_bytes)
            staged_evidence = self._stage(evidence_path, evidence_bytes)

            os.replace(staged_evidence, evidence_path)
            staged_evidence = None
            committed.append((evidence_path, old_evidence_bytes))

            os.replace(staged_progress, progress_path)
            staged_progress = None
            committed.append((progress_path, old_progress))

            os.replace(staged_roots, roots_path)
            staged_roots = None
            committed.append((roots_path, old_roots))

            self.store.load_roots()
            self.store.load_progress()
            return value
        except Exception:
            for path, old in reversed(committed):
                try:
                    self._restore(path, old)
                except Exception:
                    pass
            raise
        finally:
            for tmp in (staged_roots, staged_progress, staged_evidence):
                if tmp is not None:
                    tmp.unlink(missing_ok=True)

    def replace_roots(self, raw: bytes) -> dict:
        value = validate_roots(json.loads(raw.decode("utf-8-sig")))
        path = self.store.roots_path
        stage = path.with_suffix(".staging")
        backup = path.with_suffix(".backup")
        with stage.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        validate_roots(json.loads(stage.read_text(encoding="utf-8")))
        shutil.copy2(path, backup)
        try:
            os.replace(stage, path)
            self.store.load_roots()
        except Exception:
            if backup.exists():
                shutil.copy2(backup, path)
            raise
        return value

    def repair(self):
        checks = []
        try:
            roots = self.store.load_roots()
            checks.append(("Knowledge DB", "PASS", f'{len(roots["roots"])} roots'))
        except Exception as exc:
            self._preserve_original(self.store.roots_path)
            self._restore(self.store.roots_path, bundled_path("data", "roots.json").read_bytes())
            self.store.load_roots()
            checks.append(("Knowledge DB", "REPAIRED", str(exc)))
        try:
            progress = self.store.load_progress()
            checks.append(("User Progress", "PASS", f'{len(progress.get("practiced", {}))} practiced roots'))
        except Exception as exc:
            self._preserve_original(self.store.progress_path)
            self.store.save_progress({"schema": 1, "practiced": {}, "analyses": 0, "last_update": None})
            checks.append(("User Progress", "REPAIRED", str(exc)))
        try:
            self.store.load_roots()
            self.store.load_progress()
            status = "PASS"
        except Exception as exc:
            checks.append(("Final Gate", "FAIL", str(exc)))
            status = "FAIL"
        return {"status": status, "checks": checks}

    def _preserve_original(self, path: Path) -> None:
        if not path.is_file():
            return
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        destination = self.root / "recovery" / f"{path.name}.{digest}.original"
        if destination.exists():
            if destination.read_bytes() != original:
                raise RuntimeError("repair recovery artifact mismatch")
            return
        staged = self._stage(destination, original)
        try:
            os.replace(staged, destination)
        finally:
            staged.unlink(missing_ok=True)
