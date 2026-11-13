"""SendInput 动作注入器。

持有自己独占的 user32 句柄（见 winapi.py）：与鼠标钩子、键盘录制器
各自独立，避免 ctypes 函数原型互相覆盖。

dry_run=True 时不调用任何 Win32 API，只记录意图 —— 供单元测试与
`--selftest` 在无鼠标环境下验证整条调度链。
"""
from __future__ import annotations

import ctypes
from typing import Iterable

from .winapi import (
    IS_WINDOWS, VK, INPUT, INPUT_KEYBOARD, INPUT_MOUSE,
    KEYBDINPUT, MOUSEINPUT, KEYEVENTF_KEYUP, KEYEVENTF_EXTENDEDKEY,
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL,
    XBUTTON1, XBUTTON2, private_user32,
)

# 这些键在 SendInput 中需要 EXTENDEDKEY 标志
_EXTENDED = frozenset({
    0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22,
    0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB3, 0x2C,
})

_MOUSE_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "xbutton1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    "xbutton2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
}


def resolve_vk_codes(names: Iterable[str]) -> tuple[int, ...]:
    """动作里的键名 / '0xNN' 形式 -> 虚拟键码。"""
    codes: list[int] = []
    for name in names:
        if not isinstance(name, str):
            continue
        key = name.strip().upper()
        if key.startswith("0X"):
            try:
                code = int(key, 16)
            except ValueError:
                continue
        else:
            code = VK.get(key)
            if code is None:
                continue
        if code not in codes:
            codes.append(code)
    return tuple(codes)


class Injector:
    def __init__(self, dry_run: bool = False):
        self.dry_run = bool(dry_run) or not IS_WINDOWS
        self.sent: list[tuple] = []
        self._user32 = None
        if not self.dry_run:
            self._user32 = private_user32()
            self._user32.SendInput.argtypes = [
                ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
            self._user32.SendInput.restype = ctypes.c_uint

    # ── 底层 ────────────────────────────────────────────────
    def _send(self, inputs: list[INPUT]) -> bool:
        if self.dry_run or not inputs:
            return True
        array = (INPUT * len(inputs))(*inputs)
        return self._user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) == len(inputs)

    @staticmethod
    def _key(vk: int, up: bool) -> INPUT:
        item = INPUT()
        item.type = INPUT_KEYBOARD
        flags = KEYEVENTF_KEYUP if up else 0
        if vk in _EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        item.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
        return item

    @staticmethod
    def _mouse(flags: int, data: int = 0) -> INPUT:
        item = INPUT()
        item.type = INPUT_MOUSE
        item.u.mi = MOUSEINPUT(dx=0, dy=0, mouseData=data & 0xFFFFFFFF,
                               dwFlags=flags, time=0, dwExtraInfo=0)
        return item

    # ── 对外动作 ────────────────────────────────────────────
    def key_combo(self, codes: Iterable[int]) -> bool:
        """按下全部键后逆序释放，形成一次组合键。"""
        seq = tuple(codes)
        if not seq:
            return False
        self.sent.append(("keys", seq))
        inputs = [self._key(vk, False) for vk in seq]
        inputs += [self._key(vk, True) for vk in reversed(seq)]
        return self._send(inputs)

    def mouse_button(self, button: str) -> bool:
        spec = _MOUSE_FLAGS.get(button)
        if not spec:
            return False
        down, up, data = spec
        self.sent.append(("mouse", button))
        return self._send([self._mouse(down, data), self._mouse(up, data)])

    def scroll(self, delta: int, horizontal: bool = False) -> bool:
        self.sent.append(("scroll", delta, horizontal))
        flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        return self._send([self._mouse(flag, int(delta))])
