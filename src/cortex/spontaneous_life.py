# -*- coding: utf-8 -*-
"""Endogenous + situated speech pressure for ERIS.

Mô-đun này không viết câu công cộng. Nó tạo một SpeechImpulse bằng cách dựng
AgentStateStack rồi cho nhiều impulse cạnh tranh: silence, scene curiosity,
inner whim, micro story, companionship, technical help, body-only.

Điểm vá chính: ERIS không còn cần rule kiểu "5 phút nói một lần". Thời gian chỉ
làm tăng/giảm need; hành vi cuối do arbitration chọn. Cuối cùng thì cũng có một
chút văn minh trong đống dây điện này.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .agent_mind_persistence import PersistentAgentMindStore
from .agent_state_stack import build_agent_state_stack
from .contracts import SpeechImpulse
from .impulse_arbitration import ImpulseArbitrator, build_default_impulse_candidates
from .internal_state import PersistentInternalState


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if numeric != numeric:
        numeric = default
    return max(0.0, min(1.0, numeric))


def _clean(value: Any, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9_\s-]", " ", text)
    words = [word for word in text.split() if len(word) >= 2]
    return "_".join(words[:5])[:80] or "unanchored"


@dataclass(slots=True)
class SpontaneousLifeConfig:
    """Low-gain knobs for internal/situated speech pressure."""

    autonomous_threshold: float = 0.50
    force_speak_threshold: float = 0.30
    default_cooldown_seconds: float = 240.0
    fatigue_block_threshold: float = 0.78


@dataclass(slots=True)
class SpontaneousLifeTrace:
    pressure: float = 0.0
    novelty: float = 0.0
    impulse_type: str = "none"
    family: str = ""
    blocked_reason: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)
    selected_impulse: str = ""
    arbitration_reason: str = ""
    candidate_scores: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "pressure": round(float(self.pressure), 3),
            "novelty": round(float(self.novelty), 3),
            "impulse_type": self.impulse_type,
            "family": self.family,
            "blocked_reason": self.blocked_reason,
            "evidence": list(self.evidence),
            "selected_impulse": self.selected_impulse,
            "arbitration_reason": self.arbitration_reason,
            "candidate_scores": list(self.candidate_scores),
        }


class SpontaneousLifeEngine:
    """Tạo xung giọng nói từ state phân tầng, không viết câu cuối.

    SpeechCore và ActionUtility vẫn có quyền chặn/sửa/chọn im. Module này chỉ nói:
    "nội lực nào đang thắng và vì sao". Một tầng nhỏ, nhưng đỡ hơn để mỗi module
    tự bịa ra lý do riêng như hội đồng phường.
    """

    def __init__(self, *, config: SpontaneousLifeConfig | None = None) -> None:
        self.config = config or SpontaneousLifeConfig()
        self._last_family_at: dict[str, float] = {}
        self.last_trace = SpontaneousLifeTrace()
        self._arbitrator = ImpulseArbitrator()

    def evaluate(
        self,
        *,
        channel: str,
        snapshot=None,
        internal_state: PersistentInternalState | None = None,
        thought_surface=None,
        personality_lens=None,
        relationship_state=None,
        concrete_signals: tuple[str, ...] = (),
        recent_speech_acts: tuple[str, ...] = (),
        agent_mind: PersistentAgentMindStore | None = None,
        now: float | None = None,
    ) -> SpeechImpulse:
        now = time.monotonic() if now is None else float(now)
        channel_name = str(channel or "autonomous").strip().lower() or "autonomous"
        state = internal_state or PersistentInternalState()
        relationship = relationship_state or (getattr(state, "relationship_dynamics", None) if state is not None else None)

        stack = build_agent_state_stack(
            snapshot=snapshot,
            internal_state=state,
            thought_surface=thought_surface,
            personality_lens=personality_lens,
            relationship_state=relationship,
            concrete_signals=tuple(concrete_signals or ()),
            channel=channel_name,
            recent_speech_acts=tuple(recent_speech_acts or ()),
            agent_mind=agent_mind,
        )
        candidates = build_default_impulse_candidates(stack, thought_surface=thought_surface)
        report = self._arbitrator.select(candidates)
        selected = report.selected

        pressure = _clamp01(selected.total)
        novelty = _clamp01(
            max(
                getattr(thought_surface, "novelty", 0.0) if thought_surface is not None else 0.0,
                0.26 + stack.needs.curiosity_need * 0.22 + stack.needs.expression_need * 0.12,
            )
        )
        impulse_type = selected.impulse_type or "inner_whim"
        speech_act = selected.speech_act or "inner_whim"
        topic_seed = _clean(selected.topic_seed or "quiet_whim", limit=100)
        family = selected.family or f"{impulse_type}:{_normalize_key(topic_seed)}"
        cooldown = self._cooldown_for(impulse_type=impulse_type, pressure=pressure)
        cooldown_left = self._cooldown_left(family, now=now, cooldown=cooldown)
        threshold = self.config.force_speak_threshold if channel_name == "force_speak" else self.config.autonomous_threshold

        blocked_reason = ""
        if channel_name not in {"autonomous", "force_speak"}:
            blocked_reason = "channel_not_endogenous"
        elif concrete_signals:
            blocked_reason = "external_signal_has_priority"
        elif speech_act == "no_speech" or selected.name in {"silence_impulse", "body_only_impulse"}:
            blocked_reason = f"{selected.name}_selected"
        elif pressure < threshold:
            blocked_reason = f"below_threshold:{pressure:.2f}/{threshold:.2f}"
        elif stack.needs.rest_need >= self.config.fatigue_block_threshold and channel_name != "force_speak":
            blocked_reason = f"rest_need_high:{stack.needs.rest_need:.2f}"
        elif selected.requires_scene_evidence and not stack.evidence.has_scene_anchor:
            blocked_reason = "scene_impulse_without_scene_evidence"
        elif cooldown_left > 0 and channel_name != "force_speak":
            blocked_reason = f"family_cooldown:{cooldown_left:.0f}s"

        evidence = tuple(
            dict.fromkeys(
                (
                    *selected.evidence,
                    *stack.debug_notes(),
                    *report.evidence_notes(),
                    f"family={family}",
                    f"blocked={blocked_reason}" if blocked_reason else "",
                )
            )
        )
        evidence = tuple(item for item in evidence if item)[:18]

        # Giữ nguyên hồ sơ arbitration để tầng sau đọc được vì sao impulse thắng.
        # Nếu chỉ truyền suggested_speech_act thì ActionUtility chỉ thấy cái nhãn
        # cuối, còn mọi thông tin belief/need/risk/affordance bị nghiền thành bột.
        arbitration_report = report.to_dict()
        impulse_scores = tuple(item.score_note() for item in report.candidates[:8])
        body_bias_hint = self._body_bias_hint(selected_name=selected.name, stack=stack, pressure=pressure)
        agent_state_notes = stack.debug_notes()[:10]
        self.last_trace = SpontaneousLifeTrace(
            pressure=pressure,
            novelty=novelty,
            impulse_type=impulse_type,
            family=family,
            blocked_reason=blocked_reason,
            evidence=evidence,
            selected_impulse=selected.name,
            arbitration_reason=report.reason,
            candidate_scores=tuple(item.score_note() for item in report.candidates[:8]),
        )

        if blocked_reason:
            return SpeechImpulse(
                source="endogenous",
                source_layer="spontaneous_life",
                impulse_type=impulse_type,
                topic_seed=topic_seed,
                family=family,
                surface_pressure=pressure,
                novelty=novelty,
                risk=self._risk_label(selected=selected, speech_act=speech_act),
                needs_external_evidence=False,
                suggested_speech_act="no_speech",
                cooldown_seconds=cooldown,
                reason=blocked_reason,
                reaction="no_reaction",
                surface_intent="stay silent",
                semantic_family=family,
                source_fact=self._source_fact(selected),
                evidence=evidence,
                selected_impulse=selected.name,
                impulse_scores=impulse_scores,
                arbitration_report=arbitration_report,
                agent_state_notes=agent_state_notes,
                body_bias_hint=body_bias_hint,
            )

        self._last_family_at[family] = now
        return SpeechImpulse(
            source="endogenous",
            source_layer="spontaneous_life",
            impulse_type=impulse_type,
            topic_seed=topic_seed,
            family=family,
            surface_pressure=pressure,
            novelty=novelty,
            risk=self._risk_label(selected=selected, speech_act=speech_act),
            needs_external_evidence=False,
            suggested_speech_act=speech_act,
            cooldown_seconds=cooldown,
            reason=selected.reason or report.reason or "impulse arbitration selected a public-safe low-claim impulse",
            meaning=topic_seed,
            reaction=speech_act,
            attitude="low_pressure_situated" if selected.requires_scene_evidence else "low_pressure_internal",
            surface_intent=speech_act,
            mood_residue=impulse_type,
            emotional_pressure=pressure,
            attention_bias=("agent_state_stack", impulse_type),
            reaction_impulse=speech_act,
            semantic_family=family,
            source_fact=self._source_fact(selected),
            evidence=evidence,
            selected_impulse=selected.name,
            impulse_scores=impulse_scores,
            arbitration_report=arbitration_report,
            agent_state_notes=agent_state_notes,
            body_bias_hint=body_bias_hint,
        )

    def _body_bias_hint(self, *, selected_name: str, stack, pressure: float) -> dict[str, object]:
        """Gợi ý body-bias từ impulse thắng.

        Đây chỉ là hint nhẹ, không điều khiển pixel. Body/Action layer vẫn có quyền
        bỏ qua. Mục tiêu là để body biết sự khác nhau giữa:
        - scene_curiosity: nghiêng/quan sát về scene, không hỏi dồn.
        - technical_help: giữ code-side, ít biểu cảm, chuẩn bị giúp.
        - body_only/silence: hiện diện bằng chuyển động nhỏ hoặc đứng yên.
        Không có hint này thì thân thể ERIS lại mù motive, rồi ta có một con búp bê
        đi lang thang trong khi não bảo đang debug. Tuyệt phẩm kỹ thuật, hẳn rồi.
        """
        ev = getattr(stack, "evidence", None)
        needs = getattr(stack, "needs", None)
        focus_kind = str(getattr(ev, "focus_kind", "unknown") or "unknown")
        pressure_value = round(_clamp01(pressure), 3)
        hint: dict[str, object] = {
            "source": "impulse_arbitration",
            "selected_impulse": str(selected_name or ""),
            "pressure": pressure_value,
            "focus_kind": focus_kind,
        }
        if selected_name == "scene_curiosity_impulse":
            hint.update({
                "preferred_anchor": "code_side" if focus_kind in {"code", "coding", "ide"} else "chat_near",
                "body_action_bias": "quiet_observe_scene",
                "curiosity_delta": min(0.18, 0.06 + pressure_value * 0.10),
                "speech_shape": "one_short_grounded_observation",
            })
        elif selected_name == "technical_help_impulse":
            hint.update({
                "preferred_anchor": "code_side",
                "body_action_bias": "hold_focus",
                "curiosity_delta": 0.08,
                "overload_delta": min(0.10, _clamp01(getattr(needs, "competence_need", 0.0)) * 0.08),
                "speech_shape": "practical_help_if_allowed",
            })
        elif selected_name == "body_only_impulse":
            hint.update({
                "preferred_anchor": "chat_near",
                "body_action_bias": "quiet_adjustment_only",
                "speech_shape": "no_bubble",
            })
        elif selected_name == "silence_impulse":
            hint.update({
                "preferred_anchor": "bottom_right" if _clamp01(getattr(needs, "rest_need", 0.0)) >= 0.55 else "chat_near",
                "body_action_bias": "intentional_stillness",
                "speech_shape": "silence",
            })
        else:
            hint.update({
                "preferred_anchor": "chat_near",
                "body_action_bias": "low_pressure_presence",
                "speech_shape": "short_internal_fragment",
            })
        return hint

    def _risk_label(self, *, selected, speech_act: str) -> str:
        if speech_act in {"micro_presence", "companionship_ping"}:
            return "micro_presence"
        if bool(getattr(selected, "requires_scene_evidence", False)):
            return "grounded_scene"
        return "texture"

    def _source_fact(self, selected) -> str:
        if bool(getattr(selected, "requires_scene_evidence", False)):
            return "agent_state_stack/scene_evidence"
        return "agent_state_stack/internal_state"

    def _cooldown_for(self, *, impulse_type: str, pressure: float) -> float:
        base = {
            "companionship_ping": 300.0,
            "micro_story": 260.0,
            "random_chatter": 220.0,
            "scene_curiosity": 210.0,
            "technical_help": 180.0,
            "inner_whim": 200.0,
            "body_only": 120.0,
            "silence": 45.0,
        }.get(impulse_type, self.config.default_cooldown_seconds)
        if pressure >= 0.72:
            base *= 0.72
        return max(45.0, base)

    def _cooldown_left(self, family: str, *, now: float, cooldown: float) -> float:
        last = float(self._last_family_at.get(family, 0.0) or 0.0)
        if last <= 0.0:
            return 0.0
        elapsed = max(0.0, now - last)
        return max(0.0, cooldown - elapsed)
