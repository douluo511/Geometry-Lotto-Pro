from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from net_client import NetClient

APP_NAME = "国学智策系统"
APP_VERSION = "0.1.0"
MANIFEST_URLS = [
    "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/guoxue-zhice/data/update_manifest.json",
    "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/guoxue-zhice-v0.1/guoxue-zhice/data/update_manifest.json",
]

SCENARIO_KEYWORDS = {
    "negotiation": ["谈判", "压价", "价格", "合作", "说服", "条件", "底线", "筹码"],
    "competition": ["竞争", "对手", "竞标", "胜负", "争夺", "博弈", "市场"],
    "organization": ["团队", "管理", "制度", "组织", "员工", "执行", "奖惩", "领导"],
    "relationships": ["关系", "人情", "朋友", "沟通", "冲突", "信任", "人心", "识人"],
    "wealth": ["赚钱", "投资", "商业", "生意", "财富", "成本", "利润", "现金流"],
    "self": ["焦虑", "自律", "成长", "选择", "坚持", "内耗", "修身", "学习"],
    "risk": ["风险", "不确定", "危机", "失败", "退路", "损失", "机会"],
    "history": ["历史", "复盘", "规律", "兴衰", "案例", "教训"],
    "health": ["健康", "养生", "睡眠", "饮食", "身体"],
}

SCENARIO_LABELS = {
    "negotiation": "谈判与合作",
    "competition": "竞争与博弈",
    "organization": "组织与管理",
    "relationships": "人性与关系",
    "wealth": "财富与商业",
    "self": "修身与执行",
    "risk": "风险与不确定性",
    "history": "历史类比与复盘",
    "health": "健康与生活",
    "general": "综合判断",
}

DEFAULT_QUESTIONS = {
    "negotiation": ["双方真正想得到什么？", "谁的替代方案更强？", "哪些条件可交换、哪些必须守住？"],
    "competition": ["决定胜负的关键资源是什么？", "是否能避开对手优势而改变战场？", "失败成本与退出条件是什么？"],
    "organization": ["问题来自人、流程、激励还是权责？", "规则是否可执行且可审计？", "奖励与惩罚是否真的改变行为？"],
    "relationships": ["对方的利益、情绪与承诺是否一致？", "这是一次性关系还是重复合作？", "我看到的是事实还是自己的投射？"],
    "wealth": ["现金从哪里来、流向哪里？", "收益来自能力、周期还是杠杆？", "最坏情形下能否活下来？"],
    "self": ["我能控制什么、不能控制什么？", "知道与做到之间卡在哪一环？", "如果去掉面子与情绪，我会如何选择？"],
    "risk": ["最坏结果是什么？", "哪些信号出现时必须撤退？", "有没有成本更低的试错方式？"],
    "history": ["当前局面与历史案例真正相似的是机制还是表面？", "当时参与者有哪些我们今天没有的约束？", "反例在哪里？"],
    "health": ["这是古代经验、现代证据还是个人感受？", "风险是否需要现代医学评估？", "哪些生活方式调整低风险且可持续？"],
    "general": ["目标是什么？", "关键约束是什么？", "哪条假设最可能错？"],
}


