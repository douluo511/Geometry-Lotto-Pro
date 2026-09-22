from __future__ import annotations

import ctypes
import json
import queue
import threading
from ctypes import wintypes
from typing import Any, Callable

from glp.constants import APP_NAME, APP_VERSION
from glp.service import LottoService

# Pure Win32 UI: no tkinter/Tcl dependency.  The original app used the same
# native approach; this module keeps the four-entry interface while binding it
# to the upgraded service rather than the legacy service module.

LRESULT = ctypes.c_ssize_t
HCURSOR = ctypes.c_void_p
HBRUSH = ctypes.c_void_p
HICON = ctypes.c_void_p
HINSTANCE = ctypes.c_void_p
HWND = ctypes.c_void_p
HMENU = ctypes.c_void_p

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_TABSTOP = 0x00010000
WS_BORDER = 0x00800000
WS_VSCROLL = 0x00200000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_READONLY = 0x0800
BS_PUSHBUTTON = 0x00000000
SS_LEFT = 0x00000000
CW_USEDEFAULT = 0x80000000
SW_SHOW = 5
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_SETFONT = 0x0030
IDC_ARROW = 32512
COLOR_WINDOW = 5

BTN_PREDICT = 101
BTN_UPDATE = 102
BTN_REPAIR = 103
BTN_AUDIT = 104
OUT_EDIT = 201
STATUS_STATIC = 202


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False, default=str)


