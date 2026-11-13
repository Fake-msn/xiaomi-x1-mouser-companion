"""列出 Raw Input 设备，找出小米 X1 的 VID/PID 并生成白名单片段。

只读枚举，不打开设备句柄、不写任何 Feature Report。
用法: python main.py --detect-device  或  python -m tools.detect_device --json
"""
from __future__ import annotations

import argparse
import json
import sys

from core.devices import enumerate_raw_input_devices, looks_like_x1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="枚举 HID 设备，定位小米 X1")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--all", action="store_true", help="显示所有设备（默认只显示鼠标）")
    args = parser.parse_args(argv or [])

    devices = enumerate_raw_input_devices()
    shown = devices if args.all else [d for d in devices if d["mouse"]]
    candidates = [d for d in devices if looks_like_x1(d["name"])]

    if args.json:
        print(json.dumps({"devices": shown, "x1_candidates": candidates},
                         indent=2, ensure_ascii=False))
        return 0

    print(f"Raw Input 设备共 {len(devices)} 个，其中鼠标 {sum(1 for d in devices if d['mouse'])} 个\n")
    for d in shown:
        flag = "  ← 疑似 X1" if d["x1_candidate"] else ""
        print(f"  {d['token'] or '(无 VID/PID)':24s} {d['name'][:88]}{flag}")

    print("\n疑似 X1 的设备:")
    if not candidates:
        print("  (未自动识别。请拔插鼠标对比上面列表，或在设备管理器中查看硬件 ID)")
    for d in candidates:
        print(f"  {d['token'] or '(无 VID/PID)':24s} {d['name'][:88]}")

    tokens = sorted({d["token"] for d in candidates if d["token"]})
    if tokens:
        print("\n把下面片段写进 config.json 即可只对 X1 生效:")
        print(json.dumps({
            "settings": {
                "device_filter_enabled": True,
                "device_whitelist": tokens,
            }
        }, indent=2, ensure_ascii=False))
    print("\n提示: 小米 X1 由 ODM 代工，VID 未必是 2717；以拔插对比结果为准。")
    return 0


if __name__ == "__main__":
    # 允许 `python -m tools.detect_device` 从工程根目录直接运行
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    raise SystemExit(main())
