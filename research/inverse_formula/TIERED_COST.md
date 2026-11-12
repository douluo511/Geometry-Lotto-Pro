# SSQ + DLT: tiered six-specialist, cost-guarded research council

**Research-only / NO_EDGE.** This replaces the original fixed 24-request
6-propose + 6-review strategy **within the one-click research workflow only**.
Formal V4.7 ledger, original fixed Random NULL, selectors and forecasts remain
untouched. Draft PR #470 stays unmerged.

## Phases and request count

For each game, the roles remain six but their model allocation changes:

| Phase | Specialist role | Model | Requests/game |
|---|---|---|---|
| A. Independent formula proposals | Mathematician | gpt-6.1-sol | 1 |
| A. Independent formula proposals | Formula discovery | gpt-6-luna | 1 |
| A. Independent formula proposals | Ensemble researcher | gpt-6.1-terra | 1 |
| A. Independent formula proposals | Statistician | gpt-6-sol | 1 |
| A. Independent formula proposals | Engineer | gpt-6-luna | 1 |
| B. Review of at most 3 shortlisted formulas | Skeptical reviewer | gpt-6-astra | 1 |
| C. Deterministic computations | Python, no model | None | 0 |

A complete dual-game run uses **at most 12 billed requests** (5 cheap + 1
Astra for each game, Astra **2** requests total). All roles request
reasoning.effort=high. Six roles are not six different model IDs: Luna is
used twice, in separately attributed requests.

Before each review, Python validates bounded integer recurrences, deduplicates
formula IDs, and selects the three lowest complexity formula identities.
The filter NEVER ranks newly proposed formulas using known historical wins.
The Astra reviewer returns one validated verdict for every shortlisted
formula. Reject means exclusion; test/needs_evidence are weighted and passed
to deterministic Python voting. If all are rejected, the program refuses to
invent a ticket. Only Python builds SSQ/DLT full tickets, D2, candidate dan
and sha, content seals, source receipts and final reports.

'Dan' and 'sha' denote research candidate keep/exclude lists, never certain
winning/losing numbers.

## Built-in budget controller

- Configured limit: SSQDLT_MAX_USD, default USD 3.00 per click.
- Request cap: SSQDLT_MAX_REQUESTS, default 12 and cannot exceed 12.
- Each request uses max_output_tokens=8192, including hidden reasoning.
- Each guarded request explicitly uses service_tier=default. The returned
  model ID must exactly match the configured priced model and the returned
  tier must be default. Missing or changed identities abort the run with
  the reservation retained; they are never settled using the standard
  price table. Versioned model IDs need a separately reviewed price mapping.
  The budget audit records pricing_service_tier. This prevents an omitted
  tier from silently inheriting a more expensive API project setting.
  Contract: https://developers.openai.com/api/reference/resources/responses/methods/create .
- No parallel paid requests, implicit retry, background model fanout or
  unmetered fallback. Request admission reserves the conservative maximum
  estimated cost before contacting the provider. It uses a UTF-8 prompt-byte
  upper estimate + framing margin and full allowed output tokens.
- OpenAI Response usage records input_tokens, output_tokens, cached_tokens
  and reasoning_tokens. Output usage **already includes reasoning**: the
  controller does not add reasoning tokens twice. For conservative cost
  accounting, cached input is priced at the full noncached input rate.
- After each successful Response, the local reservation is replaced with
  its observed usage-based price estimate. Missing usage, incomplete
  response, network error, unexpected token counts or insufficient budget
  ABORTS the run. Unknown-usage requests retain their reserved amount.
- An audit file named api-budget-audit.json is created even on failure.
  Partial outputs are also preserved as GitHub Actions artifacts.
- All research receipts are exclusive-write; previous files are never
  silently overwritten.

Prices snapshot checked on 2026-11-11, standard short-context, USD/1M:
Astra 10/50 input/output; Sol 2/10; Terra 1/5; Luna 0.10/0.50.
Pricing: https://developers.openai.com/api/docs/pricing .
Provider-specific, long-context, regional, processing, cache-write or price
changes may make actual bills different. **The local USD cap is NOT an
OpenAI account/project hard spend cap.** For genuine monetary enforcement,
configure an API project or organization hard spend limit separately:
https://developers.openai.com/api/docs/guides/rate-limits .

OpenAI recommends providing generous reasoning-token output headroom;
a request can consume reasoning budget and finish incomplete even if billed:
https://developers.openai.com/api/docs/guides/reasoning .

## Historical test: precise boundary

Python computes two different results:

1. An independently past-only one-step replay of the pre-existing
   deterministic research formula bank, including a separate research NULL.
2. Descriptive retrospective stats for the **newly GPT-proposed formulas**,
   applied using earlier inputs but selected AFTER seeing the full history.
   These are explicitly labeled POST_SELECTION_DESCRIPTIVE_NOT_INDEPENDENT;
   they are NOT true independent historical test results.

Only predictions sealed and externally visible BEFORE a future target draw
can build valid prospective evidence for the new GPT formulas. Until then,
NO_EDGE, and no V4.7 promotion. SHA256 is content integrity, not a trusted
external time attestation.

## GitHub use

GitHub Actions -> SSQ + DLT | Six-GPT one-click research meeting -> Run workflow.

Repository Settings -> Secrets and variables -> Actions:

- Secret OPENAI_API_KEY: private key; never commit or send it in chat.
- Variable SSQDLT_PAID_APPROVED: exact value true to explicitly enable billing.
- Optional variable SSQDLT_MAX_USD: e.g. 3.00. Refuses invalid, zero or
  over-USD-100 values.
- Optional variable SSQDLT_MAX_REQUESTS: e.g. 12 (range 1..12).
- Optional SSQDLT_PUBLISH_ISSUE=true publishes the final report as a
  persistent GitHub Issue. **Issues in public repositories are public.**

A complete run reports SSQ and DLT separately, with a combined Markdown
summary, role/model receipts, formulas, peer-review summaries, research
dan/sha, a formula evidence graph, content hashes, historical boundary
labels and input/output/reasoning Token ledger.

The workflow uses a pinned research commit verified by PR CI. This avoids
merging experimental predictors into official V4.7. Changing the research
branch alone will not change the pinned paid-run implementation until the
workflow file is deliberately reviewed and repinned.

## Verification

Offline regression tests simulate provider output and token usage; they do
NOT constitute real OpenAI model calls or billed usage. Tests verify
pre-request budget rejection, request-count ceiling, unknown-billing
reservation retention, Astra-only shortlisted review, deterministic ranking,
tampering, future cutoff isolation and the no-authorization stop. Real API
entitlements, true spend and any predictive superiority stay UNVERIFIED
until independently observed.
