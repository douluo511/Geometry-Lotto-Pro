"""Mock-only Fable audit contract tests; zero paid API calls."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.automation.fable52_manual_review import (
    MODEL, ENDPOINT, SourceBlocked, make_request, perform_live_review, select_payload
)
from research.supercompute.automation.shadow_forward_loop import (
    PREFIX, seal_record, immutable_write
)


class FakeResponse:
    status = 200
    def __init__(self, content, model=MODEL):
        data = {
            'id': 'msg_offline_test', 'model': model,
            'content': [{'type': 'text', 'text': content}],
            'usage': {'input_tokens': 123, 'output_tokens': 44},
        }
        self.data = io.BytesIO(json.dumps(data).encode())
    def __enter__(self): return self
    def __exit__(self, *_): self.data.close()
    def geturl(self): return ENDPOINT
    def read(self, count): return self.data.read(count)


def fake_audit(**overrides):
    o = {'verdict': 'BLOCKED', 'findings': ['Not independent'],
         'required_tests': ['Untouched prospective samples'],
         'edge_proven': False, 'external_timestamp_verified': False}
    o.update(overrides)
    return json.dumps(o)


def fake_ledger(root):
    forecast = seal_record({
        'game': 'SSQ', 'target_issue': '2026131',
        'schema': 'SSQDLT_OFFICIAL_CROSSCHECK_SHADOW_FORECAST_V1',
        'source_latest_issue': '2026130',
        'selection': {'chosen': 'UNIFORM', 'validation_log_score_delta': {'UNIFORM': 0}},
        'source_crosscheck': {'official_window': 50, 'matched_issues': 50},
        'independent_random_null': {'front': [1,2,3,4,5,6], 'back': [1]},
        'claimed_timestamp_trust': 'GITHUB_RUNNER_CLOCK_NOT_EXTERNAL_TSA',
        'formal_A': 0, 'edge': 'NO_EDGE',
    })
    immutable_write(root, 'forecasts/SSQ-2026131.json', forecast)


class FableReviewTests(unittest.TestCase):
    def test_requires_existing_frozen_ticket(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SourceBlocked, 'FORECAST_NOT_FOUND'):
                select_payload(Path(tmp), 'SSQ', '2026131')

    def test_readonly_review_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_ledger(root)
            p = select_payload(root, 'SSQ', '2026131')
            self.assertEqual('SSQ', p['game'])
            self.assertEqual('RESEARCH_ONLY_NO_EDGE', p['status'])
            self.assertIn('original_forecast_sha256', p)
            self.assertNotIn('prediction', p)
            self.assertNotIn('independent_random_null', p)

    def test_model_id_request_contract(self):
        p = make_request({'status': 'RESEARCH_ONLY_NO_EDGE'})
        self.assertEqual(MODEL, p['model'])
        self.assertLessEqual(p['max_tokens'], 1400)
        self.assertNotIn('temperature', p)
        self.assertNotIn('tool_choice', p)
        self.assertNotIn('thinking', p)

    def test_requires_key(self):
        with self.assertRaisesRegex(SourceBlocked, 'NO_ANTHROPIC_API_KEY'):
            perform_live_review({}, key='')

    def test_valid_mock_response(self):
        result = perform_live_review(
            make_request({'x':1}), key='offline-test-key',
            opener=lambda req, timeout: FakeResponse(fake_audit()))
        self.assertEqual(MODEL, result['provider_model'])
        self.assertEqual('BLOCKED', result['review']['verdict'])
        self.assertFalse(result['review']['edge_proven'])
        self.assertEqual(123, result['input_tokens'])

    def test_reject_wrong_model(self):
        with self.assertRaisesRegex(SourceBlocked, 'MODEL_ID_NOT_VERIFIED'):
            perform_live_review({}, key='fake',
                opener=lambda req, timeout: FakeResponse(fake_audit(), model='some-other-model'))

    def test_reject_non_json_review(self):
        with self.assertRaisesRegex(SourceBlocked, 'NOT_STRICT_JSON'):
            perform_live_review({}, key='fake',
                opener=lambda req, timeout: FakeResponse('This seems okay'))

    def test_reject_false_edge_claim(self):
        with self.assertRaisesRegex(SourceBlocked, 'REVIEW_CONTRACT_INVALID'):
            perform_live_review({}, key='fake',
                opener=lambda req, timeout: FakeResponse(fake_audit(edge_proven=True)))

    def test_tampered_forecast_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_ledger(root)
            path = root / PREFIX / 'forecasts/SSQ-2026131.json'
            obj = json.loads(path.read_text())
            obj['source_latest_issue'] = '2026131'
            path.write_text(json.dumps(obj))
            with self.assertRaisesRegex(SourceBlocked, 'RECEIPT_TAMPERED'):
                select_payload(root, 'SSQ', '2026131')


if __name__ == '__main__':
    unittest.main()
