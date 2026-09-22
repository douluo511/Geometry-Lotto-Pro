from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any

from .constants import APP_NAME, APP_VERSION
from .service import LottoService

BTN_PREDICT = 1001
BTN_UPDATE = 1002
BTN_REPAIR = 1003
BTN_AUDIT = 1004


def _format_prediction(value: dict) -> str:
    p = value["prediction"]
    t = value.get("effect_trace", {})
    return (
        f"{p['edge_state']} · {p['dan_state']}\r\n\r\n"
        f"目标期号  {p['target_issue']}    预计开奖日  {p['target_date']}\r\n\r\n"
        f"研究候选  前区 {' '.join(f'{n:02d}' for n in p['front'])}\r\n"
        f"          后区 {' '.join(f'{n:02d}' for n in p['back'])}\r\n\r\n"
        f"研究胆观察  前区 {' '.join(f'{n:02d}' for n in p['research_dan_front'])}  ·  后区 {' '.join(f'{n:02d}' for n in p['research_dan_back'])}\r\n"
        f"正式胆码状态  {p['dan_state']}\r\n真实优势状态  {p['edge_state']}\r\n"
        f"Scientific Gate  {t.get('scientific_gate','UNKNOWN')}  · Edge Gate {t.get('edge_gate','FAIL')}\r\n\r\n"
        f"完整评分空间  前区 {t.get('complete_space',{}).get('front',324632):,} / 后区 {t.get('complete_space',{}).get('back',66):,}\r\n"
        f"Freeze Hash  {p['freeze_hash']}\r\nSelector Hash {p['selector_hash']}\r\n\r\n"
        "注意：研究候选不代表更高中奖概率；只有严格 OOS/holdout 证据通过才允许 EDGE_PROVEN/CERTIFIED_DAN。"
    )


def _format_update(value: dict) -> str:
    latest = value["latest"]
    receipts = value.get("source_receipts", [])
    rows = "\r\n".join(f"• {x.get('source')}: {x.get('status')} / {x.get('draw_count')} 条 / {x.get('raw_sha256')}" for x in receipts)
    return (
        "双官方源更新：PASS\r\n\r\n"
        f"最新期 {latest['issue']}  {latest['draw_date']}\r\n"
        f"开奖号码 {' '.join(f'{n:02d}' for n in latest['front'])} + {' '.join(f'{n:02d}' for n in latest['back'])}\r\n"
        f"历史总数 {value.get('draw_count')} · 交叉核对 {value.get('crosscheck_count')} 期\r\n"
        f"Canonical Hash {value.get('canonical_hash')}\r\n\r\n{rows}\r\n\r\n已自动 Replay：{value.get('replayed',0)} 条"
    )


def _format_audit(value: dict) -> str:
    c = value["court"]
    gates = "\r\n".join(f"[{g['status']} / {g['decision']}] {g['name']} — {g['outcome']}" for g in c["gates"])
    return (
        f"Evidence Court：{c['software_verdict']}\r\nScientific Gate：{c['scientific_gate']}\r\n"
        f"真实预测优势：{c['edge_state']}\r\n胆码防火墙：{c['dan_state']}\r\n"
        f"Champion：{c['lifecycle']['Champion']}\r\n"
        f"Challenger：{', '.join(c['lifecycle']['Challenger'])}\r\n"
        f"Shadow：{', '.join(c['lifecycle']['Shadow'])}\r\n\r\n{gates}\r\n\r\n"
        f"KEEP：{c.get('validated_components',[])}\r\nDEAD_PATH：{c.get('dead_paths',[])}\r\n"
        f"Court Hash {c['court_hash']}\r\nORS Hash {value['ors']['ors_hash']}"
    )


