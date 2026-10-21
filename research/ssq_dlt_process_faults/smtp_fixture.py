"""Bounded, synthetic STARTTLS SMTP receiver for process-fault experiments.

This receiver binds only 127.0.0.1:587.  It never relays mail, uses only the
synthetic credential below, and accepts only the reserved ``example.invalid``
address.  An occupied port or unavailable OpenSSL is an explicit BLOCKED result;
neither condition is bypassed with another endpoint or a mocked transport.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from typing import IO


HOST = "127.0.0.1"
PORT = 587
SYNTHETIC_ADDRESS = "synthetic@example.invalid"
SYNTHETIC_USERNAME = "synthetic"
SYNTHETIC_PASSWORD = "SYNTHETIC_ONLY"
PASSWORD_ENV = "GLP_SYNTHETIC_SMTP_PASSWORD"


class FixtureBlocked(RuntimeError):
    """A required real-loopback prerequisite is unavailable; do not claim PASS."""


@dataclass(frozen=True)
class SMTPEvent:
    sequence: int
    connection_id: int
    kind: str
    command: str = ""
    detail: str = ""


@dataclass(frozen=True)
class SMTPReceipt:
    transaction_id: int
    connection_id: int
    data_sha256: str
    data_bytes: int
    envelope_from: str
    recipients: tuple[str, ...]
    mode: str


class _ProtocolLimit(Exception):
    pass


class LoopbackSMTP:
    """Context-managed real SMTP fixture, isolated from OS trust and credentials.

    Merge ``child_env`` into the *worker subprocess's* environment.  Do not
    update ``os.environ``: ``SSL_CERT_FILE`` trusts this CA only in that child.
    ``events`` and ``receipts`` are immutable snapshots of append-only logs.
    A receipt proves complete DATA reached the receiver; only the separate
    acknowledgement event indicates that the receiver wrote its SMTP 250 reply.
    """

    MAX_CONNECTIONS = 32
    MAX_EVENTS = 4096
    MAX_LINE_BYTES = 8192
    MAX_DATA_BYTES = 1024 * 1024
    SESSION_SECONDS = 30.0
    IDLE_SECONDS = 10.0

    def __init__(self, directory: Path, mode: str = "accept"):
        if mode not in ("accept", "disconnect_after_data"):
            raise ValueError("INVALID_SYNTHETIC_SMTP_MODE")
        self.directory = Path(directory).resolve()
        self.mode = mode
        self.ca_path = self.directory / "test-ca.pem"
        self.certificate_path = self.directory / "loopback-cert.pem"
        self.events_path = self.directory / "smtp-events.jsonl"
        self.receipts_path = self.directory / "smtp-receipts.jsonl"
        self._condition = threading.Condition(threading.RLock())
        self._events: list[SMTPEvent] = []
        self._receipts: list[SMTPReceipt] = []
        self._acknowledged: list[SMTPReceipt] = []
        self._stats = dict(connections=0, authenticated_connections=0,
                           data_transactions=0, acknowledgements=0)
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._workers: list[threading.Thread] = []
        self._sockets: set[socket.socket] = set()
        self._event_file: IO[str] | None = None
        self._receipt_file: IO[str] | None = None
        self._tls_context: ssl.SSLContext | None = None
        self._entered = False
        self._closed = False

    @property
    def smtp_config(self) -> dict:
        return dict(host=HOST, port=PORT, sender=SYNTHETIC_ADDRESS,
                    username=SYNTHETIC_USERNAME, password_env=PASSWORD_ENV)

    @property
    def child_env(self) -> dict[str, str]:
        return {"SSL_CERT_FILE": str(self.ca_path), PASSWORD_ENV: SYNTHETIC_PASSWORD}

    @property
    def events(self) -> tuple[SMTPEvent, ...]:
        with self._condition:
            return tuple(self._events)

    @property
    def receipts(self) -> tuple[SMTPReceipt, ...]:
        with self._condition:
            return tuple(self._receipts)

    @property
    def stats(self) -> dict[str, int]:
        with self._condition:
            return dict(self._stats)

    @property
    def is_running(self) -> bool:
        return bool(self._accept_thread and self._accept_thread.is_alive()
                    and not self._stop.is_set())

    def __enter__(self) -> "LoopbackSMTP":
        if self._entered or self._closed:
            raise RuntimeError("SMTP_FIXTURE_CONTEXT_CANNOT_BE_REUSED")
        self._entered = True
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((HOST, PORT))
        except OSError as exc:
            listener.close()
            raise FixtureBlocked("BLOCKED_LOOPBACK_PORT_587_UNAVAILABLE") from exc
        self._listener = listener
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents accidental replacement of old evidence.
            self._event_file = self.events_path.open("x", encoding="utf-8", newline="\n")
            self._receipt_file = self.receipts_path.open("x", encoding="utf-8", newline="\n")
            self._make_certificates()
            self._tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._tls_context.load_cert_chain(str(self.certificate_path),
                                             str(self.directory / "loopback-key.pem"))
            listener.listen(8)
            listener.settimeout(0.2)
            self._record_event(0, "listening", detail=f"{HOST}:{PORT}")
            self._accept_thread = threading.Thread(target=self._accept_loop,
                                                   name="synthetic-smtp-listener", daemon=True)
            self._accept_thread.start()
            return self
        except FileExistsError as exc:
            self.close()
            raise FixtureBlocked("BLOCKED_SYNTHETIC_SMTP_EVIDENCE_ALREADY_EXISTS") from exc
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._listener:
            self._listener.close()
        with self._condition:
            active = tuple(self._sockets)
            self._condition.notify_all()
        for connection in active:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        if self._accept_thread:
            self._accept_thread.join(timeout=3)
        for worker in self._workers:
            worker.join(timeout=3)
        if any(worker.is_alive() for worker in self._workers):
            raise RuntimeError("SYNTHETIC_SMTP_WORKER_DID_NOT_STOP")
        for handle in (self._event_file, self._receipt_file):
            if handle:
                handle.close()

    def wait_for_data(self, timeout: float = 10.0, *, count: int = 1) -> SMTPReceipt:
        return self._wait_for(self._receipts, timeout, count, "DATA")

    def wait_for_ack(self, timeout: float = 10.0, *, count: int = 1) -> SMTPReceipt:
        return self._wait_for(self._acknowledged, timeout, count, "SMTP_250")

    def _wait_for(self, values: list[SMTPReceipt], timeout: float,
                  count: int, label: str) -> SMTPReceipt:
        if timeout < 0 or count < 1:
            raise ValueError("INVALID_SMTP_WAIT")
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(values) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stop.is_set():
                    raise TimeoutError(f"SYNTHETIC_SMTP_{label}_NOT_OBSERVED")
                self._condition.wait(remaining)
            return values[count - 1]

    @staticmethod
    def _find_openssl() -> str:
        choices = [shutil.which("openssl")]
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                prefix = Path(root) / ("Programs/Git" if variable == "LOCALAPPDATA" else "Git")
                choices.extend(str(prefix / suffix) for suffix in
                               ("usr/bin/openssl.exe", "mingw64/bin/openssl.exe"))
        for candidate in choices:
            if candidate and Path(candidate).is_file():
                return candidate
        raise FixtureBlocked("BLOCKED_OPENSSL_UNAVAILABLE")

    def _make_certificates(self) -> None:
        openssl = self._find_openssl()
        configuration = self.directory / "openssl-test.cnf"
        # The SAN is deliberately an IP address, matching the pinned SMTP host.
        configuration.write_text(
            "[req]\nprompt=no\ndistinguished_name=dn\n[dn]\nCN=SYNTHETIC LOOPBACK ONLY\n"
            "[ca_ext]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
            "[server_ext]\nbasicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n",
            encoding="ascii")
        commands = [
            ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "1",
             "-config", str(configuration), "-extensions", "ca_ext",
             "-keyout", str(self.directory / "test-ca-key.pem"), "-out", str(self.ca_path)],
            ["req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
             "-config", str(configuration), "-keyout", str(self.directory / "loopback-key.pem"),
             "-out", str(self.directory / "loopback.csr")],
            ["x509", "-req", "-sha256", "-days", "1", "-in", str(self.directory / "loopback.csr"),
             "-CA", str(self.ca_path), "-CAkey", str(self.directory / "test-ca-key.pem"),
             "-CAcreateserial", "-extfile", str(configuration), "-extensions", "server_ext",
             "-out", str(self.certificate_path)],
        ]
        try:
            for index, arguments in enumerate(commands, 1):
                started=time.time()
                result=subprocess.run([openssl, *arguments], capture_output=True,
                                      timeout=30, stdin=subprocess.DEVNULL)
                prefix=self.directory/f"certificate-command-{index}"
                prefix.with_suffix(".stdout").write_bytes(result.stdout)
                prefix.with_suffix(".stderr").write_bytes(result.stderr)
                with prefix.with_suffix(".json").open("x",encoding="utf-8") as stream:
                    json.dump(dict(argv=[openssl,*arguments],exit_code=result.returncode,
                                   started_at_local_unix=started,finished_at_local_unix=time.time(),
                                   stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
                                   stderr_sha256=hashlib.sha256(result.stderr).hexdigest()),stream,indent=2)
                if result.returncode:
                    raise subprocess.CalledProcessError(result.returncode,[openssl,*arguments])
        except (OSError, subprocess.SubprocessError) as exc:
            raise FixtureBlocked("BLOCKED_TEST_CERTIFICATE_GENERATION_FAILED") from exc

    @staticmethod
    def _append_json(handle: IO[str], value: dict) -> None:
        handle.write(json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    def _record_event(self, connection_id: int, kind: str,
                      command: str = "", detail: str = "") -> None:
        with self._condition:
            if len(self._events) >= self.MAX_EVENTS:
                raise _ProtocolLimit("EVENT_LIMIT")
            event = SMTPEvent(len(self._events) + 1, connection_id, kind, command, detail)
            assert self._event_file is not None
            self._append_json(self._event_file, asdict(event))
            self._events.append(event)
            self._condition.notify_all()

    def _record_receipt(self, connection_id: int, data: bytes,
                        sender: str, recipients: list[str]) -> SMTPReceipt:
        with self._condition:
            with (self.directory/f"received-{len(self._receipts)+1:04d}.eml").open("xb") as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            receipt = SMTPReceipt(len(self._receipts) + 1, connection_id,
                                  hashlib.sha256(data).hexdigest(), len(data),
                                  sender, tuple(recipients), self.mode)
            assert self._receipt_file is not None
            self._append_json(self._receipt_file, asdict(receipt))
            self._receipts.append(receipt)
            self._stats["data_transactions"] += 1
            self._condition.notify_all()
            return receipt

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                connection, address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._condition:
                if (self._stop.is_set() or address[0] != HOST
                        or self._stats["connections"] >= self.MAX_CONNECTIONS):
                    connection.close()
                    continue
                self._stats["connections"] += 1
                connection_id = self._stats["connections"]
                self._sockets.add(connection)
                worker = threading.Thread(target=self._session,
                                          args=(connection, connection_id),
                                          name=f"synthetic-smtp-{connection_id}", daemon=True)
                self._workers.append(worker)
                worker.start()

    def _readline(self, connection: socket.socket, buffer: bytearray, deadline: float) -> bytes:
        while True:
            index = buffer.find(b"\n")
            if index >= 0:
                if index + 1 > self.MAX_LINE_BYTES:
                    raise _ProtocolLimit("LINE_LIMIT")
                line = bytes(buffer[:index + 1])
                del buffer[:index + 1]
                return line
            if len(buffer) >= self.MAX_LINE_BYTES:
                raise _ProtocolLimit("LINE_LIMIT")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self._stop.is_set():
                raise _ProtocolLimit("SESSION_TIME_LIMIT")
            connection.settimeout(min(self.IDLE_SECONDS, remaining))
            chunk = connection.recv(min(4096, self.MAX_LINE_BYTES - len(buffer)))
            if not chunk:
                raise EOFError
            buffer.extend(chunk)

    def _session(self, connection: socket.socket, connection_id: int) -> None:
        deadline = time.monotonic() + self.SESSION_SECONDS
        buffer = bytearray()
        tls = False
        authenticated = False
        sender = ""
        recipients: list[str] = []
        try:
            self._record_event(connection_id, "connected", detail=HOST)
            connection.sendall(b"220 synthetic.example.invalid ESMTP SYNTHETIC_ONLY\r\n")
            while not self._stop.is_set():
                line = self._readline(connection, buffer, deadline)
                command, _, arguments = line.rstrip(b"\r\n").partition(b" ")
                verb = command.decode("ascii", "replace").upper()
                logged_verb = verb if re.fullmatch(r"[A-Z]{1,16}", verb) else "INVALID"
                detail = ""
                if verb == "AUTH":
                    detail = arguments.split(b" ", 1)[0].decode("ascii", "replace")[:16]
                self._record_event(connection_id, "command", logged_verb, detail)
                if verb in ("EHLO", "HELO"):
                    if tls:
                        connection.sendall(b"250-synthetic.example.invalid\r\n250-AUTH PLAIN LOGIN\r\n250 SIZE 1048576\r\n")
                    else:
                        connection.sendall(b"250-synthetic.example.invalid\r\n250-STARTTLS\r\n250 SIZE 1048576\r\n")
                elif verb == "STARTTLS" and not tls:
                    if buffer:
                        raise _ProtocolLimit("PIPELINED_STARTTLS")
                    connection.sendall(b"220 Ready for synthetic TLS\r\n")
                    assert self._tls_context is not None
                    secure = self._tls_context.wrap_socket(connection, server_side=True,
                                                           do_handshake_on_connect=False)
                    with self._condition:
                        self._sockets.discard(connection)
                        self._sockets.add(secure)
                    connection = secure
                    connection.settimeout(min(self.IDLE_SECONDS, max(0.01, deadline - time.monotonic())))
                    connection.do_handshake()
                    tls = True
                    authenticated = False
                    sender, recipients = "", []
                    self._record_event(connection_id, "tls_established", detail=connection.version() or "")
                elif verb == "AUTH" and tls:
                    was_authenticated = authenticated
                    authenticated = self._authenticate(connection, buffer, deadline, arguments)
                    if authenticated:
                        if not was_authenticated:
                            with self._condition:
                                self._stats["authenticated_connections"] += 1
                        self._record_event(connection_id, "authenticated", detail=SYNTHETIC_USERNAME)
                        connection.sendall(b"235 2.7.0 Synthetic authentication successful\r\n")
                    else:
                        self._record_event(connection_id, "authentication_rejected")
                        connection.sendall(b"535 5.7.8 Synthetic credential required\r\n")
                elif verb == "MAIL" and tls and authenticated:
                    match = re.fullmatch(rb"FROM:\s*<([^<>]*)>(?:\s+SIZE=\d+)?", arguments, re.IGNORECASE)
                    if not match or match.group(1).decode("ascii", "replace") != SYNTHETIC_ADDRESS:
                        connection.sendall(b"553 5.7.1 Synthetic sender only\r\n")
                    else:
                        sender, recipients = SYNTHETIC_ADDRESS, []
                        connection.sendall(b"250 2.1.0 Synthetic sender accepted\r\n")
                elif verb == "RCPT" and sender:
                    match = re.fullmatch(rb"TO:\s*<([^<>]*)>", arguments, re.IGNORECASE)
                    if not match or match.group(1).decode("ascii", "replace") != SYNTHETIC_ADDRESS:
                        connection.sendall(b"553 5.7.1 Synthetic recipient only\r\n")
                    elif len(recipients) >= 8:
                        connection.sendall(b"452 4.5.3 Recipient limit\r\n")
                    else:
                        recipients.append(SYNTHETIC_ADDRESS)
                        connection.sendall(b"250 2.1.5 Synthetic recipient accepted\r\n")
                elif verb == "DATA" and recipients:
                    connection.sendall(b"354 End synthetic DATA with <CRLF>.<CRLF>\r\n")
                    data = bytearray()
                    while True:
                        data_line = self._readline(connection, buffer, deadline)
                        if data_line == b".\r\n":
                            break
                        if data_line.startswith(b".."):
                            data_line = data_line[1:]
                        if len(data) + len(data_line) > self.MAX_DATA_BYTES:
                            raise _ProtocolLimit("DATA_SIZE_LIMIT")
                        data.extend(data_line)
                    receipt = self._record_receipt(connection_id, bytes(data), sender, recipients)
                    self._record_event(connection_id, "data_received", detail=receipt.data_sha256)
                    if self.mode == "disconnect_after_data":
                        self._record_event(connection_id, "disconnect_before_ack", detail=str(receipt.transaction_id))
                        return
                    connection.sendall(b"250 2.0.0 Synthetic DATA accepted\r\n")
                    self._record_event(connection_id, "acknowledgement", detail=str(receipt.transaction_id))
                    with self._condition:
                        self._acknowledged.append(receipt)
                        self._stats["acknowledgements"] += 1
                        self._condition.notify_all()
                    sender, recipients = "", []
                elif verb == "RSET":
                    sender, recipients = "", []
                    connection.sendall(b"250 2.0.0 Reset\r\n")
                elif verb == "NOOP":
                    connection.sendall(b"250 2.0.0 OK\r\n")
                elif verb == "QUIT":
                    connection.sendall(b"221 2.0.0 Closing synthetic session\r\n")
                    return
                else:
                    connection.sendall(b"530 5.7.0 Synthetic STARTTLS and AUTH required\r\n")
        except (EOFError, OSError, ssl.SSLError, _ProtocolLimit) as exc:
            if not self._stop.is_set():
                try:
                    self._record_event(connection_id, "session_ended", detail=type(exc).__name__)
                except _ProtocolLimit:
                    pass
        finally:
            with self._condition:
                self._sockets.discard(connection)
            connection.close()

    def _authenticate(self, connection: socket.socket, buffer: bytearray,
                      deadline: float, arguments: bytes) -> bool:
        mechanism, _, initial = arguments.partition(b" ")
        try:
            if mechanism.upper() == b"PLAIN":
                if not initial:
                    connection.sendall(b"334 \r\n")
                    initial = self._readline(connection, buffer, deadline).strip()
                fields = base64.b64decode(initial, validate=True).split(b"\0")
                if len(fields) != 3 or fields[0] not in (b"", SYNTHETIC_USERNAME.encode()):
                    return False
                username, password = fields[1:]
            elif mechanism.upper() == b"LOGIN":
                if not initial:
                    connection.sendall(b"334 VXNlcm5hbWU6\r\n")
                    initial = self._readline(connection, buffer, deadline).strip()
                username = base64.b64decode(initial, validate=True)
                connection.sendall(b"334 UGFzc3dvcmQ6\r\n")
                password = base64.b64decode(self._readline(connection, buffer, deadline).strip(), validate=True)
            else:
                return False
        except (binascii.Error, ValueError):
            return False
        return (hmac.compare_digest(username, SYNTHETIC_USERNAME.encode())
                and hmac.compare_digest(password, SYNTHETIC_PASSWORD.encode()))
