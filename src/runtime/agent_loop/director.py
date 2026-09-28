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
        """Cắt public disclosure theo *nhịp người nghe*, không theo token budget.

        Voice mode chủ động ngắn hơn text vì 1000+ chữ TTS tạo cảm giác lecture và
        làm người nghe khó chen vào. User vẫn có thể yêu cầu report/exhaustive;
        khi đó budget tăng, nhưng director vẫn giữ hard cap rõ ràng.
        """
        proposed = plan.speech_budget.normalized()
        disclosure_mode = plan.disclosure_mode

        if explicit_exhaustive_request or disclosure_mode == DisclosureMode.REPORT:
            default_budget = TurnSpeechBudget(
                target_words=700 if not voice_mode else 260,
                hard_max_words=1200 if not voice_mode else 420,
                max_beats=6 if not voice_mode else 4,
                target_seconds=150.0 if not voice_mode else 65.0,
                hard_max_seconds=210.0 if not voice_mode else 90.0,
            )
        elif disclosure_mode == DisclosureMode.DEEP_DIALOGUE:
            default_budget = TurnSpeechBudget(
                target_words=260 if not voice_mode else 110,
                hard_max_words=420 if not voice_mode else 180,
                max_beats=3 if not voice_mode else 2,
                target_seconds=65.0 if not voice_mode else 28.0,
                hard_max_seconds=90.0 if not voice_mode else 40.0,
            )
        else:
            default_budget = TurnSpeechBudget(
                target_words=150 if not voice_mode else 70,
                hard_max_words=240 if not voice_mode else 120,
                max_beats=2 if not voice_mode else 1,
                target_seconds=36.0 if not voice_mode else 20.0,
                hard_max_seconds=52.0 if not voice_mode else 30.0,
            )

        # Model được phép đề xuất ngắn hơn mặc định. Nó không được phép tự nâng
        # hard cap vô hạn, đặc biệt trong voice mode.
        target_seconds = min(proposed.target_seconds, default_budget.target_seconds)
        hard_seconds = min(proposed.hard_max_seconds, default_budget.hard_max_seconds)
        # Trong voice mode, word cap phải đi theo *thời gian nghe* và tốc độ TTS.
        # Model không được nâng cap bằng cách trả target_words lớn.
        time_word_target = words_for_seconds(target_seconds, speed=tts_speed)
        time_word_hard = words_for_seconds(hard_seconds, speed=tts_speed)
        budget = TurnSpeechBudget(
            target_words=min(proposed.target_words, default_budget.target_words, time_word_target) if voice_mode else min(proposed.target_words, default_budget.target_words),
            hard_max_words=min(proposed.hard_max_words, default_budget.hard_max_words, time_word_hard) if voice_mode else min(proposed.hard_max_words, default_budget.hard_max_words),
            max_beats=min(proposed.max_beats, default_budget.max_beats),
            target_seconds=target_seconds,
            hard_max_seconds=hard_seconds,
        ).normalized()

        visible: list[DialogueBeat] = []
        held: list[DialogueBeat] = []
        estimated_seconds = 0.0
        for beat in plan.beats:
            beat_seconds = estimate_beat(beat, speed=tts_speed).seconds if voice_mode else 0.0
            would_exceed_time = bool(
                voice_mode
                and visible
                and estimated_seconds + beat_seconds > budget.target_seconds
            )
            if len(visible) < budget.max_beats and not would_exceed_time:
                visible.append(beat)
                estimated_seconds += beat_seconds
            else:
                held.append(beat)

        continuation = plan.continuation
        held_threads = [beat.proposition for beat in held if beat.proposition]
        deferred = self._dedupe((*continuation.deferred_threads, *held_threads), 12)
        if held and not continuation.next_if_continue:
            continuation = replace(continuation, next_if_continue=held[0].proposition[:420])
        continuation = replace(continuation, deferred_threads=deferred)

        notes = self._dedupe(
            (
                *plan.style_notes,
                f"PUBLIC WORD BUDGET: aim about {budget.target_words} words; hard stop at {budget.hard_max_words} words.",
                f"PUBLIC BEAT BUDGET: at most {budget.max_beats} dialogue beat(s) this turn.",
                f"PUBLIC SPEECH TIME: target about {budget.target_seconds:.0f}s; hard stop about {budget.hard_max_seconds:.0f}s at TTS speed {float(tts_speed):.2f}x.",
                "Khi đủ budget, dừng ở breakpoint tự nhiên; không cố hoàn thành toàn bộ analysis map.",
            ),
            12,
        )
        return replace(
            plan,
            beats=tuple(visible),
            style_notes=notes,
            speech_budget=budget,
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
