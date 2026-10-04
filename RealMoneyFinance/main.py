from __future__ import annotations

from pathlib import Path
import json
import os
import sys

from app.service import FinanceService
from app.build_info import PRODUCT, VERSION, SOURCE_SHA


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
            "product": PRODUCT,
            "version": VERSION,
            "source_sha": SOURCE_SHA,
        }
        if "--health-report" in sys.argv:
            import hashlib
            report = Path(sys.argv[sys.argv.index("--health-report") + 1])
            result["nonce"] = sys.argv[sys.argv.index("--health-nonce") + 1]
            with Path(sys.executable).open("rb") as stream:
                result["exe_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False))
        return 0 if result["storage_integrity"] == "ok" else 1

    from app.ui import FinanceDesktop
    app = FinanceDesktop(root)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

