"""Windows 动作库（48 个内置动作 + 自定义组合键）。

移植自 Mouser v3.7.3 的 Available actions 表设计（MIT），按 Windows 精简：
剔除 Mission Control / App Exposé / Launchpad 等 macOS 专属动作，
新增 Win+D / Task View / 虚拟桌面切换 / Win+Shift+S 截图等 Windows 项。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .winapi import VK

CATEGORY_LABELS = {
    "navigation": "窗口导航",
    "browser": "浏览器",
    "editing": "编辑",
    "media": "媒体",
    "mouse": "鼠标按键",
    "system": "系统",
    "scroll": "滚动",
    "special": "特殊",
    "custom": "自定义快捷键",
}


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    category: str
    vks: tuple[str, ...] = ()
    mouse: str | None = None
    scroll: int | None = None
    special: str | None = None

    @property
    def is_special(self) -> bool:
        return self.special is not None


def _a(action_id, label, category, vks=(), *, mouse=None, scroll=None, special=None) -> Action:
    return Action(action_id, label, category, tuple(vks), mouse, scroll, special)


_ACTIONS_LIST: list[Action] = [
    # ── 窗口导航 ───────────────────────────────────────────────
    _a("alt_tab", "切换窗口 (Alt+Tab)", "navigation", ("ALT", "TAB")),
    _a("alt_shift_tab", "反向切换窗口 (Alt+Shift+Tab)", "navigation", ("ALT", "SHIFT", "TAB")),
    _a("win_d", "显示桌面 (Win+D)", "navigation", ("WIN", "D")),
    _a("task_view", "任务视图 (Win+Tab)", "navigation", ("WIN", "TAB")),
    _a("next_desktop", "下一个虚拟桌面", "navigation", ("WIN", "CTRL", "RIGHT")),
    _a("prev_desktop", "上一个虚拟桌面", "navigation", ("WIN", "CTRL", "LEFT")),
    _a("page_up", "Page Up", "navigation", ("PGUP",)),
    _a("page_down", "Page Down", "navigation", ("PGDN",)),
    _a("home", "Home", "navigation", ("HOME",)),
    _a("end", "End", "navigation", ("END",)),
    _a("escape", "Esc", "navigation", ("ESC",)),
    # ── 浏览器 ─────────────────────────────────────────────────
    _a("browser_back", "后退 (Alt+Left)", "browser", ("ALT", "LEFT")),
    _a("browser_forward", "前进 (Alt+Right)", "browser", ("ALT", "RIGHT")),
    _a("close_tab", "关闭标签 (Ctrl+W)", "browser", ("CTRL", "W")),
    _a("new_tab", "新建标签 (Ctrl+T)", "browser", ("CTRL", "T")),
    _a("next_tab", "下一个标签 (Ctrl+Tab)", "browser", ("CTRL", "TAB")),
    _a("prev_tab", "上一个标签 (Ctrl+Shift+Tab)", "browser", ("CTRL", "SHIFT", "TAB")),
    _a("refresh", "刷新 (F5)", "browser", ("F5",)),
    _a("address_bar", "定位地址栏 (Ctrl+L)", "browser", ("CTRL", "L")),
    # ── 编辑 ───────────────────────────────────────────────────
    _a("copy", "复制 (Ctrl+C)", "editing", ("CTRL", "C")),
    _a("paste", "粘贴 (Ctrl+V)", "editing", ("CTRL", "V")),
    _a("cut", "剪切 (Ctrl+X)", "editing", ("CTRL", "X")),
    _a("undo", "撤销 (Ctrl+Z)", "editing", ("CTRL", "Z")),
    _a("redo", "重做 (Ctrl+Y)", "editing", ("CTRL", "Y")),
    _a("select_all", "全选 (Ctrl+A)", "editing", ("CTRL", "A")),
    _a("save", "保存 (Ctrl+S)", "editing", ("CTRL", "S")),
    _a("find", "查找 (Ctrl+F)", "editing", ("CTRL", "F")),
    # ── 媒体 ───────────────────────────────────────────────────
    _a("volume_up", "音量增", "media", ("VOLUME_UP",)),
    _a("volume_down", "音量减", "media", ("VOLUME_DOWN",)),
    _a("volume_mute", "静音切换", "media", ("VOLUME_MUTE",)),
    _a("play_pause", "播放 / 暂停", "media", ("MEDIA_PLAY_PAUSE",)),
    _a("next_track", "下一曲", "media", ("MEDIA_NEXT_TRACK",)),
    _a("prev_track", "上一曲", "media", ("MEDIA_PREV_TRACK",)),
    # ── 鼠标按键 ───────────────────────────────────────────────
    _a("mouse_left", "左键", "mouse", mouse="left"),
    _a("mouse_right", "右键", "mouse", mouse="right"),
    _a("mouse_middle", "中键", "mouse", mouse="middle"),
    _a("mouse_back", "后退 (Mouse4)", "mouse", mouse="xbutton1"),
    _a("mouse_forward", "前进 (Mouse5)", "mouse", mouse="xbutton2"),
    # ── 系统 ───────────────────────────────────────────────────
    _a("screenshot", "区域截图 (Win+Shift+S)", "system", ("WIN", "SHIFT", "S")),
    _a("lock_screen", "锁屏 (Win+L)", "system", ("WIN", "L")),
    _a("win_search", "搜索 (Win+S)", "system", ("WIN", "S")),
    _a("win_explorer", "资源管理器 (Win+E)", "system", ("WIN", "E")),
    _a("win_settings", "设置 (Win+I)", "system", ("WIN", "I")),
    # ── 滚动 ───────────────────────────────────────────────────
    _a("scroll_up", "向上滚动", "scroll", scroll=120),
    _a("scroll_down", "向下滚动", "scroll", scroll=-120),
    # ── 特殊 ───────────────────────────────────────────────────
    _a("none", "不操作（透传）", "special", special="none"),
    _a("gesture_swipe", "启用四向滑动手势", "special", special="gesture"),
    _a("activate_actions_ring", "启用动作环", "special", special="ring"),
]

ACTIONS: dict[str, Action] = {a.id: a for a in _ACTIONS_LIST}
MODIFIER_NAMES = frozenset({"CTRL", "CONTROL", "SHIFT", "ALT", "WIN", "LWIN"})
CUSTOM_PREFIX = "custom:"


def actions_by_category() -> dict[str, list[Action]]:
    out: dict[str, list[Action]] = {key: [] for key in CATEGORY_LABELS}
    for action in _ACTIONS_LIST:
        out[action.category].append(action)
    return out


def parse_shortcut_string(text: str) -> tuple[int, ...]:
    """'Ctrl+Shift+P' -> (0x11, 0x10, 0x50)。未知键名返回空元组。"""
    if not isinstance(text, str):
        return ()
    parts = [p.strip().upper() for p in text.replace(" ", "").split("+") if p.strip()]
    codes: list[int] = []
    for part in parts:
        code = VK.get(part)
        if code is None:
            if part.startswith("0X"):
                try:
                    code = int(part, 16)
                except ValueError:
                    return ()
            elif part.isdigit() and len(part) == 1:
                code = ord(part)
            else:
                return ()
        if code not in codes:
            codes.append(code)
    return tuple(codes)


def format_shortcut(vks: Iterable[int]) -> str:
    """虚拟键码 -> 可读文本。"""
    from .winapi import VK_NAMES
    pretty = {"CTRL": "Ctrl", "CONTROL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt", "WIN": "Win",
              "LWIN": "Win", "MEDIA_PLAY_PAUSE": "Play/Pause", "VOLUME_UP": "Vol+",
              "VOLUME_DOWN": "Vol-", "VOLUME_MUTE": "Mute"}
    names = []
    for code in vks:
        raw = VK_NAMES.get(code, f"0x{code:02X}")
        names.append(pretty.get(raw, raw.replace("_", " ").title()))
    return " + ".join(names)


def shortcut_to_id(vks: Iterable[int]) -> str:
    """把录制到的键码编码成配置里的动作 ID。"""
    codes = tuple(vks)
    if not codes:
        return "none"
    # 修饰键在前，其余按键按码值排序，保证同一组合总能得到同一个 ID
    mods = tuple(sorted(c for c in codes if c in (VK["CTRL"], VK["SHIFT"], VK["ALT"], VK["WIN"])))
    others = tuple(sorted(c for c in codes if c not in mods))
    ordered = mods + others
    return CUSTOM_PREFIX + "+".join(f"0x{c:02X}" for c in ordered)


def parse_custom_action(action_id: str) -> tuple[int, ...]:
    """'custom:0x11+0x50' -> (0x11, 0x50)。"""
    if not isinstance(action_id, str) or not action_id.startswith(CUSTOM_PREFIX):
        return ()
    body = action_id[len(CUSTOM_PREFIX):]
    codes = []
    for part in body.split("+"):
        part = part.strip()
        if not part:
            continue
        try:
            codes.append(int(part, 16) if part.lower().startswith("0x") else int(part, 10))
        except ValueError:
            return ()
    return tuple(codes)


def resolve_action(action_id: str) -> Action | None:
    if action_id in ACTIONS:
        return ACTIONS[action_id]
    codes = parse_custom_action(action_id)
    if codes:
        return Action(action_id, f"自定义：{format_shortcut(codes)}", "custom",
                      vks=tuple(f"0x{c:02X}" for c in codes))
    return None


def is_supported_action(action_id: str) -> bool:
    return resolve_action(action_id) is not None


def all_action_ids() -> tuple[str, ...]:
    return tuple(ACTIONS) + ("custom:0x11+0x50",)
