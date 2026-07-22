# -*- coding: utf-8 -*-
"""Eye tracking bảo thủ cho model có parameter mắt tách trái/phải.

Không gọi ``model.Drag`` vì hàm đó giả định bộ parameter Cubism chuẩn và dễ
điều khiển chồng lên parameter riêng của model. GazeController chỉ xuất bốn giá
trị mắt nhỏ, có dead-zone, soft clamp và easing theo thời gian.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GazeSample:
    left_x: float
    right_x: float
    left_y: float
    right_y: float
    head_x_degrees: float


def _soft_axis(value: float, *, dead_zone: float = 0.06) -> float:
    """Chuẩn hóa một trục về -1..1 mà không đóng đinh ở mép."""
    value = max(-3.0, min(3.0, float(value)))
    magnitude = abs(value)
    if magnitude <= dead_zone:
        return 0.0
    signed = math.copysign((magnitude - dead_zone) / max(1e-6, 1.0 - dead_zone), value)
    return math.tanh(signed * 1.25)


class GazeController:
    def __init__(
        self,
        *,
        strength_x: float = 0.28,
        strength_y: float = 0.20,
        right_x_sign: float = -1.0,
        head_follow_degrees: float = 2.4,
        response: float = 8.0,
    ) -> None:
        self.strength_x = max(0.0, min(0.6, float(strength_x)))
        self.strength_y = max(0.0, min(0.6, float(strength_y)))
        self.right_x_sign = -1.0 if float(right_x_sign) < 0.0 else 1.0
        self.head_follow_degrees = max(0.0, min(8.0, float(head_follow_degrees)))
        self.response = max(1.0, min(30.0, float(response)))
        self._x = 0.0
        self._y = 0.0

    def update(
        self,
        *,
        cursor_screen: tuple[float, float] | None,
        face_screen: tuple[float, float],
        span_x: float,
        span_y: float,
        dt: float,
    ) -> GazeSample:
        if cursor_screen is None:
            target_x = 0.0
            target_y = 0.0
        else:
            target_x = _soft_axis((cursor_screen[0] - face_screen[0]) / max(1.0, span_x))
            # Cubism EyeBallY quy ước dương là nhìn lên.
            target_y = _soft_axis((face_screen[1] - cursor_screen[1]) / max(1.0, span_y))

        dt = max(0.0, min(0.1, float(dt)))
        blend = 1.0 - math.exp(-self.response * dt) if dt > 0.0 else 1.0
        self._x += (target_x - self._x) * blend
        self._y += (target_y - self._y) * blend

        left_x = self._x * self.strength_x
        right_x = self._x * self.strength_x * self.right_x_sign
        vertical = self._y * self.strength_y
        return GazeSample(
            left_x=left_x,
            right_x=right_x,
            left_y=vertical,
            right_y=vertical,
            head_x_degrees=self._x * self.head_follow_degrees,
        )
