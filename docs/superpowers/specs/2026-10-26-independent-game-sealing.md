# Independent-game frozen-ledger sealing repair

Base HEAD: 584a3949f5fcf1d68fa3f664e719cd0473f841b1; tree9a7068e2a8700f67a750df242f9c68a1b576305c. SoleIssue468/DraftPR467; no alternate Harness/PR, main merge, purchase or model/seed/family change.

## Confirmed boundary and scope
The existing closed_loop independent-game path freezes six original models as V47G runs. In the TEMP-only reproduction saved at work/local_deploy_evidence/v47g_seal_reproduction.json, both games pass original _read_frozen_game checks but frozen_seal_payload, prepare_request, verify_response and requestCLI all reject DUAL_GAME_V47_RUN_ID_REQUIRED. Real ledger and source bytes remained unchanged. The existing A checklist explicitly identifies this missing interface.

User scope authorizes repair of the sustained per-game freeze/seal/score chain and delegates implementation choices. This is the coordinator's bounded implementation choice: extend the EXISTING predraw_seal module, using its current Python/SQLite/OpenSSL stack and exact existing original-version reader. No new predictor, scheduler, trusted-source admission or alternate sealing pipeline.

## Required behavior
Accept only exact V47G-[0-9a-f]{32} identities through the current public functions/CLI. Resolve exactly one original game_runs row in a read-only query-only transaction; require valid game and full original-version reconstruction through closed_loop._read_frozen_game. No calls that create runs, scores or receipts. Missing, ambiguous, malformed or tampered records block before seal output.

Export one game's unchanged snapshot plus ALL six original cards with stored hashes and original frozen_at timestamp. Reuse snapshots/games MAP shape, but use a distinct V47G-FROZEN-SEAL-PAYLOAD-1 schema and clearly typed DERIVED game registration metadata; never fabricate a registered dual V47-RUN manifest or historical orchestration/source authentication. No source-time inference or current-model substitution for old cards.

Old dual V47 payload preimages and outputs stay byte-identical. Shared prepare/verify loops retain aware clocks, asof/freeze checks, strict upper signed time bound before the appropriate cutoff, nonce AND data imprint, explicit CA pin/empty trust store/EKU verification and known signed accuracy. Preserve old dual time label; singleton success label must describe only that game's claimed cutoff.

All current source/trust qualifications remain CALLER_UNVERIFIED/BLOCKED/A0/NO_EDGE. A cryptographic result under a caller pin cannot certify official source independence, target/cutoff, trust policy or prediction advantage. No actual forward target, freeze, token request or network submission is authorized by these tests.

## Invariants and rejection cases
- Both SSQ and DLT valid singleton payload/request/verify paths; an invalid other game's unrelated row cannot alter a valid singleton.
- Malformed, absent, ambiguous and wrong-game run identities; missing/extra/mixed-source arms; changed/noncanonical snapshot/card, NULL seed, model parameters, target or stored source artifact must reject.
- Stored local timestamp outside asof/cutoff or after request, request at cutoff, clock reversal, wrong payload/CA/nonce/imprint, missing accuracy or upper bound touching cutoff must reject.
- Original DB bytes, old frozen source artifacts and cards unchanged after success and failure. No dual-manifest table required for a V47G run, and no invented dual manifest in singleton output.
- Existing dual tests and original exact-code/seed/NULL/source gates retain their meanings. Engineering fixtures remain TEST_ONLY_SYNTHETIC; no formal sample count.
