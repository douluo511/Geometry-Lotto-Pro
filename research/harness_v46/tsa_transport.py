"""Preserve one HTTPS RFC3161 exchange; transport is never verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .core import GateError
from .official_intake import _physical_root

MAX_BYTES = 1_000_000


def submit_request(request_file, output_dir, *, tsa_url):
    """Submit only existing TSQ bytes, with TLS defaults and no redirects.

    Every attempt has a new directory. Preserve diagnostic bytes even on HTTP
    failure; a successful HTTP response has no cryptographic authority until
    separately checked against its exact data, query, nonce and pinned CA.
    """
    try:
        url = urlsplit(tsa_url)
        valid = (url.scheme == 'https' and bool(url.hostname)
                 and not url.username and not url.password and not url.fragment
                 and url.port in (None, 443))
    except (TypeError, ValueError) as exc:
        raise GateError('HTTPS_TSA_URL_REQUIRED') from exc
    if not valid:
        raise GateError('HTTPS_TSA_URL_REQUIRED')
    with _physical_root(request_file).open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise GateError('INVALID_TSA_REQUEST')
    root = _physical_root(output_dir)
    root.mkdir()  # A prior receipt or response must never be overwritten.
    (root / 'request.tsq').write_bytes(raw)
    receipt = {
        'schema': 'V47-RFC3161-TRANSPORT-1', 'tsa_url': tsa_url,
        'request_sha256': hashlib.sha256(raw).hexdigest(),
        'started_at_local_untrusted': datetime.now(timezone.utc).isoformat(),
        'http_status': None, 'response_sha256': None, 'response_bytes': 0,
        'response_truncated': False, 'status': 'BLOCKED',
        'response_capture_complete': False,
        'external_tsa': 'NOT_VERIFIED', 'source_authenticity': 'CALLER_UNVERIFIED',
        'formal_A': 0, 'decision': 'NO_EDGE',
    }
    response = None
    chunks = bytearray()
    saved = False

    def preserve_received_bytes():
        nonlocal saved
        body = bytes(chunks)
        with (root / 'response.tsr').open('xb') as handle:
            handle.write(body)
        receipt['response_sha256'] = hashlib.sha256(body).hexdigest()
        receipt['response_bytes'] = len(body)
        saved = True

    try:
        response = requests.post(
            tsa_url, data=raw, headers={
                'Content-Type':'application/timestamp-query',
                'Accept':'application/timestamp-reply',
            }, timeout=(10,30), allow_redirects=False, stream=True,
        )
        receipt['http_status'] = response.status_code
        receipt['response_content_type'] = response.headers.get('Content-Type','')
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue
            remaining = MAX_BYTES - len(chunks)
            chunks.extend(chunk[:remaining])
            if len(chunk) > remaining:
                receipt['response_truncated'] = True
                break
        body = bytes(chunks)
        preserve_received_bytes()
        receipt['response_capture_complete'] = not receipt['response_truncated']
        if receipt['response_truncated']:
            raise GateError('TSA_RESPONSE_TOO_LARGE')
        if response.status_code != 200:
            raise GateError('TSA_HTTP_STATUS:' + str(response.status_code))
        kind = receipt['response_content_type'].split(';',1)[0].strip().lower()
        if not body or kind != 'application/timestamp-reply':
            raise GateError('TSA_INVALID_RESPONSE')
        receipt['status'] = 'RESPONSE_PRESERVED_NOT_VERIFIED'
    except requests.RequestException as exc:
        receipt['error'] = type(exc).__name__ + ':' + str(exc)
        raise GateError('TSA_NETWORK_FAILED:' + type(exc).__name__) from exc
    except GateError as exc:
        receipt['error'] = str(exc)
        raise
    finally:
        if response is not None:
            if not saved:
                preserve_received_bytes()
            response.close()
        receipt['finished_at_local_untrusted'] = datetime.now(timezone.utc).isoformat()
        with (root / 'transport.json').open('x',encoding='utf-8',newline='\n') as handle:
            json.dump(receipt,handle,ensure_ascii=False,sort_keys=True,indent=2)
            handle.write('\n')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--tsa-url',required=True)
    args = parser.parse_args(argv)
    try:
        receipt = submit_request(args.request,args.output_dir,tsa_url=args.tsa_url)
        print(json.dumps(receipt,sort_keys=True,ensure_ascii=False))
        return 0
    except (GateError,OSError,ValueError,TypeError) as exc:
        parser.exit(2,'BLOCKED: '+str(exc)+'\n')


if __name__=='__main__':
    raise SystemExit(main())
