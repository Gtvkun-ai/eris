from __future__ import annotations

"""
memory.claims.claim_builder
===========================

Biến MeaningFrame thành SemanticClaim.

Đây mới là nơi map `frame_type + relation` sang predicate memory. Parser/model chỉ
được phép nói "khung nghĩa có vẻ là hometown/living/preference"; claim builder
mới quyết định predicate chuẩn nào được sinh ra. Nhờ vậy `claim_extractor` không
còn là một hang regex tự phong làm não.
"""

from dataclasses import dataclass
from typing import Iterable, Mapping, Any
import time

try:
    from ..semantic_claim import ExtractedClaim, SemanticClaim, build_claim
    from ..understanding.meaning_frame import MeaningFrame, MeaningParseResult
except Exception:  # pragma: no cover
    from semantic_claim import ExtractedClaim, SemanticClaim, build_claim  # type: ignore
    from understanding.meaning_frame import MeaningFrame, MeaningParseResult  # type: ignore


# Map frame relation -> predicate cuối.
# Nếu model.gguf trả relation đã là predicate chuẩn, map này vẫn nhận được.
RELATION_TO_PREDICATE: dict[tuple[str, str], str] = {
    ("identity", "name"): "name_is",
    ("identity", "name_is"): "name_is",
    ("identity", "birth_month"): "birth_month_is",
    ("identity", "birth_month_is"): "birth_month_is",
    ("identity", "birth_year"): "birth_year_is",
    ("identity", "birth_year_is"): "birth_year_is",
    ("identity", "age"): "age_observed_is",
    ("identity", "age_observed_is"): "age_observed_is",

    ("location", "current_location"): "current_location_is",
    ("location", "current_location_is"): "current_location_is",
    ("location", "living_location"): "living_location_is",
    ("location", "living_location_is"): "living_location_is",
    ("location", "hometown"): "hometown_is",
    ("location", "hometown_is"): "hometown_is",
    ("location", "mentioned_location"): "mentioned_location",

    ("preference", "likes"): "preference_location_or_general",
    ("preference", "dislikes"): "preference_location_or_general",
    ("preference", "preference_location"): "preference_location",
    ("preference", "general_preference"): "general_preference",

    # Profile học tập/ngành học. Tách khỏi preference để câu "Tôi đang học IT"
    # không bị nhớ thành "tôi thích IT". Một chữ sai predicate, sau này recall sai cả đời.
    ("project", "study_field"): "study_field_is",
    ("project", "study_field_is"): "study_field_is",

    ("instruction", "response_style"): "response_style_prefers",
    ("instruction", "response_style_prefers"): "response_style_prefers",
    ("feedback", "tone_feedback"): "response_style_prefers",
    ("feedback", "response_style_prefers"): "response_style_prefers",

    ("session_event", "greeting"): "greeted",
    ("session_event", "asked_about"): "asked_about",
}


PREDICATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "name_is": {"object_type": "person_name", "modality": "fact", "temporal": "stable", "stability": "stable", "confidence_floor": 0.80},
    "birth_month_is": {"object_type": "month", "modality": "fact", "temporal": "stable", "stability": "stable", "confidence_floor": 0.78},
    "birth_year_is": {"object_type": "year", "modality": "fact", "temporal": "stable", "stability": "stable", "confidence_floor": 0.78},
    "age_observed_is": {"object_type": "age", "modality": "observation", "temporal": "current", "stability": "medium", "valid_seconds": 86400 * 370},
    "current_location_is": {"object_type": "location", "modality": "observation", "temporal": "current", "stability": "transient", "valid_seconds": 3600},
    "living_location_is": {"object_type": "location", "modality": "fact", "temporal": "current", "stability": "medium"},
    "hometown_is": {"object_type": "location", "modality": "fact", "temporal": "stable", "stability": "stable"},
    "preference_location": {"object_type": "location", "modality": "preference", "temporal": "stable", "stability": "medium"},
    "general_preference": {"object_type": "unknown", "modality": "preference", "temporal": "stable", "stability": "medium"},
    "study_field_is": {"object_type": "study_field", "modality": "fact", "temporal": "current", "stability": "medium", "confidence_floor": 0.74},
    "response_style_prefers": {"object_type": "style_rule", "modality": "preference", "temporal": "stable", "stability": "medium"},
    "mentioned_location": {"object_type": "location", "modality": "observation", "temporal": "session", "stability": "session"},
    "greeted": {"object_type": "utterance", "modality": "observation", "temporal": "session", "stability": "session"},
    "asked_about": {"object_type": "topic", "modality": "observation", "temporal": "session", "stability": "session"},
}


