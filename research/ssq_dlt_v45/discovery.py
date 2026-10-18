"""Bounded AnySearch discovery. Search output is NEVER an official draw/target.

Only the fixed public queries leave this client. No accounts are registered and
no credentials received in anonymous-quota responses are accepted or persisted.
The caller must independently fetch and verify original official bytes.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from .sources import URLS
from .store import canonical, parse

MCP_URL = 'https://api.anysearch.com/mcp'
REST_URL = 'https://api.anysearch.com/v1/search'
CLIENT = 'ssq-dlt-v45-discovery/1.0.0'
MAX_BYTES = 4 * 1024 * 1024
FIXED_QUERIES = (
    ('S01', '(site:cwl.gov.cn OR site:sporttery.cn) (双色球 OR 大乐透) 最新 开奖公告'),
    ('S02', '(site:cwl.gov.cn OR site:sporttery.cn) (双色球 OR 大乐透) 开奖日历 休市 期号调整'),
    ('S03', '(site:cwl.gov.cn OR site:sporttery.cn) (双色球 OR 大乐透) 更正 公告'),
    ('S04', '(site:cwl.gov.cn OR site:sporttery.cn) (双色球 OR 大乐透) 历史 开奖期号 数据'),
    ('S05', 'lottery randomness joint pair probability calibration temporal validation statistical hypothesis testing primary research'),
)
DEFAULT_HOSTS = frozenset({
    'www.cwl.gov.cn', 'cwl.gov.cn', 'www.swlc.net.cn', 'swlc.net.cn',
    'www.sporttery.cn', 'sporttery.cn', 'webapi.sporttery.cn',
    'www.lottery.gov.cn', 'lottery.gov.cn', 'api.js-lottery.com',
    'www.itl.nist.gov', 'stat.ethz.ch', 'otexts.com', 'www.statsmodels.org',
    'arxiv.org', 'doi.org', 'royalsocietypublishing.org',
})
OFFICIAL_FALLBACK_HOSTS = {
    'SSQ': frozenset({'www.cwl.gov.cn', 'cwl.gov.cn', 'www.swlc.net.cn', 'swlc.net.cn'}),
    'DLT': frozenset({'www.sporttery.cn', 'sporttery.cn', 'webapi.sporttery.cn',
                      'www.lottery.gov.cn', 'lottery.gov.cn', 'api.js-lottery.com'}),
}


class DiscoveryError(ValueError):
    """Safe machine-readable failure, never including a response body/key."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def valid_url(url, allowed_hosts):
    """Exact HTTPS host match. No credentials, ports, lookalikes or controls."""
    if not isinstance(url, str) or len(url) > 4096 or re.search(r'[\x00-\x20\x7f\\]', url):
        return False
    try:
        p = urlsplit(url)
        host = p.hostname
        return (p.scheme == 'https' and bool(host) and host in allowed_hosts
                and p.netloc == host and host.isascii() and not p.fragment)
    except (ValueError, UnicodeError):
        return False


def _exclusive(path, raw):
    with path.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_transport(url, raw, headers, timeout):
    """The only live transport. Redirects forbidden; bytes and socket bounded."""
    if url not in (MCP_URL, REST_URL):
        raise DiscoveryError('ENDPOINT_NOT_ALLOWED')
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, data=raw, headers={'User-Agent': CLIENT, **headers}, method='POST')
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        chunks, size = [], 0
        # A single large read can be kept alive indefinitely by a slow trickle.
        # read1 bounds each underlying read; deadline checked between reads.
        # DNS resolution remains subject to the operating system resolver.
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('RESPONSE_DEADLINE')
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if time.monotonic() > deadline:
                raise TimeoutError('RESPONSE_DEADLINE')
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise DiscoveryError('RESPONSE_TOO_LARGE')
        body = b''.join(chunks)
        return Response(response.status, dict(response.headers.items()), body)


