from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--marker", required=True)
    a = p.parse_args()

    exe = Path(a.exe)
    evidence_path = Path(a.evidence)
    marker = Path(a.marker)
    if not exe.exists() or not evidence_path.exists():
        return 2

    data = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    buttons = data.get("buttons")
    button_checks = []

    if isinstance(buttons, list):
        for expected_index, item in enumerate(buttons, start=1):
            before = item.get("before_sha256")
            after = item.get("after_sha256")
            button_checks.append(
                item.get("button_index") == expected_index
                and item.get("status") == "PASS"
                and item.get("visual_changed") is True
                and isinstance(before, str)
                and isinstance(after, str)
                and bool(before)
                and bool(after)
                and before != after
            )

    strict_clicks_ok = (
        data.get("schema") == "physical-gui-click-smoke-v1"
        and data.get("status") == "PASS"
        and isinstance(buttons, list)
        and len(buttons) == 4
        and len(button_checks) == 4
        and all(button_checks)
    )

    data["button_count"] = len(buttons) if isinstance(buttons, list) else 0
    data["strict_click_evidence"] = "PASS" if strict_clicks_ok else "FAIL"
    data["exe_sha256"] = sha256(exe)
    evidence_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ok = strict_clicks_ok and data["button_count"] == 4
    if ok:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("PASS\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "PASS" if ok else "FAIL",
                "exe_sha256": data["exe_sha256"],
                "button_count": data["button_count"],
                "strict_click_evidence": data["strict_click_evidence"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
