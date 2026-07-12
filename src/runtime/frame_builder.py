from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass, replace

from cortex.contracts import (
    AgentSpeechCore,
    AttentionCandidate,
    CognitiveActionPlan,
    CognitiveAppraisal,
    CognitiveBroadcast,
    CognitiveDisturbance,
    CognitiveFrame,
    InnerThought,
    CognitiveMemoryUpdate,
    MeaningLayerResult,
    PersonalityLensResult,
    PerceptEvent,
    SessionRitualReport,
    SilenceState,
    SubconsciousReport,
    ThoughtStreamReport,
    TiPolicyReport,
)
from cortex.internal_state import PersistentInternalState
from cortex.micro_policy import RelationalContext
from cortex.relationship_dynamics import RelationshipTurnEvent
from core.evidence import EvidenceItem, RawSignal
from cortex.modes import QUIET_MODES
from cortex.ni import NiStateMachine
from domain import Decision
from runtime.body_bias import BodyBiasProjector
from runtime.presence_controller import SocialPresenceEvent
from runtime.speech_pipeline import SpeechIntentDecision


class FrameBuilderMixin:
    def _make_cognitive_disturbance(
        self,
        *,
        channel: str,
        kind: str,
        content: str,
        evidence: tuple[str, ...] = (),
        intensity: float = 1.0,
    ) -> CognitiveDisturbance | None:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        if not text:
            return None
        return CognitiveDisturbance(
            channel=str(channel or ""),
            kind=str(kind or ""),
            content=text[:240],
            evidence=tuple(str(item) for item in (evidence or ()) if str(item or "").strip())[:6],
            intensity=self._bounded_float(intensity),
            timestamp=time.time(),
            closes_loop=self._looks_like_closure_disturbance(text),
        )
    def _looks_like_closure_disturbance(self, content: str) -> bool:
        normalized = self._normalize_user_message(content)
        return any(
            token in normalized
            for token in (
                "done",
                "fixed",
                "resolved",
                "solved",
                "complete",
                "completed",
                "xong",
                "đã xong",
                "giải quyết",
            )
        )
    def _build_event_disturbances(
        self,
        *,
        channel: str,
        snapshot=None,
        user_text: str = "",
        force_speak: bool = False,
        vision_facts: tuple[str, ...] = (),
    ) -> tuple[CognitiveDisturbance, ...]:
        disturbances: list[CognitiveDisturbance] = []
        if user_text:
            disturbance = self._make_cognitive_disturbance(
                channel=channel,
                kind="user_message",
                content=user_text,
                evidence=("direct_user_input",),
                intensity=1.0,
            )
            if disturbance is not None:
                disturbances.append(disturbance)

        if force_speak:
            # P0: force_speak là explicit pull từ user. Nếu không có evidence màn
            # hình cụ thể, vẫn phải tạo requested_presence cực mạnh để thought_stream
            # và impulse arbitration có chất liệu nội sinh, thay vì rơi xuống
            # micro_presence máy móc.
            concrete = ()
            try:
                concrete = tuple(self._concrete_screen_signals(snapshot) or ())
            except Exception:
                concrete = ()
            force_evidence = tuple(vision_facts or ())[:3] or ("ui_request",)
            if not concrete:
                force_evidence = tuple(dict.fromkeys((*force_evidence, "requested_presence", "no_concrete_screen_signal")))
            disturbance = self._make_cognitive_disturbance(
                channel=channel,
                kind="user_force_speak",
                content="requested_presence: force_speak requested without concrete screen evidence" if not concrete else "force_speak requested",
                evidence=force_evidence,
                intensity=1.0 if not concrete else 0.92,
            )
            if disturbance is not None:
                disturbances.append(disturbance)

        if channel == "autonomous":
            recent_events = tuple(str(item) for item in (getattr(snapshot, "recent_events", ()) or ())[:3])
            evidence = tuple(str(item) for item in (getattr(snapshot, "evidence", ()) or ())[:3])
            active = str(getattr(snapshot, "active_window_kind", "") or getattr(snapshot, "active_window", "") or "ambient")
            idle = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
            content = f"autonomous tick: focus={active}; idle={int(idle)}s"
            if recent_events:
                content = f"{content}; events={', '.join(recent_events[:2])}"
            intensity = 0.34 + min(0.18, idle / 1800.0)
            if recent_events or evidence or vision_facts:
                intensity += 0.16
            disturbance = self._make_cognitive_disturbance(
                channel=channel,
                kind="autonomous_tick",
                content=content,
                evidence=tuple(dict.fromkeys((*recent_events, *evidence, *tuple(vision_facts or ()))))[:6],
                intensity=intensity,
            )
            if disturbance is not None:
                disturbances.append(disturbance)

        return tuple(disturbances)
    def _disturb_cognitive_substrate(
        self,
        *,
        channel: str,
        snapshot=None,
        user_text: str = "",
        force_speak: bool = False,
        vision_facts: tuple[str, ...] = (),
        consume_surface: bool = False,
    ) -> ThoughtStreamReport:
        disturbances = self._build_event_disturbances(
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            force_speak=force_speak,
            vision_facts=vision_facts,
        )
        substrate = getattr(self, "cognitive_substrate", self.thought_stream)
        report = substrate.latest_report() if callable(getattr(substrate, "latest_report", None)) else ThoughtStreamReport()
        injector = getattr(substrate, "inject_disturbances", None)
        if disturbances and callable(injector):
            report = injector(disturbances, immediate=True, queue_surface=False)
        if consume_surface and not getattr(getattr(report, "latest_seed", None), "mode", ""):
            pop_surface = getattr(substrate, "pop_surface", None)
            if callable(pop_surface):
                report = self._with_thought_stream_surface(report, pop_surface())
        return report
    def _with_thought_stream_surface(self, report: ThoughtStreamReport, surface) -> ThoughtStreamReport:
        if surface is None or not getattr(surface, "mode", ""):
            return report
        return ThoughtStreamReport(
            latest_seed=surface,
            recent_seeds=getattr(report, "recent_seeds", ()),
            surface_pressure=max(float(getattr(report, "surface_pressure", 0.0) or 0.0), float(getattr(surface, "pressure", 0.0) or 0.0)),
            suppression_reason="",
            latest_thought=getattr(report, "latest_thought", None) or ThoughtStreamReport().latest_thought,
            recent_thoughts=getattr(report, "recent_thoughts", ()),
            momentum=getattr(report, "momentum", None) or ThoughtStreamReport().momentum,
            recent_momentum=getattr(report, "recent_momentum", ()),
            active_attractor=getattr(report, "active_attractor", None) or ThoughtStreamReport().active_attractor,
            unresolved_loops=getattr(report, "unresolved_loops", ()),
            stream_tension=float(getattr(report, "stream_tension", 0.0) or 0.0),
            unresolved_count=int(getattr(report, "unresolved_count", 0) or 0),
            continuity_notes=tuple(getattr(report, "continuity_notes", ()) or ()),
            disturbances=tuple(getattr(report, "disturbances", ()) or ()),
        )
    def _pop_thought_stream_report_for_autonomous(self) -> ThoughtStreamReport:
        surface = self.thought_stream.pop_surface()
        latest = self.thought_stream.latest_report()
        if not surface.mode:
            return ThoughtStreamReport(
                recent_seeds=latest.recent_seeds,
                surface_pressure=latest.surface_pressure,
                suppression_reason=latest.suppression_reason or "no_surface_seed",
                latest_thought=latest.latest_thought,
                recent_thoughts=latest.recent_thoughts,
                momentum=latest.momentum,
                recent_momentum=latest.recent_momentum,
                active_attractor=latest.active_attractor,
                unresolved_loops=latest.unresolved_loops,
                stream_tension=latest.stream_tension,
                unresolved_count=latest.unresolved_count,
                continuity_notes=latest.continuity_notes,
                disturbances=latest.disturbances,
            )
        return ThoughtStreamReport(
            latest_seed=surface,
            recent_seeds=latest.recent_seeds,
            surface_pressure=surface.pressure,
            suppression_reason="",
            latest_thought=latest.latest_thought,
            recent_thoughts=latest.recent_thoughts,
            momentum=latest.momentum,
            recent_momentum=latest.recent_momentum,
            active_attractor=latest.active_attractor,
            unresolved_loops=latest.unresolved_loops,
            stream_tension=latest.stream_tension,
            unresolved_count=latest.unresolved_count,
            continuity_notes=latest.continuity_notes,
            disturbances=latest.disturbances,
        )
    def _pop_subconscious_report_for_autonomous(self) -> SubconsciousReport:
        return self._pop_thought_stream_report_for_autonomous()
    def _thought_stream_resonance_fragments(self) -> tuple[str, ...]:
        report = self.thought_stream.latest_report()
        thought = getattr(report, "latest_thought", None)
        momentum = getattr(report, "momentum", None)
        attractor = getattr(report, "active_attractor", None)
        fragments: list[str] = []
        if thought is not None:
            fragments.extend(
                str(item)
                for item in (
                    getattr(thought, "topic_seed", ""),
                    getattr(thought, "partial_text", ""),
                    getattr(thought, "unresolved_reason", ""),
                    getattr(thought, "source_memory", ""),
                    *tuple(getattr(thought, "associations", ()) or ())[:3],
                )
                if str(item or "").strip()
            )
        if momentum is not None and getattr(momentum, "unresolved", False):
            fragments.append(
                " ".join(
                    str(item)
                    for item in (
                        getattr(momentum, "topic_seed", ""),
                        getattr(momentum, "affordance", ""),
                        getattr(momentum, "closure_state", ""),
                    )
                    if str(item or "").strip()
                )
            )
        if attractor is not None and getattr(attractor, "attractor", False):
            fragments.append(
                " ".join(
                    str(item)
                    for item in (
                        getattr(attractor, "topic_seed", ""),
                        "unresolved_tension_loop",
                    )
                    if str(item or "").strip()
                )
            )
        return tuple(item for item in fragments[-8:] if item)
    def _normalize_event_evidence(self, evidence, *, limit: int = 4) -> tuple[str, ...]:
        items: list[str] = []
        seen: set[str] = set()
        for item in evidence or ():
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            items.append(text[:160])
            seen.add(key)
            if len(items) >= limit:
                break
        return tuple(items)
    def _make_percept_event(
        self,
        *,
        #Nhận các field
        kind: str,
        content: str,
        timestamp: str,
        evidence=(),
        confidence: float = 1.0,
        source: str = "runtime",
        privacy_level: str = "internal",
        novelty_hint: str = "routine",
    ) -> PerceptEvent | None:
        text = str(content or "").strip()
        if not text:
            return None
        return PerceptEvent(
            kind=str(kind or "unknown").strip() or "unknown",
            content=text[:260],
            evidence=self._normalize_event_evidence(evidence),
            confidence=self._bounded_float(confidence),
            source=str(source or "runtime").strip() or "runtime",
            timestamp=timestamp,
            privacy_level=str(privacy_level or "internal").strip() or "internal",
            novelty_hint=str(novelty_hint or "routine").strip() or "routine",
        )
    def _telemetry_event_privacy_level(self, kind: str) -> str:
        if kind == "resource_pressure":
            return "system_metric" #chỉ số hệ thống kiểu CPU/RAM
        if kind == "idle_state": #trạng thái hoạt động/nhàn rỗi
            return "activity_state"
        return "local_context" #ngữ cảnh cục bộ như cửa sổ đang active, focus summary, recent events, evidence
    def _telemetry_event_novelty_hint(self, kind: str, content: str) -> str:
        if kind == "resource_pressure": #threshold_crossed vượt ngưỡng
            return "threshold_crossed"
        if kind == "idle_state":
            return "duration_threshold"
        if kind in {"recent_event", "evidence"}:
            if kind == "recent_event" and self._is_generic_screen_event(content):
                return "routine_telemetry" #telemetry lặp/nhạt, như "đã mở Chrome" hay "đang ở desktop"
            if kind == "evidence" and self._is_generic_screen_evidence(content):
                return "routine_telemetry" # telemetry lặp/nhạt
            return "concrete_telemetry" #telemetry cụ thể, đáng chú ý hơn
        if kind in {"active_window", "focus_context"}:
            return "ambient_context"
        return "routine"
    def _collect_percept_events(
        self,
        *,
        channel: str,
        snapshot,
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        force_speak: bool = False,
        internal_state: PersistentInternalState | None = None,
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        started_at: float | None = None,
    ) -> tuple[PerceptEvent, ...]:
        percepts: list[PerceptEvent] = []
        timestamp = self._event_timestamp(snapshot, started_at=started_at)

        def add(
            kind: str,
            content: str,
            *,
            source: str = "runtime",
            confidence: float = 1.0,
            evidence=(),
            privacy_level: str = "internal",
            novelty_hint: str = "routine",
        ) -> None:
            event = self._make_percept_event(
                kind=kind,
                content=content,
                evidence=evidence,
                confidence=confidence,
                source=source,
                timestamp=timestamp,
                privacy_level=privacy_level,
                novelty_hint=novelty_hint,
            )
            if event is not None:
                percepts.append(event)

        if user_text:
            add(
                "user_message",
                user_text,
                source="chat",
                confidence=1.0,
                privacy_level="user_private",
                novelty_hint="direct_user_input",
            )
        if force_speak:
            add(
                "user_force_speak",
                "force_speak requested",
                source="ui",
                confidence=1.0,
                privacy_level="internal",
                novelty_hint="explicit_request",
            )

        if social_presence_event is not None and bool(getattr(social_presence_event, "present", False)):
            kind = str(getattr(social_presence_event, "kind", "") or "presence")
            reason = str(getattr(social_presence_event, "reason", "") or "")
            content = f"kind={kind}; speech_allowed={bool(getattr(social_presence_event, 'speech_allowed', False))}"
            if reason:
                content += f"; reason={reason}"
            add(
                "social_presence_event",
                content,
                source="internal_state",
                confidence=max(0.45, self._bounded_float(getattr(social_presence_event, "confidence", 0.0))),
                evidence=tuple(getattr(social_presence_event, "evidence", ()) or ())[:6],
                privacy_level="internal",
                novelty_hint="social_presence",
            )

        active_window = getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "")
        add(
            "active_window",
            active_window,
            source="telemetry",
            confidence=0.72,
            privacy_level=self._telemetry_event_privacy_level("active_window"),
            novelty_hint=self._telemetry_event_novelty_hint("active_window", str(active_window)),
        )
        focus_summary = getattr(snapshot, "focus_summary", "")
        add(
            "focus_context",
            focus_summary,
            source="telemetry",
            confidence=0.68,
            privacy_level=self._telemetry_event_privacy_level("focus_context"),
            novelty_hint=self._telemetry_event_novelty_hint("focus_context", str(focus_summary)),
        )

        for deviation_text in self._norm_deviation_texts(snapshot):
            add(
                "norm_deviation",
                deviation_text,
                source="memory",
                confidence=0.66,
                evidence=("norm_memory",),
                privacy_level="internal",
                novelty_hint="baseline_deviation",
            )

        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        if idle_seconds >= 180:
            idle_content = f"idle={int(idle_seconds)}s ({getattr(snapshot, 'idle_label', '') or 'idle'})"
            add(
                "idle_state",
                idle_content,
                source="telemetry",
                confidence=0.64,
                privacy_level=self._telemetry_event_privacy_level("idle_state"),
                novelty_hint=self._telemetry_event_novelty_hint("idle_state", idle_content),
            )

        vision_fact_keys = {str(item or "").strip().lower() for item in tuple(vision_facts or ())}
        for event in tuple(getattr(snapshot, "recent_events", ()) or ())[:6]:
            event_text = str(event)
            if event_text.strip().lower() in vision_fact_keys:
                continue
            add(
                "recent_event",
                event_text,
                source="telemetry",
                confidence=0.76,
                privacy_level=self._telemetry_event_privacy_level("recent_event"),
                novelty_hint=self._telemetry_event_novelty_hint("recent_event", event_text),
            )
        for item in tuple(getattr(snapshot, "evidence", ()) or ())[:6]:
            evidence_text = str(item)
            add(
                "evidence",
                evidence_text,
                source="telemetry",
                confidence=0.72,
                privacy_level=self._telemetry_event_privacy_level("evidence"),
                novelty_hint=self._telemetry_event_novelty_hint("evidence", evidence_text),
            )
        for fact in tuple(vision_facts or ())[: self.vision_fact_max_items]:
            add(
                "vision_fact",
                str(fact),
                source="vision",
                confidence=0.86,
                evidence=(self.vision_last_trace or "vision_facts",),
                privacy_level="screen_context",
                novelty_hint=getattr(self, "vision_facts_novelty_hint", "") or "screen_fact",
            )

        for disturbance in tuple(getattr(thought_stream_report, "disturbances", ()) or ())[:3]:
            disturbance_channel = str(getattr(disturbance, "channel", "") or "")
            disturbance_kind = str(getattr(disturbance, "kind", "") or "")
            disturbance_content = str(getattr(disturbance, "content", "") or "")
            if not disturbance_content:
                continue
            add(
                "substrate_disturbance",
                f"{disturbance_channel}/{disturbance_kind}: {disturbance_content}",
                source="cognitive_substrate",
                confidence=max(0.45, self._bounded_float(getattr(disturbance, "intensity", 0.0))),
                evidence=tuple(getattr(disturbance, "evidence", ()) or ())[:6],
                privacy_level="internal" if disturbance_kind != "user_message" else "user_private",
                novelty_hint="input_disturbance",
            )

        momentum = getattr(thought_stream_report, "momentum", None)
        active_attractor = getattr(thought_stream_report, "active_attractor", None)
        if (
            active_attractor is not None
            and bool(getattr(active_attractor, "attractor", False))
            and float(getattr(active_attractor, "score", 0.0) or 0.0) >= 0.64
        ):
            loop_id = str(getattr(active_attractor, "loop_id", "") or "")
            topic_seed = str(getattr(active_attractor, "topic_seed", "") or "")
            add(
                "cognitive_attractor",
                f"loop={loop_id}; topic={topic_seed}",
                source="thought_stream",
                confidence=max(0.76, self._bounded_float(getattr(active_attractor, "score", 0.0))),
                evidence=tuple(getattr(active_attractor, "evidence", ()) or ())[:6],
                privacy_level="internal",
                novelty_hint="cognitive_attractor",
            )

        if (
            momentum is not None
            and str(getattr(momentum, "affordance", "") or "") == "attention"
            and float(getattr(momentum, "score", 0.0) or 0.0) >= 0.58
        ):
            topic_seed = str(getattr(momentum, "topic_seed", "") or "")
            mode = str(getattr(momentum, "mode", "") or "")
            thought_id = str(getattr(momentum, "thought_id", "") or "")
            add(
                "cognitive_momentum",
                f"thought={thought_id}; mode={mode}; topic={topic_seed}",
                source="thought_stream",
                confidence=max(0.72, self._bounded_float(getattr(momentum, "score", 0.0))),
                evidence=tuple(getattr(momentum, "evidence", ()) or ())[:6],
                privacy_level="internal",
                novelty_hint="cognitive_momentum",
            )

        goal_state = getattr(internal_state, "goal_persistence", None) if internal_state is not None else None
        if goal_state is not None and bool(getattr(goal_state, "active", False)):
            summary = str(getattr(goal_state, "summary", "") or "")
            strength = float(getattr(goal_state, "strength", 0.0) or 0.0)
            urgency = float(getattr(goal_state, "urgency", 0.0) or 0.0)
            if summary:
                add(
                    "persistent_goal",
                    f"goal={summary}; strength={strength:.2f}; urgency={urgency:.2f}",
                    source="internal_state",
                    confidence=max(0.70, self._bounded_float(strength)),
                    evidence=tuple(getattr(goal_state, "evidence", ()) or ())[:6],
                    privacy_level="internal",
                    novelty_hint="persistent_goal",
                )

        add(
            "cycle_channel",
            channel,
            source="runtime",
            confidence=0.50,
            privacy_level="internal",
            novelty_hint="cycle_marker",
        )
        return tuple(percepts[:18])
    def _collect_cognitive_percepts(self, **kwargs) -> tuple[PerceptEvent, ...]:
        return self._collect_percept_events(**kwargs)
    def _score_attention_candidate(self, percept: PerceptEvent) -> tuple[float, str]:
        candidates = self._build_attention_candidates((percept,), channel="test")
        if not candidates:
            return 0.0, "attention_salience:no_candidate"
        candidate = candidates[0]
        return candidate.score, candidate.reason

        base_by_kind = {
            "user_message": 0.96,
            "user_force_speak": 0.91,
            "resource_pressure": 0.88,
            "vision_fact": 0.84,
            "recent_event": 0.66,
            "evidence": 0.58,
            "idle_state": 0.48,
            "active_window": 0.42,
            "focus_context": 0.40,
            "cycle_channel": 0.20,
        }
        score = base_by_kind.get(percept.kind, 0.36) * percept.confidence
        reason_parts = [f"kind={percept.kind}", f"confidence={percept.confidence:.2f}"]
        lowered = percept.content.lower()

        if percept.source == "vision":
            score += 0.08
            reason_parts.append("vision")
        if len(percept.content) >= 28:
            score += 0.04
            reason_parts.append("specific")
        if any(token in lowered for token in ("error", "failed", "lỗi", "cpu", "ram", "đã đọc", "message", "tin nhắn")):
            score += 0.08
            reason_parts.append("charged")
        if percept.kind == "recent_event" and self._is_generic_screen_event(percept.content):
            score -= 0.18
            reason_parts.append("generic_event")
        if percept.kind == "evidence" and self._is_generic_screen_evidence(percept.content):
            score -= 0.18
            reason_parts.append("generic_evidence")

        return self._bounded_float(score), ", ".join(reason_parts)
    def _build_attention_candidates(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
    ) -> tuple[AttentionCandidate, ...]:
        evidence = self._evidence_from_percepts(
            percepts,
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
        )
        if not evidence:
            return ()
        try:
            salience = self.attention_salience_engine.evaluate(
                evidence=evidence,
                channel=channel,
                active_goal=getattr(self._get_internal_state(), "goal_persistence", None),
                now=time.time(),
                write_to_frame=False,
            )
        except Exception as exc:
            self.logger.warning("AttentionSalience candidate ranking error: %s", exc)
            return ()
        converted = [self._salience_candidate_to_runtime(candidate) for candidate in salience.candidates]
        converted.sort(key=lambda item: item.score, reverse=True)
        return tuple(converted)
    def _build_broadcast(self, candidates: tuple[AttentionCandidate, ...]) -> CognitiveBroadcast:
        if not candidates:
            return CognitiveBroadcast(reason="attention_salience:no_candidates")
        broadcastable = tuple(
            candidate
            for candidate in candidates
            if candidate.label not in {"social_presence_event"}
        )
        if not broadcastable:
            return CognitiveBroadcast(reason="attention_salience:background_only")
        winners = tuple(
            candidate
            for candidate in broadcastable
            if candidate.score >= self.attention_broadcast_threshold
            and candidate.privacy_level not in {"private", "sensitive"}
        )
        if not winners:
            top = broadcastable[0]
            return CognitiveBroadcast(
                label=top.label,
                content=top.content,
                score=top.score,
                source=top.source,
                reason=f"attention_salience:top_below_threshold; {top.reason}",
                evidence=top.evidence,
                items=(top,),
            )
        top = winners[0]
        return CognitiveBroadcast(
            label=top.label,
            content=top.content,
            score=top.score,
            source=top.source,
            reason=(
                "attention_salience:winners="
                + ",".join(f"{item.label}:{item.score:.2f}" for item in winners[:4])
            ),
            evidence=top.evidence,
            items=winners,
        )
    def _evidence_from_percepts(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
    ) -> tuple[dict[str, object], ...]:
        evidence: list[dict[str, object]] = []

        def add(
            source: str,
            claim: str,
            *,
            confidence: float = 0.62,
            reliability: float = 0.72,
            privacy_level: str = "normal",
            tags: tuple[str, ...] = (),
        ) -> None:
            clean = str(claim or "").strip()
            if not clean:
                return
            index = len(evidence)
            evidence.append(
                {
                    "id": f"att.ev.{index:03d}",
                    "source_signal_id": f"{source}.{index:03d}",
                    "source": source,
                    "claim": clean,
                    "timestamp": time.time(),
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "reliability": max(0.0, min(1.0, float(reliability))),
                    "privacy_level": privacy_level,
                    "raw_or_inferred": "raw",
                    "tags": tags,
                }
            )

        if user_text:
            add("user_chat", user_text, confidence=0.96, reliability=0.98, tags=("user_message", "user", "request"))
        for percept in tuple(percepts or ()):
            kind = str(getattr(percept, "kind", "") or "percept")
            source = str(getattr(percept, "source", "") or "runtime")
            if source in {"runtime", "internal_state", "thought_stream", "social_presence_detector"}:
                source = "system_log"
            add(
                source,
                str(getattr(percept, "content", "") or ""),
                confidence=float(getattr(percept, "confidence", 0.62) or 0.62),
                reliability=0.70,
                privacy_level=str(getattr(percept, "privacy_level", "normal") or "normal"),
                tags=(kind, *tuple(str(x) for x in getattr(percept, "evidence", ()) or ()), channel),
            )
        return tuple(evidence)
    def _salience_candidate_to_runtime(self, candidate) -> AttentionCandidate:
        tags = tuple(str(item) for item in getattr(candidate, "tags", ()) or ())
        label = self._runtime_attention_label(candidate, tags)
        breakdown = getattr(candidate, "score_breakdown", None)
        score_parts: dict[str, float] = {}
        if breakdown is not None and callable(getattr(breakdown, "to_dict", None)):
            score_parts = {str(key): float(value) for key, value in breakdown.to_dict().items()}
        return AttentionCandidate(
            label=label,
            content=str(getattr(candidate, "claim", "") or ""),
            score=float(getattr(candidate, "score", 0.0) or 0.0),
            source=str(getattr(candidate, "source", "") or "runtime"),
            reason=(
                f"attention_salience:{getattr(candidate, 'family', 'unknown')}:"
                f"{getattr(candidate, 'focus_kind', 'unknown')}"
            ),
            evidence=tuple(str(item) for item in (getattr(candidate, "evidence_id", "") or "",) if item),
            privacy_level=str(getattr(candidate, "privacy_level", "internal") or "internal"),
            novelty_hint=str((tags or ("routine",))[0] or "routine"),
            score_parts=score_parts,
        )
    def _runtime_attention_label(self, candidate, tags: tuple[str, ...]) -> str:
        known_labels = {
            "user_message",
            "user_force_speak",
            "resource_pressure",
            "vision_fact",
            "recent_event",
            "evidence",
            "idle_state",
            "active_window",
            "focus_context",
            "cycle_channel",
            "cognitive_momentum",
            "cognitive_attractor",
            "persistent_goal",
            "social_presence_event",
            "substrate_disturbance",
        }
        for tag in tags:
            if tag in known_labels:
                return tag
        source = str(getattr(candidate, "source", "") or "")
        family = str(getattr(candidate, "family", "") or "")
        if source == "vision":
            return "vision_fact"
        if source == "active_window":
            return "active_window"
        if family == "user_request":
            return "user_message"
        if family == "runtime_risk":
            return "resource_pressure"
        if family == "goal_signal":
            return "persistent_goal"
        return str(getattr(candidate, "focus_kind", "") or "attention_signal")
    def _build_meaning_layer(
        self,
        *,
        snapshot,
        broadcast: CognitiveBroadcast,
        internal_state,
        thought_stream_report=None,
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
        affect_signal=None,
        ti_report=None,
        fe_plan=None,
    ) -> MeaningLayerResult:
        if str(channel or "").strip().lower() == "chat":
            return self.chat_meaning_layer_light.evaluate(
                user_text=user_text,
                affect_signal=affect_signal,
                ti_report=ti_report,
                fe_plan=fe_plan,
                previous_assistant_text=getattr(self, "last_chat_answer", ""),
            )
        return self.meaning_layer.evaluate(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=internal_state,
            thought_stream_report=thought_stream_report,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            recent_families=tuple(self.recent_meaning_families[-3:]),
        )
    def _build_personality_lens(
        self,
        *,
        snapshot,
        broadcast: CognitiveBroadcast,
        internal_state,
        meaning_layer: MeaningLayerResult | None = None,
        channel: str = "",
        user_text: str = "",
        affect_signal=None,
        ti_report=None,
        fe_plan=None,
    ) -> PersonalityLensResult:
        if str(channel or "").strip().lower() == "chat":
            return self.chat_personality_pressure_light.evaluate(
                meaning_layer=meaning_layer,
                affect_signal=affect_signal,
                ti_report=ti_report,
                fe_plan=fe_plan,
                user_text=user_text,
                previous_assistant_text=getattr(self, "last_chat_answer", ""),
            )
        return self.personality_lens.evaluate(
            scene=snapshot,
            attention=broadcast,
            meaning_layer=meaning_layer,
            internal_state=internal_state,
            relationship=self.fe_style_memory,
            channel=channel,
            user_text=user_text,
        )
    def _apply_personality_lens_to_fe_plan(self, fe_plan, lens: PersonalityLensResult):
        applicator = getattr(self.fe_renderer, "apply_personality_lens", None)
        if callable(applicator):
            return applicator(fe_plan, lens)

        prompt_context = str(getattr(lens, "prompt_context", "") or "").strip()
        if prompt_context and hasattr(fe_plan, "style_context"):
            current = str(getattr(fe_plan, "style_context", "") or "")
            setattr(fe_plan, "style_context", f"{current}\n{prompt_context}" if current else prompt_context)
        if hasattr(fe_plan, "evidence"):
            evidence = tuple(getattr(fe_plan, "evidence", ()) or ())
            setattr(
                fe_plan,
                "evidence",
                tuple(dict.fromkeys((*evidence, f"personality_lens={lens.interpretation}"))),
            )
        return fe_plan
    def _build_cognitive_appraisal(
        self,
        *,
        internal_state,
        ni_report,
        ti_report,
        fe_plan,
        broadcast,
        channel: str = "",
        user_text: str = "",
        force_speak: bool = False,
        personality_lens=None,
    ) -> CognitiveAppraisal:
        return self.appraisal_engine.evaluate(
            internal_state=internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            broadcast=broadcast,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            memory_resonance=getattr(self, "active_memory_resonance", None),
            personality_lens=personality_lens,
            prev_stance_blend=getattr(internal_state, "last_stance_blend", None) or None,
        )
    def _build_appraisal_context(self, appraisal: CognitiveAppraisal, *, frame=None) -> str:
        context = self.appraisal_engine.render_prompt_context(appraisal)
        advisory = self._tom_advisory_for(frame)
        if advisory:
            context = f"{context}\n{advisory}"
        self._maybe_write_panel_snapshot(appraisal, advisory)
        return context

    def _maybe_write_panel_snapshot(self, appraisal, advisory) -> None:
        """Ghi tín hiệu sống ra panel_snapshot.json (flag-gated, throttled, không ném).

        Cũng cache tom advisory để depth_v2 payload sang body Godot có dữ liệu —
        đây là chỗ duy nhất tom_read được tính trên hot path nói.
        """
        try:
            self._last_tom_advisory = advisory or ""
        except Exception:
            pass
        try:
            from runtime.panel_snapshot import write as _write_snapshot

            _write_snapshot(
                appraisal=appraisal,
                expression_gate=getattr(self, "_last_expression_gate", None),
                tom_read=advisory or "",
            )
        except Exception:
            pass

    def _tom_advisory_for(self, frame) -> str:
        """Nước 3 — dòng ToM advisory cho prompt. "" khi tắt cờ / không có workspace / lỗi."""
        if frame is None:
            return ""
        try:
            from cortex.tom_advisor import advise

            line = advise(frame)
        except Exception:
            line = ""
        try:
            self._last_tom_advisory = line  # cache cho panel depth block
        except Exception:
            pass
        return line
    def _build_inner_thought(
        self,
        *,
        channel: str,
        snapshot,
        frame: CognitiveFrame,
        concrete_signals: tuple[str, ...] = (),
        repeat_count: int = 1,
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
        subconscious_seed=None,
        thought_surface=None,
    ) -> InnerThought:
        return self.inner_thought_engine.evaluate(
            channel=channel,
            snapshot=snapshot,
            appraisal=frame.appraisal,
            broadcast=frame.broadcast,
            style_memory=self.fe_style_memory,
            concrete_signals=tuple(concrete_signals or ()),
            last_text=self.last_text,
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            recent_inner_intents=self.recent_inner_thought_intents,
            recent_inner_seeds=self.recent_inner_thought_seeds,
            thought_surface=thought_surface if thought_surface is not None else subconscious_seed,
        )
    def _build_speech_core(
        self,
        *,
        channel: str,
        snapshot,
        internal_state,
        frame: CognitiveFrame,
        ti_report,
        fe_plan,
        ni_report=None,
        ni_state_label: str = "",
        repeat_count: int = 1,
        repeated_topic_tag: str = "",
        repeated_topic_streak: int = 0,
        subconscious_seed=None,
        thought_surface=None,
    ) -> AgentSpeechCore:
        concrete_signals = self._concrete_screen_signals(snapshot)
        screen_comment_allowed = channel == "force_speak"
        if concrete_signals and channel != "force_speak":
            screen_comment_allowed = bool(self._broadcast_screen_winners(frame.broadcast))
        speech_core = self.speech_core_engine.evaluate(
            channel=channel,
            snapshot=snapshot,
            internal_state=internal_state,
            appraisal=frame.appraisal,
            broadcast=frame.broadcast,
            ti_report=ti_report,
            fe_plan=fe_plan,
            style_memory=self.fe_style_memory,
            concrete_signals=concrete_signals,
            vision_signals=self._concrete_vision_signals(snapshot),
            telemetry_signals=self._concrete_telemetry_signals(snapshot),
            screen_comment_allowed=screen_comment_allowed,
            repeat_count=repeat_count,
            repeated_topic_tag=repeated_topic_tag,
            repeated_topic_streak=repeated_topic_streak,
            recent_inner_intents=self.recent_inner_thought_intents,
            recent_inner_seeds=self.recent_inner_thought_seeds,
            ni_state_label=ni_state_label,
            ni_report=ni_report,
            thought_surface=thought_surface if thought_surface is not None else subconscious_seed,
            self_state=frame.self_state,
            meaning_layer=getattr(frame, "meaning_layer", None),
            personality_lens=getattr(frame, "personality_lens", None),
            agent_mind=getattr(self, "epistemic_agent_mind", None) or getattr(getattr(self, "memory_core", None), "agent_mind", None),
            safe_small_talk_allowed=self._safe_small_talk_budget_allowed(
                channel=channel,
                snapshot=snapshot,
                now=time.time(),
            ),
        )
        frame.speech_core = speech_core
        frame.inner_thought = speech_core.inner_thought
        return speech_core
    def _remember_inner_thought_rhythm(self, inner_thought: InnerThought | None) -> None:
        if inner_thought is None or not inner_thought.intent:
            return
        self.recent_inner_thought_intents = (*self.recent_inner_thought_intents, inner_thought.intent)[-6:]
        if inner_thought.topic_seed:
            self.recent_inner_thought_seeds = (*self.recent_inner_thought_seeds, inner_thought.topic_seed)[-8:]
    def _run_context_bottleneck(
        self,
        frame: CognitiveFrame,
        *,
        snapshot,
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        started_at: float,
    ) -> None:
        evidence = self._build_cognitive_evidence(
            frame,
            snapshot=snapshot,
            user_text=user_text,
            vision_facts=vision_facts,
            started_at=started_at,
        )
        frame.evidence = evidence
        try:
            frame.salience = self.attention_salience_engine.evaluate(
                frame,
                evidence=evidence,
                channel=frame.channel,
                active_goal=getattr(frame.internal_state_after, "goal_persistence", None),
                now=started_at,
                write_to_frame=False,
            )
        except Exception as exc:
            self.logger.warning("AttentionSalience integration error: %s", exc)
            frame.salience = None
        try:
            frame.working_memory = self.working_memory_engine.select(frame, now=started_at)
        except Exception as exc:
            self.logger.warning("WorkingMemory integration error: %s", exc)
            frame.working_memory = None
    def _build_cognitive_evidence(
        self,
        frame: CognitiveFrame,
        *,
        snapshot,
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        started_at: float,
    ) -> tuple[dict[str, object], ...]:
        evidence: list[dict[str, object]] = []

        def add(
            source: str,
            claim: str,
            *,
            confidence: float = 0.62,
            reliability: float = 0.72,
            privacy_level: str = "normal",
            raw_or_inferred: str = "raw",
            tags: tuple[str, ...] = (),
        ) -> None:
            clean = str(claim or "").strip()
            if not clean:
                return
            index = len(evidence)
            evidence.append(
                {
                    "id": f"ev.{frame.cycle_id}.{index:03d}",
                    "source_signal_id": f"{source}.{index:03d}",
                    "source": source,
                    "claim": clean,
                    "timestamp": started_at,
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "reliability": max(0.0, min(1.0, float(reliability))),
                    "privacy_level": privacy_level,
                    "raw_or_inferred": raw_or_inferred,
                    "tags": tags,
                }
            )

        add(
            "user_chat",
            user_text,
            confidence=0.96,
            reliability=0.98,
            privacy_level="normal",
            tags=("user", "request", "chat"),
        )
        for percept in tuple(frame.percepts or ()):
            source = str(getattr(percept, "source", "") or "runtime")
            if source == "runtime":
                source = "system_log"
            kind = str(getattr(percept, "kind", "") or "percept")
            add(
                source,
                str(getattr(percept, "content", "") or ""),
                confidence=float(getattr(percept, "confidence", 0.62) or 0.62),
                reliability=0.70,
                privacy_level=str(getattr(percept, "privacy_level", "normal") or "normal"),
                raw_or_inferred="raw",
                tags=("percept", kind, *tuple(str(x) for x in getattr(percept, "evidence", ()) or ())),
            )
        for item in tuple(getattr(snapshot, "evidence", ()) or ()):
            add("telemetry", str(item), confidence=0.62, reliability=0.72, tags=("telemetry", "snapshot"))
        focus = str(getattr(snapshot, "focus_summary", "") or "").strip()
        if focus:
            add("active_window", focus, confidence=0.58, reliability=0.78, tags=("focus", "snapshot"))
        for item in tuple(vision_facts or ()):
            add("vision", str(item), confidence=0.58, reliability=0.62, privacy_level="private", tags=("vision",))
        for item in self._memory_attention_lines()[:5]:
            add("memory", str(item), confidence=0.56, reliability=0.60, privacy_level="private", tags=("memory",))
        return tuple(evidence)
    def _append_working_memory_context(self, memory_context: str, frame: CognitiveFrame) -> str:
        render = getattr(getattr(frame, "working_memory", None), "render_prompt_context", None)
        if not callable(render):
            return memory_context
        try:
            working_context = str(render() or "").strip()
        except Exception as exc:
            self.logger.warning("WorkingMemory prompt render error: %s", exc)
            return memory_context
        if not working_context:
            return memory_context
        return f"{memory_context}\n\n{working_context}".strip() if memory_context else working_context
    def _start_cognitive_frame(
        self,
        *,
        channel: str,
        started_at: float,
        snapshot,
        internal_state_before,
        sensed_internal_state,
        ni_report,
        ti_report,
        fe_plan,
        user_text: str = "",
        vision_facts: tuple[str, ...] = (),
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        force_speak: bool = False,
        memory_resonance=None,
        affect_signal=None,
    ) -> CognitiveFrame:
        if memory_resonance is not None:
            self.active_memory_resonance = memory_resonance
        kernel = getattr(self, "epistemic_kernel", None)
        if kernel is not None and getattr(kernel, "authoritative", False) and sensed_internal_state is not None:
            saved_relationship = kernel.get_projection("relationship").get("state")
            if saved_relationship:
                from cortex.relationship_dynamics import RelationshipDynamicsState
                sensed_internal_state = replace(
                    sensed_internal_state,
                    relationship_dynamics=RelationshipDynamicsState.from_dict(saved_relationship),
                )
        percepts = self._collect_percept_events(
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            vision_facts=vision_facts,
            force_speak=force_speak,
            thought_stream_report=thought_stream_report,
            social_presence_event=social_presence_event,
            started_at=started_at,
        )
        candidates = self._build_attention_candidates(
            percepts,
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
        )
        broadcast = self._build_broadcast(candidates)
        meaning_layer = self._build_meaning_layer(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=sensed_internal_state,
            thought_stream_report=thought_stream_report,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            affect_signal=affect_signal,
            ti_report=ti_report,
            fe_plan=fe_plan,
        )
        personality_lens = self._build_personality_lens(
            snapshot=snapshot,
            broadcast=broadcast,
            internal_state=sensed_internal_state,
            meaning_layer=meaning_layer,
            channel=channel,
            user_text=user_text,
            affect_signal=affect_signal,
            ti_report=ti_report,
            fe_plan=fe_plan,
        )
        fe_plan = self._apply_personality_lens_to_fe_plan(fe_plan, personality_lens)
        appraisal = self._build_cognitive_appraisal(
            internal_state=sensed_internal_state,
            ni_report=ni_report,
            ti_report=ti_report,
            fe_plan=fe_plan,
            broadcast=broadcast,
            channel=channel,
            user_text=user_text,
            force_speak=force_speak,
            personality_lens=personality_lens,
        )
        frame = CognitiveFrame(
            cycle_id=self._next_cognitive_cycle_id(channel),
            channel=channel,
            started_at=started_at,
            percepts=percepts,
            attention_candidates=candidates,
            broadcast=broadcast,
            meaning_layer=meaning_layer,
            personality_lens=personality_lens,
            appraisal=appraisal,
            memory_resonance=memory_resonance if memory_resonance is not None else getattr(self, "active_memory_resonance", None),
            self_state=self.self_model_engine.evaluate(
                channel=channel,
                snapshot=snapshot,
                internal_state=sensed_internal_state,
                ti_report=ti_report,
                broadcast=broadcast,
                user_text=user_text,
                force_speak=force_speak,
            ),
            internal_state_before=internal_state_before,
            internal_state_after=sensed_internal_state,
            social_presence_event=social_presence_event or SocialPresenceEvent(present=False),
        )
        if kernel is not None and getattr(kernel, "authoritative", False):
            self_state_payload = frame.self_state.to_dict() if callable(getattr(frame.self_state, "to_dict", None)) else {}
            kernel.set_projection("self_current", self_state_payload, reason=f"frame:{frame.cycle_id}")
        if thought_stream_report is not None:
            frame.thought_stream_report = thought_stream_report
            frame.subconscious_report = thought_stream_report
        self._run_context_bottleneck(
            frame,
            snapshot=snapshot,
            user_text=user_text,
            vision_facts=vision_facts,
            started_at=started_at,
        )
        self._note_norm_observation(snapshot)
        return frame
    def _set_cognitive_action_plan(
        self,
        frame: CognitiveFrame,
        *,
        should_speak: bool,
        speech_intent: str,
        reason: str,
        snapshot=None,
        user_text: str = "",
        force_speak: bool = False,
        concrete_signals: tuple[str, ...] = (),
        ti_report=None,
        fe_plan=None,
        system_action: str = "",
        speech_act: str = "",
        notes: tuple[str, ...] = (),
        inner_thought: InnerThought | None = None,
    ) -> None:
        proposed_intent = speech_intent or ("brief_ack" if should_speak else "no_speech")
        if (
            getattr(frame, "speech_core", None) is not None
            and (
                frame.channel in {"autonomous", "force_speak"}
                or frame.speech_core.should_speak
                or frame.speech_core.speech_source != "none"
                or frame.speech_core.reason
            )
        ):
            notes = self._merge_speech_core_notes(notes, frame.speech_core)
        if inner_thought is not None:
            frame.inner_thought = inner_thought
            if inner_thought.should_surface and not speech_act:
                speech_act = inner_thought.intent
                if inner_thought.topic_seed:
                    reason = f"{reason} InnerThought: {inner_thought.topic_seed}"
            notes = self._merge_inner_thought_notes(notes, inner_thought)
        notes = self._merge_meaning_layer_notes(notes, getattr(frame, "meaning_layer", None))
        notes = self._merge_personality_lens_notes(notes, getattr(frame, "personality_lens", None))
        notes = self._merge_subconscious_notes(notes, getattr(frame, "subconscious_report", None))
        notes = self._merge_memory_resonance_notes(notes, getattr(frame, "memory_resonance", None))
        internal_state = frame.internal_state_after or frame.internal_state_before or self._get_internal_state()
        frame.action_plan = self.action_planner.plan(
            channel=frame.channel,
            snapshot=snapshot,
            ti_report=ti_report,
            fe_plan=fe_plan,
            appraisal=frame.appraisal,
            broadcast=frame.broadcast,
            user_text=user_text,
            force_speak=force_speak,
            proposed_intent=proposed_intent,
            proposed_reason=reason,
            proposed_speech_act=speech_act,
            system_action=system_action,
            notes=tuple(notes),
            concrete_signals=tuple(concrete_signals or ()),
            self_state=frame.self_state,
            speech_core=frame.speech_core,
            conversation_dynamics=getattr(internal_state, "conversation_dynamics", None),
            relationship_dynamics=getattr(internal_state, "relationship_dynamics", None),
            goal_state=getattr(internal_state, "goal_persistence", None),
            action_memory=getattr(internal_state, "action_memory", None),
            auto_record_local_memory=False,
        )
        kernel = getattr(self, "epistemic_kernel", None)
        if kernel is not None:
            try:
                from .epistemic_bridge import prepare_authoritative_action
                prepare_authoritative_action(kernel, frame)
            except Exception as exc:
                self.logger.warning("Epistemic V2 action selection failed: %s", exc, exc_info=True)
        self._apply_micro_line_policy_to_action_plan(
            frame,
            vision_fact=str((tuple(concrete_signals or ()) or ("",))[0] or ""),
        )
    def _apply_micro_line_policy_to_action_plan(self, frame: CognitiveFrame, *, vision_fact: str = "") -> None:
        action_plan = frame.action_plan
        user_action_hint, session_context_hint = self._micro_policy_anchor_hints(
            broadcast=frame.broadcast,
            snapshot=None,
        )
        policy = self.micro_line_policy.evaluate(
            speech_intent=action_plan.speech_intent,
            broadcast=frame.broadcast,
            vision_fact=vision_fact,
            user_action=user_action_hint,
            session_context=session_context_hint,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=frame.channel,
        )
        notes = list(action_plan.notes or ())
        notes.append(f"micro_line_type={policy.allowed_line_type}")
        notes.append(f"micro_signal_score={policy.signal_score:.2f}")
        notes.append(f"micro_risk_level={policy.risk_level}")
        flags = list(action_plan.risk_flags or ())
        for reason in policy.reject_reasons:
            flags.append(f"micro_policy_reject={reason}")
        if "no_speech_blocks_final" in policy.reject_reasons:
            action_plan.should_speak = False
            action_plan.speech_intent = "no_speech"
            action_plan.speech_act = "no_speech"
            action_plan.reason_to_speak = "MicroLinePolicy returned no_speech for a repeated or blocked micro line."
            action_plan.reason = action_plan.reason_to_speak
        action_plan.notes = tuple(dict.fromkeys(str(item) for item in notes if str(item or "").strip()))
        action_plan.risk_flags = tuple(dict.fromkeys(str(item) for item in flags if str(item or "").strip()))
    def _micro_policy_anchor_hints(self, *, broadcast=None, snapshot=None) -> tuple[str, str]:
        user_action = ""
        session_context = ""
        if broadcast is not None:
            for item in (broadcast, *tuple(getattr(broadcast, "items", ()) or ())):
                label = str(getattr(item, "label", "") or "").strip().lower()
                content = str(getattr(item, "content", "") or "").strip()
                if not content:
                    continue
                if not user_action and label in {"user_action", "action_context", "recent_event"}:
                    user_action = content
                if not session_context and label in {"focus_context", "session_context", "active_window", "focus_summary"}:
                    session_context = content
        if snapshot is not None:
            if not user_action:
                recent_events = tuple(
                    str(item or "").strip().replace("_", " ")
                    for item in (getattr(snapshot, "recent_events", ()) or ())
                    if str(item or "").strip()
                )
                user_action = next((item for item in recent_events if item), "")
            if not session_context:
                session_context = str(
                    getattr(snapshot, "focus_summary", "")
                    or getattr(snapshot, "active_window", "")
                    or getattr(snapshot, "active_app", "")
                    or getattr(snapshot, "active_window_kind", "")
                    or ""
                ).strip()
        return user_action, session_context
    def _build_relational_context(self, state: PersistentInternalState | None = None) -> RelationalContext:
        state = state or self._get_internal_state()
        recent_notes = " ".join(str(item or "") for item in tuple(getattr(state, "recent_notes", ()) or ())).lower()
        mental_processes = getattr(state, "mental_processes", None)
        continuity_process = getattr(mental_processes, "continuity", None)
        session_return = min(1.0, max(0, int(getattr(state, "session_resume_count", 0) or 0)) / 2.0)
        ritual_return = 1.0 if float(getattr(state, "last_session_ritual_at", 0.0) or 0.0) > 0.0 else 0.0
        memory_continuity = max(
            float(getattr(state, "recursive_reactivation_pressure", 0.0) or 0.0),
            float(getattr(state, "memory_replay_pressure", 0.0) or 0.0),
            float(getattr(state, "last_memory_resonance", 0.0) or 0.0),
            float(getattr(continuity_process, "level", 0.0) or 0.0),
        )
        ritual_note = 1.0 if any(
            marker in recent_notes
            for marker in ("session_ritual", "continuity_restored", "long_silence_return", "memory_replay", "recursive")
        ) else 0.0
        recent_channels = tuple(str(item or "") for item in tuple(getattr(state, "recent_channels", ()) or ()))
        long_silence_return = 1.0 if (
            float(getattr(state, "last_elapsed_seconds", 0.0) or 0.0) >= 600.0
            and any(item in {"chat", "force_speak"} for item in recent_channels[-4:])
        ) else 0.0
        sustained_presence = min(
            1.0,
            (
                float(getattr(state, "last_social_presence_confidence", 0.0) or 0.0)
                + float(getattr(state, "last_social_presence_intensity", 0.0) or 0.0)
            )
            * 0.5,
        )
        continuity_score = min(
            1.0,
            session_return * 0.28
            + ritual_return * 0.18
            + memory_continuity * 0.34
            + ritual_note * 0.12
            + long_silence_return * 0.10
            + sustained_presence * 0.08,
        )
        attachment = float(getattr(state, "attachment", 0.0) or 0.0)
        if continuity_score >= 0.66 and attachment >= 0.62:
            stage = "rooted"
        elif continuity_score >= 0.52 and attachment >= 0.50:
            stage = "established"
        elif continuity_score >= 0.38:
            stage = "forming"
        else:
            stage = "low_context"
        return RelationalContext(
            attachment_level=attachment,
            continuity_score=continuity_score,
            social_resonance=float(getattr(state, "social_energy", 0.0) or 0.0),
            recent_presence_density=sustained_presence,
            abandonment_sensitivity=max(
                float(getattr(state, "silence_pressure", 0.0) or 0.0),
                float(getattr(getattr(state, "desire", None), "unresolved_residue", 0.0) or 0.0),
            ),
            trust_stability=max(
                0.0,
                min(1.0, float(getattr(state, "confidence", 0.0) or 0.0) - float(getattr(state, "irritation", 0.0) or 0.0) * 0.35),
            ),
            relationship_stage=stage,
        )
    def _speech_intent_from_core(self, speech_core: AgentSpeechCore, *, channel: str) -> str:
        if not speech_core.should_speak:
            return "no_speech"
        if channel == "chat":
            return "user_requested"
        if speech_core.utterance_type in {"telemetry_comment", "vision_comment"}:
            return "screen_observation"
        if speech_core.utterance_type == "micro_observation":
            return "micro_observation"
        if speech_core.utterance_type == "micro_presence":
            return "micro_presence"
        if speech_core.utterance_type == "curious_question":
            return "curious_question"
        if speech_core.utterance_type == "guarded_reply":
            return "guarded_reply"
        if speech_core.utterance_type == "indirect_presence":
            return "indirect_presence"
        if speech_core.utterance_type in {"inner_whim", "random_chatter", "light_muse", "soft_boundary"}:
            if channel == "force_speak":
                return "micro_presence"
            # soft_boundary không nằm trong SPEECH_INTENTS công khai nên giữ ở
            # social_presence; còn lại để autonomous giữ đúng bản sắc "nói nhảm /
            # ngẫu hứng / muse nhẹ" thay vì bị làm phẳng thành social_presence.
            if speech_core.utterance_type == "soft_boundary":
                return "social_presence"
            return speech_core.utterance_type
        if channel == "force_speak":
            return "user_requested"
        return "brief_ack"
    def _merge_speech_core_notes(
        self,
        notes: tuple[str, ...],
        speech_core: AgentSpeechCore,
    ) -> tuple[str, ...]:
        merged = list(notes or ())
        if speech_core.speech_source:
            merged.append(f"speech_source={speech_core.speech_source}")
        if speech_core.grounding:
            merged.append(f"grounding={speech_core.grounding}")
        if getattr(speech_core, "speech_risk_level", ""):
            merged.append(f"speech_risk_level={speech_core.speech_risk_level}")
        if speech_core.delivery:
            merged.append(f"delivery={speech_core.delivery}")
        silence = getattr(speech_core, "silence_state", None)
        if silence is not None and getattr(silence, "intentional_withholding", False):
            merged.append(f"silence_state={getattr(silence, 'mode', '') or 'intentional_withholding'}")
            for label, value in (
                ("suppressed_thought", getattr(silence, "suppressed_thought", "")),
                ("almost_spoke", getattr(silence, "almost_spoke", "")),
                ("unfinished_impulse", getattr(silence, "unfinished_impulse", "")),
                ("internal_hesitation", getattr(silence, "internal_hesitation", "")),
            ):
                if value:
                    merged.append(f"{label}={value}")
        if speech_core.reason:
            merged.append(f"speech_core_reason={speech_core.reason}")
        impulse = getattr(speech_core, "speech_impulse", None)
        if impulse is not None:
            reaction = str(getattr(impulse, "reaction", "") or "")
            mood_residue = str(getattr(impulse, "mood_residue", "") or "")
            reaction_impulse = str(getattr(impulse, "reaction_impulse", "") or "")
            pressure = float(getattr(impulse, "emotional_pressure", 0.0) or 0.0)
            if mood_residue:
                merged.append(f"mood_residue={mood_residue}")
            if reaction_impulse:
                merged.append(f"reaction_impulse={reaction_impulse}")
            if pressure:
                merged.append(f"emotional_pressure={pressure:.2f}")
            if reaction:
                merged.append(f"speech_impulse_reaction={reaction}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
    def _merge_meaning_layer_notes(self, notes: tuple[str, ...], meaning_layer) -> tuple[str, ...]:
        merged = list(notes or ())
        if meaning_layer is None:
            return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
        family = str(getattr(meaning_layer, "semantic_family", "") or "")
        shift_reason = str(getattr(meaning_layer, "shift_reason", "") or "")
        reaction = str(getattr(meaning_layer, "reaction", "") or "")
        mood_residue = str(getattr(meaning_layer, "mood_residue", "") or "")
        reaction_impulse = str(getattr(meaning_layer, "reaction_impulse", "") or "")
        pressure = float(getattr(meaning_layer, "emotional_pressure", 0.0) or 0.0)
        if family:
            merged.append(f"internal_family={family}")
        if shift_reason:
            merged.append(f"meaning_shift={shift_reason}")
        if mood_residue:
            merged.append(f"mood_residue={mood_residue}")
        if reaction_impulse:
            merged.append(f"reaction_impulse={reaction_impulse}")
        if pressure:
            merged.append(f"emotional_pressure={pressure:.2f}")
        if reaction:
            merged.append(f"meaning_reaction={reaction}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
    def _merge_memory_resonance_notes(self, notes: tuple[str, ...], memory_resonance) -> tuple[str, ...]:
        merged = list(notes or ())
        if memory_resonance is None:
            return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
        layer = str(getattr(memory_resonance, "dominant_layer", "") or "")
        try:
            score = float(getattr(memory_resonance, "score", 0.0) or 0.0)
            silence = float(getattr(memory_resonance, "silence_bias", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
            silence = 0.0
        if score > 0.0:
            merged.append(f"memory_resonance={layer or 'none'}:{score:.2f}")
        if silence >= 0.35:
            merged.append(f"memory_silence_bias={silence:.2f}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
    def _merge_inner_thought_notes(self, notes: tuple[str, ...], inner_thought: InnerThought) -> tuple[str, ...]:
        merged = list(notes or ())
        if inner_thought.intent:
            merged.append(f"inner_thought={inner_thought.intent}")
        if inner_thought.motive:
            merged.append(f"inner_motive={inner_thought.motive}")
        if inner_thought.topic_seed:
            merged.append(f"inner_seed={inner_thought.topic_seed}")
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
    def _merge_personality_lens_notes(self, notes: tuple[str, ...], personality_lens) -> tuple[str, ...]:
        merged = list(notes or ())
        if personality_lens is None:
            return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
        interpretation = str(getattr(personality_lens, "interpretation", "") or "")
        stance = str(getattr(personality_lens, "stance", "") or "")
        distance = str(getattr(personality_lens, "social_distance", "") or "")
        rhythm = str(getattr(personality_lens, "rhythm", "") or "")
        restraint_mode = str(getattr(personality_lens, "restraint_mode", "") or "")
        try:
            want_to_say = float(getattr(personality_lens, "want_to_say", 0.0) or 0.0)
            allowed_expression = float(getattr(personality_lens, "allowed_expression", 0.0) or 0.0)
            suppression_pressure = float(getattr(personality_lens, "suppression_pressure", 0.0) or 0.0)
        except (TypeError, ValueError):
            want_to_say = allowed_expression = suppression_pressure = 0.0
        if interpretation:
            merged.append(f"personality_interpretation={interpretation}")
        if stance:
            merged.append(f"personality_stance={stance}")
        if distance:
            merged.append(f"social_distance={distance}")
        if rhythm:
            merged.append(f"rhythm={rhythm}")
        if restraint_mode:
            merged.append(f"restraint_mode={restraint_mode}")
        merged.append(f"expression_gate={want_to_say:.2f}->{allowed_expression:.2f}")
        merged.append(f"suppression_pressure={suppression_pressure:.2f}")
        merged.append("suppression_layer=inner_restraint")
        # Nước 1 — van bước-cuối: lưu lại expression gate để post-generation
        # đo "phẳng dưới biểu đạt cao". Chỉ là cache nhẹ, không đổi hành vi cũ.
        try:
            self._last_expression_gate = {
                "want_to_say": want_to_say,
                "allowed_expression": allowed_expression,
                "suppression_pressure": suppression_pressure,
                "stance": stance,
            }
        except Exception:
            pass
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
    def _merge_subconscious_notes(self, notes: tuple[str, ...], subconscious_report) -> tuple[str, ...]:
        merged = list(notes or ())
        seed = getattr(subconscious_report, "latest_seed", None)
        mode = str(getattr(seed, "mode", "") or "")
        topic_seed = str(getattr(seed, "topic_seed", "") or "")
        thought = getattr(subconscious_report, "latest_thought", None)
        momentum = getattr(subconscious_report, "momentum", None)
        thought_id = str(getattr(thought, "thought_id", "") or getattr(seed, "thought_id", "") or "")
        tension = getattr(subconscious_report, "stream_tension", 0.0)
        if mode:
            merged.append(f"thought_surface_mode={mode}")
            merged.append(f"subconscious_mode={mode}")
        if topic_seed:
            merged.append(f"thought_surface={topic_seed}")
            merged.append(f"subconscious_seed={topic_seed}")
        if thought_id:
            merged.append(f"thought_id={thought_id}")
        try:
            if float(tension or 0.0) > 0.0:
                merged.append(f"cognitive_tension={float(tension):.2f}")
        except (TypeError, ValueError):
            pass
        try:
            momentum_score = float(getattr(momentum, "score", 0.0) if momentum is not None else 0.0)
            if momentum_score > 0.0:
                merged.append(f"cognitive_momentum={momentum_score:.2f}")
                affordance = str(getattr(momentum, "affordance", "") or "")
                if affordance:
                    merged.append(f"momentum_affordance={affordance}")
        except (TypeError, ValueError):
            pass
        return tuple(dict.fromkeys(str(item) for item in merged if str(item or "").strip()))
    def _is_inner_thought_speech_act(self, speech_act: str) -> bool:
        return speech_act in {
            "meta_reply",
            "random_chatter",
            "inner_whim",
            "curious_question",
            "relational_checkin",
            "light_muse",
            "soft_boundary",
        }

        if getattr(self, "_session_ritual_ran", False):
            return SessionRitualReport(restored=False, session_resumed=False, should_greet=False)
        self._session_ritual_ran = True

        self._ensure_internal_state()
        internal_state = self._get_internal_state()
        self.logger.info("[session_ritual] collecting startup context")

        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=self.mood_score,
            inferred_pos_x=self.inferred_pos_x,
        )
        thought_stream_report = (
            self.cognitive_substrate.latest_report()
            if callable(getattr(self.cognitive_substrate, "latest_report", None))
            else ThoughtStreamReport()
        )
        social_presence_event = self._detect_social_presence_event(
            channel="autonomous",
            snapshot=snapshot,
            internal_state=internal_state,
            started_at=time.time(),
        )
        report = self.session_ritual_engine.evaluate(
            snapshot=snapshot,
            internal_state=internal_state,
            thought_stream_report=thought_stream_report,
            social_presence_event=social_presence_event,
        )
        self.logger.info(
            "[session_ritual] report restored=%s | presence=%s | continuity=%s | greet=%s | tone=%s",
            int(bool(report.restored)),
            int(bool(report.presence_restored)),
            int(bool(report.continuity_restored)),
            int(bool(report.should_greet)),
            report.tone,
        )

        if report.should_greet:
            self.logger.info("[session_ritual] generating startup greeting")
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._recall_memory_resonance(
                snapshot=snapshot,
                channel="session_ritual",
                fragments=tuple(
                    item
                    for item in (
                        report.active_goal,
                        report.current_attractor,
                        report.recent_cognition_direction,
                        report.self_continuity,
                        *tuple(report.unresolved_loops or ()),
                    )
                    if str(item or "").strip()
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
            ni_report = self.ni_engine.evaluate_autonomous(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                last_text=self.last_text,
                goal_state=getattr(internal_state, "goal_persistence", None),
            )
            ti_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
            ti_report = self.ti_governor.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ni_state_label=ti_view["discrete_state"],
                ni_state_streak=ti_view["streak_length"],
                idle_cycles=self.idle_cycles,
                last_text=self.last_text,
            )
            fe_plan = self.fe_renderer.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                internal_state=internal_state,
                last_text=self.last_text,
            )
            greeting_source = "llm"
            try:
                raw = self.llm_service.generate_directive(
                    telemetry_data=self._build_speech_evidence_context(snapshot),
                    ni_context=str(getattr(ni_report, "prompt_context", "") or ""),
                    ti_context=self._build_session_ritual_ti_context(report, snapshot),
                    fe_context=fe_plan.style_context,
                    appraisal_context="session_ritual: startup greeting; express current attitude without reporting telemetry.",
                    internal_state_context=self._build_internal_state_context(internal_state),
                    memory_context=memory_context,
                    avoid_text=self.last_text,
                    speech_intent="session_ritual",
                    vision_trace_marker="session_ritual",
                )
                self._log_raw_llm_output("session_ritual", raw)
                decision = self.parser.parse(raw)
            except Exception as exc:
                self.logger.warning("[session_ritual] LLM greeting failed: %s", exc)
                greeting_source = "fallback_after_llm_error"
                # Bỏ câu chào canned — degrade về IM thay vì template cố định.
                decision = Decision(
                    text="",
                    animation="stand",
                    should_speak=False,
                    debug_trace="session_ritual_layer; fallback=silent_no_template",
                )
            if not decision.text.strip():
                greeting_source = "fallback_after_empty_llm"
                decision = Decision(
                    text="",
                    animation="stand",
                    should_speak=False,
                    debug_trace="session_ritual_layer; fallback=silent_no_template",
                )
            if decision.text.strip():
                decision.intent = decision.intent or "session_ritual"
                decision.reasoning_tags = tuple(dict.fromkeys((*decision.reasoning_tags, "session_ritual", "startup_greeting")))
                decision.should_speak = True
                decision.confidence = decision.confidence or 0.72
                decision.parse_mode = "session_ritual"
                decision.debug_trace = (
                    f"{decision.debug_trace} | session_ritual_layer; source={greeting_source}; tone={report.tone}"
                    if decision.debug_trace
                    else f"session_ritual_layer; source={greeting_source}; tone={report.tone}"
                )
                self.fe_style_memory = self.fe_renderer.remember_style(
                    self.fe_style_memory,
                    plan=fe_plan,
                    rendered_text=decision.text,
                )
                self.last_text = decision.text
                spoken_at = time.time()
                self._note_autonomous_spoken(now=spoken_at)
                block_fn = getattr(self, "_block_autonomous_presence_after_public_turn", None)
                if callable(block_fn):
                    block_fn(now=spoken_at)
                self.logger.info('[session_ritual] sent LLM greeting text="%s"', decision.text)
                self._send_decision_to_body(decision)

        updated_state = self.internal_state_engine.commit_session_ritual(
            internal_state,
            session_ritual=report,
        )
        self._set_internal_state(updated_state)
        if self.memory_state is not None:
            self._save_memory_state()

        return report
