# -*- coding: utf-8 -*-
"""Social Initiative Worker cho autonomous speech của ERIS.

Quyền được tách theo ownership thật:

- worker ``seed`` chạy nền trên DS2API port riêng và tích lũy premise typed;
- agenda selector chỉ xử lý các lane có cấu trúc khác;
- runtime giữ privacy/turn collision; self-rhythm điều tiết mật độ, không suy user-busy thành boundary;
- worker ``surface`` chỉ viết câu cuối sau khi candidate đã được duyệt.

Random chat không gọi model trên critical path. Kho seed trống thì ERIS im và
producer tiếp tục nạp nền, thay vì giật một worker khác sang phát câu điểm danh.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .affordance import ExecutiveAffordance
from .cognitive_blackboard import CognitiveAnchor, TypedCognitiveBlackboard
from .random_chat_seed import assess_seed_quality
from .random_chat_seed_service import RandomChatSeedReservoir, build_seed_temporal_context
from cortex.subject.expression_commitment import commitment_payload


CANDIDATE_SCHEMA = "eris.social_speech_candidate.v1"


def _compact(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _autonomous_expression_policy() -> dict[str, Any]:
    """Đọc explicit output boundary + self-rhythm settings; không cấp quyền nói."""
    try:
        from runtime.runtime_settings_store import runtime_bool, runtime_float
        enabled = runtime_bool("commentary", "autonomous_expression_enabled", default=True)
        return {
            "enabled": enabled,
            "surface_only": runtime_bool("commentary", "surface_only", default=True),
            "open_topic": runtime_bool("commentary", "open_topic", default=True),
            "desired": runtime_float("commentary", "desired_interval_seconds", default=35.0),
            "maximum": runtime_float("commentary", "maximum_quiet_seconds", default=70.0),
        }
    except Exception:
        return {"enabled": True, "surface_only": True, "open_topic": True, "desired": 35.0, "maximum": 70.0}


_ALLOWED_KINDS = {
    "continuation",
    "conversation_arc",
    "afterbeat",
    "social_exposure_recovery",
    "social_agenda",
    "followup_reminder",
    "task_followup",
    "discovery_share",
    "screen_comment",
    "semantic_scene",
    "memory_callback",
    "inner_thought",
    "social_check_in",
    "relational_initiative",
    "casual_curiosity",
    "playful_prompt",
    "random_chat",
    "capability_statement",
    "grounded_tool_finding",
}

_SOCIAL_KINDS = {"social_check_in", "casual_curiosity", "playful_prompt", "random_chat"}


@dataclass(frozen=True, slots=True)
class SocialSpeechCandidate:
    """Một ý định trò chuyện do model đề xuất, chưa có quyền phát ra.

    ``topic`` là mục tiêu giao tiếp, không phải câu public. Runtime không sửa topic
    để biến candidate thành ý khác; nó chỉ approve/defer/reject candidate này.
    """

    decision: str = "none"
    kind: str = "random_chat"
    topic: str = ""
    speech_act: str = "social_check_in"
    anchor_type: str = "idle"
    anchor_id: str = "shared_quiet"
    evidence_refs: tuple[str, ...] = ()
    requires_grounding: bool = False
    confidence: float = 0.0
    relevance: float = 0.0
    urgency: float = 0.0
    tone: str = "casual_warm"
    reason: str = ""
    source: str = "surface_initiative_worker"
    continuation_lane: str = ""
    claim_token: str = ""
    idempotency_key: str = ""
    seed_id: str = ""
    seed_mode: str = ""
    source_kind: str = ""
    topic_tags: tuple[str, ...] = ()
    seed_event_kind: str = "thought"
    seed_epistemic_mode: str = "opinion"
    seed_open_loop: bool = False
    desired_response: tuple[str, ...] = ()
    eris_motive_kind: str = ""
    eris_motive_why_now: str = ""
    personal_stake: float = 0.0
    authenticity: float = 0.0
    daring: float = 0.0
    uncertainty: float = 0.0
    seed_intrusion_risk: float = 0.0
    face_risk: float = 0.0
    recovery_available: bool = False
    seed_lease_token: str = ""
    seed_generated_at: float = 0.0
    seed_expires_at: float = 0.0
    seed_ttl_seconds: float = 600.0
    seed_quality_score: float = 0.0
    seed_specificity: float = 0.0
    seed_motive_strength: float = 0.0
    seed_semantic_completeness: float = 0.0
    seed_temporal_context: Mapping[str, Any] = field(default_factory=dict)
    # V70: private-rumination provenance. Không phải evidence/current-world claim.
    semantic_development_mode: str = ""
    semantic_development_score: float = 0.0
    semantic_development_required: bool = False
    rumination_return: bool = False
    semantic_parent_concern_id: str = ""
    # V44: desire có nội dung. Các field này chỉ là projection trước Neuro;
    # chúng không phải lệnh speak và không được Surface tự sửa.
    expression_urge_id: str = ""
    expression_pressure: float = 0.0
    expression_freshness: float = 0.0
    expression_satisfaction: float = 0.0
    expression_motive: str = ""
    # V67: semantic identity typed của một public expression đã được Eris commit.
    # Candidate có thể tồn tại trước commitment (opportunity/thought), nhưng chỉ
    # candidate mang payload này mới được phép bước vào public proposal lane.
    expression_commitment: Mapping[str, Any] = field(default_factory=dict)

    @property
    def random_chat_seed(self) -> dict[str, Any]:
        if not self.seed_id:
            return {}
        return {
            "schema": "eris.random_chat_seed.v1",
            "decision": "seed",
            "seed_id": self.seed_id,
            "mode": self.seed_mode,
            "premise": self.topic,
            "source_kind": self.source_kind,
            "source_refs": list(self.evidence_refs),
            "topic_tags": list(self.topic_tags),
            "event_kind": self.seed_event_kind,
            "epistemic_mode": self.seed_epistemic_mode,
            "open_loop": self.seed_open_loop,
            "opening_move": self.speech_act,
            "desired_response": list(self.desired_response),
            "eris_motive": {
                "kind": self.eris_motive_kind,
                "why_now": self.eris_motive_why_now,
                "personal_stake": self.personal_stake,
                "authenticity": self.authenticity,
            },
            "risk": {
                "daring": self.daring,
                "uncertainty": self.uncertainty,
                "intrusion_risk": self.seed_intrusion_risk,
                "face_risk": self.face_risk,
                "recovery_available": self.recovery_available,
            },
            "estimated_fit": self.relevance,
            "confidence": self.confidence,
            "tone": self.tone,
            "ttl_seconds": self.seed_ttl_seconds,
            "quality": {
                "score": self.seed_quality_score,
                "specificity": self.seed_specificity,
                "motive_strength": self.seed_motive_strength,
                "semantic_completeness": self.seed_semantic_completeness,
            },
            # Late-bound at materialization time, never copied from generation.
            "temporal_context": dict(self.seed_temporal_context),
            "claim_contract": {
                "runtime_clock_is_evidence_for": ["local_time", "local_date", "weekday", "daypart_by_clock"],
                "current_environment_requires_direct_evidence": True,
                "clock_never_proves": [
                    "weather", "ambient_sound", "room_lighting", "outdoor_lighting",
                    "user_activity", "user_emotion", "user_fatigue",
                ],
                "surface_may_not_add_new_current_world_premises": True,
            },
        }

    @property
    def available(self) -> bool:
        if self.kind == "force_speak" and self.decision in {"speak", "candidate"}:
            return True
        return self.decision == "candidate" and self.kind in _ALLOWED_KINDS and bool(self.topic)

    @property
    def social(self) -> bool:
        return self.kind in _SOCIAL_KINDS

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = CANDIDATE_SCHEMA
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None, *, source: str = "surface_initiative_worker") -> "SocialSpeechCandidate":
        data = payload or {}
        decision = _compact(data.get("decision", "none"), 24).lower() or "none"
        if decision not in {"candidate", "none"}:
            decision = "none"
        kind = _compact(data.get("kind", "random_chat"), 48).lower() or "random_chat"
        if kind not in _ALLOWED_KINDS:
            kind = "random_chat"
        refs = tuple(
            item for item in (_compact(value, 140) for value in _sequence(data.get("evidence_refs"))[:6]) if item
        )
        requires_grounding = bool(data.get("requires_grounding", False) or kind == "screen_comment")
        return cls(
            decision=decision,
            kind=kind,
            topic=_compact(data.get("topic", ""), 300),
            speech_act=_compact(data.get("speech_act", kind), 64).lower() or kind,
            anchor_type=_compact(data.get("anchor_type", "idle"), 40).lower() or "idle",
            anchor_id=_compact(data.get("anchor_id", "shared_quiet"), 120) or "shared_quiet",
            evidence_refs=refs,
            requires_grounding=requires_grounding,
            confidence=_clamp01(data.get("confidence", 0.0)),
            relevance=_clamp01(data.get("relevance", 0.0)),
            urgency=_clamp01(data.get("urgency", 0.0)),
            tone=_compact(data.get("tone", "casual_warm"), 48).lower() or "casual_warm",
            reason=_compact(data.get("reason", ""), 240),
            source=source,
            continuation_lane=_compact(data.get("continuation_lane", ""), 48).lower(),
            claim_token=_compact(data.get("claim_token", ""), 180),
            idempotency_key=_compact(data.get("idempotency_key", ""), 180),
            seed_id=_compact(data.get("seed_id", ""), 80),
            seed_mode=_compact(data.get("seed_mode", ""), 24).lower(),
            source_kind=_compact(data.get("source_kind", ""), 40).lower(),
            topic_tags=tuple(
                item for item in (_compact(value, 48).lower() for value in _sequence(data.get("topic_tags"))[:8]) if item
            ),
            desired_response=tuple(
                item for item in (_compact(value, 64).lower() for value in _sequence(data.get("desired_response"))[:6]) if item
            ),
            eris_motive_kind=_compact(data.get("eris_motive_kind", ""), 40).lower(),
            eris_motive_why_now=_compact(data.get("eris_motive_why_now", ""), 220),
            personal_stake=_clamp01(data.get("personal_stake", 0.0)),
            authenticity=_clamp01(data.get("authenticity", 0.0)),
            daring=_clamp01(data.get("daring", 0.0)),
            uncertainty=_clamp01(data.get("uncertainty", 0.0)),
            seed_intrusion_risk=_clamp01(data.get("seed_intrusion_risk", 0.0)),
            face_risk=_clamp01(data.get("face_risk", 0.0)),
            recovery_available=bool(data.get("recovery_available", False)),
            semantic_development_mode=_compact(data.get("semantic_development_mode", ""), 24).lower(),
            semantic_development_score=_clamp01(data.get("semantic_development_score", 0.0)),
            semantic_development_required=bool(data.get("semantic_development_required", False)),
            rumination_return=bool(data.get("rumination_return", False)),
            semantic_parent_concern_id=_compact(data.get("semantic_parent_concern_id", ""), 120),
            seed_lease_token=_compact(data.get("seed_lease_token", ""), 120),
            seed_generated_at=float(data.get("seed_generated_at", 0.0) or 0.0),
            seed_expires_at=float(data.get("seed_expires_at", 0.0) or 0.0),
            seed_ttl_seconds=max(60.0, min(1800.0, float(data.get("seed_ttl_seconds", 600.0) or 600.0))),
            seed_quality_score=_clamp01(data.get("seed_quality_score", 0.0)),
            seed_specificity=_clamp01(data.get("seed_specificity", 0.0)),
            seed_motive_strength=_clamp01(data.get("seed_motive_strength", 0.0)),
            seed_semantic_completeness=_clamp01(data.get("seed_semantic_completeness", 0.0)),
            seed_temporal_context=dict(data.get("seed_temporal_context", {})) if isinstance(data.get("seed_temporal_context"), Mapping) else {},
            expression_urge_id=_compact(data.get("expression_urge_id", ""), 96),
            expression_pressure=_clamp01(data.get("expression_pressure", 0.0)),
            expression_freshness=_clamp01(data.get("expression_freshness", 0.0)),
            expression_satisfaction=_clamp01(data.get("expression_satisfaction", 0.0)),
            expression_motive=_compact(data.get("expression_motive", ""), 32).lower(),
            expression_commitment=(
                dict(data.get("expression_commitment", {}))
                if isinstance(data.get("expression_commitment"), Mapping) else {}
            ),
        )


class SocialInitiativeEngine:
    """Cho DeepSeek quyền đề xuất chủ đề; không cho nó quyền tự phát ngôn."""

    def __init__(
        self,
        router: Any,
        *,
        seed_reservoir: RandomChatSeedReservoir | None = None,
        logger: Any | None = None,
    ) -> None:
        self.router = router
        self.seed_reservoir = seed_reservoir
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.router, "surface_client", None) is not None)

    def propose_options(
        self,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> tuple[SocialSpeechCandidate, ...]:
        """Compatibility view over the collect-before-claim API.

        No source is leased here.  Production code must pass the corresponding
        :class:`ExecutiveAffordance` objects to the Executive and claim exactly
        the selected ID afterwards.
        """

        return tuple(
            affordance.candidate
            for affordance in self.collect_affordances(blackboard, snapshot=snapshot)
            if affordance.available
        )

    def propose(
        self,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> SocialSpeechCandidate | None:
        """Compatibility single-candidate view with no reservation authority."""

        affordances = self.collect_affordances(blackboard, snapshot=snapshot)
        return affordances[0].candidate if affordances else None

    def collect_affordances(
        self,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutiveAffordance, ...]:
        """Collect every currently meaningful social move without claiming it.

        ``reply_expected`` chỉ mô tả mạch hội thoại để tránh nag/lặp câu hỏi;
        nó không phải hard boundary. Chỉ turn collision/interaction đang hoạt động
        mới được giữ public floor ở downstream.
        """

        # V66: telemetry ``user_busy`` không phải social boundary. Affordance vẫn
        # được materialize; hard turn collision/boundary sẽ được xử lý bởi owner
        # native của expression commitment.

        revision = max(1, int(float(blackboard.now or 0.0) * 1000.0))
        found: list[ExecutiveAffordance] = []
        seen: set[tuple[str, str, str]] = set()

        def add(candidate: SocialSpeechCandidate | None, *, owner: str) -> None:
            if candidate is None or not candidate.available:
                return
            key = (candidate.kind, candidate.anchor_id, candidate.topic)
            if key in seen:
                return
            seen.add(key)
            found.append(
                ExecutiveAffordance(
                    affordance_id=(
                        f"social:{owner}:{candidate.kind}:{candidate.anchor_id}:{revision}"
                    ),
                    owner=owner,
                    revision=revision,
                    candidate=candidate,
                    claim_required=False,
                    metadata={
                        "reply_expected": bool(blackboard.reply_expected),
                        "engagement_active": bool(blackboard.engagement_active),
                    },
                )
            )

        if getattr(blackboard, "force_speak_pending", False):
            add(
                SocialSpeechCandidate(
                    decision="speak",
                    kind="force_speak",
                    topic="Respond to the explicit request for presence with one short grounded line.",
                    speech_act="presence_response",
                    anchor_type="presence",
                    anchor_id="force_speak",
                    confidence=1.0,
                    relevance=1.0,
                    urgency=1.0,
                    reason="explicit_user_pull",
                    source="runtime_presence_request",
                    expression_commitment=commitment_payload(
                        origin="force_speak",
                        source_id="force_speak",
                        semantic_target="Respond to the explicit request for presence with one short grounded line.",
                        motive="force_expression",
                        pressure=1.0,
                        freshness=1.0,
                        persistence=1.0,
                        forced=True,
                    ),
                ),
                owner="runtime_presence_request",
            )

        # These are independent affordances.  None receives priority merely by
        # appearing first in a Python function.
        add(self._followup_reminder_candidate(blackboard), owner="followup_appraisal")
        add(self._abandoned_topic_shift_candidate(blackboard), owner="followup_appraisal")
        add(self._task_followup_candidate(blackboard, reason="typed_task_event"), owner="engagement_runtime")
        add(self._semantic_scene_candidate(blackboard, reason="typed_semantic_scene"), owner="semantic_context")

        surface_policy = _autonomous_expression_policy()
        soft_default = float(surface_policy.get("desired", 35.0)) if surface_policy.get("enabled") else 180.0
        soft = _env_float(
            "ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC",
            soft_default,
            minimum=20.0,
            maximum=3600.0,
        )
        # V66: opportunity clock thuộc nhịp của Eris. User im lâu không phải
        # nguyên nhân sinh expression và user vừa nói cũng không phải lý do cấm nó.
        social_opportunity_due = bool(
            blackboard.commentary_due
            or blackboard.seconds_since_assistant >= soft
        )

        if self._has_structured_opportunity(blackboard):
            add(
                self._structured_model_candidate(
                    blackboard,
                    snapshot=snapshot or {},
                    surface_policy=surface_policy,
                ),
                owner="deepseek_social_initiative",
            )

        if social_opportunity_due:
            seed_affordance = self._random_chat_seed_affordance(blackboard)
            if seed_affordance is not None:
                seed_key = (
                    seed_affordance.candidate.kind,
                    seed_affordance.candidate.anchor_id,
                    seed_affordance.candidate.topic,
                )
                if seed_key not in seen:
                    seen.add(seed_key)
                    found.append(seed_affordance)

        return tuple(found)

    def claim_affordance(
        self,
        affordance: ExecutiveAffordance,
        *,
        now: float | None = None,
    ) -> SocialSpeechCandidate | None:
        """Claim exactly the affordance selected by the Executive."""

        if not affordance.available:
            return None
        if affordance.owner != "random_chat_seed":
            return affordance.candidate
        reservoir = self.seed_reservoir
        if reservoir is None:
            return None
        lease = reservoir.claim_seed(
            affordance.claim_key,
            context_revision=affordance.revision,
            now=now,
        )
        if lease is None:
            return None
        return self._candidate_from_seed(
            lease.seed,
            generated_at=lease.generated_at,
            expires_at=lease.expires_at,
            lease_token=lease.token,
        )

    def _structured_model_candidate(
        self,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any],
        surface_policy: Mapping[str, Any],
    ) -> SocialSpeechCandidate | None:
        """Ask the existing DeepSeek lane for one structured affordance only."""

        if not self.enabled:
            return None
        writer = getattr(self.router, "propose_social_initiative", None)
        if not callable(writer):
            return None
        request = {
            "blackboard": blackboard.public_view(),
            "recent_public_history": list(snapshot.get("recent_public_history", ()))[-6:],
            "social_context": {
                "personality_summary": _compact(snapshot.get("personality_summary", ""), 900),
                "identity_summary": _compact(snapshot.get("identity_summary", ""), 900),
                "relationship": snapshot.get("relationship", {}),
                "recent_self_turn_semantics": list(snapshot.get("recent_self_turn_semantics", ()))[-6:],
                "memory_context": _compact(snapshot.get("memory_context", ""), 1800),
                "self_context": snapshot.get("self_context", {}),
            },
            "autonomous_expression_policy": dict(surface_policy),
            "candidate_contract": {
                "authority": "affordance_only",
                "allowed_kinds": sorted(_ALLOWED_KINDS),
                "social_kinds_do_not_require_grounding": sorted(_SOCIAL_KINDS),
                "rule": (
                    "Propose at most one public-safe semantic affordance. Do not choose whether it will be used, "
                    "do not reserve the public lane, and do not write final wording. A generic affordance is only an option; "
                    "Subject/Neuro may later form or choose an ExpressionCommitment. Do not infer permission or rejection from user silence. "
                    "Prefer a specific grounded shared-context move over generic presence language."
                ),
            },
        }
        if blackboard.engagement_kind == "chess":
            request["candidate_contract"]["rule"] += (
                " For a due chess event, propose an entertaining grounded commentary affordance."
            )
        try:
            raw = writer(request)
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[social initiative] worker failed: %s", exc)
            return None
        candidate = SocialSpeechCandidate.from_mapping(raw, source="surface_initiative_worker")
        if not candidate.available or candidate.confidence < 0.32 or candidate.relevance < 0.24:
            return None
        if not self._candidate_matches_blackboard(candidate, blackboard):
            self._log(
                "warning",
                "[social initiative] rejected kind=%s anchor=%s reason=anchor_or_evidence_mismatch",
                candidate.kind,
                candidate.anchor_type,
            )
            return None
        return candidate

    @staticmethod
    def _has_structured_opportunity(blackboard: TypedCognitiveBlackboard) -> bool:
        return any(
            anchor.kind in {"conversation", "task", "screen", "semantic_scene", "discovery"}
            for anchor in blackboard.anchors
        )

    def _random_chat_seed_affordance(
        self,
        blackboard: TypedCognitiveBlackboard,
    ) -> ExecutiveAffordance | None:
        reservoir = self.seed_reservoir
        if reservoir is None or not reservoir.enabled:
            return None
        preview = reservoir.peek(now=blackboard.now)
        if preview is None:
            return None
        # V45 production seed là associative material, không phải một social
        # candidate đang chờ được nói. Nó phải đi qua MentalMaterial lifecycle →
        # Concern/ExpressionUrge trước khi Neuro nhìn thấy. Legacy seed vẫn giữ
        # đường này cho compatibility/plugin cũ.
        if bool(getattr(preview.seed, "material_only", False)):
            return None
        candidate = self._candidate_from_seed(
            preview.seed,
            generated_at=preview.generated_at,
            expires_at=preview.expires_at,
            now=blackboard.now,
        )
        return ExecutiveAffordance(
            affordance_id=f"seed:{preview.seed.seed_id}:{preview.context_revision}",
            owner="random_chat_seed",
            revision=preview.context_revision,
            candidate=candidate,
            claim_required=True,
            expires_at=preview.expires_at,
            claim_key=preview.seed.seed_id,
            metadata={"mode": preview.seed.mode},
        )

    def _random_chat_seed_candidate(
        self,
        blackboard: TypedCognitiveBlackboard,
    ) -> SocialSpeechCandidate | None:
        """Compatibility API: claim the currently previewed seed exactly."""

        affordance = self._random_chat_seed_affordance(blackboard)
        if affordance is None:
            return None
        return self.claim_affordance(affordance, now=blackboard.now)

    @staticmethod
    def _candidate_from_seed(
        seed: Any,
        *,
        generated_at: float,
        expires_at: float,
        lease_token: str = "",
        now: float | None = None,
    ) -> SocialSpeechCandidate:
        quality = assess_seed_quality(seed)
        temporal_context = build_seed_temporal_context(now)
        # Quality raises or lowers the social candidate's effective confidence,
        # but never decides speak/silence by itself. Neuro still owns that choice.
        confidence = max(seed.confidence, 0.34 + 0.40 * seed.authenticity)
        confidence *= 0.80 + 0.20 * quality.score
        relevance = max(seed.estimated_fit, 0.36 + 0.34 * seed.personal_stake)
        relevance *= 0.78 + 0.22 * quality.score
        return SocialSpeechCandidate(
            decision="candidate",
            kind="random_chat",
            topic=seed.premise,
            speech_act=seed.opening_move,
            anchor_type="idle",
            anchor_id=seed.seed_id,
            evidence_refs=seed.source_refs,
            requires_grounding=False,
            confidence=min(0.96, confidence),
            relevance=min(0.96, relevance),
            urgency=min(0.72, 0.12 + 0.38 * seed.personal_stake + 0.18 * seed.daring),
            tone=seed.tone,
            reason=(
                f"random_chat_seed_reservoir:{seed.mode}:{seed.eris_motive_kind}:"
                f"stake={seed.personal_stake:.2f}:daring={seed.daring:.2f}"
            ),
            source="random_chat_seed_reservoir",
            seed_id=seed.seed_id,
            seed_mode=seed.mode,
            source_kind=seed.source_kind,
            topic_tags=seed.topic_tags,
            seed_event_kind=seed.event_kind,
            seed_epistemic_mode=seed.epistemic_mode,
            seed_open_loop=seed.open_loop,
            desired_response=seed.desired_response,
            eris_motive_kind=seed.eris_motive_kind,
            eris_motive_why_now=seed.eris_motive_why_now,
            personal_stake=seed.personal_stake,
            authenticity=seed.authenticity,
            daring=seed.daring,
            uncertainty=seed.uncertainty,
            seed_intrusion_risk=seed.intrusion_risk,
            face_risk=seed.face_risk,
            recovery_available=seed.recovery_available,
            seed_lease_token=lease_token,
            seed_generated_at=generated_at,
            seed_expires_at=expires_at,
            seed_ttl_seconds=seed.ttl_seconds,
            seed_quality_score=quality.score,
            seed_specificity=quality.specificity,
            seed_motive_strength=quality.motive_strength,
            seed_semantic_completeness=quality.semantic_completeness,
            seed_temporal_context=temporal_context,
        )


    @staticmethod
    def _followup_reminder_candidate(
        blackboard: TypedCognitiveBlackboard,
    ) -> SocialSpeechCandidate | None:
        """Tạo route nhắc lại đúng một lần, không tạo câu public hard-code."""

        if not blackboard.followup_reminder_due or blackboard.followup_reminder_count > 0:
            return None
        anchor = next(
            (
                item for item in blackboard.anchors
                if item.kind == "conversation" and bool(item.metadata.get("followup_reminder", False))
            ),
            None,
        )
        if anchor is None:
            return None
        return SocialSpeechCandidate(
            decision="candidate",
            kind="followup_reminder",
            topic=(
                f"Pending public thread: {anchor.topic_seed}. If this thread is still worth reopening, make exactly "
                "one short face-saving reminder. Preserve the semantic target, paraphrase rather than repeat verbatim, "
                "add no accusation or guilt, and do not append a second new question."
            ),
            speech_act="followup_reminder",
            anchor_type="conversation",
            anchor_id=anchor.anchor_id,
            evidence_refs=(),
            requires_grounding=False,
            confidence=max(0.82, anchor.confidence),
            relevance=0.94,
            urgency=0.42,
            tone="gentle_reminder",
            reason="followup_appraisal:user_may_not_have_noticed",
            source="followup_appraisal",
        )

    @staticmethod
    def _abandoned_topic_shift_candidate(
        blackboard: TypedCognitiveBlackboard,
    ) -> SocialSpeechCandidate | None:
        """Rút khỏi thread cũ và mở một ý khác với khoảng cách xã hội nhẹ."""

        if not (
            blackboard.followup_abandoned
            and blackboard.may_start_new_topic
            and blackboard.suppress_same_topic
        ):
            return None
        return SocialSpeechCandidate(
            decision="candidate",
            kind="random_chat",
            topic=(
                "Silently abandon the previous unanswered topic and start one different, self-contained public-safe "
                "thought from ERIS's own curiosity or the recent shared context. Treat lack of interest only as a weak "
                "inference: do not mention being ignored, do not revive the old question, do not guilt-trip, and do not "
                "ask the user to explain the silence. Sound slightly more self-contained and reserved for this turn, "
                "but remain civil and leave an easy path back. Prefer a statement or observation over another question."
            ),
            speech_act="independent_topic_shift",
            anchor_type="idle",
            anchor_id="abandoned_thread_shift",
            evidence_refs=(),
            requires_grounding=False,
            confidence=0.80,
            relevance=0.86,
            urgency=0.24,
            tone="slightly_reserved",
            reason=(
                f"followup_appraisal:abandoned_thread:distance={blackboard.social_distance:.2f}"
            ),
            source="followup_appraisal",
        )

    def fallback_candidate(self, blackboard: TypedCognitiveBlackboard, *, reason: str) -> SocialSpeechCandidate | None:
        """Chỉ tạo typed route tới Surface, tuyệt đối không tạo câu local.

        Event engagement có provenance vẫn cần một candidate cơ học để tới Surface.
        Với quiet companion, candidate chỉ được tạo khi user đã bật preference
        nói tự động. Nếu Surface provider không viết được câu, pipeline sẽ im và
        thử lại nhịp sau; không có loa phường hard-code chen vào.
        """

        # Model/seed worker trả none là một quyết định im lặng thật. Generic
        # random-chat fallback chính là nguồn của các câu kiểu "mình vẫn ở đây".
        # Structured task/semantic lanes vẫn có fallback riêng vì chúng có provenance.
        if reason == "worker_no_candidate":
            return None
        task_candidate = self._task_followup_candidate(blackboard, reason=reason)
        if task_candidate is not None:
            return task_candidate
        if blackboard.engagement_exclusive_focus and blackboard.engagement_active:
            return None

        semantic_candidate = self._semantic_scene_candidate(blackboard, reason=reason)
        if semantic_candidate is not None:
            return semantic_candidate

        # Generic liveness fallback was removed, not shadowed.  A dead Seed or
        # unavailable social worker produces no semantic affordance.  Runtime may
        # still emit body presence through the governor, but it may not manufacture
        # a public topic merely because a timer expired.
        return None

    @staticmethod
    def _semantic_scene_candidate(
        blackboard: TypedCognitiveBlackboard,
        *,
        reason: str,
    ) -> SocialSpeechCandidate | None:
        """Giữ semantic scene khỏi rơi xuống generic small talk khi model lỗi.

        Đây vẫn chỉ là route semantic tới Surface, không phải câu hard-code.
        Packet nền cũ chỉ được dùng khi cadence đã due; packet mới có thể mở một
        cơ hội bình luận ngay vì nó tương ứng app/tab/media/content vừa đổi.
        """

        if not blackboard.semantic_context_ready:
            return None
        anchor = next((item for item in blackboard.anchors if item.kind == "semantic_scene"), None)
        if anchor is None:
            return None
        novel = bool(anchor.metadata.get("novel", False))
        if not novel and not blackboard.commentary_due:
            return None
        scores = dict(blackboard.semantic_response_mode_scores or {})
        analysis_score = max(
            float(scores.get("screen_analysis", 0.0) or 0.0),
            float(scores.get("deep_analysis", 0.0) or 0.0),
        )
        small_talk_score = max(
            float(scores.get("screen_related_small_talk", 0.0) or 0.0),
            float(scores.get("cross_context_connection", 0.0) or 0.0),
        )
        if max(analysis_score, small_talk_score) < 0.28:
            return None
        speech_act = "analyze_foreground" if analysis_score >= small_talk_score else "screen_related_small_talk"
        topic_options = tuple(blackboard.semantic_topic_options or ())
        topic = topic_options[0] if topic_options else blackboard.semantic_foreground
        return SocialSpeechCandidate(
            decision="candidate",
            kind="semantic_scene",
            topic=_compact(topic or anchor.topic_seed, 300),
            speech_act=speech_act,
            anchor_type="semantic_scene",
            anchor_id=anchor.anchor_id,
            evidence_refs=anchor.evidence_refs,
            requires_grounding=False,
            confidence=max(0.72, anchor.confidence),
            relevance=max(0.78, anchor.priority),
            urgency=0.34 if novel else 0.14,
            tone="curious" if speech_act == "analyze_foreground" else "casual_warm",
            reason=f"semantic_scene_route:{reason}",
            source="semantic_context_fallback",
        )

    @staticmethod
    def _task_anchor(blackboard: TypedCognitiveBlackboard) -> CognitiveAnchor | None:
        if not blackboard.engagement_active or not (blackboard.engagement_due or blackboard.engagement_required):
            return None
        return next((anchor for anchor in blackboard.anchors if anchor.kind == "task"), None)

    @classmethod
    def _chess_event_overrides_reply_baton(cls, blackboard: TypedCognitiveBlackboard) -> bool:
        anchor = cls._task_anchor(blackboard)
        return bool(
            anchor is not None
            and str(blackboard.engagement_kind or anchor.metadata.get("engagement_kind", "")).lower() == "chess"
        )

    @classmethod
    def _task_followup_candidate(
        cls,
        blackboard: TypedCognitiveBlackboard,
        *,
        reason: str,
    ) -> SocialSpeechCandidate | None:
        """Deterministic lane fallback cho event engagement đã đến hạn.

        Đây không phải local small-talk generator. Nó chỉ giữ task/event đã có
        provenance khỏi biến mất khi Surface worker lỗi, trả ``none`` hoặc chọn
        nhầm một lane xã giao. Surface Realizer vẫn viết câu public cuối cùng.
        """

        anchor = cls._task_anchor(blackboard)
        if anchor is None:
            return None
        engagement_kind = str(
            blackboard.engagement_kind or anchor.metadata.get("engagement_kind", "task") or "task"
        ).strip().lower()
        topic = (
            f"Continue the active {engagement_kind} engagement from its newest structured event/state. "
            f"Current task reason: {anchor.topic_seed}. Do not ask the user to restate facts already "
            "available in engagement context."
        )
        return SocialSpeechCandidate(
            decision="candidate",
            kind="task_followup",
            topic=_compact(topic, 300),
            speech_act="comment_on_progress",
            anchor_type="task",
            anchor_id=anchor.anchor_id,
            evidence_refs=anchor.evidence_refs,
            requires_grounding=False,
            confidence=max(0.82, anchor.confidence),
            relevance=max(0.92, anchor.priority),
            urgency=0.78 if blackboard.engagement_required else 0.64,
            tone="focused",
            reason=f"deterministic_engagement_fallback:{reason}",
            source="initiative_local_task_fallback",
        )

    @staticmethod
    def _candidate_matches_blackboard(
        candidate: SocialSpeechCandidate,
        blackboard: TypedCognitiveBlackboard,
    ) -> bool:
        if candidate.social:
            return not candidate.requires_grounding and candidate.anchor_type in {"idle", "conversation", "none"}
        anchors = tuple(blackboard.anchors)
        matching: CognitiveAnchor | None = next(
            (
                anchor
                for anchor in anchors
                if anchor.kind == candidate.anchor_type
                and (not candidate.anchor_id or candidate.anchor_id == anchor.anchor_id)
            ),
            None,
        )
        if matching is None:
            # Mode names and source kinds are intentionally different for a few
            # contracts. Keep the mapping explicit rather than guessing by text.
            expected = {
                "continuation": "conversation",
                "conversation_arc": "conversation",
                "followup_reminder": "conversation",
                "task_followup": "task",
                "discovery_share": "discovery",
                "screen_comment": "screen",
                "semantic_scene": "semantic_scene",
                "memory_callback": "memory",
                "inner_thought": "self",
            }.get(candidate.kind, candidate.anchor_type)
            matching = next((anchor for anchor in anchors if anchor.kind == expected), None)
        if matching is None:
            return False
        allowed_refs = set(matching.evidence_refs)
        if candidate.requires_grounding:
            return bool(candidate.evidence_refs) and set(candidate.evidence_refs).issubset(allowed_refs)
        return set(candidate.evidence_refs).issubset(allowed_refs)

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass


__all__ = [
    "CANDIDATE_SCHEMA",
    "SocialInitiativeEngine",
    "SocialSpeechCandidate",
]
