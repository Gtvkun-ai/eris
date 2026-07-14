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
from runtime.evidence_authority import EvidenceAuthority
from runtime.scene_repair_policy import SceneRepairPolicy


_WORD_RE = re.compile(r"\S+")
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
            evidence_refs=tuple(
                str(item or "").strip()
                for item in (payload.get("evidence_refs", ()) or ())
                if str(item or "").strip()
            ) if not isinstance(payload.get("evidence_refs", ()), str) else (str(payload.get("evidence_refs") or "").strip(),),
            repair_mode=str(payload.get("repair_mode", "") or ""),
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


class StageScorer:
    """Rule-based scorer dau tien cho Director -> Stage.

    Scorer áp dụng hard gate cho mọi channel. Chat vẫn được ưu tiên repair thay
    vì suppress, nhưng không còn đặc quyền phát một câu mà runtime đã biết là sai.
    """

    LOW_INTRUSION_SCENES = {"coding_partner", "study_partner", "social_sidecar"}

    def __init__(
        self,
        *,
        evidence_authority: EvidenceAuthority | None = None,
        repair_policy: SceneRepairPolicy | None = None,
    ) -> None:
        self.evidence_authority = evidence_authority or EvidenceAuthority()
        self.repair_policy = repair_policy or SceneRepairPolicy()

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
        authority = self.evidence_authority.validate_candidate(candidate, context)
        evidence_ok = authority.allowed
        evidence_reasons = authority.reasons
        tags.extend(evidence_reasons)
        if authority.used_levels:
            tags.extend(f"evidence_level:{level}" for level in authority.used_levels)
        budget_ratio = words / max(1, context.speak_budget_words)
        clip_risk = _clamp01((budget_ratio - 0.9) / 1.4)
        if not authority.allowed:
            # Hard-gate lỗi bằng chứng phải nổi lên rõ trong score, không chìm
            # dưới một câu văn có nhịp khá. Con người rất thích bị câu chữ đẹp lừa.
            clip_risk = max(clip_risk, 0.78)
        tts_fit = self._tts_fit(text, words=words, budget=context.speak_budget_words)
        liveliness = self._liveliness(text, candidate)
        hook_bonus, hook_tags = self._content_hook_bonus(candidate, context)
        liveliness = _clamp01(liveliness + hook_bonus)
        tags.extend(hook_tags)
        scene_fit = self._scene_fit(candidate, context, words=words)
        relation_fit = self._relation_fit(context)
        performance_fit = self._performance_fit(candidate)
        speakable = bool(candidate.should_speak and text and evidence_ok and tts_fit >= 0.35)

        channel_name = str(channel or "").strip().lower()
        interactive_chat = channel_name == "chat"
        hard_authority_failure = any(
            reason in {
                "missing_evidence_ref",
                "expired_evidence_ref",
                "private_evidence_in_public",
                "forbidden_evidence_level",
                "screen_claim_without_sensor",
                "screen_claim_not_grounded",
                "system_action_without_tool",
                "emotion_as_fact",
                "hearing_user_breath",
                "physical_world_overreach",
            }
            for reason in evidence_reasons
        )
        if not candidate.should_speak or not text:
            decision_mode: DecisionMode = "body_only" if candidate.stage_motion or candidate.nonverbal_cue else "suppress"
            reason = "candidate_empty_or_non_speech"
        elif hard_authority_failure:
            # Chat cũng phải chịu hard gate. Trước đây chat chỉ được annotate,
            # tức là runtime biết câu sai nhưng vẫn đọc nó ra. Một kiểu trung thực
            # rất đặc biệt của phần mềm.
            decision_mode = "repair" if interactive_chat else "suppress"
            reason = ",".join(evidence_reasons) or "evidence_block"
        elif not evidence_ok:
            decision_mode = "repair"
            reason = ",".join(evidence_reasons) or "evidence_surface_repair"
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
        context: DirectorContext | None = None,
    ) -> dict[str, Any]:
        """Thực thi quyết định scorer trên mọi channel, kể cả chat.

        Bản cũ chỉ annotate chat nên ``repair``/``short`` không hề sửa gì. Bản
        này dùng SceneRepairPolicy deterministic: rút ngắn, bóc stage tag, thêm
        marker ký ức/hedge; claim vượt quyền thì suppress thay vì phát ra rồi ghi
        log như thể log có thể bịt tai người nghe.
        """

        payload["stage_score"] = score.to_payload()
        max_words = int(getattr(context, "speak_budget_words", 0) or payload.get("speak_budget_words", 0) or 16)
        payload, repair = self.repair_policy.apply_to_payload(
            payload,
            decision=score.decision,
            reasons=score.policy_tags,
            max_words=max_words,
        )
        payload["stage_score"]["applied_action"] = repair.action
        payload["stage_score"]["applied_changed"] = repair.changed
        return payload

    def apply_candidate_to_payload(
        self,
        payload: dict[str, Any],
        candidate: CandidateUtterance,
        score: StageScore,
        *,
        channel: str | None = None,
        context: DirectorContext | None = None,
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
        return self.apply_to_payload(payload, score, channel=channel, context=context)

    def ranking_value(self, candidate: CandidateUtterance, score: StageScore) -> float:
        """Điểm xếp hạng public cho pipeline Director.

        Quyền quyết định vẫn nằm trong ``StageScore.decision``; giá trị này chỉ
        dùng để so sánh các candidate trong cùng một turn.
        """
        return self._ranking_value(candidate, score)

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

    def _content_hook_bonus(self, candidate: CandidateUtterance, context: DirectorContext) -> tuple[float, list[str]]:
        """Cộng điểm nhẹ nếu candidate bám hook nội dung.

        Hook là mồi, không phải luật cứng. Vì vậy không bám hook chỉ mất cơ hội
        cộng điểm; không bị reject trừ khi đã vi phạm evidence ở tầng khác.
        """

        world = context.world_state if isinstance(context.world_state, dict) else {}
        hook = world.get("content_hook")
        if not isinstance(hook, Mapping):
            return 0.0, []
        text = _normalize(candidate.text)
        intent = _normalize(candidate.intent)
        keywords = hook.get("keywords", ()) or ()
        if isinstance(keywords, str):
            keyword_list = [keywords]
        elif isinstance(keywords, (list, tuple)):
            keyword_list = [str(item or "") for item in keywords]
        else:
            keyword_list = []
        matched = [kw for kw in keyword_list if kw and _normalize(kw) in text]
        family = str(hook.get("family", "") or "")
        hook_id = str(hook.get("id", "") or "")
        bonus = 0.0
        tags: list[str] = []
        if matched:
            bonus += min(0.12, 0.04 + len(matched) * 0.025)
            tags.append(f"content_hook_match:{hook_id}")
        if family == "technical" and intent in {"technical_help", "screen_observation", "curious_question"}:
            bonus += 0.05
            tags.append("content_hook_family_fit:technical")
        if family in {"running_bit", "dead_air_recovery"} and intent in {"micro_presence", "random_chatter", "tease"}:
            bonus += 0.05
            tags.append(f"content_hook_family_fit:{family}")
        return _clamp01(bonus), tags

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