def bundled_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def validate_knowledge(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("knowledge schema mismatch")
    classics = value.get("classics")
    if not isinstance(classics, list) or len(classics) < 15:
        raise ValueError("knowledge base is incomplete")
    seen = set()
    for row in classics:
        if not isinstance(row, dict):
            raise ValueError("invalid classic row")
        title = str(row.get("title", "")).strip()
        if not title or title in seen:
            raise ValueError("empty or duplicate title")
        seen.add(title)
        if not isinstance(row.get("scenarios"), list) or not row["scenarios"]:
            raise ValueError(f"{title}: missing scenarios")
        if not isinstance(row.get("methods"), list) or not row["methods"]:
            raise ValueError(f"{title}: missing methods")
        if not str(row.get("source_note", "")).strip():
            raise ValueError(f"{title}: missing source note")
        if not str(row.get("boundary", "")).strip():
            raise ValueError(f"{title}: missing boundary")
    return value


class Store:
    def __init__(self, root: Path | None = None):
        if root is None:
            appdata = os.environ.get("APPDATA")
            root = Path(appdata) / "GuoxueZhice" if appdata else Path.home() / ".guoxue-zhice"
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.knowledge_path = self.data_dir / "knowledge.json"
        self.state_path = self.root / "state.json"
        self.evidence_path = self.root / "network_evidence.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_seed()

    def _ensure_seed(self) -> None:
        if not self.knowledge_path.exists():
            shutil.copy2(bundled_path("data", "knowledge.json"), self.knowledge_path)
        if not self.state_path.exists():
            atomic_json(self.state_path, {
                "schema": 1,
                "analyses": [],
                "reviews": [],
                "last_update": None,
            })

    def load_knowledge(self) -> dict[str, Any]:
        return validate_knowledge(json.loads(self.knowledge_path.read_text(encoding="utf-8")))

    def load_state(self) -> dict[str, Any]:
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != 1:
            raise ValueError("state schema mismatch")
        value.setdefault("analyses", [])
        value.setdefault("reviews", [])
        value.setdefault("last_update", None)
        return value

    def save_state(self, value: dict[str, Any]) -> None:
        atomic_json(self.state_path, value)

    @staticmethod
    def _stage_bytes(path: Path, data: bytes) -> Path:
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
    def _restore_bytes(path: Path, previous: bytes | None) -> None:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        staged = Store._stage_bytes(path, previous)
        os.replace(staged, path)

    def commit_network_update(self, raw: bytes, evidence: dict[str, Any], fetched_at: str) -> dict[str, Any]:
        value = validate_knowledge(json.loads(raw.decode("utf-8-sig")))
        state = self.load_state()
        state["last_update"] = fetched_at

        knowledge_bytes = raw
        state_bytes = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        evidence_bytes = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

        old = {
            self.knowledge_path: self.knowledge_path.read_bytes() if self.knowledge_path.exists() else None,
            self.state_path: self.state_path.read_bytes() if self.state_path.exists() else None,
            self.evidence_path: self.evidence_path.read_bytes() if self.evidence_path.exists() else None,
        }
        staged: dict[Path, Path] = {}
        committed: list[Path] = []
        try:
            staged[self.knowledge_path] = self._stage_bytes(self.knowledge_path, knowledge_bytes)
            staged[self.state_path] = self._stage_bytes(self.state_path, state_bytes)
            staged[self.evidence_path] = self._stage_bytes(self.evidence_path, evidence_bytes)

            for target in (self.evidence_path, self.state_path, self.knowledge_path):
                os.replace(staged.pop(target), target)
                committed.append(target)

            self.load_knowledge()
            self.load_state()
            reloaded = json.loads(self.evidence_path.read_text(encoding="utf-8"))
            if reloaded.get("status") != "PASS" or reloaded.get("knowledge_sha256") != evidence.get("knowledge_sha256"):
                raise ValueError("network evidence post-write verification failed")
            return value
        except Exception:
            for target in reversed(committed):
                try:
                    self._restore_bytes(target, old[target])
                except Exception:
                    pass
            raise
        finally:
            for tmp in staged.values():
                tmp.unlink(missing_ok=True)

    def append_analysis(self, item: dict[str, Any]) -> None:
        state = self.load_state()
        state["analyses"].append(item)
        state["analyses"] = state["analyses"][-100:]
        self.save_state(state)

    def append_review(self, item: dict[str, Any]) -> None:
        state = self.load_state()
        state["reviews"].append(item)
        state["reviews"] = state["reviews"][-200:]
        self.save_state(state)


class GoalEngine:
    def __init__(self, store: Store):
        self.store = store

    @property
    def classics(self) -> list[dict[str, Any]]:
        return self.store.load_knowledge()["classics"]

    def classify(self, goal: str) -> list[tuple[str, int]]:
        text = goal.strip()
        scores = []
        for scenario, words in SCENARIO_KEYWORDS.items():
            score = sum(1 for w in words if w in text)
            if score:
                scores.append((scenario, score))
        if not scores:
            return [("general", 1)]
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:3]

    def _select_classics(self, scenarios: list[str]) -> list[dict[str, Any]]:
        scored = []
        for row in self.classics:
            overlap = sum(1 for s in scenarios if s in row["scenarios"])
            if overlap:
                scored.append((overlap, int(row.get("priority", 0)), row))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]["title"]))
        if not scored:
            return self.classics[:4]
        return [x[2] for x in scored[:4]]

    def analyze(self, goal: str) -> dict[str, Any]:
        goal = goal.strip()
        if len(goal) < 4:
            raise ValueError("请把目标写得更具体一些")
        classified = self.classify(goal)
        scenarios = [x[0] for x in classified if x[0] != "general"] or ["general"]
        selected = self._select_classics(scenarios)
        questions: list[str] = []
        for s in scenarios:
            questions.extend(DEFAULT_QUESTIONS.get(s, DEFAULT_QUESTIONS["general"]))
        questions = list(dict.fromkeys(questions))[:6]

        methods = []
        for row in selected:
            method = row["methods"][0]
            methods.append({
                "title": row["title"],
                "method": method["name"],
                "prompt": method["prompt"],
                "source_note": row["source_note"],
                "boundary": row["boundary"],
                "authorship_status": row.get("authorship_status", "常规传世文本"),
            })

        result = {
            "goal": goal,
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "scenarios": [SCENARIO_LABELS.get(s, s) for s in scenarios],
            "questions": questions,
            "methods": methods,
            "five_whys": [
                "为什么我认为这条路径能达成目标？",
                "这个判断依赖的关键事实是什么？",
                "这些事实是已验证，还是推测/听说？",
                "如果关键事实相反，我的方案还成立吗？",
                "最小成本验证这条假设的方法是什么？",
            ],
            "reverse_validation": [
                "假设当前结论完全错误，哪些现象仍能被解释？",
                "寻找至少一个能推翻主判断的反例。",
                "把最强反方观点写出来，再决定是否行动。",
            ],
            "status": "ACTION_HYPOTHESIS",
            "note": "经典提供的是分析视角，不是自动正确的答案；先验证事实，再做行动。",
        }
        self.store.append_analysis({
            "timestamp": result["timestamp"],
            "goal": goal,
            "scenarios": result["scenarios"],
            "status": result["status"],
        })
        return result

    def stats(self) -> dict[str, Any]:
        state = self.store.load_state()
        classics = self.classics
        disputed = sum(1 for r in classics if r.get("authorship_status") not in (None, "常规传世文本"))
        return {
            "classics": len(classics),
            "analyses": len(state["analyses"]),
            "reviews": len(state["reviews"]),
            "disputed": disputed,
            "last_update": state.get("last_update") or "尚未联网更新",
        }