class NativeApp:
    def __init__(self, service: LottoService | None = None):
        self.service = service or LottoService()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self.controls: dict[int, HWND] = {}
        self.buttons: list[HWND] = []
        self.hwnd: HWND | None = None
        self._wndproc_ref = WNDPROC(self._wndproc)
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = HINSTANCE
        self.user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, HMENU, HINSTANCE, ctypes.c_void_p]
        self.user32.CreateWindowExW.restype = HWND
        self.user32.LoadCursorW.argtypes = [HINSTANCE, ctypes.c_void_p]
        self.user32.LoadCursorW.restype = HCURSOR
        self.user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.DefWindowProcW.restype = LRESULT
        self.user32.SetWindowTextW.argtypes = [HWND, wintypes.LPCWSTR]
        self.user32.IsWindow.argtypes = [HWND]
        self.user32.DestroyWindow.argtypes = [HWND]
        self.user32.EnableWindow.argtypes = [HWND, wintypes.BOOL]
        self.user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
        self.user32.UpdateWindow.argtypes = [HWND]
        self.user32.SetTimer.argtypes = [HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        self.user32.SetTimer.restype = ctypes.c_size_t
        self.user32.KillTimer.argtypes = [HWND, ctypes.c_size_t]
        self.class_name = "GeometryLottoProSSQv8Window"
        self.hinstance = HINSTANCE(self.kernel32.GetModuleHandleW(None))
        self._register()
        self._create_window()

    def _register(self) -> None:
        cls = WNDCLASSW()
        cls.style = 0
        cls.lpfnWndProc = self._wndproc_ref
        cls.cbClsExtra = 0
        cls.cbWndExtra = 0
        cls.hInstance = self.hinstance
        cls.hIcon = None
        cls.hCursor = HCURSOR(self.user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW)))
        cls.hbrBackground = HBRUSH(COLOR_WINDOW + 1)
        cls.lpszMenuName = None
        cls.lpszClassName = self.class_name
        atom = self.user32.RegisterClassW(ctypes.byref(cls))
        # ERROR_CLASS_ALREADY_EXISTS is harmless when self-test creates a second window.
        if not atom and ctypes.get_last_error() not in (0, 1410):
            raise ctypes.WinError(ctypes.get_last_error())

    def _control(self, klass: str, text: str, style: int, x: int, y: int, w: int, h: int, cid: int) -> HWND:
        hwnd = self.user32.CreateWindowExW(
            0, klass, text, style | WS_CHILD | WS_VISIBLE,
            x, y, w, h, self.hwnd, HMENU(cid), self.hinstance, None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        h = HWND(hwnd)
        self.controls[cid] = h
        return h

    def _create_window(self) -> None:
        hwnd = self.user32.CreateWindowExW(
            0, self.class_name,
            f"{APP_NAME} — SSQ ONLY — v{APP_VERSION}",
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT, CW_USEDEFAULT, 920, 700,
            None, None, self.hinstance, None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = HWND(hwnd)
        self._build_controls()
        self.user32.SetTimer(self.hwnd, 1, 150, None)
        self.user32.ShowWindow(self.hwnd, SW_SHOW)
        self.user32.UpdateWindow(self.hwnd)

    def _build_controls(self) -> None:
        self._control("STATIC", f"{APP_NAME}  v{APP_VERSION}   ·   SSQ ONLY", SS_LEFT, 24, 18, 840, 28, 301)
        self._control(
            "STATIC",
            "代码完整度 → 科学验证完整度 → 最终 EXE 验收完整度｜NO_EDGE/NULL_DAN 时生产层保持随机基准",
            SS_LEFT, 24, 50, 850, 38, 302,
        )
        b1 = self._control("BUTTON", "预测下一期", WS_TABSTOP | BS_PUSHBUTTON, 24, 98, 420, 46, BTN_PREDICT)
        b2 = self._control("BUTTON", "一键更新", WS_TABSTOP | BS_PUSHBUTTON, 460, 98, 420, 46, BTN_UPDATE)
        b3 = self._control("BUTTON", "一键修复", WS_TABSTOP | BS_PUSHBUTTON, 24, 154, 420, 46, BTN_REPAIR)
        b4 = self._control("BUTTON", "高级分析", WS_TABSTOP | BS_PUSHBUTTON, 460, 154, 420, 46, BTN_AUDIT)
        self.buttons = [b1, b2, b3, b4]
        self._control("STATIC", "就绪", SS_LEFT, 24, 210, 856, 24, STATUS_STATIC)
        self._control(
            "EDIT", "",
            WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
            24, 244, 856, 390, OUT_EDIT,
        )
        self._set_text(OUT_EDIT, "四个入口均连接真实执行路径。\r\n高级分析不会产生正式 Prediction Freeze。\r\n")

    def _set_text(self, cid: int, text: str) -> None:
        hwnd = self.controls.get(cid)
        if hwnd:
            self.user32.SetWindowTextW(hwnd, str(text).replace("\n", "\r\n"))

    def _enable_buttons(self, enabled: bool) -> None:
        for b in self.buttons:
            self.user32.EnableWindow(b, bool(enabled))

    def _progress(self, msg: str) -> None:
        self.events.put(("progress", msg))

    def _start(self, name: str, target: Callable[..., Any], renderer: Callable[[Any], str]) -> None:
        if self.busy:
            return
        self.busy = True
        self._enable_buttons(False)
        self._set_text(STATUS_STATIC, f"{name}：执行中…")
        self._set_text(OUT_EDIT, f"{name}：开始\n")

        def worker() -> None:
            try:
                result = target(progress=self._progress)
                self.events.put(("done", (name, result, renderer)))
            except Exception as exc:
                self.events.put(("error", (name, f"{type(exc).__name__}: {exc}")))
        threading.Thread(target=worker, daemon=True).start()

    def _render_prediction(self, value: Any) -> str:
        p = value.get("prediction", {}) if isinstance(value, dict) else {}
        gate = value.get("final_gate", {}) if isinstance(value, dict) else {}
        trace = value.get("effect_trace", {}) if isinstance(value, dict) else {}
        fr = (p.get("front_ranking") or {}).get("numbers", [])
        br = (p.get("back_ranking") or {}).get("numbers", [])
        lines = [
            "=== SSQ 预测 / 研究结果 ===",
            f"目标期号：{p.get('target_issue')}    日期：{p.get('target_date')}",
            "生产层红球：" + " ".join(f"{int(x):02d}" for x in fr[:6]),
            "生产层蓝球：" + " ".join(f"{int(x):02d}" for x in br[:1]),
            f"EDGE：{p.get('edge_state')}    DAN：{p.get('dan_state')}",
            "研究胆码(红)：" + " ".join(f"{int(x):02d}" for x in p.get("research_dan_front", [])),
            "研究胆码(蓝)：" + " ".join(f"{int(x):02d}" for x in p.get("research_dan_back", [])),
            f"Final Gate：{gate.get('status')}    hard_fail_count={gate.get('hard_fail_count')}",
            f"Freeze：{p.get('freeze_hash','')}",
            f"Selector：{p.get('selector_hash','')}",
            f"生产权重：{trace.get('production_weights')}",
        ]
        if value.get("auto_update_error"):
            lines.append("官方更新错误（Fail-Closed）：" + str(value.get("auto_update_error")))
        lines.append("\nFinal Gate checks:\n" + _pretty(gate.get("checks", {})))
        return "\n".join(lines)

    def _render_update(self, value: Any) -> str:
        lines = [
            "=== 官方数据更新 ===",
            f"最新期：{value.get('latest_issue')}    日期：{value.get('latest_date')}",
            f"历史期数：{value.get('draw_count')}",
            f"双源交叉核验：{value.get('crosscheck_status')} / {value.get('crosscheck_count')}",
            f"Canonical：{value.get('canonical_hash')}",
            f"Replay 新增：{value.get('replayed')}",
            "\nSource receipts:\n" + _pretty(value.get("source_receipts", [])),
        ]
        return "\n".join(lines)

    def _render_repair(self, value: Any) -> str:
        return "=== 一键修复 ===\n" + _pretty(value)

    def _render_audit(self, value: Any) -> str:
        court = value.get("court", {}) if isinstance(value, dict) else {}
        lines = [
            "=== Advanced Evidence Court ===",
            f"Software verdict：{value.get('software_verdict')}",
            f"EDGE：{court.get('edge_state')}    DAN：{court.get('dan_state')}",
            f"Court hash：{court.get('court_hash')}",
            f"Audit 写正式 Freeze：{value.get('formal_freeze_written')}",
            "\nGates:",
        ]
        for g in value.get("gates", []):
            lines.append(f"[{g.get('status')}] {g.get('name')} → {g.get('decision')} | {g.get('outcome')}")
        lines += [
            "\nDual Final Confirmation:\n" + _pretty(court.get("dual_final_confirmation", {})),
            "\nWilson / Coverage / Rank Support:\n" + _pretty(court.get("support_gate", {})),
            "\nNull-world:\n" + _pretty(court.get("null_world", {})),
            "\nSelf-test:\n" + _pretty(value.get("self_test", {})),
        ]
        return "\n".join(lines)

    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self._set_text(STATUS_STATIC, str(payload))
            elif kind == "done":
                name, result, renderer = payload
                try:
                    self._set_text(OUT_EDIT, renderer(result))
                    self._set_text(STATUS_STATIC, f"{name}：完成")
                except Exception as exc:
                    self._set_text(OUT_EDIT, f"{name}：显示结果失败：{exc}")
                    self._set_text(STATUS_STATIC, f"{name}：FAIL")
                finally:
                    self.busy = False
                    self._enable_buttons(True)
            elif kind == "error":
                name, err = payload
                self._set_text(OUT_EDIT, f"{name} FAIL\n{err}\n\nFail-Closed：未产生虚假 PASS。")
                self._set_text(STATUS_STATIC, f"{name}：FAIL")
                self.busy = False
                self._enable_buttons(True)

    def _wndproc(self, hwnd: HWND, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_COMMAND:
            cid = int(wparam) & 0xFFFF
            if cid == BTN_PREDICT:
                self._start("预测下一期", self.service.predict, self._render_prediction)
                return 0
            if cid == BTN_UPDATE:
                self._start("一键更新", self.service.update, self._render_update)
                return 0
            if cid == BTN_REPAIR:
                self._start("一键修复", self.service.repair, self._render_repair)
                return 0
            if cid == BTN_AUDIT:
                self._start("高级分析", self.service.audit, self._render_audit)
                return 0
        elif msg == WM_TIMER:
            self._drain()
            return 0
        elif msg == WM_CLOSE:
            self.user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            self.user32.KillTimer(hwnd, 1)
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self) -> int:
        msg = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))
        return int(msg.wParam)


