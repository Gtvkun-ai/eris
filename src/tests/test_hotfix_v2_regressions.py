from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from runtime.ai_orchestrated.discourse_state import DiscourseState
from runtime.ai_orchestrated.followup_appraisal import FollowUpAppraisalLayer, FollowUpPolicy
from runtime.ai_orchestrated.surface_intent import _surface_text_is_duplicate
from cortex.vision_semantic_compressor import RemoteCaptionClient
import runtime.inference_broker as inference_broker


def _waiting_discourse() -> DiscourseState:
    return DiscourseState(
        mode="ambient",
        last_role="assistant",
        reply_expected=True,
        assistant_may_continue=False,
        thread_key="old-thread",
        seconds_since_assistant=0.0,
        confidence=0.9,
    )


def test_first_user_turn_in_new_session_closes_old_followup_cycle():
    layer = FollowUpAppraisalLayer(FollowUpPolicy(
        remind_after_seconds=30.0,
        abandon_after_reminder_seconds=48.0,
        abandon_without_reminder_seconds=105.0,
        reserved_distance=0.2,
    ))
    discourse = _waiting_discourse()

    # ERIS asked before any user turn has been seen in this process.
    first = layer.evaluate(discourse, now=100.0, user_turn_at=0.0, assistant_turn_at=100.0)
    assert first.reply_expected is True
    layer.note_spoken(
        SimpleNamespace(
            semantics=SimpleNamespace(speech_act="followup_reminder"),
            motive="followup_reminder",
        ),
        now=131.0,
    )

    # The very first user turn must reset the old cycle even though the previous
    # marker was zero. A stale observer baton must not restart that old timer.
    after_user = layer.evaluate(discourse, now=140.0, user_turn_at=140.0, assistant_turn_at=100.0)
    assert after_user.followup_reminder_due is False
    assert after_user.followup_reminder_count == 0
    assert layer._question_started_at == 0.0
    assert layer._reminder_spoken_at == 0.0


def test_new_assistant_question_after_user_can_start_new_cycle():
    layer = FollowUpAppraisalLayer()
    discourse = _waiting_discourse()
    layer.evaluate(discourse, now=100.0, user_turn_at=0.0, assistant_turn_at=100.0)
    layer.evaluate(discourse, now=140.0, user_turn_at=140.0, assistant_turn_at=100.0)

    newer = layer.evaluate(discourse, now=151.0, user_turn_at=140.0, assistant_turn_at=150.0)
    assert newer.reply_expected is True
    assert layer._question_started_at == 150.0


def test_surface_duplicate_guard_catches_same_line_with_extra_greeting():
    previous = "Có một điều nhỏ từ trước vẫn đang chờ, bạn có muốn xem lại nó không?"
    current = "Chào mừng trở lại. Có một điều nhỏ từ trước vẫn đang chờ, bạn có muốn xem lại nó không?"
    assert _surface_text_is_duplicate(current, previous) is True


class _VisionClient:
    model_name = "test-vision"

    def __init__(self) -> None:
        self.calls = 0

    def create_chat_completion(self, **_kwargs):
        self.calls += 1
        return {"choices": [{"message": {"content": "should not be reached"}}]}


def test_optional_broker_rejection_is_not_retried(monkeypatch):
    entries = 0

    @contextmanager
    def rejected_context(*_args, **_kwargs):
        nonlocal entries
        entries += 1
        raise inference_broker.InferenceRejected("shed_optional_user_active")
        yield  # pragma: no cover

    monkeypatch.setattr(inference_broker, "inference_context", rejected_context)
    client = _VisionClient()
    captioner = RemoteCaptionClient(client)

    assert captioner.caption_image("ZmFrZS1wbmc=") == ""
    assert entries == 1
    assert client.calls == 0
