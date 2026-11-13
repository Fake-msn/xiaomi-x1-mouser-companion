"""X1 Companion —— 小米 X1 鼠标的跨应用快捷键伴生层。

设计前提（见方案文档 §0/§2）：
* 不修改 Xiaomi G-HUB 的任何文件、不写设备 HID Feature Report。
* 只在 Windows 用户态做 WH_MOUSE_LL 拦截与 SendInput 注入。
* 核心零第三方依赖，仅使用 Python 标准库 ctypes / winreg / json。
"""
from __future__ import annotations

__version__ = "1.0.0"
APP_NAME = "X1 Companion"
CONFIG_DIR_NAME = "X1Companion"
CONFIG_FILE_NAME = "config.json"
