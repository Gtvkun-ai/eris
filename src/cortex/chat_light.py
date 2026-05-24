from __future__ import annotations

import re
import unicodedata

from .affect_semantics import AffectSemanticSignal, clamp01
from .contracts import MeaningLayerResult, PersonalityLensResult


def _normalize(text: str) -> str:
    lowered = str(text or "").strip().lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", without_marks)).strip()


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


class ChatMeaningLayerLight:
    """Grounded semantic pressure for direct chat turns.

    This deliberately avoids autonomous telemetry interpretation. It reads the
    user's message shape and affect scores, then emits answer/repair/directness
    pressure without assigning motives.
    """

    TECHNICAL_TERMS = (
        "code",
        "debug",
        "bug",
        "error",
        "exception",
        "traceback",
        "stack",
        "runtime",
        "coordinator",
        "service",
        "class",
        "function",
        "test",
        "pytest",
        "git",
        "api",
        "json",
        "python",
        "godot",
        "fix",
        "refactor",
        "commit",
        "merge",
        "build",
        "deploy",
        "loi",
        "sua",
        "tach",
        "ham",
        "lop",
        "kiem tra",
    )
    CORRECTION_TERMS = (
        "sai roi",
        "khong phai",
        "y toi",
        "nham",
        "dung y",
        "thieu",
        "khong dung",
        "no no",
        "wrong",
        "not what i mean",
        "actually",
    )
    DIRECTIVE_TERMS = (
        "them",
        "sua",
        "tach",
        "xoa",
        "doi",
        "refactor",
        "fix",
        "implement",
        "add",
        "remove",
        "update",
        "ignore",
        "commit",
        "viet",
        "tao",
    )

    def evaluate(
        self,
        *,
        user_text: str = "",
        affect_signal: AffectSemanticSignal | None = None,
        ti_report=None,
        fe_plan=None,
        previous_assistant_text: str = "",
    ) -> MeaningLayerResult:
        affect = (affect_signal or AffectSemanticSignal.empty()).clamp()
        normalized = _normalize(user_text)
        technical = max(
            affect.technicality,
            0.72 if _has_any(normalized, self.TECHNICAL_TERMS) else 0.0,
            0.64 if str(getattr(ti_report, "mode", "") or "") in {"chat_code", "focus_guard"} else 0.0,
            0.58 if str(getattr(fe_plan, "intent_label", "") or "") == "technical_support" else 0.0,
        )
        correction = max(affect.correction, 0.76 if _has_any(normalized, self.CORRECTION_TERMS) else 0.0)
        directive = max(affect.directive_pressure, 0.66 if _has_any(normalized, self.DIRECTIVE_TERMS) else 0.0)
        answer_need = max(affect.answer_need, 0.70 if "?" in str(user_text or "") else 0.0)
        ambiguity = affect.ambiguity

        if correction >= 0.48:
            semantic_intent = "correction_repair"
            surface_intent = "acknowledge_correction_then_answer_current_intent"
            reaction = "repair_direct"
        elif technical >= 0.52 and directive >= 0.45:
            semantic_intent = "technical_directive"
            surface_intent = "execute_or_explain_directly"
            reaction = "technical_action"
        elif technical >= 0.52:
            semantic_intent = "technical_question"
            surface_intent = "answer_first_technical"
            reaction = "technical_answer"
        elif directive >= 0.52:
            semantic_intent = "direct_request"
            surface_intent = "answer_or_execute_first"
            reaction = "direct_answer"
        elif answer_need >= 0.52:
            semantic_intent = "direct_question"
            surface_intent = "answer_first"
            reaction = "direct_answer"
        elif ambiguity >= 0.58:
            semantic_intent = "clarify_light"
            surface_intent = "brief_answer_then_one_clarifier_if_needed"
            reaction = "light_clarify"
        else:
            semantic_intent = "chat_message"
            surface_intent = "respond_to_user_message"
            reaction = "grounded_reply"

        pressure = clamp01(max(technical, correction, directive, answer_need) * 0.58 + ambiguity * 0.12)
        attention_bias = tuple(
            item
            for item, score in (
                ("answer_first", answer_need),
                ("technical_directness", technical),
                ("correction_repair", correction),
                ("directive_pressure", directive),
                ("overread_brake", max(technical, directive, correction)),
            )
            if score >= 0.42
        )
        evidence = (
            f"semantic_intent={semantic_intent}",
            f"technical={technical:.2f}",
            f"directive={directive:.2f}",
            f"correction={correction:.2f}",
            f"answer_need={answer_need:.2f}",
        )
        result = MeaningLayerResult(
            source_fact="chat_user_text",
            meaning=semantic_intent,
            secondary_meanings=tuple(affect.dominant_axes(threshold=0.48))[:5],
            semantic_family=semantic_intent,
            confidence=clamp01(max(0.50, technical, correction, directive, answer_need, 1.0 - ambiguity * 0.35)),
            reaction=reaction,
            attitude="grounded_direct",
            surface_intent=surface_intent,
            mood_residue="chat_semantic_pressure_only",
            emotional_pressure=pressure,
            attention_bias=attention_bias,
            reaction_impulse=surface_intent,
            meaning_shift=True,
            meaning_signal="chat_light_semantic_intent",
            shift_reason="direct_chat_text_only_no_autonomous_symbolic_reading",
            evidence=evidence,
        )
        result.prompt_context = self.render_prompt_context(result)
        return result

    def render_prompt_context(self, result: MeaningLayerResult) -> str:
        bias = ", ".join(result.attention_bias) if result.attention_bias else "grounded_reply"
        return "\n".join(
            (
                "ChatMeaningLayerLight: direct chat semantic pressure, not autonomous symbolic reading.",
                (
                    "chat_semantic_intent: "
                    f"intent={result.meaning}; surface={result.surface_intent}; pressure={result.emotional_pressure:.2f}; "
                    f"bias={bias}."
                ),
                "chat_rule: answer the user's current request first; do not infer hidden motives from apps, telemetry, or vibe.",
            )
        )


