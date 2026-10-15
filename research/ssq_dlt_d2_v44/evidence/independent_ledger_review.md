# Independent ledger/runtime review

The initial independent synthetic probe reproduced a cross-version comparison defect: M04 v1 and v2 from two issues were merged into one comparison with n=2 and no version field. That FAIL is retained in `independent_ledger_review_initial.json`.

After the fix, a fresh independent run returned all 10 probes PASS. The new registry rejects a version or M05 primary change within the same game/trial ledger, and replay independently rejects an injected mixed registry. Comparison outputs expose candidate version, null version, M05 primary and its preselected flag.

| Probe | Current result |
| --- | --- |
| Cross-version registry change rejected | PASS |
| Comparison identities and primary exposed | PASS |
| M05 primary change rejected | PASS |
| Missing expected issue suppresses comparisons | PASS |
| SQL UPDATE, DELETE and INSERT OR REPLACE rejected | PASS |
| Read-only replay preserves all table rows | PASS |
| 16 concurrent identical jobs insert exactly one candidate | PASS |
| Missing candidate cannot be supplied after recorded draw | PASS |
| Independent, non-nested D1–D5 score oracle | PASS |
| Direct mixed-version registry injection rejected by replay | PASS |

Actual command: `python work/review_ledger_probe.py`; exit code 0. Probe code wrote only a disposable work directory and evidence outputs. The current JSON records source SHA-256 before and after the run; source bytes were unchanged during the probes.

These are synthetic storage and arithmetic probes. They do not verify official network data, publication/as-of proof, external 01/04 keys, TSA, original producer identities, prospective statistics, Windows boot trigger or real elapsed 30-minute execution. `R2=BLOCKED`, `formal_A=0`, `NO_EDGE`, repository independence FAIL and Final Gate FAIL remain unchanged.
