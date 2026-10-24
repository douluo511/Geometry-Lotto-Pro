"""Bounded raw observations only: no targets, forecasts, ledger writes or admission.

Two freshly fetched complete 100-row pages are preserved and replayed using the
repository's pinned parser in separate interpreters. The fixed latest 120 rows
are a distinct study input policy, never recovered from a quarantined bundle.
All clocks and source/publication authenticity remain untrusted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import requests

from . import official_intake as oi
from .core import GateError

SCHEMA = "V47-RAW-OBSERVATION-1"
POLICY = "LATEST_120_VALIDATED_DRAWS_V1"
SELF_PATH = "research/harness_v46/recent_observation.py"
ENDPOINTS = {
    "SSQ": "https://www.swlc.net.cn/lottery/ssq.html",
    "DLT": "https://api.js-lottery.com/Lottery/_ListData",
}
MAX_BYTES = 8 * 1024 * 1024
MANIFEST_KEYS = frozenset({
    "schema", "lottery", "source_id", "history_policy", "all_rows", "selected_rows",
    "selected_rows_sha256", "parser_source_files_sha256", "parser_source_sha256",
    "parser_version", "pages", "capture_started_at_local_untrusted",
    "observed_at_local_untrusted", "timestamp_trust", "parser_to_raw_binding",
    "source_origin_authenticity", "publication_time_authenticity", "official_G01",
    "official_target_admission", "formal_A", "decision",
})
PAGE_KEYS = frozenset({
    "requested_url", "url", "http_status", "content_type",
    "fetch_completed_at_local_untrusted", "size_bytes", "raw_sha256",
    "sequence", "raw_file", "parser_version",
})


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value) -> str:
    return _sha(_canonical(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pins(game: str) -> dict:
    if game not in ENDPOINTS:
        raise GateError("OBSERVATION_GAME_INVALID")
    return {**oi.source_file_hashes(game), SELF_PATH: _sha(Path(__file__).read_bytes()),
            "research/harness_v46/core.py": _sha((oi.REPO_ROOT / "research/harness_v46/core.py").read_bytes())}


def _stamp(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed
    except (ValueError, TypeError, AttributeError) as exc:
        raise GateError("OBSERVATION_LOCAL_TIME_INVALID") from exc


def _params(game: str, page: int, first_rows=None) -> dict:
    if game == "DLT":
        return {"itemType": "lo", "pageIndex": str(page), "pageSize": "100"}
    if page == 1:
        return {"limit": "100", "view": "previous"}
    oldest = min(row["issue"] for row in first_rows)
    return {"view": "previous", "limit": "100",
            "start_issue": f"{int(oldest[:4]) - 1}001",
            "end_issue": str(int(oldest) - 1)}


def _check_url(game: str, url: str, expected_params: dict) -> None:
    actual, expected = urlsplit(url), urlsplit(ENDPOINTS[game])
    try:
        port = actual.port
    except ValueError as exc:
        raise GateError("OBSERVATION_URL_INVALID") from exc
    query_items = parse_qsl(actual.query, keep_blank_values=True)
    if (actual.scheme != "https" or actual.hostname != expected.hostname
            or actual.path != expected.path or actual.username or actual.password
            or actual.fragment or port not in (None, 443)
            or len(query_items) != len(expected_params)
            or dict(query_items) != expected_params):
        raise GateError("OBSERVATION_URL_OR_REDIRECT_NOT_ALLOWLISTED")


def _fetch_page(game: str, params: dict, headers: dict) -> tuple[bytes, dict]:
    requested = ENDPOINTS[game] + "?" + urlencode(params)
    current = requested
    for _ in range(6):
        _check_url(game, current, params)
        response = requests.get(current, headers=headers, timeout=(10, 30),
                                allow_redirects=False, stream=True)
        try:
            final = str(response.url or current)
            _check_url(game, final, params)
            status = int(response.status_code)
            if status in oi.REDIRECT_CODES:
                location = response.headers.get("Location")
                if not location:
                    raise GateError("OBSERVATION_REDIRECT_LOCATION_MISSING")
                current = urljoin(final, location)
                _check_url(game, current, params)
                continue
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if status != 200:
                raise GateError("OBSERVATION_HTTP_STATUS:" + str(status))
            if not any(value in content_type for value in ("text/html", "application/xhtml+xml")):
                raise GateError("OBSERVATION_CONTENT_TYPE_INVALID")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    body.extend(chunk[:MAX_BYTES + 1 - len(body)])
                    if len(body) > MAX_BYTES:
                        raise GateError("OBSERVATION_RAW_BYTES_EXCEED_LIMIT")
            raw = bytes(body)
            # This clock samples completion of the entire bounded body. It is
            # never a publication/draw/cutoff time or a trusted timestamp.
            fetched = _now()
            if not raw:
                raise GateError("OBSERVATION_RAW_BYTES_EMPTY")
            return raw, {"requested_url": requested, "url": final,
                         "http_status": status, "content_type": content_type,
                         "fetch_completed_at_local_untrusted": fetched,
                         "size_bytes": len(raw), "raw_sha256": _sha(raw)}
        finally:
            response.close()
    raise GateError("OBSERVATION_REDIRECT_LIMIT")


class _Tables(HTMLParser):
    """Account for every data row, including rows a source regex would skip."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack = [], []
        self.row = self.cell = None
        self.cell_style = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.stack:
                raise GateError("OBSERVATION_NESTED_TABLE_UNSUPPORTED")
            self.stack.append([])
        elif tag == "tr" and self.stack:
            if self.row is not None:
                raise GateError("OBSERVATION_UNCLOSED_ROW")
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            if self.cell is not None:
                raise GateError("OBSERVATION_UNCLOSED_CELL")
            self.cell = []
            self.cell_style = dict(attrs).get("style", "") or ""
            self.cell_kind = tag

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            if self.cell_kind != tag:
                raise GateError("OBSERVATION_CELL_TAG_MISMATCH")
            self.row.append((tag, " ".join("".join(self.cell).split()), self.cell_style))
            self.cell = None
        elif tag == "tr" and self.stack:
            if self.row is None or self.cell is not None:
                raise GateError("OBSERVATION_MALFORMED_ROW")
            self.stack[-1].append(self.row)
            self.row = None
        elif tag == "table" and self.stack:
            if self.row is not None:
                raise GateError("OBSERVATION_UNCLOSED_ROW")
            self.tables.append(self.stack.pop())


