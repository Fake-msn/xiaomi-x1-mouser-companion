"""Win32 常量、结构体与「私有 user32 句柄」工厂。

这是整个项目最关键的一条护栏，直接继承 Mouser v3.7.3 的修复：

    ctypes.windll.user32 是进程级单例；ctypes 把函数原型(argtypes/restype)
    挂在这个句柄对象上，而不是挂在调用点。若两个钩子共用同一句柄并给
    CallNextHookEx 声明不同原型，后声明者会覆盖前者。Mouser v3.7.2 的
    快捷键录制器（键盘钩子）与低级鼠标钩子正是这样互相踩踏，导致
    CallNextHookEx 原型错配、每个鼠标事件进钩子即失败、全会话指针冻结
    (issue #259)。v3.7.3 的修复是让录制器加载自己的私有句柄。

本项目规定：鼠标钩子、键盘录制器、SendInput 注入器、前台窗口识别器
各自调用 private_user32()，绝不共享 windll.user32。
"""
from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes
else:  # 允许在非 Windows 上导入本模块做纯逻辑单测
    class _WinTypes:  # pragma: no cover - 仅用于类型占位
        DWORD = ctypes.c_uint32
        WORD = ctypes.c_uint16
        BOOL = ctypes.c_int
        HWND = ctypes.c_void_p
        HHOOK = ctypes.c_void_p
        HINSTANCE = ctypes.c_void_p
        HANDLE = ctypes.c_void_p
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t
        LPCWSTR = ctypes.c_wchar_p
        POINT = type("POINT", (ctypes.Structure,), {})
    wintypes = _WinTypes()

# ── 钩子 ──────────────────────────────────────────────────────────
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_QUIT = 0x0012

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

XBUTTON1 = 0x0001
XBUTTON2 = 0x0002
LLMHF_INJECTED = 0x00000001
LLKHF_INJECTED = 0x00000010
LLKHF_EXTENDED = 0x00000001

# ── 进程 / 窗口 ───────────────────────────────────────────────────
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260
WM_INPUT = 0x00FF
WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007
RIDI_DEVICENAME = 0x20000007
RIM_TYPEMOUSE = 0
ERROR_ALREADY_EXISTS = 183

# ── SendInput ─────────────────────────────────────────────────────
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100

# ── 常用虚拟键 ────────────────────────────────────────────────────
VK = {
    "CTRL": 0x11, "CONTROL": 0x11, "SHIFT": 0x10, "ALT": 0x12,
    "WIN": 0x5B, "LWIN": 0x5B, "TAB": 0x09, "ENTER": 0x0D,
    "ESC": 0x1B, "SPACE": 0x20, "BACKSPACE": 0x08, "DELETE": 0x2E,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDN": 0x22,
    "F5": 0x74, "F6": 0x75, "F11": 0x7A, "F12": 0x7B,
    "PRTSC": 0x2C, "VOLUME_UP": 0xAF, "VOLUME_DOWN": 0xAE,
    "VOLUME_MUTE": 0xAD, "MEDIA_PLAY_PAUSE": 0xB3,
    "MEDIA_NEXT_TRACK": 0xB0, "MEDIA_PREV_TRACK": 0xB1,
    "L": 0x4C, "S": 0x53, "E": 0x45, "W": 0x57, "T": 0x54,
    "P": 0x50, "C": 0x43, "V": 0x56, "X": 0x58, "Z": 0x5A,
    "A": 0x41, "F": 0x46, "N": 0x4E, "O": 0x4F, "R": 0x52,
    "D": 0x44, "G": 0x47, "H": 0x48, "J": 0x4A, "K": 0x4B,
    "Q": 0x51, "U": 0x55, "I": 0x49, "M": 0x4D, "B": 0x42,
    "Y": 0x59,
}
for _d in "0123456789":
    VK[_d] = ord(_d)
for _i in range(1, 13):
    VK[f"F{_i}"] = 0x6F + _i

VK_NAMES = {v: k for k, v in VK.items()}


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    """WH_MOUSE_LL 的 lParam。dwExtraInfo 是值而非指针，绝不能解引用。"""

    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def private_user32():
    """返回一个本模块独占的 user32 句柄，避免 ctypes 原型互相覆盖。"""
    if not IS_WINDOWS:
        return None
    return ctypes.WinDLL("user32", use_last_error=True)


def private_kernel32():
    if not IS_WINDOWS:
        return None
    return ctypes.WinDLL("kernel32", use_last_error=True)


def hiword(dword: int) -> int:
    value = (int(dword) >> 16) & 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def loword(dword: int) -> int:
    return int(dword) & 0xFFFF