@dataclass(slots=True)
class ClaimBuilder:
    """Builder deterministic từ MeaningFrame sang ExtractedClaim."""

    def build_many(
        self,
        result: MeaningParseResult,
        *,
        evidence_ids: Iterable[str] = (),
        source: str = "user_text",
    ) -> list[ExtractedClaim]:
        out: list[ExtractedClaim] = []
        for frame in result.frames:
            item = self.build_one(frame, evidence_ids=tuple(evidence_ids), source=source)
            if item is not None:
                out.append(item)
        return self._dedupe(out)

    def build_one(self, frame: MeaningFrame, *, evidence_ids: tuple[str, ...] = (), source: str = "user_text") -> ExtractedClaim | None:
        # --- Path mới: Gemini đã quyết định classification ---
        # Nếu frame có memory_type (schema mới), dùng trực tiếp thay vì map cứng.
        raw = (frame.slots or {}).get("_raw") or {}
        if isinstance(raw, Mapping) and raw.get("memory_type"):
            return self._build_from_ai_classification(raw, evidence_ids=evidence_ids)

        # --- Path cũ: map frame_type + relation sang predicate (fallback) ---
        predicate = self._predicate_for_frame(frame)
        if not predicate:
            return None
        if frame.polarity in {"hypothetical", "quoted"}:
            return None

        defaults = dict(PREDICATE_DEFAULTS.get(predicate, {}))
        target = frame.target
        if target is None and predicate not in {"greeted", "asked_about"}:
            return None

        object_text = target.text if target else frame.evidence_span
        object_value: Any = target.text if target else object_text
        object_type = str(defaults.get("object_type") or (target.kind if target else "unknown"))

        # Nếu preference target là location thì thành preference_location, còn không là general_preference.
        if predicate == "preference_location_or_general":
            if target and target.kind == "location":
                predicate = "preference_location"
                defaults = dict(PREDICATE_DEFAULTS[predicate])
                object_type = "location"
            else:
                predicate = "general_preference"
                defaults = dict(PREDICATE_DEFAULTS[predicate])
                object_type = target.kind if target else "unknown"

        temporal = str(defaults.get("temporal") or frame.time_scope or "unknown")
        if frame.time_scope != "unknown":
            temporal = frame.time_scope
        stability = str(defaults.get("stability") or frame.stability or "unknown")
        if frame.stability != "unknown":
            stability = frame.stability

        valid_until = None
        valid_seconds = defaults.get("valid_seconds")
        if valid_seconds:
            valid_until = time.time() + float(valid_seconds)

        confidence = max(float(frame.certainty), float(defaults.get("confidence_floor", 0.0)))
        if target is not None:
            confidence = min(1.0, confidence * 0.82 + target.confidence * 0.18)
        confidence = max(0.0, min(1.0, confidence))

        claim = build_claim(
            subject=frame.subject or "user",
            predicate=predicate,
            object_text=str(object_text),
            object_value=object_value,
            object_type=object_type,
            assertion=frame.polarity,  # type: ignore[arg-type]
            modality=str(defaults.get("modality") or frame.modality or "fact"),  # type: ignore[arg-type]
            temporal=temporal,  # type: ignore[arg-type]
            scope=frame.scope or "self",  # type: ignore[arg-type]
            source="user_text" if source == "user_text" else "inference",  # type: ignore[arg-type]
            confidence=confidence,
            evidence_text=frame.evidence_span,
            evidence_ids=evidence_ids,
            valid_until=valid_until,
            stability=stability,  # type: ignore[arg-type]
            qualifiers={
                "meaning_frame": frame.to_dict(),
                "pipeline": "meaning_frame_claim_builder",
            },
        )
        return ExtractedClaim(
            claim=claim,
            extraction_confidence=confidence,
            extraction_method="meaning_frame_builder",
            commit_hint="semantic",
            warnings=frame.warnings,
        )

    def _build_from_ai_classification(
        self,
        raw: Mapping[str, Any],
        *,
        evidence_ids: tuple[str, ...] = (),
    ) -> ExtractedClaim | None:
        """Build ExtractedClaim từ schema mới của Gemini.

        Gemini quyết định memory_type, storage_target, importance, decay, surface_fn.
        Không cần map sang predicate cứng.
        """
        claim_text = str(raw.get("claim") or "").strip()
        if not claim_text:
            return None

        memory_type = str(raw.get("memory_type") or "context")
        storage_target = str(raw.get("storage_target") or "semantic")
        importance = float(raw.get("importance") or 0.5)
        decay = str(raw.get("decay") or "normal")
        surface_fn = str(raw.get("surface_fn") or "background")
        fact_key = str(raw.get("fact_key") or "")
        value = raw.get("value")
        confidence = float(raw.get("confidence") or 0.65)
        time_scope = str(raw.get("time_scope") or "stable")
        subject = str(raw.get("subject") or "user")
        why = str(raw.get("why") or "")

        # Map storage_target → commit_hint và predicate fallback
        target_map = {
            "semantic": "semantic",
            "episodic": "episodic",
            "procedural": "procedural",
            "affective_residue": "affective_residue",
            "relational": "relational",
            "candidate": "candidate",
        }
        commit_hint = target_map.get(storage_target, "semantic")

        # Map decay string → decay_policy chuẩn
        decay_map = {
            "slow": "slow",
            "normal": "normal",
            "fast": "fast",
            "ephemeral": "session_only",
        }
        decay_policy = decay_map.get(decay, "normal")

        # Map surface_fn → surface_policy
        surface_policy_map = {
            "can_answer": "surface_if_contextual",
            "background": "silent_bias",
            "never": "never_direct_claim",
        }
        surface_policy = surface_policy_map.get(surface_fn, "silent_bias")

        # Predicate đặc biệt: dùng fact_key nếu có, không thì dùng memory_type
        predicate = fact_key.replace(".", "_") if fact_key else f"{memory_type}_observed"

        claim = build_claim(
            subject=subject,
            predicate=predicate,
            object_text=claim_text,
            object_value=value if value is not None else claim_text,
            object_type=memory_type,
            assertion="asserted",
            modality="fact" if memory_type in {"fact", "knowledge"} else
                     "preference" if memory_type == "convention" else
                     "feedback" if memory_type == "feedback" else
                     "observation",
            temporal=time_scope,  # type: ignore[arg-type]
            scope="self",  # type: ignore[arg-type]
            source="user_text",  # type: ignore[arg-type]
            confidence=min(1.0, max(0.0, confidence)),
            evidence_text=claim_text,
            evidence_ids=evidence_ids,
            valid_until=None,
            stability="stable" if decay in {"slow"} else "medium" if decay == "normal" else "transient",  # type: ignore[arg-type]
            qualifiers={
                "memory_type": memory_type,
                "storage_target": storage_target,
                "importance": importance,
                "decay": decay,
                "decay_policy": decay_policy,
                "surface_fn": surface_fn,
                "surface_policy": surface_policy,
                "fact_key": fact_key,
                "value": value,
                "why": why,
                "pipeline": "ai_classification",
            },
        )
        return ExtractedClaim(
            claim=claim,
            extraction_confidence=confidence,
            extraction_method="ai_classification",
            commit_hint=commit_hint,
            warnings=(),
        )

    def _predicate_for_frame(self, frame: MeaningFrame) -> str:
        key = (frame.frame_type, frame.relation)
        if key in RELATION_TO_PREDICATE:
            return RELATION_TO_PREDICATE[key]
        # Nếu model trả thẳng predicate chuẩn, nhận luôn khi defaults có.
        if frame.relation in PREDICATE_DEFAULTS:
            return frame.relation
        return ""

    def _dedupe(self, items: list[ExtractedClaim]) -> list[ExtractedClaim]:
        seen: set[tuple[str, str, str, str]] = set()
        out: list[ExtractedClaim] = []
        for item in items:
            c = item.claim
            key = (c.subject, c.predicate, c.object_text.casefold(), c.assertion)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out


__all__ = ["ClaimBuilder", "RELATION_TO_PREDICATE", "PREDICATE_DEFAULTS"]
