# DLT production network boundary

Status: implementation contract, not a Final or Real Network PASS.
Existing source provenance, schema/content/freshness checks, official fallback
and conflict detection remain mandatory in the Source layer.

## Root cause and fix

The former transport delegated redirects to Requests and checked the final URL
only after the request. An HTTPS-to-HTTP hop could therefore precede rejection.
It also read an unbounded body and accepted non-finite timeout values.
The missing invariant was validation before each external hop, with bounded
resource use. Source-level post-validation alone cannot establish that invariant.

The client now validates each redirect before transmission, streams bounded
bodies, closes resources before retry, and records terminal failure reasons.
Controlled negative tests also require the intended parser failure; a transport
error must not satisfy a malformed-row or duplicate-row test.

## Interfaces and defaults

| Interface / policy | Contract |
|---|---|
| NetClient.get(url, params=None, headers=None, timeout=None, allow_redirects=True) | Existing positional parameter order preserved; returns a response with cached bytes and glp_attempts |
| Constructor | Existing first eight positional arguments preserved; new resource limits are keyword-only |
| Connect / read | Independent 10 s / 30 s defaults; overrides must be a positive finite tuple |
| Attempts | Integer 1-4; default 3; no silent clamping |
| Retry | 408, 429 and 500-599, timeout, connection and chunked-transfer errors |
| Backoff | Exponential plus independent jitter; default base 0.35 s, cap 5 s |
| Retry-After | Numeric seconds or HTTP date; stop if the server requires more than the permitted delay, never retry early |
| Redirects | Manual, default 3 hops; HTTPS, same hostname, port 443, no credentials; no automatic traversal |
| Body | Default 8 MiB, streamed; maximum configuration 64 MiB; overflow raises with failure ledger |
| Operation budget | 120 s default, monotonic cooperative budget across redirects/retries/body processing |
| HTTP failure | Bounded terminal response retained, labeled FINAL_HTTP / FINAL_RETRYABLE_HTTP; Source must reject bad status/content/schema |
| Exceptions | Propagated with glp_attempts; never converted into a successful data update |

Requests inactivity timeouts are not a hard process-level deadline for DNS or
slow-drip transfers. The operation budget is cooperative; it must not be reported
as a demonstrated hard wall-clock cancellation guarantee.

## Layer responsibilities

GUI -> Service/Updater -> Source -> NetClient -> Source validation ->
canonical cross-check -> atomic Store -> Evidence -> result/GUI.
An HTTP 200 is only transport receipt, never a dataset acceptance result.
The complete official GET contract rejects every other status, including
201/202/204/206: partial or pending content cannot become canonical history.
Fallback is explicitly selected by Source, not an unapproved cross-host redirect.
Raw terminal bytes, UTC time, source/parser identity and SHA-256 are retained by
the existing Source/Evidence path. Oversized or unavailable bodies remain failures,
not complete raw-response evidence.

## Verification and invalidation

The security unit tests use controlled transports only. Contract and fault reports
explicitly label that scope. New tests cover pre-follow downgrade rejection,
host/credential/port rejection, redirect limits, body limits, resource closure,
finite retries, Retry-After, configuration validation and operation budgets.
Existing source/contract/fault regression tests must still pass.

Any change to this client invalidates the previous DLT candidate acceptance.
The new candidate must independently pass official Real Network, native Windows
build, Exact EXE, physical GUI success/failure paths, Same Hash and Final Gate.
Independent repository/release/updater and complete business approval remain
separate blocking gates; none is waived by these transport tests.
