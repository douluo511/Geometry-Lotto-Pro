# Copy-paste handoff: test10 REA + Harness engineering

Associated RUN_ID: `V46-R1-20261022T015053-0400-7F3A9C`

Inspect and continue the V4.6 safe research branch only. Do not merge PR #425 or alter V4.5 formal eight-slot identities.

Current verified state:
- Repository: https://github.com/douluo511/Geometry-Lotto-Pro
- Branch: `research/ssq-dlt-v46-harness-bootstrap-20261022`
- Head: `1cd80efdcf3ad9b33577c9cac5736fdad85a29f9`
- Draft PR #425: https://github.com/douluo511/Geometry-Lotto-Pro/pull/425 ; open, not merged.
- Relevant CI run: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39667599443 ; 13 synthetic tests pass on Ubuntu and Windows Server 2022.
- Current registered run is PREP / BLOCKED. No verified >=120-row official snapshots or snapshot SHA256 yet. Do not produce official forecasts or claim live orchestration.

Execute next:
1. Inspect current PR head and latest CI before editing; add run registry/handoff files already committed on branch.
2. Implement official snapshot ingestion only through a verified allowlist, raw source-byte retention, SHA256 of exact snapshot bytes, schema/issue/calendar checks and fail-closed as-of validation.
3. Implement orchestration that accepts one locked snapshot SHA per lottery and launches model jobs in isolated inputs; do not expose other models' same-target outputs before freeze.
4. Add external TSA provider interface with a real verification path; no local time or Git commit can be described as external TSA.
5. Add atomic dual-lottery run coordination, immutable submission manifest, read-only test9 scoring, paired D2 statistics, and P0 failure tests. Keep status SHADOW until external evidence exists.
6. Run the exact test suite and report commit SHA, CI run URL, pass/fail logs, unimplemented gates, and no-overclaim status.

Do not merge main, do not modify V4.5 records, do not buy tickets, and do not label any missing function PASS.
