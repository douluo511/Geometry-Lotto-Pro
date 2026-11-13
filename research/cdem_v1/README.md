# CDEM V1.0 — SSQ / DLT evolutionary research (2026-11-13)

Research branch `research/cdem-v1-20261113`: 10 G0 → 20 G1 → 40 G2 → 80 G3 **per game**. Selection: 300 historical draws. Final holdout: 200 later draws. The holdout was not used to choose the finalists. No demonstrated predictive edge.

- `reports/2026-11-13-{ssq,dlt}.json`: original Git blob identity, post-snapshot historical draw additions, model IDs, genealogy, weights, selection scores, holdout scores, and forecast.
- `seals/2026-11-13-{ssq,dlt}.json`: source cutoff and candidate predictions stored on a dated Git commit; normal Git branch history is not independently tamper-proof.
- `score.py`: create-only post-draw score receipts with a source URL and SHA-256. **It does not itself verify official web content**.

When official outcomes are independently confirmed, run from the repository root:

```powershell
python -m research.cdem_v1.score --seal research/cdem_v1/seals/2026-11-13-ssq.json --issue 2026131 --front <six verified red numbers> --back <one verified blue number> --evidence-url <official HTTPS URL> --evidence-sha256 <captured page bytes SHA256> --out research/cdem_v1/settlements/2026131-ssq.json
python -m research.cdem_v1.score --seal research/cdem_v1/seals/2026-11-13-dlt.json --issue 26130 --front <five verified front numbers> --back <two verified back numbers> --evidence-url <official HTTPS URL> --evidence-sha256 <captured page bytes SHA256> --out research/cdem_v1/settlements/26130-dlt.json
```

These are command templates, not validated real draws. An output file must not already exist; the receipt is written with exclusive create mode.

Run unit tests: `python -m unittest discover -s research/cdem_v1/tests -p 'test_*.py' -v`.

**Limitations:** The G0–G3 calculation was done in an isolated JavaScript execution and its models and scores preserved in report JSON. The source code for regenerating that original model-selection run byte-for-byte is not in this branch. The production V4.7 selectors were not run. The post-draw scorer was tested on synthetic inputs, not a real future draw. Retain `NO_EDGE` and `NULL_DAN` until validated evidence shows otherwise.
