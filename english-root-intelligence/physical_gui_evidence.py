from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from gate_common import current_report

LABELS = ["今日学习", "一键更新", "一键修复", "高级分析"]


def validate_physical(report: dict, source_sha: str | None, *, require_configured: bool = False) -> bool:
    """Bind physical mouse events, screenshot bytes and completed Service results."""
    try:
        if (not current_report(report, source_sha) or report.get("status") != "PASS"
                or report.get("schema") != "english-root-physical-gui-bound-v1"
                or report.get("activation") != "foreground cursor + mouse_event LEFTDOWN/LEFTUP"):
            return False
        buttons, actions = report.get("buttons"), report.get("service_actions")
        if not isinstance(buttons, list) or not isinstance(actions, list) or len(buttons) != 4 or len(actions) != 4:
            return False
        for index, (label, button, action) in enumerate(zip(LABELS, buttons, actions), 1):
            if (button.get("button_index") != index or button.get("status") != "PASS"
                    or button.get("visual_changed") is not True or int(button.get("target_pid", 0)) <= 0
                    or action.get("label") != label or action.get("process_id") != button["target_pid"]
                    or action.get("exe_sha256") != report.get("exe_sha256")
                    or action.get("source_sha") != source_sha):
                return False
            if any(str(action.get(key)) != str(report.get(key)) for key in ("github_run_id", "github_run_attempt")):
                return False
            if not (datetime.fromisoformat(button["clicked_at"]) <= datetime.fromisoformat(action["recorded_at"])
                    <= datetime.fromisoformat(button["completed_at"])):
                return False
            for phase in ("before", "after"):
                image = Path(button.get(phase + "_screenshot") or "")
                if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != button.get(phase + "_sha256"):
                    return False
            if button.get("before_sha256") == button.get("after_sha256"):
                return False
            result = action.get("result") or {}
            if label == "一键更新":
                configured = (result.get("status") == "PASS" and result.get("action") == "UPDATER_HANDOFF"
                              and result.get("operation") == "software_update"
                              and int(result.get("updater_pid", 0)) > 0 and result.get("requires_parent_exit") is True)
                blocked = result.get("status") == "BLOCKED" and bool(result.get("error"))
                if not configured and (require_configured or not blocked):
                    return False
                if report.get("update_mode") != ("ConfiguredRelease" if configured else "BlockedRelease"):
                    return False
            elif result.get("status") != "PASS":
                return False
            elif label == "今日学习":
                if result.get("root_count") != 3 or len(set(result.get("morphemes") or [])) != 3:
                    return False
            elif label == "一键修复":
                checks = result.get("checks") or []
                if len(checks) < 2 or any(len(row) != 3 or row[1] not in {"PASS", "REPAIRED"} for row in checks):
                    return False
            elif label == "高级分析":
                stats = result.get("stats") or {}
                if int(stats.get("root_total", 0)) < 10 or any(key not in stats for key in ("coverage_pct", "practice_repetitions", "word_analyses")):
                    return False
        return True
    except (TypeError, ValueError, KeyError, OSError):
        return False