def _complete_row_coverage(game: str, text: str, parsed: list[dict]) -> None:
    tables = _Tables()
    tables.feed(text)
    tables.close()
    if tables.stack or tables.row is not None or tables.cell is not None:
        raise GateError("OBSERVATION_INCOMPLETE_TABLE")
    relevant = []
    issue_pattern = r"20\d{5}" if game == "SSQ" else r"\d{5}"
    for table in tables.tables:
        if any(any(re.fullmatch(issue_pattern, cell[1]) or
                       re.match(r"20\d{2}-\d{2}-\d{2}", cell[1]) for cell in row)
               for row in table):
            relevant.append(table)
    if len(relevant) != 1:
        raise GateError("OBSERVATION_DRAW_TABLE_COVERAGE_INVALID")
    candidates, header_count = [], 0
    for index, row in enumerate(relevant[0]):
        if row and all(cell[0] == "th" for cell in row):
            candidate_tokens = any(re.search(r"20\d{2}-\d{2}-\d{2}", cell[1]) or
                                   re.search(r"(?<!\d)(?:20\d{5}|\d{5})(?!\d)", cell[1])
                                   for cell in row)
            if candidates or candidate_tokens or header_count >= (2 if game == "SSQ" else 1):
                raise GateError("OBSERVATION_DATA_BEARING_OR_MISPLACED_HEADER_ROW")
            header_count += 1
            continue
        # Jiangsu's documented first table header uses bold TD cells.
        if (index == 0 and row and all("font-weight:bold" in cell[2].replace(" ", "").lower()
                                      and not re.search(r"\d", cell[1]) for cell in row)):
            header_count += 1
            continue
        if not row or any(cell[0] != "td" for cell in row):
            raise GateError("OBSERVATION_UNACCOUNTED_TABLE_ROW")
        candidates.append(row)
    if len(candidates) != 100 or len(parsed) != len(candidates):
        raise GateError("OBSERVATION_ROW_COVERAGE_REQUIRES_100")
    claimed = {row["issue"]: row["draw_date"] for row in parsed}
    seen = set()
    for cells in candidates:
        if len(cells) < (4 if game == "SSQ" else 3):
            raise GateError("OBSERVATION_ROW_CELL_COVERAGE")
        issue_cell, date_cell = (0, 1) if game == "SSQ" else (1, 0)
        issue, day = cells[issue_cell][1], cells[date_cell][1]
        if (not re.fullmatch(issue_pattern, issue) or
                not re.fullmatch(r"20\d{2}-\d{2}-\d{2}(?:\([^)]*\))?", day)
                or issue in seen or claimed.get(issue) != day[:10]):
            raise GateError("OBSERVATION_ROW_COVERAGE_MISMATCH")
        seen.add(issue)