class ReviewEngine:
    def __init__(self, store: Store):
        self.store = store

    def save(self, goal: str, action: str, result: str, lesson: str) -> dict[str, Any]:
        fields = [goal.strip(), action.strip(), result.strip(), lesson.strip()]
        if any(len(x) < 2 for x in fields):
            raise ValueError("目标、行动、结果、教训都需要填写")
        item = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "goal": fields[0],
            "action": fields[1],
            "result": fields[2],
            "lesson": fields[3],
        }
        self.store.append_review(item)
        return item

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        return list(reversed(self.store.load_state()["reviews"][-limit:]))


class MaintenanceEngine:
    PARSER_VERSION = "guoxue-knowledge-parser-v0.2"

    def __init__(self, store: Store, net: NetClient | None = None):
        self.store = store
        self.net = net or NetClient(connect_timeout=5, read_timeout=20, max_attempts=3)

    def _fetch_manifest(self) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        failures = []
        for index, url in enumerate(MANIFEST_URLS, 1):
            source_id = f"manifest_distribution_{index}"
            try:
                raw, receipt = self.net.get_bytes(url, source_id=source_id)
                value = json.loads(raw.decode("utf-8-sig"))
                if value.get("schema") != 1:
                    raise ValueError("manifest schema mismatch")
                if not isinstance(value.get("version"), str) or not value["version"].strip():
                    raise ValueError("manifest version missing")
                if not isinstance(value.get("data_url"), str) or not value["data_url"].startswith("https://"):
                    raise ValueError("manifest data_url must be HTTPS")
                digest = str(value.get("sha256") or "").lower()
                if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                    raise ValueError("manifest sha256 invalid")
                return value, receipt.to_dict(), raw
            except Exception as exc:
                failures.append({
                    "source_id": source_id,
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                    "attempts": list(getattr(exc, "glp_attempts", ()) or ()),
                })
        raise RuntimeError("all manifest distribution paths failed: " + json.dumps(failures, ensure_ascii=False))

    def one_click_update(self) -> dict[str, Any]:
        manifest, manifest_receipt, manifest_raw = self._fetch_manifest()
        data_raw, data_receipt_obj = self.net.get_bytes(str(manifest["data_url"]), source_id="knowledge_data")
        digest = hashlib.sha256(data_raw).hexdigest()
        if digest.lower() != str(manifest["sha256"]).lower():
            raise ValueError(f"knowledge SHA256 mismatch expected={manifest['sha256']} actual={digest}")
        value = validate_knowledge(json.loads(data_raw.decode("utf-8-sig")))
        data_receipt = data_receipt_obj.to_dict()
        evidence = {
            "schema": "guoxue-network-evidence-v2",
            "status": "PASS",
            "parser_version": self.PARSER_VERSION,
            "manifest_version": manifest["version"],
            "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "knowledge_sha256": digest,
            "manifest_source": manifest_receipt,
            "knowledge_source": data_receipt,
            "fetched_at": data_receipt["fetched_at"],
            "classics": len(value["classics"]),
        }
        self.store.commit_network_update(data_raw, evidence, fetched_at=data_receipt["fetched_at"])
        return {
            "status": "PASS",
            "version": value.get("version"),
            "classics": len(value["classics"]),
            "sha256": digest,
            "source": data_receipt,
            "manifest_source": manifest_receipt,
            "evidence": evidence,
        }

    def one_click_repair(self) -> dict[str, Any]:
        checks = []
        try:
            kb = self.store.load_knowledge()
            checks.append(("Knowledge DB", "PASS", f'{len(kb["classics"])} classics'))
        except Exception as exc:
            shutil.copy2(bundled_path("data", "knowledge.json"), self.store.knowledge_path)
            kb = self.store.load_knowledge()
            checks.append(("Knowledge DB", "REPAIRED", str(exc)))

        try:
            state = self.store.load_state()
            checks.append(("State DB", "PASS", f'{len(state["reviews"])} reviews'))
        except Exception as exc:
            atomic_json(self.store.state_path, {"schema": 1, "analyses": [], "reviews": [], "last_update": None})
            checks.append(("State DB", "REPAIRED", str(exc)))

        try:
            self.store.load_knowledge()
            self.store.load_state()
            final = "PASS"
        except Exception as exc:
            checks.append(("Final Gate", "FAIL", str(exc)))
            final = "FAIL"
        return {"status": final, "checks": checks}


def self_test(root: Path | None = None) -> dict[str, Any]:
    temp_ctx = tempfile.TemporaryDirectory() if root is None else None
    try:
        work = Path(temp_ctx.name) if temp_ctx else Path(root)
        store = Store(work)
        goal = GoalEngine(store)
        review = ReviewEngine(store)
        maintenance = MaintenanceEngine(store)
        a = goal.analyze("我要和长期合作伙伴谈价格，怎样判断底线和筹码并控制风险？")
        review.save("谈合作", "先确认替代方案", "对方给出更清晰条件", "下次先验证对方真实时间压力")
        repair = maintenance.one_click_repair()
        stats = goal.stats()
        checks = {
            "seed_database": len(goal.classics) >= 20,
            "goal_classification": "谈判与合作" in a["scenarios"],
            "multi_source_methods": len(a["methods"]) >= 3,
            "five_whys": len(a["five_whys"]) == 5,
            "reverse_validation": len(a["reverse_validation"]) >= 3,
            "review_saved": stats["reviews"] >= 1,
            "repair_gate": repair["status"] == "PASS",
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "version": APP_VERSION}
    finally:
        if temp_ctx:
            temp_ctx.cleanup()
