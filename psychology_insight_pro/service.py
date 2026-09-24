from __future__ import annotations

from contracts import parse_version
from domain import UpdateResult
from net_client import NetClient
from storage import KnowledgeStorage
from engine import analyze, self_test


class PsychologyService:
    def __init__(self, storage: KnowledgeStorage, net_client: NetClient, knowledge_url: str):
        self.storage = storage
        self.net_client = net_client
        self.knowledge_url = knowledge_url
        self.knowledge = self.storage.load_knowledge()

    def analyze_text(self, text: str, baseline_text: str = ""):
        return analyze(text, self.knowledge, baseline_text)

    def update_knowledge(self) -> UpdateResult:
        remote, source = self.net_client.get_json(self.knowledge_url)
        local = self.storage.load_knowledge()
        if parse_version(remote["version"]) < parse_version(local["version"]):
            return UpdateResult("NOOP", "远端版本低于本地版本，拒绝降级。", local["version"], source)
        if remote == local:
            return UpdateResult("NOOP", "已是最新知识库。", local["version"], source)
        self.storage.replace_knowledge(remote, source)
        self.knowledge = self.storage.load_knowledge()
        return UpdateResult("UPDATED", "知识库更新成功。", self.knowledge["version"], source)

    def repair(self):
        result = self.storage.repair_knowledge()
        self.knowledge = self.storage.load_knowledge()
        result.update(self_test())
        return result

    def health(self):
        return {
            "knowledge_version": self.knowledge["version"],
            "hypothesis_count": len(self.knowledge.get("hypotheses", [])),
            **self_test(),
        }


def create_service(local_path, bundled_path, knowledge_url: str) -> PsychologyService:
    """Application composition root. UI receives only the Service boundary."""
    return PsychologyService(
        KnowledgeStorage(local_path=local_path, bundled_path=bundled_path),
        NetClient(timeout=12.0, retries=2),
        knowledge_url,
    )
