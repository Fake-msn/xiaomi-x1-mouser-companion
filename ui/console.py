"""控制台界面（零第三方依赖）。

界面默认采用标准库实现的控制台，以保证核心零第三方依赖、免打包即可运行；
所有能力都能在这里验证与切换。图形界面可作为后续增量在 ``ui/`` 下扩展。
"""
from __future__ import annotations

import json

HELP = """\
命令:
  status                    显示当前档位 / 前台应用 / 被接管的事件
  bypass on|off             全局一键旁路（立即恢复 G-HUB 原始行为）
  game on|off               游戏模式（全透传，规避反作弊环境）
  profile <name>            手动切换档位
  profiles                  列出全部档位
  ownership <btn> <owner>   声明按键归属: owner = companion | ghub
  buttons                   列出可声明归属的按键
  actions [类别]            列出内置动作
  record                    录制自定义组合键（返回可写入配置的动作 ID）
  devices                   列出 Raw Input 设备 / 检查 X1 白名单
  refresh                   重新检测设备与配置
  save                      保存当前配置到磁盘
  help / quit
"""


def print_status(status: dict) -> None:
    print("─" * 60)
    print(f"  当前档位    : {status['active_profile']}")
    fg = status["foreground"]
    print(f"  前台应用    : {fg[0] if fg else '(未识别)'}")
    print(f"  接管事件    : {', '.join(status['blocked_events']) or '(无，全部透传)'}")
    print(f"  旁路 / 游戏 : {status['bypass']} / {status['game_mode']}")
    print(f"  设备检查    : {status['device_msg']}")
    print(f"  最近动作    : {status['last_action'] or '(无)'}")
    if status.get("injected"):
        print(f"  注入记录    : {status['injected']}")
    print("─" * 60)


def run_console(engine, cfg_path: str, *, quiet: bool = False) -> int:
    from core import config as cfgmod
    from core import buttons
    from core.actions import actions_by_category
    from core.devices import enumerate_raw_input_devices
    from core.key_capture import ShortcutRecorder

    if not quiet:
        print("\nX1 Companion 控制台。输入 help 查看命令，quit 退出。")
        print(f"配置文件: {cfg_path}")
        print_status(engine.status())

    while True:
        try:
            line = input("x1> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print(HELP)
            elif cmd == "status":
                print_status(engine.status())
            elif cmd == "bypass" and len(parts) >= 2:
                engine.set_bypass(parts[1].lower() in ("on", "1", "true", "yes"))
                print_status(engine.status())
            elif cmd == "game" and len(parts) >= 2:
                engine.set_game_mode(parts[1].lower() in ("on", "1", "true", "yes"))
                print_status(engine.status())
            elif cmd == "profile" and len(parts) >= 2:
                ok = engine.set_profile(parts[1])
                print("已切换" if ok else "档位不存在")
                print_status(engine.status())
            elif cmd == "profiles":
                for name, p in engine.cfg["profiles"].items():
                    marker = "*" if name == engine.active_profile else " "
                    print(f" {marker} {name:24s} {p.get('label','')}  apps={p.get('apps', [])}")
            elif cmd == "buttons":
                for key in buttons.OWNable:
                    owner = engine.cfg["settings"]["ownership"].get(key, "ghub")
                    print(f"  {key:16s} {buttons.BUTTON_LABELS[key]:24s} owner={owner}")
            elif cmd == "ownership" and len(parts) >= 3:
                engine.set_ownership(parts[1], parts[2])
                print("已更新归属（仅内存，输入 save 持久化）")
                print_status(engine.status())
            elif cmd == "actions":
                wanted = parts[1] if len(parts) > 1 else None
                for category, items in actions_by_category().items():
                    if wanted and wanted != category:
                        continue
                    print(f"  [{category}]")
                    for action in items:
                        print(f"    {action.id:26s} {action.label}")
            elif cmd == "record":
                print("请按下组合键（10 秒内）…")
                action_id = ShortcutRecorder().record(timeout=10)
                print(f"  动作 ID: {action_id}")
                if action_id != "none":
                    print("  把它写进 config.json 的 profiles.<档位>.mappings.<按键> 即可")
            elif cmd == "devices":
                devices = enumerate_raw_input_devices()
                if not devices:
                    print("  (无法枚举设备，或非 Windows 环境)")
                for d in devices:
                    flag = " ←疑似 X1" if d["x1_candidate"] else ""
                    print(f"  {d['token'] or '(no vid/pid)':22s} mouse={d['mouse']} {d['name'][:70]}{flag}")
                ok, msg = engine.refresh_devices()
                print(f"  白名单检查: {msg}")
            elif cmd == "refresh":
                engine.refresh_devices()
                engine.reload(cfgmod.load_config(cfg_path))
                print_status(engine.status())
            elif cmd == "save":
                cfgmod.save_config(engine.cfg, cfg_path)
                print(f"  已保存: {cfg_path}")
            else:
                print("  未知命令，输入 help 查看用法")
        except Exception as exc:
            print(f"  ✗ {type(exc).__name__}: {exc}")
    return 0
