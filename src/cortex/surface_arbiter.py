# -*- coding: utf-8 -*-
"""Single source of truth for low-level surface utterances.

SurfaceArbiter gom các lực rất nhỏ: micro presence, re-engagement, spontaneous
inner whim, idle curiosity và thought-stream surface. Nó chọn *có nên surface*
và *dùng mode sinh nào*. Nó không hardcode câu thoại. Cái thời mỗi module tự có
một hũ câu mẫu riêng nên được chôn cạnh các file backup tên final_final2.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any, Callable, Mapping

from .contracts import SpeechImpulse
from .low_level_speech_policy import LowLevelSpeechPolicy, _clamp01


@dataclass(slots=True)
class SurfaceImpulse:
    kind: str
    source: str
    confidence: float = 0.0
    pressure: float = 0.0
    score: float = 0.0
    topic_seed: str = ""
    speech_act: str = ""
    family: str = ""
    evidence: tuple[str, ...] = ()
    reason: str = ""
    focus_family: str = "general_idle"
    body_action: str = "idle_shift"
    missing_evidence_ids: bool = False
    is_presence: bool = False
    should_surface: bool = False
    needs_external_evidence: bool = False
    vital_pressure: float = 0.0
    is_vital_pressure: bool = False
    raw: Any = None

    def to_context(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source": self.source,
            "confidence": round(float(self.confidence), 3),
            "pressure": round(float(self.pressure), 3),
            "score": round(float(self.score), 3),
            "topic_seed": self.topic_seed,
            "speech_act": self.speech_act,
            "family": self.family,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "focus_family": self.focus_family,
            "body_action": self.body_action,
            "missing_evidence_ids": bool(self.missing_evidence_ids),
            "is_presence": bool(self.is_presence),
            "should_surface": bool(self.should_surface),
            "needs_external_evidence": bool(self.needs_external_evidence),
            "vital_pressure": round(float(self.vital_pressure), 3),
            "is_vital_pressure": bool(self.is_vital_pressure),
        }


@dataclass(slots=True)
class SurfaceDecision:
    text: str = ""
    body_only: bool = False
    should_speak: bool = False
    parse_mode: str = "surface_body_only"
    intent: str = "surface"
    source: str = "surface_arbiter"
    generation_mode: str = "reject"
    confidence: float = 0.0
    kind: str = ""
    body_action: str = "idle_shift"
    focus_family: str = "general_idle"
    reason: str = ""
    debug_trace: str = ""
    impulse: SurfaceImpulse | None = None
    suppressed: tuple[SurfaceImpulse, ...] = field(default_factory=tuple)

    def to_context(self) -> dict[str, object]:
        return {
            "text": self.text,
            "body_only": bool(self.body_only),
            "should_speak": bool(self.should_speak),
            "parse_mode": self.parse_mode,
            "intent": self.intent,
            "source": self.source,
            "generation_mode": self.generation_mode,
            "confidence": round(float(self.confidence), 3),
            "kind": self.kind,
            "body_action": self.body_action,
            "focus_family": self.focus_family,
            "reason": self.reason,
            "debug_trace": self.debug_trace,
            "impulse": self.impulse.to_context() if self.impulse else None,
            "suppressed": [item.to_context() for item in self.suppressed[:6]],
        }


class SurfaceArbiter:
    """Arbitrate and generate low-level utterances.

    llm_micro_gen có thể là callable:
        fn(impulse=SurfaceImpulse, snapshot=snapshot, force_llm=True) -> (text, trace)
    hoặc object có method generate_micro(...). Nhẹ nhàng, ít tôn giáo framework.
    """

    def __init__(
        self,
        policy: LowLevelSpeechPolicy | None = None,
        llm_micro_gen: Any = None,
        thought_stream: Any = None,
    ) -> None:
        self.policy = policy or LowLevelSpeechPolicy()
        self.llm_generator = llm_micro_gen
        self.thought_stream = thought_stream
        self.silent_cycles = 0
        self.last_surface_time = 0.0
        self.last_decision = SurfaceDecision(reason="not_started")
        self._last_family_at: dict[str, float] = {}
        self._body_only_streak = 0


    # Các nhóm này là chính sách phân xử, không phải văn mẫu.
    # Mục tiêu: tách "giữ nhịp hiện diện" khỏi "quyền tranh slot phát ngôn".
    # Nếu không tách, micro_presence sẽ cứ thắng vì silence_debt rồi lại câm vì thiếu evidence.
    # Đó là priority inversion: thắng bầu cử nhưng không có hộ chiếu để qua cửa thực thi.
    _PRESENCE_LIKE_KINDS = frozenset({
        "presence_maintenance",
        "micro_presence",
        "companionship_ping",
        "re_engagement",
        "idle_curiosity",
    })
    _SCREEN_ANCHORED_KINDS = frozenset({
        "micro_observation",
        "vision_comment",
        "screen_observation",
        "telemetry_comment",
    })
    _ENDOGENOUS_NO_ANCHOR_KINDS = frozenset({
        "inner_whim",
        "random_chatter",
        "thought_stream_surface",
        "idle_curiosity_inner",
        "curious_question",
        "memory_resonance",
        "light_muse",
    })

    def arbitrate(
        self,
        *,
        snapshot: Any = None,
        cognitive_frame: Any = None,
        presence_cue: Any = None,
        extra_impulses: tuple[Any, ...] = (),
        surface_kind: str = "surface",
        force_llm: bool = False,
        silent_cycles: int | None = None,
    ) -> SurfaceDecision:
        if silent_cycles is not None:
            self.silent_cycles = max(0, int(silent_cycles or 0))

        impulses = self._collect_all_impulses(
            snapshot=snapshot,
            frame=cognitive_frame,
            presence_cue=presence_cue,
            extra_impulses=extra_impulses,
            surface_kind=surface_kind,
        )
        winner, suppressed = self._score_and_select_winner(impulses)
        if winner is None:
            self.silent_cycles += 1
            decision = SurfaceDecision(
                body_only=False,
                should_speak=False,
                parse_mode="surface_reject",
                intent=surface_kind,
                source="surface_arbiter",
                generation_mode="reject",
                reason="no_winner_impulse",
                debug_trace="surface_arbiter; reason=no_winner_impulse",
            )
            self.last_decision = decision
            return decision

        forced_body_only_reason = self._forced_body_only_reason(winner)
        if forced_body_only_reason:
            # Micro/presence thiếu anchor không được gọi LLM để rồi trả rỗng.
            # Nó chỉ được giữ thân thể/nhịp, còn slot lời nói phải nhường cho impulse nội sinh nếu có.
            self._mark_attempt(winner, result=forced_body_only_reason, body_only=True)
            self._note_non_speech(body_only=True)
            decision = SurfaceDecision(
                body_only=True,
                should_speak=False,
                parse_mode=f"{winner.kind or surface_kind}_body_only",
                intent=winner.kind or surface_kind,
                source="surface_arbiter_body_only",
                generation_mode="forced_body_only",
                confidence=winner.confidence,
                kind=winner.kind,
                body_action=winner.body_action,
                focus_family=winner.focus_family,
                reason=forced_body_only_reason,
                debug_trace=self._trace(winner, suppressed, "forced_body_only", forced_body_only_reason),
                impulse=winner,
                suppressed=suppressed,
            )
            self.last_decision = decision
            return decision

        ego_gate_reason = self._ego_gate_reason(winner, snapshot=snapshot, frame=cognitive_frame, force_llm=force_llm)
        if ego_gate_reason:
            self._mark_attempt(winner, result="ego_reject", body_only=False)
            self._note_non_speech(body_only=False)
            decision = SurfaceDecision(
                body_only=False,
                should_speak=False,
                parse_mode="surface_ego_reject",
                intent=surface_kind,
                source="surface_arbiter",
                generation_mode="reject",
                confidence=winner.confidence,
                kind=winner.kind,
                body_action=winner.body_action,
                focus_family=winner.focus_family,
                reason=ego_gate_reason,
                debug_trace=self._trace(winner, suppressed, "reject", ego_gate_reason),
                impulse=winner,
                suppressed=suppressed,
            )
            self.last_decision = decision
            return decision

        rate_limit_reason = self._rate_limit_reason(winner, force_llm=force_llm)
        if rate_limit_reason:
            self._mark_attempt(winner, result="rate_limited", body_only=False)
            self._note_non_speech(body_only=False)
            decision = SurfaceDecision(
                body_only=False,
                should_speak=False,
                parse_mode="surface_rate_limited",
                intent=surface_kind,
                source="surface_arbiter",
                generation_mode="reject",
                confidence=winner.confidence,
                kind=winner.kind,
                body_action=winner.body_action,
                focus_family=winner.focus_family,
                reason=rate_limit_reason,
                debug_trace=self._trace(winner, suppressed, "reject", rate_limit_reason),
                impulse=winner,
                suppressed=suppressed,
            )
            self.last_decision = decision
            return decision

        mode = "force_llm" if force_llm else self.policy.decide_generation_mode(winner, self.silent_cycles)
        if mode == "reject":
            # Defensive override: micro/re-engagement đã đủ điểm hoặc im quá lâu thì không được
            # rơi về reject/body-only. Policy là cổng điều tiết, không phải máy nghiền ý định nói.
            kind = str(getattr(winner, "kind", "") or "").strip()
            always_llm = set(getattr(self.policy.config, "always_llm_kinds", ()) or ())
            vital = _clamp01(getattr(winner, "vital_pressure", 0.0))
            if (
                self.silent_cycles >= self.policy.config.force_llm_after_silent
                or (kind in always_llm and winner.confidence >= self.policy.config.min_surface_confidence)
                or (vital >= getattr(self.policy.config, "vital_pressure_force_llm_threshold", 0.62) and winner.confidence >= self.policy.config.body_only_min_confidence)
            ):
                mode = "force_llm"
        if mode == "reject":
            self._mark_attempt(winner, result="policy_reject", body_only=False)
            self._note_non_speech(body_only=False)
            decision = SurfaceDecision(
                body_only=False,
                should_speak=False,
                parse_mode="surface_reject",
                intent=surface_kind,
                source="surface_arbiter",
                generation_mode=mode,
                confidence=winner.confidence,
                kind=winner.kind,
                body_action=winner.body_action,
                focus_family=winner.focus_family,
                reason="policy_reject",
                debug_trace=self._trace(winner, suppressed, mode, "policy_reject"),
                impulse=winner,
                suppressed=suppressed,
            )
            self.last_decision = decision
            return decision

        if mode in {"force_llm", "normal_llm"}:
            text, trace = self._call_llm_generator(winner, snapshot=snapshot, force_llm=(mode == "force_llm" or force_llm))
            if str(text or "").strip():
                debug_trace = self._trace(winner, suppressed, mode, str(trace or "llm_ok"))
                self._reset_silence()
                self._mark_surface(winner)
                parse_mode = "presence_maintenance" if winner.is_presence else "spontaneous"
                if winner.kind in {"re_engagement", "micro_observation"}:
                    parse_mode = winner.kind
                decision = SurfaceDecision(
                    text=str(text).strip(),
                    body_only=False,
                    should_speak=True,
                    parse_mode=parse_mode,
                    intent=winner.kind or surface_kind,
                    source="surface_arbiter_llm",
                    generation_mode=mode,
                    confidence=winner.confidence,
                    kind=winner.kind,
                    body_action=winner.body_action,
                    focus_family=winner.focus_family,
                    reason=winner.reason,
                    debug_trace=debug_trace,
                    impulse=winner,
                    suppressed=suppressed,
                )
                self.last_decision = decision
                return decision

            self._mark_attempt(winner, result="llm_decline", body_only=True)
            self._note_non_speech(body_only=True)
            if not self.policy.config.body_only_after_llm_decline:
                decision = SurfaceDecision(
                    body_only=False,
                    should_speak=False,
                    parse_mode="surface_reject",
                    intent=winner.kind or surface_kind,
                    source="surface_arbiter",
                    generation_mode=mode,
                    confidence=winner.confidence,
                    kind=winner.kind,
                    body_action=winner.body_action,
                    focus_family=winner.focus_family,
                    reason="llm_declined",
                    debug_trace=self._trace(winner, suppressed, mode, str(trace or "llm_declined")),
                    impulse=winner,
                    suppressed=suppressed,
                )
                self.last_decision = decision
                return decision

            decision = SurfaceDecision(
                body_only=True,
                should_speak=False,
                parse_mode=f"{winner.kind or surface_kind}_body_only",
                intent=winner.kind or surface_kind,
                source="surface_arbiter_body_only",
                generation_mode=mode,
                confidence=winner.confidence,
                kind=winner.kind,
                body_action=winner.body_action,
                focus_family=winner.focus_family,
                reason="llm_declined",
                debug_trace=self._trace(winner, suppressed, mode, str(trace or "llm_declined")),
                impulse=winner,
                suppressed=suppressed,
            )
            self.last_decision = decision
            return decision

        self._mark_attempt(winner, result="body_only_by_policy", body_only=True)
        self._note_non_speech(body_only=True)
        decision = SurfaceDecision(
            body_only=True,
            should_speak=False,
            parse_mode=f"{winner.kind or surface_kind}_body_only",
            intent=winner.kind or surface_kind,
            source="surface_arbiter_body_only",
            generation_mode=mode,
            confidence=winner.confidence,
            kind=winner.kind,
            body_action=winner.body_action,
            focus_family=winner.focus_family,
            reason="body_only_by_policy",
            debug_trace=self._trace(winner, suppressed, mode, "body_only_by_policy"),
            impulse=winner,
            suppressed=suppressed,
        )
        self.last_decision = decision
        return decision

    def _collect_all_impulses(
        self,
        *,
        snapshot: Any,
        frame: Any,
        presence_cue: Any,
        extra_impulses: tuple[Any, ...],
        surface_kind: str,
    ) -> tuple[SurfaceImpulse, ...]:
        impulses: list[SurfaceImpulse] = []
        cue_impulse = self._from_presence_cue(presence_cue, surface_kind=surface_kind)
        if cue_impulse is not None:
            impulses.append(cue_impulse)

        speech_core = getattr(frame, "speech_core", None) if frame is not None else None
        if speech_core is not None:
            spontaneous = getattr(speech_core, "speech_impulse", None)
            spontaneous_impulse = self._from_speech_impulse(spontaneous)
            if spontaneous_impulse is not None:
                impulses.append(spontaneous_impulse)

        for owner in (frame, snapshot):
            if owner is None:
                continue
            for attr in ("surface_impulses", "low_level_impulses", "speech_impulses"):
                for raw_impulse in tuple(getattr(owner, attr, ()) or ()): 
                    converted = self._coerce_impulse(raw_impulse, surface_kind=surface_kind)
                    if converted is not None:
                        impulses.append(converted)

        if self.thought_stream is not None:
            getter = getattr(self.thought_stream, "get_surface_candidates", None)
            if callable(getter):
                try:
                    for raw_impulse in tuple(getter() or ()): 
                        converted = self._coerce_impulse(raw_impulse, surface_kind=surface_kind)
                        if converted is not None:
                            impulses.append(converted)
                except Exception:
                    pass

        thought_impulse = self._from_thought_surface(frame=frame, snapshot=snapshot)
        if thought_impulse is not None:
            impulses.append(thought_impulse)

        long_silence = self._long_silence_impulse(snapshot=snapshot, surface_kind=surface_kind)
        if long_silence is not None:
            impulses.append(long_silence)

        for item in extra_impulses or ():
            converted = self._coerce_impulse(item, surface_kind=surface_kind)
            if converted is not None:
                impulses.append(converted)

        # Dedup theo source/kind/family để một cue không tự nhân bản như spam mail nội tâm.
        unique: dict[tuple[str, str, str], SurfaceImpulse] = {}
        for item in impulses:
            key = (item.source, item.kind, item.family or item.topic_seed[:48])
            old = unique.get(key)
            if old is None or item.score > old.score:
                unique[key] = item
        return tuple(unique.values())

    def _from_presence_cue(self, cue: Any, *, surface_kind: str) -> SurfaceImpulse | None:
        if cue is None:
            return None
        needs = bool(getattr(cue, "needs_micro_presence", False))
        confidence = _clamp01(getattr(cue, "confidence", 0.0), 0.0)
        curiosity = _clamp01(getattr(cue, "curiosity", 0.0), 0.0)
        evidence = tuple(str(item) for item in (getattr(cue, "evidence", ()) or ()) if str(item).strip())[:10]
        focus_family = str(getattr(cue, "focus_family", "general_idle") or "general_idle")
        reason = str(getattr(cue, "reason", "") or surface_kind or "micro_presence")
        kind = surface_kind or reason or "presence_maintenance"
        if reason in {"re_engagement", "long_silence_reengagement"} or kind == "re_engagement":
            kind = "re_engagement"
        score = max(confidence, curiosity * 0.72)
        if self.silent_cycles >= 2:
            score = max(score, 0.48)
        return SurfaceImpulse(
            kind=kind,
            source="presence_controller",
            confidence=max(confidence, score),
            pressure=max(confidence, curiosity),
            score=score,
            topic_seed="; ".join(evidence[:3]),
            speech_act="micro_presence" if kind == "presence_maintenance" else kind,
            family=f"{kind}:{focus_family}",
            evidence=evidence,
            reason=reason,
            focus_family=focus_family,
            body_action=str(getattr(cue, "body_action", "idle_shift") or "idle_shift"),
            missing_evidence_ids=bool(getattr(cue, "missing_evidence_ids", False)),
            is_presence=True,
            should_surface=needs,
            needs_external_evidence=False,
            raw=cue,
        )

    def _from_speech_impulse(self, impulse: SpeechImpulse | None) -> SurfaceImpulse | None:
        if impulse is None or not bool(getattr(impulse, "active", False)):
            return None
        act = str(getattr(impulse, "suggested_speech_act", "") or getattr(impulse, "reaction", "") or "").strip()
        if not act or act == "no_speech":
            return None
        pressure = _clamp01(getattr(impulse, "surface_pressure", 0.0), _clamp01(getattr(impulse, "emotional_pressure", 0.0)))
        vital_pressure = _clamp01(getattr(impulse, "vital_pressure", 0.0))
        pressure = max(pressure, vital_pressure * 0.82)
        evidence = tuple(str(item) for item in (getattr(impulse, "evidence", ()) or ()) if str(item).strip())[:10]
        body_hint = getattr(impulse, "body_bias_hint", {}) or {}
        body_action = str(body_hint.get("body_action_bias", "low_pressure_presence") or "low_pressure_presence")
        return SurfaceImpulse(
            kind=act,
            source=str(getattr(impulse, "source_layer", "") or getattr(impulse, "source", "") or "spontaneous_life"),
            confidence=pressure,
            pressure=pressure,
            score=pressure,
            topic_seed=str(getattr(impulse, "topic_seed", "") or getattr(impulse, "meaning", "") or "quiet_whim")[:120],
            speech_act=act,
            family=str(getattr(impulse, "family", "") or getattr(impulse, "semantic_family", "") or act),
            evidence=evidence,
            reason=str(getattr(impulse, "reason", "") or "spontaneous low-level impulse"),
            focus_family="spontaneous",
            body_action=body_action,
            missing_evidence_ids=not any("scene_evidence" in item or "ev." in item for item in evidence),
            is_presence=act in {"micro_presence", "companionship_ping"},
            should_surface=pressure > 0.0 and not bool(getattr(impulse, "needs_external_evidence", False)),
            needs_external_evidence=bool(getattr(impulse, "needs_external_evidence", False)),
            vital_pressure=vital_pressure,
            is_vital_pressure=bool(getattr(impulse, "is_vital_pressure", False)) or vital_pressure >= 0.55,
            raw=impulse,
        )

    def _from_thought_surface(self, *, frame: Any, snapshot: Any) -> SurfaceImpulse | None:
        candidates = []
        for owner in (frame, self.thought_stream):
            if owner is None:
                continue
            for name in ("thought_stream_report", "thought_surface", "subconscious_report", "subconscious_seed"):
                value = getattr(owner, name, None)
                if value is not None:
                    candidates.append(value)
        for item in candidates:
            if isinstance(item, Mapping):
                topic = self._first_text(
                    item.get("topic_seed", ""),
                    item.get("partial_text", ""),
                    item.get("unfinished_impulse", ""),
                    item.get("almost_spoke", ""),
                )
                pressure = max(
                    _clamp01(item.get("pressure", 0.0)),
                    _clamp01(item.get("momentum_score", 0.0)),
                    _clamp01(item.get("novelty", 0.0)) * 0.7,
                )
            else:
                topic = self._first_text(
                    getattr(item, "topic_seed", ""),
                    getattr(item, "partial_text", ""),
                    getattr(item, "unfinished_impulse", ""),
                    getattr(item, "almost_spoke", ""),
                )
                pressure = max(
                    _clamp01(getattr(item, "pressure", 0.0)),
                    _clamp01(getattr(item, "momentum_score", 0.0)),
                    _clamp01(getattr(item, "novelty", 0.0)) * 0.7,
                )
            if topic and pressure >= 0.25:
                return SurfaceImpulse(
                    kind="thought_stream_surface",
                    source="thought_stream",
                    confidence=max(0.34, pressure),
                    pressure=pressure,
                    score=pressure,
                    topic_seed=topic[:120],
                    speech_act="inner_whim",
                    family="thought_stream:" + self._family_key(topic),
                    evidence=(topic[:120],),
                    reason="thought stream has a small public-safe residue",
                    focus_family="thought_stream",
                    body_action="low_pressure_presence",
                    missing_evidence_ids=True,
                    is_presence=False,
                    should_surface=True,
                    raw=item,
                )
        return None

    def _long_silence_impulse(self, *, snapshot: Any, surface_kind: str) -> SurfaceImpulse | None:
        idle = 0.0
        try:
            idle = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        except Exception:
            idle = 0.0
        if idle < 120.0 and self.silent_cycles < 3:
            return None
        confidence = max(0.40, min(0.62, 0.36 + self.silent_cycles * 0.06 + min(0.18, idle / 1800.0)))
        return SurfaceImpulse(
            kind="idle_curiosity" if surface_kind == "surface" else surface_kind,
            source="surface_arbiter",
            confidence=confidence,
            pressure=confidence,
            score=confidence - 0.02,
            topic_seed=f"idle_seconds={idle:.1f}",
            speech_act="micro_presence",
            family="long_silence:idle",
            evidence=(f"idle_seconds={idle:.1f}", f"silent_cycles={self.silent_cycles}"),
            reason="long_silence_impulse",
            focus_family="general_idle",
            body_action="idle_shift",
            missing_evidence_ids=True,
            is_presence=True,
            should_surface=True,
        )

    def _coerce_impulse(self, item: Any, *, surface_kind: str) -> SurfaceImpulse | None:
        if isinstance(item, SurfaceImpulse):
            return item
        if isinstance(item, SpeechImpulse):
            return self._from_speech_impulse(item)
        if item is None:
            return None
        if isinstance(item, Mapping):
            get = item.get
        else:
            get = lambda name, default=None: getattr(item, name, default)
        kind = str(get("kind", "") or get("impulse_type", "") or surface_kind or "surface")
        confidence = _clamp01(get("confidence", 0.0), _clamp01(get("surface_pressure", 0.0)))
        if confidence <= 0.0:
            return None
        evidence = tuple(str(value) for value in (get("evidence", ()) or ()) if str(value).strip())[:10]
        pressure = max(confidence, _clamp01(get("pressure", 0.0), confidence))
        score = max(pressure, _clamp01(get("score", 0.0), pressure))
        return SurfaceImpulse(
            kind=kind,
            source=str(get("source", "external") or "external"),
            confidence=confidence,
            pressure=pressure,
            score=score,
            topic_seed=str(get("topic_seed", "") or get("meaning", "") or "")[:120],
            speech_act=str(get("speech_act", "") or get("suggested_speech_act", "") or kind),
            family=str(get("family", "") or get("semantic_family", "") or kind),
            evidence=evidence,
            reason=str(get("reason", "") or "extra surface impulse"),
            focus_family=str(get("focus_family", "") or "surface"),
            body_action=str(get("body_action", "") or "low_pressure_presence"),
            missing_evidence_ids=bool(get("missing_evidence_ids", False)),
            is_presence=bool(get("is_presence", kind in {"presence_maintenance", "micro_presence", "re_engagement"})),
            should_surface=bool(get("should_surface", True)),
            needs_external_evidence=bool(get("needs_external_evidence", False)),
            vital_pressure=_clamp01(get("vital_pressure", 0.0)),
            is_vital_pressure=bool(get("is_vital_pressure", False)) or _clamp01(get("vital_pressure", 0.0)) >= 0.55,
            raw=item,
        )

    def _score_and_select_winner(self, impulses: tuple[SurfaceImpulse, ...]) -> tuple[SurfaceImpulse | None, tuple[SurfaceImpulse, ...]]:
        """Chọn winner theo hai hàng đợi: speakable trước, body-only sau.

        Luật dài hạn:
        - Presence/micro-presence thiếu evidence hiện tại vẫn được giữ body rhythm,
          nhưng không được tranh slot public speech.
        - Inner_whim/random_chatter/thought_stream_surface là impulse nội sinh thấp-claim,
          nên được phép thắng khi silence kéo dài mà không cần screen anchor.
        - vital_pressure không còn là cộng nhẹ tuyến tính. Khi bị nén lâu, nó tăng theo
          multiplier phi tuyến có trần, đủ để phá starvation nhưng không biến thành spam.
        """
        speakable: list[tuple[float, SurfaceImpulse]] = []
        body_only: list[tuple[float, SurfaceImpulse]] = []

        for item in impulses:
            if not item.should_surface:
                continue
            effective = self._effective_score(item)
            forced_reason = self._forced_body_only_reason(item)
            if forced_reason:
                body_only.append((effective, item))
                continue
            if item.needs_external_evidence:
                # Cần evidence ngoài nhưng không có forced-body-only reason rõ ràng thì loại hẳn.
                # Không để LLM tự tưởng tượng một cái neo màn hình. Máy đã đủ sáng tạo trong việc tự phá rồi.
                continue
            speakable.append((effective, item))

        if speakable:
            ordered_pairs = tuple(sorted(
                speakable,
                key=lambda pair: (pair[0], self._priority(pair[1].kind, pair[1].source)),
                reverse=True,
            ))
            suppressed_pairs = tuple(sorted(
                (*ordered_pairs[1:], *body_only),
                key=lambda pair: (pair[0], self._priority(pair[1].kind, pair[1].source)),
                reverse=True,
            ))
            return ordered_pairs[0][1], tuple(item for _, item in suppressed_pairs)

        if body_only:
            # Không có impulse nói được thì trả body-only thay vì gọi LLM vào khoảng trắng.
            ordered_pairs = tuple(sorted(
                body_only,
                key=lambda pair: (pair[0], self._priority(pair[1].kind, pair[1].source)),
                reverse=True,
            ))
            return ordered_pairs[0][1], tuple(item for _, item in ordered_pairs[1:])

        return None, ()

    def _presence_like(self, impulse: SurfaceImpulse) -> bool:
        kind = str(impulse.kind or impulse.speech_act or "")
        return bool(impulse.is_presence or kind in self._PRESENCE_LIKE_KINDS)

    def _endogenous_no_anchor_like(self, impulse: SurfaceImpulse) -> bool:
        kind = str(impulse.kind or impulse.speech_act or "")
        source = str(impulse.source or "")
        return bool(
            kind in self._ENDOGENOUS_NO_ANCHOR_KINDS
            or source in {"thought_stream", "endogenous_drive", "spontaneous_life", "inner_thought"}
            or bool(getattr(impulse, "is_vital_pressure", False))
        )

    def _has_concrete_evidence_anchor(self, impulse: SurfaceImpulse) -> bool:
        text = " ".join(str(item) for item in (impulse.evidence or ())).lower()
        if not text.strip():
            return False
        concrete_markers = (
            "scene_evidence", "vision_fact", "ev.active_window", "ev.active_app",
            "ev.ocr", "screen_fact", "user_chat", "runtime_event",
        )
        return any(marker in text for marker in concrete_markers)

    def _forced_body_only_reason(self, impulse: SurfaceImpulse) -> str:
        """Trả reason nếu impulse chỉ được body-only, không được tranh slot nói.

        Đây là chốt chống priority inversion: micro_presence thiếu anchor không còn
        được thắng rồi bắt LLM viết câu rỗng. Nó lui về body-only, nhường lời cho
        inner_whim/random_chatter nếu các impulse đó đủ áp lực.
        """
        if not impulse.should_surface:
            return ""
        kind = str(impulse.kind or impulse.speech_act or "")
        if kind in self._SCREEN_ANCHORED_KINDS:
            return ""
        if impulse.needs_external_evidence and impulse.missing_evidence_ids:
            return "forced_body_only:needs_external_evidence_missing"
        if self._presence_like(impulse) and impulse.missing_evidence_ids and not self._has_concrete_evidence_anchor(impulse):
            return "forced_body_only:presence_missing_evidence"
        return ""

    def _effective_score(self, impulse: SurfaceImpulse) -> float:
        base = self._clamp_score(getattr(impulse, "score", 0.0))
        vital = _clamp01(getattr(impulse, "vital_pressure", 0.0))
        effective = base

        if self._endogenous_no_anchor_like(impulse):
            # Phi tuyến có trần: im càng lâu thì nội sinh càng có quyền phá bĩnh,
            # nhưng không vượt khỏi vùng low-claim. Đây là starvation prevention,
            # không phải giấy phép nói lảm nhảm như NPC hết thoại.
            over = max(0, int(self.silent_cycles) - 3)
            multiplier = min(2.10, 1.0 + (over ** 1.35) * 0.075)
            effective += vital * 0.24 * multiplier
            effective += min(0.22, over * 0.028)
            if impulse.missing_evidence_ids:
                # Nội sinh được thiếu screen anchor, miễn là không claim screen.
                effective += 0.04

        if self._presence_like(impulse) and impulse.missing_evidence_ids and not self._has_concrete_evidence_anchor(impulse):
            # Không giết presence; chỉ hạ nó khỏi cuộc tranh lời nói.
            # Nếu không có candidate nào khác, nó vẫn có thể trả body-only.
            effective -= 0.34 + min(0.22, max(0, int(self.silent_cycles) - 2) * 0.025)

        return self._clamp_score(effective)

    @staticmethod
    def _clamp_score(value: Any) -> float:
        try:
            number = float(value)
        except Exception:
            number = 0.0
        if number != number:
            number = 0.0
        return max(-1.0, min(2.0, number))

    def _candidate_notes(self, impulse: SurfaceImpulse) -> str:
        notes: list[str] = []
        forced = self._forced_body_only_reason(impulse)
        if forced:
            notes.append(forced)
        if self._endogenous_no_anchor_like(impulse):
            vital = _clamp01(getattr(impulse, "vital_pressure", 0.0))
            over = max(0, int(self.silent_cycles) - 3)
            if vital > 0 or over > 0:
                multiplier = min(2.10, 1.0 + (over ** 1.35) * 0.075)
                notes.append(f"endogenous_boost:vital={vital:.2f}x{multiplier:.2f}")
        if self._presence_like(impulse) and impulse.missing_evidence_ids and not self._has_concrete_evidence_anchor(impulse):
            notes.append("presence_penalty:missing_anchor")
        return ",".join(notes)

    def _signed_float(self, value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except Exception:
            number = default
        if number != number:
            number = default
        return max(-1.0, min(1.0, number))

    def _runtime_internal_state(self, *, frame: Any = None, snapshot: Any = None) -> Any:
        for owner in (frame, snapshot):
            if owner is None:
                continue
            for attr in ("internal_state_after", "internal_state_before", "internal_state", "state"):
                value = getattr(owner, attr, None)
                if value is not None:
                    return value
        return None

    def _ego_gate_reason(self, impulse: SurfaceImpulse, *, snapshot: Any = None, frame: Any = None, force_llm: bool = False) -> str:
        """Ego-gate for low-level surface.

        Đây không phải filter câu chữ. Nó chặn ngay quyền surface khi impulse mâu
        thuẫn với mood/relationship distance. Presence maintenance là thứ chịu
        phạt mạnh nhất; inner_whim vẫn có cửa nếu có thought/cognitive pressure.
        """
        if force_llm:
            return ""
        kind = str(impulse.kind or impulse.speech_act or "")
        presence_like = bool(impulse.is_presence or kind in {"presence_maintenance", "micro_presence", "companionship_ping", "re_engagement"})
        if not presence_like:
            return ""
        state = self._runtime_internal_state(frame=frame, snapshot=snapshot)
        rel = getattr(state, "relationship_dynamics", None) if state is not None else None
        valence = self._signed_float(getattr(state, "valence", 0.02) if state is not None else 0.02, 0.02)
        social_energy = _clamp01(getattr(state, "social_energy", 0.38) if state is not None else 0.38, 0.38)
        irritation = _clamp01(getattr(state, "irritation", 0.0) if state is not None else 0.0)
        rupture = _clamp01(getattr(rel, "rupture", 0.0) if rel is not None else 0.0)
        dignity = _clamp01(getattr(rel, "dignity_defense", 0.0) if rel is not None else 0.0)
        preferred_distance = _clamp01(getattr(rel, "preferred_distance", 0.58) if rel is not None else 0.58, 0.58)
        trust = _clamp01(getattr(rel, "trust", 0.25) if rel is not None else 0.25, 0.25)

        if valence <= -0.18 or irritation >= 0.55:
            return "ego_gate:mood_blocks_presence"
        if social_energy <= 0.16:
            return "ego_gate:social_energy_empty"
        if rupture >= 0.42 or dignity >= 0.42:
            return "ego_gate:dignity_distance"
        if preferred_distance >= 0.74 and trust <= 0.34:
            return "ego_gate:preferred_distance_high"
        if kind == "presence_maintenance" and impulse.missing_evidence_ids and impulse.score < 0.72 and _clamp01(getattr(impulse, "vital_pressure", 0.0)) < 0.58:
            return "ego_gate:ambient_copresence_no_anchor"
        return ""

    def _rate_limit_reason(self, impulse: SurfaceImpulse, *, force_llm: bool) -> str:
        if force_llm:
            return ""
        now = time.time()
        min_interval = float(getattr(self.policy.config, "min_surface_interval_seconds", 0.0) or 0.0)
        vital = _clamp01(getattr(impulse, "vital_pressure", 0.0))
        if self.last_surface_time > 0 and min_interval > 0 and now - self.last_surface_time < min_interval:
            # Không rate-limit long-silence/vital force path; còn lại thì chặn để tránh lải nhải.
            if self.silent_cycles < self.policy.config.force_llm_after_silent and vital < 0.66:
                return f"surface_interval_cooldown:{now - self.last_surface_time:.1f}/{min_interval:.1f}s"
        family_cooldown = float(getattr(self.policy.config, "family_cooldown_seconds", 0.0) or 0.0)
        family = self._family_id(impulse)
        last_family = float(self._last_family_at.get(family, 0.0) or 0.0)
        if family and last_family > 0 and family_cooldown > 0 and now - last_family < family_cooldown:
            if self.silent_cycles < self.policy.config.force_llm_after_silent and vital < 0.66:
                return f"family_cooldown:{family}:{now - last_family:.1f}/{family_cooldown:.1f}s"
        if self._body_only_streak >= self.policy.config.max_body_only_streak:
            # Body-only quá nhiều thì không tiếp tục nhúc nhích giả vờ sống.
            # Không trả rate-limit nữa, vì rate-limit sẽ chặn luôn vòng force LLM.
            # Đẩy silent_cycles tới ngưỡng rồi cho policy đi tiếp. Máy móc cũng cần bớt tự cắn dây điện.
            self.silent_cycles = max(self.silent_cycles, int(self.policy.config.force_llm_after_silent))
            return ""
        return ""

    def _family_id(self, impulse: SurfaceImpulse) -> str:
        return f"{impulse.kind}:{impulse.family or self._family_key(impulse.topic_seed)}"[:160]

    def _mark_attempt(self, impulse: SurfaceImpulse, *, result: str, body_only: bool) -> None:
        """Ghi cả reject/body-only như một lần chạm surface budget.

        Nếu chỉ ghi khi speak, presence sẽ gõ cửa liên tục rồi giả vờ chưa làm gì.
        Một kiểu gaslight rất máy móc, và máy móc còn không có cớ hay.
        """
        now = time.time()
        presence_like = bool(impulse.is_presence or impulse.kind in {"presence_maintenance", "micro_presence", "re_engagement"})
        if presence_like or body_only:
            self.last_surface_time = now
        family = self._family_id(impulse)
        if family and (presence_like or body_only):
            self._last_family_at[family] = now

    def _mark_surface(self, impulse: SurfaceImpulse) -> None:
        now = time.time()
        self.last_surface_time = now
        family = self._family_id(impulse)
        if family:
            self._last_family_at[family] = now
        self._body_only_streak = 0

    def _note_non_speech(self, *, body_only: bool) -> None:
        self.silent_cycles += 1
        if body_only:
            self._body_only_streak += 1
        else:
            self._body_only_streak = 0

    def _call_llm_generator(self, impulse: SurfaceImpulse, *, snapshot: Any, force_llm: bool) -> tuple[str, str]:
        generator = self.llm_generator
        if generator is None:
            return "", "no_llm_generator"
        try:
            if hasattr(generator, "generate_micro"):
                result = generator.generate_micro(impulse=impulse, snapshot=snapshot, force_llm=force_llm)
            else:
                result = generator(impulse=impulse, snapshot=snapshot, force_llm=force_llm)
        except TypeError:
            try:
                result = generator(impulse, snapshot, force_llm)
            except Exception as exc:
                return "", f"llm_error:{exc}"
        except Exception as exc:
            return "", f"llm_error:{exc}"
        if isinstance(result, tuple):
            text = str(result[0] or "") if result else ""
            trace = str(result[1] or "llm") if len(result) > 1 else "llm"
            return text, trace
        return str(result or ""), "llm"

    def _reset_silence(self) -> None:
        self.silent_cycles = 0
        self.last_surface_time = time.time()

    def _trace(self, winner: SurfaceImpulse, suppressed: tuple[SurfaceImpulse, ...], mode: str, result: str) -> str:
        candidate_items = (winner, *suppressed[:5])
        candidate_note = " | ".join(
            f"{item.kind}:raw={item.score:.2f},eff={self._effective_score(item):.2f}"
            + (f"[{self._candidate_notes(item)}]" if self._candidate_notes(item) else "")
            for item in candidate_items
        )
        return (
            "[surface_arbiter_arbitration]"
            f" winner={winner.kind}"
            f"; source={winner.source}"
            f"; mode={mode}"
            f"; confidence={winner.confidence:.2f}"
            f"; raw_score={winner.score:.2f}"
            f"; effective_score={self._effective_score(winner):.2f}"
            f"; silent_cycles={self.silent_cycles}"
            f"; focus_family={winner.focus_family}"
            f"; missing_evidence_ids={winner.missing_evidence_ids}"
            f"; vital={_clamp01(getattr(winner, 'vital_pressure', 0.0)):.2f}"
            f"; result={result}"
            f"; candidates={candidate_note}"
        )

    @staticmethod
    def _priority(kind: str, source: str) -> float:
        key = str(kind or "")
        return {
            "re_engagement": 0.76,
            "micro_observation": 0.72,
            "presence_maintenance": 0.66,
            "idle_curiosity": 0.56,
            "curious_question": 0.54,
            "inner_whim": 0.50,
            "light_muse": 0.48,
            "thought_stream_surface": 0.50,
            "random_chatter": 0.49,
            "memory_resonance": 0.48,
            "micro_presence": 0.44,
        }.get(key, 0.40 if source else 0.0)

    @staticmethod
    def _first_text(*values: Any) -> str:
        for value in values:
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _family_key(value: Any) -> str:
        text = re.sub(r"[^a-zA-Z0-9_\-\s]", " ", str(value or "").lower())
        words = [word for word in text.split() if len(word) >= 2]
        return "_".join(words[:5])[:80] or "unanchored"