def _worker(payload: dict) -> dict:
    game = payload["lottery"]
    pins = _pins(game)
    if pins != payload["parser_source_files_sha256"]:
        raise GateError("OBSERVATION_PARSER_SOURCE_HASH_MISMATCH")
    source_path = oi.REPO_ROOT / ("SSQ/SSQ" if game == "SSQ" else "DLT/src")
    sys.path.insert(0, str(source_path))
    source = importlib.import_module("glp.sources")
    parser_version = oi._expected_parser_version(game)
    if source.PARSER_VERSION != parser_version:
        raise GateError("OBSERVATION_IMPORTED_PARSER_MISMATCH")
    if payload["operation"] == "config":
        headers = dict(source.HEADERS if game == "SSQ" else source.JIANGSU_HEADERS)
        headers["Referer"] = "https://www.swlc.net.cn/" if game == "SSQ" else source.JIANGSU_DATA_PAGE
        if game == "DLT":
            headers["X-Requested-With"] = "XMLHttpRequest"
        return {"headers": headers, "parser_version": parser_version}
    pages = payload["pages"]
    if len(pages) not in (1, 2):
        raise GateError("OBSERVATION_PAGE_COUNT_INVALID")
    all_rows, page_rows = [], []
    for sequence, page in enumerate(pages, 1):
        raw = base64.b64decode(page["raw_base64"], validate=True)
        if (_sha(raw) != page["raw_sha256"] or len(raw) != page["size_bytes"]
                or not raw or len(raw) > MAX_BYTES or page["http_status"] != 200):
            raise GateError("OBSERVATION_RAW_BYTES_SHA_MISMATCH")
        if page["parser_version"] != parser_version:
            raise GateError("OBSERVATION_PAGE_PARSER_MISMATCH")
        params = _params(game, sequence, page_rows[0] if page_rows else None)
        _check_url(game, page["requested_url"], params)
        _check_url(game, page["url"], params)
        _stamp(page["fetch_completed_at_local_untrusted"])
        if not any(v in page["content_type"] for v in ("text/html", "application/xhtml+xml")):
            raise GateError("OBSERVATION_PAGE_CONTENT_TYPE_INVALID")
        if game == "SSQ":
            draws = source.parse_shanghai_history(raw)
            text = source._html_markup(raw)
        else:
            text = source._decode_html(raw)
            oi._verify_jiangsu_draw_date_columns(text)
            draws = source._parse_jiangsu_html(text)
        parsed = oi._source_rows(draws)
        _complete_row_coverage(game, text, parsed)
        parsed.sort(key=lambda row: int(row["issue"]))
        parsed = oi._canonical_draws(game, parsed, minimum=100)
        china_fetch_day = _stamp(page["fetch_completed_at_local_untrusted"]).astimezone(
            timezone(timedelta(hours=8))).date().isoformat()
        if any(row["draw_date"] >= china_fetch_day for row in parsed):
            raise GateError("OBSERVATION_SAME_DAY_OR_FUTURE_DRAW_DATE")
        if oi.calendar_diagnostics(game, parsed):
            raise GateError("OBSERVATION_DRAW_CALENDAR_ANOMALIES")
        if page_rows and int(parsed[-1]["issue"]) >= int(page_rows[0][0]["issue"]):
            raise GateError("OBSERVATION_CROSS_PAGE_DUPLICATE_OR_ORDER")
        if game == "SSQ" and sequence == 2 and any(
                not params["start_issue"] <= row["issue"] <= params["end_issue"] for row in parsed):
            raise GateError("OBSERVATION_ROW_OUTSIDE_REQUEST_RANGE")
        page_rows.append(parsed)
        all_rows.extend(parsed)
    all_rows.sort(key=lambda row: int(row["issue"]))
    all_rows = oi._canonical_draws(game, all_rows, minimum=100 * len(pages))
    if oi.calendar_diagnostics(game, all_rows):
        raise GateError("OBSERVATION_DRAW_CALENDAR_ANOMALIES")
    if _pins(game) != pins:
        raise GateError("OBSERVATION_PARSER_SOURCE_HASH_CHANGED")
    return {"all_rows": all_rows, "parser_version": parser_version,
            "parser_source_files_sha256": pins}


