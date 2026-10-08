"""Parse BSE native securityinfo stock class without pretending to have PIT history.

BSE/NEEQ 2023 data-file interface, §3.1 bj_securityinfo_YYYYMMDD.xml:
SecurityIDSource=106 and SecurityType=1 denote BSE listed continuous
auction equities; Type=2/3 are NEEQ stocks, NOT BSE listed stocks.
The 2025 V1.0 notice explicitly scopes newer interfaces to bonds only.
No participant-gateway credentials/historical native bytes are available here.
A synthetically made XML fixture is only for regression tests.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NAME = re.compile(r"^bj_securityinfo_(\d{8})\.xml$")
CODE = re.compile(r"^(?:[48]\d{5}|92\d{4})$")
CODE_SIX = re.compile(r"^\d{6}$")
XML_HEAD = re.compile(rb"^<\?xml\s+[^?]*encoding\s*=\s*['\"]([A-Za-z0-9_-]+)['\"][^?]*\?>", re.I)
MIN_SPEC_DATE = date(2023, 9, 15)
MARKET_START = date(2021, 11, 15)
MAX_RAW = 20_000_000
REQUIRED = ("SecurityID", "SecurityIDSource", "SecurityType", "ListDate", "Symbol")
BSE_EQUITY_TYPE = "1"
NON_BSE_NEEQ_TYPES = {"2", "3"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_json(data) -> str:
    return sha(json.dumps(data, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


def _day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise ValueError("invalid official native YYYYMMDD day")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError as e:
        raise ValueError("impossible official native calendar date") from e


def _tag(tag: str) -> str:
    return tag.split("}", 1)[-1]


def parse(raw: bytes, filename: str, *, acquired_at_utc: str) -> dict:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RAW:
        raise ValueError("native raw bytes absent or oversized")
    match = NAME.fullmatch(filename)
    if not match:
        raise ValueError("unexpected BSE native filename")
    native_day = _day(match.group(1))
    if native_day < MARKET_START:
        raise ValueError("snapshot before BSE market existed")
    if native_day < MIN_SPEC_DATE:
        raise ValueError("2023 native schema not established for prior dates")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("external/entity declarations forbidden")
    header = XML_HEAD.match(raw[:256])
    if not header or header.group(1).upper().replace(b"-", b"") != b"GB18030":
        raise ValueError("native GB18030 XML declaration required")
    try:
        content = raw.decode("gb18030", errors="strict")
    except UnicodeError as e:
        raise ValueError("invalid native source GB18030 bytes") from e
    content = re.sub(r"^<\?xml\s+[^?]*\?>\s*", "", content, count=1)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError("malformed native XML") from e
    try:
        timestamp = datetime.fromisoformat(acquired_at_utc.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as e:
        raise ValueError("acquisition timestamp invalid") from e
    if timestamp.tzinfo is None:
        raise ValueError("acquisition timestamp must contain UTC offset")
    timestamp = timestamp.astimezone(timezone.utc)
    if timestamp.year < 2023:
        raise ValueError("invalid receipt timestamp preceding interface")
    # Exchange-local market day matters: offsets other than UTC can conceal
    # a future-dated file. This is ONLY a temporal consistency check; it
    # cannot prove independent first-party publication/receipt availability.
    exchange_receipt_day = timestamp.astimezone(
        timezone(timedelta(hours=8))
    ).date()
    if native_day > exchange_receipt_day:
        raise ValueError("BSE native snapshot day later than claimed exchange-local receipt day")
    nodes = [node for node in root.iter() if _tag(node.tag).lower() == "security"]
    if not nodes:
        raise ValueError("native XML has no security records")
    all_codes = set()
    stock = []
    neeq = []
    for n, node in enumerate(nodes):
        fields = {}
        for child in node:
            name = _tag(child.tag)
            if name in fields:
                raise ValueError(f"duplicate native field {name} at record {n}")
            fields[name] = (child.text or "").strip()
        if not all(fields.get(field) for field in REQUIRED):
            raise ValueError(f"missing native field at record {n}")
        code = fields["SecurityID"]
        if not CODE_SIX.fullmatch(code) or code in all_codes:
            raise ValueError(f"invalid or repeated native security code {code}")
        all_codes.add(code)
        if fields["SecurityIDSource"] != "106":
            raise ValueError(f"non-BSE security-code source {code}")
        listing = _day(fields["ListDate"])
        if listing > native_day:
            raise ValueError(f"listing date later than snapshot {code}")
        security_type = fields["SecurityType"]
        record = {
            "code": code, "issuer_symbol": fields["Symbol"],
            "native_list_date": listing.isoformat(),
            "source_security_type": security_type,
            "snapshot_applicability_day": native_day.isoformat(),
            "native_row_sha256": sha_json({k: fields[k] for k in sorted(fields)}),
            "share_class_from_native_type_only": "NOT VERIFIED",
            "historical_lifecycle_qualified": "NOT VERIFIED",
            "daily_st_or_suspension_qualified": "NOT VERIFIED",
        }
        if security_type == BSE_EQUITY_TYPE:
            if not CODE.fullmatch(code):
                raise ValueError(f"BSE native listed equity code not eligible {code}")
            record["native_class"] = "BSE_LISTED_CONTINUOUS_AUCTION_STOCK_RECORD"
            stock.append(record)
        elif security_type in NON_BSE_NEEQ_TYPES:
            record["native_class"] = "NEEQ_STOCK_EXCLUDED_FROM_BSE"
            neeq.append(record)
        else:
            # Do not label a bond, fund or undocumented type as an absent equity.
            raise ValueError(f"unsupported native security type for {code}")
    if not stock:
        raise ValueError("no BSE listed continuous-auction stock in snapshot")
    stock.sort(key=lambda row: row["code"])
    neeq.sort(key=lambda row: row["code"])
    return {
        "schema": "stock-bse-native-securityinfo-schema-observation-v1",
        "file_name": filename,
        "interface_authority": "BSE_NEEQ_2023_DATA_FILE_INTERFACE_SECTION_3_1",
        "snapshot_day_not_proof_of_actual_daily_trade": native_day.isoformat(),
        "observed_at_utc": timestamp.isoformat(),
        "raw_sha256": sha(raw), "raw_size_bytes": len(raw),
        "native_rows_all_types": len(nodes),
        "bse_listed_stock_rows": len(stock),
        "neeq_excluded_rows": len(neeq),
        "bse_equity": stock, "neeq_exclusions": neeq,
        "bse_equity_digest": sha_json(stock),
        "adjudication": {
            "native_structure_and_security_type_projection": "PASS",
            "original_first_party_gateway_provenance": "NOT VERIFIED",
            "historical_snapshot_availability": "NOT VERIFIED",
            "BSE_full_listing_delisting_universe": "NOT VERIFIED",
            "SSE_SZSE_BSE_full_daily_ST_suspension": "NOT VERIFIED",
            "official_effective_halt_resume": "NOT VERIFIED",
            "production_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--native-xml", type=Path, required=True)
    ap.add_argument("--receipt-utc", required=True)
    ap.add_argument("--out", type=Path, default=Path("bse_native_schema_diagnostic.json"))
    args = ap.parse_args()
    result = parse(args.native_xml.read_bytes(), args.native_xml.name,
                   acquired_at_utc=args.receipt_utc)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "native_records": result["native_rows_all_types"],
        "BSE_native_stock_rows": result["bse_listed_stock_rows"],
        "NEEQ_exclusions": result["neeq_excluded_rows"],
        "raw_sha256": result["raw_sha256"],
        "adjudication": result["adjudication"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
