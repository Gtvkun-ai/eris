from __future__ import annotations

"""BanterArbiter - trọng tài duyên nói ở cửa ra.

Mục tiêu không phải "thêm hài" vào mọi câu. Một câu đùa có duyên phải có neo:
user vừa đùa, lượt mới tạo áp lực sửa lỗi, hoặc runtime có bằng chứng màn hình/ngữ cảnh rõ.
Không có neo thì im/repair gọn tốt hơn là diễn sâu.
"""

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Literal


BanterMode = Literal[
    "none",
    "protocol_repair",
    "correction_repair",
    "overread_challenge_repair",
    "screen_underclaim_repair",
    "grounded_media_aside",
]


@dataclass(frozen=True, slots=True)
class BanterDecision:
    mode: BanterMode = "none"
    text: str = ""
    reason: str = ""
    confidence: float = 0.0

    @property
    def changed(self) -> bool:
        return bool(self.text.strip() and self.mode != "none")


@dataclass(frozen=True, slots=True)
class CorrectionEvidence:
    """Các score evidence nhỏ cho repair, không phải verdict về ý định user.

    Một câu có thể đồng thời có áp lực sửa, chọc, khó hiểu và meta-challenge.
    Threshold bên dưới chỉ mở hành động kỹ thuật; chúng không được serialize
    thành claim kiểu ``user đang sửa`` hay ``user chỉ đang thách thức``.
    """

    explicit_correction_score: float = 0.0
    replacement_content_score: float = 0.0
    challenge_score: float = 0.0
    meta_challenge_score: float = 0.0

    @property
    def correction_pressure(self) -> float:
        base = max(self.explicit_correction_score, self.replacement_content_score)
        # Meta-challenge làm giảm quyền cam kết, nhưng không xóa hoàn toàn khả năng repair.
        return max(0.0, min(1.0, base * (1.0 - 0.55 * self.meta_challenge_score)))

    @property
    def challenge_pressure(self) -> float:
        return max(0.0, min(1.0, max(self.challenge_score, self.meta_challenge_score)))

    @property
    def repair_gate_open(self) -> bool:
        """Policy gate vận hành, không phải kết luận xã hội được lưu lại."""
        return self.correction_pressure >= 0.62

    @property
    def challenge_gate_open(self) -> bool:
        """Policy gate cho repair dè dặt khi previous frame có dấu hiệu overread."""
        return self.challenge_pressure >= 0.56


def _env_enabled() -> bool:
    raw = str(os.environ.get("ERIS_BANTER_ARBITER", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}


def _normalize_vi(text: str) -> str:
    lowered = str(text or "").strip().lower()
    try:
        fixed = lowered.encode("latin1").decode("utf-8")
        if fixed:
            lowered = fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    lowered = unicodedata.normalize("NFD", lowered)
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d").replace("Đ", "d")
    lowered = re.sub(r"[^a-z0-9_./#:+\-\s]", " ", lowered)
    return " ".join(lowered.split())


def _has_any(normalized: str, markers: tuple[str, ...]) -> bool:
    return any(marker in normalized for marker in markers)


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float)))
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text_of(item) for item in value)
    return str(value)


