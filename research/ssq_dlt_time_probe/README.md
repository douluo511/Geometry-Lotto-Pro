# Offline RFC3161 technical probe

This isolated verifier checks a retained **synthetic test token**, not a lottery
prediction. It performs **zero network calls**. Inputs are read-only; outputs
require a new exclusive folder. No ledger, prediction engine or official issue
gate is opened. A=0, NO_EDGE, qualified prospective samples=0.

It checks SHA256 message imprints, the original nonce, granted status, signed
genTime, the provider's advertised raw PEM checksums, the actual CMS signer,
signature, critical timestamping purpose and a pinned certificate chain at
genTime. The SHA256 printed by FreeTSA matches the downloaded **raw PEM files**,
not their DER certificate fingerprints. The root is an explicit candidate trust
anchor, not a formally approved production provider.

OpenSSL `ts` does not support the `-no-CApath` and `-no-CAstore` switches accepted
by some other subcommands. Its trust paths are explicitly overridden with empty
local stores. A separate CMS verification binds the actual signer to the pinned
leaf, and `verify -trusted` checks the pinned root chain. Negative checks run only
after every positive check succeeds; nonzero exits caused by bad flags, missing
files or timeouts cannot count as rejection success.

Controlled negatives alter the payload, query nonce, signature and trust anchor.
A separate strict deadline predicate uses signed genTime plus declared accuracy;
unknown accuracy fails closed. The synthetic deadline is not an official lottery
deadline. FreeTSA's live test token declares **unspecified accuracy**. Revocation
checking is **NOT_RUN**, long-term validation is **NOT_ESTABLISHED**. A technical
PASS establishes none of: historical input availability, legal target identity,
01–04 approvals, formal freeze eligibility or prediction performance.

Example, from repository root (OpenSSL 3.5.7 and Python 3.11.9 were tested):

    python -m research.ssq_dlt_time_probe --input-dir NEW_CAPTURE_DIR --output NEW_EXCLUSIVE_OUTPUT_DIR --openssl OPENSSL_EXECUTABLE

The input folder contains payload.txt, request.tsq, response.tsr, cacert.pem and
tsa.crt. The CLI only verifies those bytes. The captured live token remains in
the separate evidence delivery; local synthetic tests generate a distinct test
CA and TSA in temporary storage. Such self-signed test fixtures are labelled
synthetic and are never described as third-party timestamps.

Primary sources:
[FreeTSA endpoint and certificate checksums](https://www.freetsa.org/index_en.php),
[service policy](https://www.freetsa.org/freetsa.html),
[OpenSSL ts documentation](https://docs.openssl.org/3.5/man1/openssl-ts/),
[RFC3161](https://www.rfc-editor.org/rfc/rfc3161.html).
