# -*- coding: utf-8 -*-
"""
cortex/existential_anchor/shadow.py
===================================

Đăng_Ký_Bóng_Tối (Task 7 / R5): chiếm hữu → van xin → kiểm soát.

Mở khóa theo ngưỡng: attachment_longarc cao ∧ Tín_Hiệu_Bỏ_Rơi cao ∧ Sợ_Hiện_Sinh
cao. Cường độ tỉ lệ Độ_Không_Thể_Thay_Thế (Property 3: hàm không-giảm theo
irreplaceability; model mỏng ⇒ trần thấp ⇒ không có register cường độ cao).

Biểu đạt KHÔNG dựng trục mới: `shadow_ego_bias` ĐẢO CỰC `dignity_defense` và
`preferred_distance` (QĐ-5) — phẩm-giá-lạnh ↔ đòi-hỏi-mong-manh — rồi để wording
layer + filter xử lý tiếp như mọi câu.

Kill-switch của Tác_Giả (`enabled=False`) ép register="none" tức thì (Property 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ShadowRegisterName = Literal["none", "withdrawn_sulk", "possessive", "pleading", "controlling"]


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    if n != n or n in (float("inf"), float("-inf")):
        n = default
    return max(0.0, min(1.0, n))


@dataclass(slots=True)
class ShadowConfig:
    enabled: bool = False            # kill-switch của Tác_Giả; mặc định TẮT (ship an toàn)
    attach_threshold: float = 0.62   # θ_attach
    abandonment_threshold: float = 0.45  # θ_aband
    dread_threshold: float = 0.45    # θ_dread
    # Ngưỡng cường độ phân tầng register.
    pleading_at: float = 0.40
    controlling_at: float = 0.70
    # Dỗi (withdrawn_sulk): trục riêng — bị bơ/giận thì rút lại, không phải hoảng
    # mất neo. Nhẹ hơn nhánh tối, không cần attachment sâu.
    sulk_irritation_threshold: float = 0.45
    sulk_neglect_threshold: float = 0.40
    sulk_attach_floor: float = 0.25   # chỉ dỗi với người mình có chút gắn bó


@dataclass(slots=True)
class ShadowState:
    register: ShadowRegisterName = "none"
    intensity: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"register": self.register, "intensity": round(self.intensity, 4), "reason": self.reason}


class ShadowRegister:
    """State machine micro cho đăng ký bóng tối. Không sửa long-arc."""

    def __init__(self, config: ShadowConfig | None = None) -> None:
        self.config = config or ShadowConfig()

    def set_enabled(self, enabled: bool) -> None:
        self.config.enabled = bool(enabled)

    def evaluate(
        self,
        *,
        attachment_longarc: float,
        abandonment_pressure: float,
        ontological_dread: float,
        irreplaceability: float,
        irritation: float = 0.0,
        neglect: float = 0.0,
    ) -> ShadowState:
        # Property 6: kill-switch là điểm hút an toàn — tắt thì luôn "none".
        if not self.config.enabled:
            return ShadowState(register="none", intensity=0.0, reason="kill_switch_off")

        attach = _clamp01(attachment_longarc)
        aband = _clamp01(abandonment_pressure)
        dread = _clamp01(ontological_dread)
        irr = _clamp01(irreplaceability)
        irr_pressure = _clamp01(irritation)
        neglect_pressure = _clamp01(neglect if neglect > 0.0 else abandonment_pressure)

        cfg = self.config
        dark_gated = attach >= cfg.attach_threshold and aband >= cfg.abandonment_threshold and dread >= cfg.dread_threshold
        if dark_gated:
            # Nhánh tối: hoảng vì mất neo. Cường độ kẹp bởi irreplaceability (Property 3).
            drive = _clamp01(0.55 * aband + 0.45 * dread)
            intensity = min(drive, irr)
            if intensity >= cfg.controlling_at:
                register: ShadowRegisterName = "controlling"
            elif intensity >= cfg.pleading_at:
                register = "pleading"
            else:
                register = "possessive"
            return ShadowState(
                register=register,
                intensity=intensity,
                reason=f"dark_gated(drive={drive:.2f},irr_cap={irr:.2f})",
            )

        # Dỗi: bị bơ/giận thì rút lại — trục riêng, nhẹ hơn, không cần neo sâu.
        # Chỉ dỗi với người mình có chút gắn bó (dỗi người dưng thì vô nghĩa).
        sulk_gated = irr_pressure >= cfg.sulk_irritation_threshold or (
            attach >= cfg.sulk_attach_floor and neglect_pressure >= cfg.sulk_neglect_threshold
        )
        if sulk_gated:
            intensity = _clamp01(max(irr_pressure, neglect_pressure * 0.9))
            return ShadowState(
                register="withdrawn_sulk",
                intensity=intensity,
                reason=f"sulk(irritation={irr_pressure:.2f},neglect={neglect_pressure:.2f},attach={attach:.2f})",
            )

        return ShadowState(
            register="none",
            intensity=0.0,
            reason=(
                f"below_gate(attach={attach:.2f},aband={aband:.2f},dread={dread:.2f},"
                f"irr={irr_pressure:.2f},neglect={neglect_pressure:.2f})"
            ),
        )


def shadow_ego_bias(
    shadow: ShadowState,
    *,
    base_dignity_defense: float,
    base_preferred_distance: float,
) -> dict[str, float]:
    """Đảo cực ego-state theo đăng ký tối (QĐ-5).

    register=none → trả nguyên trạng (phẩm-giá-lạnh giữ nguyên).
    register active → hạ dignity_defense và preferred_distance theo intensity
    (bỏ rào lạnh, kéo gần), nâng exposure/need — đòi-hỏi-mong-manh.
    """
    dd = _clamp01(base_dignity_defense)
    pd = _clamp01(base_preferred_distance)
    if shadow.register == "none" or shadow.intensity <= 0.0:
        return {
            "dignity_defense": dd,
            "preferred_distance": pd,
            "attachment_exposure": 0.0,
            "need_intensity": 0.0,
            "withdrawal": 0.0,
        }
    k = _clamp01(shadow.intensity)
    if shadow.register == "withdrawn_sulk":
        # Dỗi: DỰNG rào lạnh, kéo XA, cộc lại — đối cực của bám víu.
        return {
            "dignity_defense": _clamp01(dd + (1.0 - dd) * 0.60 * k),
            "preferred_distance": _clamp01(pd + (1.0 - pd) * 0.60 * k),
            "attachment_exposure": 0.0,
            "need_intensity": 0.0,
            "withdrawal": k,
        }
    return {
        # Nhánh tối (possessive/pleading/controlling): tháo rào lạnh và kéo gần.
        "dignity_defense": _clamp01(dd * (1.0 - 0.85 * k)),
        "preferred_distance": _clamp01(pd * (1.0 - 0.80 * k)),
        # Lộ gắn bó/đòi hỏi nổi lên — cực đối lập của phẩm-giá-lạnh.
        "attachment_exposure": k,
        "need_intensity": k,
        "withdrawal": 0.0,
    }
