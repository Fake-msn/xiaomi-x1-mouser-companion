"""前台应用识别（Windows）。

移植自 Mouser v3.7.3 core/app_detector.py 的实现思路（MIT），保留三处关键鲁棒性：
1. 用完整 exe 路径作为稳定身份，而非只看窗口标题。
2. UWP / ApplicationFrameHost：枚举子窗口找到真正的应用进程，否则返回空元组
   让调用方「保持上一档」，避免误切。
3. explorer.exe 的瞬态窗口分类：任务栏缩略图、Alt-Tab、右键菜单等会被直接跳过。
   上游 issue #252 曾因对每个瞬态窗口做昂贵的全窗口枚举而拖垮鼠标钩子。

本模块持有**自己独占的** user32/kernel32 句柄（见 winapi.py 说明）。
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
from typing import Callable, Iterable

from .winapi import (IS_WINDOWS, PROCESS_QUERY_LIMITED_INFORMATION, MAX_PATH,
                     private_user32, private_kernel32)

# 真正的 Explorer / 桌面 / 任务栏：应识别为 explorer.exe
EXPLORER_SHELL_CLASSES = frozenset({
    "CabinetWClass", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Progman", "WorkerW",
})

# 一闪而过的 shell 表面：不值得切档，且在它们上面做 UWP 解析会拖垮钩子
TRANSIENT_EXPLORER_CLASSES = frozenset({
    "TaskListThumbnailWnd", "ForegroundStaging", "XamlExplorerHostIslandWindow",
    "Xaml_WindowedPopupClass", "#32768", "TaskSwitcherWnd",
    "TaskSwitcherOverlayWnd", "MultitaskingViewFrame", "Windows.UI.Core.CoreWindow",
    "Shell_InputSwitchTopLevelWindow", "tooltips_class32",
})

WINDOW_CLASS_SKIP = frozenset(TRANSIENT_EXPLORER_CLASSES)

if IS_WINDOWS:
    import ctypes.wintypes as wt

    _u32 = private_user32()
    _k32 = private_kernel32()

    _u32.GetForegroundWindow.restype = wt.HWND
    _u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wt.DWORD
    _k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _k32.CloseHandle.restype = wt.BOOL
    _k32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
    _k32.QueryFullProcessImageNameW.restype = wt.BOOL
    _u32.GetClassNameW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    _u32.GetClassNameW.restype = ctypes.c_int
    _u32.IsWindowVisible.argtypes = [wt.HWND]
    _u32.IsWindowVisible.restype = wt.BOOL

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, ctypes.c_ssize_t)
    _u32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, ctypes.c_ssize_t]
    _u32.EnumChildWindows.restype = wt.BOOL
    _u32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_ssize_t]
    _u32.EnumWindows.restype = wt.BOOL

    _unresolved_explorer_key: list = [None]

    def _path_from_pid(pid: int) -> str | None:
        handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(MAX_PATH)
            size = wt.DWORD(MAX_PATH)
            if _k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            _k32.CloseHandle(handle)
        return None

    def _window_class(hwnd) -> str:
        buf = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _resolve_uwp_child(hwnd) -> str | None:
        host_pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(host_pid))
        result = [None]

        def callback(child, _lparam):
            pid = wt.DWORD()
            _u32.GetWindowThreadProcessId(child, ctypes.byref(pid))
            if pid.value != host_pid.value:
                path = _path_from_pid(pid.value)
                if path and os.path.basename(path).lower() != "applicationframehost.exe":
                    result[0] = path
                    return False
            return True

        cb = WNDENUMPROC(callback)
        _u32.EnumChildWindows(hwnd, cb, 0)
        return result[0]

    def _find_uwp_app_global() -> str | None:
        result = [None]

        def callback(hwnd, _lparam):
            if not _u32.IsWindowVisible(hwnd):
                return True
            pid = wt.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return True
            path = _path_from_pid(pid.value)
            if path and os.path.basename(path).lower() == "applicationframehost.exe":
                real = _resolve_uwp_child(hwnd)
                if real:
                    result[0] = real
                    return False
            return True

        cb = WNDENUMPROC(callback)
        _u32.EnumWindows(cb, 0)
        return result[0]


def classify_explorer_window(window_class: str, window_key=None,
                             last_unresolved_key=None) -> str:
    """纯逻辑，便于单测。返回 explorer / skip / resolve。"""
    if window_class in EXPLORER_SHELL_CLASSES:
        return "explorer"
    if window_class in TRANSIENT_EXPLORER_CLASSES:
        return "skip"
    if window_key and last_unresolved_key and window_key == last_unresolved_key:
        return "skip"
    return "resolve"


def _identities_from_path(path: str) -> tuple[str, ...]:
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    return tuple(dict.fromkeys(filter(None, (path, base, stem))))


def get_foreground_identities() -> tuple[str, ...]:
    """返回当前前台应用的身份候选；无法可靠解析时返回空元组（保持上一档）。"""
    if not IS_WINDOWS:
        return ()
    try:
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return ()
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ()
        path = _path_from_pid(pid.value)
        if not path:
            return ()
        base = os.path.basename(path).lower()

        if base == "applicationframehost.exe":
            real = _resolve_uwp_child(hwnd)
            return _identities_from_path(real) if real else ()

        if base == "explorer.exe":
            cls = _window_class(hwnd)
            key = (hwnd, cls)
            verdict = classify_explorer_window(cls, key, _unresolved_explorer_key[0])
            if verdict == "explorer":
                return _identities_from_path(path)
            if verdict == "skip":
                return ()
            real = _resolve_uwp_child(hwnd) or _find_uwp_app_global()
            if not real:
                _unresolved_explorer_key[0] = key
                return ()
            return _identities_from_path(real)

        return _identities_from_path(path)
    except Exception:
        return ()


class AppDetector:
    """每 interval 秒轮询前台窗口，变化时回调 on_change(identities)。"""

    def __init__(self, on_change: Callable[[Iterable[str]], None], interval: float = 0.3):
        self._on_change = on_change
        self._interval = max(0.05, float(interval))
        self._last: tuple[str, ...] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True, name="AppDetector")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                identity = get_foreground_identities()
                if identity and identity != self._last:
                    self._last = identity
                    self._on_change(identity)
            except Exception:
                pass
            self._stop.wait(self._interval)
