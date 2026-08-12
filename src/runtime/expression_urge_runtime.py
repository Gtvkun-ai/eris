# -*- coding: utf-8 -*-
"""Content-first initiative cho ERIS V44.

V43 đã có mood sống và V42 đã có CognitiveEvent/ActiveConcern. V44 không thêm
một kho "ham muốn" mới. Module này chỉ giữ một projection ngắn hạn của những thứ
Eris *đã có nội dung để muốn biểu đạt*.

Luật quan trọng:
- connection/social pressure KHÔNG tự sinh lời thoại;
- contact_bid/user_probe chung chung không phải content, nên không được thành speech;
- một thought/concern/seed có nội dung có thể tạo urge và urge có thể sống qua
  nhiều tick nếu Neuro chọn silence;
- cùng ý được paraphrase lại không tạo thêm urge, chỉ làm freshness giảm nếu
  không có evidence mới;
- public commit làm satisfaction tăng và pressure hạ. Surface text không feed
  ngược thành một event mới.

Nói ngắn: motive trả lời "tôi muốn gần bạn", urge trả lời "tôi muốn mang *cái gì*
sang phía bạn". Neuro chỉ cân lớp thứ hai khi quyết định phát ngôn.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from cortex.active_concern import clamp01, compact, semantic_overlap
from runtime.ai_orchestrated.affordance import ExecutiveAffordance
from runtime.ai_orchestrated.social_initiative import SocialSpeechCandidate


EXPRESSION_URGE_VERSION = "eris.initiative.v44.contentful_urge"

_GENERIC_SOCIAL_ACTS = {
    "contact_bid",
    "user_probe",
    "social_check_in",
    "curiosity_bid",
}
_GENERIC_TOPIC_MARKERS = (
    "ask one low-pressure",
    "ask one open",
    "make one low-pressure contact",
    "helps eris understand the user better",
    "tạo hoặc duy trì một nhịp tiếp xúc",
    "thăm dò một điều còn chưa biết về user",
)
_STRUCTURED_OWNERS = {
    "social_continuation",
    "conversation_arc",
    "neuro_continuation",
    "social_agenda",
}


def _refs(values: Iterable[Any], limit: int = 12) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(x) for x in values if str(x or "").strip()))[:limit]


def _digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _candidate_contentful(candidate: Any) -> bool:
    topic = compact(getattr(candidate, "topic", ""), 600)
    if len(topic) < 18:
        return False
    act = str(getattr(candidate, "speech_act", "") or "").strip().lower()
    folded = topic.casefold()
    if act in _GENERIC_SOCIAL_ACTS and any(marker in folded for marker in _GENERIC_TOPIC_MARKERS):
        return False
    # Một generic contact/probe không có seed/evidence cụ thể vẫn chỉ là mong muốn
    # tiếp xúc. Giữ nó làm drive, không cho nó mặc áo "nội dung" để qua Neuro.
    if act in _GENERIC_SOCIAL_ACTS:
        seed_id = str(getattr(candidate, "seed_id", "") or "").strip()
        refs = _refs(getattr(candidate, "evidence_refs", ()) or ())
        if not seed_id and len(refs) <= 1:
            return False
    return True


def _motive_from_candidate(candidate: Any) -> str:
    declared = str(getattr(candidate, "eris_motive_kind", "") or "").strip().lower()
    act = str(getattr(candidate, "speech_act", "") or "").strip().lower()
    kind = str(getattr(candidate, "seed_event_kind", "") or getattr(candidate, "kind", "") or "").strip().lower()
    blob = f"{declared} {act} {kind}"
    if any(token in blob for token in ("play", "tease", "banter", "amuse", "joke", "challenge")):
        return "play"
    if any(token in blob for token in ("revisit", "memory", "callback", "continuation")):
        return "revisit"
    if any(token in blob for token in ("clarif", "repair", "correct", "be_understood")):
        return "clarify"
    if any(token in blob for token in ("contribute", "result", "finding", "discovery")):
        return "contribute"
    if any(token in blob for token in ("know", "explore", "curiosity", "question", "probe", "investigat")):
        return "explore"
    return "share"


def _speech_act_for(motive: str, original: str = "") -> str:
    """Chọn hình thức biểu đạt, không biến mọi curiosity thành phỏng vấn user."""
    original = str(original or "").strip().lower()
    if motive == "play":
        return "playful_observation"
    if motive == "revisit":
        return "memory_callback"
    if motive == "clarify":
        return "self_clarification"
    if motive == "contribute":
        return original or "share_grounded_runtime_finding"
    if motive == "explore":
        # Curiosity trước hết là thứ Eris đang nghĩ. Surface có thể để ngỏ một
        # câu hỏi nếu semantic intent thật sự cần user input, nhưng mặc định không
        # biến mỗi khoảng tò mò thành questionnaire.
        return "share_self_originated_thought"
    return original if original and original not in _GENERIC_SOCIAL_ACTS else "share_self_originated_thought"


@dataclass(slots=True)
class ExpressionUrge:
    urge_id: str
    semantic_key: str
    motive: str
    content: str
    source: str
    evidence_refs: tuple[str, ...]
    concern_id: str = ""
    base_strength: float = 0.0
    freshness: float = 0.0
    satisfaction: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    last_input_at: float = 0.0
    last_expressed_at: float = 0.0
    echo_count: int = 0
    original_speech_act: str = ""
    confidence: float = 0.72
    relevance: float = 0.60
    intrusion_risk: float = 0.14

    def pressure(self, *, now: float, relational: Mapping[str, Any], affect: Mapping[str, Any]) -> float:
        age = max(0.0, float(now) - self.created_at)
        since_input = max(0.0, float(now) - self.last_input_at)
        # Urge được giữ lại một lúc có thể tích lực, nhưng freshness đồng thời
        # phai. Vì thế một ý có cơ hội "chín" chứ không tăng vô hạn như timer.
        hold_gain = min(0.18, age / 240.0 * 0.18) * (0.45 + 0.55 * self.freshness)
        stale_decay = min(0.26, max(0.0, since_input - 180.0) / 900.0 * 0.26)

        connection = clamp01(relational.get("connection_pressure", 0.0))
        outreach = clamp01(relational.get("outreach_drive", 0.0))
        social_energy = clamp01(affect.get("social_energy", affect.get("social", 0.5)), 0.5)
        curiosity = clamp01(affect.get("curiosity", 0.0))
        playful = clamp01(affect.get("playful_pull", affect.get("play", 0.0)))

        relational_boost = 0.12 * connection + 0.10 * outreach + 0.06 * social_energy
        motive_boost = 0.0
        if self.motive == "explore":
            motive_boost = 0.10 * curiosity
        elif self.motive == "play":
            motive_boost = 0.12 * playful
        elif self.motive in {"share", "revisit"}:
            motive_boost = 0.04 * curiosity

        return clamp01(
            self.base_strength
            + hold_gain
            + relational_boost
            + motive_boost
            - stale_decay
            - 0.62 * self.satisfaction
            - min(0.22, self.echo_count * 0.055)
        )

    def to_dict(self, *, now: float, relational: Mapping[str, Any], affect: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "urge_id": self.urge_id,
            "motive": self.motive,
            "content": self.content,
            "source": self.source,
            "concern_id": self.concern_id,
            "pressure": round(self.pressure(now=now, relational=relational, affect=affect), 3),
            "freshness": round(self.freshness, 3),
            "satisfaction": round(self.satisfaction, 3),
            "echo_count": self.echo_count,
            "age_seconds": round(max(0.0, now - self.created_at), 1),
            "evidence_refs": list(self.evidence_refs),
        }


class ExpressionUrgeRuntime:
    """Projection ngắn hạn: content -> desire-to-express -> Neuro."""

    def __init__(self, host: Any, *, logger: Any | None = None) -> None:
        self.host = host
        self.logger = logger or getattr(host, "logger", None)
        self._urges: dict[str, ExpressionUrge] = {}
        self._seen_inputs: dict[str, float] = {}
        self._last_log_signature = ""

    def _log(self, level: str, message: str, *args: Any) -> None:
        fn = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(fn):
            fn(message, *args)

    def _find_similar(self, content: str) -> ExpressionUrge | None:
        best = None
        score = 0.0
        for urge in self._urges.values():
            current = semantic_overlap(content, urge.content)
            if current > score:
                best, score = urge, current
        return best if score >= 0.78 else None

    @staticmethod
    def _base_from_candidate(candidate: Any) -> float:
        relevance = clamp01(getattr(candidate, "relevance", 0.0))
        confidence = clamp01(getattr(candidate, "confidence", 0.0))
        stake = clamp01(getattr(candidate, "personal_stake", 0.0))
        quality = clamp01(getattr(candidate, "seed_quality_score", 0.0))
        return clamp01(0.18 + 0.30 * relevance + 0.16 * confidence + 0.16 * stake + 0.10 * quality)

    def _ingest_content(
        self,
        *,
        input_key: str,
        content: str,
        motive: str,
        source: str,
        evidence_refs: Sequence[Any],
        now: float,
        base_strength: float,
        freshness: float,
        concern_id: str = "",
        original_speech_act: str = "",
        confidence: float = 0.72,
        relevance: float = 0.60,
        intrusion_risk: float = 0.14,
    ) -> ExpressionUrge | None:
        content = compact(content, 520)
        if len(content) < 18:
            return None
        # Cùng input chỉ được tác động một lần. Scheduler nhìn lại không phải là
        # một trải nghiệm mới, cùng invariant với CognitiveEvent V42.
        if input_key in self._seen_inputs:
            similar = self._find_similar(content)
            return similar
        self._seen_inputs[input_key] = now

        refs = _refs(evidence_refs)
        similar = self._find_similar(content)
        if similar is not None:
            old_refs = set(similar.evidence_refs)
            new_evidence = bool(set(refs) - old_refs)
            if new_evidence:
                similar.base_strength = clamp01(max(similar.base_strength, base_strength) + 0.07)
                similar.freshness = clamp01(max(similar.freshness, freshness) + 0.08)
                similar.echo_count = max(0, similar.echo_count - 1)
                similar.updated_at = now
                similar.last_input_at = now
                similar.evidence_refs = _refs((*similar.evidence_refs, *refs))
                if concern_id:
                    similar.concern_id = concern_id
            else:
                # Paraphrase cùng evidence không được tự phong thành novelty.
                similar.echo_count += 1
                similar.freshness = clamp01(similar.freshness * 0.86)
                similar.base_strength = clamp01(similar.base_strength * 0.97)
                similar.last_input_at = now
            return similar

        urge_id = f"urge:{_digest(f'{source}|{content}')}"
        urge = ExpressionUrge(
            urge_id=urge_id,
            semantic_key=_digest(content),
            motive=motive,
            content=content,
            source=source,
            evidence_refs=refs,
            concern_id=concern_id,
            base_strength=clamp01(base_strength),
            freshness=clamp01(freshness),
            satisfaction=0.0,
            created_at=now,
            updated_at=now,
            last_input_at=now,
            original_speech_act=original_speech_act,
            confidence=clamp01(confidence, 0.72),
            relevance=clamp01(relevance, 0.60),
            intrusion_risk=clamp01(intrusion_risk, 0.14),
        )
        self._urges[urge_id] = urge
        return urge

    def observe(
        self,
        affordances: Sequence[Any],
        *,
        active_concerns: Sequence[Mapping[str, Any]] = (),
        now: float | None = None,
    ) -> None:
        current = float(now or time.time())
        for affordance in tuple(affordances or ()):
            candidate = getattr(affordance, "candidate", None)
            if candidate is None or not _candidate_contentful(candidate):
                continue
            owner = str(getattr(affordance, "owner", "") or "")
            if owner in _STRUCTURED_OWNERS or str(getattr(candidate, "kind", "") or "") == "force_speak":
                continue
            content = str(getattr(candidate, "topic", "") or "")
            motive = _motive_from_candidate(candidate)
            self._ingest_content(
                input_key=f"aff:{str(getattr(affordance, 'affordance_id', '') or _digest(content))}",
                content=content,
                motive=motive,
                source=owner or str(getattr(candidate, "source", "") or "affordance"),
                evidence_refs=tuple(getattr(candidate, "evidence_refs", ()) or ()),
                now=current,
                base_strength=self._base_from_candidate(candidate),
                freshness=max(0.32, clamp01(getattr(candidate, "seed_specificity", 0.0))),
                original_speech_act=str(getattr(candidate, "speech_act", "") or ""),
                confidence=clamp01(getattr(candidate, "confidence", 0.72), 0.72),
                relevance=clamp01(getattr(candidate, "relevance", 0.60), 0.60),
                intrusion_risk=max(
                    clamp01(getattr(candidate, "seed_intrusion_risk", 0.0)),
                    clamp01(getattr(candidate, "intrusion_risk", 0.0)),
                ),
            )

        # ActiveConcern là nguồn continuity. Concern không cần phải sinh từ seed;
        # memory/agenda/thought thật cũng có thể trở thành một urge có nội dung.
        for raw in tuple(active_concerns or ()):
            concern = dict(raw)
            content = compact(concern.get("subject", ""), 520)
            state = str(concern.get("state") or "simmering")
            novelty = clamp01(concern.get("novelty", 0.0))
            speech = clamp01(concern.get("speech_pressure", 0.0))
            activation = clamp01(concern.get("activation", 0.0))
            if len(content) < 18 or state in {"blocked", "habituated"}:
                continue
            if max(speech, activation * novelty) < 0.16:
                continue
            cid = str(concern.get("concern_id") or "")
            meta = dict(concern.get("metadata") or {})
            event_count = int(meta.get("event_count", 0) or 0)
            mutation_count = int(concern.get("mutation_count", 0) or 0)
            sources = " ".join(str(x) for x in tuple(concern.get("source_kinds", ()) or ())).lower()
            motive = "revisit" if float(concern.get("age_seconds", 0.0) or 0.0) >= 90.0 else "share"
            if "curiosity" in sources or "question" in sources or "?" in content:
                motive = "explore"
            if "agenda:" in sources:
                motive = "contribute"
            self._ingest_content(
                input_key=f"concern:{cid}:{event_count}:{mutation_count}",
                content=content,
                motive=motive,
                source="active_concern",
                evidence_refs=tuple(concern.get("evidence_refs", ()) or ()),
                now=current,
                base_strength=clamp01(0.16 + 0.46 * speech + 0.20 * activation + 0.12 * novelty),
                freshness=max(0.18, novelty),
                concern_id=cid,
                original_speech_act="",
                confidence=clamp01(0.52 + 0.30 * activation),
                relevance=clamp01(0.42 + 0.42 * max(speech, activation)),
                intrusion_risk=clamp01(concern.get("interruption_cost", 0.0)) * 0.55,
            )
        self._prune(current)

    def _prune(self, now: float) -> None:
        # Projection sống theo session. Không biến một urge thoáng qua thành ký ức
        # mới chỉ vì nó chưa được nói.
        dead: list[str] = []
        for urge_id, urge in self._urges.items():
            age = max(0.0, now - urge.created_at)
            stale = max(0.0, now - urge.last_input_at)
            if urge.satisfaction >= 0.88 or age > 1800.0 or (stale > 720.0 and urge.freshness < 0.24):
                dead.append(urge_id)
        for urge_id in dead:
            self._urges.pop(urge_id, None)
        # Ledger input chỉ cần đủ dài để một scheduler/session không replay.
        for key, seen_at in tuple(self._seen_inputs.items()):
            if now - seen_at > 3600.0:
                self._seen_inputs.pop(key, None)

    def wake_pressure(self, *, now: float | None = None) -> float:
        current = float(now or time.time())
        self._prune(current)
        # Cheap path chưa cần đọc relationship/mood. Chỉ cần biết có một ý đang
        # đủ lực để TemporalMind nhìn lại. Modulation đầy đủ diễn ra sau wake.
        return max(
            (
                clamp01(
                    urge.base_strength
                    + min(0.16, max(0.0, current - urge.created_at) / 240.0 * 0.16)
                    - 0.60 * urge.satisfaction
                    - min(0.18, urge.echo_count * 0.05)
                )
                for urge in self._urges.values()
            ),
            default=0.0,
        )

    def shape_affordances(
        self,
        affordances: Sequence[Any],
        *,
        active_concerns: Sequence[Mapping[str, Any]] = (),
        relational: Mapping[str, Any] | None = None,
        affect: Mapping[str, Any] | None = None,
        now: float | None = None,
        limit: int = 3,
    ) -> tuple[Any, ...]:
        current = float(now or time.time())
        rel = dict(relational or {})
        aff = dict(affect or {})
        self.observe(affordances, active_concerns=active_concerns, now=current)

        # Structured continuations/task bindings giữ nguyên identity/claim owner.
        # Generic social openers bị loại; relation chỉ còn là lực modulation.
        preserved: list[Any] = []
        for affordance in tuple(affordances or ()):
            candidate = getattr(affordance, "candidate", None)
            owner = str(getattr(affordance, "owner", "") or "")
            if candidate is None:
                continue
            act = str(getattr(candidate, "speech_act", "") or "").strip().lower()
            kind = str(getattr(candidate, "kind", "") or "").strip().lower()
            if kind == "force_speak" or owner in _STRUCTURED_OWNERS:
                preserved.append(affordance)
                continue
            if act in _GENERIC_SOCIAL_ACTS and not _candidate_contentful(candidate):
                continue
            # Contentful seed/private candidate sẽ được đại diện bằng urge phía
            # dưới để không có hai coalition cùng một ý nhưng khác owner.

        ranked = sorted(
            self._urges.values(),
            key=lambda urge: (
                urge.pressure(now=current, relational=rel, affect=aff),
                urge.freshness,
                urge.updated_at,
            ),
            reverse=True,
        )
        emitted = 0
        for urge in ranked:
            pressure = urge.pressure(now=current, relational=rel, affect=aff)
            if pressure < 0.34 or urge.freshness < 0.12:
                continue
            speech_act = _speech_act_for(urge.motive, urge.original_speech_act)
            candidate = SocialSpeechCandidate(
                decision="candidate",
                kind="random_chat",
                topic=urge.content,
                speech_act=speech_act,
                anchor_type="internal",
                anchor_id=urge.concern_id or urge.urge_id,
                evidence_refs=urge.evidence_refs or ((urge.concern_id,) if urge.concern_id else (urge.urge_id,)),
                requires_grounding=False,
                confidence=max(0.50, urge.confidence),
                relevance=max(0.42, urge.relevance),
                urgency=clamp01(0.12 + 0.46 * pressure),
                tone="natural",
                reason=f"expression_urge:{urge.motive}:pressure={pressure:.2f}",
                source="expression_urge",
                eris_motive_kind=f"want_to_{urge.motive}",
                eris_motive_why_now="a contentful urge remained active long enough to be worth expressing",
                personal_stake=pressure,
                authenticity=1.0,
                uncertainty=clamp01(1.0 - urge.confidence),
                seed_intrusion_risk=urge.intrusion_risk,
                face_risk=clamp01(0.08 + 0.18 * urge.intrusion_risk),
                recovery_available=True,
                expression_urge_id=urge.urge_id,
                expression_pressure=pressure,
                expression_freshness=urge.freshness,
                expression_satisfaction=urge.satisfaction,
                expression_motive=urge.motive,
            )
            preserved.append(ExecutiveAffordance(
                affordance_id=f"expression-urge:{urge.urge_id}",
                owner="expression_urge",
                revision=int(urge.updated_at * 1000.0),
                candidate=candidate,
                claim_required=False,
                expires_at=current + 75.0,
                metadata={
                    "expression_urge": True,
                    "urge_id": urge.urge_id,
                    "concern_id": urge.concern_id,
                    "motive": urge.motive,
                },
            ))
            emitted += 1
            if emitted >= max(1, int(limit)):
                break

        self._log_state(current, rel, aff)
        return tuple(preserved)

    def _log_state(self, now: float, relational: Mapping[str, Any], affect: Mapping[str, Any]) -> None:
        if not self._urges:
            signature = "none"
        else:
            ranked = sorted(
                self._urges.values(),
                key=lambda urge: urge.pressure(now=now, relational=relational, affect=affect),
                reverse=True,
            )
            top = ranked[0]
            p = top.pressure(now=now, relational=relational, affect=affect)
            signature = f"{top.urge_id}:{round(p,1)}:{round(top.satisfaction,1)}:{top.echo_count}"
            if signature != self._last_log_signature:
                self._log(
                    "info",
                    "[expression urge] top id=%s motive=%s pressure=%.2f fresh=%.2f satisfaction=%.2f echoes=%s source=%s content=%s",
                    top.urge_id,
                    top.motive,
                    p,
                    top.freshness,
                    top.satisfaction,
                    top.echo_count,
                    top.source,
                    compact(top.content, 180),
                )
        self._last_log_signature = signature

    def note_expressed(self, urge_id: str, *, now: float | None = None) -> bool:
        urge = self._urges.get(str(urge_id or "").strip())
        if urge is None:
            return False
        current = float(now or time.time())
        urge.last_expressed_at = current
        urge.updated_at = current
        urge.satisfaction = clamp01(max(urge.satisfaction, 0.76))
        urge.base_strength = clamp01(urge.base_strength * 0.52)
        urge.freshness = clamp01(urge.freshness * 0.72)
        self._log(
            "info",
            "[expression urge] expressed id=%s satisfaction=%.2f remaining=%.2f",
            urge.urge_id,
            urge.satisfaction,
            urge.base_strength,
        )
        return True

    def snapshot(
        self,
        *,
        now: float | None = None,
        relational: Mapping[str, Any] | None = None,
        affect: Mapping[str, Any] | None = None,
        limit: int = 8,
    ) -> tuple[dict[str, Any], ...]:
        current = float(now or time.time())
        rel = dict(relational or {})
        aff = dict(affect or {})
        self._prune(current)
        ranked = sorted(
            self._urges.values(),
            key=lambda urge: urge.pressure(now=current, relational=rel, affect=aff),
            reverse=True,
        )
        return tuple(urge.to_dict(now=current, relational=rel, affect=aff) for urge in ranked[: max(0, int(limit))])


__all__ = ["EXPRESSION_URGE_VERSION", "ExpressionUrge", "ExpressionUrgeRuntime"]
