"""应用目录：把「用户写的规则」归一成可与前台进程身份匹配的标识集合。

移植自 Mouser v3.7.3 core/app_catalog.py 的设计（MIT），精简为 Windows 版：
策展式常用应用表 + 别名展开 + winreg 已安装应用发现 + casefold 归一化。
不移植任何 Logitech 相关内容。
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys
from typing import Iterable

IS_WINDOWS = sys.platform == "win32"

# 策展式常用应用：id / 显示名 / 可执行文件 / 别名 / 路径提示
WINDOWS_APP_SPECS: list[dict] = [
    {"id": "chrome.exe", "label": "Google Chrome", "aliases": ["Chrome", "谷歌浏览器"],
     "executables": ["chrome.exe"]},
    {"id": "msedge.exe", "label": "Microsoft Edge", "aliases": ["Edge"],
     "executables": ["msedge.exe"]},
    {"id": "firefox.exe", "label": "Firefox", "aliases": ["火狐"], "executables": ["firefox.exe"]},
    {"id": "Code.exe", "label": "Visual Studio Code", "aliases": ["VS Code", "VSCode", "Code"],
     "executables": ["Code.exe"]},
    {"id": "Cursor.exe", "label": "Cursor", "aliases": [], "executables": ["Cursor.exe"]},
    {"id": "explorer.exe", "label": "文件资源管理器", "aliases": ["File Explorer", "Explorer", "资源管理器"],
     "executables": ["explorer.exe"]},
    {"id": "WindowsTerminal.exe", "label": "Windows 终端",
     "aliases": ["Windows Terminal", "Terminal", "wt"],
     "executables": ["WindowsTerminal.exe", "wt.exe"]},
    {"id": "powershell.exe", "label": "Windows PowerShell",
     "aliases": ["PowerShell"], "executables": ["powershell.exe"]},
    {"id": "pwsh.exe", "label": "PowerShell 7", "aliases": ["pwsh"], "executables": ["pwsh.exe"]},
    {"id": "cmd.exe", "label": "命令提示符", "aliases": ["Command Prompt", "cmd"],
     "executables": ["cmd.exe"]},
    {"id": "notepad.exe", "label": "记事本", "aliases": ["Notepad"], "executables": ["notepad.exe"]},
    {"id": "Photoshop.exe", "label": "Adobe Photoshop", "aliases": ["PS", "Photoshop"],
     "executables": ["Photoshop.exe"]},
    {"id": "AfterFX.exe", "label": "Adobe After Effects", "aliases": ["AE", "After Effects"],
     "executables": ["AfterFX.exe"]},
    {"id": "Adobe Premiere Pro.exe", "label": "Adobe Premiere Pro",
     "aliases": ["PR", "Premiere"], "executables": ["Adobe Premiere Pro.exe"]},
    {"id": "vlc.exe", "label": "VLC", "aliases": ["VLC Media Player"], "executables": ["vlc.exe"]},
    {"id": "Discord.exe", "label": "Discord", "aliases": [], "executables": ["Discord.exe"]},
    {"id": "steam.exe", "label": "Steam", "aliases": [], "executables": ["steam.exe"]},
    {"id": "WeChat.exe", "label": "微信", "aliases": ["WeChat", "微信"], "executables": ["WeChat.exe", "Weixin.exe"]},
    {"id": "WINWORD.EXE", "label": "Microsoft Word", "aliases": ["Word"], "executables": ["WINWORD.EXE"]},
    {"id": "EXCEL.EXE", "label": "Microsoft Excel", "aliases": ["Excel"], "executables": ["EXCEL.EXE"]},
    {"id": "wps.exe", "label": "WPS Office", "aliases": ["WPS"], "executables": ["wps.exe", "et.exe", "wpp.exe"]},
    {"id": "idea64.exe", "label": "IntelliJ IDEA", "aliases": ["IDEA"], "executables": ["idea64.exe"]},
    {"id": "pycharm64.exe", "label": "PyCharm", "aliases": [], "executables": ["pycharm64.exe"]},
    {"id": "devenv.exe", "label": "Visual Studio", "aliases": ["VS"], "executables": ["devenv.exe"]},
    {"id": "mintty.exe", "label": "Git Bash", "aliases": ["Git Bash", "mintty"], "executables": ["mintty.exe", "git-bash.exe"]},
]

_HINTS: dict[str, dict] = {}
for _spec in WINDOWS_APP_SPECS:
    _aliases = {_spec["id"], _spec["label"], *_spec["aliases"], *_spec["executables"]}
    for _alias in _aliases:
        _HINTS[_alias.casefold()] = {"id": _spec["id"], "label": _spec["label"],
                                     "aliases": _aliases}

UNINSTALL_KEYS = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)


def normalize(value: str) -> str:
    """路径分隔符统一 + 去引号 + 大小写折叠。"""
    if not value:
        return ""
    text = str(value).strip().strip('"').replace("\\", "/")
    return re.sub(r"/+", "/", text).casefold()


def expand_identity(value: str) -> set[str]:
    """一个进程身份展开成多个可匹配形式：完整路径 / 文件名 / 无扩展名。"""
    if not value:
        return set()
    out = {normalize(value)}
    base = os.path.basename(value.replace("\\", "/"))
    out.add(normalize(base))
    stem = os.path.splitext(base)[0]
    out.add(normalize(stem))
    out.discard("")
    return out


def resolve_app_spec(spec: str) -> set[str]:
    """把一条 apps 规则展开成候选标识（含别名、文件名、去扩展名、通配符）。"""
    if not isinstance(spec, str) or not spec.strip():
        return set()
    raw = spec.strip()
    candidates = expand_identity(raw)
    hint = _HINTS.get(normalize(raw)) or _HINTS.get(raw.casefold())
    if hint:
        for alias in hint["aliases"]:
            candidates |= expand_identity(alias)
    return {c for c in candidates if c}


def match_profile_apps(apps: Iterable[str], identities: Iterable[str]) -> bool:
    """档位的 apps 规则是否命中当前前台应用身份。

    支持：exe 文件名 / 完整路径 / 显示名与别名 / 路径通配符（如 app-*\\*）。
    """
    idset: set[str] = set()
    for value in identities:
        idset |= expand_identity(str(value))
    if not idset:
        return False
    for spec in apps or []:
        for candidate in resolve_app_spec(spec):
            for identity in idset:
                if candidate == identity or fnmatch.fnmatchcase(identity, candidate):
                    return True
                # 规则写完整路径、身份只给文件名时也允许命中
                if "/" in candidate:
                    base = candidate.rsplit("/", 1)[-1]
                    if base == identity or fnmatch.fnmatchcase(identity, base):
                        return True
    return False


def friendly_label(spec: str) -> str:
    hint = _HINTS.get(normalize(spec)) or _HINTS.get(spec.casefold())
    return hint["label"] if hint else spec


def discover_installed_apps(limit: int = 200) -> list[dict]:
    """从注册表 Uninstall 键发现已安装应用（只读；任何异常都返回已得结果）。"""
    if not IS_WINDOWS:
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return []
    found: dict[str, dict] = {}
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for root in roots:
        for sub in UNINSTALL_KEYS:
            try:
                parent = winreg.OpenKey(root, sub)
            except OSError:
                continue
            try:
                count = winreg.QueryInfoKey(parent)[0]
                for idx in range(count):
                    try:
                        name = winreg.EnumKey(parent, idx)
                        key = winreg.OpenKey(parent, name)
                        display = _read_str(key, "DisplayName")
                        icon = _read_str(key, "DisplayIcon")
                        if not display:
                            continue
                        exe = ""
                        if ".exe" in icon.lower():
                            exe = icon.lower().split(".exe", 1)[0] + ".exe"
                        exe = exe.strip('"')
                        found[display.casefold()] = {
                            "label": display,
                            "id": os.path.basename(exe) if exe else display,
                            "path": exe,
                        }
                        if len(found) >= limit:
                            return sorted(found.values(), key=lambda e: e["label"].casefold())
                    except OSError:
                        continue
            finally:
                try:
                    winreg.CloseKey(parent)
                except OSError:
                    pass
    return sorted(found.values(), key=lambda e: e["label"].casefold())


def _read_str(key, name: str) -> str:
    try:
        import winreg
        value, _ = winreg.QueryValueEx(key, name)
        return value if isinstance(value, str) else ""
    except OSError:
        return ""
