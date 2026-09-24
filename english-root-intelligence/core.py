from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

APP_NAME = "English Root Intelligence"
APP_VERSION = "0.2.0"
MANIFEST_URL = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/english-root-intelligence/data/update_manifest.json"

PREFIXES = {
    "un": "not / reverse",
    "re": "again / back",
    "pre": "before",
    "pro": "forward / for",
    "con": "together",
    "com": "together",
    "trans": "across / change",
    "inter": "between",
    "sub": "under",
    "ex": "out",
    "in": "in / into / not",
    "im": "in / into / not",
    "dis": "apart / not",
}
SUFFIXES = {
    "able": "able to",
    "ible": "able to",
    "tion": "noun/action",
    "sion": "noun/action",
    "ion": "noun/action",
    "ive": "adjective",
    "al": "adjective",
    "ity": "state/quality",
    "ment": "result/action",
    "er": "person/thing",
    "or": "person/thing",
    "ly": "adverb",
}


def bundled_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def validate_roots(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("roots schema mismatch")
    roots = value.get("roots")
    if not isinstance(roots, list) or len(roots) < 5:
        raise ValueError("root database is incomplete")
    seen = set()
    for row in roots:
        if not isinstance(row, dict):
            raise ValueError("invalid root row")
        m = str(row.get("morpheme", "")).strip().lower()
        if not m or m in seen:
            raise ValueError("empty or duplicate morpheme")
        seen.add(m)
        words = row.get("words")
        chunks = row.get("chunks")
        if not isinstance(words, list) or not words:
            raise ValueError(f"{m}: missing words")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"{m}: missing chunks")
        for w in words:
            if not isinstance(w, list) or len(w) != 4 or not all(str(x).strip() for x in w):
                raise ValueError(f"{m}: invalid word record")
    return value