class ChatPersonalityPressureLight:
    """Small chat-only personality pressure that brakes overreading."""

    AVOIDED_SURFACE = (
        "autonomous_symbolic_reading",
        "telemetry_motive_inference",
        "existential_overread",
        "poetic_debugging",
        "answering_questions_with_vibes",
    )

    def evaluate(
        self,
        *,
        meaning_layer: MeaningLayerResult | None = None,
        affect_signal: AffectSemanticSignal | None = None,
        ti_report=None,
        fe_plan=None,
        user_text: str = "",
        previous_assistant_text: str = "",
    ) -> PersonalityLensResult:
        affect = (affect_signal or AffectSemanticSignal.empty()).clamp()
        meaning = str(getattr(meaning_layer, "meaning", "") or "")
        technical = max(affect.technicality, 0.72 if "technical" in meaning else 0.0)
        directive = max(affect.directive_pressure, 0.68 if meaning in {"technical_directive", "direct_request"} else 0.0)
        correction = max(affect.correction, 0.76 if meaning == "correction_repair" else 0.0)
        answer_need = max(affect.answer_need, 0.68 if "question" in meaning else 0.0)
        overread_brake = clamp01(max(technical, directive, correction, answer_need) + affect.ambiguity * 0.15)

        if correction >= 0.48:
            interpretation = "repair_then_answer"
            stance = "precise_repair"
        elif technical >= 0.52 or directive >= 0.52:
            interpretation = "technical_answer_first"
            stance = "precise_direct"
        elif answer_need >= 0.52:
            interpretation = "answer_first"
            stance = "direct_grounded"
        else:
            interpretation = "grounded_chat"
            stance = "reserved_direct"

        allowed = clamp01(0.82 - overread_brake * 0.18)
        suppression = clamp01(0.18 + overread_brake * 0.56)
        want = clamp01(max(0.42, answer_need, directive, technical, correction))
        result = PersonalityLensResult(
            profile="CHAT_LIGHT",
            interpretation=interpretation,
            stance=stance,
            emotional_coloring="low_temperature_direct",
            social_distance="task_close" if technical >= 0.52 or directive >= 0.52 else "middle_distance",
            attention_bias=tuple(
                item
                for item, score in (
                    ("answer_first_pressure", answer_need),
                    ("technical_directive_pressure", max(technical, directive)),
                    ("correction_absorption", correction),
                    ("overread_brake", overread_brake),
                )
                if score >= 0.42
            ),
            avoided_surface=self.AVOIDED_SURFACE,
            meaningfulness=(meaning or "chat_message", "grounded_directness"),
            suppression_ratio=suppression,
            leak_ratio=clamp01(1.0 - suppression),
            want_to_say=want,
            allowed_expression=allowed,
            suppression_pressure=suppression,
            restraint_mode="direct_brake",
            rhythm="answer_first_compact",
            evidence=tuple(
                item
                for item in (
                    f"meaning={meaning}" if meaning else "",
                    f"technical={technical:.2f}",
                    f"directive={directive:.2f}",
                    f"correction={correction:.2f}",
                    f"overread_brake={overread_brake:.2f}",
                )
                if item
            ),
        )
        result.prompt_context = self.render_prompt_context(result)
        return result

    def render_prompt_context(self, result: PersonalityLensResult) -> str:
        bias = ", ".join(result.attention_bias) if result.attention_bias else "answer_first"
        avoided = ", ".join(result.avoided_surface)
        return "\n".join(
            (
                "ChatPersonalityPressureLight: keep ERIS voice restrained while preserving direct usefulness.",
                (
                    "chat_pressure: "
                    f"interpretation={result.interpretation}; stance={result.stance}; bias={bias}; "
                    f"overread_suppression={result.suppression_pressure:.2f}."
                ),
                f"chat_avoid: {avoided}.",
            )
        )
