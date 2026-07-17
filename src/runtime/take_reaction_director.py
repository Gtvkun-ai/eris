# -*- coding: utf-8 -*-
"""take_reaction_director.py — biến kết quả Tutor thành một phản ứng có diễn tiến.

Điểm khác với ``"À. {{tutor_answer}}"`` là runtime không xem câu trả lời của
Tutor như lời thoại đã hoàn thiện. Tutor cung cấp tri thức; Eris vẫn phải:

    nhận ra -> lộ giả định cũ -> đổi cách hiểu -> để lại dư âm

Đây là lớp *surface realization* dành riêng cho take quay. Nó không thêm fact
mới và không giả vờ autonomous. Take có thể khóa sẵn ``summary``/``afterthought``
để quay lặp lại ổn định, hoặc cho model mạnh viết lại từ evidence khi rehearsal.
Mọi lỗi model đều rơi về đường deterministic sạch, không làm take chết giữa sân
khấu chỉ vì một JSON quên đóng ngoặc. Nhân loại đã có đủ drama rồi.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from llm.json_sanitizer import extract_last_valid_json_object, strip_reasoning_envelope


_URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_CITATION_RE = re.compile(r"(?:【[^】]+】|\[(?:\d+|source[^\]]*)\])", flags=re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦]+|\d+[.)])\s+")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*")
_SOURCE_LINE_RE = re.compile(r"^\s*(?:nguồn|sources?|tham khảo|references?)\s*[:：]", flags=re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True, slots=True)
class TakeReactionLine:
    """Một nhịp nói nhỏ trong reaction arc."""

    phase: str
    text: str
    pause_after_ms: int
    motion: str
    emotion: str
    tts_style: str


@dataclass(frozen=True, slots=True)
class TakeReaction:
    """Kết quả đã sẵn sàng đưa qua StageFrame/TTS."""

    lines: tuple[TakeReactionLine, ...]
    spoken_summary: str
    clean_answer: str
    pre_hold_ms: int = 320
    source: str = "deterministic"


class TutorReactionDirector:
    """Đạo diễn phản ứng sau khi Tutor trả lời.

    Model là tùy chọn. Với bản quay chính thức, ``locked_summary`` và
    ``afterthought`` nên được ghi ngay trong take JSON để fact, nhịp và cá tính
    lặp lại ổn định giữa các take. Model phù hợp hơn cho rehearsal hoặc chủ đề
    động, nơi cần rút một answer mới thành lời nói tự nhiên.
    """

    def __init__(self, owner: Any | None = None) -> None:
        self.owner = owner

    def direct(
        self,
        *,
        query: str,
        answer: str,
        lead_in: str = "À...",
        expectation: str = "",
        locked_summary: str = "",
        afterthought: str = "",
        angle: str = "",
        use_model: bool = False,
        max_sentences: int = 2,
        response_hold_ms: int = 320,
        final_pause_ms: int = 760,
        emotion: str = "curious_warm",
        motion: str = "assimilate",
        tts_style: str = "curious_discovery",
    ) -> TakeReaction:
        clean_answer = clean_tutor_answer(answer, max_sentences=max(2, max_sentences + 1))
        summary = clean_spoken_text(locked_summary, limit=420)
        resolved_lead = clean_spoken_text(lead_in, limit=40)
        resolved_after = clean_spoken_text(afterthought, limit=180)
        resolved_expectation = clean_spoken_text(expectation, limit=220)
        source = "locked" if summary else "deterministic"

        if not summary and use_model and clean_answer:
            generated = self._generate_with_model(
                query=query,
                answer=clean_answer,
                expectation=expectation,
                angle=angle,
                max_sentences=max_sentences,
            )
            if generated:
                summary = clean_spoken_text(generated.get("discovery", ""), limit=420)
                resolved_lead = clean_spoken_text(generated.get("lead_in", resolved_lead), limit=40)
                resolved_after = clean_spoken_text(generated.get("afterthought", resolved_after), limit=180)
                resolved_expectation = clean_spoken_text(
                    generated.get("contrast", resolved_expectation), limit=220
                )
                emotion = _enum_text(generated.get("emotion"), emotion, 64)
                motion = _enum_text(generated.get("motion"), motion, 64)
                tts_style = _enum_text(generated.get("tts_style"), tts_style, 64)
                source = "model"

        if not summary:
            summary = clean_tutor_answer(clean_answer, max_sentences=max_sentences)
        if not summary:
            summary = "Tôi chưa lấy được một câu trả lời đủ sạch để nói lại."
            emotion = "quiet_uncertain"
            motion = "settle"
            tts_style = "quiet_repair"
            source = "empty_fallback"

        lines: list[TakeReactionLine] = []
        if resolved_lead and not _same_opening(resolved_lead, summary):
            lines.append(TakeReactionLine(
                phase="recognition",
                text=resolved_lead,
                pause_after_ms=260,
                motion="recognition",
                emotion=emotion,
                tts_style="soft_realization",
            ))

        if resolved_expectation and not _semantic_duplicate(resolved_expectation, summary):
            lines.append(TakeReactionLine(
                phase="contrast",
                text=resolved_expectation,
                pause_after_ms=300,
                motion="belief_update",
                emotion=emotion,
                tts_style="quiet_contrast",
            ))

        lines.append(TakeReactionLine(
            phase="reframe",
            text=summary,
            pause_after_ms=420 if resolved_after else max(320, int(final_pause_ms)),
            motion=motion or "assimilate",
            emotion=emotion,
            tts_style=tts_style,
        ))

        if resolved_after and not _semantic_duplicate(resolved_after, summary):
            lines.append(TakeReactionLine(
                phase="afterthought",
                text=resolved_after,
                pause_after_ms=max(320, min(2400, int(final_pause_ms))),
                motion="afterthought",
                emotion="warm_soft" if "warm" in emotion or "curious" in emotion else emotion,
                tts_style="dry_afterthought",
            ))

        return TakeReaction(
            lines=tuple(lines),
            spoken_summary=summary,
            clean_answer=clean_answer,
            pre_hold_ms=max(120, min(1600, int(response_hold_ms))),
            source=source,
        )

    def _generate_with_model(
        self,
        *,
        query: str,
        answer: str,
        expectation: str,
        angle: str,
        max_sentences: int,
    ) -> dict[str, Any] | None:
        """Gọi lane mạnh một lần; mọi lỗi đều trả ``None`` để dùng fallback."""

        injected = getattr(self.owner, "generate_take_reaction", None)
        if callable(injected):
            try:
                value = injected(
                    query=query,
                    answer=answer,
                    expectation=expectation,
                    angle=angle,
                    max_sentences=max_sentences,
                )
                return _coerce_mapping(value)
            except Exception:
                return None

        service = getattr(self.owner, "llm_service", None)
        client = (
            getattr(service, "escalation_client", None)
            or getattr(service, "client", None)
            or getattr(service, "style_client", None)
            or getattr(service, "fallback_client", None)
        )
        complete = getattr(client, "create_chat_completion", None)
        if not callable(complete):
            return None

        system = (
            "Bạn là surface director cho ERIS trong một take VTuber ngắn. "
            "Tutor đã cung cấp evidence; bạn chỉ biến evidence thành lời nói tại chỗ. "
            "ERIS bình tĩnh, thông minh, hơi khô, không cute quá, không giọng trợ lý. "
            "Phản ứng phải có cảm giác vừa hiểu ra, nhưng không bịa cảm xúc, trải nghiệm hay fact. "
            "Không markdown, bullet, URL, trích nguồn, lời chào, hay câu kiểu 'theo kết quả tìm kiếm'. "
            "Trả đúng JSON object."
        )
        user = (
            f"Câu hỏi: {query}\n"
            f"Evidence Tutor: {answer}\n"
            f"Điều Eris từng nghi/nghĩ trước đó (có thể rỗng): {expectation}\n"
            f"Góc diễn mong muốn (có thể rỗng): {angle}\n\n"
            "JSON schema:\n"
            "{\"lead_in\":\"À... hoặc một phản ứng cực ngắn\","
            "\"contrast\":\"giả định cũ ngắn, ngôi thứ nhất; được phép rỗng\","
            "\"discovery\":\"1-2 câu nói tự nhiên, chỉ dùng fact trong evidence\","
            "\"afterthought\":\"một nhận xét cá tính rất ngắn, được phép rỗng\","
            "\"emotion\":\"curious_warm|quiet_uncertain|warm_soft\","
            "\"motion\":\"recognition|assimilate|afterthought|settle\","
            "\"tts_style\":\"curious_discovery|quiet_repair|dry_afterthought\"}\n"
            f"Discovery tối đa {max(1, min(3, int(max_sentences)))} câu và 320 ký tự. "
            "Contrast tối đa 150 ký tự. Afterthought tối đa 110 ký tự. "
            "Không lặp nguyên văn evidence."
        )
        try:
            raw = complete(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.45,
                frequency_penalty=0.15,
                presence_penalty=0.0,
                max_tokens=300,
                response_format={"type": "json_object"},
                timeout=45,
                reasoning_effort="medium",
            )
            content = _extract_model_content(raw)
            cleaned = strip_reasoning_envelope(content)
            candidate = extract_last_valid_json_object(cleaned) or cleaned
            parsed = json.loads(candidate)
            return _coerce_mapping(parsed)
        except Exception:
            return None


def clean_tutor_answer(text: str, *, max_sentences: int = 2) -> str:
    """Dọn answer thành văn nói, không cho TTS đọc bullet/URL/citation."""

    raw = str(text or "").replace("```", "\n")
    raw = _MARKDOWN_LINK_RE.sub(r"\1", raw)
    raw = _URL_RE.sub("", raw)
    raw = _CITATION_RE.sub("", raw)

    lines: list[str] = []
    for line in raw.splitlines():
        if _SOURCE_LINE_RE.match(line):
            break
        clean = _HEADING_RE.sub("", line)
        clean = _BULLET_RE.sub("", clean)
        clean = " ".join(clean.split()).strip(" -•\t")
        if clean:
            lines.append(clean)
    merged = " ".join(lines)
    merged = re.sub(r"\s+([,.;:!?])", r"\1", merged)
    merged = " ".join(merged.split()).strip()
    if not merged:
        return ""

    sentences = [piece.strip() for piece in _SENTENCE_RE.split(merged) if piece.strip()]
    picked = sentences[: max(1, min(4, int(max_sentences)))]
    result = " ".join(picked).strip()
    return clean_spoken_text(result, limit=520)


def clean_spoken_text(text: str, *, limit: int) -> str:
    value = str(text or "")
    value = _MARKDOWN_LINK_RE.sub(r"\1", value)
    value = _URL_RE.sub("", value)
    value = _CITATION_RE.sub("", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = " ".join(value.split()).strip()
    if len(value) > max(1, int(limit)):
        value = value[: max(1, int(limit))].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return value


def _extract_model_content(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], Mapping) else {}
        message = first.get("message") if isinstance(first, Mapping) else {}
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                return content
        text = first.get("text") if isinstance(first, Mapping) else ""
        if isinstance(text, str):
            return text
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0] if isinstance(candidates[0], Mapping) else {}
        content = first.get("content") if isinstance(first, Mapping) else {}
        parts = content.get("parts") if isinstance(content, Mapping) else []
        if isinstance(parts, list):
            texts = [str(part.get("text", "")) for part in parts if isinstance(part, Mapping)]
            if texts:
                return "\n".join(texts)
    for key in ("content", "response", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _coerce_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(extract_last_valid_json_object(value) or value)
            return dict(parsed) if isinstance(parsed, Mapping) else None
        except Exception:
            return None
    return None


def _enum_text(value: Any, default: str, limit: int) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "", str(value or "").strip())[:limit]
    return clean or default


def _same_opening(lead: str, summary: str) -> bool:
    a = re.sub(r"\W+", "", lead.lower())
    b = re.sub(r"\W+", "", summary.lower())
    return bool(a and b.startswith(a))


def _semantic_duplicate(a: str, b: str) -> bool:
    def tokens(text: str) -> set[str]:
        return {token for token in re.findall(r"\w+", text.lower(), flags=re.UNICODE) if len(token) > 2}

    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return overlap >= 0.82


__all__ = [
    "TakeReaction",
    "TakeReactionLine",
    "TutorReactionDirector",
    "clean_spoken_text",
    "clean_tutor_answer",
]
