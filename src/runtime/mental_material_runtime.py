# -*- coding: utf-8 -*-
"""Runtime lifecycle cho MentalMaterial V45.

DFU/seed worker giờ chỉ sinh *associative material*. Module này mới sở hữu việc
mảnh đó có còn sống, có đáng thành concern, hay có pull biểu đạt hay không.

Không có public writer ở đây. Không có speak/silence ở đây. Một material có thể
thoáng qua rồi mất mà chưa bao giờ đi vào Neuro. Đây là khác biệt chính với kiến
trúc cũ nơi seed hợp lệ gần như mặc định là một candidate hội thoại đang chờ lượt.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from cortex.mental_material import (
    MENTAL_MATERIAL_VERSION,
    MATERIAL_KINDS,
    MentalMaterial,
)
from cortex.rumination_dynamics import semantic_development_score
from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.random_chat_seed import assess_seed_quality
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


MENTAL_MATERIAL_RUNTIME_VERSION = MENTAL_MATERIAL_VERSION


def _compact(value: Any, limit: int = 520) -> str:
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


def _refs(values: Sequence[Any] | tuple[Any, ...], limit: int = 12) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(x).strip() for x in values if str(x or "").strip()))[:limit]


def _material_speech_act(kind: str, *, expected_update: Sequence[str] = ()) -> str:
    if kind == "question" and tuple(expected_update or ()):
        return "ask_genuine_question"
    if kind == "playful_impulse":
        return "playful_observation"
    if kind == "memory_callback":
        return "memory_callback"
    if kind == "small_contact":
        return "contextual_small_contact"
    if kind == "plan":
        return "share_intention"
    if kind == "desire":
        return "share_preference"
    if kind == "reaction":
        return "share_reaction"
    if kind == "opinion":
        return "share_opinion"
    if kind == "observation":
        return "share_observation"
    return "share_self_originated_thought"


def _legacy_motive(motive_kind: str, material_kind: str = "") -> str:
    # Causal motive giải thích *vì sao thought sinh ra*. Expression motive được
    # suy từ chính loại material, không để user-event motive biến mọi reaction
    # thành "explore" rồi lại kéo chúng về dạng câu hỏi.
    by_material = {
        "playful_impulse": "want_to_play",
        "small_contact": "want_to_connect",
        "question": "want_to_know",
        "hunch": "want_to_explore",
        "unfinished_thought": "want_to_explore",
        "memory_callback": "want_to_revisit",
        "reaction": "want_to_share",
        "opinion": "want_to_share",
        "observation": "want_to_share",
        "association": "want_to_share",
        "plan": "want_to_express",
        "desire": "want_to_express",
        "self_reflection": "want_to_express",
    }
    if material_kind in by_material:
        return by_material[material_kind]
    return {
        "engage_user_event": "want_to_explore",
        "continue_concern": "want_to_revisit",
        "revisit_memory": "want_to_revisit",
        "continue_private_thought": "want_to_express",
        "react_to_self_outcome": "want_to_express",
        "share_internal_material": "want_to_share",
    }.get(str(motive_kind or ""), "want_to_share")


class MentalMaterialRuntime:
    """Session-local material field giữa associative generation và cognition."""

    def __init__(self, host: Any, *, logger: Any | None = None) -> None:
        self.host = host
        self.logger = logger or getattr(host, "logger", None)
        self._materials: dict[str, MentalMaterial] = {}
        self._last_log_signature = ""

    def _log(self, level: str, message: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(message, *args)

    def ingest_seed(self, seed: Any, *, now: float | None = None) -> dict[str, Any] | None:
        """Nhận material seed đã validate; không tự biến nó thành speech candidate."""

        if not bool(getattr(seed, "material_only", False)):
            # Compatibility: seed legacy vẫn đi đường V44 cũ. V45 production luôn
            # đánh dấu material_only=True sau khi runtime đã gắn causal motive.
            return None
        current = float(now or time.time())
        material_id = str(getattr(seed, "material_id", "") or getattr(seed, "seed_id", "") or "").strip()
        content = _compact(getattr(seed, "premise", ""), 620)
        material_kind = str(getattr(seed, "material_kind", "") or "observation").strip().lower()
        if not material_id or not content or material_kind not in MATERIAL_KINDS:
            return None

        quality = assess_seed_quality(seed).score
        existing = self._materials.get(material_id)
        if existing is not None:
            # Cùng material identity không phải event mới. Chỉ cập nhật transport
            # freshness nếu producer retry cùng object, không tạo thêm cognition.
            existing.last_input_at = max(existing.last_input_at, current)
            existing.freshness = max(existing.freshness, 0.72)
            return existing.to_dict(current)

        expected_update = tuple(
            str(x).strip() for x in (getattr(seed, "expected_update", ()) or ()) if str(x or "").strip()
        )[:8]
        development_mode = str(getattr(seed, "development_mode", "") or "").strip().lower()
        cause_focus = _compact(getattr(seed, "cause_semantic_focus", ""), 620)
        development_score = semantic_development_score(cause_focus, content, development_mode)
        development_required = bool(getattr(seed, "development_required", False))
        rumination_return = bool(getattr(seed, "rumination_return", False))
        source_refs = _refs(tuple(getattr(seed, "source_refs", ()) or ()))
        parent_concern_id = next((ref for ref in source_refs if str(ref).startswith("concern.")), "")
        material = MentalMaterial(
            material_id=material_id,
            material_kind=material_kind,
            content=content,
            cause_id=str(getattr(seed, "cause_id", "") or "").strip(),
            cause_kind=str(getattr(seed, "cause_kind", "") or "").strip(),
            motive_kind=str(getattr(seed, "runtime_motive_kind", "") or "share_internal_material").strip(),
            source_kind=str(getattr(seed, "source_kind", "") or "weak_association").strip(),
            source_refs=source_refs,
            topic_tags=tuple(str(x) for x in (getattr(seed, "topic_tags", ()) or ()) if str(x or "").strip())[:10],
            epistemic_mode=str(getattr(seed, "epistemic_mode", "") or "bounded_inference").strip(),
            open_loop=bool(getattr(seed, "open_loop", False)),
            cause_strength=_clamp01(getattr(seed, "cause_strength", 0.0)),
            quality=_clamp01(quality),
            confidence=_clamp01(getattr(seed, "confidence", 0.0)),
            uncertainty=_clamp01(getattr(seed, "uncertainty", 0.0)),
            created_at=current,
            last_input_at=current,
            ttl_seconds=max(90.0, min(1800.0, float(getattr(seed, "ttl_seconds", 600.0) or 600.0))),
            expected_update=expected_update,
            development_mode=development_mode,
            development_score=development_score,
            development_required=development_required,
            rumination_return=rumination_return,
            cause_semantic_focus=cause_focus,
            parent_concern_id=parent_concern_id,
            freshness=1.0,
        )
        self._materials[material.material_id] = material
        self._log(
            "info",
            "[mental material] born id=%s kind=%s cause=%s motive=%s strength=%.2f quality=%.2f rumination=%s development=%s/%.2f content=%s",
            material.material_id,
            material.material_kind,
            material.cause_kind,
            material.motive_kind,
            material.cause_strength,
            material.quality,
            str(material.rumination_return).lower(),
            material.development_mode or "none",
            material.development_score,
            _compact(material.content, 180),
        )
        # V70: một material sinh từ active concern là một private return thật.
        # Ghi receipt vào concern owner, nhưng không tạo evidence/speech pressure.
        if material.cause_kind == "active_concern" and material.rumination_return:
            concern_id = material.parent_concern_id
            note_return = getattr(getattr(self.host, "active_concern_runtime", None), "note_private_return", None)
            if concern_id and callable(note_return):
                try:
                    note_return(
                        concern_id,
                        material_id=material.material_id,
                        development_mode=material.development_mode,
                        development_score=material.development_score,
                        now=current,
                    )
                except Exception as exc:
                    self._log("debug", "[rumination v70] private return receipt degraded: %s", exc)
        self._prune(current)
        return material.to_dict(current)

    def _prune(self, now: float) -> None:
        dead: list[str] = []
        for material_id, material in self._materials.items():
            age = max(0.0, now - material.created_at)
            if age > material.ttl_seconds or material.lifecycle_state(now) == "fading":
                if material.effective_freshness(now) < 0.08 or age > material.ttl_seconds:
                    dead.append(material_id)
        for material_id in dead:
            self._materials.pop(material_id, None)

    def snapshot(self, *, now: float | None = None, limit: int = 12) -> tuple[dict[str, Any], ...]:
        current = float(now or time.time())
        self._prune(current)
        ranked = sorted(
            self._materials.values(),
            key=lambda item: (item.activation(current), item.expression_pull(current), item.created_at),
            reverse=True,
        )
        return tuple(item.to_dict(current) for item in ranked[: max(0, int(limit))])

    def wake_pressure(self, *, now: float | None = None) -> float:
        current = float(now or time.time())
        self._prune(current)
        # Material chỉ đánh thức self-turn nếu thật sự có pull sống. Một thought
        # 0.2 không nên khiến scheduler chạy vòng nặng chỉ vì nó tồn tại.
        pulls: list[float] = []
        for item in self._materials.values():
            # V70: worker đã quay lại concern nhưng chỉ restate thì material được
            # giữ private để audit/awareness, không được tạo wake loop chỉ vì
            # expression_pull legacy vẫn cao. Insight hợp lệ hoặc material mới
            # bình thường vẫn đánh thức như trước.
            if item.development_required and item.development_score < 0.62:
                pulls.append(0.0)
                continue
            pulls.append(max(item.expression_pull(current), item.concern_pull(current) * 0.78))
        return max(pulls, default=0.0)

    def project(
        self,
        *,
        now: float | None = None,
        limit: int = 8,
    ) -> tuple[tuple[ExecutiveAffordance, ...], tuple[ExecutiveAffordance, ...]]:
        """Trả hai projection riêng: concern ingress và expression ingress.

        Tách hai list là cố ý. Nếu dùng một affordance rồi để mọi downstream cùng
        đọc, ta lại vô tình biến "thought tồn tại" thành "thought muốn nói".
        """

        current = float(now or time.time())
        self._prune(current)
        ranked = sorted(
            self._materials.values(),
            key=lambda item: (item.activation(current), item.created_at),
            reverse=True,
        )
        concern_affordances: list[ExecutiveAffordance] = []
        expression_affordances: list[ExecutiveAffordance] = []

        for material in ranked[: max(1, int(limit))]:
            state = material.lifecycle_state(current)
            fresh = material.effective_freshness(current)
            activation = material.activation(current)
            concern_pull = material.concern_pull(current)
            expression_pull = material.expression_pull(current)
            if state == "fading":
                continue
            valid_development = bool(material.development_score >= 0.62)
            # Nếu concern đã consummate và worker chỉ paraphrase, material vẫn
            # được tồn tại private nhưng không được lẻn sang expression lane.
            expression_allowed = not material.development_required or valid_development

            common = dict(
                decision="candidate",
                kind="random_chat",
                topic=material.content,
                anchor_type="internal",
                anchor_id=material.material_id,
                evidence_refs=material.source_refs or (material.cause_id, material.material_id),
                requires_grounding=False,
                confidence=max(0.42, material.confidence),
                relevance=max(0.34, activation),
                urgency=min(0.72, 0.08 + 0.48 * expression_pull),
                tone="natural",
                source="mental_material",
                seed_id=material.material_id,
                seed_mode="eris_led",
                source_kind=material.source_kind,
                topic_tags=material.topic_tags,
                # Compatibility fields để CognitiveEvent/ConcernStore không cần
                # hiểu toàn bộ ontology V45 trong cùng một release.
                seed_event_kind={
                    "question": "curiosity_question",
                    "memory_callback": "memory_callback",
                    "association": "association",
                    "unfinished_thought": "unfinished_loop",
                    "playful_impulse": "playful_probe",
                    "self_reflection": "self_reflection",
                    "hunch": "speculation",
                    "opinion": "opinion",
                }.get(material.material_kind, "thought"),
                seed_epistemic_mode=material.epistemic_mode,
                seed_open_loop=material.open_loop,
                desired_response=(),
                eris_motive_kind=_legacy_motive(material.motive_kind, material.material_kind),
                eris_motive_why_now=f"causal_motive:{material.cause_id}",
                personal_stake=material.cause_strength,
                authenticity=max(0.50, material.quality),
                daring=0.18,
                uncertainty=material.uncertainty,
                seed_intrusion_risk=0.12,
                face_risk=0.08,
                recovery_available=True,
                seed_quality_score=material.quality,
                seed_specificity=material.quality,
                seed_motive_strength=material.cause_strength,
                seed_semantic_completeness=material.quality,
                semantic_development_mode=material.development_mode,
                semantic_development_score=material.development_score,
                semantic_development_required=material.development_required,
                rumination_return=material.rumination_return,
                semantic_parent_concern_id=material.parent_concern_id,
            )

            if (
                material.quality >= 0.58
                and expression_allowed
                and (
                    concern_pull >= 0.58
                    # V70: semantic development thật tự nó là một cognitive event
                    # đáng cập nhật concern cha, kể cả material không có open-loop
                    # đủ mạnh để vượt concern_pull legacy.
                    or (material.cause_kind == "active_concern" and valid_development)
                )
            ):
                candidate = SocialSpeechCandidate(
                    **common,
                    speech_act="internal_material",
                    reason=(
                        f"mental_material_concern:{material.material_kind}:"
                        f"cause={material.cause_kind}:pull={concern_pull:.2f}"
                    ),
                )
                concern_affordances.append(ExecutiveAffordance(
                    affordance_id=f"mental-material-concern:{material.material_id}",
                    owner="mental_material",
                    revision=int(material.created_at * 1000),
                    candidate=candidate,
                    claim_required=False,
                    expires_at=current + 60.0,
                    metadata={
                        "mental_material": True,
                        "material_id": material.material_id,
                        "material_kind": material.material_kind,
                        "cause_id": material.cause_id,
                        "cause_kind": material.cause_kind,
                        "lifecycle_state": state,
                        "expression_ready": False,
                    },
                ))
                # Affordance có thể xuất hiện lại ở tick sau, nhưng CognitiveEvent
                # ledger V42 consume đúng một lần. Giữ retry-safe nếu ConcernStore
                # tạm unavailable thay vì đánh dấu "đã promote" trước receipt.

            if expression_pull >= 0.60 and expression_allowed:
                candidate = SocialSpeechCandidate(
                    **common,
                    speech_act=_material_speech_act(material.material_kind, expected_update=material.expected_update),
                    reason=(
                        f"mental_material_expression:{material.material_kind}:"
                        f"cause={material.cause_kind}:pull={expression_pull:.2f}"
                    ),
                )
                expression_affordances.append(ExecutiveAffordance(
                    affordance_id=f"mental-material-expression:{material.material_id}",
                    owner="mental_material",
                    revision=int(material.last_input_at * 1000),
                    candidate=candidate,
                    claim_required=False,
                    expires_at=current + 60.0,
                    metadata={
                        "mental_material": True,
                        "material_id": material.material_id,
                        "material_kind": material.material_kind,
                        "cause_id": material.cause_id,
                        "cause_kind": material.cause_kind,
                        "lifecycle_state": state,
                        "expression_ready": True,
                        "expected_update": list(material.expected_update),
                    },
                ))

        self._log_top(current)
        return tuple(concern_affordances), tuple(expression_affordances)

    def note_expressed(self, material_id: str, *, now: float | None = None) -> bool:
        material = self._materials.get(str(material_id or "").strip())
        if material is None:
            return False
        current = float(now or time.time())
        material.expressed_at = current
        material.satisfaction = max(material.satisfaction, 0.82)
        material.freshness *= 0.58
        self._log(
            "info",
            "[mental material] expressed id=%s kind=%s satisfaction=%.2f",
            material.material_id,
            material.material_kind,
            material.satisfaction,
        )
        return True

    def _log_top(self, now: float) -> None:
        if not self._materials:
            signature = "none"
        else:
            top = max(self._materials.values(), key=lambda item: item.activation(now))
            payload = top.to_dict(now)
            signature = f"{top.material_id}:{payload['state']}:{round(float(payload['activation']),1)}"
            if signature != self._last_log_signature:
                self._log(
                    "info",
                    "[mental material] top id=%s kind=%s state=%s activation=%.2f concern=%.2f express=%.2f fresh=%.2f cause=%s content=%s",
                    top.material_id,
                    top.material_kind,
                    payload["state"],
                    payload["activation"],
                    payload["concern_pull"],
                    payload["expression_pull"],
                    payload["freshness"],
                    top.cause_kind,
                    _compact(top.content, 180),
                )
        self._last_log_signature = signature


__all__ = ["MENTAL_MATERIAL_RUNTIME_VERSION", "MentalMaterialRuntime"]
