from __future__ import annotations
import json, sys, threading, tkinter as tk
from pathlib import Path
from tkinter import messagebox
from domain import APP_NAME, APP_VERSION
from service import GuoxueService, self_test
BG="#f4f7fb"; CARD="#ffffff"; BLUE="#2563eb"; TEXT="#172033"; MUTED="#667085"; BORDER="#dbe3ef"

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title(f"{APP_NAME} v{APP_VERSION}"); self.geometry("1040x760"); self.minsize(920,680); self.configure(bg=BG)
        self.service=GuoxueService(); self.status_var=tk.StringVar(value="系统就绪 · Service/Evidence 审计链已启用"); self.nav_labels=["目标推演","一键更新","一键复盘","高级分析"]; self._build(); self.show_goal()
    def _build(self):
        header=tk.Frame(self,bg=BG); header.pack(fill="x",padx=34,pady=(22,8))
        tk.Label(header,text="国学智策系统",bg=BG,fg=TEXT,font=("Microsoft YaHei UI",25,"bold")).pack(anchor="w")
        tk.Label(header,text="经典证据 × 目标推演 × 反例验证 × 行动复盘",bg=BG,fg=MUTED,font=("Microsoft YaHei UI",11)).pack(anchor="w")
        nav=tk.Frame(self,bg=BG); nav.pack(fill="x",padx=34,pady=(8,12))
        for i,(label,cmd) in enumerate([("目标推演",self.show_goal),("一键更新",self.run_update),("一键复盘",self.show_review),("高级分析",self.show_analysis)]):
            tk.Button(nav,text=label,command=cmd,bg=BLUE,fg="white",relief="flat",height=2,font=("Microsoft YaHei UI",11,"bold")).grid(row=i//2,column=i%2,sticky="ew",padx=6,pady=6)
        nav.grid_columnconfigure(0,weight=1); nav.grid_columnconfigure(1,weight=1)
        self.content=tk.Frame(self,bg=BG); self.content.pack(fill="both",expand=True,padx=34,pady=(0,12))
        bottom=tk.Frame(self,bg="#eaf0f8"); bottom.pack(fill="x",side="bottom")
        tk.Label(bottom,textvariable=self.status_var,bg="#eaf0f8",fg=MUTED).pack(side="left",padx=18,pady=7); tk.Label(bottom,text=f"v{APP_VERSION}",bg="#eaf0f8",fg=MUTED).pack(side="right",padx=18)
    def clear(self):
        for w in self.content.winfo_children(): w.destroy()
    def card(self,parent=None): return tk.Frame(parent or self.content,bg=CARD,highlightthickness=1,highlightbackground=BORDER)
    def show_goal(self):
        self.clear(); c=self.card(); c.pack(fill="both",expand=True)
        tk.Label(c,text="把经典变成可验证的现实分析工具",bg=CARD,fg=TEXT,font=("Microsoft YaHei UI",19,"bold")).pack(anchor="w",padx=26,pady=(24,6))
        row=tk.Frame(c,bg=CARD); row.pack(fill="x",padx=26,pady=18); self.goal_entry=tk.Entry(row,font=("Microsoft YaHei UI",13)); self.goal_entry.pack(side="left",fill="x",expand=True,ipady=9); self.goal_entry.insert(0,"我要和长期合作伙伴谈价格，怎样判断底线、筹码和风险？")
        tk.Button(row,text="开始推演",command=self.analyze_goal,bg=BLUE,fg="white",relief="flat",padx=18,pady=8).pack(side="left",padx=(10,0))
        self.result=tk.Text(c,wrap="word",bg="#fbfcff",fg=TEXT,relief="flat",padx=16,pady=14,font=("Microsoft YaHei UI",10)); self.result.pack(fill="both",expand=True,padx=26,pady=(0,24)); self.result.insert("1.0","输入目标后点击“开始推演”。")
    def analyze_goal(self):
        try:r=self.service.analyze_goal(self.goal_entry.get())
        except Exception as exc: messagebox.showerror("推演失败",str(exc)); return
        lines=[f"目标：{r['goal']}",f"识别场景：{' / '.join(r['scenarios'])}","","① 先问事实，不先套经典"]+[f"  • {x}" for x in r["questions"]]+["","② 多经典交叉推演"]
        for i,m in enumerate(r["methods"],1): lines += [f"  {i}. 《{m['title']}》｜{m['method']}",f"     用法：{m['prompt']}",f"     来源：{m['source_note']}",f"     边界：{m['boundary']}"]
        lines += ["","③ 5 Why"]+[f"  • {x}" for x in r["five_whys"]]+["","④ 逆转验证"]+[f"  • {x}" for x in r["reverse_validation"]]+["",f"状态：{r['status']}",f"提示：{r['note']}"]
        self.result.delete("1.0","end"); self.result.insert("1.0","\n".join(lines)); self.status_var.set("推演完成 · 已写入 Evidence 审计链")
    def run_update(self): self.status_var.set("正在真实联网并校验…"); threading.Thread(target=self._update_worker,daemon=True).start()
    def _update_worker(self):
        try:
            r=self.service.one_click_update(); self.after(0,lambda:messagebox.showinfo("一键更新 PASS",f"版本：{r['version']}\n条目：{r['classics']}\nHTTP：{r['http_status']}\nSHA256：{r['sha256'][:20]}…")); self.after(0,lambda:self.status_var.set("一键更新 PASS · 证据已记录"))
        except Exception as exc: self.after(0,lambda:messagebox.showerror("一键更新失败",str(exc))); self.after(0,lambda:self.status_var.set("一键更新 FAIL · 旧库保持不变"))
    def show_review(self):
        self.clear(); c=self.card(); c.pack(fill="both",expand=True); self.review_boxes=[]
        for i,(label,default) in enumerate(zip(["当时目标","实际行动","实际结果","下次教训"],["谈合作时守住利润并保持长期关系","先问对方预算与替代方案，再报价","",""])):
            tk.Label(c,text=label,bg=CARD,fg=TEXT,font=("Microsoft YaHei UI",10,"bold")).grid(row=i,column=0,sticky="nw",padx=18,pady=10); box=tk.Text(c,height=3,wrap="word"); box.grid(row=i,column=1,sticky="ew",padx=(0,18),pady=7); box.insert("1.0",default); self.review_boxes.append(box)
        c.grid_columnconfigure(1,weight=1); tk.Button(c,text="保存复盘",command=self.save_review,bg=BLUE,fg="white",relief="flat").grid(row=4,column=1,sticky="e",padx=18,pady=16)
    def save_review(self):
        try: item=self.service.save_review(*[b.get("1.0","end").strip() for b in self.review_boxes]); messagebox.showinfo("复盘已保存",item["timestamp"])
        except Exception as exc: messagebox.showerror("保存失败",str(exc))
    def show_analysis(self):
        self.clear(); s=self.service.stats(); c=self.card(); c.pack(fill="x")
        text=f"经典条目：{s['classics']}\n目标推演：{s['analyses']}\n行动复盘：{s['reviews']}\nEvidence：{s['evidence_events']}\n上次更新：{s['last_update']}"
        tk.Label(c,text=text,bg=CARD,fg=TEXT,justify="left",font=("Microsoft YaHei UI",12)).pack(anchor="w",padx=18,pady=18); tk.Button(c,text="一键修复",command=self.run_repair,bg=BLUE,fg="white",relief="flat").pack(anchor="w",padx=18,pady=(0,18))
    def run_repair(self):
        try:
            r=self.service.one_click_repair()
            if r["status"]!="PASS": raise RuntimeError(str(r))
            messagebox.showinfo("一键修复 PASS",json.dumps(r["checks"],ensure_ascii=False,indent=2))
        except Exception as exc: messagebox.showerror("一键修复 FAIL",str(exc))

def gui_smoke():
    app=App(); app.withdraw(); app.update_idletasks(); checks={"title":APP_NAME in app.title(),"four_entries":app.nav_labels==["目标推演","一键更新","一键复盘","高级分析"],"service_bound":isinstance(app.service,GuoxueService)}; app.destroy(); return {"status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"version":APP_VERSION}

def write_result(value,path=None):
    text=json.dumps(value,ensure_ascii=False)
    if path: target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text,encoding="utf-8")
    else: print(text)

def main():
    if "--gui-smoke" in sys.argv:
        r=gui_smoke(); write_result(r); return 0 if r["status"]=="PASS" else 2
    if "--self-test" in sys.argv or "--self-test-out" in sys.argv:
        out=None
        if "--self-test-out" in sys.argv:
            i=sys.argv.index("--self-test-out")
            if i+1>=len(sys.argv): raise SystemExit("--self-test-out requires path")
            out=sys.argv[i+1]
        r=self_test(); write_result(r,out); return 0 if r["status"]=="PASS" else 2
    App().mainloop(); return 0
if __name__=="__main__": raise SystemExit(main())
