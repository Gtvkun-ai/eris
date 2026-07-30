# -*- coding: utf-8 -*-
"""Typed Cognitive Blackboard cho self-initiated turn của ERIS.

Blackboard là ranh giới giữa cognition nền và quyền phát ngôn:

- observer / inner / critic / memory chỉ đóng góp tín hiệu đã chuẩn hóa;
- không worker nào được tự viết câu public từ đây;
- controller đọc đúng contract này để chọn NO_OP, BODY_ONLY hoặc SPEECH;
- raw chain-of-thought, raw diary và nội dung riêng tư không được đi qua.

Nói cách khác: đây là bảng trạng thái có kiểu, không phải phòng họp nơi bảy
worker cùng giành micro. Một cải tiến nhỏ cho văn minh phần mềm.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


BLACKBOARD_SCHEMA = "eris.cognitive_blackboard.v2"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


@dataclass(frozen=True, slots=True)
class CognitiveAnchor:
    """Một neo công khai mà controller có thể dùng.

    ``kind`` là semantic source, không phải câu thoại. ``topic_seed`` chỉ chứa
    nội dung đã public-safe hoặc mô tả cơ học, tuyệt đối không chứa raw thought.
    """

    kind: str
    anchor_id: str
    topic_seed: str
    confidence: float
    priority: float
    evidence_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TypedCognitiveBlackboard:
    """Snapshot bất biến dùng cho một lần quyết định initiative."""

    schema: str = BLACKBOARD_SCHEMA
    now: float = 0.0
    user_busy: bool = False
    privacy_blocked: bool = False
    reply_expected: bool = False
    assistant_may_continue: bool = False
    thread_fresh: bool = False
    thread_key: str = "none"
    seconds_since_user: float = 0.0
    seconds_since_assistant: float = 0.0
    mechanical_delta: bool = False
    activity_event: bool = False
    screen_fresh: bool = False
    screen_title: str = ""
    screen_evidence_refs: tuple[str, ...] = ()
    vision_grounding_recommendation: str = "silence"
    vision_grounding_strength: float = 0.0
    grounded_screen_claims: tuple[str, ...] = ()
    grounded_screen_evidence_refs: tuple[str, ...] = ()
    public_seed_ready: bool = False
    public_seed_score: float = 0.0
    discovery_ready: bool = False
    commentary_due: bool = False
    commentary_required: bool = False
    commentary_reason: str = ""
    commentary_anchor_kind: str = ""
    engagement_active: bool = False
    engagement_due: bool = False
    engagement_required: bool = False
    engagement_kind: str = ""
    attention_pressure: float = 0.0
    observer_ready: bool = False
    observer_confidence: float = 0.0
    critic_reviewed: bool = False
    repair_pending: bool = False
    memory_available: bool = False
    anchors: tuple[CognitiveAnchor, ...] = ()

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any], *, now: float | None = None) -> "TypedCognitiveBlackboard":
        """Rút một blackboard typed từ snapshot planner hiện có.

        Hàm cố ý chỉ đọc field có provenance rõ. Nó không đoán mood/user intent
        từ OCR, không biến open loop thành memory, và không copy raw history vào
        blackboard public.
        """

        telemetry = _mapping(snapshot.get("telemetry"))
        screen = _mapping(snapshot.get("screen_context"))
        baton = _mapping(snapshot.get("conversation_baton"))
        activity = _mapping(snapshot.get("activity_session"))
        self_context = _mapping(snapshot.get("self_context"))
        attention = _mapping(self_context.get("attention"))
        discovery = _mapping(snapshot.get("discovery"))
        commentary = _mapping(snapshot.get("commentary_expectation"))
        engagement = _mapping(snapshot.get("engagement_context"))
        engagement_interaction = _mapping(snapshot.get("engagement_interaction"))
        latest_observation = _mapping(snapshot.get("latest_observation"))
        vision_grounding = _mapping(snapshot.get("vision_grounding"))

        user_busy = bool(
            telemetry.get("user_busy", False)
            or telemetry.get("interaction_busy", False)
            or snapshot.get("chat_processing", False)
        )
        privacy_blocked = bool(screen.get("privacy_blocked", False))
        screen_fresh = bool(screen.get("fresh", False) and not privacy_blocked)
        screen_refs = tuple(
            ref for ref in (_compact(item, 120) for item in _sequence(screen.get("evidence_refs"))[:8]) if ref
        )
        screen_title = _compact(
            screen.get("window_title")
            or telemetry.get("active_window")
            or telemetry.get("window_title")
            or telemetry.get("foreground_window"),
            180,
        )
        grounding_recommendation = _compact(vision_grounding.get("recommendation", "silence"), 24).lower() or "silence"
        grounding_strength = _clamp01(vision_grounding.get("evidence_strength", 0.0))
        grounded_claims_raw = [
            _mapping(item) for item in _sequence(vision_grounding.get("claims"))[:8] if isinstance(item, Mapping)
        ]
        grounded_claims = tuple(
            _compact(item.get("text", ""), 240)
            for item in grounded_claims_raw
            if bool(item.get("grounded", False)) and not bool(item.get("stale", False)) and _compact(item.get("text", ""), 240)
        )
        grounded_refs = tuple(dict.fromkeys(
            ref
            for item in grounded_claims_raw
            if bool(item.get("grounded", False)) and not bool(item.get("stale", False))
            for ref in (_compact(value, 140) for value in _sequence(item.get("evidence_ids"))[:6])
            if ref
        ))
        mechanical_delta = bool(screen.get("meaningful_delta", False) or screen.get("window_changed", False))
        new_event_keys = tuple(
            key for key in (_compact(item, 120) for item in _sequence(activity.get("new_event_keys"))[:8]) if key
        )
        activity_event = bool(activity.get("has_new_event", False) or new_event_keys)

        public_seed_ready = bool(self_context.get("has_public_seed", False))
        public_seed_score = _clamp01(self_context.get("strongest_seed_score", 0.0))
        discovery_ready = bool(
            discovery.get("ready_to_share")
            or discovery.get("artifact")
            or discovery.get("artifact_ready")
        )
        attention_pressure = max(
            _clamp01(attention.get("external_pressure", 0.0)),
            _clamp01(attention.get("internal_drive", 0.0)),
        )
        observation_source = _compact(latest_observation.get("source", ""), 100).lower()
        observer_ready = bool(latest_observation)
        observer_confidence = _clamp01(latest_observation.get("confidence", 0.0))
        # Critic chỉ được ghi là đã tham gia khi observer contract nói rõ deep
        # review. Không suy "critic chắc đã chạy" từ việc client tồn tại.
        critic_reviewed = bool("deep" in observation_source or "critic" in observation_source)
        repair_pending = bool(latest_observation.get("repair_needed", False))

        anchors: list[CognitiveAnchor] = []

        # 1) Conversation continuity có quyền ưu tiên cao nhất vì đây là mạch
        # công khai đã tồn tại, không phải một ý nghĩ nền muốn chen hàng.
        thread_key = _compact(baton.get("thread_key", "none"), 120) or "none"
        if bool(baton.get("assistant_may_continue", False)) and bool(baton.get("thread_fresh", False)):
            anchors.append(CognitiveAnchor(
                kind="conversation",
                anchor_id=thread_key,
                topic_seed=_compact(baton.get("unresolved_point", ""), 240) or "continue the open public thread",
                confidence=_clamp01(baton.get("confidence", 0.72), 0.72),
                priority=0.96,
                evidence_refs=(),
                metadata={"reply_expected": bool(baton.get("reply_expected", False))},
            ))

        # 2) Engagement có contract riêng. Chỉ đưa vào khi runtime nói đã đến
        # nhịp; không tự biến một task đang chờ thành cái cớ nói linh tinh.
        engagement_active = bool(engagement.get("active", False))
        engagement_due = bool(engagement_interaction.get("due", False))
        engagement_required = bool(engagement_interaction.get("required", False))
        engagement_kind = _compact(
            engagement_interaction.get("engagement_kind") or engagement.get("kind", ""), 80
        )
        if engagement_active and (engagement_due or engagement_required):
            anchors.append(CognitiveAnchor(
                kind="task",
                anchor_id=_compact(engagement_interaction.get("engagement_id", "active_engagement"), 120),
                topic_seed=_compact(
                    engagement_interaction.get("reason") or engagement.get("objective", "follow up active engagement"),
                    240,
                ),
                confidence=0.86 if engagement_required else 0.76,
                priority=0.94 if engagement_required else 0.88,
                evidence_refs=(),
                metadata={"engagement_kind": engagement_kind},
            ))

        # 3) Discovery chỉ được surface khi DiscoveryRuntime đã đánh dấu một
        # record verified là ready_to_share. Contract thật dùng một list payload,
        # không phải field ``artifact`` đơn. Ta vẫn đọc artifact legacy để package
        # cũ không chết ngay, nhưng ready_to_share luôn là authority ưu tiên.
        ready_items = [
            _mapping(item)
            for item in _sequence(discovery.get("ready_to_share"))[:3]
            if isinstance(item, Mapping)
        ]
        artifact = ready_items[0] if ready_items else _mapping(discovery.get("artifact"))
        if discovery_ready:
            discovery_id = _compact(
                artifact.get("discovery_id")
                or artifact.get("id")
                or discovery.get("id", "discovery_ready"),
                120,
            )
            evidence_refs = tuple(
                ref for ref in (
                    _compact(item, 160)
                    for item in _sequence(
                        artifact.get("evidence") or artifact.get("evidence_refs")
                    )[:6]
                ) if ref
            )
            anchors.append(CognitiveAnchor(
                kind="discovery",
                anchor_id=discovery_id,
                topic_seed=_compact(
                    artifact.get("topic")
                    or artifact.get("verified_summary")
                    or artifact.get("summary")
                    or discovery.get("topic")
                    or discovery.get("reason", "share verified discovery"),
                    260,
                ),
                confidence=_clamp01(
                    artifact.get("source_confidence", discovery.get("confidence", 0.74)),
                    0.74,
                ),
                priority=0.86,
                evidence_refs=evidence_refs,
                metadata={
                    "artifact_ready": True,
                    "lane": _compact(artifact.get("lane", ""), 80),
                    "source": _compact(artifact.get("source", ""), 80),
                },
            ))

        # 4) Screen chỉ trở thành *speech anchor* khi VisionGroundingPolicy đã
        # duyệt ít nhất một grounded claim có provenance. Window title/OCR delta
        # thô vẫn giữ cho body-only gesture, nhưng không được tự thăng chức thành
        # sự thật công khai. Đây là chỗ chặn câu kiểu "Brave là chủ đề moc3".
        grounded_screen_ready = bool(
            grounding_recommendation == "speak"
            and grounded_claims
            and grounded_refs
            and not privacy_blocked
        )
        if (mechanical_delta or activity_event) and grounded_screen_ready:
            anchors.append(CognitiveAnchor(
                kind="screen" if mechanical_delta else "activity",
                anchor_id=grounded_refs[0],
                topic_seed=grounded_claims[0],
                confidence=max(0.72, grounding_strength),
                priority=0.84,
                evidence_refs=grounded_refs,
                metadata={
                    "new_event_keys": list(new_event_keys),
                    "grounded_claims": list(grounded_claims),
                    "raw_window_title_withheld": bool(screen_title),
                },
            ))

        # 5) Chỉ dùng public-safe queue/agenda. Không đọc raw private mind.
        if public_seed_ready:
            candidates: list[Mapping[str, Any]] = []
            for group in ("agenda", "private_mind_surface", "private_life_surface"):
                candidates.extend(_mapping(item) for item in _sequence(self_context.get(group))[:5])
            candidates.sort(
                key=lambda item: max(
                    _clamp01(item.get("score", 0.0)),
                    _clamp01(item.get("speech_value", 0.0)),
                    _clamp01(item.get("confidence", 0.0)),
                ),
                reverse=True,
            )
            seed = candidates[0] if candidates else {}
            topic_seed = _compact(seed.get("topic_seed") or seed.get("summary", "public-safe internal thought"), 260)
            evidence_refs = tuple(
                ref for ref in (
                    _compact(item, 120) for item in _sequence(seed.get("evidence_refs"))[:6]
                ) if ref
            )
            source_kind = _compact(seed.get("source") or seed.get("kind", "public_safe_self"), 80).lower()
            # Memory chỉ trở thành anchor riêng khi đã qua surface valve VÀ còn
            # provenance. Một cảm giác "hình như từng nhớ" không được panel/code
            # nâng cấp thành ký ức thật chỉ vì tên nghe thơ.
            memory_seed = bool(
                evidence_refs
                and (
                    source_kind in {"memory", "memory_resonance", "memory_echo", "episodic_memory"}
                    or any(ref.lower().startswith(("memory:", "episode:", "episodic:")) for ref in evidence_refs)
                )
            )
            anchors.append(CognitiveAnchor(
                kind="memory" if memory_seed else "self",
                anchor_id=_compact(seed.get("id", "public_self_seed"), 120),
                topic_seed=topic_seed,
                confidence=max(public_seed_score, _clamp01(seed.get("confidence", 0.0))),
                priority=0.72 + 0.18 * public_seed_score if memory_seed else 0.68 + 0.20 * public_seed_score,
                evidence_refs=evidence_refs,
                metadata={"source": source_kind},
            ))

        # 6) Presence là neo sản phẩm cuối cùng, chỉ tồn tại khi cadence nói due.
        # Nó không mang nội dung sẵn; Surface Worker sẽ viết từ persona/public
        # context, còn controller vẫn quyết định có phát biểu hay không.
        commentary_due = bool(commentary.get("due", False))
        commentary_required = bool(commentary.get("required", False))
        if commentary_due:
            anchors.append(CognitiveAnchor(
                kind="presence",
                anchor_id=_compact(commentary.get("anchor_kind", "shared_quiet"), 120),
                topic_seed="brief companion presence grounded in the current public context",
                confidence=0.76 if commentary_required else 0.64,
                priority=0.90 if commentary_required else 0.56,
                evidence_refs=(),
                metadata={"required": commentary_required},
            ))

        anchors.sort(key=lambda item: (item.priority, item.confidence), reverse=True)
        memory_context = _compact(snapshot.get("memory_context", ""), 32)

        return cls(
            now=float(now if now is not None else snapshot.get("time", 0.0) or 0.0),
            user_busy=user_busy,
            privacy_blocked=privacy_blocked,
            reply_expected=bool(baton.get("reply_expected", False)),
            assistant_may_continue=bool(baton.get("assistant_may_continue", False)),
            thread_fresh=bool(baton.get("thread_fresh", False)),
            thread_key=thread_key,
            seconds_since_user=max(0.0, float(snapshot.get("seconds_since_user", 0.0) or 0.0)),
            seconds_since_assistant=max(0.0, float(snapshot.get("seconds_since_assistant", 0.0) or 0.0)),
            mechanical_delta=mechanical_delta,
            activity_event=activity_event,
            screen_fresh=screen_fresh,
            screen_title=screen_title,
            screen_evidence_refs=screen_refs,
            vision_grounding_recommendation=grounding_recommendation,
            vision_grounding_strength=grounding_strength,
            grounded_screen_claims=grounded_claims,
            grounded_screen_evidence_refs=grounded_refs,
            public_seed_ready=public_seed_ready,
            public_seed_score=public_seed_score,
            discovery_ready=discovery_ready,
            commentary_due=commentary_due,
            commentary_required=commentary_required,
            commentary_reason=_compact(commentary.get("reason", ""), 120),
            commentary_anchor_kind=_compact(commentary.get("anchor_kind", ""), 120),
            engagement_active=engagement_active,
            engagement_due=engagement_due,
            engagement_required=engagement_required,
            engagement_kind=engagement_kind,
            attention_pressure=attention_pressure,
            observer_ready=observer_ready,
            observer_confidence=observer_confidence,
            critic_reviewed=critic_reviewed,
            repair_pending=repair_pending,
            memory_available=bool(memory_context or snapshot.get("open_loops")),
            anchors=tuple(anchors[:8]),
        )

    def strongest_anchor(self) -> CognitiveAnchor | None:
        return self.anchors[0] if self.anchors else None

    def public_view(self) -> dict[str, Any]:
        """View an toàn cho Surface Worker; không chứa raw cognition."""

        return {
            "schema": self.schema,
            "now": self.now,
            "seconds_since_user": round(self.seconds_since_user, 2),
            "seconds_since_assistant": round(self.seconds_since_assistant, 2),
            "reply_expected": self.reply_expected,
            "privacy_blocked": self.privacy_blocked,
            "screen_fresh": bool(self.grounded_screen_claims),
            # Chỉ public title/claim đã grounded; raw title vẫn ở telemetry nội bộ
            # để UI/body biết có delta nhưng không được đưa cho topic generator.
            "screen_title": self.grounded_screen_claims[0] if self.grounded_screen_claims else "",
            "vision_grounding": {
                "recommendation": self.vision_grounding_recommendation,
                "evidence_strength": round(self.vision_grounding_strength, 3),
                "grounded_claims": list(self.grounded_screen_claims),
                "evidence_refs": list(self.grounded_screen_evidence_refs),
            },
            "commentary_due": self.commentary_due,
            "commentary_required": self.commentary_required,
            "engagement_active": self.engagement_active,
            "background_cognition": {
                "observer_ready": self.observer_ready,
                "observer_confidence": round(self.observer_confidence, 3),
                "critic_reviewed": self.critic_reviewed,
                "repair_pending": self.repair_pending,
                "inner_public_seed_ready": self.public_seed_ready,
                "memory_available": self.memory_available,
            },
            "anchors": [item.to_dict() for item in self.anchors],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "screen_evidence_refs": list(self.screen_evidence_refs),
            "grounded_screen_claims": list(self.grounded_screen_claims),
            "grounded_screen_evidence_refs": list(self.grounded_screen_evidence_refs),
            "anchors": [item.to_dict() for item in self.anchors],
        }


__all__ = [
    "BLACKBOARD_SCHEMA",
    "CognitiveAnchor",
    "TypedCognitiveBlackboard",
]
