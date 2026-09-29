from __future__ import annotations
import json
import os
from pathlib import Path

from contracts import validate_snapshot


class SnapshotStorage:
    def __init__(self, root: Path | None = None):
        if root is None:
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            root = (Path(base) if base else Path.home() / ".investment_finance_pro") / "InvestmentFinancePro"
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "snapshot.json"

    def path(self) -> Path:
        return self._path

    def read(self):
        if not self._path.exists():
            return None
        try:
            return validate_snapshot(json.loads(self._path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def write(self, data: dict):
        validate_snapshot(data)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        return self.read()

    def repair(self):
        checks=[]
        if self._path.exists():
            try:
                value=json.loads(self._path.read_text(encoding="utf-8"))
                validate_snapshot(value)
                checks.append({"check":"snapshot_schema","status":"PASS"})
            except Exception as exc:
                backup=self._path.with_suffix(".corrupt.json")
                try:
                    os.replace(self._path,backup)
                    checks.append({"check":"snapshot_schema","status":"REPAIRED","detail":str(exc),"backup":str(backup)})
                except Exception as move_exc:
                    checks.append({"check":"snapshot_schema","status":"FAILED","detail":str(move_exc)})
        else:
            checks.append({"check":"snapshot_schema","status":"PASS","detail":"no snapshot yet"})
        probe=self.root/"write_probe.tmp"
        try:
            probe.write_text("ok",encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks.append({"check":"storage_write","status":"PASS","detail":str(self.root)})
        except Exception as exc:
            checks.append({"check":"storage_write","status":"FAILED","detail":str(exc)})
        overall="PASS" if all(x["status"] in {"PASS","REPAIRED"} for x in checks) else "FAILED"
        return {"status":"PASS" if overall=="PASS" else "FAIL","overall":overall,"checks":checks}
