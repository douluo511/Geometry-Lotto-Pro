from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse

from contracts import parse_version
from domain import UpdateResult
from net_client import NetClient, NetError
from storage import KnowledgeStorage
from engine import analyze, self_test
from pathlib import Path
from software_update import UpdateEnvironmentBlocked, launch_independent_updater, software_update_environment_status

SOFTWARE_VERSION = "0.4.0"


def _semantic_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _source_id(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host or url


class PsychologyService:
    def __init__(self, storage: KnowledgeStorage, net_client: NetClient, knowledge_url: str | list[str] | tuple[str, ...]):
        self.storage = storage
        self.net_client = net_client
        if isinstance(knowledge_url, str):
            self.knowledge_urls = (knowledge_url,)
        else:
            self.knowledge_urls = tuple(str(x) for x in knowledge_url)
        if not self.knowledge_urls:
            raise ValueError("at least one knowledge source is required")
        self.knowledge = self.storage.load_knowledge()

    @property
    def knowledge_url(self) -> str:
        return self.knowledge_urls[0]

    def analyze_text(self, text: str, baseline_text: str = ""):
        return analyze(text, self.knowledge, baseline_text)

    def update_knowledge(self) -> UpdateResult:
        # A production network PASS requires at least two independently
        # addressable distribution paths that return the same validated
        # semantic package. One-source availability is useful diagnostics but
        # remains fail-closed for the release/network gate.
        if len(self.knowledge_urls) < 2:
            raise NetError("trusted source redundancy unavailable: at least two distribution paths are required")

        successes: list[tuple[dict, object]] = []
        failures: list[str] = []
        for url in self.knowledge_urls:
            try:
                payload, source = self.net_client.get_json(url, source_id=_source_id(url))
                successes.append((payload, source))
            except Exception as exc:
                failures.append(f"{_source_id(url)}: {type(exc).__name__}: {exc}")

        if len(successes) < 2:
            raise NetError(
                "trusted multi-source quorum failed; "
                f"successes={len(successes)} failures={' | '.join(failures) or 'none'}"
            )

        semantic_hashes = {_semantic_hash(payload) for payload, _ in successes}
        versions = {str(payload.get("version")) for payload, _ in successes}
        source_ids = {source.source_id for _, source in successes}
        if len(source_ids) < 2:
            raise NetError("source redundancy invalid: successful paths do not have distinct source identities")
        if len(semantic_hashes) != 1 or len(versions) != 1:
            raise NetError(
                "source conflict: validated distribution paths disagree "
                f"semantic_hashes={sorted(semantic_hashes)} versions={sorted(versions)}"
            )

        remote = successes[0][0]
        sources = tuple(source for _, source in successes)
        local = self.storage.load_knowledge()
        if parse_version(remote["version"]) < parse_version(local["version"]):
            raise NetError(
                f"remote downgrade rejected: remote={remote['version']} local={local['version']}"
            )

        if remote == local:
            return UpdateResult(
                "NOOP",
                "双分发源一致，当前已是最新知识库。",
                local["version"],
                sources[0],
                sources,
                "PASS",
            )

        self.storage.replace_knowledge(remote, sources)
        self.knowledge = self.storage.load_knowledge()
        return UpdateResult(
            "UPDATED",
            "双分发源一致，知识库原子更新成功。",
            self.knowledge["version"],
            sources[0],
            sources,
            "PASS",
        )

    def repair(self):
        result = self.storage.repair_knowledge()
        self.knowledge = self.storage.load_knowledge()
        post_test = self_test()
        result.update(post_test)
        result["post_repair_self_test"] = {"status": "PASS" if all(x == "PASS" for x in post_test.values()) else "FAIL", "checks": post_test}
        result["status"] = "PASS" if result.get("knowledge") == "PASS" and result["post_repair_self_test"]["status"] == "PASS" else "FAIL"
        return result

    def one_click_update(self):
        """Hand software replacement to the product's independent Updater."""
        try:
            return launch_independent_updater(data_root=self.storage.local_path.parent, current_version=SOFTWARE_VERSION)
        except UpdateEnvironmentBlocked as exc:
            return {"status": "BLOCKED", "operation": "software_update", "action": "RELEASE_DEPENDENCY_UNAVAILABLE", "detail": str(exc)}

    def software_update_status(self, *, main_exe: Path):
        return software_update_environment_status(main_exe=main_exe, current_version=SOFTWARE_VERSION)

    def health(self):
        return {
            "knowledge_version": self.knowledge["version"],
            "hypothesis_count": len(self.knowledge.get("hypotheses", [])),
            "configured_source_count": len(self.knowledge_urls),
            **self_test(),
        }


def create_service(local_path, bundled_path, knowledge_url: str | list[str] | tuple[str, ...]) -> PsychologyService:
    """Application composition root. UI receives only the Service boundary."""
    return PsychologyService(
        KnowledgeStorage(local_path=local_path, bundled_path=bundled_path),
        NetClient(connect_timeout=5.0, read_timeout=12.0, retries=2),
        knowledge_url,
    )
