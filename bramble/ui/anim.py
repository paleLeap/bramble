"""Time-based tweens, re-targetable mid-flight like a CSS transition."""
from __future__ import annotations

import time
from typing import Callable

from . import look


def now() -> float:
    return time.monotonic()


class Prop:
    """One animated number. set() starts a transition from wherever it is now."""

    def __init__(self, value: float, ms: float = look.MOVE_MS,
                 curve: Callable[[float], float] = look.ease):
        self.a = self.b = float(value)
        self.t0 = 0.0
        self.ms = ms
        self.curve = curve

    def set(self, target: float, ms: float | None = None, curve=None) -> None:
        target = float(target)
        if target == self.b:
            return
        self.a = self.value
        self.b = target
        self.t0 = now()
        if ms is not None:
            self.ms = ms
        if curve is not None:
            self.curve = curve

    def jump(self, value: float) -> None:
        self.a = self.b = float(value)
        self.t0 = 0.0

    @property
    def progress(self) -> float:
        if self.ms <= 0 or self.a == self.b:
            return 1.0
        return look.clamp((now() - self.t0) * 1000 / self.ms)

    @property
    def value(self) -> float:
        p = self.progress
        return self.b if p >= 1 else self.a + (self.b - self.a) * self.curve(p)

    @property
    def moving(self) -> bool:
        return self.progress < 1.0

    @property
    def target(self) -> float:
        return self.b


class Timeline:
    """Hawthorn's corner-line clock: plays forward when opened, backward when closed."""

    def __init__(self, length: float):
        self.length = length
        self.opening = False
        self.t0 = 0.0
        self.base = 0.0             # where in the timeline the current run started

    def position(self) -> float:
        age = now() - self.t0
        if self.opening:
            return min(self.length, self.base + age)
        return max(0.0, self.base - age)

    def open(self) -> None:
        if not self.opening:
            self.base = self.position()
            self.t0 = now()
            self.opening = True

    def close(self) -> None:
        if self.opening:
            self.base = self.position()
            self.t0 = now()
            self.opening = False

    def part(self, span: tuple[float, float]) -> float:
        a, b = span
        return look.ease(look.clamp((self.position() - a) / (b - a)))

    @property
    def moving(self) -> bool:
        p = self.position()
        return (self.opening and p < self.length) or (not self.opening and p > 0)

    @property
    def shut(self) -> bool:
        return not self.opening and self.position() <= 0
