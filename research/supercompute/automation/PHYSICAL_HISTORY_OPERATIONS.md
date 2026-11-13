# SSQ + DLT durable official-source research ledger (V1)

**Status: staged for review in PR #488.** An exact-head CI test is not a
production unattended schedule. The historical issuer-derived database is not
formal V4.7 data; it must not modify selectors, sealed forecasts or Random NULL.

## Architecture: immutable originals + queryable database

A dedicated remote Git branch named
\`ssqdlt-physical-evidence-ledger-v1\` is the proposed durable evidence store.
Each tick restores that remote branch into a clean worktree, verifies the
previous canonical raw/normalized data and SQLite consistency, then:

1. Fetches the official Shanghai Welfare Lottery sorted-results HTML, with
   bounded HTTP retries and recorded failure details, and selects at most
   eight **new** issues already present in the live official history window.
   SSQ ball order / ball group remain **unknown**, not sorted-as-physical.
2. Attempts one bounded Guangdong DLT archive issue candidate per tick,
   scanning 26001 through 26135 until independently corroborated by its
   source page, skipping successes and recently attempted candidates for
   six hours. Missing issues are recorded as blocked, not as fake draws.
   The two Guangdong hostname forms are never considered independent issuers.
3. Writes source bytes at \`SSQ/raw/<sha>.bin\` and \`DLT/raw/<sha>.bin\`,
   immutable \`draws/<issue>.json\`, and immutable
   \`attempts/<issue>/<UTC>-<nonce>.json\`.
4. Reconciles all canonical originals into SQLite
   \`physical_history.sqlite3\` using an all-or-nothing local transaction,
   checking duplicate keys, hashes, source bytes, game domains, schema,
   foreign keys and table counts. Existing canonical records cannot change.
5. Commits only **new** source/receipt files and the derived updated SQLite
   database to the separate evidence branch. A fresh independent worktree
   re-fetches the pushed commit and replays the database and raw-file checks.

SQLite tables: \`raw_documents\`, \`draws\`, \`attempts\`,
\`schema_version\`. The SQLite database is a materialized view, not an
independently authoritative observation. Git alone is not a trusted timestamp
or protection against an administrator force-rewriting history.

## Workflow triggers and what they prove

\`.github/workflows/ssqdlt-physical-history.yml\` has:
- \`push\` on the isolated research branch: executes offline contracts, then
  runs one real evidence tick and independently re-reads the remote ledger.
  These executions are **not scheduled** and cannot count as real timed runs.
- \`pull_request\`: offline contracts only, no token write to remote evidence.
- \`schedule\`: UTC 02:11 and 14:11 daily, **not activated on a research
  branch**. GitHub Actions time schedules only execute on the default branch.
  Activating it requires separate successful source/CI review and a merge.
- \`workflow_dispatch\`: also restricted to main in this draft; manual events
  never count as scheduled triggers.

No automated purchase, paid model request, or predraw seal occurs.

## Recovery tests and acceptance

Run offline from repository root:

\`\`\`bash
python -m unittest discover -s research/supercompute/tests -p test_physical_transport.py -v
python -m unittest discover -s research/supercompute/tests -p test_physical_ledger_db.py -v
python -m unittest discover -s research/supercompute/tests -p test_ssq_physical_source.py -v
python -m unittest discover -s research/supercompute/tests -p test_dlt_physical_source.py -v
\`\`\`

SQLite crash simulation: forcibly abort inside the transaction before
\`COMMIT\`; restart from the same file and re-import canonical source bytes.
External recovery acceptance additionally requires **two distinct successful
GitHub push-triggered ledger runs**, each saved remotely, with run 2 loading
run 1's prefix; check both GitHub job metadata and the ledger.

A true unattended **schedule** PASS requires at least two separately
confirmed \`event=schedule\` GitHub runs on default branch with remote
persistent receipts and fresh-checkout verification, followed by a tested
failure/recovery cycle. The P0 basic scheduler in the existing repository
is a different workflow and does not satisfy this collector-specific gate.

Keep status **UNVERIFIED** for any gate not supported by real Actions and
remote ledger observations. Source-probe red, temporary ISP/network
failures, host-level access restrictions, publication-date ambiguity and
historical issue gaps must not be hidden by a successful test-only job.

The official source contract prioritizes integrity over uptime. For HTTP 403
do not evade access controls, and when all attempts fail store the error and
stop admitting a physical observation. Neither statistical outliers nor
hardware metadata provide a demonstrated lottery edge. Formal A=0; NO_EDGE.