class BanterArbiter:
    """Quyết định khi nào được sửa câu cuối thành một repair/aside có duyên.

    Luật chính:
    - repair thắng joke;
    - joke phải bám evidence;
    - không bao giờ nói về JSON/parser/format/debug ra public;
    - khi correction pressure đủ mạnh, không hỏi lại rộng nếu có thể tự nhận sai gọn.
    """

    _PROTOCOL_MARKERS = (
        "json",
        "parser",
        "parse mode",
        "parse_mode",
        "debug",
        "protocol",
        "format",
        "dinh dang",
        "loi format",
        "loi dinh dang",
        "metadata",
        "reasoning tags",
        "reasoning_tags",
    )
    _CORRECTION_MARKERS = (
        "khong phai",
        "toi co code dau",
        "sai",
        "sai roi",
        "nham",
        "lech",
        "hieu sai",
        "chi nghe nhac",
    )
    _CHALLENGE_ONLY_MARKERS = (
        "gi vay",
        "la sao",
        "wtf",
    )
    _META_CHALLENGE_MARKERS = (
        "hieu sai la sao",
        "toi da noi gi dau",
        "toi da noi gi",
        "toi noi gi dau",
        "co sua gi dau",
        "toi sua gi dau",
    )
    _REPLACEMENT_MARKERS = (
        "y toi la",
        "y minh la",
        "toi noi la",
        "toi bao la",
        "sua lai la",
        "phai la",
        "dung ra la",
        "actually",
        "not what i mean",
    )
    _GENERIC_CLARIFY_MARKERS = (
        "ngai dang lam gi vay",
        "ngai co the mo ta",
        "ngai co the noi ro",
        "toi chua hieu",
        "co ve nhu toi da hieu sai",
    )
    _SCREEN_UNDERCLAIM_MARKERS = (
        "khong co kha nang nhin man hinh",
        "khong the nhin man hinh",
        "khong nhin duoc man hinh",
        "chi co the phan hoi dua tren nhung gi ngai chia se",
        "khong co quyen truy cap man hinh",
    )
    _MINDREADING_MEDIA_MARKERS = (
        "co le ngai dang tim kiem",
        "co le ngai dang suy nghi",
        "mot chut tinh lang",
        "giup ngai suy nghi ro hon",
        "tim kiem mot goc nhin",
    )

    def arbitrate(
        self,
        decision: Any,
        *,
        channel: str,
        user_text: str = "",
        previous_text: str = "",
        grounding: Any = None,
        frame: Any = None,
        speech_core: Any = None,
    ) -> BanterDecision:
        if not _env_enabled():
            return BanterDecision(reason="disabled")
        text = str(getattr(decision, "text", "") or "").strip()
        if not text or not bool(getattr(decision, "should_speak", True)):
            return BanterDecision(reason="no_public_text")

        normalized_text = _normalize_vi(text)
        normalized_user = _normalize_vi(user_text)
        previous_norm = _normalize_vi(previous_text)
        grounding = grounding or self._grounding_from(frame)
        evidence_blob = self._evidence_blob(grounding=grounding, frame=frame, speech_core=speech_core)

        if self._looks_like_protocol_surface(normalized_text, decision):
            return BanterDecision(
                mode="protocol_repair",
                text=self._protocol_repair_text(normalized_user=normalized_user, previous_norm=previous_norm, evidence_blob=evidence_blob),
                reason="blocked_protocol_surface",
                confidence=0.82,
            )

        if self._has_screen_evidence(grounding, evidence_blob) and _has_any(normalized_text, self._SCREEN_UNDERCLAIM_MARKERS):
            return BanterDecision(
                mode="screen_underclaim_repair",
                text="Tôi có tín hiệu màn hình. Câu đúng hơn là: tôi đọc ngữ cảnh vừa rồi sai.",
                reason="screen_underclaim_with_evidence",
                confidence=0.86,
            )

        correction = self._assess_user_correction(normalized_user)
        if correction.repair_gate_open:
            repair = self._correction_repair_text(
                normalized_user=normalized_user,
                previous_norm=previous_norm,
                current_norm=normalized_text,
                evidence_blob=evidence_blob,
                correction=correction,
            )
            if repair:
                return BanterDecision(
                    mode="correction_repair",
                    text=repair,
                    reason="correction_pressure_first",
                    confidence=0.80,
                )

        if correction.challenge_gate_open and self._needs_overread_challenge_repair(normalized_text):
            return BanterDecision(
                mode="overread_challenge_repair",
                text=self._overread_challenge_repair_text(
                    normalized_user=normalized_user,
                    previous_norm=previous_norm,
                    current_norm=normalized_text,
                ),
                reason="challenge_pressure_without_replacement",
                confidence=0.78,
            )

        if channel in {"autonomous", "force_speak"} and self._should_downgrade_media_mindread(normalized_text, evidence_blob):
            return BanterDecision(
                mode="grounded_media_aside",
                text=self._grounded_media_aside(evidence_blob),
                reason="media_context_mindread_downgrade",
                confidence=0.66,
            )

        return BanterDecision(reason="kept")

    def apply(self, decision: Any, banter: BanterDecision) -> Any:
        if not banter.changed:
            return decision
        trace = str(getattr(decision, "debug_trace", "") or "").strip()
        marker = f"banter_arbiter={banter.mode};reason={banter.reason}"
        debug_trace = f"{trace} | {marker}" if trace else marker
        try:
            tags = tuple(getattr(decision, "reasoning_tags", ()) or ())
            return replace(
                decision,
                text=banter.text,
                intent=self._intent_for(banter.mode, getattr(decision, "intent", "")),
                action="guarded_reply" if banter.mode.endswith("repair") else getattr(decision, "action", "observe"),
                reasoning_tags=tuple(dict.fromkeys((*tags, "banter_arbiter", banter.mode))),
                should_speak=True,
                confidence=max(float(getattr(decision, "confidence", 0.0) or 0.0), banter.confidence),
                debug_trace=debug_trace,
                parse_mode="banter_arbiter",
                system_action="",
                action_input="",
            )
        except Exception:
            # Nếu Decision không phải dataclass chuẩn, mutate tại chỗ để không làm chết hot path.
            decision.text = banter.text
            decision.intent = self._intent_for(banter.mode, getattr(decision, "intent", ""))
            decision.should_speak = True
            decision.debug_trace = debug_trace
            decision.parse_mode = "banter_arbiter"
            return decision

    def repair_correction(
        self,
        *,
        user_text: str,
        previous_text: str,
        grounding: Any = None,
        frame: Any = None,
        speech_core: Any = None,
    ) -> BanterDecision:
        """Sinh repair khi lượt mới tạo áp lực phủ định/sửa câu public trước.

        Đây là API cho chat-cycle trước khi gọi LLM. Nó giúp Eris sửa nhịp như
        một chủ thể đang bị bắt lỗi: nhận frame sai, bỏ frame đó, rồi dừng. Nếu
        evidence chưa đủ mở repair gate, trả none để pipeline bình thường tiếp tục.
        """
        if not _env_enabled():
            return BanterDecision(reason="disabled")
        normalized_user = _normalize_vi(user_text)
        previous_norm = _normalize_vi(previous_text)
        correction = self._assess_user_correction(normalized_user)
        if not correction.repair_gate_open:
            if correction.challenge_gate_open:
                if not self._previous_text_invites_challenge_repair(previous_norm):
                    return BanterDecision(reason="challenge_without_bad_previous_frame")
                return BanterDecision(
                    mode="overread_challenge_repair",
                    text=self._overread_challenge_repair_text(
                        normalized_user=normalized_user,
                        previous_norm=previous_norm,
                        current_norm="",
                    ),
                    reason="previous_public_turn_challenged_without_replacement",
                    confidence=0.80,
                )
            return BanterDecision(reason="correction_pressure_below_gate")
        if not previous_norm:
            return BanterDecision(reason="no_previous_public_text")
        evidence_blob = self._evidence_blob(grounding=grounding, frame=frame, speech_core=speech_core)
        text = self._correction_repair_text(
            normalized_user=normalized_user,
            previous_norm=previous_norm,
            current_norm="",
            evidence_blob=evidence_blob,
            correction=correction,
        )
        if not text:
            return BanterDecision(reason="no_repair_text")
        return BanterDecision(
            mode="correction_repair",
            text=text,
            reason="previous_public_turn_correction_pressure",
            confidence=0.82,
        )

    def _grounding_from(self, frame: Any) -> Any:
        if frame is None:
            return None
        return getattr(frame, "source_grounding", None) or getattr(frame, "grounding", None)

    def _evidence_blob(self, *, grounding: Any = None, frame: Any = None, speech_core: Any = None) -> str:
        chunks: list[str] = []
        for obj in (grounding, frame, speech_core):
            if obj is None:
                continue
            for name in (
                "prompt_context",
                "screen_facts_preview",
                "evidence",
                "evidence_preview",
                "extracted_fact",
                "debug_trace",
                "grounding_source",
                "intent",
            ):
                chunks.append(_text_of(getattr(obj, name, "")))
        return _normalize_vi(" ".join(chunks))

    def _looks_like_protocol_surface(self, normalized_text: str, decision: Any) -> bool:
        intent = _normalize_vi(getattr(decision, "intent", ""))
        if "protocol_repair" in intent:
            return True
        # `hard_json_repair` only means the parser had to salvage structure.
        # The same is true for other parser/block modes: some of them are
        # deliberate public block messages, not leaks. Only rewrite when the
        # surfaced text itself leaks protocol/debug markers.
        return _has_any(normalized_text, self._PROTOCOL_MARKERS)

    def _assess_user_correction(self, normalized_user: str) -> CorrectionEvidence:
        if not normalized_user:
            return CorrectionEvidence()
        challenge = (
            normalized_user in {"ha", "hả", "gi", "gi vay", "wtf"}
            or _has_any(normalized_user, self._CHALLENGE_ONLY_MARKERS)
        )
        meta_challenge = _has_any(normalized_user, self._META_CHALLENGE_MARKERS)
        has_replacement = _has_any(normalized_user, self._REPLACEMENT_MARKERS)
        explicit = _has_any(normalized_user, self._CORRECTION_MARKERS)

        # "hiểu sai là sao/tôi đã nói gì đâu" thường là meta-challenge. Ta chỉ
        # hạ correction pressure, không đóng dấu user chắc chắn không sửa gì.
        if meta_challenge and not has_replacement:
            return CorrectionEvidence(
                explicit_correction_score=0.18 if explicit else 0.0,
                replacement_content_score=0.0,
                challenge_score=0.72 if challenge else 0.58,
                meta_challenge_score=0.92,
            )
        return CorrectionEvidence(
            explicit_correction_score=0.86 if explicit else 0.0,
            replacement_content_score=0.92 if has_replacement else 0.0,
            challenge_score=0.68 if challenge else 0.0,
            meta_challenge_score=0.0,
        )

    def _has_screen_evidence(self, grounding: Any, evidence_blob: str) -> bool:
        if grounding is not None:
            if bool(getattr(grounding, "screen_evidence_present", False)):
                return True
            if tuple(getattr(grounding, "screen_facts_preview", ()) or ()):
                return True
            source = str(getattr(grounding, "grounding_source", "") or "")
            if source in {"live_vision", "current_screen"}:
                return True
        return _has_any(evidence_blob, ("youtube", "video", "music", "nhac", "anime", "screen", "man hinh"))

    def _protocol_repair_text(self, *, normalized_user: str, previous_norm: str, evidence_blob: str) -> str:
        correction = self._assess_user_correction(normalized_user)
        if correction.repair_gate_open:
            return self._correction_repair_text(
                normalized_user=normalized_user,
                previous_norm=previous_norm,
                current_norm="",
                evidence_blob=evidence_blob,
                correction=correction,
            ) or "Ừ, câu đó lệch. Tôi rút lại, không dựng tiếp trên nó."
        return "Câu đó lệch. Tôi rút lại một nhịp."

    def _correction_repair_text(
        self,
        *,
        normalized_user: str,
        previous_norm: str,
        current_norm: str,
        evidence_blob: str,
        correction: CorrectionEvidence | None = None,
    ) -> str:
        correction = correction or self._assess_user_correction(normalized_user)
        mentions_code = "code" in previous_norm or "code" in current_norm or "code" in normalized_user
        media_anchor = _has_any(evidence_blob, ("youtube", "video", "music", "nhac", "anime"))
        if mentions_code and media_anchor:
            return "Ừ, tôi đoán quá tay. YouTube/nhạc mà tôi kéo sang code, tự tin hơi quá."
        if mentions_code:
            return "Ừ, tôi vừa gán nhầm nó thành code. Tôi bỏ frame đó."
        if "chi nghe nhac" in normalized_user or "nghe nhac" in normalized_user:
            return "À, chỉ nghe nhạc thôi. Tôi vừa dựng nguyên chuyện trên một cái playlist."
        if _has_any(current_norm, self._GENERIC_CLARIFY_MARKERS):
            return "Ừ, tôi hiểu sai. Tôi bỏ frame đó, không hỏi vòng thêm."
        if normalized_user in {"ha", "hả", "gi", "gi vay"}:
            return "Câu vừa rồi không có neo. Bỏ qua nó đi."
        if correction.replacement_content_score >= 0.58:
            return "Ừ, tôi hiểu sai. Tôi bỏ frame đó, nói lại theo phần Ngài vừa chỉnh."
        return "Ừ, tôi hiểu sai. Tôi bỏ frame đó, không dựng tiếp trên nó."

    def _needs_overread_challenge_repair(self, normalized_text: str) -> bool:
        return (
            _has_any(normalized_text, self._GENERIC_CLARIFY_MARKERS)
            or _has_any(normalized_text, ("cam thay khong thoai mai", "phan ung cua ngai", "ngai dang"))
            or "khong du neo" in normalized_text
        )

    def _previous_text_invites_challenge_repair(self, previous_norm: str) -> bool:
        return _has_any(
            previous_norm,
            (
                "can mot chut thoi gian",
                "du luan trong tam tri",
                "khong thoai mai",
                "phan ung cua ngai",
                "hieu sai",
                "vua sua",
                "vua chinh",
                "bo frame",
                "khong du neo",
            ),
        )

    def _overread_challenge_repair_text(self, *, normalized_user: str, previous_norm: str, current_norm: str) -> str:
        if _has_any(normalized_user, self._META_CHALLENGE_MARKERS):
            return "Đúng, Ngài chưa sửa gì cả. Tôi tự gán nhầm frame đó."
        if _has_any(previous_norm, ("can mot chut thoi gian", "du luan trong tam tri", "khong thoai mai")):
            return "Ừ, câu vừa rồi tôi tự suy quá tay. Ngài chỉ đang hỏi lại thôi."
        if _has_any(current_norm, ("phan ung cua ngai", "khong thoai mai", "ngai dang")):
            return "Ừ, câu đó gán cảm xúc hơi vội. Tôi rút lại."
        return "Câu vừa rồi không đủ neo. Tôi rút lại."

    def _should_downgrade_media_mindread(self, normalized_text: str, evidence_blob: str) -> bool:
        if not _has_any(evidence_blob, ("youtube", "video", "music", "nhac", "anime")):
            return False
        return _has_any(normalized_text, self._MINDREADING_MEDIA_MARKERS)

    def _grounded_media_aside(self, evidence_blob: str) -> str:
        if _has_any(evidence_blob, ("music", "nhac")):
            return "Đang là nhạc thôi. Tôi không dựng thêm chuyện lên đó."
        return "Đang là YouTube thôi. Tôi hạ suy diễn xuống."

    def _intent_for(self, mode: BanterMode, fallback: str) -> str:
        if mode in {"protocol_repair", "correction_repair", "overread_challenge_repair", "screen_underclaim_repair"}:
            return "grounded_repair"
        if mode == "grounded_media_aside":
            return "grounded_aside"
        return str(fallback or "banter")
