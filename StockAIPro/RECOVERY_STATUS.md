# Stock AI Pro recovery — NOT FINAL

Original archive SHA256 `fedbc5378ed5916e487b9cdc70051d5d00f790e4689ba8ff96dc8f2396ac7e10` (225815 bytes). The immutable `recovered_exact/Stock_AI_Pro` contains all 187 original files, including the binary ZIP test fixture. The import manifest records every original byte count, SHA256 and Git blob; remote tree comparison verified 187/187 matching blobs on commit `56e9ce17ad8a4cb03585dc83bee41f9a5b39fd09`.

Original Windows Python 3.11.9 offline acceptance failed 3/30 gates: Windows file URI interpretation and leaked session log file handles. The unmodified original and its failure remain preserved. Separate `staging/Stock_AI_Pro` corrects local URI parsing, rejects unsafe URI hosts and closes owned log handlers on both success and failure. It includes 2 regression gates in addition to the 30 original gates; current local compile and all 32 offline subprocess gates PASS. Package manifests are regenerated for the repaired source, never for the immutable import.

The Windows workflow validates exact checkout identity, all 187 immutable bytes before/after tests, the full 32-test denominator, compile and subprocess exit codes. Its evidence is a current-run diagnostic, not a product acceptance report. New remote execution is NOT VERIFIED until the workflow runs.

## Current execution — 2026-10-04, STRICT ENGINEERING EXECUTION MODE

This record is a control plane, not acceptance evidence. The immutable original Streamlit/Python package remains preserved; the native desktop hardening is a separately traceable candidate lineage.

Failed base: `acae720f6976bdf5f7d76a15cdf91c23abdb79c7`.

- Source/offline run `37166091584` completed successfully on that exact head. Its 187-file identity and 32 offline gates do not prove the desktop or business Final.
- Native run `37166091546`, job `111329154034`, built and self-tested the Windows candidate and ran its repair worker, then FAILED the frozen real-network core action; advanced/physical-GUI stages were skipped. Main candidate SHA-256: `a02b8a0c8e85a67f28547de1643c3fa07cc5ba13700a675fe6974563b2308e4f`.
- Full-business run `37166091551`, job `111329169274`, FAILED after the unchanged 3300-second timeout. Raw provider receipts show nested retries and serial downloads reached only about 124 of 300 live histories.
- Downloaded native artifact ZIP SHA-256 `1c5ef4c0b089391a7574ce68d824109620a1b9ffde6300d4f24aeeeebd42cdca` matched GitHub. A local replay of its same-hash main EXE produced a traceback from AkShare/tqdm writing to the windowed EXE's missing standard stream. This is direct failure evidence; it is not GUI or final acceptance.

Fixes in this successor candidate:

Integration parent: `1aadeba717ca83796621fed29cd17fc0bad68d32`. Five concurrent commits supplied the single-owner history retry regression, package identities, and broader desktop triggers. Their behavior and regression are preserved. On that exact head source run `37177614529` passed, desktop run `37177614524`/job `111363441632` still failed core (primary SSE HTTP 403; Eastmoney disconnect; Sina windowed stream `NoneType.write`), and business run `37177614522` was still running when read. None is inherited by the successor. The new allowlist collector preserves the diagnostic intent without exporting entire runtime directories.

- Supply writable per-worker diagnostic streams to the windowed EXE; retain structured success/failure receipts tied to GUI invocation and source identity.
- Give transport retries one owner, retry only transient errors, enforce explicit timeout bounds, and overlap history I/O with at most four workers. Preserve the 300 live stocks, 60 research bootstrap batch, 20180101 history start, model parameters, and 3300-second full-business acceptance limit.
- Keep thread-local transport receipts separate, serialize JSONL writes, deduplicate history targets, and preserve per-symbol and pipeline progress. Keep cached bytes on live-source failure but never count that cache as a successful refresh.
- Persist business stdout from process start, including timeout failures. CI desktop diagnostics export only a fixed field allowlist; raw exception messages, runtime logs, state, and cache are excluded from that new diagnostic export.
- Bind physical GUI clicks to the running Tk window geometry and actual service invocation/result evidence; report completed operations separately from any unverified business or positive-update acceptance.

Local dirty-worktree regressions are development evidence only. They cannot be assigned to the failed base SHA or counted as new exact-head Actions PASS. The successor commit must rerun affected source/offline, real-network business, native build, Exact EXE, physical GUI, and Same Hash gates. Preserve the original FAIL → FIX → reacceptance chain.

Engineering completion: NOT VERIFIED. Business completion: NOT VERIFIED. Overall completion: NOT VERIFIED. No complete current frozen engineering/business denominator and evidence mapping exists; test counts are not a substitute.

Dedicated repository: BLOCKED (not found/current GitHub installation cannot see an independent target). Production signed Release N→N+1: BLOCKED (no production release context). Model qualification and business audit: NOT VERIFIED until the complete frozen requirements have direct evidence. Final Gate: FAIL. Unique accepted final artifact: NONE. Delivery authorized by acceptance: NO.