class NativeApp:
    def __init__(self, service: Any | None = None):
        if os.name != "nt":
            raise RuntimeError("Native Win32 GUI requires Windows")
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.gdi32 = ctypes.windll.gdi32
        # Win64 handle-returning APIs must use pointer-sized restypes. Without this,
        # ctypes defaults to c_int and can truncate HWND/HINSTANCE/HFONT values.
        self.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self.user32.CreateWindowExW.restype = ctypes.c_void_p
        self.user32.LoadCursorW.restype = ctypes.c_void_p
        self.user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self.gdi32.CreateFontW.restype = ctypes.c_void_p
        self.service = service or LottoService()
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.controls: dict[str, int] = {}
        self.buttons: list[int] = []
        self.renderers = {
            BTN_PREDICT: ("预测下一期", self.service.predict, _format_prediction),
            BTN_UPDATE: ("一键更新", self.service.update, _format_update),
            BTN_REPAIR: ("一键修复", self.service.repair, lambda v: json.dumps(v, ensure_ascii=False, indent=2)),
            BTN_AUDIT: ("高级分析 · ORS + Evidence Court", self.service.audit, _format_audit),
        }
        self.WM_COMMAND = 0x0111; self.WM_TIMER = 0x0113; self.WM_DESTROY = 0x0002; self.WM_CLOSE = 0x0010
        self.WS_OVERLAPPEDWINDOW = 0x00CF0000; self.WS_VISIBLE=0x10000000; self.WS_CHILD=0x40000000
        self.ES_MULTILINE=0x0004; self.ES_AUTOVSCROLL=0x0040; self.ES_READONLY=0x0800; self.WS_VSCROLL=0x00200000
        self.BS_PUSHBUTTON=0x00000000; self.SW_SHOW=5; self.WM_SETFONT=0x0030
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT),("lpfnWndProc", WNDPROC),("cbClsExtra", ctypes.c_int),("cbWndExtra", ctypes.c_int),("hInstance", wintypes.HINSTANCE),("hIcon", wintypes.HICON),("hCursor", wintypes.HANDLE),("hbrBackground", wintypes.HBRUSH),("lpszMenuName", wintypes.LPCWSTR),("lpszClassName", wintypes.LPCWSTR)]
        self._WNDCLASSW=WNDCLASSW; self._WNDPROC=WNDPROC
        self.hinstance = self.kernel32.GetModuleHandleW(None)
        self.class_name = "GeometryLottoProV2Window"
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc=WNDCLASSW(); wc.lpfnWndProc=self._wndproc_ref; wc.hInstance=self.hinstance; wc.hCursor=self.user32.LoadCursorW(None, 32512); wc.hbrBackground=6; wc.lpszClassName=self.class_name
        atom=self.user32.RegisterClassW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() not in (0,1410):
            raise ctypes.WinError()
        self.hwnd=self.user32.CreateWindowExW(0,self.class_name,f"{APP_NAME} · DLT",self.WS_OVERLAPPEDWINDOW|self.WS_VISIBLE,100,80,1120,760,None,None,self.hinstance,None)
        if not self.hwnd: raise ctypes.WinError()
        self._build_controls()
        self.user32.SetTimer(self.hwnd,1,100,None)
        self.user32.ShowWindow(self.hwnd,self.SW_SHOW); self.user32.UpdateWindow(self.hwnd)

    def _ctl(self, cls, text, style, x,y,w,h,cid=0):
        hwnd=self.user32.CreateWindowExW(0,cls,text,self.WS_CHILD|self.WS_VISIBLE|style,x,y,w,h,self.hwnd,cid,self.hinstance,None)
        if not hwnd: raise self.ctypes.WinError()
        return hwnd

    def _font(self, size=18, weight=400, face="Microsoft YaHei UI"):
        return self.gdi32.CreateFontW(-size,0,0,0,weight,0,0,0,1,0,0,5,0,face)

    def _build_controls(self):
        title=self._ctl("STATIC",f"{APP_NAME}  ·  v{APP_VERSION}",0,28,20,520,44); self.user32.SendMessageW(title,self.WM_SETFONT,self._font(26,700),True)
        badge=self._ctl("STATIC","NO_EDGE · NO_DAN",0,850,30,220,30); self.controls["badge"]=badge
        labels=[(BTN_PREDICT,"预测下一期"),(BTN_UPDATE,"一键更新"),(BTN_REPAIR,"一键修复"),(BTN_AUDIT,"高级分析")]
        for i,(cid,label) in enumerate(labels):
            x=28+(i%2)*264; y=84+(i//2)*62
            btn=self._ctl("BUTTON",label,self.BS_PUSHBUTTON,x,y,245,52,cid); self.buttons.append(btn); self.user32.SendMessageW(btn,self.WM_SETFONT,self._font(18,600),True)
        heading=self._ctl("STATIC","证据优先的大乐透研究系统",0,560,84,500,34); self.controls["heading"]=heading; self.user32.SendMessageW(heading,self.WM_SETFONT,self._font(20,700),True)
        summary=self._ctl("STATIC","代码完整度 → 科学验证完整度 → 最终 EXE 验收完整度。所有声称有效的路径必须通过严格证伪。",0,560,122,510,62); self.controls["summary"]=summary
        out=self._ctl("EDIT","首次运行已内置构建时双官方源验证的历史快照。\r\n\r\n当前正确状态：NO_EDGE / NO_DAN",self.WS_VSCROLL|self.ES_MULTILINE|self.ES_AUTOVSCROLL|self.ES_READONLY,28,220,1040,405); self.controls["output"]=out; self.user32.SendMessageW(out,self.WM_SETFONT,self._font(16,400,"Consolas"),True)
        status=self._ctl("STATIC","就绪",0,28,640,1040,26); self.controls["status"]=status
        disclaimer=self._ctl("STATIC","本软件仅用于统计研究。大乐透由官方摇奖设备随机产生结果；请理性购彩，未成年人不得购彩。",0,28,678,1040,24); self.controls["disclaimer"]=disclaimer

    def _set(self,name,text): self.user32.SetWindowTextW(self.controls[name],str(text).replace("\n","\r\n"))
    def _enable(self,enabled):
        for h in self.buttons: self.user32.EnableWindow(h,bool(enabled))
    def _start(self,cid):
        if self.busy or cid not in self.renderers: return
        title,fn,renderer=self.renderers[cid]; self.busy=True; self._enable(False); self._set("heading",title); self._set("status","正在执行…")
        def worker():
            try:
                result=fn(lambda msg:self.events.put(("progress",msg)))
                self.events.put(("done",(result,renderer)))
            except Exception as exc:
                self.events.put(("error",str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def _drain(self):
        while True:
            try: kind,payload=self.events.get_nowait()
            except queue.Empty: break
            if kind=="progress": self._set("status",payload)
            elif kind=="done":
                result,renderer=payload; text=renderer(result); self._set("output",text)
                p=result.get("prediction") if isinstance(result,dict) else None; c=result.get("court") if isinstance(result,dict) else None
                state=p or c
                if state: self.user32.SetWindowTextW(self.controls["badge"],f"{state.get('edge_state','NO_EDGE')} · {state.get('dan_state','NULL_DAN')}")
                self._set("status","完成 · 结果已写入实验账本"); self.busy=False; self._enable(True)
            elif kind=="error":
                self._set("output","执行失败（Fail-Closed）\r\n\r\n"+payload+"\r\n\r\n未写入未经验证的数据，也未改变既有 Freeze。"); self._set("status","失败 · 状态未伪装为 PASS"); self.busy=False; self._enable(True)
    def _wndproc(self,hwnd,msg,wparam,lparam):
        if msg==self.WM_COMMAND:
            self._start(int(wparam)&0xFFFF); return 0
        if msg==self.WM_TIMER:
            self._drain(); return 0
        if msg==self.WM_CLOSE:
            self.user32.DestroyWindow(hwnd); return 0
        if msg==self.WM_DESTROY:
            self.user32.KillTimer(hwnd,1); self.user32.PostQuitMessage(0); return 0
        return self.user32.DefWindowProcW(hwnd,msg,wparam,lparam)
    def run(self):
        msg=self.wintypes.MSG()
        while self.user32.GetMessageW(self.ctypes.byref(msg),None,0,0)>0:
            self.user32.TranslateMessage(self.ctypes.byref(msg)); self.user32.DispatchMessageW(self.ctypes.byref(msg))


def run_gui():
    NativeApp().run()


def gui_self_test() -> dict[str, Any]:
    if os.name != "nt":
        return {"status":"FAIL","checks":[{"name":"Native Win32 window","status":"FAIL","detail":"not Windows"}]}
    class StubService:
        def _ok(self,name): return lambda progress=None: {"entry":name}
        predict=property(lambda self:self._ok("预测下一期")); update=property(lambda self:self._ok("一键更新")); repair=property(lambda self:self._ok("一键修复")); audit=property(lambda self:self._ok("高级分析"))
    app=NativeApp(StubService())
    checks=[]
    try:
        expected={BTN_PREDICT:"预测下一期",BTN_UPDATE:"一键更新",BTN_REPAIR:"一键修复",BTN_AUDIT:"高级分析"}
        for cid,label in expected.items():
            checks.append({"name":label,"status":"PASS" if cid in app.renderers else "FAIL"})
        checks.append({"name":"Native Win32 window","status":"PASS" if app.user32.IsWindow(app.hwnd) else "FAIL"})
    finally:
        if app.user32.IsWindow(app.hwnd): app.user32.DestroyWindow(app.hwnd)
    return {"status":"PASS" if all(c["status"]=="PASS" for c in checks) else "FAIL","checks":checks}
