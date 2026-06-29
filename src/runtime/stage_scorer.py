# -*- coding: utf-8 -*-
"""stage_scorer.py - van dieu ap giua cognition va man dien.

StageScorer khong sinh cau moi.  No chi cham candidate/Decision da co va quyet
dinh surface mode: suppress, body_only, short, repair, full.  Cach nay giu LLM
nho duoc sang tao, nhung stage co quyen tu choi neu cau vuot budget/evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from runtime.director_context import DecisionMode, DirectorContext


_WORD_RE = re.compile(r"\S+")
_PERCEPTION_CLAIM_RE = re.compile(
    r"\b("
    r"tôi thấy|toi thay|tôi nhìn|toi nhin|trên màn hình|tren man hinh|"
    r"màn hình của ngài|man hinh cua ngai|cửa sổ|cua so|tab |file này|file nay"
    r")\b",
    re.I,
)
_ACTION_CLAIM_RE = re.compile(
    r"\b("
    r"tôi đã làm|toi da lam|tôi đã sửa|toi da sua|tôi đã chạy|toi da chay|"
    r"tôi đã mở|toi da mo|tôi vừa|toi vua|đã hoàn tất|da hoan tat"
    r")\b",
    re.I,
)
_STAGE_TAG_RE = re.compile(r"\((?:cười|cuoi|thở dài|tho dai|nhìn|nhin|nghiêng|nghieng|blink|smile)[^)]+\)", re.I)


@dataclass(frozen=True, slots=True)
class CandidateUtterance:
    text: str
    should_speak: bool
    confidence: float
    intent: str
    delivery_hint: str = ""
    nonverbal_cue: str = ""
    stage_motion: str = ""
    evidence_refs: tuple[str, ...] = ()
    repair_mode: str = ""

    @classmethod
    def from_decision_payload(cls, decision: Any, payload: Mapping[str, Any]) -> "CandidateUtterance":
        return cls(
            text=str(payload.get("text", getattr(decision, "text", "")) or ""),
            should_speak=bool(payload.get("should_speak", getattr(decision, "should_speak", True))),
            confidence=_safe_float(payload.get("confidence", getattr(decision, "confidence", 0.0)), 0.0),
            intent=str(payload.get("intent", getattr(decision, "intent", "")) or ""),
            delivery_hint=str(payload.get("delivery_hint", getattr(decision, "delivery_hint", "")) or ""),
            nonverbal_cue=str(payload.get("nonverbal_cue", getattr(decision, "nonverbal_cue", "")) or ""),
            stage_motion=str(payload.get("stage_motion", getattr(decision, "stage_motion", "")) or ""),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CandidateUtterance":
        """Nhận candidate từ JSON contract mới.

        LLM có thể trả item dạng string ở giai đoạn chuyển tiếp; caller nên bọc
        thành {"text": "..."} trước khi gọi hàm này.
        """

        refs = data.get("evidence_refs", ())
        if isinstance(refs, str):
            refs_tuple = (refs,)
        elif isinstance(refs, (list, tuple)):
            refs_tuple = tuple(str(item) for item in refs if str(item or "").strip())
        else:
            refs_tuple = ()
        return cls(
            text=str(data.get("text", "") or ""),
            should_speak=bool(data.get("should_speak", True)),
            confidence=_safe_float(data.get("confidence", 0.0), 0.0),
            intent=str(data.get("intent", "") or ""),
            delivery_hint=str(data.get("delivery_hint", "") or ""),
            nonverbal_cue=str(data.get("nonverbal_cue", "") or ""),
            stage_motion=str(data.get("stage_motion", "") or ""),
            evidence_refs=refs_tuple,
            repair_mode=str(data.get("repair_mode", "") or ""),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "should_speak": self.should_speak,
            "confidence": self.confidence,
            "intent": self.intent,
            "delivery_hint": self.delivery_hint,
            "nonverbal_cue": self.nonverbal_cue,
            "stage_motion": self.stage_motion,
            "evidence_refs": list(self.evidence_refs),
            "repair_mode": self.repair_mode,
        }


@dataclass(frozen=True, slots=True)
class StageScore:
    speakable: bool
    liveliness: float
    scene_fit: float
    relation_fit: float
    performance_fit: float
    tts_fit: float
    clip_risk: float
    evidence_ok: bool
    decision: DecisionMode
    reason: str
    policy_tags: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["policy_tags"] = list(self.policy_tags)
        return data


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    return re.sub(r"\s+", " ", value).strip()


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(str(text or "")))


class EvidenceAuthority:
    """Kiem tra nhanh cac claim bi cam theo ladder observed/tool/inferred."""

    def evaluate_text(self, text: str, context: DirectorContext) -> tuple[bool, tuple[str, ...]]:
        normalized = _normalize(text)
        reasons: list[str] = []
        forbidden = set(context.forbidden_claims)
        if "screen_claim_without_sensor" in forbidden and _PERCEPTION_CLAIM_RE.search(normalized):
            reasons.append("screen_claim_without_sensor")
        if "system_action_without_tool" in forbidden and _ACTION_CLAIM_RE.search(normalized):
            reasons.append("system_action_without_tool")
        return (not reasons, tuple(reasons))


class StageScorer:
    """Rule-based scorer dau tien cho Director -> Stage.

    Chat co user text la khu vuc nhay cam: scorer chi annotate, khong nen tu
    suppress tru khi candidate da rong/should_speak=false.  Autonomous thi can
    nghiem hon de Eris khong pha focus bang filler.
    """

    LOW_INTRUSION_SCENES = {"coding_partner", "study_partner", "social_sidecar"}

    def __init__(self, *, evidence_authority: EvidenceAuthority | None = None) -> None:
        self.evidence_authority = evidence_authority or EvidenceAuthority()

    def score_decision(
        self,
        decision: Any,
        *,
        payload: Mapping[str, Any],
        context: DirectorContext,
        channel: str | None = None,
    ) -> StageScore:
        candidate = CandidateUtterance.from_decision_payload(decision, payload)
        return self.score_candidate(candidate, context=context, channel=channel)

    def choose_best_candidate(
        self,
        candidates: list[CandidateUtterance],
        *,
        context: DirectorContext,
        channel: str | None = None,
    ) -> tuple[CandidateUtterance | None, StageScore | None]:
        """Chọn candidate tốt nhất theo score tách metric.

        Điểm tổng chỉ dùng để xếp hạng. Quyền nói cuối vẫn nằm trong
        StageScore.decision, nên candidate thắng vẫn có thể là body_only/suppress.
        """

        best_pair: tuple[CandidateUtterance, StageScore] | None = None
        best_value = -999.0
        for candidate in candidates:
            score = self.score_candidate(candidate, context=context, channel=channel)
            value = self._ranking_value(candidate, score)
            if value > best_value:
                best_value = value
                best_pair = (candidate, score)
        if best_pair is None:
            return None, None
        return best_pair

    def choose_best_from_payload(
        self,
        raw_candidates: object,
        *,
        context: DirectorContext,
        channel: str | None = None,
    ) -> tuple[CandidateUtterance | None, StageScore | None]:
        """Parse list candidate mềm để hỗ trợ cả schema cũ và mới."""

        candidates: list[CandidateUtterance] = []
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if isinstance(item, str):
                    candidates.append(CandidateUtterance.from_mapping({"text": item, "confidence": 0.5}))
                elif isinstance(item, Mapping):
                    candidates.append(CandidateUtterance.from_mapping(item))
        return self.choose_best_candidate(candidates, context=context, channel=channel)

    def score_candidate(
        self,
        candidate: CandidateUtterance,
        *,
        context: DirectorContext,
        channel: str | None = None,
    ) -> StageScore:
        text = str(candidate.text or "").strip()
        words = _word_count(text)
        tags: list[str] = []
        evidence_ok, evidence_reasons = self.evidence_authority.evaluate_text(text, context)
        tags.extend(evidence_reasons)
        budget_ratio = words / max(1, context.speak_budget_words)
        clip_risk = _clamp01((budget_ratio - 0.9) / 1.4)
        tts_fit = self._tts_fit(text, words=words, budget=context.speak_budget_words)
        liveliness = self._liveliness(text, candidate)
        scene_fit = self._scene_fit(candidate, context, words=words)
        relation_fit = self._relation_fit(context)
        performance_fit = self._performance_fit(candidate)
        speakable = bool(candidate.should_speak and text and evidence_ok and tts_fit >= 0.35)

        channel_name = str(channel or "").strip().lower()
        interactive_chat = channel_name == "chat"
        if not candidate.should_speak or not text:
            decision_mode: DecisionMode = "body_only" if candidate.stage_motion or candidate.nonverbal_cue else "suppress"
            reason = "candidate_empty_or_non_speech"
        elif not evidence_ok:
            decision_mode = "repair" if interactive_chat else "suppress"
            reason = ",".join(evidence_reasons) or "evidence_block"
        elif budget_ratio > 2.2 and not interactive_chat:
            decision_mode = "suppress"
            reason = "autonomous_text_far_over_budget"
        elif budget_ratio > 1.25:
            decision_mode = "short"
            reason = "text_over_speak_budget"
        elif context.scene_mode.name in self.LOW_INTRUSION_SCENES and channel_name not in {"chat", "force_speak"} and liveliness < 0.38:
            decision_mode = "body_only"
            reason = "low_intrusion_scene_with_weak_line"
        elif not speakable:
            decision_mode = "body_only"
            reason = "not_speakable_but_body_presence_allowed"
        else:
            decision_mode = "full"
            reason = "stage_ok"

        if _STAGE_TAG_RE.search(text):
            tags.append("stage_tag_in_text")
            performance_fit = min(performance_fit, 0.42)
            if decision_mode == "full":
                decision_mode = "repair"
                reason = "stage_tag_should_be_metadata"

        return StageScore(
            speakable=speakable,
            liveliness=round(liveliness, 3),
            scene_fit=round(scene_fit, 3),
            relation_fit=round(relation_fit, 3),
            performance_fit=round(performance_fit, 3),
            tts_fit=round(tts_fit, 3),
            clip_risk=round(clip_risk, 3),
            evidence_ok=evidence_ok,
            decision=decision_mode,
            reason=reason,
            policy_tags=tuple(dict.fromkeys(tags)),
        )

    def apply_to_payload(
        self,
        payload: dict[str, Any],
        score: StageScore,
        *,
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Can thiep nhe vao payload cu truoc StageFrameBuilder.

        Chat cua user chi nhan metadata; autonomous/presence moi bi keo ve
        body_only/suppress.  Neu sau nay can strict hon, doi policy o day.
        """

        payload["stage_score"] = score.to_payload()
        channel_name = str(channel or "").strip().lower()
        if channel_name == "chat":
            return payload
        if score.decision == "suppress":
            payload["text"] = ""
            payload["should_speak"] = False
            payload["parse_mode"] = f"{payload.get('parse_mode', 'json')}:director_suppress"
        elif score.decision == "body_only":
            payload["text"] = ""
            payload["should_speak"] = False
            payload.setdefault("stage_motion", "blink_slow")
            payload["parse_mode"] = f"{payload.get('parse_mode', 'json')}:director_body_only"
        return payload

    def apply_candidate_to_payload(
        self,
        payload: dict[str, Any],
        candidate: CandidateUtterance,
        score: StageScore,
        *,
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Đổ candidate thắng vào payload Decision cũ.

        Nhờ hàm này, candidate generation có thể được bật từng phần mà không đổi
        contract UDP/Godot đang dùng.
        """

        payload["text"] = candidate.text
        payload["should_speak"] = candidate.should_speak
        payload["confidence"] = max(_safe_float(payload.get("confidence", 0.0), 0.0), candidate.confidence)
        payload["intent"] = candidate.intent or str(payload.get("intent", "") or "")
        payload["delivery_hint"] = candidate.delivery_hint or str(payload.get("delivery_hint", "") or "")
        payload["nonverbal_cue"] = candidate.nonverbal_cue or str(payload.get("nonverbal_cue", "") or "")
        payload["stage_motion"] = candidate.stage_motion or str(payload.get("stage_motion", "") or "")
        payload["selected_candidate"] = candidate.to_payload()
        return self.apply_to_payload(payload, score, channel=channel)

    def _ranking_value(self, candidate: CandidateUtterance, score: StageScore) -> float:
        mode_bonus = {
            "full": 0.18,
            "short": 0.08,
            "repair": -0.04,
            "body_only": -0.10,
            "suppress": -0.24,
        }.get(score.decision, 0.0)
        confidence = _clamp01(candidate.confidence)
        return (
            mode_bonus
            + score.liveliness * 0.26
            + score.scene_fit * 0.22
            + score.relation_fit * 0.12
            + score.performance_fit * 0.18
            + score.tts_fit * 0.16
            + confidence * 0.08
            - score.clip_risk * 0.28
            + (0.08 if score.evidence_ok else -0.32)
        )

    def _tts_fit(self, text: str, *, words: int, budget: int) -> float:
        if not text:
            return 0.0
        fit = 0.72
        if words <= max(5, budget):
            fit += 0.16
        if words > budget:
            fit -= min(0.45, (words - budget) * 0.025)
        if "\n" in text or len(text) > 220:
            fit -= 0.12
        if re.search(r"https?://|```|^\s*[-*]\s+", text, re.M):
            fit -= 0.22
        return _clamp01(fit)

    def _liveliness(self, text: str, candidate: CandidateUtterance) -> float:
        if not text:
            return 0.0
        normalized = _normalize(text)
        score = 0.36
        if any(mark in text for mark in (".", "?", "!", "…")):
            score += 0.08
        if candidate.delivery_hint or candidate.nonverbal_cue or candidate.stage_motion:
            score += 0.16
        if any(token in normalized for token in ("ngai", "bug", "khoan", "hm", "toi", "eris")):
            score += 0.08
        if normalized in {"ok", "oke", "duoc", "duoc roi", "vang", "uh"}:
            score -= 0.22
        if len(set(normalized.split())) <= 3 and _word_count(text) > 5:
            score -= 0.20
        return _clamp01(score)

    def _scene_fit(self, candidate: CandidateUtterance, context: DirectorContext, *, words: int) -> float:
        scene = context.scene_mode.name
        fit = 0.64
        if scene in self.LOW_INTRUSION_SCENES and words <= context.speak_budget_words:
            fit += 0.15
        if scene == "private_idle" and candidate.intent in {"micro_presence", "random_chatter", "inner_whim"}:
            fit += 0.12
        if scene == "coding_partner" and candidate.intent in {"technical_support", "curious_question", "screen_observation"}:
            fit += 0.12
        if scene in self.LOW_INTRUSION_SCENES and candidate.intent in {"random_chatter", "inner_whim"} and words > 10:
            fit -= 0.22
        return _clamp01(fit)

    def _relation_fit(self, context: DirectorContext) -> float:
        if context.audience_mode in {"stream", "recording"} and context.relation_band == "close_restrained":
            return 0.58
        if context.relation_band in {"warm", "close_restrained"}:
            return 0.76
        if context.relation_band == "unknown":
            return 0.62
        return 0.68

    def _performance_fit(self, candidate: CandidateUtterance) -> float:
        fit = 0.52
        if candidate.delivery_hint:
            fit += 0.14
        if candidate.nonverbal_cue:
            fit += 0.12
        if candidate.stage_motion:
            fit += 0.14
        return _clamp01(fit)


__all__ = [
    "CandidateUtterance",
    "EvidenceAuthority",
    "StageScore",
    "StageScorer",
]
