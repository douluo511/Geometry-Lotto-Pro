from pathlib import Path
import argparse, json, sys

from talkcraft.service.training_service import TrainingService
from talkcraft.service.self_test import run_self_test

BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))

class TalkCraftApp:
    def __init__(self):
        from talkcraft.ui.main_window import MainWindow
        self.window=MainWindow(TrainingService(BASE))
        self.root=self.window.root
        self.buttons=self.window.buttons

    def run(self):
        self.window.run()


def run_gui():
    TalkCraftApp().run()


def gui_smoke():
    app=TalkCraftApp()
    try:
        app.root.update_idletasks()
        labels=[str(b.cget("text")) for b in app.buttons]
        expected=["今日训练","一键更新","一键修复","高级分析"]
        checks={
            "window_exists":bool(app.root.winfo_exists()),
            "button_count":len(app.buttons)==4,
            "button_labels":labels==expected,
        }
        return {"ok":all(checks.values()),"checks":checks,"labels":labels}
    finally:
        try:
            app.root.destroy()
        except Exception:
            pass


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--gui-smoke',action='store_true')
    p.add_argument('--repair',action='store_true')
    p.add_argument('--update',action='store_true')
    args=p.parse_args()
    if args.self_test:
        r=run_self_test(BASE); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 2)
    if args.gui_smoke:
        r=gui_smoke(); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 2)
    svc=TrainingService(BASE)
    if args.repair:
        r=svc.repair(); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 2)
    if args.update:
        r=svc.update_all_sources(); print(json.dumps(r,ensure_ascii=False)); raise SystemExit(0 if r['ok'] else 3)
    run_gui()

if __name__=='__main__':
    main()
