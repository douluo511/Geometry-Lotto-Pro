import pathlib, sys, tempfile, shutil, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from talkcraft.service.training_service import TrainingService

class IntegrationTests(unittest.TestCase):
    def test_training_evidence_storage_and_repair(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td); shutil.copytree(ROOT/"data",base/"data")
            svc=TrainingService(base)
            self.assertGreaterEqual(len(svc.engine.drills),180); self.assertGreaterEqual(len(svc.engine.cases),60)
            self.assertTrue(svc.daily()["task"]); self.assertTrue(svc.case()["boundary"])
            svc.analyze("昨天排队30分钟，本来以为很快，结果队伍像在原地修仙。我发现排队是一种时间教育。")
            a=svc.analytics(); self.assertEqual(a["count"],1); self.assertTrue(a["weakest"])
            self.assertTrue(svc.repair()["ok"])
            self.assertEqual(svc.store.integrity(),"ok")
if __name__=="__main__": unittest.main()
