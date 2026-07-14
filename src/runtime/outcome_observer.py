from __future__ import annotations

"""Quan sát hậu quả theo score giả thuyết, không đóng dấu trạng thái user.

OutcomeObserver chỉ đọc tín hiệu bề mặt và tạo ``SocialOutcomeAppraisal``.
Nó không còn lưu các field kiểu ``user_corrected=True`` hay
``relation_ruptured=True``. Downstream có thể dùng score để mở policy gate,
nhưng gate đó không được ghi ngược thành fact về động cơ/cảm xúc người dùng.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping

from .social_outcome_appraisal import (
    SocialHypothesis,
    SocialOutcomeAppraisal,
    clamp01,
)


@dataclass(slots=True)
class OutcomeReport:
    """Báo cáo hậu quả một turn.

    ``social`` là phân bố tín hiệu mềm. Hai field kỹ thuật ``action_success`` và
    ``body_match_success`` vẫn là score trực tiếp vì chúng mô tả kết quả runtime,
    không phải phán đoán tâm lý người dùng.
    """

    social: SocialOutcomeAppraisal = field(default_factory=SocialOutcomeAppraisal)
    action_success: float = 1.0
    body_match_success: float = 1.0
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5
    correction_excerpt: str = ""
    feedback_text: str = ""
    idle_evidence: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "social": self.social.to_dict(),
            "action_success": round(clamp01(self.action_success), 4),
            "body_match_success": round(clamp01(self.body_match_success), 4),
            "evidence": list(self.evidence),
            "confidence": round(clamp01(self.confidence), 4),
            "correction_excerpt": self.correction_excerpt,
            "feedback_text": self.feedback_text,
            "idle_evidence": self.idle_evidence,
            "tags": list(self.tags),
        }

    @classmethod
    def from_any(cls, value: Any) -> "OutcomeReport":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return cls()
        payload = dict(value)
        social = SocialOutcomeAppraisal.from_any(payload.get("social"))
        # Đọc dữ liệu legacy tại biên migration, nhưng không giữ lại hard claim.
        if payload.get("social") is None:
            social.acceptance_support = 1.0 if payload.get("user_accepted") is True else 0.0
            social.correction_pressure = 1.0 if payload.get("user_corrected") is True else 0.0
            social.confusion_pressure = 1.0 if payload.get("user_confused") is True else 0.0
            social.laughter_signal = 1.0 if payload.get("user_laughed") is True else 0.0
            social.intrusion_risk = 1.0 if payload.get("user_felt_intruded") is True else 0.0
            social.soothing_signal = 1.0 if payload.get("user_soothed") is True else 0.0
            social.relationship_warmth_signal = 1.0 if payload.get("relation_improved") is True else 0.0
            social.relationship_strain_signal = 1.0 if payload.get("relation_ruptured") is True else 0.0
            social.disengagement_risk = 1.0 if payload.get("user_ignored") is True else 0.0
            social.clamp()
        return cls(
            social=social,
            action_success=clamp01(payload.get("action_success", 1.0), 1.0),
            body_match_success=clamp01(payload.get("body_match_success", 1.0), 1.0),
            evidence=[str(x) for x in (payload.get("evidence", ()) or ())],
            confidence=clamp01(payload.get("confidence", social.confidence), social.confidence),
            correction_excerpt=str(payload.get("correction_excerpt") or payload.get("correction_text") or "")[:300],
            feedback_text=str(payload.get("feedback_text", "") or "")[:300],
            idle_evidence=str(payload.get("idle_evidence") or payload.get("ignored_reason") or "")[:160],
            tags=[str(x) for x in (payload.get("tags", ()) or ())],
        )


class OutcomeObserver:
    """Đọc feedback thành các pressure/support score độc lập."""

    ACCEPTANCE_PATTERNS = (
        "đúng", "dung", "chuẩn", "chuan", "hợp lý", "hop ly",
        "ok", "oke", "được", "duoc", "ngon", "ổn", "on",
        "đúng rồi", "dung roi", "chuẩn rồi", "chuan roi",
        "hợp lý đó", "hop ly do", "tiếp", "tiếp tục", "tiep tuc",
    )
    CORRECTION_PATTERNS = (
        "không phải", "khong phai", "sai rồi", "sai roi", "sai",
        "thiếu", "thieu", "chưa đúng", "chua dung", "chưa phải", "chua phai",
        "đọc lại", "doc lai", "lệch", "lech", "nhầm", "nham",
        "không hiểu ý", "khong hieu y", "ý tôi là", "y toi la",
        "no, ", "not what", "wrong", "incorrect", "you missed",
    )
    CONFUSION_PATTERNS = (
        "khó hiểu", "kho hieu", "gì vậy", "gi vay", "là sao", "la sao",
        "nói gì", "noi gi", "không hiểu", "khong hieu", "wtf",
        "what do you mean", "confused",
    )
    LAUGHTER_PATTERNS = (
        "haha", "hahaha", "hehe", "hihi", "kkk", "kaka", "lol", "lmao",
        "cười", "cuoi", "hề", "he",
    )
    INTRUSION_PATTERNS = (
        "đừng suy diễn", "dung suy dien", "đừng hỏi", "dung hoi",
        "đừng nói kháy", "dung noi khay", "nói kháy", "noi khay",
        "móc mỉa", "moc mia", "phiền", "phien", "xen vào", "xen vao",
        "overread", "mindread", "intrusive", "privacy",
        "đừng phân tích", "dung phan tich",
    )
    STRAIN_PATTERNS = (
        "khó chịu", "kho chiu", "bực", "buc", "cay", "ghét", "ghet",
        "tức", "tuc", "nói như", "noi nhu", "chán", "chan",
        "thất vọng", "that vong",
    )
    WARMTH_PATTERNS = (
        "cảm ơn", "cam on", "thanks", "thank you", "đúng ý", "dung y",
        "hợp gu", "hop gu", "nghe được", "nghe duoc", "ổn rồi", "on roi",
    )
    COMFORT_PATTERNS = (
        "đừng lo", "dung lo", "đừng buồn", "dung buon", "đừng căng", "dung cang",
        "đừng nghĩ nhiều", "dung nghi nhieu", "đừng tự trách", "dung tu trach",
        "không sao", "khong sao", "bình tĩnh", "binh tinh", "yên tâm", "yen tam",
        "ổn mà", "on ma", "tôi ở đây", "toi o day", "có tôi đây", "co toi day",
        "nghỉ đi", "nghi di", "thư giãn", "thu gian", "thả lỏng", "tha long",
    )
    TONE_PATTERNS = (
        "lạnh", "lanh", "robot", "máy móc", "may moc", "vô hồn", "vo hon",
        "formal", "cứng", "cung", "không tự nhiên", "khong tu nhien",
    )
    NEGATED_ACCEPTANCE_PATTERNS = (
        "ok nhưng sai", "ok nhung sai", "đúng nhưng", "dung nhung",
        "chuẩn nhưng", "chuan nhung", "hợp lý nhưng", "hop ly nhung",
    )

    def observe(
        self,
        frame: Any,
        *,
        user_feedback_text: str | None = None,
        execution_result: Any = None,
        body_result: Any = None,
        idle_seconds_after_turn: float | None = None,
        attach_to_frame: bool = True,
    ) -> OutcomeReport:
        evidence: list[str] = []
        tags: list[str] = []
        final_text = self._extract_final_text(frame)
        system_action = self._extract_system_action(frame)
        action_success = self._infer_action_success(
            frame, final_text=final_text, system_action=system_action,
            execution_result=execution_result, evidence=evidence, tags=tags,
        )
        body_match_success = self._infer_body_match_success(
            frame, body_result=body_result, evidence=evidence, tags=tags,
        )

        feedback = str(user_feedback_text or "").strip()
        norm = self._normalize(feedback)
        acceptance = correction = confusion = laughter = intrusion = 0.0
        soothing = warmth = strain = tone = disengagement = 0.0
        correction_excerpt = ""
        hypotheses: list[SocialHypothesis] = []
        social_evidence: list[str] = []

        if feedback:
            correction_hit = self._has_any(norm, self.CORRECTION_PATTERNS)
            confusion_hit = self._has_any(norm, self.CONFUSION_PATTERNS)
            laughter_hit = self._has_any(norm, self.LAUGHTER_PATTERNS)
            intrusion_hit = self._has_any(norm, self.INTRUSION_PATTERNS)
            strain_hit = self._has_any(norm, self.STRAIN_PATTERNS)
            warmth_hit = self._has_any(norm, self.WARMTH_PATTERNS)
            acceptance_hit = self._has_any(norm, self.ACCEPTANCE_PATTERNS)
            comfort_hit = self._has_any(norm, self.COMFORT_PATTERNS)
            tone_hit = self._has_any(norm, self.TONE_PATTERNS)
            negated_acceptance = self._has_any(norm, self.NEGATED_ACCEPTANCE_PATTERNS)

            correction = 0.82 if correction_hit else 0.0
            confusion = 0.66 if confusion_hit else 0.0
            laughter = 0.72 if laughter_hit else 0.0
            intrusion = 0.76 if intrusion_hit else 0.0
            strain = max(0.68 if strain_hit else 0.0, intrusion * 0.72)
            warmth = 0.66 if warmth_hit else 0.0
            acceptance = 0.72 if acceptance_hit else 0.0
            soothing = 0.72 if comfort_hit else 0.0
            tone = 0.72 if tone_hit else 0.0

            # Các tín hiệu được giữ đồng thời. Chỉ hạ support khi phrase tự phủ định.
            if negated_acceptance:
                acceptance = min(acceptance, 0.24)
                correction = max(correction, 0.76)
            if correction_hit or confusion_hit:
                acceptance = min(acceptance, 0.34)
            if intrusion_hit:
                soothing = min(soothing, 0.20)
            if laughter_hit and (correction_hit or confusion_hit):
                # Có thể là playful correction, không xóa correction pressure.
                strain *= 0.72

            signals = (
                ("acceptance_support", acceptance),
                ("correction_pressure", correction),
                ("confusion_pressure", confusion),
                ("laughter_signal", laughter),
                ("intrusion_risk", intrusion),
                ("soothing_signal", soothing),
                ("relationship_warmth_signal", warmth),
                ("relationship_strain_signal", strain),
                ("tone_feedback_pressure", tone),
            )
            for label, score in signals:
                if score < 0.18:
                    continue
                ev = f"{label}={feedback[:140]}"
                social_evidence.append(ev)
                hypotheses.append(SocialHypothesis(label=label, score=score, evidence=(ev,)))
                tags.append(f"hypothesis:{label}")
            if correction >= 0.40:
                correction_excerpt = feedback[:300]

        idle_evidence = ""
        if idle_seconds_after_turn is not None:
            try:
                idle = max(0.0, float(idle_seconds_after_turn))
            except Exception:
                idle = 0.0
            if idle >= 90.0 and (final_text or system_action):
                # Im lặng có nhiều nguyên nhân. Chỉ ghi disengagement risk mềm.
                disengagement = min(0.68, 0.36 + (idle - 90.0) / 600.0)
                idle_evidence = f"idle_after_turn={idle:.1f}s"
                social_evidence.append(idle_evidence)
                hypotheses.append(SocialHypothesis(
                    label="disengagement_risk", score=disengagement,
                    evidence=(idle_evidence,), provenance="runtime_idle_signal", ttl_turns=1,
                ))
                tags.append("hypothesis:disengagement_risk")

        active_scores = [
            score for score in (acceptance, correction, confusion, laughter, intrusion,
                                soothing, warmth, strain, disengagement, tone)
            if score >= 0.18
        ]
        confidence = self._estimate_social_confidence(
            has_feedback=bool(feedback), active_count=len(active_scores),
            action_success=action_success, body_match_success=body_match_success,
        )
        uncertainty = 1.0 if not active_scores else clamp01(
            0.68 - min(0.42, max(active_scores) * 0.34) + (0.10 if len(active_scores) >= 3 else 0.0)
        )
        social = SocialOutcomeAppraisal(
            acceptance_support=acceptance,
            correction_pressure=correction,
            confusion_pressure=confusion,
            laughter_signal=laughter,
            intrusion_risk=intrusion,
            soothing_signal=soothing,
            relationship_warmth_signal=warmth,
            relationship_strain_signal=strain,
            disengagement_risk=disengagement,
            tone_feedback_pressure=tone,
            interpretation_uncertainty=uncertainty,
            confidence=confidence,
            hypotheses=tuple(hypotheses),
            evidence=tuple(social_evidence),
        ).clamp()
        report = OutcomeReport(
            social=social,
            action_success=clamp01(action_success, 1.0),
            body_match_success=clamp01(body_match_success, 1.0),
            evidence=[*evidence, *social_evidence][:16],
            confidence=confidence,
            correction_excerpt=correction_excerpt,
            feedback_text=feedback[:300],
            idle_evidence=idle_evidence,
            tags=list(dict.fromkeys(tags))[:16],
        )
        if attach_to_frame:
            self._safe_setattr(frame, "outcome", report)
        return report

    def observe_user_feedback_for_previous_frame(
        self, previous_frame: Any, user_feedback_text: str, *, attach_to_frame: bool = True,
    ) -> OutcomeReport:
        return self.observe(
            previous_frame, user_feedback_text=user_feedback_text,
            attach_to_frame=attach_to_frame,
        )

    def _infer_action_success(
        self,
        frame: Any,
        *,
        final_text: str,
        system_action: str,
        execution_result: Any,
        evidence: list[str],
        tags: list[str],
    ) -> float:
        if execution_result is not None:
            success = self._read_bool(execution_result, "success")
            if success is not None:
                evidence.append(f"execution_success={success}")
                tags.append("execution_result")
                return 1.0 if success else 0.0

            score = self._read_float(execution_result, "success_score")
            if score is not None:
                evidence.append(f"execution_success_score={score:.2f}")
                tags.append("execution_result")
                return score

        execution = getattr(frame, "execution", None)
        if execution is not None:
            success = self._read_bool(execution, "success")
            if success is not None:
                evidence.append(f"frame_execution_success={success}")
                tags.append("frame_execution")
                return 1.0 if success else 0.0

        # Nếu có system action nhưng không có execution_result, chỉ nên coi là chưa chắc.
        if system_action:
            evidence.append(f"system_action_without_execution_result={system_action}")
            tags.append("system_action_uncertain")
            return 0.55

        # Nếu turn có text hợp lệ thì speech execution coi như thành công ở tầng output.
        if final_text:
            evidence.append("speech_text_present")
            tags.append("speech_executed")
            return 1.0

        # Im lặng có thể là hành vi đúng. Không phạt nếu speech_opportunity/action_plan nói no_speech.
        speech_core = getattr(frame, "speech_core", None)
        utterance_type = str(getattr(speech_core, "utterance_type", "") or "")
        if utterance_type in {"no_speech", "silence"}:
            evidence.append(f"intentional_silence={utterance_type}")
            tags.append("intentional_silence")
            return 1.0

        return 0.5

    def _infer_body_match_success(
        self,
        frame: Any,
        *,
        body_result: Any,
        evidence: list[str],
        tags: list[str],
    ) -> float:
        if body_result is not None:
            matched = self._read_bool(body_result, "matched")
            if matched is None:
                matched = self._read_bool(body_result, "success")
            if matched is not None:
                evidence.append(f"body_matched={matched}")
                tags.append("body_result")
                return 1.0 if matched else 0.0

            score = self._read_float(body_result, "match_score")
            if score is not None:
                evidence.append(f"body_match_score={score:.2f}")
                tags.append("body_result")
                return score

        modality = getattr(frame, "modality", None)
        contradiction_risk = self._read_float(modality, "contradiction_risk") if modality is not None else None
        if contradiction_risk is not None:
            score = 1.0 - self._clamp01(contradiction_risk)
            evidence.append(f"modality_contradiction_risk={contradiction_risk:.2f}")
            tags.append("modality")
            return score

        grounding = getattr(frame, "grounding", None)
        body_mismatch = self._read_float(grounding, "body_action_mismatch") if grounding is not None else None
        if body_mismatch is not None:
            score = 1.0 - self._clamp01(body_mismatch)
            evidence.append(f"grounding_body_action_mismatch={body_mismatch:.2f}")
            tags.append("grounding")
            return score

        return 1.0

    def _estimate_social_confidence(
        self, *, has_feedback: bool, active_count: int, action_success: float, body_match_success: float
    ) -> float:
        confidence = 0.34 + (0.30 if has_feedback else 0.0)
        confidence += min(0.18, max(0, int(active_count)) * 0.045)
        if action_success in (0.0, 1.0):
            confidence += 0.04
        if body_match_success in (0.0, 1.0):
            confidence += 0.02
        return clamp01(confidence)

    @classmethod
    def _normalize(cls, text: str) -> str:
        text = str(text or "").strip().lower()
        text = unicodedata.normalize("NFD", text)
        text = "".join(char for char in text if unicodedata.category(char) != "Mn")
        text = re.sub(r"\s+", " ", text)
        return text

    @classmethod
    def _has_any(cls, normalized_text: str, patterns: tuple[str, ...]) -> bool:
        if not normalized_text:
            return False
        for pattern in patterns:
            normalized_pattern = cls._normalize(pattern)
            if normalized_pattern and normalized_pattern in normalized_text:
                return True
        return False

    @staticmethod
    def _extract_final_text(frame: Any) -> str:
        final_decision = getattr(frame, "final_decision", None)
        if isinstance(final_decision, Mapping):
            text = str(final_decision.get("text", "") or "").strip()
            if text:
                return text
        decision = getattr(frame, "decision", None)
        text = str(getattr(decision, "text", "") or "").strip()
        if text:
            return text
        # Canonical V3 không có final_decision; wording là source of truth sau
        # finalize. Observer cũ bỏ qua slot này nên mọi câu đã nói đều bị nhìn như
        # im lặng. Một cách khá hiệu quả để tự chẩn đoán sai chính mình.
        wording = getattr(frame, "wording", None)
        if isinstance(wording, Mapping):
            return str(wording.get("parsed_text") or wording.get("raw_text") or "").strip()
        return str(getattr(wording, "parsed_text", None) or getattr(wording, "raw_text", "") or "").strip()

    @staticmethod
    def _extract_system_action(frame: Any) -> str:
        final_decision = getattr(frame, "final_decision", None)
        if isinstance(final_decision, Mapping):
            action = str(final_decision.get("system_action", "") or "").strip()
            if action:
                return action
        action_plan = getattr(frame, "action_plan", None)
        action = str(getattr(action_plan, "system_action", "") or "").strip()
        if action:
            return action
        modality = getattr(frame, "modality", None)
        if isinstance(modality, Mapping):
            return str(modality.get("system_action", "") or "").strip()
        return str(getattr(modality, "system_action", "") or "").strip()

    @staticmethod
    def _read_bool(obj: Any, key: str) -> bool | None:
        if obj is None:
            return None
        if isinstance(obj, Mapping) and key in obj:
            value = obj.get(key)
        else:
            value = getattr(obj, key, None)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1", "ok", "success"}:
                return True
            if lowered in {"false", "no", "0", "failed", "error"}:
                return False
        return None

    @staticmethod
    def _read_float(obj: Any, key: str) -> float | None:
        if obj is None:
            return None
        if isinstance(obj, Mapping) and key in obj:
            value = obj.get(key)
        else:
            value = getattr(obj, key, None)
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _safe_setattr(obj: Any, key: str, value: Any) -> None:
        try:
            setattr(obj, key, value)
        except Exception:
            return

    @staticmethod
    def _clamp01(value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.0
