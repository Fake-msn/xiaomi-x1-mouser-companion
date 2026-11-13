"""调度引擎：把「前台应用 → 档位 → 按键映射 → 动作注入」串起来。

兼容性最关键的一行在 handle_event 开头：
    if event.key not in self._blocked: return
即「没有被明确声明为 companion 所有的事件，伴生层连动作都不执行」。
否则 G-HUB 已经处理过的按键会被我们再触发一次，造成双重动作。
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from . import config as cfgmod
from .actions import resolve_action, is_supported_action
from .app_detector import AppDetector
from .buttons import is_ownable
from .devices import whitelist_satisfied
from .gesture import GestureRecognizer
from .key_capture import resolve_action_codes
from .key_simulator import Injector, resolve_vk_codes
from .mouse_hook import MouseEvent, MouseHook


class Engine:
    def __init__(self, cfg: dict, *, dry_run: bool = False,
                 injector: Injector | None = None,
                 hook: MouseHook | None = None,
                 detector: AppDetector | None = None,
                 on_status: Callable[[dict], None] | None = None):
        self.cfg = cfg
        self.injector = injector or Injector(dry_run=dry_run)
        self.on_status = on_status
        self._queue: queue.Queue[MouseEvent] = queue.Queue(maxsize=512)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._force_bypass = False

        self.active_profile, self._profile = cfgmod.get_profile(cfg)
        self._blocked = cfgmod.build_blocked_events(cfg, self._profile)
        self.current_identities: tuple[str, ...] = ()
        self.last_action = ""
        self._device_ok, self._device_msg = whitelist_satisfied(cfg)

        settings = cfg.get("settings", {})
        self._gesture = GestureRecognizer(
            threshold_px=settings.get("gesture_threshold_px", 25),
            commit_window_ms=settings.get("gesture_commit_window_ms", 400),
            cross_ratio=settings.get("gesture_cross_ratio", 0.5),
        )
        self._gesture_owner: str | None = None

        self.hook = hook or MouseHook(
            on_event=self._enqueue,
            should_intercept=self.should_intercept,
            blocked_provider=lambda: self._blocked,
            on_move=self._on_move,
        )
        self.detector = detector or AppDetector(
            on_change=self.on_foreground_change,
            interval=settings.get("poll_interval_s", 0.3),
        )
        # 把测试/CLI 注入的事件也接到同一条队列
        self.hook.events = self._queue

    # ── 生命周期 ─────────────────────────────────────────────
    def start(self, *, with_hook: bool = True, with_detector: bool = True) -> bool:
        self._stop.clear()
        self._worker = threading.Thread(target=self._dispatch_loop,
                                        daemon=True, name="DispatchWorker")
        self._worker.start()
        if with_detector:
            self.detector.start()
        if with_hook:
            return self.hook.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self.detector.stop()
        self.hook.stop()
        if self._worker:
            self._worker.join(timeout=2)
            self._worker = None

    # ── 共存护栏 ─────────────────────────────────────────────
    def should_intercept(self) -> bool:
        s = self.cfg.get("settings", {})
        if self._force_bypass or s.get("bypass") or s.get("game_mode"):
            return False
        return bool(self._device_ok)

    def refresh_devices(self) -> tuple[bool, str]:
        self._device_ok, self._device_msg = whitelist_satisfied(self.cfg)
        return self._device_ok, self._device_msg

    def set_bypass(self, value: bool) -> None:
        self._force_bypass = bool(value)
        self._recompute()
        self._emit()

    def set_game_mode(self, value: bool) -> None:
        self.cfg.setdefault("settings", {})["game_mode"] = bool(value)
        self._recompute()
        self._emit()

    def set_ownership(self, button: str, owner: str) -> None:
        cfgmod.set_ownership(self.cfg, button, owner)
        self._recompute()
        self._emit()

    def set_profile(self, name: str) -> bool:
        if name not in self.cfg["profiles"]:
            return False
        self.cfg["active_profile"] = name
        self.active_profile, self._profile = cfgmod.get_profile(self.cfg, name)
        self._recompute()
        self._emit()
        return True

    def reload(self, cfg: dict) -> None:
        with self._lock:
            self.cfg = cfg
            self.active_profile, self._profile = cfgmod.get_profile(cfg)
            self._device_ok, self._device_msg = whitelist_satisfied(cfg)
            self._recompute()
        self._emit()

    def _recompute(self) -> None:
        with self._lock:
            # 旁路必须同时关断「钩子层」和「调度层」：
            # 前者让事件全透传，后者保证任何绕过钩子的路径也不会注入动作。
            if self._force_bypass:
                self._blocked = frozenset()
            else:
                self._blocked = cfgmod.build_blocked_events(self.cfg, self._profile)

    # ── 前台应用 → 档位 ──────────────────────────────────────
    def on_foreground_change(self, identities) -> None:
        ids = tuple(str(i) for i in identities if i)
        self.current_identities = ids
        name, profile = cfgmod.resolve_profile(self.cfg, ids)
        with self._lock:
            self.active_profile = name
            self._profile = profile
            self.cfg["active_profile"] = name
            self._blocked = cfgmod.build_blocked_events(self.cfg, profile)
        self._emit()

    # ── 事件链 ──────────────────────────────────────────────
    def _enqueue(self, event: MouseEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass

    def _on_move(self, x: int, y: int) -> None:
        # 在钩子线程里只做 O(1) 采样，绝不在这里注入动作
        if self._gesture_owner and self._gesture.active:
            self._gesture.sample_point(x, y)

    def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.handle_event(event)
            except Exception as exc:  # 调度异常绝不能影响钩子线程
                self.last_action = f"error: {exc}"

    def handle_event(self, event: MouseEvent) -> None:
        """只处理被明确声明为 companion 所有的事件。"""
        if event.key not in self._blocked:
            return
        if event.kind == "move" or event.button == "pointer":
            return

        with self._lock:
            mappings = dict(self._profile.get("mappings", {}))
            gestures = dict(self._profile.get("gestures", {}))

        action_id = mappings.get(event.button, "none")

        # 手势键：按下开始采样，松开结算方向
        if action_id == "gesture_swipe" or event.button in gestures:
            slots = gestures.get(event.button, {})
            if event.kind == "down":
                self._gesture_owner = event.button
                self._gesture.begin(event.x, event.y, time.monotonic() * 1000)
                return
            if event.kind == "up" and self._gesture_owner == event.button:
                direction = self._gesture.finish(time.monotonic() * 1000)
                self._gesture_owner = None
                target = slots.get(direction or "", "none")
                self.execute(target)
                return
            return

        if event.kind != "down" and event.kind != "wheel":
            return
        self.execute(action_id)

    def execute(self, action_id: str) -> bool:
        """执行一个动作 ID；返回是否真的注入了什么。"""
        if not action_id or action_id == "none":
            self.last_action = "none (pass-through)"
            return False
        action = resolve_action(action_id)
        if action is None:
            self.last_action = f"unknown action: {action_id}"
            return False
        self.last_action = f"{action_id} -> {action.label}"
        if action.special in ("none", "gesture"):
            return False
        if action.special == "ring":
            # 动作环是可选 UI 功能；无 UI 时降级为不操作，绝不误触发
            return False
        if action.mouse:
            return self.injector.mouse_button(action.mouse)
        if action.scroll is not None:
            return self.injector.scroll(action.scroll)
        codes = resolve_action_codes(action_id) or resolve_vk_codes(action.vks)
        if not codes:
            return False
        return self.injector.key_combo(codes)

    # 测试 / CLI 用：绕过钩子直接把事件送进调度链
    def inject_test_event(self, button: str, kind: str = "down", **kwargs) -> None:
        self.handle_event(MouseEvent(button=button, kind=kind, **kwargs))

    # ── 状态 ────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "active_profile": self.active_profile,
            "foreground": list(self.current_identities),
            "blocked_events": sorted(self._blocked),
            "bypass": self._force_bypass or bool(self.cfg.get("settings", {}).get("bypass")),
            "game_mode": bool(self.cfg.get("settings", {}).get("game_mode")),
            "device_ok": self._device_ok,
            "device_msg": self._device_msg,
            "last_action": self.last_action,
            "injected": list(self.injector.sent[-10:]) if self.injector.dry_run else [],
        }

    def _emit(self) -> None:
        if self.on_status:
            try:
                self.on_status(self.status())
            except Exception:
                pass
