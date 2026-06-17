# backend/app/core/providers/circuit.py
#
# 轻量异步熔断器。每个 provider 一个实例：连续失败到阈值就"跳闸"，
# 跳闸期间直接拒绝(不真正调用)，冷却后半开试探，成功即恢复。
from __future__ import annotations

import time


class CircuitOpenError(Exception):
    """熔断器处于 OPEN 状态时抛出——表示"该 provider 暂时不可用，别调了"。"""


class CircuitBreaker:
    def __init__(self, name: str, fail_max: int = 3, reset_timeout: float = 30.0):
        self.name = name
        self.fail_max = fail_max            # 连续失败多少次跳闸
        self.reset_timeout = reset_timeout  # 跳闸后冷却多少秒才允许半开试探
        self.failures = 0
        self.state = "closed"               # closed / open / half_open
        self.opened_at = 0.0

    def allow(self) -> bool:
        """这次调用是否放行。OPEN 且冷却已过 → 转 half_open 放一个试探。"""
        if self.state == "open":
            if time.monotonic() - self.opened_at >= self.reset_timeout:
                self.state = "half_open"
                return True
            return False                    # 仍在冷却 → 拒绝
        return True                         # closed / half_open → 放行

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"               # 成功 → 复位

    def record_failure(self) -> None:
        self.failures += 1
        # 半开试探失败、或连续失败达阈值 → 跳闸并重置冷却计时
        if self.state == "half_open" or self.failures >= self.fail_max:
            self.state = "open"
            self.opened_at = time.monotonic()


# ── 全局注册表：每个 provider 名一个熔断器(进程内共享)──────────────────────────────
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


def all_breakers() -> dict[str, CircuitBreaker]:
    return _breakers                        # 给 /health 暴露状态用