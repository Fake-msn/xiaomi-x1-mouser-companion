"""HID / Raw Input 设备枚举与 X1 白名单。

说明一个诚实的边界：WH_MOUSE_LL 的事件**不携带设备标识**，
因此无法在钩子回调里逐事件判断「这一下是不是 X1 发出的」。
本模块的做法是：
  * 启动时枚举全部 Raw Input 设备，找出疑似 X1 的 VID/PID；
  * device_filter_enabled=true 时，仅当白名单中的设备当前在线才启用伴生层；
  * 默认关闭过滤（对所有鼠标生效），并在 README 明确标注该限制。

绝不打开设备句柄、绝不写 Feature Report —— 设备侧始终归 G-HUB。
"""
from __future__ import annotations

import ctypes
import re
from typing import Any

from .winapi import IS_WINDOWS, RIDI_DEVICENAME, RIM_TYPEMOUSE, private_user32

# 小米常见 USB VID；X1 由 ODM（Evision）代工，也可能使用 ODM 自有 VID，
# 因此这里只作为「疑似」线索，最终以 tools/detect_device.py 的实测输出为准。
XIAOMI_VIDS = frozenset({"2717", "18d1"})
_X1_HINTS = ("x1", "xiaomi", "mi_mouse", "evision", "g-hub")

_VID_PID_RE = re.compile(r"VID[_#]([0-9A-Fa-f]{4})&(?:PID[_#]([0-9A-Fa-f]{4}))?")
_HID_PATH_RE = re.compile(r"\\vid_[0-9a-fA-F]{4}", re.IGNORECASE)


def parse_vid_pid(device_name: str) -> dict[str, str] | None:
    """从 '\\\\?\\HID#VID_XXXX&PID_XXXX&MI_00#...' 抽出 vid/pid（XXXX 为 4 位十六进制占位）。"""
    if not device_name:
        return None
    match = _VID_PID_RE.search(device_name)
    if not match:
        return None
    return {"vid": match.group(1).upper(), "pid": (match.group(2) or "").upper(),
            "raw": device_name}


def device_token(device_name: str) -> str:
    info = parse_vid_pid(device_name)
    if not info:
        return ""
    token = f"VID_{info['vid']}"
    if info["pid"]:
        token += f"&PID_{info['pid']}"
    return token


def looks_like_x1(device_name: str) -> bool:
    info = parse_vid_pid(device_name)
    lowered = device_name.lower()
    if info and info["vid"] in XIAOMI_VIDS:
        return True
    return any(hint in lowered for hint in _X1_HINTS)


def match_whitelist(device_name: str, whitelist: list[str]) -> bool:
    if not whitelist:
        return False
    token = device_token(device_name)
    lowered = device_name.lower()
    for entry in whitelist:
        if not isinstance(entry, str) or not entry.strip():
            continue
        e = entry.strip().lower()
        if (token and e == token.lower()) or e in lowered:
            return True
    return False


if IS_WINDOWS:
    import ctypes.wintypes as wt

    class RAWINPUTDEVICELIST(ctypes.Structure):
        _fields_ = [("hDevice", wt.HANDLE), ("dwType", wt.DWORD)]


def enumerate_raw_input_devices() -> list[dict[str, Any]]:
    """只读枚举，返回 [{'name','type','vid','pid','token','mouse','x1_candidate'}]。"""
    if not IS_WINDOWS:
        return []
    u = private_user32()
    u.GetRawInputDeviceList.argtypes = [
        ctypes.POINTER(RAWINPUTDEVICELIST), ctypes.POINTER(ctypes.c_uint), ctypes.c_uint]
    u.GetRawInputDeviceList.restype = ctypes.c_uint
    u.GetRawInputDeviceInfoW.argtypes = [
        wt.HANDLE, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    u.GetRawInputDeviceInfoW.restype = ctypes.c_uint

    count = ctypes.c_uint(0)
    if u.GetRawInputDeviceList(None, ctypes.byref(count),
                               ctypes.sizeof(RAWINPUTDEVICELIST)) != 0:
        return []
    if not count.value:
        return []
    items = (RAWINPUTDEVICELIST * count.value)()
    got = u.GetRawInputDeviceList(items, ctypes.byref(count),
                                  ctypes.sizeof(RAWINPUTDEVICELIST))
    if got == ctypes.c_uint(-1).value:
        return []

    result: list[dict[str, Any]] = []
    for item in items[:got]:
        size = ctypes.c_uint(0)
        u.GetRawInputDeviceInfoW(item.hDevice, RIDI_DEVICENAME, None, ctypes.byref(size))
        if not size.value:
            continue
        buf = ctypes.create_unicode_buffer(size.value + 1)
        u.GetRawInputDeviceInfoW(item.hDevice, RIDI_DEVICENAME, buf, ctypes.byref(size))
        name = buf.value
        info = parse_vid_pid(name) or {}
        result.append({
            "name": name,
            "type": int(item.dwType),
            "mouse": int(item.dwType) == RIM_TYPEMOUSE,
            "vid": info.get("vid", ""),
            "pid": info.get("pid", ""),
            "token": device_token(name),
            "x1_candidate": looks_like_x1(name),
        })
    return result


def whitelist_satisfied(cfg: dict, devices: list[dict] | None = None) -> tuple[bool, str]:
    """共存护栏之一：设备过滤开启时，白名单设备必须在线。

    返回 (是否满足, 说明)。过滤关闭时恒为 True。
    """
    settings = cfg.get("settings", {})
    if not settings.get("device_filter_enabled"):
        return True, "设备过滤未启用（对所有鼠标生效）"
    whitelist = settings.get("device_whitelist") or []
    if not whitelist:
        return False, "已启用设备过滤但白名单为空 —— 为安全起见不拦截任何事件"
    devices = devices if devices is not None else enumerate_raw_input_devices()
    hits = [d for d in devices if match_whitelist(d["name"], whitelist)]
    if not hits:
        return False, "白名单中的 X1 设备当前未在线"
    return True, f"检测到 {len(hits)} 个白名单设备"
