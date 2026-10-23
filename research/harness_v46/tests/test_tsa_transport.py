"""HTTP transport fixtures only; a transport receipt never verifies a TSA."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import requests
from research.harness_v46.core import GateError


class TSATransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.query = self.root / 'original.tsq'
        self.query.write_bytes(b'opaque-request-test-not-real-DER')

    def module(self):
        from research.harness_v46 import tsa_transport
        return tsa_transport

    def response(self, status=200, content=b'opaque-response-not-verified', content_type='application/timestamp-reply'):
        response = Mock()
        response.status_code = status
        response.headers = {'Content-Type':content_type}
        response.url = 'https://freetsa.org/tsr'
        response.iter_content.return_value = iter([content])
        return response

    def submit(self, name='transport', url='https://freetsa.org/tsr'):
        return self.module().submit_request(self.query, self.root/name, tsa_url=url)

    def test_exact_request_and_response_preserved_without_verification_claim(self):
        with patch('requests.post',return_value=self.response()) as post:
            result = self.submit()
        self.assertEqual(post.call_args.kwargs['data'],self.query.read_bytes())
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertNotIn('verify',post.call_args.kwargs) # requests default TLS verification
        self.assertEqual((self.root/'transport/request.tsq').read_bytes(),self.query.read_bytes())
        self.assertEqual((self.root/'transport/response.tsr').read_bytes(),b'opaque-response-not-verified')
        self.assertEqual(result['status'],'RESPONSE_PRESERVED_NOT_VERIFIED')
        self.assertEqual(result['external_tsa'],'NOT_VERIFIED')
        self.assertEqual(result['formal_A'],0)
        self.assertEqual(result['decision'],'NO_EDGE')

    def test_non_https_or_ambiguous_url_makes_no_network_request(self):
        for url in ('http://freetsa.org/tsr','https://user:pass@freetsa.org/tsr','https://freetsa.org/tsr#fragment'):
            with self.subTest(url=url), patch('requests.post') as post:
                with self.assertRaisesRegex(GateError,'HTTPS_TSA_URL_REQUIRED'):
                    self.submit(url=url)
                post.assert_not_called()
        self.assertFalse((self.root/'transport').exists())

    def test_http_failure_body_and_receipt_are_preserved(self):
        with patch('requests.post',return_value=self.response(403,b'blocked','text/html')):
            with self.assertRaisesRegex(GateError,'TSA_HTTP_STATUS'):
                self.submit()
        self.assertEqual((self.root/'transport/response.tsr').read_bytes(),b'blocked')
        result=json.loads((self.root/'transport/transport.json').read_text())
        self.assertEqual(result['http_status'],403)
        self.assertEqual(result['status'],'BLOCKED')

    def test_http_redirect_is_preserved_and_never_followed(self):
        with patch('requests.post',return_value=self.response(302,b'redirect','text/html')) as post:
            with self.assertRaisesRegex(GateError,'TSA_HTTP_STATUS'):
                self.submit()
        self.assertEqual(post.call_count,1)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_wrong_content_type_and_empty_body_fail_closed(self):
        for name,content,kind in [('html',b'<html>no</html>','text/html'),('empty',b'','application/timestamp-reply')]:
            with self.subTest(name=name), patch('requests.post',return_value=self.response(200,content,kind)):
                with self.assertRaisesRegex(GateError,'TSA_INVALID_RESPONSE'):
                    self.submit(name)

    def test_oversized_body_is_bounded_and_diagnostic_is_preserved(self):
        with patch('requests.post',return_value=self.response(200,b'x'*1_000_001)):
            with self.assertRaisesRegex(GateError,'TSA_RESPONSE_TOO_LARGE'):
                self.submit()
        self.assertLessEqual((self.root/'transport/response.tsr').stat().st_size,1_000_000)
        result=json.loads((self.root/'transport/transport.json').read_text())
        self.assertTrue(result['response_truncated'])

    def test_network_error_receipt_is_preserved_without_fake_response(self):
        with patch('requests.post',side_effect=requests.Timeout('fixture timeout')):
            with self.assertRaisesRegex(GateError,'TSA_NETWORK_FAILED'):
                self.submit()
        self.assertTrue((self.root/'transport/transport.json').is_file())
        self.assertFalse((self.root/'transport/response.tsr').exists())

    def test_existing_directory_cannot_recontact_service_or_overwrite(self):
        with patch('requests.post',return_value=self.response()):
            self.submit()
        original=(self.root/'transport/response.tsr').read_bytes()
        with patch('requests.post') as post:
            with self.assertRaises(FileExistsError): self.submit()
            post.assert_not_called()
        self.assertEqual((self.root/'transport/response.tsr').read_bytes(),original)

    def test_partial_response_is_preserved_when_stream_fails(self):
        response=self.response()
        def broken_stream():
            yield b'partial-DER-diagnostic'
            raise requests.ConnectionError('fixture midstream failure')
        response.iter_content.return_value=broken_stream()
        with patch('requests.post',return_value=response):
            with self.assertRaisesRegex(GateError,'TSA_NETWORK_FAILED'):
                self.submit()
        self.assertEqual((self.root/'transport/response.tsr').read_bytes(),b'partial-DER-diagnostic')
        receipt=json.loads((self.root/'transport/transport.json').read_text())
        self.assertFalse(receipt['response_capture_complete'])
        self.assertEqual(receipt['status'],'BLOCKED')
        self.assertEqual(receipt['response_bytes'],22)

    def test_empty_or_large_request_makes_no_network_call(self):
        for value in (b'',b'x'*1_000_001):
            self.query.write_bytes(value)
            with patch('requests.post') as post:
                with self.assertRaisesRegex(GateError,'INVALID_TSA_REQUEST'):
                    self.submit()
                post.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows extended path contract')
    def test_windows_long_output_path_preserves_response(self):
        from research.harness_v46.official_intake import _physical_root
        parent=self.root/('a'*90)/('b'*90)/('c'*90)
        _physical_root(parent).mkdir(parents=True)
        if not _physical_root(parent).is_relative_to(_physical_root(self.root)):
            raise AssertionError('unsafe temporary cleanup path')
        self.addCleanup(shutil.rmtree,_physical_root(parent))
        destination=parent/'attempt'
        with patch('requests.post',return_value=self.response()):
            receipt=self.module().submit_request(self.query,destination,tsa_url='https://freetsa.org/tsr')
        self.assertEqual(receipt['status'],'RESPONSE_PRESERVED_NOT_VERIFIED')
        self.assertTrue((_physical_root(destination)/'response.tsr').is_file())


if __name__=='__main__': unittest.main()