def run_gui() -> int:
    return NativeApp().run()


def gui_self_test() -> dict[str, Any]:
    """Windows-native smoke test including WM_COMMAND -> backend routing.

    The backend is a spy, so this verifies the real Win32 message path without
    touching network/data or creating a formal prediction Freeze.
    """
    import time

    class _Spy:
        def __init__(self):
            self.calls = []
        def _hit(self, name, progress=None):
            self.calls.append(name)
            return {"status": "PASS", "final_gate": {"status": "PASS"}, "software_verdict": "PASS"}
        def predict(self, progress=None): return self._hit("predict", progress)
        def update(self, progress=None): return self._hit("update", progress)
        def repair(self, progress=None): return self._hit("repair", progress)
        def audit(self, progress=None): return self._hit("audit", progress)

    checks = {}
    app = None
    try:
        spy = _Spy()
        app = NativeApp(spy)
        checks["native_window_created"] = bool(app.user32.IsWindow(app.hwnd))
        for cid in (BTN_PREDICT, BTN_UPDATE, BTN_REPAIR, BTN_AUDIT):
            checks[f"control_{cid}"] = bool(app.user32.IsWindow(app.controls[cid]))
        app.user32.SendMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        app.user32.SendMessageW.restype = LRESULT
        routes = [(BTN_PREDICT, "predict"), (BTN_UPDATE, "update"), (BTN_REPAIR, "repair"), (BTN_AUDIT, "audit")]
        for cid, expected in routes:
            before = len(spy.calls)
            app.user32.SendMessageW(app.hwnd, WM_COMMAND, cid, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                app._drain()
                if len(spy.calls) > before and not app.busy:
                    break
                time.sleep(0.01)
            checks[f"route_{expected}"] = len(spy.calls) > before and spy.calls[-1] == expected
    except Exception as exc:
        return {"status": "FAIL", "checks": checks, "error": str(exc), "scope": "Win32 window/control/WM_COMMAND routing"}
    finally:
        if app is not None and app.hwnd and app.user32.IsWindow(app.hwnd):
            app.user32.DestroyWindow(app.hwnd)
    return {
        "status": "PASS" if checks and all(checks.values()) else "FAIL",
        "checks": checks,
        "scope": "native window + four controls + WM_COMMAND backend routing",
        "physical_human_click": "UNAVAILABLE_IN_AUTOMATION",
    }

