"""配置模型：纯 JSON、原子写、版本迁移、档位解析、共存护栏。

移植自 Mouser v3.7.3 core/config.py 的**设计**（MIT），实现为本项目独立代码：
* profiles.<name>.apps[] 用进程可执行文件名 / 完整路径 / 显示别名做匹配，空数组 = 兜底档。
* mappings 为「物理按键 -> 动作 ID」。
* _atomic_write_json: mkstemp + fsync + os.replace，避免写一半崩溃损坏配置。

本项目额外加了 Mouser 没有的两样东西：
1. settings.ownership —— 按键归属表。默认全部 "ghub"（透传），
   只有用户显式声明 companion 的按键才会被钩子吞掉。这是兼容性的核心。
2. import_ghub_applink —— 只读导入 G-HUB 的 AppLink/AppName/AppPath，绝不写回。
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from typing import Any, Iterable

from . import CONFIG_DIR_NAME, CONFIG_FILE_NAME
from . import buttons
from .app_catalog import match_profile_apps

CONFIG_VERSION = 1

DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "schema": "x1-companion/1",
    "active_profile": "default",
    "profiles": {
        "default": {
            "label": "默认（所有应用）",
            "apps": [],          # 空 = 兜底档，匹配一切
            "priority": 0,
            "mappings": dict(buttons.DEFAULT_MAPPINGS),
            "gestures": {},      # button -> {left/right/up/down/tap: action_id}
            "actions_ring_slots": [],
        },
    },
    "settings": {
        "start_minimized": False,
        "start_at_login": False,
        "language": "zh-CN",
        # ── 共存护栏 ──────────────────────────────────────────
        "bypass": False,              # 全局一键旁路
        "game_mode": False,           # 竞技/反作弊场景全透传
        "ownership": {},              # button -> "companion" | "ghub"（缺省 ghub）
        "device_filter_enabled": False,
        "device_whitelist": [],       # ["VID_XXXX&PID_XXXX", ...]
        "coexist_delay_ms": 1500,     # 等 G-HUB 先就绪
        "coexist_detect_ghub": True,
        # ── 行为 ──────────────────────────────────────────────
        "gesture_threshold_px": 25,
        "gesture_commit_window_ms": 400,
        "gesture_cross_ratio": 0.5,
        "poll_interval_s": 0.3,
        "log_level": "info",
    },
}


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, CONFIG_DIR_NAME)


def config_path(path: str | None = None) -> str:
    return path or os.path.join(config_dir(), CONFIG_FILE_NAME)


def _atomic_write_json(path: str, obj: Any) -> None:
    target = os.path.realpath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _merge_defaults(value: Any, default: Any) -> Any:
    """递归补齐缺失键；已有的用户值原样保留。"""
    if isinstance(default, dict):
        out = copy.deepcopy(default)
        if isinstance(value, dict):
            for key, val in value.items():
                out[key] = _merge_defaults(val, default[key]) if key in default else copy.deepcopy(val)
        return out
    return copy.deepcopy(value) if value is not None else copy.deepcopy(default)


def _validate_types(cfg: dict) -> dict:
    """把明显损坏的值收敛回默认值，防止钩子层拿到奇怪类型。"""
    if not isinstance(cfg.get("profiles"), dict) or not cfg["profiles"]:
        cfg["profiles"] = copy.deepcopy(DEFAULT_CONFIG["profiles"])
    for name, profile in list(cfg["profiles"].items()):
        if not isinstance(profile, dict):
            del cfg["profiles"][name]
            continue
        profile.setdefault("label", name)
        profile.setdefault("apps", [])
        profile["mappings"] = _merge_defaults(profile.get("mappings"), buttons.DEFAULT_MAPPINGS)
        # 丢弃不认识的键位，避免脏配置让钩子吞掉未知事件
        for key in list(profile["mappings"]):
            if key not in buttons.BUTTON_KEYS:
                del profile["mappings"][key]
        if not isinstance(profile.get("apps"), list):
            profile["apps"] = []
        if not isinstance(profile.get("priority"), int):
            profile["priority"] = 0
        if not isinstance(profile.get("gestures"), dict):
            profile["gestures"] = {}
    if cfg.get("active_profile") not in cfg["profiles"]:
        cfg["active_profile"] = "default" if "default" in cfg["profiles"] else next(iter(cfg["profiles"]))
    settings = cfg.setdefault("settings", {})
    if not isinstance(settings.get("ownership"), dict):
        settings["ownership"] = {}
    if not isinstance(settings.get("device_whitelist"), list):
        settings["device_whitelist"] = []
    for flag in ("bypass", "game_mode", "device_filter_enabled", "start_minimized",
                 "start_at_login", "coexist_detect_ghub"):
        if not isinstance(settings.get(flag), bool):
            settings[flag] = DEFAULT_CONFIG["settings"][flag]
    return cfg


def _migrate(cfg: dict) -> dict:
    """未来版本升级时在此追加迁移；当前只做版本标记归一。"""
    version = cfg.get("version", 0)
    if not isinstance(version, int) or version < 1:
        cfg["version"] = 1
    cfg["schema"] = "x1-companion/1"
    return cfg


def load_config(path: str | None = None) -> dict:
    file = config_path(path)
    if not os.path.exists(file):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(file, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            raise ValueError("config root is not an object")
    except (OSError, ValueError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)
    return _validate_types(_merge_defaults(_migrate(cfg), DEFAULT_CONFIG))


def save_config(cfg: dict, path: str | None = None) -> None:
    _atomic_write_json(config_path(path), cfg)


def get_profile(cfg: dict, name: str | None = None) -> tuple[str, dict]:
    profiles = cfg["profiles"]
    key = name or cfg.get("active_profile", "default")
    if key not in profiles:
        key = "default" if "default" in profiles else next(iter(profiles))
    return key, profiles[key]


def resolve_profile(cfg: dict, identities: Iterable[str]) -> tuple[str, dict]:
    """按前台应用身份选出应生效的档位。

    优先级：显式 priority 降序 > 绑定规则更具体者 > 名称稳定排序。
    apps 为空的档位是兜底档；若没有任何档位命中，返回兜底档（没有则用 default）。
    """
    ids = [str(i) for i in identities if i]
    profiles = cfg["profiles"]
    fallback = None
    for name in sorted(profiles):
        if not profiles[name].get("apps"):
            fallback = name
            break
    if fallback is None:
        fallback = "default" if "default" in profiles else next(iter(profiles))

    candidates = []
    for name, profile in profiles.items():
        apps = profile.get("apps") or []
        if not apps:
            continue
        if match_profile_apps(apps, ids):
            candidates.append((int(profile.get("priority", 0)), len(apps), name))
    if not candidates:
        return fallback, profiles[fallback]
    # priority 越高越优先；同优先级下规则更具体者优先；名称倒序保证确定性
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    winner = candidates[0][2]
    return winner, profiles[winner]


def build_blocked_events(cfg: dict, profile: dict | None = None) -> frozenset[str]:
    """共存护栏的核心：算出钩子**允许吞掉**的事件键集合。

    只有同时满足下列条件才吞：
      1. 未开启 bypass / game_mode；
      2. 该键在 ownership 中被显式声明为 companion（缺省是 ghub = 透传）；
      3. 该键不是 PROTECTED / HARDWARE_ONLY；
      4. 当前档位给它配了非 "none" 的动作。
    任何不满足，事件一律 CallNextHookEx 放行给 G-HUB 与系统。
    """
    settings = cfg.get("settings", {})
    if settings.get("bypass") or settings.get("game_mode"):
        return frozenset()
    if profile is None:
        _, profile = get_profile(cfg)
    ownership = settings.get("ownership", {})
    blocked: set[str] = set()
    for button, action in profile.get("mappings", {}).items():
        if action in (None, "", "none"):
            continue
        if button in buttons.PROTECTED or button in buttons.HARDWARE_ONLY:
            continue
        if ownership.get(button, "ghub") != "companion":
            continue
        blocked.update(buttons.events_for(button))
    return frozenset(blocked)


def set_ownership(cfg: dict, button: str, owner: str) -> dict:
    if not buttons.is_ownable(button):
        raise ValueError(f"按键 {button!r} 不可声明归属（受保护或固件独占）")
    if owner not in ("companion", "ghub"):
        raise ValueError("owner 必须是 companion 或 ghub")
    cfg.setdefault("settings", {}).setdefault("ownership", {})[button] = owner
    return cfg


# ── 导入 / 导出 ────────────────────────────────────────────────────
_MOUSER_BUTTON_MAP = {
    "middle": "middle", "xbutton1": "xbutton1", "xbutton2": "xbutton2",
    "hscroll_left": "hscroll_left", "hscroll_right": "hscroll_right",
    "mode_shift": "middle", "dpi_switch": "dpi_switch",
    "thumb_button": "xbutton1",
}
# gesture*/actions_ring* 依赖 HID++，一律丢弃
_MOUSER_SKIP_PREFIXES = ("gesture_", "actions_ring", "sense_")


def import_mouser_config(data: dict, *, actions_supported: set[str] | None = None) -> tuple[dict, dict]:
    """把 Mouser v3.7.3 的 config.json 转成 X1 Companion 配置。

    只迁移「跨应用档位定义 + 按键映射 + 自定义快捷键」这一可适配子集；
    罗技设备发现 / HID++ / SmartShift / 手势环等一概不导入。
    """
    from .actions import is_supported_action

    supported = actions_supported if actions_supported is not None else None
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    report: dict[str, Any] = {"profiles": 0, "mappings": 0, "skipped_buttons": [], "skipped_actions": []}

    for name, src in (data.get("profiles") or {}).items():
        if not isinstance(src, dict):
            continue
        apps = [a for a in (src.get("apps") or []) if isinstance(a, str)]
        mappings = dict(buttons.DEFAULT_MAPPINGS)
        gestures: dict[str, dict] = {}
        for key, action in (src.get("mappings") or {}).items():
            if not isinstance(key, str) or key.startswith(_MOUSER_SKIP_PREFIXES) or key.endswith("_tap"):
                report["skipped_buttons"].append(key)
                continue
            target = _MOUSER_BUTTON_MAP.get(key)
            if target is None:
                report["skipped_buttons"].append(key)
                continue
            if target in buttons.PROTECTED or target in buttons.HARDWARE_ONLY:
                report["skipped_buttons"].append(key)
                continue
            if not isinstance(action, str):
                continue
            if action == "gesture_swipe":
                # 上游的 HID++ 原生手势方向键不适用于 X1；转成 OS 手势的空模板
                gestures[target] = {d: "none" for d in ("left", "right", "up", "down", "tap")}
                continue
            if supported is not None:
                ok = action in supported
            else:
                ok = action == "none" or is_supported_action(action)
            if not ok:
                report["skipped_actions"].append(action)
                continue
            mappings[target] = action
            report["mappings"] += 1
        cfg["profiles"][name] = {
            "label": src.get("label") or name,
            "apps": apps,
            "priority": int(src.get("priority", 0)) if isinstance(src.get("priority"), int) else 0,
            "mappings": mappings,
            "gestures": gestures,
            "actions_ring_slots": [],
        }
        report["profiles"] += 1

    if "default" not in cfg["profiles"]:
        cfg["profiles"]["default"] = copy.deepcopy(DEFAULT_CONFIG["profiles"]["default"])
    cfg["active_profile"] = "default"
    # 导入的档位默认仍由 G-HUB  owning —— 用户必须显式声明才会真正接管
    return _validate_types(_merge_defaults(cfg, DEFAULT_CONFIG)), report


def import_ghub_applink(data: dict) -> tuple[dict, dict]:
    """只读地从 G-HUB 的 Mouse_*.json 抽取 AppLink/AppName/AppPath。

    绝不修改或写回厂商文件。返回 (部分配置, 报告)，供调用方合并。
    """
    report: dict[str, Any] = {"found": False, "app": "", "path": "", "reason": ""}
    linked = bool(data.get("AppLink"))
    name = str(data.get("AppName") or "").strip()
    path = str(data.get("AppPath") or "").strip()
    if not linked:
        report["reason"] = "AppLink 为 false，G-HUB 未启用应用关联"
        return {}, report
    spec = path or name
    if not spec:
        report["reason"] = "AppLink 为 true 但 AppName/AppPath 均为空"
        return {}, report
    label = str(data.get("profilename") or name or os.path.basename(path) or "G-HUB 关联档")
    profile = {
        "label": f"{label}（自 G-HUB 导入）",
        "apps": [spec],
        "priority": 10,
        "mappings": dict(buttons.DEFAULT_MAPPINGS),
        "gestures": {},
        "actions_ring_slots": [],
    }
    report.update({"found": True, "app": name, "path": path})
    return {"profiles": {_safe_profile_name(label): profile}}, report


def _safe_profile_name(label: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", label).strip("_")
    return cleaned or "ghub_linked"


def export_config(cfg: dict) -> str:
    return json.dumps(cfg, indent=2, ensure_ascii=False)


def merge_profiles(cfg: dict, extra: dict) -> dict:
    """把 import_ghub_applink 之类的片段安全合并进现有配置。"""
    for name, profile in (extra.get("profiles") or {}).items():
        cfg.setdefault("profiles", {})[name] = profile
    return _validate_types(_merge_defaults(cfg, DEFAULT_CONFIG))
