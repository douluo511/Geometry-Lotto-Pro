# Six GPT Expert Research Council (research-only, V2)

The default research council now uses **six separately invoked GPT model IDs**
over **one OpenAI API account/key**. Two rounds run six proposals and six
cross-reviews (12 externally billed API calls). Do NOT describe these as six
different companies or independent providers. The model calls are isolated
but can share biases or training data. **No claim of improved lottery
predictability has been established.**

## Default expert assignment

| Research role | OpenAI API model ID | Responsibility |
|---|---|---|
| Mathematician | gpt-6-astra | Mathematical formula families, assumptions and falsifiability |
| Formula discovery | gpt-6.1-sol | Existing historical formula-bank exploration |
| Ensemble researcher | gpt-6-luna | Heuristic combination and diversity |
| Statistician | gpt-6-sol | D2/random NULL comparisons and multiplicity warnings |
| Skeptical reviewer | gpt-5.6-sol | Challenge leakage, chance results and overfitting |
| Engineer | gpt-6.1-terra | Input/legal-number validation and audit integrity |

The model IDs are documented in the OpenAI API catalog:
https://developers.openai.com/api/docs/models

Review any changes in the actual configuration file:
\`research/inverse_formula/multi_provider_agents.example.json\`

All six models need to be enabled for the OpenAI API project. The models
have different pricing and strengths; role labels do not guarantee expertise.
ChatGPT subscription access does not automatically grant API credits.

## Windows PowerShell launch

Open the repository root. Configure OPENAI_API_KEY locally (for example
using a secure environment variable loaded outside the repository). **Do not
paste API keys into the chat, code, GitHub commits, test fixtures or logs.**

Run an explicitly authorized, paid six-GPT council:

\`\`\`powershell
python -m research.inverse_formula.live_models --live --game ssq --agents research/inverse_formula/multi_provider_agents.example.json --out ssq-gpt-council.json
\`\`\`

For DLT:

\`\`\`powershell
python -m research.inverse_formula.live_models --live --game dlt --agents research/inverse_formula/multi_provider_agents.example.json --out dlt-gpt-council.json
\`\`\`

Each invocation runs two rounds of six OpenAI calls and may incur costs.
Without --live, or without OPENAI_API_KEY, the CLI refuses to run. If the
project lacks access to one of the six models, it fails rather than silently
substituting a simulated response.

The supplied SSQ and DLT fixtures are **historical research samples** and may
not include the latest draws. Validate authoritative source data and the
as-of cutoff before claiming a candidate for the actual next issue.

## Test without any live API calls

\`\`\`powershell
python -m pytest -q tests/test_inverse_live_models.py
\`\`\`

GitHub Actions PR checks run on Windows and Ubuntu without network
requests to paid model endpoints. They test only injected/mock model
responses, prompt separation, schema restrictions and committee receipts.

## GitHub Actions live option

The research workflow defines \`workflow_dispatch\` with
\`live_models=true\`. That job is disabled for ordinary pull requests and
must find a repository Actions secret named \`OPENAI_API_KEY\`. It only passes
this secret to the live job, and generates an audit artifact on success.
New manual workflow buttons may be unavailable until the workflow definition
exists on the repository's default branch. Do not merge the draft PR solely
to enable the button; use the Windows CLI or a separately approved deployment.

## Meeting protocol

1. Each configured GPT model receives a different specialty and the same
   already-known 30 historical draws. Role-specific evidence comes only from
   the past-only formula library and historical research replay.
2. Round one sends six requests concurrently. Each agent produces a bounded,
   declarative integer formula proposal without reading any other agent.
3. Strict schema checks reject malformed proposals, unexpected fields and
   model-generated executable code. Only verified integer recurrences are
   interpreted in Python.
4. Round two sends six independently executed review requests with the other
   five validated proposals. Review comments remain untrusted data.
5. The deterministic coordinator deduplicates identical formulas and
   calculates equal vote totals, one vote per unique formula. It outputs a
   valid research ticket and explicit D2 pair.
6. Audit JSON retains role/model identity, proposal IDs, reviews, provider
   response IDs if available, result hashes and overall SHA256.

A SHA256 audit receipt proves content consistency, but does **not** prove
external pre-draw timestamping. Independent prospective prediction requires
separate authenticated freezing and after-draw scoring.

## Statistical and engineering boundaries

- Historical reverse-fitting after knowing winning numbers is not evidence
  that the same formulas predict future fair lottery draws.
- More models/formulas may add selection bias. Unseen future samples and
  paired fair-random baselines are essential; no automatic model promotion.
- No OpenAI API key has been verified here and no real paid multi-GPT
  meeting has been completed in this branch's CI.
- V4.7 official models, fixed Random NULL, seeds and frozen scoring ledger
  remain unchanged.
