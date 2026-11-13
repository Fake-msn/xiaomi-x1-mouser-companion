# X1 Companion

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6.svg)
![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)

**运行环境**：Windows 10/11 + Python 3.10+（仅标准库，零第三方依赖）。

> **非官方声明 / Disclaimer**
>
> 本项目是**独立的、非官方的**开源工具，与小米（Xiaomi）、Xiaomi G-HUB 的开发商、其 Authenticode 签名主体、以及任何 ODM / 设备制造商**均无隶属、授权、背书或合作关系**。文中「Xiaomi」「X1」「G-HUB」等名称、型号与 VID/PID 仅用于兼容性说明，不构成商标授权，也不代表官方支持。
>
> 本项目**不包含、不修改、不重新分发**任何厂商安装包、驱动、DLL 或配置文件；仅调用 Windows 公开**用户态** API（`WH_MOUSE_LL` / `SendInput` / Raw Input / Win32），不写入任何 HID Feature Report，不改动设备固件与板载配置。
>
> 文中静态分析结论仅为技术说明，不代表厂商立场，也不保证适用于所有版本。使用风险由使用者自行承担，请遵守厂商 EULA 及适用法律法规。
>
> *This is an independent, unofficial project, not affiliated with, endorsed by, or authorized by Xiaomi or the G-HUB developers.*

