"""自定义快捷键录制器。

⚠ 本模块刻意使用**自己独占的** user32 句柄，绝不复用 ctypes.windll.user32。
理由见 winapi.py：Mouser v3.7.2 的录制器与鼠标钩子共用句柄，导致
CallNextHookEx 原型被覆盖、全会话鼠标冻结；v3.7.3 以私有句柄修复 (issue #259)。

提供两种录制方式：
* record_shortcut()  —— WH_KEYBOARD_LL 全局录制（需要消息循环，Windows 桌面会话）
* capture_from_console() —— 无 GUI / 无桌面会话时的文本输入退路
"""
from __future__ import annotations

import ctypes
import time
from typing import Iterable

from .winapi import (
    IS_WINDOWS, VK, WH_KEYBOARD_LL, HC_ACTION, LLKHF_INJECTED,
    KBDLLHOOKSTRUCT, private_user32,
)
from .actions import (parse_shortcut_string, shortcut_to_id, format_shortcut,
                      parse_custom_action)
from .key_simulator import resolve_vk_codes

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
PM_REMOVE = 0x0001

_MOD_CODES = frozenset({VK["CTRL"], VK["SHIFT"], VK["ALT"], VK["WIN"]})


def shortcut_id_from_text(text: str) -> str:
    """'Ctrl+Shift+P' -> 'custom:0x11+0x10+0x50'。"""
    codes = parse_shortcut_string(text)
    return shortcut_to_id(codes) if codes else "none"


def describe_shortcut(action_id: str) -> str:
    codes = parse_custom_action(action_id)
    return format_shortcut(codes) if codes else action_id


def capture_from_console(prompt: str = "输入组合键（如 Ctrl+Shift+P）: ") -> str:
    text = input(prompt)
    result = shortcut_id_from_text(text)
    if result == "none":
        print("  ✗ 无法解析该组合键")
    else:
        print(f"  ✓ {describe_shortcut(result)}  ->  {result}")
    return result


class ShortcutRecorder:
    """WH_KEYBOARD_LL 录制一次组合键；录制期间吞掉按键，带超时保护。"""

    def __init__(self):
        self._recorded: set[int] = set()
        self._pressed: set[int] = set()
        self._done = False
        self._hook = None
        self._proc_ref = None
        # 关键：私有句柄，与鼠标钩子 / 注入器完全隔离
        self._user32 = private_user32() if IS_WINDOWS else None
        if IS_WINDOWS:
            import ctypes.wintypes as wt
            self.HOOKPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, wt.WPARAM,
                ctypes.POINTER(KBDLLHOOKSTRUCT))
            u = self._user32
            u.SetWindowsHookExW.restype = wt.HHOOK
            u.SetWindowsHookExW.argtypes = [ctypes.c_int, self.HOOKPROC,
                                            wt.HINSTANCE, wt.DWORD]
            u.CallNextHookEx.restype = ctypes.c_long
            u.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM,
                                         ctypes.POINTER(KBDLLHOOKSTRUCT)]
            u.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
            u.UnhookWindowsHookEx.restype = wt.BOOL
            u.GetModuleHandleW.restype = wt.HMODULE
            u.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            u.PeekMessageW.argtypes = [ctypes.c_void_p, wt.HWND, ctypes.c_uint,
                                       ctypes.c_uint, ctypes.c_uint]
            u.PeekMessageW.restype = wt.BOOL
            u.TranslateMessage.argtypes = [ctypes.c_void_p]
            u.DispatchMessageW.argtypes = [ctypes.c_void_p]

    def _handler(self, n_code, w_param, l_param):
        try:
            if n_code == HC_ACTION:
                data = l_param.contents
                if not (data.flags & LLKHF_INJECTED):
                    vk = int(data.vkCode)
                    is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    if is_down:
                        self._pressed.add(vk)
                        self._recorded.add(vk)
                    else:
                        self._pressed.discard(vk)
                        # 所有键松开、且录到至少一个非修饰键 -> 完成
                        if not self._pressed and any(c not in _MOD_CODES for c in self._recorded):
                            self._done = True
            # 录制期间一律吞掉，避免组合键触发当前应用
            return 1
        except Exception:
            return 1

    def record(self, timeout: float = 10.0) -> str:
        """阻塞录制；返回 custom:... 动作 ID，超时或失败返回 'none'。"""
        if not IS_WINDOWS or self._user32 is None:
            return capture_from_console()
        u = self._user32
        self._proc_ref = self.HOOKPROC(self._handler)
        self._hook = u.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc_ref,
                                         u.GetModuleHandleW(None), 0)
        if not self._hook:
            return capture_from_console()
        msg = ctypes.create_string_buffer(64)
        deadline = time.monotonic() + max(1.0, timeout)
        try:
            while not self._done and time.monotonic() < deadline:
                while u.PeekMessageW(msg, None, 0, 0, PM_REMOVE):
                    u.TranslateMessage(msg)
                    u.DispatchMessageW(msg)
                time.sleep(0.02)
        finally:
            u.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc_ref = None
        if not self._done:
            return "none"
        # 修饰键在前，其余按码值排序，保证稳定编码
        mods = tuple(sorted(c for c in self._recorded if c in _MOD_CODES))
        others = tuple(sorted(c for c in self._recorded if c not in _MOD_CODES))
        return shortcut_to_id(mods + others)


def resolve_action_codes(action_id: str) -> tuple[int, ...]:
    """把动作 ID 解析成可注入的键码（内置动作与自定义快捷键统一入口）。"""
    from .actions import resolve_action
    codes = parse_custom_action(action_id)
    if codes:
        return codes
    action = resolve_action(action_id)
    if action is None:
        return ()
    return resolve_vk_codes(action.vks)
