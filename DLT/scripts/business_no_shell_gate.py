from __future__ import annotations

import inspect
import json
from pathlib import Path

from glp.constants import (
    APP_VERSION, BACK_MAX, BACK_PICK, FOUR_ENTRIES, FRONT_MAX, FRONT_PICK,
    GAME, PROMOTION_POLICY,
)
from glp.domain import Draw
from glp.delivery import (
    UpdaterClient, create_backup, export_evidence, launch_software_update,
    read_software_update_result, restore_backup, source_health, verify_export,
)
from glp.engine import BASE_MODELS, model_identity
from glp.net_client import NetClient
from glp.service import LottoService, self_test
from glp.storage import Store
import glp.gui as gui
import glp.service as service
import glp.sources as sources
from final_gate import derive
from completion_boundary import static_report


def check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def main() -> int:
    checks: list[dict] = []

    checks.append(check(
        "DLT domain contract",
        GAME == "DLT" and (FRONT_MAX, FRONT_PICK, BACK_MAX, BACK_PICK) == (35, 5, 12, 2)
        and hasattr(Draw, "from_dict") and hasattr(Draw, "validate"),
        f"game={GAME}; front={FRONT_PICK}/{FRONT_MAX}; back={BACK_PICK}/{BACK_MAX}",
    ))

    source_urls = (
        str(getattr(sources, "NATIONAL_URL", "")),
        str(getattr(sources, "JIANGSU_DATA_PAGE", "")),
        str(getattr(sources, "GANSU_HISTORY_URL", "")),
    )
    checks.append(check(
        "Independent official source paths",
        all(x.startswith("https://") for x in source_urls)
        and len({x.split("/")[2] for x in source_urls}) >= 3,
        json.dumps(source_urls, ensure_ascii=False),
    ))

    required_policy = {
        "windows", "seeds", "walk_forward_points", "untouched_holdout",
        "min_era_count", "bootstrap_rounds", "permutation_rounds",
        "null_worlds", "synthetic_null_worlds", "ablation_points",
        "min_prospective_replays",
    }
    checks.append(check(
        "Frozen scientific protocol inventory",
        required_policy.issubset(PROMOTION_POLICY)
        and len(PROMOTION_POLICY["windows"]) >= 3
        and len(PROMOTION_POLICY["seeds"]) >= 5,
        f"policy={PROMOTION_POLICY.get('protocol_version')}; keys={sorted(required_policy)}",
    ))

    ident = model_identity()
    checks.append(check(
        "Candidate model pool and conservative production fallback",
        len(BASE_MODELS) >= 7
        and ident["production_weights"].get("uniform_baseline") == 1.0
        and ident["production_weights"].get("research_ensemble") == 0.0,
        f"models={list(BASE_MODELS)}; production={ident['production_weights']}",
    ))

    checks.append(check(
        "Four production entries",
        tuple(FOUR_ENTRIES) == ("预测下一期", "一键更新", "一键修复", "高级分析")
        and all(callable(getattr(LottoService, n, None)) for n in ("predict", "update", "repair", "audit")),
        json.dumps(list(FOUR_ENTRIES), ensure_ascii=False),
    ))

    audit_source = inspect.getsource(LottoService.audit)
    checks.append(check(
        "Audit/prediction isolation",
        "self.predict(" not in audit_source
        and ".freeze(" not in audit_source
        and "formal_freeze_written" in audit_source,
        "audit must use in-memory preview and must not create a formal prediction Freeze",
    ))

    self_source = inspect.getsource(service.self_test)
    checks.append(check(
        "Self-test/user-data isolation",
        "TemporaryDirectory" in self_source and "_self_test_in_isolated_store" in self_source,
        "synthetic test data is created only inside a disposable child directory",
    ))

    gui_source = inspect.getsource(gui)
    checks.append(check(
        "No prediction advantage overclaim",
        "不代表更高中奖概率" in gui_source
        and "未成年人不得购彩" in gui_source
        and "NO_EDGE" in gui_source,
        "GUI contains explicit no-edge/no-guarantee boundary",
    ))

    production_files = [
        Path(service.__file__).resolve(),
        Path(sources.__file__).resolve(),
        Path(gui.__file__).resolve(),
        Path(inspect.getfile(Store)).resolve(),
        Path(inspect.getfile(NetClient)).resolve(),
        Path(inspect.getfile(UpdaterClient)).resolve(),
    ]
    banned = ("StubService", "unittest.mock", "Mock(", "NotImplementedError", "TODO: production", "pass  # production")
    shell_hits: list[str] = []
    for path in production_files:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                shell_hits.append(f"{path.name}:{token}")

    interfaces_ok = (
        callable(getattr(NetClient, "get", None))
        and callable(getattr(Draw, "from_dict", None))
        and callable(getattr(Draw, "validate", None))
        and callable(getattr(Store, "save_dataset", None))
        and callable(getattr(Store, "load_draws", None))
        and callable(getattr(Store, "integrity_check", None))
        and callable(getattr(Store, "baseline_integrity_check", None))
        and callable(getattr(Store, "validate_raw_evidence", None))
        and callable(self_test)
        and all(callable(getattr(LottoService, x, None)) for x in ("update", "predict", "audit", "repair", "self_test"))
        and all(callable(getattr(UpdaterClient, x, None)) for x in ("update", "repair"))
        and all(callable(x) for x in (
            launch_software_update, read_software_update_result,
            create_backup, restore_backup, export_evidence, verify_export,
            source_health, derive,
        ))
    )
    checks.append(check(
        "No-shell production interfaces",
        interfaces_ok and not shell_hits,
        f"interfaces_ok={interfaces_ok}; banned_hits={shell_hits}",
    ))

    report = static_report(checks, APP_VERSION)
    out = Path("artifacts/business_no_shell_gate.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