小米 X1 鼠标的**跨应用快捷键伴生层**，从 [TomBadash/Mouser](https://github.com/TomBadash/Mouser) v3.7.3（MIT）迁移可适配能力，不移植罗技设备匹配模块。

> **它不改 Xiaomi G-HUB 的任何文件。** G-HUB 继续独占设备侧（DPI / 灯光 / 宏 / 板载档位 / OTA），
> 本程序只在 Windows 用户态做 `WH_MOUSE_LL` 拦截与 `SendInput` 注入，**绝不写 HID Feature Report**。

---

## 0. 为什么是「伴生程序」而不是「整合进 exe」

对**样本版本** `Xiaomi_G-HUB_Installer_1.1.0.31.exe`（一次性的只读静态分析样本，不代表当前或全部版本）的静态逆向结论：

| 发现 | 含义 |
|---|---|
| `.sys` / `.inf` / `.cat` 均为 0 | 它**不是内核驱动**，是 32 位原生 C++ 用户态程序（NSIS v2.46.5 打包、DuiLib + OpenCV 3.2） |
| 该样本 Authenticode 签名有效（签名主体 `Shenzhen Evision Semiconductor`，仅针对所分析样本） | 任何字节改动都会破坏签名，且升级会覆盖 |
| `Mouse_3389.json` 已有 `AppLink` / `AppName` / `AppPath`；`DeviceProfile.xml` 已有「关联软件」复选框与配置档导入导出 | G-HUB **本来就有**多档位 + 应用关联 + 按键映射 + 宏 |
| 主 exe 含 `GetForegroundWindow` / `SetWindowsHookEx` / `CallNextHookEx`；`HookDLL.dll` 也装钩子 | 再注入一个钩子会形成三钩子链 |
| `XiaoMiMouseLibrary.dll` 用 `Hid` + `VID/PID` + `SetFeature` | 设备侧写入存在争用风险（Mouser 自己也警告 Logitech Options+ 不能同时运行） |

**所以真正要迁移的不是「跨应用切换」这个概念，而是它的表达力与鲁棒性。** 本项目的定位是「增量增强层」。

---

## 1. 快速开始

```bat
cd x1-companion
python main.py --selftest          :: 运行内置单元测试
python main.py --detect-device     :: 只读枚举 HID 设备，查找鼠标 VID/PID
python main.py --dry-run           :: 不装钩子，验证识别/档位/动作链
```

正式启用（**会安装全局低级鼠标钩子，请先读完 §4 护栏**）：

```bat
copy config.example.json "%APPDATA%\X1Companion\config.json"
python main.py
```

控制台输入 `help` 查看全部命令，`bypass on` 即时恢复基线，`quit` 卸载钩子退出。

其他入口：

```bat
python main.py --init-config                        :: 生成默认配置
python main.py --import-mouser <Mouser config.json> :: 导入 Mouser 档位与映射
python main.py --import-ghub   <Mouse_3389.json>    :: 只读导入 G-HUB 的 AppLink 关联
python main.py --bypass                             :: 以旁路模式启动
```

**零第三方依赖**：核心只用 Python 标准库（`ctypes` / `winreg` / `json`）。
界面默认采用标准库控制台，以保证零依赖、免打包即可运行；`ui/` 与核心层解耦，
如需图形界面可自行引入 PySide6 等框架并在 `ui/` 下扩展，核心层无需改动。

---

## 2. 整合后的功能清单

### 新增（来自 Mouser 的真正增量）

| # | 功能 | 实现模块 |
|---|---|---|
| N1 | 前台应用感知：0.3s 轮询、完整 exe 路径身份、UWP / `ApplicationFrameHost` 解析、explorer 瞬态窗口过滤（任务栏缩略图 / Alt-Tab / 右键菜单），无法解析时**保持上一档** | `core/app_detector.py`, `core/app_catalog.py` |
| N2 | 跨应用多档位：每档绑定多个应用，支持 exe 名 / 完整路径 / 显示别名 / 通配符，兜底档 + 优先级；**切换只在内存生效，零设备写入** | `core/config.py::resolve_profile` |
| N3 | 自定义快捷键录制器：`WH_KEYBOARD_LL` 录制任意组合键（含 Win 键），支持 `record` 命令；带 10s 超时 | `core/key_capture.py` |
| N4 | 48 个 Windows 内置动作：窗口导航 / 浏览器 / 编辑 / 媒体 / 鼠标 / 系统 / 滚动 / 特殊 | `core/actions.py` |
| N5 | X1 按键映射：中键、侧键×2、滚轮上下、滚轮左右 → 任意动作；左/右键受保护 | `core/buttons.py` |
| N6 | 按住侧键四向滑动手势：用 OS 指针位移实现（**不依赖 HID++**），5 档阈值、commit 窗口、斜向比例判定、轻点单独动作 | `core/gesture.py` |
| N7 | 动作环接口：`activate_actions_ring` 动作 ID + `actions_ring_slots` 配置位（无 UI 时安全降级为不操作） | `core/engine.py` |
| N8 | 纯 JSON 配置：版本迁移 / 缺键合并 / 类型校验 / `mkstemp + fsync + os.replace` 原子写 / 导入导出 / Mouser 导入器 / G-HUB AppLink 只读导入 | `core/config.py` |
| N9 | 工程外围：单实例、启动延迟、启动参数、日志与状态、三语字段位（当前 UI 中文） | `main.py`, `ui/console.py` |
| N10 | 共存护栏：设备白名单、注入事件过滤、按键归属表、kill switch、游戏模式 | `core/engine.py`, `core/devices.py`, `core/mouse_hook.py` |

### 增强（复用并扩展 G-HUB 已有能力）

- **E1** 单应用 `AppLink` → 多应用 + 别名 + 路径 + UWP 规则（仅在新层生效）。
- **E2** 跨应用切换从「重写板载档」→「OS 级瞬时切映射」：无 HID 写入、无闪存磨损、无延迟。
- **E3** 枚举式按键定义（Ctrl/Shift/Alt/Win 复选框）→ 任意组合键 + 48 动作。

### 保留不动

DPI 档位与颜色、回报率 125–8000Hz、静默高度、角度修正、灯光、宏录制与管理、板载配置档与导入导出、OTA、设备信息、多设备支持、`HookDLL.dll` 行为、G-HUB 的 AppLink 行为与配置文件 —— **一个字节都不改**。

### 明确不移植

罗技设备发现与 HID++ 协议、`logi_devices.py` / `logi_device_catalog.py` / `device_layouts.py`、Logi Bolt 接收器识别、SmartShift `0x2111`、MX Master 系列设备图层、macOS / Linux 后端、DPI / 灯光 / OTA 等需 Xiaomi HID 协议的设备写入。

---

## 3. 实现方式

```
G-HUB（原样）        HID SetFeature → 设备侧 + 已有 HookDLL.dll 钩子链
──────────────────────────────────────────────────────────────────
X1 Companion（新增）  AppDetector(0.3s) ─→ resolve_profile ─→ blocked 集合
                      WH_MOUSE_LL ─→ 只吞 blocked 事件 ─→ queue(512)
                      dispatch worker ─→ 手势/动作解析 ─→ SendInput
                      全程 0 次 HID 写入
```

| 模块 | 职责 |
|---|---|
| `core/winapi.py` | Win32 常量/结构体；**私有 user32 句柄工厂** |
| `core/buttons.py` | X1 按键模型、`BUTTON_TO_EVENT_KEYS`、受保护键 |
| `core/config.py` | 配置模型、档位解析、`build_blocked_events`、导入器 |
| `core/app_catalog.py` | 应用别名展开、已安装应用发现、规则匹配 |
| `core/app_detector.py` | 前台窗口识别（含 UWP 与瞬态窗口处理） |
| `core/actions.py` | 48 动作表 + 自定义组合键编解码 |
| `core/key_simulator.py` | `SendInput` 注入（支持 `dry_run`） |
| `core/key_capture.py` | `WH_KEYBOARD_LL` 录制器 + 文本退路 |
| `core/mouse_hook.py` | `WH_MOUSE_LL`、独立线程消息循环、异常兜底 |
| `core/gesture.py` | 四向滑动纯逻辑 |
| `core/devices.py` | Raw Input 枚举、VID/PID 白名单 |
| `core/engine.py` | 调度、档位切换、动作执行、共存护栏 |
| `main.py` / `ui/console.py` | 入口、单实例、控制台 |

### 四道护栏 —— 「原有功能不受影响」如何被保证

1. **按键归属表（最关键）**：`settings.ownership` 缺省为 `ghub`。`build_blocked_events()` 只会把
   「显式声明 `companion` + 档位里配了非 `none` 动作 + 非受保护键」的事件加入可吞集合。
   默认配置下这个集合是**空集**，钩子即使装上也全部 `CallNextHookEx` 放行。
   `handle_event()` 还会再检查一次 `event.key in blocked`，确保**未被接管的按键连动作都不执行**，
   杜绝与 G-HUB 双重触发。
2. **注入事件过滤**：`LLMHF_INJECTED` 事件直接放行，防止两边互相触发形成回环。
3. **钩子句柄隔离**：鼠标钩子、键盘录制器、SendInput 注入器、前台识别器各自调用
   `private_user32()`，且钩子实例使用自己的 `HOOKPROC` 类型。这是对 Mouser v3.7.2 → v3.7.3
   事故的继承：两个钩子共用 `ctypes.windll.user32` 导致 `CallNextHookEx` 原型被覆盖、
   全会话鼠标指针冻结（issue #259）。钩子回调另有 `try/except` 兜底，**任何异常都无条件放行事件**。
4. **旁路 / 设备白名单 / 游戏模式**：托盘命令 `bypass on`、`game on`、`--bypass` 参数，
   以及 `device_filter_enabled` 白名单；旁路同时关断钩子层与调度层（双保险）。

---

## 4. 配置与按键归属表

配置路径：`%APPDATA%\X1Companion\config.json`（不占用 `%APPDATA%\Mouser`）。
完整示例见 `config.example.json`。

```json
{
  "profiles": {
    "coding": {
      "apps": ["Code.exe", "VS Code"],
      "priority": 20,
      "mappings": { "xbutton1": "custom:0x10+0x11+0x50", "xbutton2": "copy" }
    }
  },
  "settings": {
    "ownership": { "xbutton1": "companion", "xbutton2": "companion" },
    "device_filter_enabled": false,
    "device_whitelist": []
  }
}
```

`custom:0x10+0x11+0x50` = `Shift + Ctrl + P`（修饰键在前、十六进制 VK 码）。

| 按键 | 可声明归属 | 说明 |
|---|---|---|
| `left` / `right` | ✗ | 受保护，防止锁死系统输入 |
| `middle` | ✓ | 中键（滚轮按下） |
| `xbutton1` / `xbutton2` | ✓ | 侧键后退 / 前进 |
| `wheel_up` / `wheel_down` | ✓ | 垂直滚轮 |
| `hscroll_left` / `hscroll_right` | ✓ | 水平滚轮 |
| `dpi_switch` | ✗ | 固件独占，钩子观察不到 |

**启用一个按键的最小三步**：① 在目标档位 `mappings` 里配动作；
② 在 `settings.ownership` 里把它设为 `companion`；③ `save` 或重启。
少任何一步，该键都保持 G-HUB 原样。

---

## 5. 自检与能力边界

项目内置可复现的自检入口，可在自己的环境运行以确认行为（结果因机器而异）：

| 入口 | 能力 | 说明 |
|---|---|---|
| `python main.py --selftest` | 内置单元测试 | 覆盖配置迁移/原子写、档位优先级、归属表、应用别名、动作表、快捷键编解码、四向手势、消息翻译、VID/PID 解析、引擎端到端与旁路双保险 |
| `python main.py --detect-device` | 只读枚举 Raw Input HID 设备 | 输出设备名中的 VID/PID，用于确认目标鼠标；只读，不写设备 |
| `python main.py --dry-run` | 不安装钩子的演练 | 验证档位切换、旁路开关、动作列表与前台应用识别，不改动输入行为 |

> 上述为可选、可复现的能力演示，不代表任何特定机器上的实测结论。
> `--dry-run` 与 `--bypass` 模式下不安装常驻低级钩子；正式启用需显式执行 `python main.py`。

### 关于设备白名单（VID/PID）

`--detect-device` 会列出形如 `VID_XXXX&PID_XXXX` 的设备标识。若需限定伴生层仅在特定鼠标在线时生效，
请先拔插目标设备对比枚举结果，再在 `config.json` 中设置（此处为占位示例，请替换为实际值）：

```json
"device_filter_enabled": true,
"device_whitelist": ["VID_XXXX&PID_XXXX"]
```

诚实边界：`WH_MOUSE_LL` 事件**不携带设备标识**，无法逐事件判断来源。
设备过滤的实现是「启动时枚举，白名单设备在线才启用伴生层」，不是逐事件过滤。
默认 `device_filter_enabled=false` 时对所有鼠标生效。

---

## 6. 设计选型说明

| 项 | 选型 | 理由 |
|---|---|---|
| UI 框架 | 标准库控制台 + 纯 `ctypes` 核心 | 核心层零第三方依赖、免打包即可运行，稳定性与可移植性更好；`ui/` 与核心解耦，图形界面可作为后续增量 |
| 设备识别 | 运行时只读 Raw Input 枚举 | 不内置任何厂商设备清单；VID/PID 由使用者在自己的机器上通过 `--detect-device` 获取，避免硬编码特定硬件 |

---

## 7. 已知限制与风险

1. **未做双钩子长时共存实测**：G-HUB 的 `HookDLL.dll` 与本程序同时运行时的钩子顺序、
   延迟、极端情况未验证。先用 `bypass on` 观察，再逐键启用。
2. **反作弊环境**：EAC / Vanguard 等对 `SendInput` 与低级钩子的容忍度未知。
   进游戏前用 `game on` 或配置 `gaming` 档位（全 `none`）全透传。
3. **管理员权限窗口**：低完整性进程无法拦截高完整性进程的输入，属 Windows 设计；
   不要为本程序提权运行。
4. **G-HUB 的 AppLink 语义**仅由字符串与 XML 推断（前台切换 or 启动关联、是否写板载），
   未做动态行为验证。本程序不依赖它、也不写回。
5. `Mouse_3389.json` 对应 PMW3389，X1 为 PAW3395；G-HUB 按设备加载不同默认数据，
   但这不影响本程序（我们不碰设备配置）。
6. **仅静态只读分析过安装包**：未运行、未解压落盘、未修改厂商任何文件。
7. 合规：Mouser 为 MIT，见 `LICENSE-THIRD-PARTY.md`；本项目不分发改造后的厂商安装包，
   使用请遵守厂商软件的最终用户许可协议（EULA）。详见文首非官方声明。

## 8. 回滚

`quit` 或 `Ctrl+C` → 钩子卸载、检测器停止。程序不在注册表写启动项（除非你自行配置），
不写 G-HUB 配置，不写设备。删除整个 `x1-companion` 目录即完全移除。