def _has_secret(raw, key):
    # HTTP402 is always suppressed separately. Success/error bodies may also
    # contain the documented auto-registration text, or echo a caller key.
    text = raw.decode('utf-8', errors='replace')
    try:
        # Decode escaped JSON field names/messages before scanning. Otherwise
        # e.g. password\u003d... could evade a scan of the transport bytes.
        text += '\n' + canonical(parse(raw))
    except RecursionError:
        return True
    except (ValueError, UnicodeError):
        pass
    return (bool(key and key.encode('utf-8') in raw)
            or bool(re.search(r'(?i)\b(?:password|api[_-]?key)\s*["\x27]?\s*[:=]', text))
            or bool(re.search(r'(?i)\bbearer\s+[A-Za-z0-9_.-]{8,}', text))
            or 'as_sk_' in text or bool(key and key in text))


def _candidate_urls(value, depth=0):
    """Parse URLs only; returned instructions/snippets are never executed."""
    if depth > 24:
        raise DiscoveryError('RESULT_NESTING_BOUND')
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'url' and isinstance(child, str):
                found.append(child)
            elif key in ('text', 'content') and isinstance(child, str):
                found.extend(re.findall(r'https://[^\s<>"\x27)\]}]+', child))
                try:
                    found.extend(_candidate_urls(parse(child), depth + 1))
                except (ValueError, TypeError):
                    pass
            else:
                found.extend(_candidate_urls(child, depth + 1))
    elif isinstance(value, list):
        for child in value:
            found.extend(_candidate_urls(child, depth + 1))
    return found


def _validate_schema(value, schema, root=None, _depth=0, _budget=None):
    """Validate the supported, bounded subset of advertised tool JSON Schema.

    Unknown assertion keywords fail closed rather than claiming validation.
    Annotation keywords do not affect argument validity. Remote refs forbidden.
    """
    if _budget is None:
        _budget = [512]
    _budget[0] -= 1
    if _depth > 24 or _budget[0] < 0:
        raise DiscoveryError('SCHEMA_COMPLEXITY_BOUND')
    root = schema if root is None else root
    def child_validate(item, subschema):
        validate_schema(item, subschema, root, _depth + 1, _budget)
    if type(schema) is bool:
        if not schema:
            raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
        return
    if not isinstance(schema, dict):
        raise DiscoveryError('INVALID_TOOL_SCHEMA')
    annotations = {'description', 'title', 'default', 'examples', '$schema', '$id', '$defs', 'definitions'}
    assertions = {'$ref', 'type', 'properties', 'required', 'additionalProperties', 'items',
                  'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum',
                  'enum', 'const', 'anyOf', 'oneOf', 'allOf', 'uniqueItems'}
    if set(schema) - annotations - assertions:
        raise DiscoveryError('UNSUPPORTED_TOOL_SCHEMA')
    if '$ref' in schema:
        ref = schema['$ref']
        if not isinstance(ref, str) or not ref.startswith('#/'):
            raise DiscoveryError('REMOTE_SCHEMA_REFERENCE_FORBIDDEN')
        target = root
        try:
            for part in ref[2:].split('/'):
                target = target[part.replace('~1', '/').replace('~0', '~')]
        except (KeyError, TypeError):
            raise DiscoveryError('INVALID_SCHEMA_REFERENCE') from None
        child_validate(value, target)
    for kind in ('anyOf', 'oneOf', 'allOf'):
        if kind in schema:
            passed = 0
            for option in schema[kind]:
                try:
                    child_validate(value, option)
                    passed += 1
                except DiscoveryError:
                    pass
            if ((kind == 'anyOf' and not passed) or (kind == 'oneOf' and passed != 1)
                    or (kind == 'allOf' and passed != len(schema[kind]))):
                raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
    typ = schema.get('type')
    types = typ if isinstance(typ, list) else [typ] if typ else []
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'integer': type(value) is int,
               'number': type(value) in (int, float), 'boolean': type(value) is bool,
               'null': value is None}
    if types and not any(matches.get(t, False) for t in types):
        raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
    if 'enum' in schema and value not in schema['enum']:
        raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
    if 'const' in schema and value != schema['const']:
        raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
    if isinstance(value, dict):
        if set(schema.get('required', [])) - set(value):
            raise DiscoveryError('SCHEMA_REQUIRED_ARGUMENT_MISSING')
        properties = schema.get('properties', {})
        extra = set(value) - set(properties)
        if extra and schema.get('additionalProperties') is False:
            raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
        for key, child in value.items():
            if key in properties:
                child_validate(child, properties[key])
            elif isinstance(schema.get('additionalProperties'), dict):
                child_validate(child, schema['additionalProperties'])
    elif isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 1000000):
            raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
        if schema.get('uniqueItems') and len({canonical(v) for v in value}) != len(value):
            raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
        for child in value:
            child_validate(child, schema.get('items', {}))
    elif isinstance(value, str):
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 1000000):
            raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')
    elif type(value) in (int, float):
        if not schema.get('minimum', float('-inf')) <= value <= schema.get('maximum', float('inf')):
            raise DiscoveryError('SCHEMA_REJECTED_ARGUMENT')


