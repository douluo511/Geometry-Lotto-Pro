"""Offline source-native BSE membership contract; fixtures are NOT real files."""
import copy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bse_native", HERE / "stock_bse_native_securityinfo.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
STAMP = "2026-10-08T07:00:00+00:00"
NAME = "bj_securityinfo_20261008.xml"
cases = []


def xml(*records, encoding="GB18030", extra=""):
    fields = []
    for code, kind, day, symbol, src in records:
        fields.append(
            "<security><SecurityID>"+code+"</SecurityID>"
            "<SecurityIDSource>"+src+"</SecurityIDSource>"
            "<SecurityType>"+kind+"</SecurityType>"
            "<ListDate>"+day+"</ListDate>"
            "<Symbol>"+symbol+"</Symbol>"+extra+"</security>"
        )
    payload='<?xml version="1.0" encoding="'+encoding+'"?>'
    payload+="<SecurityInfo>" + "".join(fields) + "</SecurityInfo>"
    return payload.encode("gb18030")


stock = ("920001", "1", "20240109", "北交示例一", "106")
stock2 = ("830002", "1", "20210115", "北交示例二", "106")
neeq = ("430003", "2", "20221220", "新三板挂牌股", "106")
neeq2 = ("830004", "3", "20221220", "创新层股份", "106")
normal = xml(stock, stock2, neeq, neeq2)


def pass_case(name, action):
    action()
    cases.append(name)


def reject_case(name, data=None, file=NAME, stamp=STAMP):
    try:
        m.parse(data if data is not None else normal, file, acquired_at_utc=stamp)
    except ValueError:
        cases.append(name)
        return
    raise AssertionError("FALSE PASS: " + name)


def check_normal():
    result = m.parse(normal, NAME, acquired_at_utc=STAMP)
    assert result["native_rows_all_types"] == 4
    assert result["bse_listed_stock_rows"] == 2
    assert result["neeq_excluded_rows"] == 2
    assert [r["code"] for r in result["bse_equity"]] == ["830002", "920001"]
    assert all(r["native_class"] == "NEEQ_STOCK_EXCLUDED_FROM_BSE" for r in result["neeq_exclusions"])
    assert result["raw_sha256"] == m.sha(normal)
    assert all(v == "NOT VERIFIED" for k, v in result["adjudication"].items()
               if k not in {"native_structure_and_security_type_projection", "final_gate"})
    assert result["adjudication"]["final_gate"] == "FAIL"
    assert result["adjudication"]["native_structure_and_security_type_projection"] == "PASS"


pass_case("positive BSE equities, NEEQ 2 and 3 excluded, no lifetime inference", check_normal)
pass_case("repeatable native evidence digest", lambda: (
    m.parse(normal, NAME, acquired_at_utc=STAMP)["bse_equity_digest"]
    == m.parse(normal, NAME, acquired_at_utc=STAMP)["bse_equity_digest"]
) or (_ for _ in ()).throw(AssertionError("nondeterministic source hash")))
reject_case("listed NEEQ stock not BSE stock", xml(neeq, neeq2))
reject_case("fake BSE source 102", xml(("920001", "1", "20240109", "证券", "102")))
reject_case("unsupported bond or fund code type cannot disappear silently", xml(stock, ("350001", "6", "20240109", "债券", "106")))
reject_case("equity type1 wrong listed code family", xml(("600001", "1", "20240109", "沪市股票", "106")))
reject_case("duplicate security identity prohibited", xml(stock, stock))
reject_case("invalid six-digit security code", xml(("92000", "1", "20240109", "证券", "106")))
reject_case("impossible date", xml(("920001", "1", "20240230", "证券", "106")))
reject_case("future listing date", xml(("920001", "1", "20270101", "证券", "106")))
reject_case("record missing stock class", xml(("920001", "", "20240109", "证券", "106")))
reject_case("record missing exchange identity", xml(("920001", "1", "20240109", "证券", "")))
reject_case("no records", xml())
reject_case("wrong filename", normal, file="bj_securityinfo_20261008_backup.xml")
reject_case("filename impossible date", normal, file="bj_securityinfo_20260230.xml")
reject_case("early pre-BSE snapshot date", normal, file="bj_securityinfo_20211114.xml")
reject_case("no proof 2023 spec governed 2021 snapshots", normal, file="bj_securityinfo_20211201.xml")
reject_case("timestamp must carry offset", normal, stamp="2026-10-08T07:00:00")
reject_case("unknown acquisition date", normal, stamp="unknown")
reject_case("non-GB declared charset", xml(stock, encoding="UTF-8"))
reject_case("malformed XML truncated", normal[:-20])
reject_case("untrusted external DTD", normal.replace(b"<SecurityInfo>", b'<!DOCTYPE a [<!ENTITY test "yes">]><SecurityInfo>'))
reject_case("duplicate native SecurityType tag", xml(stock, extra="<SecurityType>1</SecurityType>"))
reject_case("unsupported GB bytes", normal + b"\xff")
reject_case("empty raw response", b"")
assert len(cases) == 25, (len(cases), cases)
print("BSE NATIVE SECURITYINFO OFFLINE CONTRACTS 25/25 PASS")
