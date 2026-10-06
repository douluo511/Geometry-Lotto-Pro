# DanLab 1.0.3 external candidate intake — DLT

Status: **EXTERNAL RESEARCH CANDIDATE / NOT VERIFIED AS GITHUB PRODUCT BYTES**

This record preserves the user-supplied state of a separately built local DanLab 1.0.3 candidate without pretending it is identical to the current GitHub DLT product.

## Reported external candidate

Candidate version: `1.0.3`

Reported executable filename:
- `DanLab_DLT.exe`

Reported behavior:
- DLT background prediction is enabled.
- After the visible window closes, a background process continues checking official draw results every 30 minutes while the computer remains powered on and online.
- When a new issue is detected, the candidate settles the previous prediction and generates the next issue's dan selection plus one number set.
- Default future dan count is 2.
- The already frozen historical 1-dan DLT record is retained and must not be rewritten as a 2-dan result.
- Predictive advantage has **not** been proven.

Startup limitation reported for this external candidate:
- automatic permission review did not grant write access for the login shortcut/startup registration;
- after reboot or a new login, the user must launch the new version once before background operation can continue;
- therefore reboot/login persistence is **NOT COMPLETE**.

## Separation from current GitHub DLT

Current GitHub DLT application version at intake:
- `2.1.2`

The external `1.0.3` candidate and GitHub `2.1.2` are different version lines. No equivalence is claimed.

The external candidate's exact local bytes are not present in the connected GitHub repository or accessible file library. Therefore all byte-level claims below remain **NOT VERIFIED**:
- exact EXE SHA-256
- Same Hash against a GitHub-built artifact
- source-to-EXE provenance
- Windows native build provenance
- physical GUI evidence for those exact external bytes
- 30-minute scheduler/process survival evidence for those exact external bytes
- reboot/login persistence
- independent repository/release provenance

## Current GitHub DLT engineering boundary

The GitHub DLT line now contains the restored independent Updater architecture and current validation has demonstrated the following on the restoration line:
- independent Updater process boundary
- Updater Exact EXE
- atomic backup/replace/rollback behavior
- updater data real-network acceptance
- Updater reproducible Same Hash
- Physical GUI Update/Repair routing through the independent Updater
- Update and Repair fail-closed negative-path evidence

Those facts do **not** clear the two remaining release-context requirements:
- `repository_independence` requires the real independent DLT repository;
- `updater_real_network` requires a real software Release N→N+1 transaction from that independent release context.

The external DanLab 1.0.3 background polling process is not automatically equivalent to the required independent software-release Updater.

## Intake gate before any promotion or replacement

The external 1.0.3 bytes may be promoted into the GitHub release line only after all of the following are evidenced against the exact imported bytes/source:
1. immutable source/EXE identity and SHA-256
2. official-network source evidence
3. background 30-minute polling test
4. close-window background survival
5. new-issue settlement and next-prediction transaction evidence
6. default future 2-dan contract test plus preservation of the frozen legacy 1-dan record
7. reboot/login persistence or an explicit FAIL state that is not mislabeled
8. one-click update/repair/advanced-analysis acceptance
9. independent updater process and rollback evidence
10. updater real software Release N→N+1 transaction
11. updater Same Hash
12. Windows native build
13. Exact EXE
14. physical GUI click smoke
15. independent repository
16. Final Gate

Until then:
- engineering status of the external 1.0.3 bytes = **NOT VERIFIED**
- predictive edge = **NOT VERIFIED / NO CLAIM**
- Final Gate = **FAIL**
- delivery authorization as final product = **NO**
