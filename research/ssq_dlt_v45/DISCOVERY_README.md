# V4.5 AnySearch discovery adapter

This adapter discovers candidate URLs. It never admits official data, chooses
numbers, changes the primary D2, infers a legal issue/deadline, or grants A status.
Search snippets and extracted text are untrusted data. An independent official
fetcher must download the original bytes and perform game, issue, chronology,
source agreement, publication and deadline checks.

## Documented protocol

The implementation was checked against these first-party public pages on
2026-10-18. Documentation is not a certificate that a live probe succeeded.

- [AnySearch MCP server](https://github.com/anysearch-ai/anysearch-mcp-server)
- [REST POST /v1/search](https://www.anysearch.com/docs/api-endpoints/v1-search)
- [Authentication](https://anysearch.com/docs/auth)
- [MCP installation](https://anysearch.com/docs/mcp-install)

MCP endpoint: `https://api.anysearch.com/mcp`. The adapter sends `initialize`,
`notifications/initialized`, and bounded paginated `tools/list`. It validates
the fixed five query arguments against the server's actual `batch_search`
input schema before calling it. Unknown required arguments, unsupported schema
assertions and malformed/cyclic schemas fail closed. JSON and finite SSE POST
responses are supported. JSON-RPC IDs and error envelopes are checked. Session
IDs remain in memory. Server-advertised tool names are recorded; this component
does not call `extract` because extraction cannot replace official-original
verification.

REST endpoint: `https://api.anysearch.com/v1/search`. REST performs five separate
search requests. No REST batch route is invented. Requests use the documented
`query`, `max_results=5`, `zone=cn`, `language=zh-CN` and `format=json` fields.
No vertical domain or structured routing parameters are guessed.

Five fixed public queries cover S01 official latest results, S02 official
calendar/closures/issue adjustments, S03 corrections, S04 historical-data
completeness, and S05 primary statistical research. User text, local records,
recipient addresses and credentials never enter these queries. Returned URLs
must match a reviewed host exactly over HTTPS; suffix lookalikes, credentials,
ports, fragments, IPs, backslashes and controls are rejected. The host allowlist
can be narrowed through configuration, not widened by search output. A listed
host is only eligible for further review, not a statement of source authenticity.

## Local interface

From the repository root:

```text
python -m research.ssq_dlt_v45.discovery probe --transport rest --output C:\GLP\V45\discovery
python -m research.ssq_dlt_v45.discovery probe --transport mcp --output C:\GLP\V45\discovery
python -m research.ssq_dlt_v45.discovery verify --output C:\GLP\V45\discovery\d-<uuid32>
```

The optional `--config` path must be absolute. Allowed fields are:

```json
{
  "transport": "rest",
  "attempts": 2,
  "timeout_seconds": 8
}
```

The Python interface is `run_discovery(config, absolute_output_path,
transport=None, sleep=time.sleep)`. Test transports return
`Response(status, headers, body_bytes)`. The result includes `receipt_path` and
`receipt_sha256`; these two convenience fields are not part of the saved receipt.
`verify_discovery(absolute_run_directory)` verifies the receipt and all retained
raw-response file sizes and SHA-256 values.

Every probe creates a new exclusive `d-<uuid32>` run directory. Ordinary responses
are stored as short exclusive counter files such as `001.bin`, with full
SHA-256 and byte counts in the receipt. Windows filesystem IO uses extended
absolute paths, including verification, so a deep workspace does not depend on
the legacy 260-character limit. Receipts, SHA sidecars and
raw files are never overwritten by the adapter. A privileged file owner can alter
local files; SHA verification detects drift but is not an external TSA or
independent custody.

## Credentials and failures

`ANYSEARCH_API_KEY` is optional and read only from the environment. It is sent in
memory through `Authorization: Bearer ...`; the fixed `X-Anysearch-Client` header
is sent for anonymous and authenticated requests. The adapter does not register
accounts, use a report recipient for registration, or install MCP configuration.

The official REST documentation warns that anonymous HTTP 402 responses can
contain generated passwords/API keys. Therefore **all HTTP 402 bodies and any
other detected credential-bearing bodies are suppressed**, retaining only body
length/SHA and a suppression reason. They are never saved as raw evidence,
printed, accepted, or reused. Escaped JSON credential text and known-key echoes
are screened too. Only constrained content-type and numeric retry-after response
headers are retained; arbitrary headers and MCP session IDs are not persisted.
This safety exception is explicit: a suppressed body is not an archived original.

Retries are bounded to 1–3 attempts per request. Socket timeouts and monotonic
read deadlines are bounded to at most 30 seconds each; response sizes are bounded
to 4 MiB. `read1` plus deadline checks prevent an indefinitely successful slow
trickle. DNS timing still depends on the operating system resolver. HTTP 429 and
5xx responses retry with capped delay; authentication and other client errors
are not blindly retried. HTTP redirects are rejected. Transport, protocol, schema,
business errors and absence of allowed URLs return `DEGRADED`, with fixed/reviewed
official fallback URLs for independent fetching. Partial REST successes retain
their candidate URLs and failure receipts.

A raw-response storage error is `LOCAL_EVIDENCE_WRITE_FAILED`, with
`raw_saved=false`. A successfully completed HTTP request is never repeated
because of that local IO failure; later independent REST queries may continue.

`SUCCESS` means the discovery exchange produced eligible candidate URLs; it does
not mean all candidate content is correct, that each S01–S05 goal was answered,
or that MCP batch item success was independently authenticated. MCP batch results
are attributed to the fixed batch collectively, without inventing per-query
provenance. MCP candidates carry `query_ids=[]`,
`batch_query_ids=["S01","S02","S03","S04","S05"]` and
`query_attribution=BATCH_UNRESOLVED`; untrusted textual group headings are not
used as attribution. REST candidates carry `query_attribution=EXACT_REQUEST`
and merge only the IDs of individual requests that actually returned that URL.
`official_original_verification=NOT_PERFORMED`, `legal_target=null`,
`candidate_numbers=null`, `formal_A=0`, and `edge=NO_EDGE` remain explicit.

## Offline acceptance

```text
python -m unittest research.ssq_dlt_v45.tests.test_discovery -v
```

The tests exercise real adapter paths with deterministic transports: both
protocols, actual advertised-schema handling, over-five rejection, wrong RPC IDs,
RPC/tool/business errors, rate limits, 5xx/timeout retry bounds, slow-trickle
deadline, malicious URLs and prompt text, anonymous quota credential suppression,
escaped credentials and header echoes, raw/receipt tampering and append-only
reruns. They do not establish a live connection; live receipts are reported
separately by the caller.
