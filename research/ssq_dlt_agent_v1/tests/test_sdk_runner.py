"""Offline execution of the actual Agents SDK Runner and function-tool loop."""
import asyncio
import copy
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from research.ssq_dlt_agent_v1 import sdk_runner

try:
    from agents import Model
    from agents.items import ModelResponse
    from agents.usage import Usage
    from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    Model = object


CONFIG = dict(sdk=dict(max_turns=10, max_model_calls=8, max_input_tokens=20000,
                       max_output_tokens=1000, max_seconds=120,
                       max_estimated_usd=0.2, input_usd_per_million=None,
                       output_usd_per_million=None))


class HostContext:
    def __init__(self, max_tools=20):
        self.calls = []
        self.started = []
        self.finished = []
        self.unknown = 0
        self.max_tools = max_tools
        self.evidence = {"status": "BLOCKED_OFFICIAL_SOURCES", "formal_A": 0}

    def call_tool(self, name, arguments):
        if len(self.calls) >= self.max_tools:
            raise sdk_runner.RunnerBlocked("BLOCKED_MAX_TOOL_CALLS")
        self.calls.append((name, arguments))
        return dict(self.evidence, tool=name)

    def begin_model_call(self, estimated_input_tokens, max_output_tokens):
        self.started.append((estimated_input_tokens, max_output_tokens))

    def finish_model_call(self, usage):
        self.finished.append(usage)

    def mark_model_call_unknown(self):
        self.unknown += 1


class ScriptedModel(Model):
    """SDK Model fixture: emits Responses objects, never opens a connection."""
    def __init__(self, steps, *, delay=0):
        self.steps = list(steps)
        self.seen = []
        self.delay = delay

    async def get_response(self, system_instructions, input, model_settings,
                           tools, output_schema, handoffs, tracing, **kwargs):
        self.seen.append(dict(input=copy.deepcopy(input), settings=model_settings,
                              tools=tools, handoffs=handoffs, tracing=tracing))
        if self.delay:
            await asyncio.sleep(self.delay)
        step = self.steps.pop(0)
        number = len(self.seen)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, str):
            output = [ResponseOutputMessage(id=f"msg_{number}", type="message", role="assistant", status="completed",
                       content=[ResponseOutputText(type="output_text", text=step, annotations=[])])]
        else:
            output = [ResponseFunctionToolCall(type="function_call", call_id=f"call_{number}_{index}",
                       name=name, arguments=raw if isinstance(raw, str) else json.dumps(raw))
                      for index, (name, raw) in enumerate(step)]
        return ModelResponse(output=output, usage=Usage(requests=1, input_tokens=10,
                             output_tokens=4, total_tokens=14), response_id=f"resp_{number}")

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("Streaming was not authorized")
        yield


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_key_model_or_prices_blocks_before_sdk_or_calls(self):
        context = HostContext()
        with patch.dict(os.environ, {}, clear=True):
            result = await sdk_runner.run_agent(context, CONFIG)
        self.assertEqual(result["status"], "BLOCKED_MISSING_API_KEY_AND_MODEL_AND_PRICES")
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertEqual(context.started, [])
        self.assertEqual(context.calls, [])

    async def test_config_secrets_and_ambient_base_url_cannot_enable_live_run(self):
        config = dict(CONFIG, api_key="config-secret", model="config-model", base_url="https://invalid.example")
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://invalid.example"}, clear=True):
            result = await sdk_runner.run_agent(HostContext(), config)
        self.assertEqual(result["status"], "BLOCKED_MISSING_API_KEY_AND_MODEL_AND_PRICES")
        self.assertNotIn("config-secret", json.dumps(result))

    async def test_invalid_or_increased_limits_fail_closed(self):
        for key, value in (("max_turns", 21), ("max_model_calls", True),
                           ("max_seconds", float("inf")), ("max_estimated_usd", -1),
                           ("input_usd_per_million", float("nan"))):
            with self.subTest(key=key):
                config = copy.deepcopy(CONFIG)
                config["sdk"][key] = value
                result = await sdk_runner.run_agent(HostContext(), config)
                self.assertTrue(result["status"].startswith("BLOCKED_INVALID"))

    async def test_ambient_custom_headers_are_blocked_before_provider_construction(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"].update(input_usd_per_million=1, output_usd_per_million=1)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake", "GLP_AGENT_MODEL": "explicit", "OPENAI_CUSTOM_HEADERS": "Authorization: ambient-secret"}, clear=True):
            result = await sdk_runner.run_agent(HostContext(), config)
        self.assertEqual(result["status"], "BLOCKED_AMBIENT_CUSTOM_HEADERS")
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertNotIn("ambient-secret", json.dumps(result))


