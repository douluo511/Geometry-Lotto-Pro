# Independent Multi-Model Council V1 (research-only)

This module actually makes **six API requests** for a three-model council:
three independent, parallel proposal calls followed by three separate,
parallel cross-review calls. It supports OpenAI Responses, Anthropic Messages,
and Google Gemini generateContent with HTTPS requests. The code **does not**
claim to have contacted these models until an authenticated live run succeeds.

No generated source code is executed. Each candidate is a constrained,
human-readable integer formula using one to three lags, bounded integer
coefficients, modulo the legal ball range, and a deterministic unique-ball
normalizer. Cross-review outputs are untrusted evidence, not commands.

## Windows configuration (PowerShell from repository root)

1. Review and optionally edit:
   research/inverse_formula/multi_provider_agents.example.json
   (model IDs must be enabled on the corresponding API accounts).
2. Create API credentials with the respective provider. Store them in Windows
   environment variables OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
   or configure GitHub Actions secrets with those exact names. **Never commit
   secrets, paste them into chat, or embed them in an audit report.**
3. Run live for exactly one chosen game with explicit --live:

    python -m research.inverse_formula.live_models --live --game ssq --agents research/inverse_formula/multi_provider_agents.example.json --out ssq-live-council.json

   For DLT replace --game ssq with --game dlt and change the output path.

4. Optional offline, no-charge adapter/committee tests:

    python -m pytest -q tests/test_inverse_live_models.py

Without --live, or when any required API key is missing, the command fails
closed and does not silently substitute a scripted response. A key can be
valid but lack access to the configured model; that also causes an error.
Make sure the user understands the model API billing is separate from ChatGPT
subscription access. Start small; no unattended schedule is configured.

## On GitHub Actions

The scoped research workflow has an optional workflow_dispatch input
live_models = true (false by default). The live-only job is not run for PRs,
requires GitHub Actions secrets, and uploads the resulting JSON receipt.
The ordinary Windows and Linux CI runs only the no-network mocked contract
tests. This cannot be used to certify that actual provider keys are installed.

## Two-round meeting contract

1. The model specification file lists 3..6 *distinct* model IDs from at
   least two providers, with distinct role names.
2. Every agent sees the same preceding 30 draws for its independent proposal.
   It cannot see the unknown target outcome or another agent's proposal.
3. A bounded schema validator rejects malformed model outputs or free-form
   executable code. Providers are not allowed to write local files.
4. Validated proposals are shown to the *other* agents for independent
   critique in the second round. All agent requests and outputs are logged
   with provider/model identity, provider response IDs when supplied, and SHA256 digests; secret values are omitted.
5. Every **unique** formula receives one vote; duplicated proposals are
   deduplicated. The resulting research candidate includes a separate D2 pair.
6. A receipt records the model configurations, two rounds, challenges,
   candidate tickets, exact as-of issue, status and SHA256.

A hash proves file-content integrity only; it does **not** prove that a
prediction was sealed before the draw. For an operational forecast, persist
a signed or externally timestamped record before the lottery deadline.

## Hard research boundaries

- A model seeing the last 30 draws can adapt to those observations. A
  backtest on those same data is **not** an independent holdout.
- Multiple formulas/reviewers can increase selection bias, not necessarily
  the chance of hitting a fair randomized lottery. There is no established
  advantage beyond random baselines.
- The current research fixtures are finite and some DLT sourcing is
  third-party; validate and update official draw history before relying on
  any 'next issue' field.
- All outputs remain NO_EDGE / research only, with no automatic V4.7
  promotion or changes to the frozen Random NULL, seeds or ledger.

Official API references:
OpenAI: https://developers.openai.com/api/reference/resources/responses/methods/create
Anthropic: https://platform.claude.com/docs/en/api/messages/create
Gemini: https://ai.google.dev/api/generate-content
