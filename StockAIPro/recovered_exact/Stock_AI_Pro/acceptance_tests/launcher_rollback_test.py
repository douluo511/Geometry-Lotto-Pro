import json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import launcher

class DeadProc:
    def poll(self):return 1
    def terminate(self):pass
    def wait(self):return 1

with tempfile.TemporaryDirectory() as td:
    r=Path(td);(r/'versions'/'4.3.0').mkdir(parents=True);(r/'versions'/'4.2.0').mkdir(parents=True);(r/'staging').mkdir()
    for v in ['4.3.0','4.2.0']:(r/'versions'/v/'app.py').write_text('')
    (r/'current.json').write_text(json.dumps({'active_version':'4.3.0','previous_version':'4.2.0','pending_health':True,'pending_release_id':'bad-430','failed_release_ids':[]}))
    calls=iter([False,True])
    with patch.object(launcher,'ROOT',r),patch.object(launcher,'port_open',side_effect=lambda *a,**k:next(calls)),patch.object(launcher.subprocess,'Popen',return_value=DeadProc()),patch.object(launcher,'ensure_version_env',return_value=Path(sys.executable)),patch.object(launcher,'run_health',return_value=True),patch.object(launcher.webbrowser,'open',return_value=True):
        rc=launcher.start_ui('4.3.0',Path(sys.executable),True)
    cur=json.loads((r/'current.json').read_text())
    assert rc==0 and cur['active_version']=='4.2.0' and cur['pending_health'] is False and 'bad-430' in cur['failed_release_ids']
print('LAUNCHER UI FAILURE AUTO-ROLLBACK TEST PASS')
