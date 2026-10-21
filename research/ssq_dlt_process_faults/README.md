# Process recovery laboratory and opt-in publication repair

The engineering objective is one reproducible report and mail identity after a
process crash, not a lottery edge. All database/state/history files are newly
created synthetic fixtures. No existing SQLite, holdout or results are read.
No model, lottery window or prediction seed changes. A=0, NO_EDGE, prospective=0.
Formal twelve comparisons, eight producers and approvals 01–04 remain unestablished.

## Actual defect and repair

Original workflow: write report → prepare outbox → commit workflow_publish.
After outbox commit and before publication commit, a crash leaves the first
outbox. Restart changes created_at/metrics but reuses the old notification
identity, so outbox.report_sha256 can differ from the published report hash.

The opt-in `workflow_recovery` version first commits a full publication intent.
Retries reuse its report, observation time, metrics and recipient. They recreate
artifacts and outbox from that intent, check binding, then commit publication.
An inconsistent legacy orphan blocks publication and the current SMTP flush;
no old event is rewritten. This version pins its two source files in addition
to the original workflow sources. Existing code/config drift rules require a
**new state directory**, not silent migration of an old ledger.

    python -m research.ssq_dlt_process_faults.workflow_recovery --config ABS_CONFIG

This is a directly runnable research workflow. It is **not installed in Task
Scheduler**, does not assign an official issue, and cannot confer formal status.
The original 180 source files remain immutable; the older failed case is not
retroactively repaired.

The earlier source capsule retains 21 original Windows CRLF files even though
their unchanged Git blobs use LF. CI uses a Windows CRLF checkout and restores
the frozen LF root metadata/workflow files with a command-local checkout option.
No global Git setting or old Git blob is changed. The full 196-file runtime
manifest must match the local capsule exactly; normalizing hashes is forbidden.

## Eight registered process scenarios

`protocol.json` fixes R00–R07 before execution. R00 is the normal runtime retry
baseline. R01 kills after real cycle commit, R02 after real outbox commit, R03
tests the original workflow gap, R04 tests the repaired gap. R05 kills after
send_started but before DATA; R06 after real DATA250 but before sent commit;
R07 disconnects the receiver after complete DATA without sending250.

The parent waits for an identified live checkpoint, independently reads the
committed synthetic ledger, terminates its owned OS process, then starts a new
process. A wrapper observes real Store.append before/after the specified side
effect; it does not replace transactions or SMTP return values. On Windows,
workers use the actual base Python executable: a venv redirector's PID can
otherwise differ from the real worker. PID mismatch never counts as a valid kill.

The original workflow inconsistency remains a **FAIL_BASELINE_MAPPING** when
reproduced. `DIAGNOSTIC_COMPLETE_WITH_BASELINE_FAIL` means the eight diagnostic
expectations executed, not that all components or production passed. Partial
case selections are labelled partial scope. The first failed harness attempt
and its receipt must be retained.

    python -m research.ssq_dlt_process_faults --output NEW_ABSOLUTE_OUTPUT
    python -m research.ssq_dlt_process_faults --output EXISTING_OUTPUT --verify

Execution requires an exclusive output outside the source checkout. Unknown
interruption never reuses an output directory. Verification reads saved JSON,
hashes and process receipts; it opens no SQLite or network and reexecutes no code.
The local SHA inventory is integrity evidence, not external immutable custody.

On Windows use a short absolute output root (for example
`C:/Users/15928/Documents/Codex/pf-final-20261021`). A real acceptance attempt in
a deeply nested output directory failed when legacy report artifact paths reached
260/261 characters. That failed run is retained. This opt-in publication repair
does not change the frozen legacy file writer or claim general long-path support;
short-root acceptance is a narrower, explicit operating condition.

## Loopback SMTP and honest delivery limits

Only `127.0.0.1:587` is used, with `synthetic@example.invalid` at both ends and
dummy credentials. The fixture never relays or contacts outside SMTP. It uses
real sockets/STARTTLS/authentication/DATA. Its self-signed test CA is trusted only
by the worker environment; TLS hostname verification remains enabled. Existing
port use or missing OpenSSL is BLOCKED; no alternative endpoint is substituted.
DATA bytes, receiver receipts, protocol events and certificate commands are kept.
These receiver receipts are **not digitally signed**. Test keys are synthetic,
short-lived local fixture keys, never production secrets or trusted TSA keys.

`send_started` is committed before DATA. A crash there can leave **zero DATA yet
UNKNOWN forever pending reconciliation**. DATA accepted by the server followed
by a crash before the sent commit also remains UNKNOWN; a lost final250 has
the same ambiguity. The tests require no automatic reconnect/resend in those
cases. This conservative policy avoids duplicates but does not guarantee
delivery or exactly-once delivery. SMTP_ACCEPTED is not inbox delivery. Local
test acknowledgements cannot be used as evidence of mail to the user's address.

Workflow discovery is an explicitly prefilled synthetic offline stage and
history is invented. No AnySearch or official-source exchange is tested here.
All clocks are fixtures, not elapsed scheduler executions or external timestamps.
This is not a physical power failure, reboot, real network removal, live Windows
Task Scheduler acceptance, complete P0 validation or a prediction-skill test.

Verification uses Python3.11 stdlib and an available OpenSSL executable. Component
tests: `python -m unittest discover -s research/ssq_dlt_process_faults/tests -v`.
The CI acceptance runner records those tests separately from the eight actual
child-process scenarios. SQLite atomicity also depends on real storage and OS
assumptions: [SQLite WAL](https://www.sqlite.org/wal.html),
[atomic commit and hardware assumptions](https://www.sqlite.org/atomiccommit.html).