class Store:
    def __init__(self, root: Path | None = None):
        if root is None:
            appdata = os.environ.get("APPDATA")
            root = Path(appdata) / "EnglishRootIntelligence" if appdata else Path.home() / ".english-root-intelligence"
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.roots_path = self.data_dir / "roots.json"
        self.progress_path = self.root / "progress.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_seed()

    def _ensure_seed(self) -> None:
        if not self.roots_path.exists():
            shutil.copy2(bundled_path("data", "roots.json"), self.roots_path)
        if not self.progress_path.exists():
            atomic_json(self.progress_path, {"schema": 1, "practiced": {}, "analyses": 0, "last_update": None})

    def load_roots(self) -> dict[str, Any]:
        return validate_roots(json.loads(self.roots_path.read_text(encoding="utf-8")))

    def load_progress(self) -> dict[str, Any]:
        value = json.loads(self.progress_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != 1:
            raise ValueError("progress schema mismatch")
        value.setdefault("practiced", {})
        value.setdefault("analyses", 0)
        value.setdefault("last_update", None)
        return value

    def save_progress(self, value: dict[str, Any]) -> None:
        atomic_json(self.progress_path, value)

    def mark_practiced(self, morpheme: str) -> None:
        p = self.load_progress()
        d = p["practiced"]
        d[morpheme] = int(d.get(morpheme, 0)) + 1
        self.save_progress(p)

    def bump_analysis(self) -> None:
        p = self.load_progress()
        p["analyses"] = int(p.get("analyses", 0)) + 1
        self.save_progress(p)


class LearningEngine:
    def __init__(self, store: Store):
        self.store = store

    @property
    def roots(self) -> list[dict[str, Any]]:
        return self.store.load_roots()["roots"]

    def today_roots(self, count: int = 3) -> list[dict[str, Any]]:
        rows = self.roots
        ordinal = dt.date.today().toordinal()
        start = ordinal % len(rows)
        return [rows[(start + i) % len(rows)] for i in range(min(count, len(rows)))]

    def find_root(self, morpheme: str) -> dict[str, Any] | None:
        q = morpheme.lower().strip()
        return next((r for r in self.roots if r["morpheme"] == q), None)

    def analyze(self, word: str) -> dict[str, Any]:
        q = "".join(ch for ch in word.lower().strip() if ch.isalpha())
        if not q:
            raise ValueError("请输入英文单词")

        exact = None
        root_hit = None
        for r in self.roots:
            for w in r["words"]:
                if str(w[0]).lower() == q:
                    exact = w
                    root_hit = r
                    break
            if exact:
                break

        prefix = next(((p, PREFIXES[p]) for p in sorted(PREFIXES, key=len, reverse=True) if q.startswith(p) and len(q) > len(p) + 2), None)
        suffix = next(((s, SUFFIXES[s]) for s in sorted(SUFFIXES, key=len, reverse=True) if q.endswith(s) and len(q) > len(s) + 2), None)
        candidates = [r for r in self.roots if r["morpheme"] in q]
        if root_hit is None and candidates:
            root_hit = max(candidates, key=lambda r: len(r["morpheme"]))

        self.store.bump_analysis()
        if exact and root_hit:
            return {
                "word": q,
                "confidence": 0.98,
                "segmentation": exact[2],
                "meaning": exact[1],
                "semantic_bridge": exact[3],
                "root": root_hit,
                "prefix": prefix,
                "suffix": suffix,
                "family": root_hit["words"],
                "chunks": root_hit["chunks"],
            }

        pieces = []
        if prefix:
            pieces.append(prefix[0])
        if root_hit:
            pieces.append(root_hit["morpheme"])
        if suffix:
            pieces.append(suffix[0])
        return {
            "word": q,
            "confidence": 0.72 if root_hit else 0.25,
            "segmentation": " + ".join(pieces) if pieces else "未找到可靠拆分",
            "meaning": "需要结合词典语境确认",
            "semantic_bridge": root_hit["bridge"] if root_hit else "词根库暂无足够证据，不强行拆词。",
            "root": root_hit,
            "prefix": prefix,
            "suffix": suffix,
            "family": root_hit["words"] if root_hit else [],
            "chunks": root_hit["chunks"] if root_hit else [],
        }

    def stats(self) -> dict[str, Any]:
        p = self.store.load_progress()
        practiced = p.get("practiced", {})
        total = len(self.roots)
        touched = sum(1 for r in self.roots if int(practiced.get(r["morpheme"], 0)) > 0)
        repetitions = sum(int(x) for x in practiced.values())
        return {
            "root_total": total,
            "root_touched": touched,
            "coverage_pct": round(100 * touched / total, 1) if total else 0,
            "practice_repetitions": repetitions,
            "word_analyses": int(p.get("analyses", 0)),
            "last_update": p.get("last_update") or "尚未联网更新",
        }


class MaintenanceEngine:
    def __init__(self, store: Store):
        self.store = store

    def one_click_update(self) -> dict[str, Any]:
        with urllib.request.urlopen(MANIFEST_URL, timeout=15) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
        if manifest.get("schema") != 1 or not manifest.get("data_url") or not manifest.get("sha256"):
            raise ValueError("远程更新清单无效")

        with urllib.request.urlopen(str(manifest["data_url"]), timeout=20) as resp:
            raw = resp.read()
        digest = hashlib.sha256(raw).hexdigest()
        if digest.lower() != str(manifest["sha256"]).lower():
            raise ValueError("更新包 SHA256 校验失败")
        value = validate_roots(json.loads(raw.decode("utf-8")))

        tmp = self.store.data_dir / "roots.json.staging"
        tmp.write_bytes(raw)
        validate_roots(json.loads(tmp.read_text(encoding="utf-8")))
        backup = self.store.data_dir / "roots.json.backup"
        shutil.copy2(self.store.roots_path, backup)
        try:
            os.replace(tmp, self.store.roots_path)
            self.store.load_roots()
        except Exception:
            if backup.exists():
                shutil.copy2(backup, self.store.roots_path)
            raise

        p = self.store.load_progress()
        p["last_update"] = dt.datetime.now().isoformat(timespec="seconds")
        self.store.save_progress(p)
        return {
            "status": "PASS",
            "version": value.get("version"),
            "roots": len(value["roots"]),
            "sha256": digest,
        }

    def one_click_repair(self) -> dict[str, Any]:
        checks = []
        try:
            roots = self.store.load_roots()
            checks.append(("Knowledge DB", "PASS", f'{len(roots["roots"])} roots'))
        except Exception as exc:
            shutil.copy2(bundled_path("data", "roots.json"), self.store.roots_path)
            roots = self.store.load_roots()
            checks.append(("Knowledge DB", "REPAIRED", str(exc)))

        try:
            p = self.store.load_progress()
            checks.append(("User Progress", "PASS", f'{len(p.get("practiced", {}))} practiced roots'))
        except Exception as exc:
            atomic_json(self.store.progress_path, {"schema": 1, "practiced": {}, "analyses": 0, "last_update": None})
            checks.append(("User Progress", "REPAIRED", str(exc)))

        try:
            self.store.load_roots()
            self.store.load_progress()
            final = "PASS"
        except Exception as exc:
            checks.append(("Final Gate", "FAIL", str(exc)))
            final = "FAIL"
        return {"status": final, "checks": checks}


def self_test(root: Path | None = None) -> dict[str, Any]:
    temp_ctx = tempfile.TemporaryDirectory() if root is None else None
    try:
        work = Path(temp_ctx.name) if temp_ctx else Path(root)
        s = Store(work)
        e = LearningEngine(s)
        m = MaintenanceEngine(s)
        a = e.analyze("predict")
        b = e.analyze("inspect")
        plan = e.today_roots(3)
        repair = m.one_click_repair()
        checks = {
            "seed_database": len(e.roots) >= 10,
            "predict_segmentation": "dict" in a["segmentation"],
            "inspect_semantic_bridge": bool(b["semantic_bridge"]),
            "today_plan": len(plan) == 3,
            "repair_gate": repair["status"] == "PASS",
            "progress_integrity": e.stats()["word_analyses"] >= 2,
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "version": APP_VERSION}
    finally:
        if temp_ctx:
            temp_ctx.cleanup()
