"""Real bounded network capture, with no promotion or prediction side effects."""
import argparse
import concurrent.futures
import json
from pathlib import Path

from .network import AnySearchDiscovery, fetch_official

TARGETS = (
    ("SSQ", "national", "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq&issueCount=1"),
    ("SSQ", "shanghai", "https://www.swlc.net.cn/lottery/ssq.html"),
    ("DLT", "national", "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&provinceId=0&pageSize=1&isVerify=1&pageNo=1"),
    ("DLT", "jiangsu", "https://api.js-lottery.com/wfzq/dlt/data"),
)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--discovery-tools",action="store_true",
                        help="Actually probe the discovered search, batch_search and extract tools without credentials")
    args=parser.parse_args(argv)
    args.output.mkdir(parents=True,exist_ok=False)
    def official(target):
        game,name,url=target
        try:
            body,receipt=fetch_official(game,url,attempts=1,timeout=5)
            filename=f"{game}_{name}_{receipt['sha256']}.bin"
            (args.output/filename).write_bytes(body)
            return dict(game=game,source=name,status="HTTP_CAPTURE_ONLY",raw=filename,**receipt)
        except Exception as exc:
            return dict(game=game,source=name,url=url,status="BLOCKED",reason=str(exc),exception=type(exc).__name__)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records=list(pool.map(official,TARGETS))
    try:
        client=AnySearchDiscovery()
        discovery=client.rpc("initialize",dict(protocolVersion="2024-11-05",capabilities={},clientInfo=dict(name="GLP-V44-source-discovery",version="0.1")))
        anysearch=dict(status="INITIALIZE_ONLY",authenticated=False,search="NOT_RUN",batch_search="NOT_RUN",extract="NOT_RUN",**discovery)
        if args.discovery_tools:
            listed=client.rpc("tools/list",{},2)
            (args.output/"anysearch_tools.json").write_text(json.dumps(listed,ensure_ascii=False,indent=2),encoding="utf-8")
            actions=(
                ("search",{"query":"site:cwl.gov.cn SSQ official draw results","max_results":2}),
                ("batch_search",{"queries":[{"query":"site:cwl.gov.cn SSQ official draw results","max_results":2},
                                             {"query":"site:lottery.gov.cn DLT official draw results","max_results":2}]}),
                ("extract",{"url":"https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"}),
            )
            def call_tool(item):
                index,(name,arguments)=item
                try:
                    result=client.rpc("tools/call",dict(name=name,arguments=arguments),index+3)
                    value=result["result"]
                    status="APPLICATION_ERROR" if type(value) is dict and value.get("isError") is True else "DISCOVERY_RESPONSE_ONLY"
                    (args.output/f"anysearch_{name}.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                    return name,status
                except Exception as exc:
                    (args.output/f"anysearch_{name}.json").write_text(json.dumps(dict(status="BLOCKED",reason=str(exc)),indent=2),encoding="utf-8")
                    return name,"BLOCKED"
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                outcomes=dict(pool.map(call_tool,enumerate(actions)))
            anysearch.update(outcomes,status="DISCOVERY_TOOLS_PROBED",authentication="NO_CREDENTIALS_SUPPLIED")
    except Exception as exc:
        anysearch=dict(status="BLOCKED",authenticated=False,reason=str(exc),exception=type(exc).__name__,
                       search="NOT_RUN",batch_search="NOT_RUN",extract="NOT_RUN")
    report=dict(scope="REAL_NETWORK_PROBE_ONLY",sources=records,AnySearch=anysearch,
                as_of_verified=False,official_two_source_draw_admission="BLOCKED",
                R2="BLOCKED",formal_A=0,decision="NO_EDGE")
    (args.output/"network_probe.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(dict(sources=[dict(game=r["game"],source=r["source"],status=r["status"]) for r in records],
                         AnySearch={key:anysearch[key] for key in ("status","search","batch_search","extract")},
                         R2="BLOCKED",formal_A=0,decision="NO_EDGE")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
