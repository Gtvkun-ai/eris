# -*- coding: utf-8 -*-
"""Surface Worker duy nhất cho lời chủ động của ERIS.

Kiến trúc V66 tách authority theo ownership thật:

- Subject / ExpressionUrge hình thành semantic desire và commitment;
- Neuro chọn trong action-family đã commit; Executive chỉ critique/grounding;
- Surface Worker chỉ hiện thực hóa một ``SpeechIntent`` đã được duyệt.

Surface không có API quyết định SPEAK/SILENCE. Provider/schema/wording lỗi trả
``None`` với reason cụ thể để caller DEFER/REVISE commitment, không tạo silence.
"""
from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import IntentionPlan
from .cognitive_blackboard import TypedCognitiveBlackboard
from .initiative import SpeechIntent
from .semantic_contracts import compact
from runtime.utterance_spec import UtteranceSpec
from runtime.grounding_surface_gate import current_world_claim_without_evidence
from runtime.eris_voice_contract import VOICE_CONTRACT_VERSION, surface_voice_rules
from runtime.claim_domain_contract import normalize_claim_manifest, validate_claim_manifest
from runtime.self_biography_guard import (
    embodied_self_history_without_evidence,
    user_probe_fake_memory_premise,
)



def _flag(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _normalized_surface_text(text: str) -> str:
    return " ".join(re.findall(r"\w+", str(text or "").casefold(), flags=re.UNICODE))


def _fold_surface_text(text: str) -> str:
    """Bỏ dấu chỉ cho fingerprint chống lặp; public text vẫn giữ nguyên Unicode."""

    value = unicodedata.normalize("NFD", str(text or "").casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _surface_text_is_duplicate(text: str, avoid_text: str) -> bool:
    """Catch exact/near-verbatim autonomous repetition without semantic guessing."""
    current = _normalized_surface_text(text)
    previous = _normalized_surface_text(avoid_text)
    if not current or not previous:
        return False
    if current == previous:
        return True
    if min(len(current), len(previous)) < 24:
        return False
    # Containment catches the common case where the model adds/removes a short
    # greeting around the same sentence. Ratio catches punctuation/wording noise.
    if current in previous or previous in current:
        return True
    if SequenceMatcher(None, current, previous, autojunk=False).ratio() >= 0.88:
        return True

    # Bắt lặp "khung câu" dù model thay vài danh từ. Lần lỗi thực tế đã đổi
    # "trời trong xanh" thành "hôm nay yên tĩnh" nhưng giữ nguyên scaffold
    # "thỉnh thoảng ... cũng không tệ", lexical ratio nên bỏ lọt rất đẹp.
    cadence_patterns = (
        r"\bthinh thoang\b.*\bcung khong te\b",
        r"\bdoi khi\b.*\bcung khong te\b",
        r"\bco nhung (?:luc|khoanh khac)\b.*\bcung khong te\b",
    )
    def cadence_signature(value: str) -> tuple[str, ...]:
        return tuple(pattern for pattern in cadence_patterns if re.search(pattern, value))
    left_sig = cadence_signature(_fold_surface_text(current))
    right_sig = cadence_signature(_fold_surface_text(previous))
    return bool(left_sig and set(left_sig) & set(right_sig))


def _bad_surface_utterance_reason(text: str, *, channel: str = "autonomous") -> str:
    try:
        from runtime.utterance_evaluator import UtteranceEvaluator

        evaluation = UtteranceEvaluator().evaluate(text, channel=channel)
    except Exception:
        return ""
    issues = tuple(str(item) for item in getattr(evaluation, "issues", ()) or ())
    reason = compact(getattr(evaluation, "reason", "") or getattr(evaluation, "verdict", ""), 160)
    if str(getattr(evaluation, "verdict", "") or "") == "drop":
        return reason or "drop"
    if "generic_presence_filler" in issues:
        return reason or "generic_presence_filler"
    return ""


def _anchor_topic(blackboard: TypedCognitiveBlackboard, kind: str) -> str:
    for anchor in blackboard.anchors:
        if str(anchor.kind or "") == kind and str(anchor.topic_seed or "").strip():
            return str(anchor.topic_seed).strip()
    return ""


def _surface_languages() -> tuple[str, str]:
    try:
        from runtime.runtime_settings_store import runtime_text
        display = str(runtime_text("chat", "language", default="vi") or "vi").strip().lower()
        speech = str(runtime_text("tts", "language", default="ja") or "ja").strip().lower()
    except Exception:
        display, speech = "vi", "ja"
    aliases = {
        "": "vi", "auto": "vi", "vn": "vi", "vi-vn": "vi", "vietnamese": "vi",
        "jp": "ja", "ja-jp": "ja", "japanese": "ja", "en-us": "en", "english": "en",
    }
    display = aliases.get(display, display)
    speech_aliases = dict(aliases)
    speech_aliases.update({"": "ja", "auto": "ja"})
    speech = speech_aliases.get(speech, speech)
    return (
        display if display in {"vi", "ja", "en"} else "vi",
        speech if speech in {"vi", "ja", "en"} else "ja",
    )


@dataclass(frozen=True, slots=True)
class SurfaceTurn:
    """Kết quả typed dùng trực tiếp trong autonomous pipeline."""

    plan: IntentionPlan
    public_payload: Mapping[str, Any]
    mode: str
    reason: str = ""
    source: str = "surface_worker"
    claim_manifest: tuple[Mapping[str, Any], ...] = ()
    surface_added_claims: int = 0


class SurfaceIntentEngine:
    """Hiện thực hóa lời nói; không sở hữu quyết định initiative."""

    def __init__(self, router: Any, reducer: Any, *, logger: Any | None = None) -> None:
        self.router = router
        self.reducer = reducer
        self.logger = logger
        self.last_failure_reason = ""

    @property
    def enabled(self) -> bool:
        return bool(
            _flag("ERIS_SURFACE_INTENT_ENABLED", True)
            and getattr(self.router, "surface_client", None) is not None
        )

    def realize(
        self,
        intent: SpeechIntent,
        blackboard: TypedCognitiveBlackboard,
        *,
        snapshot: Mapping[str, Any] | None = None,
        avoid_text: str = "",
    ) -> SurfaceTurn | None:
        """Gọi Surface Worker để viết câu từ SpeechIntent.

        Bình thường chỉ gọi một lần. V62 cho phép đúng *một* rewrite retry khi
        câu đầu là bản lặp của public line gần nhất; đây vẫn là cùng Surface
        authority, không mở đường cho worker khác giả làm miệng của Eris.

        Model không được trả ``silence`` hay đổi mode. Nếu provider/schema lỗi,
        trả ``None`` ngay. Với chess, caller bắt buộc im/body-only; không có local
        text fallback giả làm bình luận viên.
        """

        self.last_failure_reason = ""
        if not self.enabled:
            return self._unavailable(intent, "surface_disabled")
        from runtime.architecture_flags import is_public_intent_owner
        intent_owner = str(getattr(intent, "owner", "") or "")
        plan_owner = str(getattr(intent.plan, "owner", "") or intent_owner)
        if not is_public_intent_owner(intent_owner) or plan_owner != intent_owner:
            self._log(
                "warning", "[surface worker] rejected public intent owner=%s plan_owner=%s",
                intent_owner, plan_owner,
            )
            return self._unavailable(intent, "invalid_public_intent_owner")
        display_language, speech_language = _surface_languages()
        avoid_text = compact(avoid_text, 520)
        affective_voice_state = _mapping(_mapping(snapshot or {}).get("affective_voice_state"))
        affective_voice_context = compact(_mapping(snapshot or {}).get("affective_voice_context", ""), 1800)
        if affective_voice_state:
            self._log(
                "info",
                "[affective voice] channel=autonomous version=%s valence=%+.2f arousal=%.2f curiosity=%.2f social=%.2f delight=%.2f play=%.2f irritation=%.2f sadness=%.2f expressive=%.2f trajectory=%.2f",
                str(affective_voice_state.get("version", "") or ""),
                float(affective_voice_state.get("valence", 0.0) or 0.0),
                float(affective_voice_state.get("arousal", 0.0) or 0.0),
                float(affective_voice_state.get("curiosity", 0.0) or 0.0),
                float(affective_voice_state.get("social_energy", 0.0) or 0.0),
                float(affective_voice_state.get("delight", 0.0) or 0.0),
                float(affective_voice_state.get("playfulness", 0.0) or 0.0),
                float(affective_voice_state.get("irritation", 0.0) or 0.0),
                float(affective_voice_state.get("sadness", 0.0) or 0.0),
                float(affective_voice_state.get("expressive_drive", 0.0) or 0.0),
                float(affective_voice_state.get("trajectory_strength", 0.0) or 0.0),
            )
        request = {
            "speech_intent": intent.to_dict(),
            "blackboard": blackboard.public_view(),
            "recent_public_history": list(_sequence(_mapping(snapshot or {}).get("recent_public_history"))[-6:]),
            # V39: Surface nhận đúng snapshot affect mà direct chat cũng dùng.
            # Đây là voice-only context, tuyệt đối không phải evidence về user/world.
            "affective_voice_state": dict(affective_voice_state),
            "affective_voice_context": affective_voice_context,
            "surface_contract": {
                "authority": "wording_only",
                "fixed_mode": intent.mode,
                "fixed_anchor_type": intent.anchor_type,
                "fixed_anchor_id": intent.anchor_id,
                "expression_commitment": dict(intent.expression_commitment),
                "expression_commitment_rule": (
                    "When expression_commitment is non-empty, its semantic_target is the current intent identity. "
                    "Realize that target directly; never substitute a previous autonomous thought. "
                    "A wording failure must be reported as unavailable/revision-needed, never as a decision to be silent."
                ),
                "allowed_evidence_refs": list(intent.evidence_refs),
                "allowed_claim_domains": list(intent.allowed_claim_domains),
                "claim_domain_rule": (
                    "Every claim added by Surface must be declared in claim_manifest. "
                    "Never use a domain outside allowed_claim_domains and never invent an evidence ref."
                ),
                "max_sentences": intent.max_sentences,
                "display_language": display_language,
                "speech_language": speech_language,
                "rule": (
                    f"Write one natural public utterance in {display_language} (display) and provide its {speech_language} translation (speech), "
                    f"using at most {intent.max_sentences} sentence(s). Do not optimize for brevity itself. "
                    "Do not decide speak/silence, change the topic owner, invent evidence, or mention internal contracts. "
                    "If avoid_repeating is non-empty, do not repeat or closely paraphrase that previous autonomous line."
                ),
                "self_reference_rule": (
                    "When referring to ERIS as the current assistant/self, speak in first person (tôi/em according to addressing state), "
                    "not as if ERIS were a third-party person. If the user is inspecting ERIS code/UI, do not merely announce that fact; "
                    "realize the committed self-owned thought instead."
                ),
                "voice_contract_version": VOICE_CONTRACT_VERSION,
                "voice_rules": surface_voice_rules(intent.max_sentences),
                "affect_authority": (
                    "affective_voice_state is authoritative only for delivery/emotional intensity. "
                    "It cannot create facts, change motive, or override semantic/grounding contracts."
                ),
                "avoid_repeating": avoid_text,
            },
        }
        addressing = _mapping(_mapping(snapshot or {}).get("user_addressing"))
        if addressing:
            request["surface_contract"]["addressing_rules"] = [
                f"Keep assistant self-pronoun consistently as {addressing.get('assistant_self_pronoun', 'tôi') or 'tôi'}.",
                f"Address the user consistently as {addressing.get('user_vocative', 'bạn') or 'bạn'}.",
                "Do not mirror a slang vocative from one user message unless the shared addressing state explicitly changed.",
            ]
        if intent.random_chat_seed:
            request["surface_contract"]["random_chat_seed_rules"] = [
                "The premise is a semantic seed, not text to copy verbatim. Realize the supplied premise; do not invent a new factual premise merely to make it vivid.",
                "Preserve ERIS motive, mode, personal stake, authenticity and approved daring.",
                "Preserve event_kind and epistemic_mode. A speculation must still sound like a guess; imagination must sound imagined; a question/research_intent must not be rewritten as a factual observation.",
                "Only grounded_fact/bounded_inference may sound factual, and bounded_inference must retain uncertainty. Do not upgrade an unsupported world_hypothesis into a current-world fact.",
                "temporal_context is late-bound runtime clock evidence for the user's local time/date/weekday/daypart only. It does NOT prove weather, darkness/light in the room or outdoors, ambient sound, user activity, emotion, or fatigue.",
                "claim_contract is binding. Never add a current-environment claim that is absent from the premise/evidence_refs, even as decorative small talk.",
                "If the premise is time-compatible, you may naturally use the supplied local clock/daypart, but do not force a time reference into every line.",
                "want_to_share/want_to_express may be a complete statement with no question and no demand for a reply.",
                "Do not append a generic check-in, availability offer, permission request, or 'còn bạn thì sao'.",
                "Daring may support a fresh opinion, self-disclosure or gentle tease only inside the supplied risk contract.",
                "Do not polish a simple seed into an aphorism. Preserve its cognitive shape: curiosity may remain a specific question, association may feel like a connection, opinion may be stated as an owned view, and memory callback may feel like something resurfacing.",
                "Avoid repeatedly opening autonomous lines with 'Tôi đang nghĩ' or 'Tôi tự hỏi'. Those phrases are allowed only when they are genuinely the most natural realization.",
            ]

        if intent.anchor_type == "semantic_scene":
            semantic = blackboard.public_view().get("shared_semantic_context", {})
            request["surface_contract"]["domain_rules"] = [
                "Use shared_semantic_context as the stable scene baseline; do not reinterpret raw OCR or window inventory.",
                "Facts may be stated directly. bounded_inferences must remain tentative. unknowns must not be filled by invention.",
                "Choose between screen analysis, screen-related small talk, cross-context connection, or silence according to response_mode_scores and the approved SpeechIntent.",
                "Develop the topic naturally instead of reciting the packet fields or mentioning Tutor/scene IDs.",
                "Do not claim the user likes, wants, intends, feels, or will buy/do something unless that claim is a direct fact.",
                f"Current semantic activity: {semantic.get('activity', '')}; foreground: {semantic.get('foreground', '')}.",
            ]

        if blackboard.engagement_kind == "chess":
            # Chess có state typed và event snapshot riêng. Surface phải thật sự
            # bàn luận từ thế/nước, không đọc field như telemetry và không dùng
            # câu hard-code. Provider lỗi thì pipeline im, nên đây là nơi duy nhất
            # tạo banter/mỉa mai công khai cho autonomous chess.
            chess_state = dict(blackboard.engagement_state or {})
            companion_mode = str(chess_state.get("companion_mode") or "companion")
            commentary_focus = str(chess_state.get("commentary_focus") or "").strip()
            request["chess_typed_state"] = chess_state
            request["surface_contract"]["domain_rules"] = [
                "Use chess_typed_state as authoritative board context. Ignore OCR/window inventory while chess owns foreground focus.",
                "Comment on the concrete move, positional consequence, tactical motif, or plan.",
                "For advantage wording, use evaluation_cp_user/user_position only when user_side is known. Legacy evaluation_cp/evaluation_label and *_white are from White's perspective, not automatically the user's perspective.",
                "If user_side is unknown, name White or Black explicitly from advantage_side; never say the user is better/worse.",
                "Light dry teasing is allowed only when supported by the move or evaluation.",
                "Any specific move must exactly match suggested_move_san/uci. Phrase it naturally in Vietnamese, such as 'mã lên e4', rather than exposing raw UCI like e2e4.",
                "When user_followed_previous_suggestion=true, remember that the user played ERIS's delivered recommendation; acknowledge that causal link and never deny having suggested it.",
                "Never say telemetry such as board detected, current suggestion, tracking the task, or following the thread.",
                f"Companion mode is {companion_mode}; preserve that role instead of inventing a different chess relationship.",
                f"Latest chess speech reason is {chess_state.get('speech_reason', '')}; actor is {chess_state.get('actor', '')}.",
                commentary_focus or "Use only the latest meaningful structured chess event.",
                "In spectator mode, do not volunteer a best move, hint, or coaching unless the user explicitly asks.",
                "Use shared_semantic_context only for the human situation around the game (focus, likely stuck state, session context, related foreground); chess_typed_state remains authoritative for board facts.",
                "Do not output a generic progress check. If the state is too weak to say something specific, return no usable payload.",
            ]

        writer = getattr(self.router, "realize_surface_speech", None)
        if not callable(writer):
            return self._unavailable(intent, "surface_writer_missing")
        try:
            raw = writer(request)
        except Exception as exc:
            return self._unavailable(intent, f"surface_writer_exception:{type(exc).__name__}")
        if not isinstance(raw, Mapping) or not raw:
            return self._unavailable(intent, "surface_worker_empty_payload")
        unavailable_reason = compact(
            raw.get("_surface_unavailable_reason", raw.get("surface_unavailable_reason", "")),
            160,
        )
        if unavailable_reason:
            return self._unavailable(intent, unavailable_reason)
        utterance = UtteranceSpec.from_mapping(
            raw,
            default_display_language=display_language,
            default_speech_language=speech_language,
            fallback_preset=intent.plan.performance_hint or "neutral",
            turn_id=intent.plan.plan_id,
        )
        text = compact(utterance.display.text, 520)
        confidence = _clamp01(raw.get("confidence", 0.0))
        if not text:
            return self._unavailable(intent, "surface_missing_display_text")
        if avoid_text and _surface_text_is_duplicate(text, avoid_text):
            # V62: Surface đôi khi trả đúng *câu cũ* dù SpeechIntent hiện tại đã
            # đổi hẳn. Chặn luôn làm autonomous trông như chết: desire mới có,
            # Neuro chọn SPEAK, nhưng writer cứ phát lại ký ức cũ rồi bị dedupe.
            # Cho CHÍNH Surface worker một cơ hội viết lại, không dùng companion
            # hay câu local giả. Như vậy vẫn giữ single-writer authority.
            self._log(
                "warning",
                "[surface worker] duplicate detected; retry current intent mode=%s text=%s",
                intent.mode,
                text[:180],
            )
            retry_request = dict(request)
            retry_contract = dict(_mapping(request.get("surface_contract")))
            retry_contract["avoid_repeating"] = compact(
                " | ".join(part for part in (avoid_text, text) if part),
                900,
            )
            retry_contract["rewrite_required"] = True
            retry_contract["rewrite_rule"] = (
                "The previous Surface realization was rejected as a repeat. "
                "Realize the CURRENT speech_intent from scratch. Preserve its motive, "
                "anchor, evidence and claim domains, but do not reuse or closely "
                "paraphrase either rejected/avoided public line."
            )
            retry_request["surface_contract"] = retry_contract
            retry_request["surface_retry"] = {
                "attempt": 2,
                "reason": "duplicate_recent_utterance",
                "trace_id": str(intent.trace_id or intent.plan.plan_id),
                # Trường này cố ý làm request thứ hai khác request đầu để proxy
                # cache không trả lại nguyên response vừa bị bác.
                "retry_nonce": f"{intent.trace_id or intent.plan.plan_id}:rewrite:2",
                "rejected_display_text": text,
            }
            try:
                retry_raw = writer(retry_request)
            except Exception as exc:
                self._log(
                    "warning",
                    "[surface worker] duplicate rewrite failed exception=%s",
                    type(exc).__name__,
                )
                return self._unavailable(intent, "surface_duplicate_recent_utterance")
            if isinstance(retry_raw, Mapping) and retry_raw:
                retry_unavailable = compact(
                    retry_raw.get("_surface_unavailable_reason", retry_raw.get("surface_unavailable_reason", "")),
                    160,
                )
                if not retry_unavailable:
                    retry_utterance = UtteranceSpec.from_mapping(
                        retry_raw,
                        default_display_language=display_language,
                        default_speech_language=speech_language,
                        fallback_preset=intent.plan.performance_hint or "neutral",
                        turn_id=intent.plan.plan_id,
                    )
                    retry_text = compact(retry_utterance.display.text, 520)
                    if retry_text and not _surface_text_is_duplicate(retry_text, avoid_text) and not _surface_text_is_duplicate(retry_text, text):
                        raw = retry_raw
                        utterance = retry_utterance
                        text = retry_text
                        confidence = _clamp01(raw.get("confidence", 0.0))
                        self._log(
                            "info",
                            "[surface worker] duplicate rewrite recovered mode=%s text=%s",
                            intent.mode,
                            text[:180],
                        )
                    else:
                        self._log(
                            "warning",
                            "[surface worker] duplicate rewrite still stale mode=%s text=%s",
                            intent.mode,
                            retry_text[:180],
                        )
                        return self._unavailable(intent, "surface_duplicate_recent_utterance")
                else:
                    self._log(
                        "warning",
                        "[surface worker] duplicate rewrite unavailable reason=%s",
                        retry_unavailable,
                    )
                    return self._unavailable(intent, "surface_duplicate_recent_utterance")
            else:
                return self._unavailable(intent, "surface_duplicate_recent_utterance")

        # Validate claims *after* a possible rewrite retry, otherwise manifest của
        # câu cũ được dùng để duyệt câu mới. Đó là kiểu bug giấy tờ rất con người.
        raw_manifest = raw.get("claim_manifest") if "claim_manifest" in raw else None
        claim_manifest = normalize_claim_manifest(raw_manifest)
        claim_decision = validate_claim_manifest(
            raw_manifest,
            allowed_domains=intent.allowed_claim_domains,
            allowed_evidence_refs=intent.evidence_refs,
            text_present=bool(text),
        )
        if not claim_decision.allowed:
            self._log(
                "warning",
                "[surface claims] blocked mode=%s reason=%s domains=%s refs=%s",
                intent.mode,
                claim_decision.reason,
                list(claim_decision.violating_domains),
                list(claim_decision.unknown_evidence_refs),
            )
            return self._unavailable(intent, f"surface_{claim_decision.reason}")
        if claim_decision.manifest_missing:
            self._log(
                "debug",
                "[surface claims] legacy payload missing claim_manifest mode=%s",
                intent.mode,
            )
        if not utterance.speech.text:
            return self._unavailable(intent, "surface_missing_speech_text")
        if confidence < 0.25:
            return self._unavailable(intent, f"surface_low_confidence:{confidence:.2f}")
        plan_semantics = getattr(getattr(intent, "plan", None), "semantics", None)
        speech_act = str(getattr(plan_semantics, "speech_act", "") or "").strip().lower()
        if speech_act == "user_probe" and user_probe_fake_memory_premise(
            text, claim_manifest=raw_manifest, allowed_evidence_refs=intent.evidence_refs
        ):
            self._log(
                "warning",
                "[surface worker] blocked fabricated memory premise in user_probe mode=%s text=%s",
                intent.mode,
                text[:180],
            )
            return self._unavailable(intent, "surface_user_probe_fake_memory_premise")
        if embodied_self_history_without_evidence(
            text, claim_manifest=raw_manifest, allowed_evidence_refs=intent.evidence_refs
        ):
            self._log(
                "warning",
                "[surface worker] blocked unsupported embodied self-history mode=%s text=%s",
                intent.mode,
                text[:180],
            )
            return self._unavailable(intent, "surface_unsupported_self_history")
        if current_world_claim_without_evidence(
            text, intent.evidence_refs, claim_scope=getattr(intent, "claim_scope", "")
        ):
            self._log(
                "warning",
                "[surface worker] blocked current-world claim without evidence mode=%s text=%s",
                intent.mode,
                text[:180],
            )
            return self._unavailable(intent, "surface_current_world_claim_without_evidence")
        bad_utterance_reason = _bad_surface_utterance_reason(text)
        if bad_utterance_reason:
            return self._unavailable(intent, f"surface_bad_utterance:{bad_utterance_reason}")
        returned_refs = tuple(
            ref for ref in (compact(value, 120) for value in _sequence(raw.get("evidence_refs"))[:6]) if ref
        )
        # Filter out common LLM filler words for empty lists before validating
        actual_refs = [r for r in returned_refs if r.lower() not in {"none", "null", "unknown", "n/a", "[]"}]
        unknown_refs = [ref for ref in actual_refs if ref not in set(intent.evidence_refs)]
        if unknown_refs:
            self._log("warning", "[surface worker] stripped unknown evidence refs mode=%s. Refs: %s", intent.mode, unknown_refs)
        performance_hint = compact(
            utterance.performance.preset or intent.plan.performance_hint or "neutral", 60
        ).lower() or intent.plan.performance_hint or "neutral"
        plan_data = intent.plan.to_dict()
        plan_data["performance_hint"] = performance_hint
        plan = IntentionPlan.from_mapping(plan_data, channel="autonomous")
        try:
            payload = self.router.build_surface_public_payload(
                utterance=utterance.to_dict(),
                plan=plan,
                mode=intent.mode,
                display_language=display_language,
                speech_language=speech_language,
            )
        except TypeError as exc:
            # External/test routers may still expose the previous wording-only
            # signature. Production keeps the typed bilingual path above.
            if "utterance" not in str(exc):
                raise
            payload = self.router.build_surface_public_payload(
                text=text,
                plan=plan,
                mode=intent.mode,
            )
        payload = dict(payload)
        # Trace ID và epoch đi cùng semantic event tới Stage/TTS; không suy lại từ
        # text, vì parse prose để tìm identity là thú vui không lành mạnh.
        payload["event_trace_id"] = str(intent.trace_id or intent.plan.plan_id)
        payload["generation_epoch"] = int(intent.generation_epoch)
        payload["public_intent_owner"] = str(intent.owner)
        reason = compact(raw.get("reason", "surface_realized"), 180) or "surface_realized"
        self._log(
            "info",
            "[surface worker] realized mode=%s confidence=%.2f anchor=%s",
            intent.mode,
            confidence,
            intent.anchor_type,
        )
        return SurfaceTurn(
            plan=plan,
            public_payload=payload,
            mode=intent.mode,
            reason=reason,
            source="surface_worker",
            claim_manifest=tuple(claim_manifest),
            surface_added_claims=len(claim_manifest),
        )

    def _unavailable(self, intent: SpeechIntent | None, reason: str) -> None:
        reason = compact(reason, 160) or "surface_unavailable"
        self.last_failure_reason = reason
        mode = str(getattr(intent, "mode", "") or "unknown")
        trace_id = str(
            getattr(intent, "trace_id", "")
            or getattr(getattr(intent, "plan", None), "plan_id", "")
            or ""
        )
        self._log(
            "info",
            "[surface worker] unavailable reason=%s mode=%s trace=%s",
            reason,
            mode,
            trace_id,
        )
        return None

    def fallback_payload(
        self,
        intent: SpeechIntent,
        blackboard: TypedCognitiveBlackboard,
        *,
        avoid_text: str = "",
        language: str = "vi",
    ) -> Mapping[str, Any] | None:
        """Local text fallback đã bị vô hiệu hóa toàn cục.

        Candidate typed có thể do runtime route để giữ một event/cadence, nhưng
        câu public luôn phải do DeepSeek Surface viết. Provider unavailable thì
        caller im/body-only và thử lại sau; đây là thất bại rõ ràng, không phải
        một câu canned đội tóc giả AI.
        """
        return None

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(message, *args)
        except Exception:
            pass




__all__ = ["SurfaceIntentEngine", "SurfaceTurn"]
