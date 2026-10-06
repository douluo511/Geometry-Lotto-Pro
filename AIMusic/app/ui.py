from __future__ import annotations
import json, os, tkinter as tk
from pathlib import Path
from .service import Service

TITLE="AI Music Production · Reauthored Candidate"

class UI:
    def __init__(self,root:Path|None=None):
        self.service=Service(root)
        self.win=tk.Tk(); self.win.title(TITLE); self.win.geometry("760x460")
        self.status=tk.StringVar(value="NEW_REAUTHORED_IMPLEMENTATION · Local composer only")
        tk.Label(self.win,text="AI Music Production System",font=("Segoe UI",18,"bold")).pack(pady=18)
        tk.Label(self.win,text="本地程序化作曲与外部 AI Provider 身份严格分离",font=("Segoe UI",11)).pack(pady=4)
        frame=tk.Frame(self.win); frame.pack(pady=28)
        self.buttons={}
        specs=[
            ("创作音乐",self.compose),
            ("一键更新",self.update),
            ("一键修复",self.repair),
            ("高级分析",self.advanced),
        ]
        for i,(label,cmd) in enumerate(specs):
            b=tk.Button(frame,text=label,width=18,height=2,command=cmd)
            b.grid(row=i//2,column=i%2,padx=16,pady=12)
            self.buttons[label]=b
        tk.Label(self.win,textvariable=self.status,wraplength=700,justify="left").pack(pady=16)
        self.win.after(250,self.publish_layout)

    def _set(self,label:str,out:dict):
        self.status.set(label+" → "+json.dumps(out,ensure_ascii=False)[:520])

    def compose(self): self._set("创作音乐",self.service.compose())
    def update(self): self._set("一键更新",self.service.update())
    def repair(self): self._set("一键修复",self.service.repair())
    def advanced(self): self._set("高级分析",self.service.advanced())

    def publish_layout(self):
        try:
            self.win.update_idletasks()
            data={"status":"PASS","pid":os.getpid(),"title":TITLE,"buttons":{}}
            for label,b in self.buttons.items():
                data["buttons"][label]={
                    "center_x":b.winfo_rootx()+b.winfo_width()//2,
                    "center_y":b.winfo_rooty()+b.winfo_height()//2,
                    "state":str(b["state"]),
                }
            p=self.service.storage.evidence/"ui_layout.json"
            p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        finally:
            self.win.after(1000,self.publish_layout)

    def run(self): self.win.mainloop()
