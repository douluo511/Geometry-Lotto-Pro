# Optional Agents SDK runner

`sdk_runner.run_agent(context, config, fixture_model=None)` runs exactly one
OpenAI Agents SDK `Agent` through `Runner.run`. Its only capabilities are five
`function_tool` groups:

| Tool | Model-supplied arguments |
| --- | --- |
| `discover_sources` | None |
| `verify_official_sources` | None |
| `run_frozen_models` | None |
| `audit_experiment` | `action`, `hypothesis_json` |
| `deliver_report` | None |

`audit_experiment` accepts `inspect`, `register_hypothesis`, or
`run_registered_experiment`. Registration passes a strict JSON object string
to the host policy; other actions require an empty string. The host owns the
one registered hypothesis and selects the sole registered diagnostic. There
are no model-selected paths, commands, URLs, targets, model parameters or
delivery recipients. The host validates the complete hypothesis schema and
fixed synthetic diagnostic parameters. Prospective D2 experiments stay blocked.

The context must implement these synchronous methods:

```python
call_tool(name: str, arguments: dict) -> dict
begin_model_call(estimated_input_tokens: int, max_output_tokens: int) -> None
finish_model_call(usage: dict) -> None
mark_model_call_unknown() -> None
```

The begin method must durably reserve a call before execution. The finish
method records observed usage. Cancellation, timeout, invalid usage, or a
provider failure leaves an uncertain call recorded through the unknown method;
the runner never retries it. Host tool counters, source pins, deadlines and
idempotency remain host responsibilities.
An uncertain live outcome reports `paid_api_calls=null`; its bounded attempt is
still counted in `paid_api_call_attempts`. Missing live provider token usage
also requires reconciliation. An attempted request is not a billing receipt.

## Live preconditions

The runner requires `OPENAI_API_KEY`, `GLP_AGENT_MODEL`, and explicit positive
`sdk.input_usd_per_million` / `sdk.output_usd_per_million` prices. Missing values
return `BLOCKED_MISSING_*` before model execution. It reads no credentials or
model choice from other configuration files and supplies no default model.
Prices are operator inputs; the runner does not claim they are current.

The only provider construction is `OpenAIResponsesModel` with `AsyncOpenAI`,
`base_url="https://api.openai.com/v1"`, `max_retries=0`, a bounded HTTP timeout,
and a dedicated HTTP client with environment proxies and redirects disabled.
Ambient organization/project metadata and unrelated optional credentials are
suppressed explicitly. Nonempty `OPENAI_CUSTOM_HEADERS` blocks a live run so
ambient headers cannot override authentication or add undisclosed data.
There are no hosted tools, handoffs, MCP servers, shell tools or chat-completion
fallback. Tracing is disabled using the environment setting, the SDK global
switch, and `RunConfig(tracing_disabled=True)`.

Defaults are 10 SDK turns, 8 model calls, 20,000 total observed input tokens,
1,000 output tokens per call, 120 seconds, and USD 0.20 of locally estimated
cost. Operator configuration is validated up to absolute ceilings of 20 turns,
16 calls, 100,000 input tokens, 4,000 output tokens per call, 600 seconds and
USD 1,000. The runner enforces the actual configured limits. Input
reservations use serialized request UTF-8 bytes plus framing overhead. Cost
reservations include that input estimate and the maximum output size, then
reconcile to reported token usage. These are conservative local estimates,
**not a provider billing guarantee**; unknown calls retain their reservation.
Usage already consumed cannot be undone if a provider reports an overage.

`deadline_kind` explicitly reports
`COOPERATIVE_TOOLS_AND_HTTP_TIMEOUT_NOT_OS_KILL`. The runner checks before and
after synchronous host tools and cancels awaited model calls on timeout. It
cannot preempt a blocking synchronous tool or kill an operating-system process.

## Evidence and offline validation

`status` describes SDK runtime completion or blocking only. `model_message` is
advisory text limited to 2,000 characters. The caller must reconstruct research
and delivery results from verified host state and must never accept a model's
claimed status, number, authorization or readiness as evidence.

`fixture_model` is an offline test seam for an SDK `Model` implementation. It
executes the actual SDK tool loop while reporting `SDK_SIMULATED_MODEL` and
`paid_api_calls=0`; it is never an automatic fallback for a missing live model.
The tests make no paid API calls. Optional-SDK tests explicitly skip when the
dependency is unavailable, so a skip is not an actual SDK integration pass.

`sdk_fixture.make_fixture_model()` constructs a fixed offline workflow fixture:
the five groups, one strict synthetic hypothesis registration and diagnostic,
then report delivery. It takes eight SDK model calls with zero provider tokens.

```powershell
..\.venv-agent\Scripts\python.exe -m unittest research.ssq_dlt_agent_v1.tests.test_sdk_runner -v
```

Official references: [Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk),
[models and providers](https://developers.openai.com/api/docs/guides/agents/models),
and [integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability).
