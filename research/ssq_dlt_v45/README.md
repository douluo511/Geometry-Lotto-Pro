# SSQ＋DLT V4.5 local research operations

This is a runnable research component stacked on draft #409 at
`ed6fda4f0975de3dabfd7a7e08b368669e2bef7d`. Audited main is
`c2b0db6876d2aae874f8cf4d08f52455c8eaf152`. It does not change the existing
SSQ/DLT applications or their historical databases. Repository governance
requires `repository_independence=FAIL` and `final_gate=FAIL` here.

## Current operation and hard boundary

Run from the repository root with Python 3.11+:

```powershell
python -m research.ssq_dlt_v45.runtime --config C:\GLP\V45\config.json
python -m research.ssq_dlt_v45.acceptance --output C:\GLP\V45\new-acceptance-directory
```

The configuration must use explicit absolute state/input paths and independently
reviewed whole-file SHA256 pins. See `config.example.json`. Inputs have
`{game,draws:[{issue,draw_date,front,back}]}`. Keep source originals separately.
An owner can replace SQLite or its triggers: these controls prevent accidental
mutation, not privileged tampering. Local hashes and wall clocks are not an
external pre-draw time seal. No API in this component grants formal A.

One bounded cycle reads the pinned history, fetches national and provincial
official originals using exact HTTPS host allowlists, checks every overlap and
requires matching latest issues. It rejects future/same-day draw dates whose
actual draw times cannot be proven. Newly observed rows have no historical
publication/as-of proof. The five fixed research producers output separate
D1–D5, a fixed primary Pairwise-D2, and complete legal front/back single tickets.

Neither the saved local handoff nor the currently audited official responses
contain an admitted explicit next issue and sale deadline. Therefore the runtime
**blocks next-legal-issue publication** and labels output `UNASSIGNED_PREVIEW` /
`RESEARCH_UNASSIGNED`. It never increments the latest issue to assert a target.
There is currently no production next-target admission adapter. Adding a JSON
boolean such as `authorized` or `tsa_verified` cannot bypass this boundary.

The original eight identities M04, M05-1..M05-5, M06 and M07 remain unavailable
for formal production; no research model substitutes for them. Their original
definitions, actual 01/02/03/04 approval and key custody, trustworthy candidate
TSA/deadline evidence, formal twelve-family preregistration and independent
prospective replication remain BLOCKED. `formal_A=0`, `NO_EDGE` are unconditional.

## Ledger, replay and research comparison

The separate V45 SQLite file has its own application ID. FULL/WAL transactions,
unique kind/key pairs and INSERT/UPDATE/DELETE/REPLACE guards make exact retries
no-ops and conflicting writes errors. A failed source attempt never completes a
due slot; catch-up rereads the sources. Completed previews stay byte-for-byte
fixed. A new model version or changed model source requires a separate study;
it must not reinterpret prior frozen predictions.

`replay.py` connects the actual ledger to `competition.py`: register a fixed
numeric issue plan, accept each prediction at its local current freeze time,
record outcomes, then replay complete registered trials. Known outcomes prevent
late prediction entry, including across trials. Outcome receipt metadata remains
untrusted until separately admitted. There is no automatic formal enrollment.
With no verified target freezes, runtime reports replay BLOCKED. Synthetic test
trials do not enter the delivered operational database.

Research comparison checks the complete preregistered issue/model rectangle,
fixed versions, source SHA and Random NULL seed, per-issue D1–D5, same-period D2
discordant-pair exact tests and Holm adjustment across four research challengers.
The theoretical fair D2 rates are SSQ `15/528` and DLT `10/595`. Poor periods
cannot be dropped; missing/duplicate periods block a trial. The original formal
twelve-family and independent prospective validation remain unavailable; no
research ranking is a formal winner or evidence of higher future hit rate.

## Scheduling, reporting and mail

See `windows_README.md`. The exported task has boot, Monday/Wednesday/Saturday
07:00 UTC (16:00 Japan), and 30-minute triggers, bounded retries and IgnoreNew.
Runtime deduplicates the latest due slot; elapsed slots are not regenerated as
historical predictions. Catch-up only runs while the computer and scheduler are
available. Earlier missed opportunities remain missing, not backfilled forecasts.

Immutable JSON/CSV/HTML/SHA reports, per-run heartbeats and a local EML outbox are
written under the configured state directory. SMTP requires an explicitly
configured host/sender and an environment-held credential. It uses STARTTLS on
port 587. Connection/authentication failures can retry; a crash/uncertain response
after the send claim requires reconciliation rather than automatic duplicate DATA.
Message-ID and SQLite atomic claims suppress concurrent sends. SMTP acceptance
does not prove inbox delivery. A connected-app one-time send does not provision
unattended Windows SMTP credentials.

AnySearch MCP is available through the separately tested V44 discovery client;
its REST/JSON-RPC HTTP transport is discovery-only. Search/extract content never
becomes official draw data. `probe_network` records real discovery and official
captures without predictive promotion. No general unverified REST response is a
trusted source. Physical network/power disconnect, real reboot, real 30-minute
Scheduler firing and external live TSA failure must be reported NOT_RUN unless
actually executed. Docker Compose is optional, with its own `/config` and `/data`
paths; no cloud deployment or automatic ticket purchase is provided.
