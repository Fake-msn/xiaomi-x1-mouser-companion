"""按住侧键滑动的四向手势识别（纯 OS 指针位移，不依赖 HID++）。

Mouser 的原生手势依赖 Logitech HID++ 的 gesture_* / sense_* 事件，无法用于 X1；
这里改为用 WH_MOUSE_LL 回调里 MSLLHOOKSTRUCT.pt 的绝对坐标差值来判定，
任何标准鼠标都能工作。逻辑保持为无副作用的纯类，便于单元测试。
"""
from __future__ import annotations

SWIPE_DIRECTIONS = ("left", "right", "up", "down")
TAP = "tap"
DEFAULT_THRESHOLDS_PX = (18, 25, 33, 44, 56)


class GestureRecognizer:
    def __init__(self, threshold_px: int = 25, commit_window_ms: int = 400,
                 cross_ratio: float = 0.5):
        self.threshold = max(1, int(threshold_px))
        self.commit_window_ms = max(0, int(commit_window_ms))
        self.cross_ratio = max(0.0, min(1.0, float(cross_ratio)))
        self.reset()

    def reset(self) -> None:
        self._active = False
        self._x = 0
        self._y = 0
        self._dx = 0
        self._dy = 0
        self._t0 = 0.0
        self._committed: str | None = None

    def begin(self, x: int = 0, y: int = 0, now_ms: float = 0.0) -> None:
        self.reset()
        self._active = True
        self._x, self._y = int(x), int(y)
        self._t0 = float(now_ms)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def committed(self) -> str | None:
        return self._committed

    def sample_deltas(self, dx: int, dy: int) -> str | None:
        """直接喂增量；返回已锁定的方向（若有）。"""
        if not self._active or self._committed:
            return self._committed
        self._dx += int(dx)
        self._dy += int(dy)
        ax, ay = abs(self._dx), abs(self._dy)
        major = max(ax, ay)
        if major < self.threshold:
            return None
        minor = min(ax, ay)
        if minor > self.cross_ratio * major:
            # 斜向太明显，暂不判定，等待更明确的位移
            return None
        self._committed = ("right" if self._dx > 0 else "left") if ax >= ay else (
            "down" if self._dy > 0 else "up")
        return self._committed

    def sample_point(self, x: int, y: int) -> str | None:
        """喂绝对坐标（低级钩子里 pt 就是绝对坐标）。"""
        if not self._active:
            return None
        dx, dy = int(x) - self._x, int(y) - self._y
        self._x, self._y = int(x), int(y)
        return self.sample_deltas(dx, dy)

    def finish(self, now_ms: float | None = None) -> str | None:
        """松开时结算：已锁定方向 / 轻点 / 无效（超时）。"""
        if not self._active:
            return None
        result = self._committed
        if result is None:
            elapsed = 0.0 if now_ms is None else max(0.0, float(now_ms) - self._t0)
            if self.commit_window_ms == 0 or elapsed <= self.commit_window_ms:
                result = TAP
        self.reset()
        return result