def validate_schema(value, schema, root=None, _depth=0, _budget=None):
    try:
        return _validate_schema(value, schema, root, _depth, _budget)
    except DiscoveryError:
        raise
    except (TypeError, ValueError, KeyError, RecursionError):
        raise DiscoveryError('INVALID_TOOL_SCHEMA') from None


class Client:
    def __init__(self, config, directory, transport=None, sleep=time.sleep):
        self.config = config
        self.directory = directory
        self.transport = transport or http_transport
        self.sleep = sleep
        self.attempts = config.get('attempts', 2)
        self.timeout = config.get('timeout_seconds', 8)
        if type(self.attempts) is not int or not 1 <= self.attempts <= 3:
            raise DiscoveryError('INVALID_RETRY_BOUND')
        if type(self.timeout) not in (int, float) or not 0 < self.timeout <= 30:
            raise DiscoveryError('INVALID_TIMEOUT_BOUND')
        self.key = os.environ.get('ANYSEARCH_API_KEY', '')
        if '\r' in self.key or '\n' in self.key:
            raise DiscoveryError('INVALID_CREDENTIAL_HEADER')
        self.events = []
        self.rpc_id = 0
        self.session = None
        self.protocol = '2025-03-26'

    def request(self, endpoint, payload, label, notification=False):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'X-Anysearch-Client': CLIENT}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        if endpoint == MCP_URL and self.session:
            headers['Mcp-Session-Id'] = self.session
        if endpoint == MCP_URL and label != 'initialize':
            headers['MCP-Protocol-Version'] = self.protocol
        for attempt in range(1, self.attempts + 1):
            event = {'label': label, 'attempt': attempt, 'observed_at': utc_now(),
                     'request_sha256': sha(canonical(payload).encode('utf-8'))}
            self.events.append(event)
            try:
                response = self.transport(endpoint, canonical(payload).encode('utf-8'), headers, self.timeout)
                if not isinstance(response, Response) or type(response.status) is not int or not isinstance(response.body, bytes):
                    raise DiscoveryError('INVALID_TRANSPORT_RESPONSE')
                if len(response.body) > MAX_BYTES:
                    raise DiscoveryError('RESPONSE_TOO_LARGE')
                safe_headers = {}
                # Do not persist arbitrary server header values, including an
                # echoed bearer token/session. These two fields are constrained.
                for header, value in response.headers.items():
                    if header.lower() == 'content-type':
                        for known in ('application/json', 'text/event-stream', 'text/plain'):
                            if str(value).lower().split(';', 1)[0].strip() == known:
                                safe_headers['content-type'] = known
                    elif header.lower() == 'retry-after' and re.fullmatch(r'\d{1,8}(?:\.\d{1,3})?', str(value)):
                        safe_headers['retry-after'] = str(value)
                event.update(http_status=response.status, response_bytes=len(response.body),
                             response_sha256=sha(response.body))
                sensitive = response.status == 402 or _has_secret(response.body, self.key)
                event['raw_saved'] = not sensitive
                if sensitive:
                    event['raw_suppressed_reason'] = 'CREDENTIAL_OR_ANONYMOUS_QUOTA_RESPONSE'
                    # Even request IDs/header fields may be attacker controlled.
                    raise DiscoveryError('SENSITIVE_RESPONSE_SUPPRESSED')
                path = f'{len(self.events):03d}-{sha(response.body)}.bin'
                _exclusive(self.directory / path, response.body)
                event.update(raw_file=path, response_headers=safe_headers)
                if response.status == 429 or 500 <= response.status <= 599:
                    if attempt < self.attempts:
                        try:
                            delay = min(2.0, max(0.0, float(safe_headers.get('retry-after', attempt))))
                        except ValueError:
                            delay = float(attempt)
                        event['retry_delay_seconds'] = delay
                        self.sleep(delay)
                        continue
                    raise DiscoveryError('HTTP_RETRY_EXHAUSTED')
                if not 200 <= response.status <= 299:
                    raise DiscoveryError('HTTP_NON_SUCCESS')
                if notification and not response.body.strip():
                    return None
                if endpoint == MCP_URL:
                    session = next((v for k, v in response.headers.items() if k.lower() == 'mcp-session-id'), None)
                    if session:
                        if not isinstance(session, str) or len(session) > 256 or re.search(r'[^\x21-\x7e]', session):
                            raise DiscoveryError('INVALID_MCP_SESSION')
                        self.session = session
                event['status'] = 'RECEIVED'
                return response
            except (TimeoutError, urllib.error.URLError, OSError) as error:
                event['status'] = 'TRANSPORT_FAILURE'
                event['error'] = type(error).__name__
                if attempt < self.attempts:
                    event['retry_delay_seconds'] = float(attempt)
                    self.sleep(float(attempt))
                    continue
                raise DiscoveryError('TRANSPORT_RETRY_EXHAUSTED') from None
            except DiscoveryError as error:
                event['status'] = 'REJECTED'
                event['error'] = str(error)
                raise
        raise DiscoveryError('REQUEST_FAILED')

    def rpc(self, method, params=None, notification=False):
        payload = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        if not notification:
            self.rpc_id += 1
            payload['id'] = self.rpc_id
        response = self.request(MCP_URL, payload, method, notification)
        if notification:
            return None
        try:
            documents = []
            content_type = next((v.lower() for k, v in response.headers.items() if k.lower() == 'content-type'), '')
            if 'text/event-stream' in content_type:
                data = []
                # SSE messages may carry multi-line data. A terminal newline is
                # not essential once this bounded POST response has closed.
                for line in response.body.decode('utf-8').splitlines() + ['']:
                    if line.startswith('data:'):
                        data.append(line[5:].lstrip(' '))
                    elif not line and data:
                        documents.append(parse('\n'.join(data)))
                        data = []
            else:
                documents = [parse(response.body)]
            matches = [d for d in documents if isinstance(d, dict) and 'id' in d]
            if len(matches) != 1:
                raise DiscoveryError('INVALID_RPC_RESPONSE_COUNT')
            document = matches[0]
            if document.get('jsonrpc') != '2.0' or type(document.get('id')) is not int or document['id'] != payload['id']:
                raise DiscoveryError('INVALID_RPC_RESPONSE_ID')
            if 'error' in document or 'result' not in document:
                raise DiscoveryError('RPC_ERROR_OR_MISSING_RESULT')
            return document['result']
        except (UnicodeError, ValueError, TypeError, AttributeError, RecursionError) as error:
            if isinstance(error, DiscoveryError):
                raise
            raise DiscoveryError('INVALID_RPC_BODY') from None

    def mcp(self):
        hello = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                       'clientInfo': {'name': CLIENT, 'version': '1.0.0'}})
        if not isinstance(hello, dict) or hello.get('protocolVersion') not in ('2024-11-05', '2025-03-26', '2025-06-18'):
            raise DiscoveryError('UNSUPPORTED_MCP_PROTOCOL')
        self.protocol = hello['protocolVersion']
        self.rpc('notifications/initialized', notification=True)
        tools, cursor = {}, None
        for _ in range(3):
            listed = self.rpc('tools/list', {'cursor': cursor} if cursor else {})
            if not isinstance(listed, dict) or not isinstance(listed.get('tools'), list):
                raise DiscoveryError('INVALID_TOOLS_LIST')
            for tool in listed['tools']:
                if not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or not isinstance(tool.get('inputSchema'), dict):
                    raise DiscoveryError('INVALID_TOOL_DESCRIPTION')
                if tool['name'] in tools:
                    raise DiscoveryError('DUPLICATE_TOOL_NAME')
                tools[tool['name']] = tool['inputSchema']
            cursor = listed.get('nextCursor')
            if not cursor:
                break
            if not isinstance(cursor, str) or len(cursor) > 1024:
                raise DiscoveryError('INVALID_TOOLS_CURSOR')
        if cursor:
            raise DiscoveryError('TOOLS_PAGINATION_BOUND')
        if 'batch_search' not in tools:
            raise DiscoveryError('BATCH_SEARCH_NOT_ADVERTISED')
        # Fields/required arguments are checked against actual tools/list.
        arguments = {'queries': [{'query': query, 'max_results': 5} for _, query in FIXED_QUERIES]}
        validate_schema(arguments, tools['batch_search'])
        result = self.rpc('tools/call', {'name': 'batch_search', 'arguments': arguments})
        if not isinstance(result, dict) or result.get('isError') is True:
            raise DiscoveryError('MCP_TOOL_ERROR')
        return [{'query_ids': [], 'batch_query_ids': [qid for qid, _ in FIXED_QUERIES],
                 'query_attribution': 'BATCH_UNRESOLVED', 'data': result}], sorted(tools)

    def rest(self):
        results = []
        errors = []
        # The public REST endpoint is single search. There is no invented REST batch.
        for qid, query in FIXED_QUERIES:
            try:
                response = self.request(REST_URL, {'query': query, 'max_results': 5,
                                                 'zone': 'cn', 'language': 'zh-CN', 'format': 'json'}, qid)
                try:
                    document = parse(response.body)
                except (ValueError, UnicodeError):
                    raise DiscoveryError('INVALID_REST_BODY') from None
                if not isinstance(document, dict) or type(document.get('code')) is not int or document['code'] != 0:
                    raise DiscoveryError('REST_BUSINESS_ERROR')
                if not isinstance(document.get('data'), dict) or not isinstance(document['data'].get('results'), list):
                    raise DiscoveryError('INVALID_REST_RESULTS')
                if any(not isinstance(item, dict) or not isinstance(item.get('url'), str)
                       for item in document['data']['results']):
                    raise DiscoveryError('INVALID_REST_RESULT_ITEM')
                results.append({'query_ids': [qid], 'query_attribution': 'EXACT_REQUEST',
                                'data': document['data']['results']})
            except DiscoveryError as error:
                errors.append({'query_id': qid, 'error': str(error)})
        return results, errors


