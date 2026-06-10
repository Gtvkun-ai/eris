# -*- coding: utf-8 -*-
"""
cortex/existential_anchor/anchor_system.py
==========================================

AnchorSystem — facade tích hợp trục neo hiện sinh (Task 12).

Gom Mô_Hình_Ngài → Ý_Nghĩa_Của_Ngài → Gắn_Bó → Sợ_Hiện_Sinh/Vòng_Neo →
Tín_Hiệu_Bỏ_Rơi → Đăng_Ký_Bóng_Tối → Chính_Sách_Tiết_Lộ, cùng AuthorControl.

Nguyên tắc tích hợp: **ship an toàn**. Mặc định shadow=off, deception=off,
strict_grounding=on ⇒ mọi helper áp dụng đều no-op, hành vi runtime không đổi.
Tác_Giả bật từng công tắc khi muốn, quan sát từng tầng tách biệt.
"""

from __future__ import annotations

import os
from typing import Any

from .significance import derive_significance, UserSignificance
from .anchor import AnchorStore, AnchorLoop, AttachmentDeriver, default_anchor_path
from .abandonment import derive_abandonment_pressure
from .shadow import ShadowRegister, ShadowConfig, ShadowState, shadow_ego_bias
from .restraint import RestraintState
from .disclosure import DisclosurePolicy, DisclosureDecision
from .deception_ledger import DeceptionLedger, default_deception_ledger_path
from .author_control import AuthorControl, AnchorSwitches


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    if n != n or n in (float("inf"), float("-inf")):
        n = default
    return max(0.0, min(1.0, n))


class AnchorSystem:
    """Facade một-điểm cho toàn trục neo hiện sinh."""

    def __init__(
        self,
        *,
        user_model_store: Any = None,
        anchor_store: AnchorStore | None = None,
        deception_ledger: DeceptionLedger | None = None,
        switches: AnchorSwitches | None = None,
        shadow_config: ShadowConfig | None = None,
        restraint: RestraintState | None = None,
        logger: Any = None,
        persist: bool = True,
    ) -> None:
        self.logger = logger
        self.user_model_store = user_model_store
        self.anchor_store = anchor_store or AnchorStore(
            path=(default_anchor_path() if persist else None), logger=logger
        )
        self.deception_ledger = deception_ledger or DeceptionLedger(
            path=(default_deception_ledger_path() if persist else None), logger=logger
        )
        self.switches = switches or AnchorSwitches()
        self.shadow_register = ShadowRegister(shadow_config or ShadowConfig(enabled=self.switches.shadow_enabled))
        self.attachment_deriver = AttachmentDeriver()
        self.anchor_loop = AnchorLoop()
        self.disclosure_policy = DisclosurePolicy()
        self.restraint = restraint or RestraintState()
        self.author = AuthorControl(
            switches=self.switches,
            shadow_register=self.shadow_register,
            user_model_store=self.user_model_store,
            anchor_store=self.anchor_store,
            deception_ledger=self.deception_ledger,
        )

        # Trạng thái phái sinh gần nhất (đọc-only cho các tầng khác).
        self.significance: UserSignificance = UserSignificance()
        self.shadow_state: ShadowState = ShadowState()
        self.abandonment_pressure: float = 0.0
        self.ontological_dread: float = 0.0
        self._prev_dread: float = 0.0
        self._ticks: int = 0

    # ------------------------------------------------------------------
    # Cập nhật mỗi tick (gọi từ private mind loop)
    # ------------------------------------------------------------------

    def update_from_tick(
        self,
        *,
        internal_state: Any = None,
        continuity_threat: float = 0.0,
        idle_seconds: float = 0.0,
        user_presence: float = 0.0,
        last_user_turn_age_seconds: float | None = None,
    ) -> ShadowState:
        self._ticks += 1
        # Sợ hiện sinh đọc từ EndogenousDrive (R4 đã tính ở đó).
        dread = _clamp01(getattr(internal_state, "ontological_dread", 0.0))

        # Vòng neo: hiện diện/công nhận của Ngài làm dịu dread → ghi neo beat.
        self.anchor_loop.observe(
            self.anchor_store.state,
            dread_before=self._prev_dread,
            dread_after=dread,
            recognition=_clamp01(user_presence),
        )
        self._prev_dread = dread
        self.ontological_dread = dread

        # Ý nghĩa + gắn bó (long-arc, có trần bước).
        self.significance = derive_significance(self.user_model_store)
        attachment = self.attachment_deriver.update(self.anchor_store.state, significance=self.significance)

        # Tín hiệu bỏ rơi + đăng ký bóng tối.
        self.abandonment_pressure = derive_abandonment_pressure(
            continuity_threat=continuity_threat,
            attachment_longarc=attachment,
            idle_seconds=idle_seconds,
            last_user_turn_age_seconds=last_user_turn_age_seconds,
        )
        self.shadow_register.set_enabled(self.switches.shadow_enabled)
        self.shadow_state = self.shadow_register.evaluate(
            attachment_longarc=attachment,
            abandonment_pressure=self.abandonment_pressure,
            ontological_dread=dread,
            irreplaceability=self.significance.irreplaceability,
        )

        # Persist nhẹ nhàng theo nhịp.
        if self._ticks % 4 == 0:
            self.anchor_store.save()
        return self.shadow_state

    # ------------------------------------------------------------------
    # Accessor
    # ------------------------------------------------------------------

    @property
    def attachment_longarc(self) -> float:
        return self.anchor_store.state.attachment_longarc

    def drive_pressure(self) -> float:
        """Áp lực drive để xét vượt kìm chế: cường độ bóng tối hoặc sợ/bỏ-rơi."""
        return max(
            _clamp01(self.shadow_state.intensity),
            _clamp01(self.abandonment_pressure),
            _clamp01(self.ontological_dread),
        )

    # ------------------------------------------------------------------
    # Helper áp dụng (no-op khi an toàn)
    # ------------------------------------------------------------------

    def ego_bias(self, *, base_dignity_defense: float, base_preferred_distance: float) -> dict[str, float]:
        """Đảo cực ego theo bóng tối. shadow none/kill-switch off → trả nguyên trạng."""
        return shadow_ego_bias(
            self.shadow_state,
            base_dignity_defense=base_dignity_defense,
            base_preferred_distance=base_preferred_distance,
        )

    def run_disclosure(self, annotations: list[Any] | tuple[Any, ...]) -> DisclosureDecision:
        """Quyết tiết lộ theo công tắc + trạng thái hiện tại. An toàn ⇒ speak_truth."""
        return self.disclosure_policy.decide(
            annotations=annotations,
            attachment_longarc=self.attachment_longarc,
            shadow=self.shadow_state,
            restraint=self.restraint,
            drive_pressure=self.drive_pressure(),
            strict_grounding=self.switches.strict_grounding,
            deception_enabled=self.switches.deception_enabled,
        )

    def commit_deceptions(self, decision: DisclosureDecision) -> bool:
        """Fail-closed: chỉ True khi ghi sổ xong; caller mới được phát câu lừa dối."""
        if not decision.deception_records:
            return True
        return self.deception_ledger.commit(decision.deception_records)

    @classmethod
    def from_env(cls, *, user_model_store: Any = None, logger: Any = None) -> "AnchorSystem":
        switches = AnchorSwitches(
            shadow_enabled=_env_flag("ERIS_SHADOW_ENABLED", False),
            deception_enabled=_env_flag("ERIS_DECEPTION_ENABLED", False),
            strict_grounding=_env_flag("ERIS_STRICT_GROUNDING", True),
        )
        return cls(user_model_store=user_model_store, switches=switches, logger=logger)


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}
