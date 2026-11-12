# SSQ + DLT official-source quorum and prospective research evidence gates

Date 2026-11-12. This extends the existing SSQDLT P0/research evidence loop; it does not create another Harness or modify formal V4.7 six-arm producers, fixed Random NULL seeds, frozen ledgers or previous forecasts.

## GitHub code-only storage policy (updated by user)

GitHub contains formula/algorithm **source code**, synthetic tests, CI code checks and implementation documentation only. **Never** run real-source HTTP probes or upload raw HTTP bodies, actual draw results, model tickets, pre-draw receipts, score results, ledger state, or artifacts into GitHub Actions. The previous on-GitHub schedule and append-to-ledger job from this PR were removed; the new Actions workflow runs only deterministic offline synthetic regression tests on Windows and Ubuntu.

The program REJECTS an observation output directory or immutable receipt destination inside the Git checkout. Run locally on the user's authorized Windows computer with a private persistent directory outside this repository; keep the private audit history there. GitHub .gitignore additionally excludes likely accidental generated data paths, but does not erase pre-existing tracked files, historical commits, past Action logs, or previously generated artifacts. Do not falsely claim those old records were deleted. Independent trusted timestamping and offsite encrypted backup for the private append-only evidence remain separate future gates.

Windows PowerShell example (data does not enter the repository):

    $privateRoot = Join-Path $env:LOCALAPPDATA 'GeometryLottoPrivate'
    python -m research.supercompute.official_probe --game ssq --out (Join-Path $privateRoot 'official-capture/ssq')
    python -m research.supercompute.official_probe --game dlt --out (Join-Path $privateRoot 'official-capture/dlt')
    python -m research.supercompute.official_prospective audit --ledger (Join-Path $privateRoot 'ledger')

No locally scheduled job is claimed to have been installed. A future unattended local run must require the user's authorization, a persistent local drive, recovery tests and secure backups.

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
- No GitHub-scheduled production workflow or remote ledger write is included. All real evidence remains on local/private authorized storage outside the checkout.

## Commands (Windows-compatible; Python 3.11+)

    python -m pip install requests
    python -m unittest discover -s research/supercompute/tests -p test_*.py -v
    python -m research.supercompute.official_probe --game ssq --out ../private-lottery-data/official-capture/ssq
    python -m research.supercompute.official_probe --game dlt --out ../private-lottery-data/official-capture/dlt
    python -m research.supercompute.official_prospective audit --ledger ../private-lottery-data/ledger

Research shadow freeze (only when a verified source manifest, separate candidate and FUTURE claimed cutoff exist):

    python -m research.supercompute.official_prospective freeze --ledger ../private-lottery-data/ledger --source ../private-lottery-data/official-capture/ssq/verified_latest.json --raw ../private-lottery-data/official-capture/ssq/raw --candidate ../private-lottery-data/candidate.json --target-issue 2026130 --cutoff-utc 2026-11-12T12:00:00+00:00

The example cutoff is NOT a verified official cutoff; the example MUST NOT be run if the time has passed. The tool does not buy tickets.

Score only an existing forecast after corroborated outcome:

    python -m research.supercompute.official_prospective score --ledger ../private-lottery-data/ledger --source ../private-lottery-data/official-capture/ssq/verified_latest.json --raw ../private-lottery-data/official-capture/ssq/raw

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
