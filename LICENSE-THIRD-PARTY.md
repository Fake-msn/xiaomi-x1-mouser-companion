# 第三方许可与归属声明

## Mouser（设计借鉴来源）

- 项目：<https://github.com/TomBadash/Mouser>
- 分析版本：**v3.7.3**（2026-07-28，latest release）
- 许可证：**MIT**（仓库 `LICENSE`，GitHub API `license.spdx_id = MIT`）

本项目在**设计层面**借鉴了 Mouser v3.7.3 的以下公开实现思路，并按小米 X1 / Windows 场景
重新实现（未逐字复制源码、未打包其二进制、未引入其依赖）：

| 借鉴的设计 | 本项目对应实现 |
|---|---|
| `core/app_detector.py`：`GetForegroundWindow` + `QueryFullProcessImageNameW`、UWP `ApplicationFrameHost` 解析、explorer 瞬态窗口分类、0.3s 轮询 | `core/app_detector.py` |
| `core/app_catalog.py`：策展式应用表、别名展开、casefold 归一化、注册表发现 | `core/app_catalog.py` |
| `core/config.py`：`profiles.<name>.apps[]` / `mappings`、兜底档、版本迁移、原子写 | `core/config.py` |
| `core/mouse_hook_windows.py`：`WH_MOUSE_LL`、`INJECTED_FLAG` 过滤、`should_block` 吞事件、独立钩子线程 | `core/mouse_hook.py` |
| `core/gesture_recognizer.py`：滑动阈值与方向判定 | `core/gesture.py`（改为 OS 指针位移，不依赖 HID++） |
| Available actions 表的动作分类 | `core/actions.py`（剔除 macOS 专属，扩为 48 个 Windows 动作） |
| **v3.7.3 hotfix**：`ctypes.windll.user32` 原型冲突导致全会话指针冻结 → 私有句柄隔离 | `core/winapi.py::private_user32`，并在 README §3 明确标注 |

**明确未移植**：`core/logi_devices.py`、`core/logi_device_catalog.py`、`core/device_layouts.py`
（罗技设备匹配）、HID++ 协议、Logi Bolt 识别、SmartShift `0x2111`、MX Master 系列设备图层、
macOS `CGEventTap` / Linux `evdev+uinput` 后端。

### MIT License 原文

> Copyright (c) 2026 Tom Badash
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

> 注：以上版权行已按 Mouser 仓库 `LICENSE`（默认分支 `master`）核对；分发衍生作品时请保留原文。

## 厂商软件

`Xiaomi G-HUB` 的样本版本 v1.1.0.31（该样本签名主体
`Shenzhen Evision Semiconductor Technology Co., Ltd.`，仅针对所分析样本）
仅被**只读静态分析**，本项目**不包含、不修改、不再分发**其任何文件。
使用本伴生程序时请自行遵守厂商软件的最终用户许可协议。
