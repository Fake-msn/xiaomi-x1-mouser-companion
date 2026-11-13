"""WH_MOUSE_LL 低级鼠标钩子。

四条不可妥协的护栏（见方案 §2）：
1. **私有 user32 句柄 + 实例私有 HOOKPROC 类型** —— 杜绝 ctypes 原型互相覆盖
   （Mouser v3.7.2 → v3.7.3 的全会话指针冻结事故）。
2. **INJECTED_FLAG 直接放行** —— 防止 G-HUB 与伴生层互相触发形成回环。
3. **只吞白名单事件** —— 是否吞由 engine 的 blocked_provider 决定，
   其默认值是空集（全部透传）。
4. **回调内绝不抛异常** —— 任何异常都无条件 CallNextHookEx，
   绝不因为伴生层的 bug 冻住用户的鼠标。

钩子跑在独立线程 + GetMessageW 消息循环上；回调里只做 O(1) 查询和入队，
动作注入交给 engine 的 dispatch worker。
"""
from __future__ import annotations

import ctypes
import queue
import threading
import time
from dataclasses import dataclass

from .winapi import (
    IS_WINDOWS, WH_MOUSE_LL, HC_ACTION, WM_QUIT, WM_MOUSEMOVE,
    WM_MOUSEWHEEL, WM_MOUSEHWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP,
    XBUTTON1, XBUTTON2, LLMHF_INJECTED, MSLLHOOKSTRUCT,
    private_user32, private_kernel32, hiword,
)


@dataclass(frozen=True)
class MouseEvent:
    button: str
    kind: str              # down / up / wheel / move
    delta: int = 0
    x: int = 0
    y: int = 0
    injected: bool = False

    @property
    def key(self) -> str:
        return f"{self.button}:{self.kind}"


def translate_message(w_param: int, mouse_data: int = 0,
                      x: int = 0, y: int = 0) -> MouseEvent | None:
    """Windows 消息 -> MouseEvent。纯函数，可单测。"""
    w = int(w_param)
    if w == WM_MOUSEMOVE:
        return MouseEvent("pointer", "move", x=x, y=y)
    if w == 0x0201:
        return MouseEvent("left", "down", x=x, y=y)
    if w == 0x0202:
        return MouseEvent("left", "up", x=x, y=y)
    if w == 0x0204:
        return MouseEvent("right", "down", x=x, y=y)
    if w == 0x0205:
        return MouseEvent("right", "up", x=x, y=y)
    if w == 0x0207:
        return MouseEvent("middle", "down", x=x, y=y)
    if w == 0x0208:
        return MouseEvent("middle", "up", x=x, y=y)
    if w in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        xb = hiword(mouse_data)
        button = "xbutton1" if xb == XBUTTON1 else ("xbutton2" if xb == XBUTTON2 else None)
        if button is None:
            return None
        return MouseEvent(button, "down" if w == WM_XBUTTONDOWN else "up", x=x, y=y)
    if w == WM_MOUSEWHEEL:
        delta = hiword(mouse_data)
        return MouseEvent("wheel_up" if delta > 0 else "wheel_down", "wheel",
                          delta=delta, x=x, y=y)
    if w == WM_MOUSEHWHEEL:
        delta = hiword(mouse_data)
        return MouseEvent("hscroll_right" if delta > 0 else "hscroll_left", "wheel",
                          delta=delta, x=x, y=y)
    return None


