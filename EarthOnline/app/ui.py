from __future__ import annotations
from datetime import datetime,timezone
import json,os,subprocess,sys,tkinter as tk,traceback
from pathlib import Path
from tkinter import ttk
from .service import EarthService
class UI:
    def __init__(self,service:EarthService):
        self.service=service;self.root=tk.Tk();self.root.title("地球 Online · 人生底层系统");self.root.geometry("960x670");self.status=tk.StringVar(value="READY")
        top=ttk.Frame(self.root,padding=10);top.pack(fill="x");ttk.Label(top,text="现实问题").pack(side="left");self.problem=ttk.Entry(top,width=72);self.problem.insert(0,"我要做一个重要决定");self.problem.pack(side="left",padx=8,fill="x",expand=True)
        row=ttk.Frame(self.root,padding=(10,0,10,10));row.pack(fill="x");self.buttons={}
        for label,fn in (("决策训练",self.on_core),("一键更新",self.on_update),("一键修复",self.on_repair),("高级分析",self.on_advanced)):
            b=ttk.Button(row,text=label,command=fn);b.pack(side="left",padx=4);self.buttons[label]=b
        ttk.Label(self.root,textvariable=self.status,padding=(10,0)).pack(fill="x");self.out=tk.Text(self.root,wrap="word",height=31);self.out.pack(fill="both",expand=True,padx=10,pady=10)
        self.out.insert("1.0","事实与解释分离；古典文本用于训练视角，现代证据校验现实；高风险领域不替代专业意见。\n");self.out.configure(state="disabled");self.root.after(500,self._layout)
    def _layout(self):
        self.root.update_idletasks();o={"status":"PASS","pid":os.getpid(),"window_title":self.root.title(),"buttons":{}}
        for k,b in self.buttons.items():o["buttons"][k]={"center_x":b.winfo_rootx()+b.winfo_width()//2,"center_y":b.winfo_rooty()+b.winfo_height()//2,"width":b.winfo_width(),"height":b.winfo_height()}
        self.service.storage.atomic_json(self.service.storage.evidence/"ui_layout.json",o)
    def _audit(self,a,s,p):
        with (self.service.storage.evidence/"gui_actions.jsonl").open("a",encoding="utf-8") as f:f.write(json.dumps({"time":datetime.now(timezone.utc).isoformat(),"action":a,"status":s,"payload":p},ensure_ascii=False,default=str)+"\n")
    def _run(self,a,fn):
        self.status.set(a+": RUNNING");self.root.update_idletasks()
        try:r=fn();s=str(r.get("status","PASS"))
        except Exception as exc:r={"status":"FAIL","error":repr(exc),"trace":traceback.format_exc(limit=5)};s="FAIL"
        self.out.configure(state="normal");self.out.delete("1.0","end");self.out.insert("1.0",json.dumps(r,ensure_ascii=False,indent=2,default=str));self.out.configure(state="disabled");self._audit(a,s,r);self.status.set(a+": "+s)
    def _software_update(self):
        if getattr(sys,"frozen",False):up=Path(sys.executable).with_name("EarthOnlineUpdater.exe");cmd=[str(up),"--root",str(self.service.root)]
        else:up=Path(__file__).resolve().parents[1]/"updater_main.py";cmd=[sys.executable,str(up),"--root",str(self.service.root)]
        if not up.is_file():return {"status":"FAIL","reason":"independent updater missing"}
        p=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90);f=self.service.root/"updater_result.json"
        if not f.is_file():return {"status":"FAIL","reason":"updater evidence missing","returncode":p.returncode}
        r=json.loads(f.read_text(encoding="utf-8"));r["independent_process_returncode"]=p.returncode;r["independent_updater_path"]=str(up)
        if r.get("status")=="BLOCKED" and p.returncode!=3:raise RuntimeError("BLOCKED updater must rc=3")
        return r
    def on_core(self):self._run("决策训练",lambda:self.service.core(self.problem.get()))
    def on_update(self):self._run("一键更新",self._software_update)
    def on_repair(self):self._run("一键修复",self.service.repair)
    def on_advanced(self):self._run("高级分析",self.service.advanced)
    def run(self):self.root.mainloop()
