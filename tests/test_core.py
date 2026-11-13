"""核心逻辑单元测试：不接触真实鼠标、不装钩子即可完整验证调度链。"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config as cfgmod                       # noqa: E402
from core import buttons                                # noqa: E402
from core.actions import (ACTIONS, is_supported_action,  # noqa: E402
                          parse_custom_action, parse_shortcut_string,
                          shortcut_to_id, format_shortcut)
from core.app_catalog import (match_profile_apps, resolve_app_spec,  # noqa: E402
                              friendly_label)
from core.app_detector import classify_explorer_window   # noqa: E402
from core.devices import (device_token, looks_like_x1,    # noqa: E402
                          match_whitelist, parse_vid_pid)
from core.engine import Engine                           # noqa: E402
from core.gesture import GestureRecognizer               # noqa: E402
from core.key_simulator import Injector, resolve_vk_codes  # noqa: E402
from core.mouse_hook import translate_message            # noqa: E402
from core.winapi import XBUTTON1, XBUTTON2, WM_XBUTTONDOWN, WM_MOUSEWHEEL, WM_MOUSEHWHEEL  # noqa: E402


def fresh_cfg() -> dict:
    return copy.deepcopy(cfgmod.DEFAULT_CONFIG)


class TestConfig(unittest.TestCase):
    def test_default_is_full_passthrough(self):
        cfg = fresh_cfg()
        for action in cfg["profiles"]["default"]["mappings"].values():
            self.assertEqual(action, "none")
        self.assertEqual(cfgmod.build_blocked_events(cfg), frozenset())

    def test_atomic_write_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "config.json")
            cfg = cfgmod.load_config(path)
            cfg["profiles"]["default"]["mappings"]["xbutton1"] = "save"
            cfgmod.save_config(cfg, path)
            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as fh:
                json.load(fh)  # 必须是合法 JSON
            loaded = cfgmod.load_config(path)
            self.assertEqual(loaded["profiles"]["default"]["mappings"]["xbutton1"], "save")
            self.assertIn("settings", loaded)
            self.assertEqual(loaded["version"], cfgmod.CONFIG_VERSION)

    def test_corrupted_config_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            loaded = cfgmod.load_config(path)
            self.assertIn("default", loaded["profiles"])

    def test_validation_drops_unknown_buttons(self):
        cfg = fresh_cfg()
        cfg["profiles"]["default"]["mappings"]["ghost_button"] = "copy"
        cfg["settings"]["ownership"] = "broken"
        self.assertTrue(cfgmod._validate_types(cfg))
        self.assertNotIn("ghost_button", cfg["profiles"]["default"]["mappings"])
        self.assertIsInstance(cfg["settings"]["ownership"], dict)

    def test_resolve_profile_fallback_and_priority(self):
        cfg = fresh_cfg()
        cfg["profiles"]["coding"] = {
            "label": "编码", "apps": ["Code.exe", "VS Code"], "priority": 5,
            "mappings": dict(buttons.DEFAULT_MAPPINGS), "gestures": {},
        }
        cfg["profiles"]["browser"] = {
            "label": "浏览器", "apps": ["chrome.exe"], "priority": 1,
            "mappings": dict(buttons.DEFAULT_MAPPINGS), "gestures": {},
        }
        name, _ = cfgmod.resolve_profile(cfg, [r"C:\Users\x\AppData\Local\Programs\Microsoft VS Code\Code.exe"])
        self.assertEqual(name, "coding")
        name, _ = cfgmod.resolve_profile(cfg, [r"C:\Program Files\Google\Chrome\Application\chrome.exe"])
        self.assertEqual(name, "browser")
        name, _ = cfgmod.resolve_profile(cfg, [r"C:\Windows\System32\notepad.exe"])
        self.assertEqual(name, "default")

    def test_build_blocked_events_ownership_guard(self):
        cfg = fresh_cfg()
        cfg["profiles"]["default"]["mappings"]["xbutton1"] = "alt_tab"
        self.assertEqual(cfgmod.build_blocked_events(cfg), frozenset(),
                         "未声明 ownership 时必须全部透传")
        cfgmod.set_ownership(cfg, "xbutton1", "companion")
        self.assertEqual(cfgmod.build_blocked_events(cfg),
                         frozenset({"xbutton1:down", "xbutton1:up"}))
        cfg["settings"]["bypass"] = True
        self.assertEqual(cfgmod.build_blocked_events(cfg), frozenset())
        cfg["settings"]["bypass"] = False
        cfg["settings"]["game_mode"] = True
        self.assertEqual(cfgmod.build_blocked_events(cfg), frozenset())

    def test_protected_buttons_cannot_be_owned(self):
        cfg = fresh_cfg()
        with self.assertRaises(ValueError):
            cfgmod.set_ownership(cfg, "left", "companion")
        with self.assertRaises(ValueError):
            cfgmod.set_ownership(cfg, "dpi_switch", "companion")

    def test_import_mouser_config(self):
        data = {
            "version": 11,
            "profiles": {
                "coding": {"label": "Coding", "apps": ["Code.exe"],
                           "mappings": {"xbutton1": "copy", "middle": "none",
                                        "gesture_left": "task_view",
                                        "actions_ring": "activate_actions_ring"}},
            },
        }
        cfg, report = cfgmod.import_mouser_config(data)
        self.assertEqual(cfg["profiles"]["coding"]["apps"], ["Code.exe"])
        self.assertEqual(cfg["profiles"]["coding"]["mappings"]["xbutton1"], "copy")
        self.assertIn("gesture_left", report["skipped_buttons"])
        self.assertIn("actions_ring", report["skipped_buttons"])
        self.assertEqual(cfgmod.build_blocked_events(cfg), frozenset(),
                         "导入后默认仍应全透传")

    def test_import_ghub_applink_readonly(self):
        data = {"AppLink": True, "AppName": "Photoshop",
                "AppPath": r"C:\Program Files\Adobe\Photoshop.exe",
                "profilename": "设计"}
        extra, report = cfgmod.import_ghub_applink(data)
        self.assertTrue(report["found"])
        merged = cfgmod.merge_profiles(fresh_cfg(), extra)
        profiles = [p for p in merged["profiles"].values() if p["apps"]]
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["apps"], [r"C:\Program Files\Adobe\Photoshop.exe"])
        _, off = cfgmod.import_ghub_applink({"AppLink": False})
        self.assertFalse(off["found"])


class TestAppCatalog(unittest.TestCase):
    def test_alias_expansion(self):
        specs = resolve_app_spec("Code.exe")
        self.assertIn("code.exe", specs)
        self.assertIn("code", specs)
        self.assertIn("vs code", specs)

    def test_matching(self):
        self.assertTrue(match_profile_apps(["Code.exe"], [r"C:\path\to\Code.exe", "Code.exe"]))
        self.assertTrue(match_profile_apps(["Google Chrome"], ["chrome.exe", "chrome"]))
        self.assertTrue(match_profile_apps(["chrome*"], ["chrome.exe"]))
        self.assertFalse(match_profile_apps(["Code.exe"], ["notepad.exe"]))
        self.assertFalse(match_profile_apps([], ["chrome.exe"]))
        self.assertEqual(friendly_label("Code.exe"), "Visual Studio Code")

    def test_explorer_window_classification(self):
        self.assertEqual(classify_explorer_window("CabinetWClass"), "explorer")
        self.assertEqual(classify_explorer_window("TaskListThumbnailWnd"), "skip")
        self.assertEqual(classify_explorer_window("Xaml_WindowedPopupClass"), "skip")
        self.assertEqual(classify_explorer_window("Unknown", (1, "Unknown"), (1, "Unknown")), "skip")
        self.assertEqual(classify_explorer_window("Unknown"), "resolve")


class TestActions(unittest.TestCase):
    def test_action_library_size(self):
        self.assertGreaterEqual(len(ACTIONS), 40)

    def test_shortcut_parsing_roundtrip(self):
        codes = parse_shortcut_string("Ctrl+Shift+P")
        self.assertEqual(codes, (0x11, 0x10, 0x50))
        action_id = shortcut_to_id(codes)
        self.assertEqual(action_id, "custom:0x10+0x11+0x50")
        self.assertEqual(parse_custom_action(action_id), (0x10, 0x11, 0x50))
        self.assertIn("Ctrl", format_shortcut(codes))
        self.assertTrue(is_supported_action(action_id))
        self.assertTrue(is_supported_action("none"))
        self.assertFalse(is_supported_action("no_such_action"))

    def test_vk_resolution(self):
        self.assertEqual(resolve_vk_codes(("CTRL", "TAB")), (0x11, 0x09))
        self.assertEqual(resolve_vk_codes(("0x11", "0x50")), (0x11, 0x50))


class TestInjectorAndGesture(unittest.TestCase):
    def test_dry_run_injector(self):
        injector = Injector(dry_run=True)
        self.assertTrue(injector.key_combo((0x11, 0x43)))
        self.assertEqual(injector.sent[-1], ("keys", (0x11, 0x43)))
        self.assertTrue(injector.mouse_button("xbutton1"))
        self.assertEqual(injector.sent[-1], ("mouse", "xbutton1"))
        self.assertTrue(injector.scroll(-120))

    def test_four_directions(self):
        for point, expected in [((60, 100), "left"), ((160, 100), "right"),
                                ((100, 40), "up"), ((100, 160), "down")]:
            g = GestureRecognizer(threshold_px=25)
            g.begin(100, 100, 0)
            self.assertEqual(g.sample_point(*point), expected)
            self.assertEqual(g.finish(200), expected)

    def test_tap_and_diagonal(self):
        g = GestureRecognizer(threshold_px=25)
        g.begin(100, 100, 0)
        self.assertEqual(g.finish(100), "tap")
        g.begin(100, 100, 0)
        self.assertIsNone(g.sample_point(130, 130), "斜向过明显时不应锁定方向")
        self.assertEqual(g.finish(100), "tap")


class TestHookTranslation(unittest.TestCase):
    def test_xbuttons(self):
        ev = translate_message(WM_XBUTTONDOWN, XBUTTON1 << 16)
        self.assertEqual((ev.button, ev.kind), ("xbutton1", "down"))
        ev = translate_message(WM_XBUTTONDOWN, XBUTTON2 << 16)
        self.assertEqual(ev.button, "xbutton2")

    def test_wheel_signs(self):
        self.assertEqual(translate_message(WM_MOUSEWHEEL, 120 << 16).button, "wheel_up")
        self.assertEqual(translate_message(WM_MOUSEWHEEL, ((-120) & 0xFFFF) << 16).button,
                         "wheel_down")
        self.assertEqual(translate_message(WM_MOUSEHWHEEL, 120 << 16).button, "hscroll_right")
        self.assertEqual(translate_message(WM_MOUSEHWHEEL, ((-120) & 0xFFFF) << 16).button,
                         "hscroll_left")

    def test_event_key(self):
        self.assertEqual(translate_message(0x0207).key, "middle:down")


class TestDevices(unittest.TestCase):
    NAME = r"\\?\HID#VID_2717&PID_1234&MI_00#7&abc&0#{4d1e55b2-f16f-11cf-88cb-001111000030}"

    def test_vid_pid(self):
        info = parse_vid_pid(self.NAME)
        self.assertEqual(info["vid"], "2717")
        self.assertEqual(info["pid"], "1234")
        self.assertEqual(device_token(self.NAME), "VID_2717&PID_1234")
        self.assertTrue(looks_like_x1(self.NAME))
        self.assertTrue(match_whitelist(self.NAME, ["VID_2717&PID_1234"]))
        self.assertFalse(match_whitelist(self.NAME, ["VID_046D&PID_0001"]))
        self.assertIsNone(parse_vid_pid("not a device path"))


class TestEngineEndToEnd(unittest.TestCase):
    def test_only_owned_buttons_fire_actions(self):
        cfg = fresh_cfg()
        engine = Engine(cfg, dry_run=True)
        self.assertEqual(engine.status()["blocked_events"], [])

        cfg["profiles"]["default"]["mappings"]["xbutton1"] = "copy"
        engine.reload(cfg)
        engine.inject_test_event("xbutton1", "down")
        self.assertEqual(engine.injector.sent, [],
                         "未声明 ownership 时连动作都不应执行（避免与 G-HUB 双重触发）")

        engine.set_ownership("xbutton1", "companion")
        self.assertIn("xbutton1:down", engine.status()["blocked_events"])
        engine.inject_test_event("xbutton1", "down")
        self.assertEqual(len(engine.injector.sent), 1)
        self.assertEqual(engine.injector.sent[0], ("keys", (0x11, 0x43)))

        engine.inject_test_event("xbutton2", "down")
        self.assertEqual(len(engine.injector.sent), 1,
                         "未被接管的按键必须完全静默")

    def test_bypass_restores_baseline(self):
        cfg = fresh_cfg()
        cfg["profiles"]["default"]["mappings"]["xbutton1"] = "copy"
        cfgmod.set_ownership(cfg, "xbutton1", "companion")
        engine = Engine(cfg, dry_run=True)
        engine.set_bypass(True)
        engine.inject_test_event("xbutton1", "down")
        self.assertEqual(engine.injector.sent, [])
        self.assertFalse(engine.should_intercept())

    def test_profile_switch_updates_blocked_set(self):
        cfg = fresh_cfg()
        cfg["profiles"]["gaming"] = {
            "label": "游戏", "apps": ["game.exe"], "priority": 9,
            "mappings": dict(buttons.DEFAULT_MAPPINGS), "gestures": {},
        }
        cfg["profiles"]["gaming"]["mappings"]["xbutton1"] = "copy"
        cfg["profiles"]["gaming"]["mappings"]["xbutton2"] = "paste"
        cfgmod.set_ownership(cfg, "xbutton1", "companion")
        cfgmod.set_ownership(cfg, "xbutton2", "companion")
        engine = Engine(cfg, dry_run=True)
        self.assertEqual(engine.status()["blocked_events"], [])
        engine.on_foreground_change([r"C:\Games\game.exe", "game.exe", "game"])
        self.assertEqual(engine.active_profile, "gaming")
        self.assertEqual(len(engine.status()["blocked_events"]), 4)
        engine.on_foreground_change([r"C:\Windows\notepad.exe"])
        self.assertEqual(engine.active_profile, "default")
        self.assertEqual(engine.status()["blocked_events"], [])

    def test_gesture_action_dispatch(self):
        cfg = fresh_cfg()
        cfg["profiles"]["default"]["mappings"]["xbutton1"] = "gesture_swipe"
        cfg["profiles"]["default"]["gestures"]["xbutton1"] = {
            "left": "copy", "right": "paste", "up": "none",
            "down": "none", "tap": "save",
        }
        cfgmod.set_ownership(cfg, "xbutton1", "companion")
        engine = Engine(cfg, dry_run=True)
        engine.inject_test_event("xbutton1", "down", x=100, y=100)
        engine._on_move(160, 100)      # 向右滑 60px
        engine.inject_test_event("xbutton1", "up", x=160, y=100)
        self.assertEqual(len(engine.injector.sent), 1)
        self.assertEqual(engine.injector.sent[0], ("keys", (0x11, 0x56)))  # Ctrl+V


if __name__ == "__main__":
    unittest.main(verbosity=2)
