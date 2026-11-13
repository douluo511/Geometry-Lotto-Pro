"""Inspect exact archived history shape before any future-target SHADOW run."""
from pathlib import Path
import gzip
import json
from research.harness_v46 import core
def main():
    path = Path(__file__).parent / "evidence" / "recency_ablation_20261024" / "observations.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    print("bundle keys", sorted(data))
    for game in ("SSQ","DLT"):
        rows=data[game]
        print("game", game, "n", len(rows), "first", rows[0], "last", rows[-1])
        print("last3", rows[-3:])
        print("valid", len(rows)>120)
    print("core_source_sha256",core.model_source_sha256())
if __name__=="__main__":
    main()
