"""Explicitly synthetic legal draw fixtures; never official evidence or forecasts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from research.ssq_dlt_agent_graph.tests.test_host import NOW, fixture_config as native_fixture_config


def pin(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def graph_fixture_config(root, *, limits=None):
    """Sixty fabricated draws per game encoded in the actual four parser formats."""
    root = Path(root).resolve()
    host = native_fixture_config(root)
    state = root / 'graph-state'
    host['state_dir'] = str(state / 'host')
    sources = {}
    for game in ('SSQ', 'DLT'):
        rows = json.loads(Path(host['history'][game]['path']).read_bytes())['draws']
        if game == 'SSQ':
            document = dict(state=0, result=[dict(code=r['issue'], date=r['draw_date'],
                red=','.join(str(n) for n in r['front']), blue=str(r['back'][0])) for r in rows])
            html = '<table>' + ''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                r['issue'], r['draw_date'], ' '.join(f'{n:02}' for n in r['front']),
                f"{r['back'][0]:02}") for r in rows) + '</table>'
        else:
            document = dict(success=True, value=dict(list=[dict(lotteryDrawNum=r['issue'],
                lotteryDrawTime=r['draw_date'], lotteryDrawResult=' '.join(
                    f'{n:02}' for n in r['front'] + r['back'])) for r in rows]))
            html = '<table>' + ''.join('<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                r['draw_date'], r['issue'], ' '.join(f'{n:02}' for n in r['front'] + r['back']))
                for r in rows) + '</table>'
        paths = [root / 'inputs' / (game + '-synthetic-national.json'),
                 root / 'inputs' / (game + '-synthetic-provincial.html')]
        paths[0].write_text(json.dumps(document, sort_keys=True), encoding='utf-8')
        paths[1].write_text(html, encoding='utf-8')
        sources[game] = [pin(path) for path in paths]
    return dict(root=str(state), host=host, sources=sources,
                memory_queries=[], limits=deepcopy(limits or dict(max_stage_calls=12,
                                                               max_wall_seconds=1800)))