class MouseHook:
    def __init__(self, on_event, should_intercept, blocked_provider, on_move=None):
        self._on_event = on_event
        self._should_intercept = should_intercept
        self._blocked_provider = blocked_provider
        self._on_move = on_move
        self.events: queue.Queue[MouseEvent] = queue.Queue(maxsize=512)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._proc_ref = None
        self._startup_event = threading.Event()
        self._startup_ok = False
        self._user32 = private_user32() if IS_WINDOWS else None
        self._kernel32 = private_kernel32() if IS_WINDOWS else None

        if IS_WINDOWS:
            import ctypes.wintypes as wt
            # 每个实例一个独立的回调类型，配合私有句柄做到彻底隔离
            self.HOOKPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, wt.WPARAM,
                ctypes.POINTER(MSLLHOOKSTRUCT))
            u, k = self._user32, self._kernel32
            u.SetWindowsHookExW.restype = wt.HHOOK
            u.SetWindowsHookExW.argtypes = [ctypes.c_int, self.HOOKPROC,
                                            wt.HINSTANCE, wt.DWORD]
            u.CallNextHookEx.restype = ctypes.c_long
            u.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM,
                                         ctypes.POINTER(MSLLHOOKSTRUCT)]
            u.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
            u.UnhookWindowsHookEx.restype = wt.BOOL
            u.GetMessageW.argtypes = [ctypes.c_void_p, wt.HWND, ctypes.c_uint, ctypes.c_uint]
            u.GetMessageW.restype = ctypes.c_int
            u.TranslateMessage.argtypes = [ctypes.c_void_p]
            u.DispatchMessageW.argtypes = [ctypes.c_void_p]
            u.PostThreadMessageW.argtypes = [wt.DWORD, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
            u.PostThreadMessageW.restype = wt.BOOL
            k.GetModuleHandleW.restype = wt.HMODULE
            k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            k.GetCurrentThreadId.restype = wt.DWORD
            k.GetCurrentThreadId.argtypes = []

    # ── 生命周期 ─────────────────────────────────────────────
    def start(self, timeout: float = 3.0) -> bool:
        if not IS_WINDOWS or self._user32 is None:
            return False
        self._startup_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="MouseHook")
        self._thread.start()
        self._startup_event.wait(timeout)
        return self._startup_ok

    def _run(self) -> None:
        u, k = self._user32, self._kernel32
        self._thread_id = k.GetCurrentThreadId()
        self._proc_ref = self.HOOKPROC(self._handler)
        self._hook = u.SetWindowsHookExW(WH_MOUSE_LL, self._proc_ref,
                                         k.GetModuleHandleW(None), 0)
        self._startup_ok = bool(self._hook)
        self._startup_event.set()
        if not self._hook:
            return
        msg = ctypes.create_string_buffer(64)
        try:
            while u.GetMessageW(msg, None, 0, 0) > 0:
                u.TranslateMessage(msg)
                u.DispatchMessageW(msg)
        finally:
            u.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def stop(self) -> None:
        if not IS_WINDOWS or self._user32 is None:
            return
        if self._thread_id:
            self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # ── 回调 ────────────────────────────────────────────────
    def _handler(self, n_code, w_param, l_param):
        # 无论发生什么，异常路径都必须把事件交还给系统
        try:
            if n_code != HC_ACTION:
                return self._next(n_code, w_param, l_param)
            data = l_param.contents
            # 护栏 2：注入事件直接放行，杜绝回环
            if data.flags & LLMHF_INJECTED:
                return self._next(n_code, w_param, l_param)
            # 护栏 3：bypass / game_mode / 设备白名单不满足 -> 全透传
            if not self._should_intercept():
                return self._next(n_code, w_param, l_param)

            w = int(w_param)
            if w == WM_MOUSEMOVE:
                if self._on_move:
                    self._on_move(data.pt.x, data.pt.y)
                return self._next(n_code, w_param, l_param)

            event = translate_message(w, data.mouseData, data.pt.x, data.pt.y)
            if event is None:
                return self._next(n_code, w_param, l_param)

            blocked = self._blocked_provider()
            should_block = event.key in blocked
            try:
                self._on_event(event)
            except Exception:
                pass
            if should_block:
                return 1
            return self._next(n_code, w_param, l_param)
        except Exception:
            return self._next(n_code, w_param, l_param)

    def _next(self, n_code, w_param, l_param):
        try:
            return self._user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        except Exception:
            return 0

    # ── 测试辅助：不装钩子直接把事件送进调度链 ────────────────
    def submit(self, event: MouseEvent) -> None:
        try:
            self._on_event(event)
        except Exception:
            pass
