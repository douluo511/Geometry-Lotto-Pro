# DLT physical draw source audit — P0 research-only stage

Purpose: record original Guangdong Sports Lottery DLT issuer-announcement
bytes and preserve **real ball exit order**, which is not the ascending
published combination. This is not a prediction engine and is not attached
to any formal V4.7 preregistered forecast or fixed Random NULL.

## Issuer and explicit issue identity

For an **already published** five-digit issue, e.g. `26105`:
`https://www.gdlottery.cn/f_html/kjgg/P085_26105.html`

Read-only command from the repository root:

```bash
python -m unittest discover -s research/supercompute/tests -p test_dlt_physical_source.py -v
python -m research.supercompute.automation.dlt_physical_source --issue 26105 --ledger ./local_dlt_physical_ledger
python -m research.supercompute.automation.dlt_physical_source --verify --ledger ./local_dlt_physical_ledger
```

Use a dedicated **non-version-controlled** evidence directory; no local
working tree/CI runner is a guaranteed permanent archive. To run in Actions,
select **DLT issuer physical draw evidence (research only)**, choose the code
branch and supply a real `issue`; the 30-day artifact includes source bytes
even for HTTP non-200 and blocked parses. GH workflow availability is not an
assertion that it ran or that unattended scheduling is operational.

## Canonical fields

`issue`, `draw_date` (only the explicit 开奖日期 field), `ball_group`,
`front_order` (five 1–35 values), `back_order` (two 1–12 values),
`front_sorted`, `back_sorted`, `source_url`, `source_sha256`.

The record is created once per issue under `draws/<issue>.json`. Raw
responses are content-addressed under `raw/<sha256>.bin`; one immutable
`attempts/<issue>/<utc>-<uuid>.json` receipt captures each fetch result,
including HTTP status, source URL/final URL, observed UTC, parser SHA256,
failure code and bytes SHA256 when available.

Repeated requests with unchanged physical data are `MATCHED_EXISTING`.
Conflicting group/date/balls are `BLOCKED`, never overwritten. The first
successful issuer record is not a cryptographically signed official fact;
another official issuer and document history must corroborate critical
facts before statistical or prospective admission.

## Explicit limitations and next gates

1. The HTML fixture in tests is synthetic and asserts parsing contracts. Real
   live HTML compatibility is **UNVERIFIED** until a successful real Actions
   run with archived raw bytes; websites can block or change their markup.
2. This stage does not discover the next issue, poll on a schedule, or persist
   observations to an independently verified remote Git branch. Manual
   workflow artifacts expire; unattended collection and remote persistence
   remain an **open P0 integration gate**.
3. No predictive effect is established by a ball-group difference or
   randomness-test rejection. Condition on information available *before*
   each draw and marginalize unseen ball-group state.
4. Never use sorted ball order for order-position analysis. Never treat
   publication/claim deadline as the draw date. Retain missing issues and
   parser failures as failed observations, not negative results.
5. No modifications to the mainline SSQ/DLT selectors, frozen forecasts,
   official-source gate, stable P0 scheduler, historical evidence or fixed
   Random NULL. No purchases, paid calls, or speculative forecasts.

Formal A = 0; edge decision = NO_EDGE.
