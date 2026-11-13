"""小米 X1 的按键模型。

按 G-HUB 的 Skin\\XML\\DeviceXml\\mousedevice.xml 与公开评测，X1 的可定义键位为：
左键、右键、中键（滚轮按下）、前进、后退、DPI 功能键、滚轮上下、滚轮左右。

重要边界：
* WH_MOUSE_LL 只能看到标准鼠标消息。DPI 功能键由厂商固件处理，
  通常不产生标准鼠标消息，因此标记 hardware_only，伴生层不接管。
* 左/右键是 PROTECTED：默认且强烈建议不重映射，避免把系统输入锁死。
* 所有键位默认映射为 "none"（透传），这是「原有功能不受影响」的第一道保障。
"""
from __future__ import annotations

# 可由低级鼠标钩子观察到的键
BUTTON_KEYS = (
    "left", "right", "middle",
    "xbutton1",   # 后退 / Back
    "xbutton2",   # 前进 / Forward
    "wheel_up", "wheel_down",
    "hscroll_left", "hscroll_right",
    "dpi_switch",  # 仅占位，见 hardware_only
)

# 左/右键不允许被伴生层吞掉
PROTECTED = frozenset({"left", "right"})

# 固件独占、钩子无法观察到的键
HARDWARE_ONLY = frozenset({"dpi_switch"})

# 用户可声明归属的键（ownership: companion / ghub）
OWNable = tuple(b for b in BUTTON_KEYS if b not in PROTECTED and b not in HARDWARE_ONLY)

BUTTON_LABELS = {
    "left": "左键",
    "right": "右键",
    "middle": "中键（滚轮按下）",
    "xbutton1": "侧键·后退 (XButton1)",
    "xbutton2": "侧键·前进 (XButton2)",
    "wheel_up": "滚轮向上",
    "wheel_down": "滚轮向下",
    "hscroll_left": "滚轮左倾",
    "hscroll_right": "滚轮右倾",
    "dpi_switch": "DPI 功能键（固件独占）",
}

# button -> 该键会产生哪些事件键（与 MouseEvent.key 对齐）
BUTTON_TO_EVENT_KEYS = {
    "left": ("left:down", "left:up"),
    "right": ("right:down", "right:up"),
    "middle": ("middle:down", "middle:up"),
    "xbutton1": ("xbutton1:down", "xbutton1:up"),
    "xbutton2": ("xbutton2:down", "xbutton2:up"),
    "wheel_up": ("wheel_up:wheel",),
    "wheel_down": ("wheel_down:wheel",),
    "hscroll_left": ("hscroll_left:wheel",),
    "hscroll_right": ("hscroll_right:wheel",),
    "dpi_switch": (),
}

# Windows 消息 -> (button, kind)
MESSAGE_MAP = {
    0x0201: ("left", "down"),
    0x0202: ("left", "up"),
    0x0204: ("right", "down"),
    0x0205: ("right", "up"),
    0x0207: ("middle", "down"),
    0x0208: ("middle", "up"),
    0x020B: ("xbutton1", "down"),   # XBUTTON2 在运行时改写
    0x020C: ("xbutton1", "up"),
}

DEFAULT_MAPPINGS = {key: "none" for key in BUTTON_KEYS}


def events_for(button: str) -> tuple[str, ...]:
    """返回该键需要被吞掉的事件键集合。"""
    return BUTTON_TO_EVENT_KEYS.get(button, ())


def is_ownable(button: str) -> bool:
    return button in OWNable