def run_discovery(config, output, transport=None, sleep=time.sleep):
    """Probe MCP or REST and save a fresh append-only run with integrity receipt.

    ``SUCCESS`` certifies only this discovery exchange, never official accuracy.
    ``DEGRADED`` includes configured official URLs for independent fallback.
    Invalid local config raises instead of silently changing public queries.
    """
    if not isinstance(config, dict) or set(config) - {'transport', 'attempts', 'timeout_seconds', 'allowed_hosts', 'fallback_urls'}:
        raise DiscoveryError('UNKNOWN_DISCOVERY_CONFIG')
    if config.get('transport', 'rest') not in ('rest', 'mcp'):
        raise DiscoveryError('INVALID_TRANSPORT')
    output = Path(output)
    if not output.is_absolute():
        raise DiscoveryError('ABSOLUTE_OUTPUT_REQUIRED')
    allowed = config.get('allowed_hosts', sorted(DEFAULT_HOSTS))
    if not isinstance(allowed, list) or not allowed or any(type(v) is not str or v not in DEFAULT_HOSTS for v in allowed):
        raise DiscoveryError('INVALID_ALLOWED_HOSTS')
    fallback = config.get('fallback_urls', {game: list(urls) for game, urls in URLS.items()})
    if not isinstance(fallback, dict) or set(fallback) != {'SSQ', 'DLT'}:
        raise DiscoveryError('INVALID_FALLBACK_URLS')
    if any(not isinstance(v, list) or not v or any(not valid_url(u, OFFICIAL_FALLBACK_HOSTS[game]) for u in v)
           for game, v in fallback.items()):
        raise DiscoveryError('INVALID_FALLBACK_URLS')
    output.mkdir(parents=True, exist_ok=True)
    directory = output / ('discovery-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex)
    directory.mkdir(exist_ok=False)
    client = Client(config, directory, transport, sleep)
    receipt = {'version': '1.0.0', 'transport': config.get('transport', 'rest'), 'started_at': utc_now(),
               'status': 'DEGRADED', 'scope': 'DISCOVERY_ONLY_UNTRUSTED_URLS',
               'queries': [{'id': qid, 'query': query} for qid, query in FIXED_QUERIES],
               'official_fallback_urls': fallback, 'official_original_verification': 'NOT_PERFORMED',
               'legal_target': None, 'candidate_numbers': None, 'formal_A': 0, 'edge': 'NO_EDGE',
               'credentials_persisted': False, 'external_timestamp': 'NOT_PROVIDED',
               'network_bounds': {'attempts': client.attempts, 'timeout_seconds': client.timeout,
                                  'max_response_bytes': MAX_BYTES},
               'authentication': 'ENVIRONMENT_KEY' if client.key else 'ANONYMOUS',
               'candidates': [], 'errors': [], 'events': client.events}
    documents = []
    try:
        if receipt['transport'] == 'mcp':
            documents, names = client.mcp()
            receipt['advertised_tools'] = names
        else:
            documents, receipt['errors'] = client.rest()
        seen = {}
        rejected = 0
        for document in documents:
            for url in _candidate_urls(document['data']):
                if not valid_url(url, allowed):
                    rejected += 1
                    continue
                if url not in seen:
                    candidate = {'url': url, 'query_ids': list(document['query_ids']),
                                 'query_attribution': document['query_attribution'],
                                 'official_verified': False}
                    if 'batch_query_ids' in document:
                        candidate['batch_query_ids'] = list(document['batch_query_ids'])
                    receipt['candidates'].append(candidate)
                    seen[url] = candidate
                else:
                    # A repeated REST URL retains every exact request that
                    # returned it, without claiming unobserved provenance.
                    for qid in document['query_ids']:
                        if qid not in seen[url]['query_ids']:
                            seen[url]['query_ids'].append(qid)
        receipt['rejected_url_count'] = rejected
        if not receipt['candidates'] and not receipt['errors']:
            receipt['errors'].append({'error': 'NO_ALLOWED_CANDIDATE_URLS'})
        if not receipt['errors']:
            receipt['status'] = 'SUCCESS'
    except DiscoveryError as error:
        receipt['errors'].append({'error': str(error)})
    receipt['completed_at'] = utc_now()
    raw = (canonical(receipt) + '\n').encode('utf-8')
    _exclusive(directory / 'receipt.json', raw)
    _exclusive(directory / 'receipt.sha256', (sha(raw) + '\n').encode('ascii'))
    return dict(receipt, receipt_path=str(directory / 'receipt.json'), receipt_sha256=sha(raw))


def verify_discovery(output):
    """Detect file drift. This local hash receipt is not trusted time custody."""
    directory = Path(output)
    if not directory.is_absolute():
        raise DiscoveryError('ABSOLUTE_OUTPUT_REQUIRED')
    directory = directory.resolve()
    raw = (directory / 'receipt.json').read_bytes()
    if sha(raw) != (directory / 'receipt.sha256').read_text('ascii').strip():
        raise DiscoveryError('RECEIPT_SHA_MISMATCH')
    receipt = parse(raw)
    for event in receipt['events']:
        if event.get('raw_saved'):
            path = directory / event['raw_file']
            if not path.resolve().is_relative_to(directory) or not path.is_file():
                raise DiscoveryError('RAW_PATH_ESCAPE')
            body = path.read_bytes()
            if sha(body) != event['response_sha256'] or len(body) != event['response_bytes']:
                raise DiscoveryError('RAW_SHA_MISMATCH')
    return {'status': 'PASS', 'scope': 'LOCAL_FILE_INTEGRITY_ONLY',
            'events': len(receipt['events']), 'receipt_sha256': sha(raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    probe = sub.add_parser('probe')
    probe.add_argument('--transport', choices=['mcp', 'rest'])
    probe.add_argument('--config')
    probe.add_argument('--output', required=True)
    check = sub.add_parser('verify')
    check.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if args.command == 'verify':
        result = verify_discovery(args.output)
    else:
        config = {}
        if args.config:
            path = Path(args.config)
            if not path.is_absolute():
                raise DiscoveryError('ABSOLUTE_CONFIG_REQUIRED')
            config = parse(path.read_bytes())
        if args.transport:
            config['transport'] = args.transport
        result = run_discovery(config, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('SUCCESS', 'PASS') else 2


if __name__ == '__main__':
    raise SystemExit(main())
