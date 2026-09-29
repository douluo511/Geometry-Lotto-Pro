import tkinter as tk
from tkinter import ttk, messagebox
import threading, json

class MainWindow:
    def __init__(self,svc):
        self.svc=svc; self.root=tk.Tk(); self.root.title('TalkCraft Pro v1.0'); self.root.geometry('980x720'); self.root.minsize(800,620)
        self.status=tk.StringVar(value='READY · 双完成度模式 · 未通过最终发布门')
        self._build()
    def _build(self):
        top=ttk.Frame(self.root,padding=16); top.pack(fill='x')
        ttk.Label(top,text='TalkCraft Pro · 脱口秀表达训练系统',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(top,text='观察 → 观点 → 结构 → 幽默 → 表达 → 互动 → Evidence → 逆转验证',foreground='#555').pack(anchor='w',pady=(4,12))
        btns=ttk.Frame(top); btns.pack(fill='x')
        for text,cmd in [('今日训练',self.daily),('一键更新',self.update),('一键修复',self.repair),('高级分析',self.analytics)]:
            ttk.Button(btns,text=text,command=cmd).pack(side='left',expand=True,fill='x',padx=4)
        self.nb=ttk.Notebook(self.root); self.nb.pack(fill='both',expand=True,padx=16,pady=8)
        self.train=ttk.Frame(self.nb,padding=14); self.advanced=ttk.Frame(self.nb,padding=14); self.nb.add(self.train,text='训练'); self.nb.add(self.advanced,text='高级分析')
        self.prompt=tk.StringVar(value='点击“今日训练”开始。'); ttk.Label(self.train,textvariable=self.prompt,wraplength=900,font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(0,8))
        ttk.Label(self.train,text='你的表达：').pack(anchor='w'); self.input=tk.Text(self.train,height=10,wrap='word'); self.input.pack(fill='x',pady=6)
        row=ttk.Frame(self.train); row.pack(fill='x'); ttk.Button(row,text='分析并保存 Evidence',command=self.analyze).pack(side='left'); ttk.Button(row,text='载入示例',command=self.example).pack(side='left',padx=8)
        ttk.Label(self.train,text='分析结果：').pack(anchor='w',pady=(12,4)); self.output=tk.Text(self.train,height=16,wrap='word',state='disabled'); self.output.pack(fill='both',expand=True)
        self.adv_text=tk.Text(self.advanced,wrap='word',state='disabled'); self.adv_text.pack(fill='both',expand=True)
        ttk.Label(self.root,textvariable=self.status,relief='sunken',anchor='w').pack(fill='x',side='bottom')
    def _setout(self,w,text): w.config(state='normal'); w.delete('1.0','end'); w.insert('end',text); w.config(state='disabled')
    def daily(self):
        d=self.svc.daily(); self.prompt.set(f"[{d['id']}] {d['topic']}：{d['task']}（{d['minutes']}分钟）"); self.nb.select(self.train); self.status.set('TRAINING_READY')
    def example(self): self.input.delete('1.0','end'); self.input.insert('end','我朋友每次都说马上到，结果半小时后才出现。后来我发现，马上不是时间，是一种人生理念。')
    def analyze(self):
        text=self.input.get('1.0','end').strip()
        if not text: messagebox.showwarning('TalkCraft','请先输入一段表达。'); return
        try:
            r=self.svc.analyze(text); s=r.score.as_dict(); body='七维评分\n'+'\n'.join(f'{k}: {v}' for k,v in s.items())+'\n\n改进建议\n'+'\n'.join('• '+x for x in r.improvements)+f'\n\n下一轮：{r.next_task}'
            self._setout(self.output,body); self.status.set('EVIDENCE_SAVED')
        except Exception as e: messagebox.showerror('分析失败',str(e)); self.status.set('ANALYSIS_FAIL')
    def update(self):
        self.status.set('UPDATE_RUNNING · 真实网络校验中')
        def worker():
            r=self.svc.update_all_sources(); self.root.after(0,lambda:self._update_done(r))
        threading.Thread(target=worker,daemon=True).start()
    def _update_done(self,r):
        lines=[f"总状态: {'PASS' if r['ok'] else 'FAIL'}",r['policy'],'']+[f"{x['name']}: {'PASS' if x['ok'] else 'FAIL'} HTTP={x['status']} SHA={x['sha256'][:12] if x['sha256'] else '-'} {x['error']}" for x in r['sources']]
        self._setout(self.adv_text,'\n'.join(lines)); self.nb.select(self.advanced); self.status.set('UPDATE_PASS' if r['ok'] else 'UPDATE_FAIL · 不把缓存冒充最新')
    def repair(self):
        r=self.svc.repair(); self._setout(self.adv_text,json.dumps(r,ensure_ascii=False,indent=2)); self.nb.select(self.advanced); self.status.set('REPAIR_PASS' if r['ok'] else 'REPAIR_FAIL')
    def analytics(self):
        a=self.svc.analytics(); self._setout(self.adv_text,json.dumps(a,ensure_ascii=False,indent=2)); self.nb.select(self.advanced); self.status.set('ANALYTICS_READY')
    def run(self): self.root.mainloop()
