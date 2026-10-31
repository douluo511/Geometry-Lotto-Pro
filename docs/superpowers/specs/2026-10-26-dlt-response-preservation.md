# DLT HTTP response preservation
Base: PR467 HEAD84df15115f3e7d61725ba205bc0166b3fbf93b52. Sole control Issue468.

The user has delegated implementation of the existing continuous SSQ/DLT loop and requires every genuine source failure to survive. This is a repair of layer1 of the accepted eight-layer evidence contract, not an additional model or formal trial.

Observed defect: national DLT HTTP200 nonJSON bodies are discarded because the redirect guard records only non200 and the source validator raises before returning a success manifest. Tick25 retains the error but no national body. Earlier missing bodies remain missing.

Approaches: recording only nonJSON200 would miss JSON and later-page parse failures. Changing the shared DLT selector/parser would unnecessarily alter other applications. Capture every actual response in the existing intake guard, then validate successful parser manifests against those original observations; this is the implementation choice within the user's delegated scope.

Requirements:
- Record each returned allowed-source HTTP response before parsing, including every retry and redirect hop. A connection failure with no response creates no body.
- Keep existing HTTPS/root/redirect limits and original response content bytes. Existing schema retains Content-Type/status/URLs/local untrusted capture time/hash/size, not full response headers or trusted publication time.
- A successful manifest is checked against observed bytes/SHA/size/final URL/status/case-insensitive Content-Type/parser identity. It does not append a second receipt for the same HTTP observation. Distinct identical retries remain distinct receipts; write_bundle may share one bin file.
- Retain failed200 bodies even if a later variant succeeds. Existing strict raw semantic replay stays unchanged; a newly visible malformed body can keep that source blocked. Do not delete it or relabel history as certified.
- No change to source quorum, official target/cutoff admission, model parameters, fixedNULL, family, old snapshots, failures or formal_A=0/NO_EDGE.
- Real checks use the current pinned runtime until exact new-head CI and scoped review finish.

Proof: deterministic network-boundary fixtures exercising original NetClient/parser/worker, RED then minimalGREEN; full existing regression; exact SHA Ubuntu/Windows CI; independent review. Real official attempts are separate from fixtures and future sample denominators.

