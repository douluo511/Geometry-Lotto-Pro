from __future__ import annotations
from pathlib import Path

from service import create_service


def app_data_dir()->Path:
    import os
    root=Path(os.environ.get("LOCALAPPDATA") or Path.home())/"HumanNaturePro"
    root.mkdir(parents=True,exist_ok=True)
    return root


def update_knowledge(timeout:int=12)->dict:
    # Compatibility entry point. Production networking is owned by NetClient.
    service=create_service(root=app_data_dir())
    return service.update_all()


def repair_knowledge(bundled_path:Path)->dict:
    service=create_service(root=app_data_dir(),bundled_path=bundled_path)
    result=service.repair()
    return {"ok":result.get("status")=="PASS",**result}
