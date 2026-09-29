from __future__ import annotations
import json
import os
from pathlib import Path

from contracts import SOURCE_REGISTRY, validate_knowledge
from core import APP_VERSION
from engine import HumanNatureEngine
from evidence import EvidenceLedger
from net_client import NetClient
from storage import KnowledgeStorage

def _default_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "HumanNaturePro"
    root.mkdir(parents=True, exist_ok=True)
    return root

class HumanNatureService:
    def __init__(self, storage: KnowledgeStorage, net: NetClient, evidence: EvidenceLedger):
        self.storage = storage
        self.net = net
        self.evidence = evidence
        self.engine = HumanNatureEngine(self.storage.load())

    def analyze(self, text: str, goal: str):
        result = self.engine.analyze(text, goal)
        self.evidence.record("ENGINE", "PASS", hypotheses=len(result.get("hypotheses", [])))
        return result

    def update_all(self):
        url = SOURCE_REGISTRY["knowledge"]["url"]
        try:
            raw, receipt = self.net.get(url)
            data = validate_knowledge(json.loads(raw.decode("utf-8-sig")))
            current=self.storage.load()
            def _v(v): return tuple(int(x) if str(x).isdigit() else 0 for x in str(v).replace("-",".").split("."))
            if _v(data.get("knowledge_version","0")) < _v(current.get("knowledge_version","0")):
                self.evidence.record("NETWORK","PASS",source=receipt,update_status="NOOP_OLDER_REMOTE")
                return {"status":"PASS","update_status":"NOOP_OLDER_REMOTE","knowledge_version":current.get("knowledge_version"),"source":receipt}
            self.storage.replace(raw)
            self.engine.set_knowledge(self.storage.load())
            self.evidence.record("NETWORK", "PASS", source=receipt)
            return {
                "status": "PASS",
                "knowledge_version": data.get("knowledge_version", "unknown"),
                "source": receipt,
            }
        except Exception as exc:
            self.evidence.record("NETWORK", "FAIL", error=str(exc))
            raise

    def repair(self):
        result = self.storage.repair()
        self.engine.set_knowledge(self.storage.load())
        self.evidence.record("STORAGE", result["status"], result=result)
        return result

    def advanced_analysis(self, result):
        return {
            "app_version": APP_VERSION,
            "analysis": result,
            "guardrails": [
                "hypotheses_not_facts",
                "no_coercion",
                "no_vulnerability_exploitation",
            ],
            "evidence_path": str(self.evidence.path),
        }

    def health(self):
        data = self.storage.load()
        return {
            "status": "PASS",
            "version": APP_VERSION,
            "knowledge_version": data.get("knowledge_version", "unknown"),
            "rules": len(data["rules"]),
            "hypothesis_templates": len(data.get("hypothesis_templates", [])),
        }

    def self_test(self):
        health = self.health()
        result = self.analyze(
            "客户说价格太高，一直拖延付款，我不清楚他有没有最终决定权。",
            "保证回款，同时保留长期合作",
        )
        checks = {
            "knowledge": health["rules"] > 0,
            "hypotheses": len(result["hypotheses"]) >= 4,
            "information_gain": result["strategies"][0]["information_gain"] >= 1,
            "reverse_validation": bool(result["reverse_validation"]),
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "version": APP_VERSION,
            "checks": checks,
        }

    def smoke_actions(self):
        sample = self.analyze("对方说预算不足，需要再考虑。", "保护利益并保持合作")
        self.advanced_analysis(sample)
        self.repair()
        self.health()
        return {"status": "PASS"}

def create_service(root: Path | None = None, bundled_path: Path | None = None, net: NetClient | None = None):
    if bundled_path is None:
        bundled_path = Path(__file__).resolve().parent / "knowledge_base.json"
    root = root or _default_root()
    return HumanNatureService(
        KnowledgeStorage(root, bundled_path),
        net or NetClient(),
        EvidenceLedger(Path(root) / "evidence.jsonl"),
    )

def format_report(result):
    return HumanNatureEngine().format_report(result)
