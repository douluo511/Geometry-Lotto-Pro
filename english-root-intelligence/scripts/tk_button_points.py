from __future__ import annotations
import argparse, importlib, sys
from pathlib import Path

def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--project-path", required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--entry", required=True)
    p.add_argument("--labels", required=True)
    p.add_argument("--out", required=True)
    args=p.parse_args()
    labels=args.labels.split(";")
    if len(labels)!=4:
        raise SystemExit("exactly four labels required")
    sys.path.insert(0, str(Path(args.project_path).resolve()))
    import tkinter as tk
    captured={"done":False}
    original=tk.Misc.mainloop

    def fake_mainloop(self, *a, **kw):
        root=self._root()
        root.update_idletasks(); root.update()
        rx, ry=root.winfo_rootx(), root.winfo_rooty()
        rw, rh=root.winfo_width(), root.winfo_height()
        found={}
        for w in walk(root):
            try:
                text=str(w.cget("text"))
            except Exception:
                continue
            if text in labels and text not in found:
                w.update_idletasks()
                found[text]=(
                    (w.winfo_rootx()+w.winfo_width()/2-rx)/rw,
                    (w.winfo_rooty()+w.winfo_height()/2-ry)/rh,
                )
        missing=[x for x in labels if x not in found]
        if missing:
            raise RuntimeError("missing buttons: "+repr(missing))
        points=";".join(f"{found[x][0]:.6f},{found[x][1]:.6f}" for x in labels)
        Path(args.out).write_text(points,encoding="utf-8")
        captured["done"]=True
        root.destroy()
        return 0

    tk.Misc.mainloop=fake_mainloop
    old_argv=sys.argv[:]
    sys.argv=[args.module]
    try:
        mod=importlib.import_module(args.module)
        target=getattr(mod,args.entry)
        result=target()
        if isinstance(result, tk.Misc) and not captured["done"]:
            result.mainloop()
    except SystemExit as exc:
        if exc.code not in (None,0):
            raise
    finally:
        sys.argv=old_argv
        tk.Misc.mainloop=original
    if not captured["done"]:
        raise SystemExit("mainloop was not reached")
    print(Path(args.out).read_text(encoding="utf-8"))

if __name__=="__main__":
    main()
