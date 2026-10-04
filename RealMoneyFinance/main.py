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
    if "--startup-ack" in sys.argv:
        import hashlib
        import uuid
        ack = Path(sys.argv[sys.argv.index("--startup-ack") + 1])
        nonce = sys.argv[sys.argv.index("--startup-nonce") + 1]
        def acknowledge_startup():
            if not app.winfo_ismapped():
                app.after(100, acknowledge_startup)
                return
            with Path(sys.executable).open("rb") as stream:
                binary_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            obj={"status":"PASS", "product":PRODUCT, "version":VERSION, "source_sha":SOURCE_SHA,
                 "exe_sha256":binary_hash, "nonce":nonce, "gui_mapped":True, "process_id":os.getpid()}
            ack.parent.mkdir(parents=True, exist_ok=True)
            temporary=ack.with_suffix("."+uuid.uuid4().hex+".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(obj,stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,ack)
        app.after(100, acknowledge_startup)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

