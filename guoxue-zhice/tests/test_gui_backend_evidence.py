import copy
import os
import unittest
from unittest.mock import patch
from bind_physical_gui import LABELS, validate_gui

class GuiEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'GUOXUE_SOURCE_SHA':'a'*40, 'GITHUB_RUN_ID':'42', 'GITHUB_RUN_ATTEMPT':'1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        details = [
            {'action':'GOAL_ANALYSIS', 'result':{'methods':[1], 'five_whys':[1], 'reverse_validation':[1]}},
            {'action':'RELEASE_CONFIG_UNAVAILABLE', 'error':'RuntimeError: real software-update release config is unavailable; missing'},
            {'action':'REPAIR_COMPLETE', 'result':{'status':'PASS', 'checks':[['knowledge','PASS','verified']]}},
            {'action':'ADVANCED_ANALYSIS', 'stats':{'classics':15, 'analyses':1, 'reviews':0, 'disputed':1}},
        ]
        self.report = {'status':'PASS', 'github_sha':'a'*40, 'github_run_id':'42', 'github_run_attempt':'1',
            'exe_sha256_before':'b'*64, 'exe_sha256_after':'b'*64, 'gui_mode':'BlockedRelease', 'buttons':[]}
        for i, label in enumerate(LABELS):
            self.report['buttons'].append({'button_index':i+1, 'label':label, 'status':'PASS', 'visual_changed':True,
                'before_sha256':'c'*64, 'after_sha256':'d'*64, 'backend':{'schema':'guoxue-gui-operation-v1',
                'label':label, 'status':'BLOCKED' if i == 1 else 'PASS', 'frozen':True, 'pid':11,
                'nonce':'e'*32, 'exe_sha256':'b'*64, 'github_sha':'a'*40, 'github_run_id':'42',
                'github_run_attempt':'1', 'detail':details[i]}})

    def test_blocked_release_is_only_staging_gui_proof(self):
        self.assertTrue(validate_gui(self.report, 'b'*64))
        self.assertFalse(validate_gui(self.report, 'b'*64, full_release=True))

    def test_empty_or_false_backend_rejected_despite_four_visible_clicks(self):
        for index in range(4):
            candidate = copy.deepcopy(self.report)
            candidate['buttons'][index]['backend']['detail'] = {}
            self.assertFalse(validate_gui(candidate, 'b'*64))

    def test_stale_or_different_executable_rejected(self):
        for key, value in [('github_sha','f'*40), ('github_run_id','41'), ('exe_sha256','f'*64), ('frozen',False)]:
            candidate = copy.deepcopy(self.report)
            candidate['buttons'][2]['backend'][key] = value
            self.assertFalse(validate_gui(candidate, 'b'*64))

    def test_configured_handoff_requires_success_and_real_process(self):
        candidate = copy.deepcopy(self.report)
        candidate['gui_mode'] = 'ConfiguredRelease'
        candidate['buttons'][1]['backend']['status'] = 'PASS'
        candidate['buttons'][1]['backend']['detail'] = {'action':'UPDATER_HANDOFF','updater_pid':22}
        self.assertTrue(validate_gui(candidate, 'b'*64, full_release=True))
        candidate['buttons'][1]['backend']['detail']['updater_pid'] = None
        self.assertFalse(validate_gui(candidate, 'b'*64, full_release=True))

    def test_no_visual_change_rejected(self):
        self.report['buttons'][0]['after_sha256'] = 'c'*64
        self.assertFalse(validate_gui(self.report, 'b'*64))

if __name__ == '__main__':
    unittest.main()
