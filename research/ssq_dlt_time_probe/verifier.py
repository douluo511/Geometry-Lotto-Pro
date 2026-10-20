"""Verify retained RFC3161 bytes with an independent OpenSSL executable.

All inputs are read-only; all outputs go to a newly created exclusive directory.
This module contains no network operations. Its PASS is a synthetic technical
result, not production trust approval, long-term validation, or historical proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHA256_OID = "2.16.840.1.101.3.4.2.1"
SIGNED_DATA_OID = "1.2.840.113549.1.7.2"
TST_INFO_OID = "1.2.840.113549.1.9.16.1.4"
FREETSA_ROOT_RAW_SHA256 = "2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438"
FREETSA_SIGNER_RAW_SHA256 = "8bfb0305bb64e2571ca507552ef3245cb1c2fee8728e0ff8689225081ea13467"
MAX_INPUT_BYTES = 262144


class VerificationError(ValueError):
    """A required verification predicate was not established."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_utc() -> str:
    """Operational metadata only; never a source of trusted time."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Node:
    data: bytes
    start: int
    content_start: int
    end: int
    tag: int

    @property
    def value(self) -> bytes:
        return self.data[self.content_start:self.end]

    @property
    def raw(self) -> bytes:
        return self.data[self.start:self.end]

    def children(self) -> list[Node]:
        items, offset = [], self.content_start
        while offset < self.end:
            item = read_node(self.data, offset, self.end)
            items.append(item)
            offset = item.end
        return items


def read_node(data: bytes, offset: int = 0, limit: int | None = None) -> Node:
    limit = len(data) if limit is None else limit
    start = offset
    if offset + 2 > limit:
        raise VerificationError("Truncated DER")
    tag = data[offset]
    offset += 1
    if tag & 31 == 31:
        raise VerificationError("Unsupported high-tag DER")
    size = data[offset]
    offset += 1
    if size & 128:
        count = size & 127
        if count == 0 or count > 4 or offset + count > limit or data[offset] == 0:
            raise VerificationError("Noncanonical DER length")
        size = int.from_bytes(data[offset:offset + count], "big")
        offset += count
        if size < 128:
            raise VerificationError("Nonminimal DER length")
    if offset + size > limit:
        raise VerificationError("DER length exceeds input")
    return Node(data, start, offset, offset + size, tag)


def one(data: bytes, tag: int = 48) -> Node:
    result = read_node(data)
    if result.tag != tag or result.end != len(data):
        raise VerificationError("Unexpected DER type or trailing bytes")
    return result


def integer(node: Node) -> int:
    value = node.value
    if node.tag != 2 or not value or value[0] & 128:
        raise VerificationError("Expected nonnegative DER integer")
    if len(value) > 1 and value[0] == 0 and not value[1] & 128:
        raise VerificationError("Nonminimal DER integer")
    return int.from_bytes(value, "big")


def oid(node: Node) -> str:
    if node.tag != 6 or not node.value:
        raise VerificationError("Expected DER OID")
    groups, value, first = [], 0, True
    for byte in node.value:
        if first and byte == 128:
            raise VerificationError("Nonminimal OID")
        value = (value << 7) | (byte & 127)
        if not byte & 128:
            groups.append(value)
            value, first = 0, True
        else:
            first = False
    if not first or not groups:
        raise VerificationError("Truncated OID")
    prefix = 0 if groups[0] < 40 else 1 if groups[0] < 80 else 2
    return ".".join(map(str, [prefix, groups[0] - 40 * prefix, *groups[1:]]))


def imprint(node: Node) -> tuple[str, bytes]:
    if node.tag != 48:
        raise VerificationError("Expected messageImprint sequence")
    fields = node.children()
    if len(fields) != 2 or fields[0].tag != 48 or fields[1].tag != 4:
        raise VerificationError("Invalid messageImprint")
    algorithm = fields[0].children()
    if not algorithm or len(algorithm) > 2 or (len(algorithm) == 2 and algorithm[1].raw != b"\x05\x00"):
        raise VerificationError("Unsupported algorithm parameters")
    name, digest = oid(algorithm[0]), fields[1].value
    if name != SHA256_OID or len(digest) != 32:
        raise VerificationError("Only 32-byte SHA256 imprints are accepted")
    return name, digest


def parse_query(data: bytes) -> dict:
    fields = one(data).children()
    if len(fields) < 3 or integer(fields[0]) != 1:
        raise VerificationError("Unsupported TSQ version")
    algorithm, digest = imprint(fields[1])
    nonce_nodes = [field for field in fields[2:] if field.tag == 2]
    cert_nodes = [field for field in fields[2:] if field.tag == 1]
    if len(nonce_nodes) != 1 or len(cert_nodes) != 1 or cert_nodes[0].value != b"\xff":
        raise VerificationError("TSQ must request certificate and contain one nonce")
    if any(field.tag not in (1, 2, 6) for field in fields[2:]):
        raise VerificationError("Unsupported TSQ extension")
    return dict(algorithm=algorithm, digest=digest, nonce=integer(nonce_nodes[0]), nonce_node=nonce_nodes[0])


def parse_generalized_time(value: bytes) -> datetime:
    text = value.decode("ascii")
    match = re.fullmatch(r"(\d{14})(?:\.(\d{1,6}))?Z", text)
    if not match:
        raise VerificationError("Unsupported signed UTC genTime")
    result = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return result.replace(microsecond=int((match.group(2) or "0").ljust(6, "0")))


def parse_response(data: bytes) -> dict:
    fields = one(data).children()
    if len(fields) != 2 or fields[0].tag != 48 or integer(fields[0].children()[0]) != 0:
        raise VerificationError("Timestamp response must be granted without modifications")
    token = fields[1]
    content = token.children()
    if token.tag != 48 or len(content) != 2 or oid(content[0]) != SIGNED_DATA_OID or content[1].tag != 160:
        raise VerificationError("Expected CMS SignedData token")
    wrapped = content[1].children()
    if len(wrapped) != 1 or wrapped[0].tag != 48:
        raise VerificationError("Invalid SignedData wrapper")
    signed = wrapped[0].children()
    if len(signed) < 4 or signed[2].tag != 48 or signed[-1].tag != 49:
        raise VerificationError("Invalid SignedData structure")
    encapsulated = signed[2].children()
    if len(encapsulated) != 2 or oid(encapsulated[0]) != TST_INFO_OID or encapsulated[1].tag != 160:
        raise VerificationError("Expected encapsulated TSTInfo")
    octets = encapsulated[1].children()
    if len(octets) != 1 or octets[0].tag != 4:
        raise VerificationError("Expected TSTInfo octets")
    info = one(octets[0].value).children()
    if len(info) < 6 or integer(info[0]) != 1 or info[4].tag != 24:
        raise VerificationError("Unsupported TSTInfo")
    algorithm, digest = imprint(info[2])
    nonce_nodes = [field for field in info[5:] if field.tag == 2]
    if len(nonce_nodes) != 1:
        raise VerificationError("TSTInfo must contain exactly one nonce")
    accuracies = [field for field in info[5:] if field.tag == 48]
    if len(accuracies) > 1:
        raise VerificationError("Duplicate TSTInfo accuracy")
    accuracy = None
    if accuracies:
        accuracy = 0.0
        seen = set()
        for part in accuracies[0].children():
            if part.tag not in (2, 128, 129) or part.tag in seen or not part.value or part.value[0] & 128:
                raise VerificationError("Invalid TSTInfo accuracy")
            seen.add(part.tag)
            number = int.from_bytes(part.value, "big")
            if part.tag != 2 and not 1 <= number <= 999:
                raise VerificationError("Invalid subsecond accuracy")
            accuracy += number / {2: 1, 128: 1000, 129: 1000000}[part.tag]
    signers = signed[-1].children()
    if len(signers) != 1 or signers[0].tag != 48:
        raise VerificationError("Exactly one timestamp signer is required")
    signer_fields = signers[0].children()
    index = 4 if len(signer_fields) > 3 and signer_fields[3].tag == 160 else 3
    if len(signer_fields) <= index + 1 or signer_fields[index].tag != 48 or signer_fields[index + 1].tag != 4:
        raise VerificationError("Timestamp signature not found")
    signature = signer_fields[index + 1]
    if not signature.value:
        raise VerificationError("Empty timestamp signature")
    return dict(token=token.raw, tst_info=octets[0].value, algorithm=algorithm, digest=digest,
                nonce=integer(nonce_nodes[0]), gen_time=parse_generalized_time(info[4].value),
                policy_oid=oid(info[1]), serial=integer(info[3]), accuracy_seconds=accuracy,
                signature_offset=signature.end - 1)


def deadline_allows(gen_time: datetime, deadline: datetime, accuracy_seconds: float | None) -> bool:
    """Strict upper time bound; unspecified accuracy cannot establish eligibility."""
    if gen_time.tzinfo is None or deadline.tzinfo is None:
        raise VerificationError("Deadline comparison requires timezone-aware times")
    if accuracy_seconds is None:
        return False
    if not math.isfinite(accuracy_seconds) or accuracy_seconds < 0:
        raise VerificationError("Nonfinite or negative accuracy")
    return gen_time + timedelta(seconds=accuracy_seconds) < deadline


@dataclass(frozen=True)
class Inputs:
    payload: Path
    query: Path
    response: Path
    root: Path
    signer: Path
    root_raw_sha256: str = FREETSA_ROOT_RAW_SHA256
    signer_raw_sha256: str = FREETSA_SIGNER_RAW_SHA256


class Recorder:
    def __init__(self, out: Path, openssl: Path):
        self.out, self.openssl, self.count = out, openssl, 0
        self.checks = []

    def json(self, name: str, value: dict) -> None:
        with (self.out / name).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")

    def check(self, name: str, passed: bool, **details) -> None:
        self.checks.append(dict(name=name, status="PASS" if passed else "FAIL", **details))
        if not passed:
            raise VerificationError(name)

    def command(self, label: str, *args: str, required: bool = True) -> tuple[int | None, str]:
        self.count += 1
        stem = f"{self.count:02d}-{label}"
        argv = [str(self.openssl), *map(str, args)]
        started = local_utc()
        env = os.environ.copy()
        root_file = "root.pem"
        for flag in ("-CAfile", "-trusted"):
            if flag in args:
                root_file = str(args[args.index(flag) + 1])
        env.update(OPENSSL_CONF=str(self.out / "openssl-minimal.cnf"),
                   SSL_CERT_FILE=str(self.out / root_file), SSL_CERT_DIR=str(self.out / "empty-trust"))
        try:
            result = subprocess.run(argv, cwd=self.out, capture_output=True, timeout=25, env=env)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as error:
            code, stdout, stderr = None, error.stdout or b"", error.stderr or b""
        except OSError as error:
            code, stdout, stderr = None, b"", str(error).encode("utf-8")
        (self.out / (stem + ".stdout")).write_bytes(stdout)
        (self.out / (stem + ".stderr")).write_bytes(stderr)
        self.json(stem + ".command.json", dict(argv=argv, started_at_local=started,
                  finished_at_local=local_utc(), exit_code=code, stdout_sha256=sha256(stdout),
                  stderr_sha256=sha256(stderr)))
        text = (stdout + b"\n" + stderr).decode("utf-8", "replace")
        if required and code != 0:
            raise VerificationError(f"{label}: command failed ({code}); inspect retained logs")
        return code, text

    def rejected(self, name: str, code: int | None, text: str, expected: str) -> None:
        infrastructure_error = re.search(r"unknown option|multiple digest|use -help|invalid command|no such file|can't open", text, re.I)
        self.check(name, code not in (None, 0) and not infrastructure_error and re.search(expected, text, re.I) is not None,
                   expected_error_pattern=expected, exit_code=code)


def verify_offline(inputs: Inputs, output: Path, openssl: Path) -> dict:
    """Verify all positives, then controlled negatives; never overwrite source files.

    Raises only for unsafe/existing output setup; verification failures are retained
    in RECEIPT.json and returned as FAIL. Existing directories are never reused.
    """
    output, openssl = output.resolve(), openssl.resolve()
    paths = {name: Path(getattr(inputs, name)).resolve() for name in ("payload", "query", "response", "root", "signer")}
    if output.exists():
        raise FileExistsError("Output directory must be new and exclusive")
    if any(path == output or output in path.parents for path in paths.values()):
        raise VerificationError("Output must not contain source inputs")
    raw = {}
    for name, path in paths.items():
        if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise VerificationError(f"Missing or oversized input: {name}")
        raw[name] = path.read_bytes()
    if len(set(paths.values())) != len(paths):
        raise VerificationError("Source inputs must have distinct paths")
    output.mkdir(parents=True, exist_ok=False)
    (output / "openssl-minimal.cnf").write_text("# Controlled offline configuration; no external sections.\n", encoding="ascii")
    recorder = Recorder(output, openssl)
    original_hashes = {name: sha256(data) for name, data in raw.items()}
    result, error = {}, None
    try:
        recorder.json("INPUTS.json", dict(files={name: dict(path=str(path), bytes=len(raw[name]), sha256=original_hashes[name]) for name, path in paths.items()},
                      expected_root_raw_sha256=inputs.root_raw_sha256, expected_signer_raw_sha256=inputs.signer_raw_sha256))
        recorder.command("openssl-version", "version", "-a")
        recorder.check("root-raw-pin", original_hashes["root"] == inputs.root_raw_sha256)
        recorder.check("signer-raw-pin", original_hashes["signer"] == inputs.signer_raw_sha256)
        for name, data in raw.items():
            (output / {"payload": "payload.bin", "query": "request.tsq", "response": "response.tsr", "root": "root.pem", "signer": "signer.pem"}[name]).write_bytes(data)
        query, reply = parse_query(raw["query"]), parse_response(raw["response"])
        expected_digest = hashlib.sha256(raw["payload"]).digest()
        recorder.check("independent-sha256-imprint", query["digest"] == reply["digest"] == expected_digest,
                       algorithm_oid=SHA256_OID, sha256=expected_digest.hex())
        recorder.check("independent-nonce-match", query["nonce"] == reply["nonce"], nonce_hex=hex(query["nonce"]))
        epoch = int(reply["gen_time"].timestamp())
        (output / "empty-trust").mkdir()
        # ts lacks -no-CApath/-no-CAstore. Override both with a new empty store.
        ts_trust = ["-CAfile", "root.pem", "-untrusted", "signer.pem", "-CApath", str(output / "empty-trust"),
                    "-CAstore", str(output / "empty-trust"), "-attime", str(epoch)]
        recorder.command("verify-request", "ts", "-verify", "-in", "response.tsr", "-queryfile", "request.tsq", *ts_trust)
        recorder.check("openssl-query-signature-chain-nonce", True)
        recorder.command("verify-payload", "ts", "-verify", "-in", "response.tsr", "-data", "payload.bin", *ts_trust)
        recorder.check("openssl-source-data-binding", True)
        (output / "token.der").write_bytes(reply["token"])
        recorder.command("verify-cms-actual-signer", "cms", "-verify", "-inform", "DER", "-in", "token.der", "-binary",
                         "-CAfile", "root.pem", "-no-CApath", "-no-CAstore", "-purpose", "timestampsign", "-attime", str(epoch),
                         "-signer", "actual-signer.pem", "-out", "verified-tstinfo.der")
        recorder.check("cms-verified-tstinfo-match", (output / "verified-tstinfo.der").read_bytes() == reply["tst_info"])
        actual = (output / "actual-signer.pem").read_bytes()
        recorder.check("exactly-one-actual-signer", actual.count(b"-----BEGIN CERTIFICATE-----") == 1)
        for name in ("actual-signer", "signer"):
            recorder.command("der-" + name, "x509", "-in", name + ".pem", "-outform", "DER", "-out", name + ".der")
        recorder.check("actual-signer-matches-pinned-leaf", (output / "actual-signer.der").read_bytes() == (output / "signer.der").read_bytes())
        recorder.command("verify-pinned-chain-purpose", "verify", "-trusted", "root.pem", "-purpose", "timestampsign", "-attime", str(epoch), "-show_chain", "actual-signer.pem")
        recorder.check("pinned-chain-critical-timestamp-eku-at-gentime", True)
        recorder.command("inspect-actual-signer", "x509", "-in", "actual-signer.pem", "-noout", "-text", "-fingerprint", "-sha256")
        recorder.command("inspect-signed-time", "ts", "-reply", "-in", "response.tsr", "-text")
        recorder.check("all-positive-checks-before-negatives", True)

        (output / "tampered-payload.bin").write_bytes(raw["payload"] + b"\nSYNTHETIC_TAMPER\n")
        code, text = recorder.command("negative-payload", "ts", "-verify", "-in", "response.tsr", "-data", "tampered-payload.bin", *ts_trust, required=False)
        recorder.rejected("tampered-payload-rejected", code, text, r"message imprint mismatch")
        changed_query = bytearray(raw["query"])
        changed_query[query["nonce_node"].end - 1] ^= 1
        recorder.check("negative-nonce-is-different", parse_query(bytes(changed_query))["nonce"] != query["nonce"])
        (output / "different-nonce.tsq").write_bytes(changed_query)
        code, text = recorder.command("negative-nonce", "ts", "-verify", "-in", "response.tsr", "-queryfile", "different-nonce.tsq", *ts_trust, required=False)
        recorder.rejected("different-nonce-rejected", code, text, r"nonce mismatch")
        changed_reply = bytearray(raw["response"])
        changed_reply[reply["signature_offset"]] ^= 1
        (output / "tampered-signature.tsr").write_bytes(changed_reply)
        code, text = recorder.command("negative-signature", "ts", "-verify", "-in", "tampered-signature.tsr", "-queryfile", "request.tsq", *ts_trust, required=False)
        recorder.rejected("tampered-signature-rejected", code, text, r"signature failure|signature verify error|signature verification failure|bad signature|pkcs7_signatureverify")
        wrong_trust = ["-CAfile", "signer.pem", "-CApath", str(output / "empty-trust"), "-CAstore", str(output / "empty-trust"), "-attime", str(epoch)]
        code, text = recorder.command("negative-trust", "ts", "-verify", "-in", "response.tsr", "-queryfile", "request.tsq", *wrong_trust, required=False)
        recorder.rejected("wrong-trust-rejected", code, text, r"unable to get (?:local )?issuer certificate|self-signed certificate")
        deadline = reply["gen_time"] - timedelta(seconds=1)
        recorder.check("synthetic-past-deadline-rejected", not deadline_allows(reply["gen_time"], deadline, reply["accuracy_seconds"]),
                       signed_gen_time=reply["gen_time"].isoformat(), synthetic_deadline=deadline.isoformat(), official_deadline=False)
        result = dict(signed_gen_time=reply["gen_time"].isoformat(), signed_epoch=epoch, policy_oid=reply["policy_oid"],
                      serial=reply["serial"], accuracy_seconds=reply["accuracy_seconds"],
                      signer_der_sha256=sha256((output / "actual-signer.der").read_bytes()))
    except Exception as failure:
        error = dict(type=type(failure).__name__, message=str(failure))
    unchanged = all(path.is_file() and sha256(path.read_bytes()) == original_hashes[name] for name, path in paths.items())
    recorder.checks.append(dict(name="source-digests-before-after-match", status="PASS" if unchanged else "FAIL"))
    if not unchanged:
        error = dict(type="VerificationError", message="Source input changed during verification")
    binary_digest = sha256(openssl.read_bytes()) if openssl.is_file() else None
    status = "BLOCKED" if binary_digest is None else ("PASS" if error is None else "FAIL")
    receipt = dict(schema="ssq-dlt-offline-time-probe-v1", technical_status=status, error=error,
                   checks=recorder.checks, scope="SYNTHETIC_RFC3161_TECHNICAL_TEST_ONLY", network_operations=0,
                   trusted_provider_approved_for_formal_use=False, formal_approval=False, historical_asof_proof=False,
                   revocation_check="NOT_RUN", long_term_validation="NOT_ESTABLISHED", A=0, verdict="NO_EDGE", prospective=0,
                   source_files=original_hashes, openssl_path=str(openssl), openssl_sha256=binary_digest,
                   verifier_source_sha256=sha256(Path(__file__).read_bytes()), finished_at_local=local_utc(), **result)
    recorder.json("RECEIPT.json", receipt)
    manifest = {path.name: dict(bytes=path.stat().st_size, sha256=sha256(path.read_bytes())) for path in sorted(output.iterdir()) if path.is_file()}
    recorder.json("ARTIFACTS.json", dict(files=manifest, self_excluded=True))
    return receipt
