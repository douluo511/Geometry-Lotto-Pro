"""Local deterministic graph CLI. Never starts a paid model or sends mail."""
import argparse
from pathlib import Path
import json,sqlite3,tempfile,shutil

from .journal import GraphBlocked,canonical,checked
from .runtime import GraphRunner,write_new,error_code
from .settings import BOUNDARY,STAGES,sha


def inspect_run(root,thread_id):
    """Read a quiescent journal byte-copy, never the original SQLite handle."""
    root=Path(root).resolve();source=root/'evidence.sqlite3'
    if not source.is_file():raise GraphBlocked('GRAPH_JOURNAL_NOT_FOUND')
    wal=root/'evidence.sqlite3-wal'
    if wal.exists() and wal.stat().st_size:raise GraphBlocked('INSPECT_REQUIRES_QUIESCENT_CHECKPOINTED_JOURNAL')
    before=sha(source)
    with tempfile.TemporaryDirectory(prefix='graph-inspect-') as temp:
        copy=Path(temp)/'evidence.sqlite3';shutil.copyfile(source,copy)
        if sha(copy)!=before:raise GraphBlocked('INSPECT_COPY_MISMATCH')
        db=sqlite3.connect(copy.as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            records={(kind,key):checked((payload,checksum)) for kind,key,payload,checksum in db.execute('SELECT kind,key,payload,sha256 FROM events')}
        finally:db.close()
    if sha(source)!=before:raise GraphBlocked('JOURNAL_CHANGED_DURING_INSPECTION')
    header=records.get(('run',thread_id))
    if header is None:raise GraphBlocked('GRAPH_THREAD_NOT_FOUND')
    steps=[stage for stage in STAGES[:-1] if ('step',thread_id+'|'+stage) in records]
    return dict(status='READONLY_JOURNAL_SNAPSHOT_NOT_FULL_REVERIFICATION',thread_id=thread_id,
        recorded_terminal=records.get(('terminal',thread_id)),completed_stages=steps,
        next_required_stage_by_journal=next((stage for stage in STAGES if stage not in steps),'gate'),
        journal_sha256=before,original_sqlite_opened=False,**BOUNDARY)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name in ('start','resume'):
        ap=sub.add_parser(name);ap.add_argument('--config',type=Path,required=True);ap.add_argument('--thread',required=True)
        ap.add_argument('--parent');ap.add_argument('--stop-after',choices=STAGES[:-1])
        ap.add_argument('--receipt',type=Path,help='Optional new external invocation receipt')
    ap=sub.add_parser('inspect');ap.add_argument('--root',type=Path,required=True);ap.add_argument('--thread',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='inspect':answer=inspect_run(args.root,args.thread)
        else:
            if not args.config.is_absolute():raise GraphBlocked('ABSOLUTE_CONFIG_REQUIRED')
            config=json.loads(args.config.read_bytes())
            runner=GraphRunner(config,args.thread,parent_thread_id=args.parent)
            destination=None
            if args.receipt:
                if not args.receipt.is_absolute():raise GraphBlocked('ABSOLUTE_RECEIPT_REQUIRED')
                destination=args.receipt.resolve()
                if destination.exists():raise GraphBlocked('NEW_INVOCATION_RECEIPT_REQUIRED')
                pinned=[v for pair in runner.config['sources'].values() for v in pair]
                pinned.extend(runner.config['host']['history'].values())
                if any(destination.is_relative_to(Path(v['path']).resolve().parent) for v in pinned):raise GraphBlocked('RECEIPT_MUST_NOT_WRITE_INPUT_TREE')
                if destination.is_relative_to(runner.root):raise GraphBlocked('INVOCATION_RECEIPT_MUST_BE_EXTERNAL')
            answer=runner.run(resume=args.command=='resume',stop_after=args.stop_after)
            if destination is not None:write_new(destination,answer)
        print(canonical(answer));return 0 if answer['status'] in ('COMPLETED_RESEARCH_ONLY','PAUSED_CHECKPOINT','READONLY_JOURNAL_SNAPSHOT_NOT_FULL_REVERIFICATION') else 2
    except Exception as exc:
        print(canonical(dict(status='BLOCKED',reason=error_code(exc),error=type(exc).__name__,**BOUNDARY)));return 2


if __name__=='__main__':raise SystemExit(main())
