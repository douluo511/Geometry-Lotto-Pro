# V4.4 local engineering follow-up to PR #407 / Issue #408

This is a runnable, isolated research component package. It is not the missing
V4.0 ZIP, an integration into either existing product, or a final release.
`SSQ/`, `DLT/`, R1 and original archives are unchanged. No cloud was deployed.

Always preserve `R2=BLOCKED`, `formal_A=0`, `NO_EDGE`,
`repository_independence=FAIL`, `final_gate=FAIL`.

## Run a local status check

From the repository/package root, with Python 3.11+:

```powershell
python -m pip install -r research/ssq_dlt_d2_v44/requirements-test.txt
python -m research.ssq_dlt_d2_v44.runtime --db C:\GLP\research\ledger.sqlite3 --output C:\GLP\research\reports
python -m research.ssq_dlt_d2_v44.acceptance --output C:\GLP\acceptance-new
```

Use an empty acceptance directory. Python without `cryptography` can check
status, but signature verification fails closed and crypto tests are skipped;
such a run cannot replace the full dependency-installed acceptance run.
`requirements-test.txt` pins the version actually tested on this host.

The runtime performs one local check and writes immutable per-run JSON, CSV
and HTML plus a separate append-only heartbeat. No training, source fetching,
prediction, candidate substitution or post-draw backfill runs at startup.
Process exit 0 means the check ran; inspect the report for admission states.
Empty databases truthfully report `NOT_SCORABLE`; there is no invented next
issue, verified sale deadline, formal eight-slot prediction or official result.

See [Windows instructions](windows/README.md) for BAT, PowerShell, task XML,
dry export and the explicit installation path. Actual Scheduler access on the
implementation host was denied. Durable installation, elapsed 30-minute firing,
power interruption, retry under Scheduler and Windows 10/11 reboot remain unproved.

## Storage and identity

`Ledger.register` freezes all eight slot versions and the M05 primary before
the supplied deadline. `freeze` stores independent D1..D5 lists per slot;
nesting is not assumed. The supplied clock is research metadata, never external
pre-draw proof. `record_research_draw` cannot admit official or formal evidence.

SQLite uses WAL, FULL synchronous writes, a five-second busy timeout and
`BEGIN IMMEDIATE`. Unique identities, canonical hashes and BEFORE INSERT,
UPDATE and DELETE triggers reject conflicts, overwrite and SQLite REPLACE.
Identical retries are no-ops. A foreign database is refused before conversion
to WAL, including a database without this component's application identifier.
Schema version 2 is for this research ledger only; unmarked old databases must
be independently reconciled rather than auto-imported.

An optional `signed_research` argument to `freeze` verifies real Ed25519
signatures from both 01 and 04, binds them to the exact candidate hash and
deadline, and consumes role-scoped nonces in the same SQLite transaction.
A second-signature failure rolls back the first nonce and candidate. Reusing a
nonce on another issue fails after restart. Synthetic test keys do not provision
formal authorities; unsigned research snapshots cannot become A either.

One ledger is one fixed trial per game. Changing any slot version or the M05
primary requires another ledger/trial. Replay also rejects directly injected
mixed registries. Comparisons expose model and null versions and M05 primary.
All expected issues remain visible; any absent draw/slot suppresses the entire
paired comparison. Read-only replay never rewrites candidates or stores scores.

The database owner can modify files, drop triggers or replace hashes; these
controls do not replace external custody, signed backups, TSA or independent audit.

## Source and trust boundaries

`network.fetch_official` captures original bytes only from exact HTTPS official
hosts, rejects cross-host redirects, bounds attempts and payload size and checks
response-read deadlines. Each blocking socket operation has a timeout. OS DNS
resolution remains resolver-dependent; this is not a hard process-wide deadline.

`AnySearchDiscovery` requires supported initialization, an actual tool listing
and a fixed discovery-tool allowlist. It retains raw-response fingerprints and
never turns a search/extract result into official draw evidence. Remote text is
untrusted data. Real initialization, listing, search, batch_search and extract
were exercised without credentials; authentication policy was not established.
401 non-retry and timeout/retry faults were exercised with synthetic transports.

`admission.validate_source_pair` independently checks two source originals,
hashes, JSON field paths, issue, draw and aware publication/observed/as-of times.
The live HTML adapters are not integrated with that JSON contract. Four real
HTTP captures do not establish publication time or admitted two-source draws.

`replay_dual_holdout` checks independently supplied holdout and prediction
commitments and recomputes every issue; a 10/152 to 150/152 aggregate tamper is
rejected. Local hashes are not an external preregistration. Original formal
twelve test definitions, actual producers, TSA, external trusted keys and
independent prospective replication remain unavailable. Formal family labels
or arbitrary twelve IDs do not establish the original frozen family.

## Reproduce evidence and read status

```powershell
python -m unittest discover -s research/ssq_dlt_d2_v44/tests -v
python -m research.ssq_dlt_d2_v44.probe_network --discovery-tools --output C:\GLP\new-network-capture
```

The network probe is explicit and separate from the status runtime. It never
imports observations into a formal ledger or infers the next target by adding
one to a draw issue. Inspect `evidence/` and `windows/evidence/` for scoped
observations; older source-hash-specific review results do not certify changed
code. `ACCEPTANCE_STATUS.md` records current limits and all nine P0 gates.
