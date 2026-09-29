# -*- coding: utf-8 -*-
"""ConversationDirector: biến reasoning dài thành nhịp nói tự nhiên, có giới hạn.

Director KHÔNG sở hữu factual truth và KHÔNG viết câu public cuối. Nó chỉ làm ba việc:
1) gộp DialogueBeat qua nhiều vòng agent mà không lặp claim;
2) chọn bao nhiêu beat được phép nói ở turn hiện tại;
3) giữ phần còn lại thành continuation/deferred state cho turn sau.
"""
from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from .contracts import (
    ContinuationPlan,
    DialogueBeat,
    DisclosureMode,
    DiscoursePlan,
    TurnSpeechBudget,
)
from .speech import estimate_beat, words_for_seconds


_WORD_RE = re.compile(r"[^\wÀ-ỹ]+", re.UNICODE)


def _fingerprint(text: str) -> str:
    return _WORD_RE.sub(" ", str(text or "").lower()).strip()[:360]


class ConversationDirector:
    """Owner duy nhất của pacing public trong foreground turn.

    Lưu ý kiến trúc:
    - AgentLoop có thể chạy 5 vòng và biết 10 ý.
    - Tutor có thể có learning plan nhiều bước.
    - Director vẫn được quyền cho public writer nói *một* beat rồi dừng.
    """

    DEFAULT_STYLE_NOTES = (
        "Ưu tiên phát hiện/kết luận quan trọng trước rồi mới giải thích sâu.",
        "Dùng progressive disclosure; không biến mọi ý thành heading hoặc checklist.",
        "Mỗi nhịp nói chỉ nên có một mục đích giao tiếp rõ.",
        "Không lặp lại cùng một claim chỉ để kéo dài câu trả lời.",
        "Không public chain-of-thought; chỉ nói kết luận, bằng chứng, ví dụ và lý do giải thích được.",
        "Nếu còn nhiều nhánh hay, giữ lại cho lượt sau thay vì xổ hết trong một lần.",
    )

    def merge(self, current: DiscoursePlan, incoming: DiscoursePlan, *, max_beats: int = 8) -> DiscoursePlan:
        """Gộp kết quả nhiều iteration nhưng chưa áp speech budget cuối cùng."""
        beats: list[DialogueBeat] = []
        seen: set[str] = set()
        for beat in (*current.beats, *incoming.beats):
            if not beat.proposition or not beat.say_now:
                continue
            key = _fingerprint(beat.proposition)
            if not key or key in seen:
                continue
            seen.add(key)
            beats.append(beat)
            if len(beats) >= max(2, max_beats):
                break

        notes = self._dedupe((*self.DEFAULT_STYLE_NOTES, *current.style_notes, *incoming.style_notes), 10)
        mode = incoming.response_mode or current.response_mode or "normal"
        disclosure_mode = incoming.disclosure_mode or current.disclosure_mode

        # Incoming budget là proposal mới nhất của executive. Normalize ở đây để
        # writer không bao giờ nhận số âm / cực lớn do model payload lỗi.
        budget = incoming.speech_budget.normalized()
        continuation = incoming.continuation
        if not continuation.active_thread:
            continuation = replace(
                continuation,
                active_thread=current.continuation.active_thread,
            )
        return DiscoursePlan(
            response_mode=mode,
            disclosure_mode=disclosure_mode,
            beats=tuple(beats),
            style_notes=notes,
            user_response_required=bool(current.user_response_required or incoming.user_response_required),
            speech_budget=budget,
            continuation=continuation,
        )

    def apply_turn_pacing(
        self,
        plan: DiscoursePlan,
        *,
        voice_mode: bool,
        explicit_exhaustive_request: bool = False,
        tts_speed: float = 1.0,
    ) -> DiscoursePlan:
        """Chọn *ý nào nói lượt này* nhưng không cap/cắt cách writer diễn đạt.

        Boundary V6:
        - ConversationDirector được quyền progressive-disclosure ở mức semantic
          beat: nói 1–2 ý rồi giữ phần khác cho lượt sau.
        - ``target_words`` / ``target_seconds`` chỉ là gợi ý nhịp và telemetry.
        - Runtime **không** dùng word/time để loại bớt câu sau khi writer sinh.
        - Không có hard cap public wording. Một beat khó có thể cần nhiều câu;
          writer phải được phép nói cho trọn ý thay vì bị chặt giữa chừng.
        """
        proposed = plan.speech_budget.normalized()
        disclosure_mode = plan.disclosure_mode

        if explicit_exhaustive_request or disclosure_mode == DisclosureMode.REPORT:
            default_max_beats = 6 if not voice_mode else 4
        elif disclosure_mode == DisclosureMode.DEEP_DIALOGUE:
            default_max_beats = 3 if not voice_mode else 2
        else:
            default_max_beats = 2 if not voice_mode else 1

        # Chỉ giới hạn số semantic beat được reveal. Không giới hạn word/time.
        # Model có thể đề xuất ít beat hơn; report có thể reveal nhiều beat hơn.
        reveal_beats = min(proposed.max_beats, default_max_beats)
        if explicit_exhaustive_request or disclosure_mode == DisclosureMode.REPORT:
            reveal_beats = max(reveal_beats, min(len(plan.beats) or 1, default_max_beats))

        visible = list(plan.beats[:reveal_beats])
        held = list(plan.beats[reveal_beats:])

        continuation = plan.continuation
        held_threads = [beat.proposition for beat in held if beat.proposition]
        deferred = self._dedupe((*continuation.deferred_threads, *held_threads), 12)
        if held and not continuation.next_if_continue:
            continuation = replace(continuation, next_if_continue=held[0].proposition[:420])
        continuation = replace(continuation, deferred_threads=deferred)

        notes = self._dedupe(
            (
                *plan.style_notes,
                f"PUBLIC DISCLOSURE: reveal about {reveal_beats} semantic beat(s) this turn.",
                "WORD/TIME GUIDANCE IS NON-BINDING: ưu tiên câu tự nhiên và nói trọn ý; không tự cắt câu để chạy theo số từ/giây.",
                "Dừng ở breakpoint tự nhiên sau các beat đã reveal; phần deferred để dành cho lượt sau.",
            ),
            12,
        )
        return replace(
            plan,
            beats=tuple(visible),
            style_notes=notes,
            speech_budget=replace(proposed, max_beats=reveal_beats),
            continuation=continuation,
        )

    def ensure_speakable(self, plan: DiscoursePlan, *, objective: str) -> DiscoursePlan:
        if plan.beats:
            return plan
        fallback = DialogueBeat(
            proposition=(objective or "Trả lời trực tiếp yêu cầu hiện tại.")[:800],
            communicative_goal="đặt trọng tâm public response",
            relation_to_previous="continue",
            detail_level="normal",
        )
        return replace(
            plan,
            beats=(fallback,),
            style_notes=self._dedupe((*self.DEFAULT_STYLE_NOTES, *plan.style_notes), 10),
        )

    @staticmethod
    def _dedupe(values: Iterable[str], limit: int) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value or "").strip().split())
            key = _fingerprint(text)
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(text[:500])
            if len(out) >= limit:
                break
        return tuple(out)


__all__ = ["ConversationDirector"]
