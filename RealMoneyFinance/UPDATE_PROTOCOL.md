# Independent updater contract — candidate, not accepted production release

This explicitly reauthored product has no accepted independent production repository or real Release N → N+1 pair. Updater contract/fault fixtures do not satisfy those gates.

The trusted local `userdata/updater.json` requires `enabled: true`, an actual independent `owner/repository`, a repository-owned HTTPS `manifest_url`, and a separately provisioned 32-byte Ed25519 `trusted_public_key_hex`. No key or production endpoint is invented by this implementation. The shared Geometry-Lotto-Pro repository is rejected as production context.

Each formal Release publishes `RealMoneyFinance.exe` and `release-manifest.json`. The manifest has `schema_version: 1`, `product: RealMoneyFinance`, the exact repository, strict three-component SemVer `version`, matching `release_id: v<version>`, the exact 40-character `source_sha`, and `artifact` with the fixed executable name, real GitHub Release download URL, exact byte size and SHA-256. `signature` is base64 Ed25519 over the UTF-8 JSON without `signature`, with sorted keys and compact separators.

Before an update, both the current N and proposed N+1 must have non-draft, non-prerelease GitHub Releases. Their release tags must resolve to their signed source commits. The current installed binary hash/size/source/version must match the signed N manifest. The N+1 downloaded bytes must match the signed size/hash and begin with the Windows PE marker.

The main application checks production context before exiting and passes its own absolute executable path, version, source SHA and process ID to the independent updater. The updater waits for the parent to exit before recovery or replacement, takes an installation lock, retains a hash-checked backup, journals the transaction, replaces atomically, runs the new binary self-test with a fresh nonce and checks product/version/source/binary hash/storage integrity, then relaunches. A failed new health check or launch restores, health-checks and relaunches the previous version and quarantines the failed release. Interrupted replacement remains recoverable from the journal. Failed rollback retains its journal and cannot count as PASS.

The updater limits HTTPS retries, metadata/artifact sizes and redirects and rejects HTTP downgrade before issuing a redirected request. Only trusted GitHub delivery origins are admitted. No credentials are embedded.

Acceptance status stays `BLOCKED` for real production N → N+1, `BLOCKED` for repository independence and `FAIL` for Final Gate until actual production evidence exists. Cost, slippage, liquidity, corporate-action, survivorship, leakage-safe time splits and full statistical qualification remain unverified product work. Capital deployment stays disabled.
