from __future__ import annotations
from datetime import datetime, timezone
import json, os, subprocess, sys, tkinter as tk, traceback
from pathlib import Path
from tkinter import ttk
from .service import MasterService

class MasterUI:
    def __init__(self,service:MasterService):
        self.service=service; self.root=tk.Tk(); self.root.title("做自己主人 · V10 实证训练系统"); self.root.geometry("940x650"); self.status=tk.StringVar(value="READY")
        top=ttk.Frame(self.root,padding=10); top.pack(fill="x"); ttk.Label(top,text="真实问题").pack(side="left")
        self.problem=ttk.Entry(top,width=72); self.problem.insert(0,"我想改善一个反复出现的决策问题"); self.problem.pack(side="left",padx=8,fill="x",expand=True)
        row=ttk.Frame(self.root,padding=(10,0,10,10)); row.pack(fill="x"); self.buttons={}
        for label,fn in (("核心训练",self.on_core),("一键更新",self.on_update),("一键修复",self.on_repair),("高级分析",self.on_advanced)):
            b=ttk.Button(row,text=label,command=fn); b.pack(side="left",padx=4); self.buttons[label]=b
        ttk.Label(self.root,textvariable=self.status,padding=(10,0)).pack(fill="x")
        self.output=tk.Text(self.root,wrap="word",height=30); self.output.pack(fill="both",expand=True,padx=10,pady=10); self.output.insert("1.0","5 Why/逆转只用于提出和攻击假设；30/90天真实效果必须由实际数据裁决。\n"); self.output.configure(state="disabled")
        self.root.after(500,self._write_layout)
    def _write_layout(self):
        self.root.update_idletasks(); layout={"status":"PASS","pid":os.getpid(),"window_title":self.root.title(),"buttons":{}}
        for label,b in self.buttons.items(): layout["buttons"][label]={"center_x":b.winfo_rootx()+b.winfo_width()//2,"center_y":b.winfo_rooty()+b.winfo_height()//2,"width":b.winfo_width(),"height":b.winfo_height()}
        self.service.storage.atomic_json(self.service.storage.evidence/"ui_layout.json",layout)
    def _audit(self,action,status,payload):
        with (self.service.storage.evidence/"gui_actions.jsonl").open("a",encoding="utf-8") as f: f.write(json.dumps({"time":datetime.now(timezone.utc).isoformat(),"action":action,"status":status,"payload":payload},ensure_ascii=False,default=str)+"\n")
    def _run(self,action,fn):
        self.status.set(action+": RUNNING"); self.root.update_idletasks()
        try: result=fn(); status=str(result.get("status","PASS"))
        except Exception as exc: result={"status":"FAIL","error":repr(exc),"trace":traceback.format_exc(limit=5)}; status="FAIL"
        self.output.configure(state="normal"); self.output.delete("1.0","end"); self.output.insert("1.0",json.dumps(result,ensure_ascii=False,indent=2,default=str)); self.output.configure(state="disabled"); self._audit(action,status,result); self.status.set(action+": "+status)
    def _software_update(self):
        if getattr(sys,"frozen",False): updater=Path(sys.executable).with_name("BeYourOwnMasterUpdater.exe"); cmd=[str(updater),"--root",str(self.service.root)]
        else: updater=Path(__file__).resolve().parents[1]/"updater_main.py"; cmd=[sys.executable,str(updater),"--root",str(self.service.root)]
        if not updater.is_file(): return {"status":"FAIL","reason":"independent updater missing"}
        proc=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90); p=self.service.root/"updater_result.json"
        if not p.is_file(): return {"status":"FAIL","reason":"updater produced no evidence","returncode":proc.returncode}
        obj=json.loads(p.read_text(encoding="utf-8")); obj["independent_process_returncode"]=proc.returncode; obj["independent_updater_path"]=str(updater)
        if obj.get("status")=="BLOCKED" and proc.returncode!=3: raise RuntimeError("BLOCKED updater must rc=3")
        return obj
    def on_core(self): self._run("核心训练",lambda:self.service.core(self.problem.get()))
    def on_update(self): self._run("一键更新",self._software_update)
    def on_repair(self): self._run("一键修复",self.service.repair)
    def on_advanced(self): self._run("高级分析",self.service.advanced)
    def run(self): self.root.mainloop()
