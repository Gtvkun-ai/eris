# -*- coding: utf-8 -*-
"""Regression tests cho các lỗi thấy trong log 2026-07-19.

Các test cố ý không gọi mạng. Chúng bảo vệ semantic observer, discovery scheduler,
cooperative preemption và key-pool breaker khỏi quay lại lối vá bằng từ khóa.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from cortex.tutor.config import TutorConfig
from cortex.tutor.contracts import TutorQuestion
from llm.key_pool import ApiKeyPool
from llm.tutor_backend import GeminiWebBackend, TutorCancelled
from runtime.ai_orchestrated.discovery import DiscoveryPlan, DiscoveryRuntime
from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter
from runtime.intention_authority import IntentionObserver


def test_intention_observer_does_not_turn_banter_into_execution_debt() -> None:
    observer = IntentionObserver()
    harmless = (
        "Thì khỏi làm màu. Nói lười nói chuyện ý tứ là đủ ý rồi.",
        "Tôi không cần bày đặt văn vẻ làm gì, nói thẳng là được.",
        "Bạn chỉ cần mở miệng một câu, là tui đã thấy ngày mình đỡ nhạt đi.",
        "Nếu bạn cũng muốn, thì mình thử xem hợp không.",
        "Tôi sẽ nói ngắn hơn.",
    )
    for text in harmless:
        result = observer.validate(text, {})
        assert result.missing_contract == (), (text, result.to_payload())


def test_intention_observer_still_catches_real_external_claims() -> None:
    observer = IntentionObserver()
    for text in (
        "Tôi sẽ mở file config rồi sửa key cho bạn.",
        "Để tôi kiểm tra repo này.",
        "Tôi đã xóa file đó.",
        "Bạn chỉ cần mở miệng, tôi sẽ sửa file này.",
        "Tôi nói thật, tôi sẽ mở file.",
        "Tôi không mở file A, tôi sẽ mở file B.",
    ):
        result = observer.validate(text, {})
        assert set(result.missing_contract) == {"target", "handler", "result"}


def test_intention_observer_scopes_subject_and_negation_per_clause() -> None:
    observer = IntentionObserver()
    harmless = (
        "Tôi không mở file đâu.",
        "Bạn mở miệng một câu, tui thấy vui.",
        "Tui sến xíu với bạn nè: bạn chỉ cần mở miệng một câu, là tui đã thấy ngày mình đỡ nhạt đi.",
    )
    for text in harmless:
        result = observer.validate(text, {})
        assert result.missing_contract == (), (text, result.to_payload())


def test_key_pool_breaker_stops_before_exhausting_every_key(monkeypatch) -> None:
    monkeypatch.delenv("ERIS_KEY_POOL_429_BURST_KEYS", raising=False)
    monkeypatch.setenv("ERIS_KEY_POOL_429_GLOBAL_COOLDOWN_S", "2")
    pool = ApiKeyPool([f"key-{i}" for i in range(9)], provider="groq")

    attempts = []
    while True:
        lease = pool.acquire()
        if lease is None:
            break
        attempts.append(lease.index)
        may_rotate = pool.mark_rate_limited(
            10,
            lease=lease,
            reason="http_429:openai/gpt-oss-20b",
        )
        if not may_rotate:
            break

    assert attempts == [0, 1, 2]
    assert pool.stats()["rate_limit_bursts"] == 1
    assert pool.stats()["available"] == 0


class _Router:
    def __init__(self) -> None:
        self.calls = 0

    def plan_discovery(self, _snapshot):
        self.calls += 1
        return DiscoveryPlan()


class _Host:
    chat_mode = False
    _chat_processing = False
    _chat_last_activity_at = 0.0
    tutor_daemon = None


class _BlockingDaemon:
    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.started = threading.Event()
        self.last_research_bundle = {}
        self.last_answer_ts = 0.0
        self._eris_discovery_meta = {}

    def search_now(self, *_args, **_kwargs):
        self.started.set()
        self.cancelled.wait(2.0)
        return None

    def cancel_pending(self, *, reason: str = "") -> bool:
        self.cancelled.set()
        return True


def test_discovery_does_not_start_immediately_after_boot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        router = _Router()
        runtime = DiscoveryRuntime(_Host(), router, state_path=Path(tmp) / "state.json")
        runtime.maybe_tick({}, now=time.time())
        assert router.calls == 0


def test_discovery_is_preempted_by_chat_and_not_archived() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        host = _Host()
        daemon = _BlockingDaemon()
        host.tutor_daemon = daemon
        runtime = DiscoveryRuntime(host, _Router(), state_path=Path(tmp) / "state.json")
        plan = DiscoveryPlan(
            lane="fresh_curiosity",
            topic="test topic",
            needs_external=True,
            freshness_required=True,
            verification_required=True,
            eris_interest=0.8,
            user_relevance=0.7,
            novelty=0.8,
            importance=0.8,
            confidence=0.9,
            reason="test",
        )
        runtime._start_search(plan, now=time.time())
        assert daemon.started.wait(1.0)
        assert runtime.preempt_for_chat(reason="test_chat") is True
        runtime._job_thread.join(2.0)

        state = runtime.snapshot()
        assert state.current_activity.status == "cancelled"
        assert state.records == ()


class _CancelableSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def goto(self, _url: str) -> None:
        return None

    def is_blocked(self) -> bool:
        return False

    def submit_question(self, _text: str, *, delay_min_ms: int, delay_max_ms: int, cancel_event=None) -> None:
        return None

    def read_answer(self, *, stable_window_s: float, deadline: float, cancel_event=None) -> str:
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise TutorCancelled()
            time.sleep(0.01)
        return "late answer"

    def citations(self):
        return ()


def test_tutor_backend_supports_cooperative_cancel() -> None:
    backend = GeminiWebBackend(
        TutorConfig(enabled=True, episode_timeout_s=2.0),
        page_session_factory=lambda: _CancelableSession(),
    )
    question = TutorQuestion(text="test question", gap_id="gap")
    result = {}

    thread = threading.Thread(target=lambda: result.setdefault("answer", backend.ask(question)))
    thread.start()
    time.sleep(0.05)
    backend.cancel_current("chat")
    thread.join(1.0)

    assert result["answer"].fail_reason == "cancelled"


def test_current_turn_anchor_distinguishes_style_and_reciprocity() -> None:
    assert AIRuntimeModelRouter._current_user_move_hint("em sến xíu đi cho tui zui") == "style_request"
    assert AIRuntimeModelRouter._current_user_move_hint("bạn muốn tui quen bạn hả") == "request_reciprocity"


def test_chat_start_supersedes_tts_before_asr_text_arrives() -> None:
    from runtime.chat_cycle import ChatCycleMixin

    class _Logger:
        def debug(self, *_args, **_kwargs):
            return None

    class _ChatHost(ChatCycleMixin):
        def __init__(self) -> None:
            self.chat_mode = True
            self.logger = _Logger()
            self.ai_discovery_runtime = None
            self.reasons: list[str] = []

        def _supersede_tts_for_new_user_turn(self, reason: str) -> bool:
            self.reasons.append(reason)
            return True

    host = _ChatHost()
    host._enter_chat_cycle()
    assert host.reasons == ["user_speech_started"]


def test_conversation_profile_uses_independent_tts_turn_manager() -> None:
    from runtime.stage_profiles import stage_profile

    profile = stage_profile("conversation")
    assert profile.task_manager_enabled is True
    assert profile.prefetch_workers == 1


def test_japanese_localizer_fails_closed_in_strict_mode(monkeypatch) -> None:
    from runtime.speech_localizer import SpeechLocalizationError, SpeechLocalizer

    localizer = SpeechLocalizer()
    monkeypatch.setattr(
        localizer,
        "_translate_to_japanese",
        lambda *_args, **_kwargs: "Tôi vẫn là tiếng Việt",
    )
    try:
        localizer.localize(
            "Không có gì để nói thì cứ thả một câu lửng.",
            language_hint="ja",
            strict=True,
        )
    except SpeechLocalizationError as exc:
        assert "japanese_localization" in str(exc)
    else:
        raise AssertionError("strict Japanese contract accepted Vietnamese transcript")


def test_tts_worker_relocalizes_even_when_upstream_claims_prelocalized(monkeypatch) -> None:
    import runtime.tts_engine as tts_engine

    class _Localizer:
        def __init__(self) -> None:
            self.strict = False

        def localize(self, _text: str, **kwargs) -> str:
            self.strict = bool(kwargs.get("strict"))
            return "話すことがなくても、無理に話さなくていいよ。"

    worker = tts_engine._TtsWorker.__new__(tts_engine._TtsWorker)
    worker._language_hint = "ja"
    worker._localizer = _Localizer()
    request = tts_engine._SpeakRequest(
        "Không có gì để nói thì khỏi ép.",
        prelocalized=True,
        language_hint="ja",
    )
    monkeypatch.setattr(tts_engine, "_prelocalize_japanese_enabled", lambda: True)

    text, localized = worker._resolve_main_transcript(request, request.text)
    assert worker._localizer.strict is True
    assert localized is True
    assert "話" in text


def test_tts_attempts_default_is_bounded(monkeypatch) -> None:
    import runtime.tts_engine as tts_engine

    monkeypatch.delenv("ERIS_TTS_MAX_ATTEMPTS", raising=False)
    assert tts_engine._tts_max_attempts() == 2


def test_tts_manager_new_turn_does_not_wait_for_cancelled_http_request() -> None:
    from types import SimpleNamespace

    from runtime.tts_task_manager import TtsTaskManager

    class _Backend:
        def __init__(self) -> None:
            self.first_started = threading.Event()
            self.release_first = threading.Event()
            self.second_played = threading.Event()
            self.calls = 0

        def synthesize(self, text: str, **_kwargs) -> bytes:
            self.calls += 1
            if text == "old turn":
                self.first_started.set()
                self.release_first.wait(1.0)
                return b"old"
            return b"new"

        def play_audio(self, wav_bytes: bytes, _stop_event, on_started=None) -> None:
            if on_started is not None:
                on_started()
            if wav_bytes == b"new":
                self.second_played.set()

    def frame(turn_id: str, text: str):
        return SimpleNamespace(
            turn_id=turn_id,
            segment_id=0,
            tts_text=text,
            interruptible=True,
            prosody_style="",
            prosody_notes="",
            speech_contract={"language": "ja", "locale": "ja-JP", "prelocalized": True},
            delivery={},
            audio_asset="",
            emotion="neutral",
            motion="none",
        )

    backend = _Backend()
    manager = TtsTaskManager(prefetch_workers=1, max_prefetch_segments=1)
    assert manager.dispatch_frames(
        [frame("old", "old turn")],
        backend=backend,
        valence=0.0,
        arousal=0.2,
        stance="",
    )
    assert backend.first_started.wait(0.5)

    assert manager.dispatch_frames(
        [frame("new", "new turn")],
        backend=backend,
        valence=0.0,
        arousal=0.2,
        stance="",
    )
    assert backend.second_played.wait(0.5)
    backend.release_first.set()
    manager.shutdown()


def test_tts_key_lane_reservation_prevents_concurrent_reuse() -> None:
    from runtime.tts_key_health import TtsKeyLaneHealth

    health = TtsKeyLaneHealth()
    assert health.try_reserve(2) is True
    assert health.try_reserve(2) is False
    assert 2 in health.excluded_indices()
    assert health.snapshot()["2"]["in_flight"] == 1

    health.release(2)
    assert 2 not in health.excluded_indices()
    assert health.try_reserve(2) is True
    health.release(2)


def test_speech_persona_polish_is_subtle_and_style_aware(monkeypatch) -> None:
    from runtime.speech_persona_polish import resolve_speech_persona_policy

    monkeypatch.setenv("ERIS_TTS_SPEECH_PERSONA_POLISH", "1")
    monkeypatch.setenv("ERIS_TTS_SPEECH_PERSONA_WARMTH", "0.18")
    monkeypatch.setenv("ERIS_TTS_SPEECH_PERSONA_CUTENESS", "0.10")

    neutral = resolve_speech_persona_policy("Không có gì để nói thì cứ im cũng được.")
    technical = resolve_speech_persona_policy(
        "Mở Settings rồi đổi Language sang ja.", prosody_style="focused"
    )
    soft = resolve_speech_persona_policy(
        "Cứ thả một câu lửng, tôi bắt nhịp tiếp.", prosody_style="soft_tease"
    )

    assert neutral.enabled is True
    assert neutral.profile == "infj_5w4_subtle"
    assert neutral.warmth == 0.18
    assert neutral.cuteness == 0.10
    assert technical.cuteness == 0.0
    assert technical.warmth <= 0.06
    assert soft.warmth > neutral.warmth
    assert soft.cuteness > neutral.cuteness


def test_speech_persona_gate_blocks_unearned_intimacy_and_anime_baby_talk() -> None:
    from runtime.speech_persona_polish import (
        resolve_speech_persona_policy,
        translation_respects_persona_boundaries,
    )

    source = "Không có gì để nói thì cứ im một chút cũng được."
    policy = resolve_speech_persona_policy(source)

    assert translation_respects_persona_boundaries(
        source,
        "話すことがなくても、少し黙っていてもいいよ。",
        policy,
    )
    assert not translation_respects_persona_boundaries(
        source,
        "ずっとそばにいるよ。あなたのことが大好きだよ。",
        policy,
    )
    assert not translation_respects_persona_boundaries(
        source,
        "えへへ、ご主人様。黙っていてもいいんだよぉ。",
        policy,
    )


def test_speech_persona_gate_allows_relationship_words_when_source_contains_them() -> None:
    from runtime.speech_persona_polish import (
        resolve_speech_persona_policy,
        translation_respects_persona_boundaries,
    )

    source = "Tôi thích bạn, nhưng đừng vội làm quá lên."
    policy = resolve_speech_persona_policy(source)
    assert policy.allows_relationship_escalation is True
    assert translation_respects_persona_boundaries(
        source,
        "あなたのことは好き。でも、まだ大げさにしないで。",
        policy,
    )


def test_localizer_cache_key_changes_with_persona_policy(monkeypatch) -> None:
    import runtime.speech_persona_polish as persona_polish
    from runtime.speech_localizer import SpeechLocalizer

    localizer = SpeechLocalizer()
    calls: list[str] = []
    warmth = {"value": 0.18}

    def fake_translate(text: str, **kwargs) -> str:
        calls.append(kwargs["persona_policy"].cache_key)
        return "話すことがなくても、無理に話さなくていいよ。"

    def fake_runtime_float(name: str, default: float) -> float:
        if name == "speech_persona_warmth":
            return warmth["value"]
        return default

    monkeypatch.setattr(localizer, "_translate_to_japanese", fake_translate)
    monkeypatch.setattr(persona_polish, "_runtime_float", fake_runtime_float)
    first = localizer.localize("Không có gì để nói thì khỏi ép.", language_hint="ja", strict=True)
    warmth["value"] = 0.28
    second = localizer.localize("Không có gì để nói thì khỏi ép.", language_hint="ja", strict=True)

    assert first == second
    assert len(calls) == 2
    assert calls[0] != calls[1]


def test_signature_ending_desu_ne_is_deterministic_and_context_aware(monkeypatch) -> None:
    import runtime.speech_persona_polish as persona_polish

    monkeypatch.setattr(
        persona_polish,
        "_runtime_bool",
        lambda name, default: True if name == "signature_ending_enabled" else default,
    )
    monkeypatch.setattr(
        persona_polish,
        "_runtime_text",
        lambda name, default: "desu_ne" if name == "signature_ending" else default,
    )
    monkeypatch.setattr(
        persona_polish,
        "_runtime_float",
        lambda name, default: 1.0 if name == "signature_ending_rate" else default,
    )

    source = "Không có gì để nói thì cứ im một chút cũng được."
    first = persona_polish.resolve_speech_persona_policy(source)
    second = persona_polish.resolve_speech_persona_policy(source)
    question = persona_polish.resolve_speech_persona_policy("Bạn đang nghĩ gì vậy?")
    technical = persona_polish.resolve_speech_persona_policy(
        "Mở Settings rồi đổi Language sang ja.",
        prosody_style="focused",
    )

    assert first.signature_ending == "desu_ne"
    assert first.signature_ending_selected is True
    assert first.signature_ending_rate == 1.0
    assert second.cache_key == first.cache_key
    assert "ですね" in first.prompt_directive()
    assert question.signature_ending_selected is False
    assert technical.signature_ending_selected is False


def test_signature_ending_can_be_disabled_without_disabling_persona(monkeypatch) -> None:
    import runtime.speech_persona_polish as persona_polish

    monkeypatch.setattr(
        persona_polish,
        "_runtime_bool",
        lambda name, default: False if name == "signature_ending_enabled" else default,
    )

    policy = persona_polish.resolve_speech_persona_policy("Tôi cũng nghĩ vậy.")
    assert policy.enabled is True
    assert policy.signature_ending == "off"
    assert policy.signature_ending_selected is False
    assert "Do not deliberately add ですね" in policy.prompt_directive()


def test_tts_prompt_emphasizes_only_actual_desu_ne_signature(monkeypatch) -> None:
    import runtime.tts_engine as tts_engine

    monkeypatch.setattr(tts_engine, "_pace_directive", lambda: "")
    with_signature = tts_engine._build_tts_prompt(
        "まあ、そうですね。",
        "",
        "ja",
        prelocalized=True,
    )
    without_signature = tts_engine._build_tts_prompt(
        "まあ、そう思います。",
        "",
        "ja",
        prelocalized=True,
    )

    assert "Signature ending performance" in with_signature
    assert "140–220ms" in with_signature
    assert "Signature ending performance" not in without_signature


def test_hardening_fingerprint_covers_signature_ending_runtime() -> None:
    from runtime.hardening_release import DEFAULT_AUTHORITY_FILES

    assert "runtime/speech_persona_polish.py" in DEFAULT_AUTHORITY_FILES
    assert "runtime/speech_localizer.py" in DEFAULT_AUTHORITY_FILES
    assert "runtime/tts_engine.py" in DEFAULT_AUTHORITY_FILES
    assert "runtime/runtime_settings_store.py" in DEFAULT_AUTHORITY_FILES
