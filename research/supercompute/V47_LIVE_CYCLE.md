# V4.7 official-source live closed-loop research workflow

Purpose: run eleven named model computations for each of the two lotteries against the newest *published and cross-matched* official provincial source records; produce 22 attributed rows; freeze by real next-issue identifier; score each of those rows only when its outcome appears on the same independently re-fetched publisher history.

## Timing and deployment

Workflow: `.github/workflows/v47-official-live-cycle.yml`. Schedule at **10:41 and 15:41 UTC** (18:41 and 23:41 Asia/Shanghai), plus a manual `workflow_dispatch` and read-only pull-request audit. GitHub schedules can be delayed/dropped. The cloud scheduled write job is gated by the event **schedule**, repository `douluo511/Geometry-Lotto-Pro`, branch `main`, and a successful live publisher fetch. PR/manual runs cannot write the live ledger. The separate existing P0 schedule ledger remains unchanged.

Source ingestion: SSQ from `https://www.swlc.net.cn/lottery/ssq.html?limit=100&view=previous`, DLT from `https://www.js-lottery.com/wfzq/dlt/data`. The task stores raw HTTP HTML bytes, response SHA-256, effective URL, response code, content type and a parser version. It checks at least three overlap issues against the current previously issued seed + 42-issue documented history delta. Any conflicting draw, missing next issue, future-dated winning number, HTTP failure or publisher domain mismatch writes a create-only failure receipt and suppresses all live forecasting/scoring.

On successful live ingestion, the next issue is computed as `int(last_published_issue)+1`, never `RESEARCH_UNVERIFIED_*_RUN_*`. The per-game generation refuses duplicate real issue freezes. Before attempting a freeze it checks the nominal scheduled draw calendar: SSQ Tuesday/Thursday/Sunday 21:15 China; DLT Monday/Wednesday/Saturday 21:25 China. If that time has passed but issuer results have not been published, generation is explicitly skipped. After generation the actual frozen `created_utc` is checked again against that time. Holidays may invalidate the nominal calendar; therefore the time guard is not a trusted pre-draw seal.

Live evidence is stored separately in the create-only Git branch `ssqdlt-v47-live-ledger-v1`, folder `research/v47_live_ledger`. Each actual schedule run archives raw issuer HTML with SHA-256, a hash-chained scheduled event with run ID, code SHA, frozen report and 11-ticket per-game forecasts. A later run fetches the publisher pages again and scores previously frozen real issues when their results have been published. All 11 model results and pre-draw-by-nominal-time flags are stored in a create-only score receipt. The latest champion report is a mutable convenience index; immutable original forecasts and ledger events never get overwritten.

## Tests and acceptance

Run `python -m unittest discover -s research/supercompute/tests -p 'test_v47_official_ingest.py' -v`, then `test_v47_official_score.py` and `test_v47_live_ledger.py`. Test read-only publisher ingestion before promoting to unattended scheduled writes. The cloud branch must be independently restored from remote and verified with `python -m research.supercompute.v47_live_ledger verify --ledger <checked-out-worktree>`.

Do NOT treat a pull-request smoke test, workflow dispatch, source-fetch success, a fake scheduled unit-test context or a merely registered cron as a successful real scheduled run. A trustworthy P0 acceptance requires at least two actual completed GitHub event=schedule runs and persisted chain recovery. As of development, the original V4.7 P0 ledger has **one** completed schedule record. The new live ledger has no genuine completed schedules yet.

## Limitations

Authoritative provincial pages are cross-matched over HTTPS, but are not digitally signed. `signed_issuer_feed=false`, `trusted_predraw_seal=false` and `edge=NO_EDGE` remain in force. Source access may fail (HTTP 403/5xx or anti-bot page), in which case no new candidate or outcome is accepted. Cloud worker restart evidence cannot establish Windows host physical reboot recovery. Lottery draws under fair mechanical conditions are not made reliably predictable by frequencies, evolutionary optimization or toy physics. All outputs are research, not money/prize claims.
