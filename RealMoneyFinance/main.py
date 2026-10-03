from __future__ import annotations

from pathlib import Path
import json
import os
import sys

from app.service import FinanceService


def user_root() -> Path:
    explicit = os.environ.get("REAL_MONEY_FINANCE_ROOT")
    if explicit:
        return Path(explicit)
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "RealMoneyFinance"
    return Path.cwd() / "userdata"


def main() -> int:
    root = user_root()
    if "--self-test" in sys.argv:
        service = FinanceService(root)
        result = {
            "status": "PASS",
            "storage_integrity": service.storage.integrity_check(),
            "root": str(root),
            "final_gate": "FAIL",
        }
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False))
        return 0 if result["storage_integrity"] == "ok" else 1

    from app.ui import FinanceDesktop
    app = FinanceDesktop(root)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
