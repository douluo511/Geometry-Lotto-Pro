# Evidence preflight and executable project mother template

Start with [the mother template](PROJECT_MOTHER_TEMPLATE_V2.md) and [the 18-project execution directory](EXECUTION_CONTROL.md).

This is a **report consistency preflight**, not a release certifier. It always emits `final_gate: NOT_CERTIFIED` and `release_authorized: false`, even on success. No existing SSQ release gate or repository-independence block is removed. It does not claim that all 18 projects are integrated.

## Run

From the repository root, with Python 3.11:

```text
python -m pip install -r acceptance/requirements-test.txt
python -B -m unittest discover -s acceptance/tests -v
python -B -m unittest discover -s SSQ/tests -v
python acceptance/validate_status.py --status project-status.json --baseline approved-baseline.json --approved-baseline-sha256 APPROVED_DIGEST --status-schema acceptance/project-status-v2.schema.json --evidence-root evidence --expected-candidate-id CANDIDATE_ID --expected-commit-sha EXACT_COMMIT
```

The capitalized arguments are explicitly required inputs, not runnable defaults. A missing argument gives structured JSON and a nonzero exit. Exit codes: `0` = preflight only PASS; `1` = invalid/inconsistent evidence FAIL; `2` = incomplete/unapproved/unavailable BLOCKED. Neither `0` nor a test-suite green light authorizes final release.

Use the repository's reviewed status schema, not a permissive schema supplied alongside the report. Store the approved baseline digest and expected candidate identity **outside the untrusted report** (reviewed configuration or a controlled acceptance input). Do not compute an approval hash from the submitted baseline and immediately call it approved. Schema validation cannot authenticate an approver.

The incomplete templates intentionally block. Fill and review the full baseline inventory before freezing it; do not insert dummy values to satisfy the schema. One `checks` summary is required per frozen criterion, with multiple evidence IDs when necessary. Every criterion has positive frozen weight; each stream totals 100. A missing criterion or entry is not silently dropped. `computed_scores` is diagnostic coverage; when any errors/blockers exist, `reportable_scores` is null and external completion is unverified.

## Evidence receipt contract

Every `evidence[].artifact_uri` points to a UTF-8 JSON receipt beneath `--evidence-root`. The receipt contains:

- `format: acceptance-evidence/1`;
- `evidence_id`, `candidate_id`, `kind`, `collected_at_utc`, `environment`, `assertions`, `status`, exactly matching its report index;
- `commit_sha`, matching the independently supplied commit;
- `candidate_fingerprint`: SHA-256 of sorted compact JSON of `commit_sha`, `tree_sha`, `config_sha256`, `dependencies_sha256`, `data_sha256`, `model_sha256`, `tested_exe_sha256` (see `candidate_fingerprint()`);
- `mode`: `OBSERVED`, `CONTROLLED_FAULT`, or `UNIT_FIXTURE`;
- `assets`: nonempty list of `{path, sha256}` for retained logs/inputs/outputs;
- `payload`: an object containing the project-specific facts below.

Payloads for `exact_exe` require `exe_path` and `exe_sha256`; the actual EXE bytes and the designated release EXE bytes are read and hashed. Payloads for `real_network` bind `attempt_id`, `source_id`, `source_uri`, and `raw_response_sha256` to the approved source and retained raw response. A failed primary attempt remains FAIL; approved successful fallback can satisfy a contract that does not independently require the primary to succeed. Synthetic/fault receipts cannot satisfy production-effect or Real Network evidence.

Each entry's observed effect payload also needs `entry_bindings`: a list whose matching entry records `entry_id`, `requirement_id`, `implementation_ref`, `production_call_path`, `real_input_or_data_ref`, `exe_sha256`, `input_sha256`, `implementation_asset: {path, sha256}`, and `output_asset: {path, sha256}`. Files must be nonempty, retained, and hash-consistent. Reusing another entry's evidence without a matching binding is rejected. These are consistency checks; source bytes alone do not prove an implementation actually ran.

Paths are clean, relative paths with `/`, beneath the evidence root. Absolute paths, remote URLs as local artifacts, traversal, symlinks/junction escapes and Windows alternate streams are rejected. A source URL is provenance metadata, not permission for the validator to fetch arbitrary URLs. Retain sensitive raw evidence in a controlled directory, not a public commit.

All unit-test fixtures��including the positive consistency example��are synthetic and explicitly labelled. They are not real network, Windows acceptance or business proof. There is deliberately no production PASS sample to copy into a release report.

## Proof boundaries and remaining work

This validator can reject conflicting identities, missing files, stale timestamps and fabricated coverage. It cannot establish that a self-authored receipt is truthful, that the approved inventory includes every actual product entry, or that a model has real value. Trusted execution provenance, independent inventory review, project-specific assertions, GUI success **and failure** scenarios, business threshold approval and release sign-off remain mandatory.

SSQ's modified GUI verifier now independently reparses the raw responses from the **same physical GUI update directory**, compares canonical rows, and binds the exact ledger event and displayed hash. Static BUSINESS_GATE checks are validated against the full named boolean contract, but remain static checks: they must not be reported as portfolio-level business 100% or full no-shell acceptance.

The native SSQ workflow remains authoritative for candidate building and physical GUI execution. Its existing shared-repository block is intentionally retained. The new fast workflow below proves only regression-test behavior; it neither builds an EXE nor uploads a FINAL artifact.
