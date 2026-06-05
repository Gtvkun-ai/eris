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

        rate_limit_reason = self._rate_limit_reason(winner, force_llm=force_llm)
        if rate_limit_reason:
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
                    debug_trace=self._trace(winner, suppressed, mode, str(trace or "llm_ok")),
                    impulse=winner,
                    suppressed=suppressed,
                )
                self.last_decision = decision
                return decision

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
            raw=item,
        )

    def _score_and_select_winner(self, impulses: tuple[SurfaceImpulse, ...]) -> tuple[SurfaceImpulse | None, tuple[SurfaceImpulse, ...]]:
        viable = tuple(item for item in impulses if item.should_surface and not item.needs_external_evidence)
        if not viable:
            return None, ()
        ordered = tuple(sorted(viable, key=lambda item: (item.score, self._priority(item.kind, item.source)), reverse=True))
        return ordered[0], ordered[1:]

    def _rate_limit_reason(self, impulse: SurfaceImpulse, *, force_llm: bool) -> str:
        if force_llm:
            return ""
        now = time.time()
        min_interval = float(getattr(self.policy.config, "min_surface_interval_seconds", 0.0) or 0.0)
        if self.last_surface_time > 0 and min_interval > 0 and now - self.last_surface_time < min_interval:
            # Không rate-limit long-silence force path; còn lại thì chặn để tránh lải nhải.
            if self.silent_cycles < self.policy.config.force_llm_after_silent:
                return f"surface_interval_cooldown:{now - self.last_surface_time:.1f}/{min_interval:.1f}s"
        family_cooldown = float(getattr(self.policy.config, "family_cooldown_seconds", 0.0) or 0.0)
        family = self._family_id(impulse)
        last_family = float(self._last_family_at.get(family, 0.0) or 0.0)
        if family and last_family > 0 and family_cooldown > 0 and now - last_family < family_cooldown:
            if self.silent_cycles < self.policy.config.force_llm_after_silent:
                return f"family_cooldown:{family}:{now - last_family:.1f}/{family_cooldown:.1f}s"
        if self._body_only_streak >= self.policy.config.max_body_only_streak:
            # Body-only quá nhiều thì không tiếp tục nhúc nhích giả vờ sống; đẩy silent cycle lên để tới force LLM.
            return f"body_only_streak_limit:{self._body_only_streak}"
        return ""

    def _family_id(self, impulse: SurfaceImpulse) -> str:
        return f"{impulse.kind}:{impulse.family or self._family_key(impulse.topic_seed)}"[:160]

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
        suppressed_note = ",".join(f"{item.kind}:{item.score:.2f}" for item in suppressed[:4])
        return (
            "surface_arbiter"
            f"; source={winner.source}"
            f"; kind={winner.kind}"
            f"; mode={mode}"
            f"; confidence={winner.confidence:.2f}"
            f"; score={winner.score:.2f}"
            f"; silent_cycles={self.silent_cycles}"
            f"; focus_family={winner.focus_family}"
            f"; missing_evidence_ids={winner.missing_evidence_ids}"
            f"; result={result}"
            f"; suppressed={suppressed_note}"
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
            "thought_stream_surface": 0.46,
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