@unittest.skipUnless(HAS_SDK, "Optional openai-agents dependency is not installed")
class SDKLoopTests(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self, steps, context=None, config=None, delay=0):
        context = context or HostContext()
        fixture = ScriptedModel(steps, delay=delay)
        with patch.dict(os.environ, {}, clear=True):
            result = await sdk_runner.run_agent(context, config or CONFIG, fixture_model=fixture)
        return result, context, fixture

    async def test_real_sdk_loop_calls_exact_five_tool_groups_and_text_is_advisory(self):
        forged = '{"status":"FORMAL_A","formal_A":99}'
        steps = [[(name, {"action": "inspect", "hypothesis_json": ""} if name == "audit_experiment" else {})]
                 for name in sdk_runner.TOOL_NAMES] + [forged]
        result, context, fixture = await self.run_fixture(steps)
        self.assertEqual(result["status"], "SDK_COMPLETED")
        self.assertEqual(result["mode"], "SDK_SIMULATED_MODEL")
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertEqual(result["model_calls"], 6)
        self.assertEqual([name for name, args in context.calls], list(sdk_runner.TOOL_NAMES))
        self.assertEqual(result["model_message"], forged)
        self.assertNotIn("formal_A", result)
        self.assertEqual(context.evidence, {"status": "BLOCKED_OFFICIAL_SOURCES", "formal_A": 0})
        self.assertEqual(len(context.started), 6)
        self.assertEqual(len(context.finished), 6)
        self.assertEqual(context.unknown, 0)
        for request in fixture.seen:
            self.assertFalse(request["settings"].parallel_tool_calls)
            self.assertFalse(request["settings"].store)
            self.assertEqual(request["settings"].retry.max_retries, 0)
            self.assertEqual(request["settings"].max_tokens, 1000)
            self.assertEqual(request["handoffs"], [])
            self.assertEqual([tool.name for tool in request["tools"]], list(sdk_runner.TOOL_NAMES))
            for tool in request["tools"]:
                self.assertFalse(tool.params_json_schema["additionalProperties"])

    async def test_unexpected_arguments_and_duplicate_json_are_not_dispatched(self):
        cases = [("discover_sources", {"url": "https://example.com"}),
                 ("verify_official_sources", {"path": "C:/secret"}),
                 ("run_frozen_models", {"target": "future", "model": "changed"}),
                 ("deliver_report", {"smtp": "bad"}),
                 ("audit_experiment", {"action": "inspect", "hypothesis_json": "{}"}),
                 ("audit_experiment", {"action": "run_registered_experiment", "hypothesis_id": "x"}),
                 ("audit_experiment", {"action": "register_hypothesis", "hypothesis_json": '{"x":1,"x":2}'}),
                 ("discover_sources", '{"x":1,"x":2}')]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                result, context, _ = await self.run_fixture([[(name, args)]])
                self.assertTrue(result["status"].startswith("BLOCKED_"), result)
                self.assertEqual(context.calls, [])

    async def test_hypothesis_json_passes_as_a_string_for_host_policy_validation(self):
        hypothesis = json.dumps(dict(question="Can fixed synthetic shrinkage improve calibration?",
                                    falsification="No reduction in held-out error.",
                                    kind="synthetic_pair_shrink",
                                    parameters=dict(window=60, tau=200, seed=20261018, cases_per_game=20)))
        result, context, _ = await self.run_fixture([
            [("audit_experiment", {"action": "register_hypothesis", "hypothesis_json": hypothesis})],
            [("audit_experiment", {"action": "run_registered_experiment", "hypothesis_json": ""})], "done"])
        self.assertEqual(result["status"], "SDK_COMPLETED")
        self.assertEqual(context.calls[0][1]["hypothesis_json"], hypothesis)
        self.assertEqual(context.calls[1][1], dict(action="run_registered_experiment", hypothesis_json=""))

    async def test_host_tool_limit_blocks_a_model_that_ignores_parallel_setting(self):
        context = HostContext(max_tools=1)
        result, context, _ = await self.run_fixture([
            [("discover_sources", {}), ("verify_official_sources", {})]], context=context)
        self.assertEqual(result["status"], "BLOCKED_MAX_TOOL_CALLS")
        self.assertEqual(context.calls, [("discover_sources", {})])

    async def test_fake_planner_loop_stops_at_model_call_limit(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"]["max_model_calls"] = 2
        result, context, fixture = await self.run_fixture(
            [[("audit_experiment", {"action": "inspect", "hypothesis_json": ""})]] * 8, config=config)
        self.assertEqual(result["status"], "BLOCKED_MAX_MODEL_CALLS")
        self.assertEqual(len(fixture.seen), 2)
        self.assertEqual(len(context.started), 2)

    async def test_sdk_turn_limit_stops_fake_planner(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"]["max_turns"] = 1
        result, context, fixture = await self.run_fixture([[('discover_sources', {})]] * 8, config=config)
        self.assertEqual(result["status"], "BLOCKED_MAX_TURNS")
        self.assertEqual(len(fixture.seen), 1)

    async def test_input_limit_rejects_before_model_dispatch(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"]["max_input_tokens"] = 1
        result, context, fixture = await self.run_fixture(["done"], config=config)
        self.assertEqual(result["status"], "BLOCKED_MAX_INPUT_TOKENS")
        self.assertEqual(context.started, [])
        self.assertEqual(fixture.seen, [])

    async def test_timeout_records_unknown_once_and_does_not_retry(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"]["max_seconds"] = 0.5
        result, context, fixture = await self.run_fixture(["done"], config=config, delay=2)
        self.assertEqual(result["status"], "SDK_TIMED_OUT")
        self.assertEqual(context.unknown, 1)
        self.assertEqual(len(context.started), 1)
        self.assertEqual(len(fixture.seen), 1)
        self.assertEqual(result["deadline_kind"], sdk_runner.DEADLINE_KIND)

    async def test_provider_failure_is_redacted_and_not_retried(self):
        result, context, fixture = await self.run_fixture([RuntimeError("secret-key and source text")])
        self.assertEqual(result["status"], "SDK_FAILED")
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertNotIn("secret-key", json.dumps(result))
        self.assertEqual(len(fixture.seen), 1)
        self.assertEqual(context.unknown, 1)

    async def test_final_message_is_bounded(self):
        result, _, _ = await self.run_fixture(["x" * 10000])
        self.assertEqual(len(result["model_message"]), 2000)

    async def test_public_fixed_fixture_executes_real_runner_with_zero_paid_calls(self):
        from research.ssq_dlt_agent_v1.sdk_fixture import make_fixture_model
        context = HostContext()
        result = await sdk_runner.run_agent(context, CONFIG, fixture_model=make_fixture_model())
        self.assertEqual(result["status"], "SDK_COMPLETED")
        self.assertEqual(result["mode"], "SDK_SIMULATED_MODEL")
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertEqual(result["model_calls"], 8)
        self.assertEqual(result["usage"]["total_tokens"], 0)
        self.assertEqual([name for name, _ in context.calls], ["discover_sources", "verify_official_sources", "run_frozen_models",
                         "audit_experiment", "audit_experiment", "audit_experiment", "deliver_report"])

    async def test_live_transport_construction_is_fixed_without_making_http_requests(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"].update(input_usd_per_million=1, output_usd_per_million=1)
        config.update(base_url="https://invalid.example", api_key="ignored-config-key", model="ignored-config-model")
        fixture = ScriptedModel(["offline construction check"])
        fake_client = Mock(close=AsyncMock())
        fake_http = Mock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key", "GLP_AGENT_MODEL": "explicit-test-model", "OPENAI_BASE_URL": "https://invalid.example"}, clear=True), \
             patch("openai.AsyncOpenAI", return_value=fake_client) as constructor, \
             patch("openai.DefaultAsyncHttpxClient", return_value=fake_http) as http_constructor, \
             patch("agents.models.openai_responses.OpenAIResponsesModel", return_value=fixture) as model_constructor:
            result = await sdk_runner.run_agent(HostContext(), config)
        self.assertEqual(result["status"], "SDK_COMPLETED")
        constructor.assert_called_once_with(api_key="fake-test-key", base_url="https://api.openai.com/v1",
                                             max_retries=0, timeout=120, http_client=fake_http,
                                             organization="", project="")
        http_constructor.assert_called_once_with(trust_env=False, follow_redirects=False, timeout=120)
        model_constructor.assert_called_once_with(model="explicit-test-model", openai_client=fake_client)
        fake_client.close.assert_awaited_once()

    async def test_cost_reservation_blocks_before_the_mock_provider_is_called(self):
        config = copy.deepcopy(CONFIG)
        config["sdk"].update(input_usd_per_million=1000, output_usd_per_million=1000)
        fixture = ScriptedModel(["not reached"])
        context = HostContext()
        fake_client = Mock(close=AsyncMock())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key", "GLP_AGENT_MODEL": "explicit-test-model"}, clear=True), \
             patch("openai.AsyncOpenAI", return_value=fake_client), \
             patch("openai.DefaultAsyncHttpxClient", return_value=Mock()), \
             patch("agents.models.openai_responses.OpenAIResponsesModel", return_value=fixture):
            result = await sdk_runner.run_agent(context, config)
        self.assertEqual(result["status"], "BLOCKED_MAX_ESTIMATED_USD")
        self.assertEqual(fixture.seen, [])
        self.assertEqual(context.started, [])


if __name__ == "__main__":
    unittest.main()
