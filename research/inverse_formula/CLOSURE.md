# Research closure: offline preflight → content seal → result score

This document describes the research sidecar in Draft PR #470. It requires
**zero API keys, HTTP requests, or paid model calls**. It does not write into
formal V4.7 predictors, frozen ledger, original fixed Random NULL or seeds.

## GitHub Actions CI

Ordinary PR checks run the existing tests plus tests/test_inverse_closure.py
on Ubuntu and Windows. They generate the existing deterministic committee
archive and then run, for both SSQ and DLT:

1. Offline configuration validation (six GPT-6+ roles, five unique IDs,
   all high), history validation and source SHA256.
2. Receipt/cutoff/source-hash checks, legal ticket and D2 validation, followed
   by a research-only content seal.
3. Upload four output files to the research-offline-closure-{OS} artifact:
   research-preflight-ssq.json, research-preflight-dlt.json,
   research-content-seal-ssq.json, research-content-seal-dlt.json.

These are deterministic *role-simulation* outputs. Six paid GPT-6 calls
have not been executed by this job. The paid manual workflow remains
separate, with its existing explicit opt-in.

## Manual no-cost commands

~~~bash
python -m research.inverse_formula.committee --out research-committee.json
python -m research.inverse_formula.closure preflight --game ssq --history research/inverse_formula/ssq_2026.txt --out research-preflight-ssq.json
python -m research.inverse_formula.closure freeze --game ssq --preflight research-preflight-ssq.json --candidate research-committee.json --out research-content-seal-ssq.json
~~~

For DLT, use game dlt, its historical file and separate output filenames.

After obtaining and independently verifying the official result, prepare
the result input as JSON. The following is **SYNTHETIC TEST DATA**, not
actual winning numbers:

~~~json
{
  "game": "SSQ",
  "issue": 2026130,
  "front": [1, 2, 3, 4, 5, 6],
  "back": [1],
  "source_url": "https://example.invalid/synthetic-placeholder"
}
~~~

Use the actual issue, winning numbers, and real source URL. A provided
HTTPS URL is *metadata* and does not authenticate the actual result.

~~~bash
python -m research.inverse_formula.closure score --game ssq --frozen research-content-seal-ssq.json --actual verified-result-input.json --out research-postresult-ssq.json
~~~

Scoring validates the target issue and legal result, reports exact/full,
front and back matches, and explicit D2-pair hits. The scoring file holds
the content-seal SHA256, submitted result-input digest and its own digest.
It **does not edit** the content-seal file.

All output files are created exclusively and cannot silently overwrite
existing results. SHA256 proves byte-content consistency, **not** that a
prediction existed before the draw. GitHub branch history may be rewritten,
GitHub artifacts may expire, and a commit timestamp alone is not trusted
independent pre-draw attestation.

## Failure conditions

- Invalid model-ID config, non-high reasoning, invalid or discontinuous
  history: offline preflight fails.
- Tampered digest, mismatched game/target/cutoff/source hash, malformed
  ticket or D2 pair: content seal fails.
- Injected mock transport masquerading as real model execution: rejected.
- Tampered seal, wrong-issue result, invalid numbers or missing HTTPS
  source metadata: scoring fails.
- Output path already exists: exclusive-write fails instead of overwrite.

## Status and remaining gates

| Component | Status |
|---|---|
| Offline preflight | Implemented; CI confirmation required |
| Deterministic simulated committee content seal | Implemented; CI confirmation required |
| Strict cutoff and tamper checks | Implemented; CI confirmation required |
| Manual post-result arithmetic scorer | Implemented; CI confirmation required |
| Authenticated real six-GPT model execution | UNVERIFIED |
| Review-driven model formula registry | NOT IMPLEMENTED |
| Official historical-data authentication | UNVERIFIED |
| Independently trusted pre-draw publication | NOT IMPLEMENTED |
| Scheduled post-draw scoring and restart recovery | NOT IMPLEMENTED |

**NO_EDGE / RESEARCH_ONLY / DO NOT MERGE without independent review.**
