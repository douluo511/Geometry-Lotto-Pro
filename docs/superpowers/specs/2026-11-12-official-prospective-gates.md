# SSQ + DLT official-source quorum and prospective research evidence gates

Date 2026-11-12. This extends the existing SSQDLT P0/research evidence loop; it does not create another Harness or modify formal V4.7 six-arm producers, fixed Random NULL seeds, frozen ledgers or previous forecasts.

## Official observation design

- SSQ: independently governed Shanghai Welfare Lottery official history and Hebei Welfare Lottery homepage-plus-announcement consensus. Native parsers must preserve original response bytes, SHA256, URL, status and fetched timestamp.
- DLT: Gansu Sports Lottery current-draw homepage plus Jiangsu Sports Lottery listing and **linked official announcement**. The Jiangsu listing date is explicitly a publication date, NOT draw date. Only an explicit 开奖日期 in the linked per-issue announcement can authenticate draw_date semantics. Its issue and numbers must match the listing.
- Require EXACT latest issue, date and all ball sets to match between both separately governed lottery centres. Non-200, timeout, missing raw, stale issue/date, publication-date confusion, changed page schema, content mismatch, unknown redirect or insufficient source count must yield SOURCE_BLOCKED and a create-only failure receipt.
- Source observation evidence is a two-centre public-website consensus, **NOT** a digitally signed issuer record or trusted formal observation. Raw HTTP bytes must be retained and hash-verifiable, not merely inferred from cached text or a historical checked-in seed.

## Research seal (NOT formal)

- The operator provides an explicit target issue, candidate ticket and claimed sales cutoff UTC; no official next issue or holiday-adjusted cutoff is inferred from arithmetic or a weekday.
- Source manifest and raw bytes are verified; the researched target must be exactly the next issue identity. The ticket includes a legal D2 front pair, model ID and model SHA256. The observed time must precede the claimed cutoff; attempts after it are rejected. Write one create-only SHA256 frozen receipt per game/issue.
- This is SHADOW evidence because the cutoff was not independently authenticated; the local/GitHub clock is not an independent RFC3161 timestamp. Every research freeze has formal_A=0, edge=NO_EDGE, cutoff_authority_verified=False and predraw_independent_tsa_verified=False. Nothing in this PR promotes it.

## Future read-only scoring

- The scorer only consumes an already persisted freeze and subsequently corroborated matching official outcome (same game/issue). Missing freezes cannot be reconstructed from the result. Score receipts hash-bind the original forecast and official-source consensus, record front/back hits, explicit D2, full-ticket hit, D1-D5 threshold counts; they are created only once.
- Unmatched forecasts remain PENDING in the complete-denominator audit, never silently removed. Current adapter only scores the newest two-centre corroborated issue; catch-up of a missed issue requires a separate independently authenticated historical dual-source backfill.
- A local auditor recomputes every score from its frozen card and rejects hash tampering, orphaned scores and unauthorised formal flags.
- The proposed scheduled workflow runs only once independently reviewed and merged to main. On main it appends only new research/official_prospective files to the existing ssqdlt-research-ledger-v1 branch, pushes and freshly rereads the remote head. Branch CI never writes the original ledger.

## Commands (Windows-compatible; Python 3.11+)

    python -m pip install requests
    python -m unittest discover -s research/supercompute/tests -p test_*.py -v
    python -m research.supercompute.official_probe --game ssq --out official-capture/ssq
    python -m research.supercompute.official_probe --game dlt --out official-capture/dlt
    python -m research.supercompute.official_prospective audit --ledger ledger

Research shadow freeze (only when a verified source manifest, separate candidate and FUTURE claimed cutoff exist):

    python -m research.supercompute.official_prospective freeze --ledger ledger --source official-capture/ssq/verified_latest.json --raw official-capture/ssq/raw --candidate candidate.json --target-issue 2026130 --cutoff-utc 2026-11-12T12:00:00+00:00

The example cutoff is NOT a verified official cutoff; the example MUST NOT be run if the time has passed. The tool does not buy tickets.

Score only an existing forecast after corroborated outcome:

    python -m research.supercompute.official_prospective score --ledger ledger --source official-capture/ssq/verified_latest.json --raw official-capture/ssq/raw

## Remaining independent formal gates

- Authenticated and current official source history, true future draw identity and authoritative sales cutoff / market closure arrangements.
- Official pre-draw six-arm V4.7 model production and a durable original prediction batch without modification.
- RFC3161 signature, approved CA trust and bounded token accuracy truly before the cutoff; source hashes and Git commits do not substitute for this (RFC3161 https://www.rfc-editor.org/rfc/rfc3161).
- Complete prospectively scored and independently validated cohort, source failure preservation, restoration/reboot evidence, independently reviewed GitHub PR. No positive historical fitting result is a predictive edge claim.

Until these gates are independently proven: ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; FORMAL_A=0; NO_EDGE.

Official website references:
- https://www.swlc.net.cn/lottery/ssq.html
- https://www.yzfcw.com/
- https://www.gstc.org.cn/wanfa/dlt
- https://www.js-lottery.com/wfzq/dlt/data
- https://api.js-lottery.com/cms/post-148233.html (per-issue example only, not hardcoded to latest)
