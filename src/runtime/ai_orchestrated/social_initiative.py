# -*- coding: utf-8 -*-
"""Social Initiative Worker cho autonomous speech của ERIS.

V18 tách hai quyền vốn hay bị trộn lẫn:

- model ``surface`` đề xuất *mong muốn/chủ đề* dưới dạng ``SocialSpeechCandidate``;
- runtime governor chỉ kiểm timing, cooldown, privacy, duplicate và user-busy;
- Surface Realizer viết câu cuối sau khi candidate đã được governor cho phép.

Cùng một DeepSeek worker role ``surface`` có thể phục vụ hai contract typed
(``candidate`` và ``wording``), nên không cần sinh thêm worker thứ tám chỉ để sơ
đồ trông có vẻ bận rộn. Raw chain-of-thought và raw Inner Diary không đi qua đây.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .cognitive_blackboard import CognitiveAnchor, TypedCognitiveBlackboard


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


_ALLOWED_KINDS = {
    "continuation",
    "task_followup",
    "discovery_share",
    "screen_comment",
    "memory_callback",
    "inner_thought",
    "social_check_in",
    "casual_curiosity",
    "playful_prompt",
    "random_chat",
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

    @property
    def available(self) -> bool:
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
        )


class SocialInitiativeEngine:
    """Cho DeepSeek quyền đề xuất chủ đề; không cho nó quyền tự phát ngôn."""

    def __init__(self, router: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.router, "surface_client", None) is not None)

    def propose(
        self,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> SocialSpeechCandidate | None:
        """Đề xuất một candidate typed bằng đúng một model call ngắn.

        Worker chỉ nhìn ``public_view`` và history public rút gọn. Nếu model trả
        screen candidate, evidence phải trùng grounded screen anchor đã có; title
        OCR thô không đủ tư cách làm bằng chứng, dù nó viết hoa rất thuyết phục.
        """

        # Hard timing boundaries có thể chặn trước model call. Đây là governor
        # preflight, không phải runtime nghĩ topic. Một event cờ mới từ bridge
        # được phép thắng reply baton cũ vì structured runtime đã cung cấp câu
        # trả lời thực tế; tiếp tục chờ user xác nhận lúc này chỉ làm Eris đứng im.
        if blackboard.user_busy:
            return None
        if blackboard.reply_expected and not self._chess_event_overrides_reply_baton(blackboard):
            return None
        soft = _env_float("ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC", 180.0, minimum=45.0, maximum=3600.0)
        has_typed_opportunity = any(anchor.kind != "presence" for anchor in blackboard.anchors)
        social_opportunity_due = bool(
            blackboard.commentary_due
            or blackboard.seconds_since_assistant >= soft
            or blackboard.seconds_since_user >= soft
        )
        if not has_typed_opportunity and not social_opportunity_due:
            return None
        if not self.enabled:
            return self.fallback_candidate(blackboard, reason="surface_worker_unavailable")
        writer = getattr(self.router, "propose_social_initiative", None)
        if not callable(writer):
            return self.fallback_candidate(blackboard, reason="initiative_method_unavailable")
        source_snapshot = snapshot or {}
        request = {
            "blackboard": blackboard.public_view(),
            "recent_public_history": list(source_snapshot.get("recent_public_history", ()))[-6:],
            # Đây là public/persona context đã được reducer chuẩn hóa, không phải
            # raw diary hay chain-of-thought. Nó cho random chat có chất Eris thay
            # vì một máy tạo câu hỏi xã giao tổng quát.
            "social_context": {
                "personality_summary": _compact(source_snapshot.get("personality_summary", ""), 900),
                "identity_summary": _compact(source_snapshot.get("identity_summary", ""), 900),
                "relationship": source_snapshot.get("relationship", {}),
                "recent_self_turn_semantics": list(source_snapshot.get("recent_self_turn_semantics", ()))[-6:],
            },
            "candidate_contract": {
                "authority": "desire_and_topic_only",
                "allowed_kinds": sorted(_ALLOWED_KINDS),
                "social_kinds_do_not_require_grounding": sorted(_SOCIAL_KINDS),
                "rule": (
                    "Propose at most one public-safe topic. Runtime owns permission/timing; "
                    "Surface Realizer owns final wording. Return none when nothing is worth proposing."
                ),
            },
        }
        try:
            raw = writer(request)
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "[social initiative] worker failed: %s", exc)
            return self.fallback_candidate(blackboard, reason="worker_error")
        candidate = SocialSpeechCandidate.from_mapping(raw, source="surface_initiative_worker")
        if not candidate.available:
            return self.fallback_candidate(blackboard, reason="worker_no_candidate")
        if candidate.confidence < 0.32 or candidate.relevance < 0.24:
            return self.fallback_candidate(blackboard, reason="worker_low_confidence")

        # Task event đang due không được bị một candidate xã giao hợp lệ nhưng
        # lạc đề chiếm micro. Model vẫn được đề xuất wording direction; runtime
        # chỉ ép đúng lane task khi engagement đã phát ra một event cụ thể.
        task_fallback = self._task_followup_candidate(blackboard, reason="worker_missed_due_task")
        if task_fallback is not None and candidate.kind != "task_followup":
            return task_fallback
        if not self._candidate_matches_blackboard(candidate, blackboard):
            self._log(
                "warning",
                "[social initiative] rejected kind=%s anchor=%s reason=anchor_or_evidence_mismatch",
                candidate.kind,
                candidate.anchor_type,
            )
            return self.fallback_candidate(blackboard, reason="candidate_not_grounded")
        return candidate

    def fallback_candidate(self, blackboard: TypedCognitiveBlackboard, *, reason: str) -> SocialSpeechCandidate | None:
        """Liveness fallback thuộc initiative service, không thuộc governor.

        Fallback chỉ tạo *cơ hội/chủ đề xã hội* khi quiet ceiling đã tới. Governor
        vẫn có thể hoãn vì user busy, cooldown hoặc reply baton. Như vậy không có
        ``silence_forever()``, cũng không biến hard ceiling thành đồng hồ báo nói.
        """

        task_candidate = self._task_followup_candidate(blackboard, reason=reason)
        if task_candidate is not None:
            return task_candidate

        soft = _env_float("ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC", 180.0, minimum=45.0, maximum=3600.0)
        hard = _env_float("ERIS_SOCIAL_INITIATIVE_HARD_SILENCE_SEC", 600.0, minimum=120.0, maximum=7200.0)
        if blackboard.seconds_since_assistant < soft and not blackboard.commentary_due:
            return None
        required = bool(blackboard.commentary_required or blackboard.seconds_since_assistant >= hard)
        if not required and blackboard.seconds_since_user < soft:
            return None
        kind = "casual_curiosity" if blackboard.seconds_since_user >= hard else "social_check_in"
        topic = (
            "Open one light, non-factual conversation thread because the shared silence has lasted a while; "
            "ask about the user's current headspace without claiming to know it."
            if kind == "casual_curiosity"
            else "Offer one brief social check-in that does not rely on screen facts or private cognition."
        )
        return SocialSpeechCandidate(
            decision="candidate",
            kind=kind,
            topic=topic,
            speech_act=kind,
            anchor_type="idle",
            anchor_id="long_shared_quiet" if required else "soft_shared_quiet",
            evidence_refs=(),
            requires_grounding=False,
            confidence=0.66 if required else 0.54,
            relevance=0.64 if required else 0.48,
            urgency=0.22 if required else 0.10,
            tone="casual_warm",
            reason=f"liveness_fallback:{reason}",
            source="initiative_local_liveness",
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
                "task_followup": "task",
                "discovery_share": "discovery",
                "screen_comment": "screen",
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
