"""Strict presentation-only adapter around the unchanged frozen verifier.

Only complete table data-row order and JSON object-key order inside ``pre``
may differ.  Header rows, row multiplicity, list order, numeric JSON lexemes,
all other text, markup, and attributes remain part of the comparison.  The
native report byte mismatch remains recorded; it is never rewritten to PASS.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from research.ssq_dlt_d2_forensics import protocol as frozen_protocol


class EvidenceMismatch(ValueError):
    """A presentation difference exceeds the two permitted transformations."""


@dataclass
class Element:
    tag: str
    attrs: tuple = ()
    opening: str = ""
    closing: str = ""
    children: list = field(default_factory=list)


class StrictHTML(HTMLParser):
    VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img",
                      "input", "link", "meta", "param", "source", "track", "wbr"))

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.root = Element("DOCUMENT")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, tuple(attrs), self.get_starttag_text())
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, tuple(attrs), self.get_starttag_text()))

    def handle_endtag(self, tag):
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise EvidenceMismatch("HTML_UNBALANCED_END_TAG " + tag)
        line, column = self.getpos()
        offset = sum(len(value) for value in self.source.splitlines(keepends=True)[:line - 1]) + column
        stop = self.source.find(">", offset)
        if stop < 0:
            raise EvidenceMismatch("HTML_UNTERMINATED_END_TAG")
        self.stack.pop().closing = self.source[offset:stop + 1]

    def handle_data(self, data):
        self.stack[-1].children.append(("text", data))

    def handle_entityref(self, name):
        self.stack[-1].children.append(("entity", "&" + name + ";"))

    def handle_charref(self, name):
        self.stack[-1].children.append(("charref", "&#" + name + ";"))

    def handle_comment(self, data):
        self.stack[-1].children.append(("comment", data))

    def handle_decl(self, decl):
        self.stack[-1].children.append(("declaration", decl))

    def handle_pi(self, data):
        self.stack[-1].children.append(("processing_instruction", data))

    def unknown_decl(self, data):
        raise EvidenceMismatch("HTML_UNKNOWN_DECLARATION " + data)

    def finish(self):
        self.close()
        if len(self.stack) != 1:
            raise EvidenceMismatch("HTML_UNCLOSED_TAG " + self.stack[-1].tag)
        return self.root


@dataclass(frozen=True)
class NumberLexeme:
    value: str


def _strict_json(text):
    def object_pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise EvidenceMismatch("PRE_DUPLICATE_JSON_KEY " + key)
            value[key] = item
        return value

    def nonfinite(value):
        raise EvidenceMismatch("PRE_NONFINITE_JSON " + value)

    try:
        value = json.loads(text, object_pairs_hook=object_pairs,
                           parse_int=NumberLexeme, parse_float=NumberLexeme,
                           parse_constant=nonfinite)
    except json.JSONDecodeError as exc:
        raise EvidenceMismatch("PRE_NOT_STRICT_JSON") from exc

    def freeze(item):
        if isinstance(item, NumberLexeme):
            return ("number", item.value)
        if isinstance(item, dict):
            return ("object", tuple((key, freeze(v)) for key, v in sorted(item.items())))
        if isinstance(item, list):
            return ("array", tuple(freeze(v) for v in item))
        if item is None:
            return ("null",)
        if type(item) is bool:
            return ("boolean", item)
        if type(item) is str:
            return ("string", item)
        raise EvidenceMismatch("PRE_UNEXPECTED_JSON_TYPE")

    return freeze(value)


def _parse_html(value):
    parser = StrictHTML(value)
    parser.feed(value)
    return parser.finish()


def _signature(node, counts):
    if not isinstance(node, Element):
        return node
    prefix = ("element", node.tag, node.attrs, node.opening, node.closing)
    if node.tag == "pre":
        if any(isinstance(child, Element) or child[0] not in ("text", "entity", "charref")
               for child in node.children):
            raise EvidenceMismatch("PRE_MUST_CONTAIN_ONLY_JSON_TEXT")
        counts["json_pre_blocks"] += 1
        decoded = html.unescape("".join(child[1] for child in node.children))
        return prefix + (("json", _strict_json(decoded)),)
    if node.tag == "table":
        # No other table structure can disappear through normalization.
        # The frozen renderer emits one direct header row followed by td rows.
        if not node.children or any(not isinstance(child, Element) or child.tag != "tr"
                                    for child in node.children):
            raise EvidenceMismatch("TABLE_REQUIRES_DIRECT_COMPLETE_ROWS")
        header, *rows = node.children
        if not header.children or any(not isinstance(c, Element) or c.tag != "th"
                                      for c in header.children):
            raise EvidenceMismatch("TABLE_FIXED_HEADER_REQUIRED")
        for row in rows:
            if not row.children or any(not isinstance(c, Element) or c.tag != "td"
                                       for c in row.children):
                raise EvidenceMismatch("TABLE_COMPLETE_DATA_ROWS_REQUIRED")
        counts["tables"] += 1
        counts["data_rows"] += len(rows)
        # A sorted tuple is a multiset: repeated rows remain repeated.
        signatures = [_signature(row, counts) for row in rows]
        return prefix + ((_signature(header, counts), tuple(sorted(signatures, key=repr))),)
    return prefix + (tuple(_signature(child, counts) for child in node.children),)


def assert_semantic_html_equal(expected: str, saved: str) -> dict:
    """Fail closed unless differences are solely the permitted permutations."""
    expected_counts = dict(tables=0, data_rows=0, json_pre_blocks=0)
    saved_counts = dict(expected_counts)
    left = _signature(_parse_html(expected), expected_counts)
    right = _signature(_parse_html(saved), saved_counts)
    if left != right or expected_counts != saved_counts:
        raise EvidenceMismatch("HTML_SEMANTIC_PRESENTATION_MISMATCH")
    return {"status": "PASS_ONLY_COMPLETE_ROW_AND_JSON_OBJECT_KEY_PERMUTATIONS",
            **expected_counts,
            "semantic_sha256": hashlib.sha256(repr(left).encode("utf-8")).hexdigest(),
            "byte_identical": expected == saved,
            "allowed_transformations": ["COMPLETE_TABLE_DATA_ROW_MULTISET_ORDER",
                                        "PRE_JSON_OBJECT_KEY_ORDER_ONLY"],
            "duplicate_rows_preserved": True, "json_list_order_preserved": True,
            "json_numeric_lexemes_preserved": True}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _input_manifest(directory):
    return {path.relative_to(directory).as_posix(): _sha(path)
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _immutable_events(snapshot, protocol):
    connection = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        return [(rowid, kind, key, protocol.Store.checked((payload, checksum)))
                for rowid, kind, key, payload, checksum in connection.execute(
                    "SELECT rowid,kind,key,payload,sha256 FROM events ORDER BY rowid")]
    finally:
        connection.close()


@contextmanager
def presentation_adapter(protocol, directory, snapshot, expected_result, saved_html):
    """Patch only two in-memory I/O/presentation functions, restoring on exit."""
    old_render, old_readonly = protocol.render, protocol.readonly_events
    expected_canonical = protocol.canonical(expected_result)
    calls = {"validated_render_calls": 0, "immutable_ledger_reads": 0}

    def validated_render(result):
        if protocol.canonical(result) != expected_canonical:
            raise EvidenceMismatch("ADAPTER_RENDER_RESULT_CHANGED")
        assert_semantic_html_equal(old_render(result), saved_html)
        calls["validated_render_calls"] += 1
        return saved_html

    def immutable_readonly(requested):
        if Path(requested).resolve() != directory:
            raise EvidenceMismatch("ADAPTER_UNEXPECTED_LEDGER_DIRECTORY")
        calls["immutable_ledger_reads"] += 1
        return _immutable_events(snapshot, protocol)

    protocol.render, protocol.readonly_events = validated_render, immutable_readonly
    try:
        yield calls
    finally:
        protocol.render, protocol.readonly_events = old_render, old_readonly


def verify_study(directory, receipt, *, protocol=frozen_protocol):
    """Verify stored evidence without executing an experiment or changing it."""
    directory, receipt = Path(directory).resolve(), Path(receipt).resolve()
    if not directory.is_dir():
        raise ValueError("STUDY_DIRECTORY_REQUIRED")
    if receipt.is_relative_to(directory):
        raise ValueError("RECEIPT_MUST_BE_OUTSIDE_FROZEN_STUDY")
    if receipt.exists():
        raise FileExistsError("RECEIPT_MUST_BE_NEW " + str(receipt))
    if not receipt.parent.is_dir():
        raise ValueError("RECEIPT_PARENT_MUST_EXIST")
    before = _input_manifest(directory)
    source_before = protocol.source_manifest()
    result = protocol.parse((directory / "result.json").read_bytes())
    saved_html = (directory / "report.html").read_text(encoding="utf-8")
    native_html = protocol.render(result)
    semantic = assert_semantic_html_equal(native_html, saved_html)
    native_report_status = ("PASS_BYTE_IDENTICAL_REPORT" if native_html == saved_html
                            else "FAIL_REPORT_RESULT_MISMATCH")
    wal = directory / "research.sqlite3-wal"
    if wal.exists() and wal.stat().st_size != 0:
        raise EvidenceMismatch("REFUSE_COPY_OF_UNCHECKPOINTED_WAL")
    ledger_hash = before["research.sqlite3"]
    try:
        with tempfile.TemporaryDirectory(prefix="d2-evidence-immutable-") as temp:
            snapshot = Path(temp) / "research.sqlite3"
            shutil.copyfile(directory / "research.sqlite3", snapshot)
            if _sha(snapshot) != ledger_hash:
                raise EvidenceMismatch("IMMUTABLE_SNAPSHOT_BYTE_COPY_MISMATCH")
            with presentation_adapter(protocol, directory, snapshot, result, saved_html) as calls:
                verification = protocol.verify(directory)
            if calls["validated_render_calls"] != 1 or calls["immutable_ledger_reads"] < 1:
                raise EvidenceMismatch("ORIGINAL_VERIFIER_DID_NOT_USE_REQUIRED_CHECKS")
            if _sha(snapshot) != ledger_hash or list(Path(temp).iterdir()) != [snapshot]:
                raise EvidenceMismatch("IMMUTABLE_SNAPSHOT_OR_SIDECARS_CHANGED")
    finally:
        after = _input_manifest(directory)
        source_after = protocol.source_manifest()
        if before != after:
            raise EvidenceMismatch("FROZEN_STUDY_BYTES_CHANGED_DURING_VERIFICATION")
        if source_before != source_after:
            raise EvidenceMismatch("PINNED_EXPERIMENT_SOURCE_CHANGED_DURING_VERIFICATION")
    answer = {
        "schema": "D2_FORENSICS_SEMANTIC_PRESENTATION_VERIFICATION_1",
        "status": "PASS_SEMANTIC_PRESENTATION_ADAPTER_WITH_NATIVE_INTEGRITY_CHECKS",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "study": str(directory),
        "native_report_check": {"status": native_report_status,
            "original_error": "REPORT_RESULT_MISMATCH" if native_html != saved_html else None,
            "native_render_sha256": hashlib.sha256(native_html.encode("utf-8")).hexdigest(),
            "saved_report_sha256": before["report.html"],
            "native_verification_rerun": False,
            "scope": "Exact original report-byte predicate recomputed; no cached execute or experiment rerun"},
        "original_native_failure_retained": True,
        "semantic_presentation": semantic, "original_verifier_result": verification,
        "adapter_calls": calls, "all_study_files_byte_unchanged": before == after,
        "study_sha256_before": before, "study_sha256_after": after,
        "pinned_source_count": len(source_before), "pinned_source_sha256": source_before,
        "pinned_source_unchanged": source_before == source_after,
        "ledger_snapshot": {"sha256": ledger_hash, "byte_copy": True,
                            "sqlite_uri": "mode=ro&immutable=1", "original_sqlite_opened": False,
                            "temporary_snapshot_removed": True},
        "adapter_source_sha256": _sha(__file__),
        "experiment_rerun": False, "study_files_rewritten": False,
        "original_failure_cause": "UNRESOLVED", "formal_A": 0, "decision": "NO_EDGE",
    }
    with receipt.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(answer, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return answer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    answer = verify_study(args.output, args.receipt)
    print(json.dumps({key: answer[key] for key in ("status", "native_report_check",
                     "all_study_files_byte_unchanged", "pinned_source_count", "formal_A", "decision")},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
