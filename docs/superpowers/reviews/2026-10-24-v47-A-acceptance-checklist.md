# V4.7 A acceptance checklist and separate D2 ruling — Issue #468

This operationalizes the user's existing criteria. It does not replace any
existing acceptance standard or invent score weights. Threshold: >=90/100 AND
every P0 gate, durable real-host closure, independent human review and faithfully
executed preregistered prospective sampling. The original numeric rubric and
raw basis for the historical D/52 claim were not retrieved: CURRENT_SCORE=UNKNOWN.
An audit status below is not a numerical grade and cannot be summed into A.

2026-10-27 evidence correction: this checklist began as a 2026-10-24 status snapshot. Its thresholds and counterexamples remain unchanged. The earlier statement that the independent V47G sealing interface was absent is superseded by `predraw_seal.py`, which now supports both V47 and V47G. Live source fetching/parsing and local byte replay also exist; current attempts are recorded separately. Implemented interfaces do not establish upstream/source-time authentication, approved trust policy, actual host acceptance or formal prospective evidence. Exact current code/run identities come from `work/current_runtime.json` / `work/latest_operation.json`; historical operation counts and old SHA declarations are not current-state evidence.

| Gate | Falsifiable pass evidence | Required counterexample / rejection | Current status |
|---|---|---|---|
| Identity and constraints | Exact repo/PR HEAD, parent/dependency SHAs, run/code/model/parameter/source identities; unchanged five candidates + fixed Random NULL, old ledger, main | Wrong SHA, new Harness/PR, changed NULL seed, old prediction substitution | Existing #468/#467 used; final scoped CI separately recorded |
| G00 official bytes and source independence | Two authenticated official upstreams per game; original HTTP entity bytes, URL/status/headers/capture time/SHA; 120+ aligned contiguous issue/balls/true draw dates | Same upstream on two hosts; error/WAF body; omitted failed fetch; post-hoc corrected original | SSQ 200 content matches; independence NOT_VERIFIED. DLT BLOCKED |
| G01 semantic history | Parser and independent raw-byte replay both distinguish draw_date, publication_date and observed_at; provenance for every field | Jiangsu publication-date table interpreted as draw dates; historical conflict silently repaired | Actual current guard rejects Jiangsu pages; not admitted history |
| G01 exact future target | Independent official issue, game, draw instant and sales cutoff with timezone; authoritative earliest applicable cutoff, holiday and regional/channel coverage; bounded trusted observation | Guess latest_issue+1; treat generic rule as certification of this particular issue; later regional deadline selected | Target/cutoff NOT_VERIFIED |
| Original-version replay | Complete six arms per game, exact original snapshot/model/parameter/NULL/card identities; trusted old source verified before execution; read-only old cards/scoring/receipt retries across upgrade | Comment/CRLF upgrade, absent/tampered/unknown artifact, mixed source arms, rehashed changed card/seed/parameters, missing arm, changed baseline | Scoped synthetic implementation and exact-HEAD evidence only; original host ledger NOT_VERIFIED |
| Freeze integrity and chronology | Unique preregistered D2 per arm, complete immutable input/source/model roster, actual pre-cutoff commit and independent external custody | Backfill, changed target reissue, late/future data, clock rollback, crash/parallel tick partial freeze | Synthetic guards only; authentic freeze NOT_VERIFIED |
| External RFC3161 | Approved independently authenticated trust anchor/chain, timestamping EKU, correct exact payload imprint, request nonce, known signed accuracy; upper signed bound strictly before certified cutoff; preserve token/request/CA evidence | Wrong nonce/imprint/chain, missing accuracy, boundary touching cutoff; local clock or Git commit passed off as TSA | Historical TEST_ONLY token lacks signed accuracy => BLOCKED. Current V47/V47G sealing and HTTPS transport interfaces exist; approved independently authenticated trust/admission and valid qualified future evidence remain NOT_VERIFIED |
| Authentic scoring | Independent official same-issue outcome + true draw time after cutoff; frozen card only; full D1-D5/ticket and paired same-draw NULL | Self-rehashed invented outcome, aliases, before-draw score, missing original outcome, changed existing receipt | Synthetic only; official outcomes NOT_VERIFIED |
| Durable host engineering | Identified authorized persistent Windows host/service account/config/volume; real 30-minute and boot task XML; witnessed end-to-end two-game freeze/seal/outcome/read-only score/cohort across reboot/power loss/retry/concurrency | Ephemeral Actions runner/preview called deployment; lost file, duplicate tick or reboot changes frozen state | Host task/boot queries denied; BLOCKED |
| Complete prospective sampling | Independently sealed preregistration: fixed five hypotheses/game, fixed NULL, exact inclusion/exclusion, sample size/power, stopping and multiplicity family; all eligible/pending/failed issues retained | Drop misses/pending draws; choose successful period or stopping rule afterward; historical lab renamed future evidence | Original host roster inaccessible; measured numerator/denominator NOT_VERIFIED |
| Independent acceptance | Separately identified human reviewer checks code + original evidence at exact final SHA, then signs with limitations | Author self-review or agent review called human approval | Independent agent review available; independent human sign-off NOT_VERIFIED |
| A decision | Original >=90/100 rubric independently scored and every preceding P0 passed; reproducible current-issue analysis complete | Any gate unknown/blocked but A granted | formal_A=0; no formal A |

## Independent scientific decision
Engineering/analysis quality A and D2 edge are separate decisions. Even an A
system must report NO_EDGE if complete future evidence does not establish an
advantage. Fair D2 rates remain SSQ=15/528 and DLT=10/595. Retain the same-draw
fixed Random NULL, report every game's complete n, wins/losses, intervals and
the preregistered corrected paired test/family, and require independent future
replication. A historical fit or an isolated nominal p-value is insufficient.
The historical DLT 69/2880 vs NULL 42/2880 anomaly remains unverified here and
unresolved; do not tune a model/seed or drop rows to suppress it.

Measured genuine future hits/n for SSQ, DLT and NULL in this session:
NOT_VERIFIED (original persistent host ledger unavailable), not newly measured
0/0 and not 0%. This session admitted no authentic prospective forecast.

ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET;
D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE.

## Conflicts retained explicitly
1. Old narrative: qualified future counts 0/0. Issue comment 6380148604 corrected
   the evidence basis. New measured counts remain NOT_VERIFIED; no fresh ledger
   inspection supports a numeric denominator.
2. Prior national DLT fetches reported HTTP567. This session's preserved first
   two pages returned HTTP200 valid JSON. That changes reachability evidence,
   not upstream independence, semantic approval or target/cutoff certification.
   Later page17 requests failed locally with WinError10013; no claim of a fresh
   historic16003/16004 conflict reproduction is made.
3. Old exact-head394 synthetic tests were green. The uncovered cross-version
   boundary produced a new genuine399-test RED on commit31b9861. New repair
   validation supersedes component evidence only, never official/source/host gates.
