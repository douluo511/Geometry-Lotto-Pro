import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater_runtime.updater import download, fetch_manifest, local_file_path

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    source = root / "space 中文 fixture.json"
    source.write_text(json.dumps({"version": "fixture"}), encoding="utf-8")
    canonical = source.as_uri()
    assert local_file_path(canonical) == source
    assert fetch_manifest(canonical) == {"version": "fixture"}
    target = root / "copied.json"
    download(canonical, target)
    assert target.read_bytes() == source.read_bytes()
    if os.name == "nt":
        legacy = "file://" + str(source)
        assert local_file_path(legacy) == source
        download(legacy, target)
        assert target.read_bytes() == source.read_bytes()
    for bad in ["file://remote.example/share/data.zip", "file://", "relative://fixture.json", canonical + "?extra=1", canonical + "#fragment"]:
        try:
            local_file_path(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted invalid offline file URI: " + bad)
    try:
        download("http://example.invalid/update.zip", target)
    except ValueError:
        pass
    else:
        raise AssertionError("production HTTPS boundary was weakened")

print("LOCAL FILE URI WINDOWS / HTTPS BOUNDARY TEST PASS")
