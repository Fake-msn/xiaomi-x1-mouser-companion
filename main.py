"""X1 Companion 入口。

用法:
  python main.py                     正常启动（钩子 + 前台检测 + 控制台）
  python main.py --dry-run           不装钩子，只验证应用识别/档位/动作链
  python main.py --detect-device     列出 HID 设备，找出 X1 的 VID/PID
  python main.py --selftest          运行单元测试
  python main.py --init-config       生成默认 config.json
  python main.py --import-mouser <Mouser config.json>
  python main.py --import-ghub   <G-HUB Mouse_*.json>
  python main.py --bypass            以全局旁路模式启动
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import APP_NAME, __version__                      # noqa: E402
from core import config as cfgmod                          # noqa: E402
from core.engine import Engine                             # noqa: E402
from core.winapi import (IS_WINDOWS, ERROR_ALREADY_EXISTS,  # noqa: E402
                         private_kernel32)
from ui.console import run_console, print_status            # noqa: E402

MUTEX_NAME = "Local\\X1Companion_SingleInstance"


def single_instance_guard() -> tuple[bool, object]:
    """CreateMutexW 单实例保护；非 Windows 直接放行。"""
    if not IS_WINDOWS:
        return True, None
    import ctypes.wintypes as wt
    k = private_kernel32()
    k.CreateMutexW.restype = wt.HANDLE
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, ctypes.c_wchar_p]
    handle = k.CreateMutexW(None, False, MUTEX_NAME)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    return (not already), handle


def cmd_detect_device() -> int:
    from tools.detect_device import main as detect_main
    return detect_main([])


def cmd_selftest() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    suite = unittest.defaultTestLoader.discover(os.path.join(root, "tests"),
                                                pattern="test_*.py",
                                                top_level_dir=root)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_import_mouser(path: str, cfg_path: str) -> int:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    cfg, report = cfgmod.import_mouser_config(data)
    cfgmod.save_config(cfg, cfg_path)
    print(f"已导入 Mouser 配置 -> {cfg_path}")
    print(f"  档位 {report['profiles']} 个，按键映射 {report['mappings']} 条")
    print(f"  跳过的按键 {len(report['skipped_buttons'])} 个（HID++/罗技专属）")
    print(f"  跳过的动作 {len(set(report['skipped_actions']))} 种")
    print("  注意：导入后 ownership 仍全为 ghub（透传），需显式声明 companion 才会接管。")
    return 0


def cmd_import_ghub(path: str, cfg_path: str) -> int:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    extra, report = cfgmod.import_ghub_applink(data)
    if not report["found"]:
        print(f"未导入：{report['reason']}")
        return 1
    cfg = cfgmod.merge_profiles(cfgmod.load_config(cfg_path), extra)
    cfgmod.save_config(cfg, cfg_path)
    print(f"已从 G-HUB 只读导入应用关联: {report['app'] or report['path']} -> {cfg_path}")
    print("  仅写入 X1 Companion 自己的配置，未修改任何 G-HUB 文件。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="x1-companion", description=f"{APP_NAME} {__version__}")
    p.add_argument("--config", help="配置文件路径（默认 %APPDATA%\\X1Companion\\config.json）")
    p.add_argument("--dry-run", action="store_true", help="不安装钩子；只验证识别/档位/动作链")
    p.add_argument("--bypass", action="store_true", help="以全局旁路启动")
    p.add_argument("--no-console", action="store_true", help="启动后不进入交互控制台")
    p.add_argument("--no-single-instance", action="store_true", help="允许多实例（调试用）")
    p.add_argument("--init-config", action="store_true", help="写出默认配置后退出")
    p.add_argument("--detect-device", action="store_true", help="列出 HID 设备并退出")
    p.add_argument("--selftest", action="store_true", help="运行单元测试并退出")
    p.add_argument("--import-mouser", metavar="PATH", help="导入 Mouser config.json 后退出")
    p.add_argument("--import-ghub", metavar="PATH", help="只读导入 G-HUB Mouse_*.json 后退出")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg_path = cfgmod.config_path(args.config)

    if args.selftest:
        return cmd_selftest()
    if args.detect_device:
        return cmd_detect_device()
    if args.init_config:
        cfgmod.save_config(cfgmod.load_config(cfg_path), cfg_path)
        print(f"已生成默认配置: {cfg_path}")
        return 0
    if args.import_mouser:
        return cmd_import_mouser(args.import_mouser, cfg_path)
    if args.import_ghub:
        return cmd_import_ghub(args.import_ghub, cfg_path)

    if not args.no_single_instance:
        first, _mutex = single_instance_guard()
        if not first:
            print(f"{APP_NAME} 已在运行。如需多实例请加 --no-single-instance。")
            return 1

    cfg = cfgmod.load_config(cfg_path)
    if args.bypass:
        cfg["settings"]["bypass"] = True

    print(f"{APP_NAME} {__version__}  |  Python {sys.version.split()[0]}  |  Windows={IS_WINDOWS}")
    print(f"配置: {cfg_path}")
    print(f"模式: {'DRY-RUN（不装钩子）' if args.dry_run else '正常'}  "
          f"旁路={'开' if cfg['settings'].get('bypass') else '关'}")

    engine = Engine(cfg, dry_run=args.dry_run)
    hook_ok = engine.start(with_hook=not args.dry_run, with_detector=True)
    if not args.dry_run and not hook_ok:
        print("  ⚠ 钩子安装失败（可能无桌面会话）。已自动降级为纯检测模式。")
    if not args.dry_run:
        ok, msg = engine.refresh_devices()
        print(f"设备白名单: {msg}")
        delay = cfg["settings"].get("coexist_delay_ms", 0) / 1000.0
        if delay > 0:
            import time
            time.sleep(min(delay, 5.0))  # 等 G-HUB 先就绪，避免抢钩子

    if args.no_console:
        print_status(engine.status())
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop()
        return 0

    try:
        return run_console(engine, cfg_path)
    finally:
        engine.stop()
        print("已停止。Xiaomi G-HUB 未被修改，输入行为已恢复基线。")


if __name__ == "__main__":
    raise SystemExit(main())
