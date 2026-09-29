from pathlib import Path
import argparse, json, sys
from talkcraft.service.training_service import TrainingService
from talkcraft.service.self_test import run_self_test

BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--self-test',action='store_true'); p.add_argument('--repair',action='store_true'); p.add_argument('--update',action='store_true'); args=p.parse_args()
    if args.self_test:
        r=run_self_test(BASE); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 2)
    svc=TrainingService(BASE)
    if args.repair:
        r=svc.repair(); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 2)
    if args.update:
        r=svc.update_all_sources(); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 3)
    from talkcraft.ui.main_window import MainWindow
    MainWindow(svc).run()
if __name__=='__main__': main()
