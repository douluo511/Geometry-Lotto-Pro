"""Fixed offline SDK Model fixture. Never a live API or a fallback model."""
import json


def make_fixture_model():
    """Return a scripted SDK Model that exercises the fixed host workflow.

    This fixture supplies Responses objects to the actual SDK Runner. There is
    no HTTP client, paid API call, model inference, or observed provider usage.
    All reported token usage is zero because it is a simulation.
    """
    from agents import Model
    from agents.items import ModelResponse
    from agents.usage import Usage
    from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

    hypothesis = dict(
        question="Does fixed pair shrinkage reduce error in the prebuilt synthetic diagnostic?",
        falsification="The paired synthetic error difference is nonpositive or its uncertainty includes zero.",
        kind="synthetic_pair_shrink",
        parameters=dict(window=60, tau=200, seed=20261018, cases_per_game=20),
    )
    script = (
        ("discover_sources", {}),
        ("verify_official_sources", {}),
        ("run_frozen_models", {}),
        ("audit_experiment", dict(action="inspect", hypothesis_json="")),
        ("audit_experiment", dict(action="register_hypothesis", hypothesis_json=json.dumps(hypothesis, sort_keys=True))),
        ("audit_experiment", dict(action="run_registered_experiment", hypothesis_json="")),
        ("deliver_report", {}),
    )

    class OfflineWorkflowModel(Model):
        def __init__(self):
            self.calls = 0

        async def get_response(self, system_instructions, input, model_settings,
                               tools, output_schema, handoffs, tracing, **kwargs):
            index = self.calls
            self.calls += 1
            if index < len(script):
                name, arguments = script[index]
                output = [ResponseFunctionToolCall(type="function_call", call_id=f"offline_{index}",
                          name=name, arguments=json.dumps(arguments, sort_keys=True))]
            elif index == len(script):
                output = [ResponseOutputMessage(id="offline_final", type="message", role="assistant", status="completed",
                          content=[ResponseOutputText(type="output_text", annotations=[],
                          text="SDK_SIMULATED_MODEL: the offline SDK fixture ended. Consult the host's verified report; this is not a live model result.")])]
            else:
                raise RuntimeError("OFFLINE_FIXTURE_EXHAUSTED")
            return ModelResponse(output=output, usage=Usage(requests=1, input_tokens=0,
                                 output_tokens=0, total_tokens=0), response_id=f"offline_{index}")

        async def stream_response(self, *args, **kwargs):
            raise RuntimeError("OFFLINE_FIXTURE_STREAMING_UNSUPPORTED")
            yield

    return OfflineWorkflowModel()
