from __future__ import annotations
import json, os, time, tkinter as tk
from .service import Service
from .storage import data_root, atomic_json

TITLE="Earth Online · Life Base · Reauthored Candidate"

class UI:
    def __init__(self):
        self.root=tk.Tk(); self.root.title(TITLE); self.root.geometry("760x430")
        self.service=Service(); self.status=tk.StringVar(value="Ready")
        tk.Label(self.root,text="Earth Online · 人生底层系统",font=("Segoe UI",18,"bold")).pack(pady=18)
        tk.Label(self.root,text="事实 → 证据 → 五维 → 5 Why → 逆转验证 → 小步行动 → 复盘").pack()
        frame=tk.Frame(self.root); frame.pack(pady=36)
        self.buttons={}
        actions=[("决策训练",self.core),("一键更新",self.update),("一键修复",self.repair),("高级分析",self.advanced)]
        for i,(label,fn) in enumerate(actions):
            b=tk.Button(frame,text=label,width=16,height=3,command=fn); b.grid(row=0,column=i,padx=8); self.buttons[label]=b
        tk.Label(self.root,textvariable=self.status,wraplength=700,justify="left").pack(pady=16)
        self.root.after(300,self.publish_layout)

    def invoke(self,name,fn):
        try:
            out=fn(); self.status.set(f'{name}: {out.get("status")} · '+json.dumps(out,ensure_ascii=False)[:360])
        except Exception as exc:
            self.status.set(f"{name}: FAIL · {type(exc).__name__}: {exc}")
        self.publish_layout()

    def core(self): self.invoke("决策训练",self.service.core)
    def update(self): self.invoke("一键更新",self.service.update)
    def repair(self): self.invoke("一键修复",self.service.repair)
    def advanced(self): self.invoke("高级分析",self.service.advanced)

    def publish_layout(self):
        try:
            self.root.update_idletasks()
            buttons={}
            for label,b in self.buttons.items():
                buttons[label]={"x":b.winfo_rootx()+b.winfo_width()//2,"y":b.winfo_rooty()+b.winfo_height()//2,
                                "state":str(b["state"])}
            atomic_json(data_root()/"evidence"/"ui_layout.json",
                        {"schema":"earth-online-live-tk-layout-v1","recorded_at":time.time(),"pid":os.getpid(),
                         "window_title":TITLE,"buttons":buttons})
        except Exception: pass

    def run(self): self.root.mainloop()
