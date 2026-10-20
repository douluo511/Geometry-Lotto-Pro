"""Run current old and graph suites; preserve exact source and lock hashes."""
from pathlib import Path
import hashlib
from research.ssq_dlt_d2_forensics import acceptance as frozen

NAMES=('ssq_dlt_d2_v44','ssq_dlt_v45','ssq_dlt_agent_v1','ssq_dlt_d2_next',
       'ssq_dlt_d2_forensics','ssq_dlt_d2_forensics_evidence','ssq_dlt_agent_graph')

def manifest():
    root=Path(__file__).resolve().parents[2];result={}
    for name in NAMES:
        for path in sorted((root/'research'/name).rglob('*')):
            if path.is_file() and not {'__pycache__','evidence'}.intersection(path.parts):
                if path.suffix in ('.py','.ps1','.xml','.md','.txt','.json','.yml','.yaml','.lock') or path.name=='.gitattributes':
                    result[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for relative in ('.github/workflows/ssq-dlt-d2-forensics.yml',
                     '.github/workflows/ssq-dlt-agent-graph.yml','.github/workflows/.gitattributes'):
        path=root/relative
        result[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def main(argv=None):
    frozen.NAMES=NAMES
    frozen.manifest=manifest
    return frozen.main(argv)

if __name__=='__main__':raise SystemExit(main())