def _parser_call(game: str, pins: dict, *, pages=None) -> dict:
    payload = {"lottery": game, "parser_source_files_sha256": pins,
               "operation": "config" if pages is None else "parse", "pages": pages}
    process = subprocess.run(
        [sys.executable, "-m", "research.harness_v46.recent_observation", "_worker"],
        input=_canonical(payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=oi.REPO_ROOT, timeout=120, check=False,
    )
    if process.returncode:
        raise GateError("OBSERVATION_PARSER_REPLAY_FAILED:" + process.stderr.decode("utf-8", errors="replace")[-2000:])
    if _pins(game) != pins:
        raise GateError("OBSERVATION_PARSER_SOURCE_HASH_CHANGED")
    return json.loads(process.stdout)


def capture(game: str, output_dir: str | Path) -> Path:
    """Fetch only the two hardcoded fresh pages; return a verified manifest path."""
    pins = _pins(game)
    output = oi._physical_root(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    started = _now()
    config = _parser_call(game, pins)
    pages, first_rows = [], None
    for sequence in (1, 2):
        raw, page = _fetch_page(game, _params(game, sequence, first_rows), config["headers"])
        page.update({"sequence": sequence, "raw_file": f"raw/{page['raw_sha256']}.bin",
                     "parser_version": config["parser_version"]})
        # Preserve complete bytes before semantic parsing; failures never receive
        # a successful observation manifest or a silently shortened history.
        with (output / page["raw_file"]).open("xb") as handle:
            handle.write(raw)
        pages.append({**page, "raw_base64": base64.b64encode(raw).decode("ascii")})
        parsed = _parser_call(game, pins, pages=pages)
        if sequence == 1:
            first_rows = parsed["all_rows"]
    all_rows = parsed["all_rows"]
    selected = all_rows[-120:]
    observed = _now()
    manifest = {
        "schema": SCHEMA, "lottery": game,
        "source_id": "shanghai" if game == "SSQ" else "jiangsu",
        "history_policy": POLICY, "all_rows": all_rows, "selected_rows": selected,
        "selected_rows_sha256": _digest(selected),
        "parser_source_files_sha256": pins, "parser_source_sha256": _digest(pins),
        "parser_version": config["parser_version"],
        "pages": [{k: v for k, v in page.items() if k != "raw_base64"} for page in pages],
        "capture_started_at_local_untrusted": started,
        "observed_at_local_untrusted": observed,
        "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
        "parser_to_raw_binding": "SECOND_PROCESS_SAME_PARSER_REPLAY_MATCHED",
        "source_origin_authenticity": "NOT_VERIFIED",
        "publication_time_authenticity": "NOT_VERIFIED",
        "official_G01": "BLOCKED", "official_target_admission": "BLOCKED",
        "formal_A": 0, "decision": "NO_EDGE",
    }
    path = output / "manifest.json"
    with path.open("xb") as handle:
        handle.write(_canonical(manifest) + b"\n")
    verify_observation(output)
    return path


def verify_observation(observation_dir: str | Path) -> dict:
    """Read-only replay of original raw files; never trusts manifest row claims."""
    output = oi._physical_root(observation_dir).resolve(strict=True)
    manifest = json.loads((output / "manifest.json").read_bytes())
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise GateError("OBSERVATION_MANIFEST_SCHEMA_CONTRACT_INVALID")
    game = manifest.get("lottery")
    pins = _pins(game)
    if (manifest.get("parser_source_files_sha256") != pins or
            manifest.get("parser_source_sha256") != _digest(pins)):
        raise GateError("OBSERVATION_PARSER_SOURCE_HASH_MISMATCH")
    if (manifest.get("schema") != SCHEMA or manifest.get("history_policy") != POLICY
            or manifest.get("source_id") != ("shanghai" if game == "SSQ" else "jiangsu")
            or type(manifest.get("formal_A")) is not int or manifest.get("formal_A") != 0
            or manifest.get("decision") != "NO_EDGE"
            or manifest.get("official_G01") != "BLOCKED"
            or manifest.get("official_target_admission") != "BLOCKED"
            or manifest.get("source_origin_authenticity") != "NOT_VERIFIED"
            or manifest.get("publication_time_authenticity") != "NOT_VERIFIED"
            or manifest.get("timestamp_trust") != "LOCAL_CLOCK_UNTRUSTED"
            or manifest.get("parser_to_raw_binding") != "SECOND_PROCESS_SAME_PARSER_REPLAY_MATCHED"):
        raise GateError("OBSERVATION_MANIFEST_CONTRACT_INVALID")
    observed = _stamp(manifest["observed_at_local_untrusted"])
    started = _stamp(manifest["capture_started_at_local_untrusted"])
    pages = manifest.get("pages")
    if not isinstance(pages, list) or len(pages) != 2:
        raise GateError("OBSERVATION_REQUIRES_TWO_RAW_PAGES")
    payload_pages, digests = [], set()
    previous = started
    for sequence, page in enumerate(pages, 1):
        if not isinstance(page, dict) or set(page) != PAGE_KEYS:
            raise GateError("OBSERVATION_PAGE_SCHEMA_CONTRACT_INVALID")
        digest = page.get("raw_sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in digests:
            raise GateError("OBSERVATION_RAW_SHA_INVALID_OR_DUPLICATE")
        digests.add(digest)
        if page.get("raw_file") != f"raw/{digest}.bin" or page.get("sequence") != sequence:
            raise GateError("OBSERVATION_RAW_REFERENCE_INVALID")
        path = (output / page["raw_file"]).resolve(strict=True)
        if not path.is_relative_to(output):
            raise GateError("OBSERVATION_RAW_PATH_ESCAPED")
        raw = path.read_bytes()
        if _sha(raw) != digest or len(raw) != page["size_bytes"]:
            raise GateError("OBSERVATION_RAW_BYTES_SHA_MISMATCH")
        stamp = _stamp(page["fetch_completed_at_local_untrusted"])
        if not previous <= stamp <= observed:
            raise GateError("OBSERVATION_LOCAL_TIME_ORDER_INVALID")
        previous = stamp
        payload_pages.append({**page, "raw_base64": base64.b64encode(raw).decode("ascii")})
    replay = _parser_call(game, pins, pages=payload_pages)
    all_rows = replay["all_rows"]
    if (len(all_rows) != 200 or _canonical(manifest.get("all_rows")) != _canonical(all_rows)
            or _canonical(manifest.get("selected_rows")) != _canonical(all_rows[-120:])
            or manifest.get("selected_rows_sha256") != _digest(all_rows[-120:])
            or manifest.get("parser_version") != replay["parser_version"]):
        raise GateError("OBSERVATION_REPLAY_ROWS_DIFFER_FROM_MANIFEST")
    return manifest


def make_observation_metadata(observation_dir: str | Path) -> dict:
    manifest = verify_observation(observation_dir)
    return {"schema": SCHEMA, "manifest_sha256": _digest(manifest),
            "parser_source_sha256": manifest["parser_source_sha256"],
            "raw_sha256s": [page["raw_sha256"] for page in manifest["pages"]],
            "observed_at_local_untrusted": manifest["observed_at_local_untrusted"],
            "history_policy": POLICY,
            "selected_rows_sha256": manifest["selected_rows_sha256"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    take = commands.add_parser("capture")
    take.add_argument("game", choices=("SSQ", "DLT"))
    take.add_argument("output_dir")
    for name in ("verify", "metadata"):
        commands.add_parser(name).add_argument("observation_dir")
    commands.add_parser("_worker")
    args = parser.parse_args(argv)
    try:
        if args.command == "_worker":
            result = _worker(json.load(sys.stdin))
        elif args.command == "capture":
            result = {"manifest": str(capture(args.game, args.output_dir))}
        elif args.command == "verify":
            result = verify_observation(args.observation_dir)
        else:
            result = make_observation_metadata(args.observation_dir)
        sys.stdout.buffer.write(_canonical(result) + b"\n")
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
