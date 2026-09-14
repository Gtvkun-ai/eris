# -*- coding: utf-8 -*-
"""Regression cho Basic Settings và credential não chính.

Giữ ba contract người dùng nhìn thấy được:
- main cognition có pool riêng, không mượn key Groq/Gemini phụ;
- health snapshot nêu rõ model/provider/fingerprint mà không lộ raw key;
- connection test dùng đúng client main và trả ACK kỹ thuật, không chen vào chat.
"""

from __future__ import annotations

import logging
import os
import time
from types import SimpleNamespace


def test_remote_main_pool_is_distinct_from_groq_and_gemini(monkeypatch) -> None:
    import eris_secrets
    from llm import key_pool

    monkeypatch.setenv("ERIS_REMOTE_PROVIDER", "deepseek")
    monkeypatch.setenv("ERIS_REMOTE_FALLBACK_API_KEYS", "remote-fallback-1,remote-fallback-2")
    monkeypatch.setattr(
        eris_secrets,
        "get_provider_profile",
        lambda provider, slot="default": {"api_key": "remote-primary"} if slot == "remote_main" else {},
    )
    monkeypatch.setattr(
        eris_secrets,
        "get_secret",
        lambda *names, default="": "legacy-remote" if "ERIS_REMOTE_API_KEY" in names else default,
    )
    monkeypatch.setattr(
        eris_secrets,
        "_load_secrets",
        lambda: {"api_keys": {"ERIS_REMOTE_FALLBACK_API_KEYS": ["remote-file-fallback"]}},
    )

    assert key_pool._normalize_kind("remote_main") == "remote"
    assert key_pool._normalize_kind("deepseek") == "remote"
    assert key_pool._normalize_kind("groq") == "groq"
    assert key_pool._normalize_kind("gemini") == "gemini"
    assert key_pool._collect_remote_keys() == [
        "remote-primary",
        "legacy-remote",
        "remote-file-fallback",
        "remote-fallback-1",
        "remote-fallback-2",
    ]
    # Remote key không được rơi ngược vào pool Gemini phụ.
    assert key_pool._collect_gemini_keys() == []


def test_process_manager_attaches_remote_pool_to_main_openai_client(monkeypatch) -> None:
    import llm.process_manager as process_manager

    class _Pool:
        def acquire(self, allow_cooling=False):
            return SimpleNamespace(key="main-pool-key")

    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("ERIS_REMOTE_PROVIDER", "deepseek")
    monkeypatch.setenv("ERIS_REMOTE_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("ERIS_REMOTE_MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(process_manager, "apply_secrets_to_environ", lambda: None)
    monkeypatch.setattr(process_manager, "get_provider_profile", lambda *a, **k: {})
    monkeypatch.setattr(process_manager, "get_secret", lambda *a, **k: "")
    monkeypatch.setattr(process_manager, "get_key_pool", lambda kind: _Pool() if kind == "remote_main" else None)
    monkeypatch.setattr(process_manager, "OpenAICompatibleClient", _Client)

    manager = process_manager.RemoteModelProcessManager(logger=logging.getLogger("test"), project_root=".")
    manager._build_remote_client()

    assert captured["model_name"] == "deepseek-v4-flash"
    assert captured["api_key"] == "main-pool-key"
    assert isinstance(captured["key_pool"], _Pool)


def test_main_brain_health_and_connection_ack_hide_raw_key(monkeypatch) -> None:
    from runtime.coordinator import RuntimeCoordinator

    class _Pool:
        def snapshot(self):
            return {
                "size": 2,
                "available": 2,
                "keys": [
                    {"fingerprint": "abc123def456", "active": True, "status": "ready"},
                    {"fingerprint": "fed654cba321", "active": False, "status": "ready"},
                ],
            }

    class _Client:
        base_url = "https://api.deepseek.com"
        model_name = "deepseek-v4-flash"
        api_key = "SECRET-MUST-NOT-LEAK"
        key_pool = _Pool()

        def create_chat_completion(self, **kwargs):
            return {"choices": [{"message": {"content": "OK"}}]}

    class _Transport:
        def __init__(self):
            self.messages = []

        def send_json(self, payload):
            self.messages.append(payload)

    owner = object.__new__(RuntimeCoordinator)
    owner.logger = logging.getLogger("test")
    owner.transport = _Transport()
    owner.llm_service = SimpleNamespace(
        client=_Client(),
        fallback_client=SimpleNamespace(model_name="gpt-5.5"),
        _extract_content=lambda response: "OK",
    )
    monkeypatch.setenv("ERIS_REMOTE_PROVIDER", "deepseek")

    snapshot = owner._main_brain_health_snapshot()
    assert snapshot["model"] == "deepseek-v4-flash"
    assert snapshot["active_key_fingerprint"] == "abc123def456"
    assert "SECRET-MUST-NOT-LEAK" not in repr(snapshot)

    owner._run_settings_connection_test("test-1")
    ack = owner.transport.messages[-1]["settings_connection_test_ack"]
    assert ack["ok"] is True
    assert ack["latency_ms"] >= 0
    assert ack["main_brain"]["model"] == "deepseek-v4-flash"
    assert "SECRET-MUST-NOT-LEAK" not in repr(ack)


def test_tts_text_sync_timeout_defaults_to_audio_start_window(monkeypatch) -> None:
    from runtime.tts_sync_policy import text_sync_timeout_seconds

    monkeypatch.delenv("ERIS_TTS_TEXT_SYNC_TIMEOUT", raising=False)
    assert text_sync_timeout_seconds() == 30.0

    monkeypatch.setenv("ERIS_TTS_TEXT_SYNC_TIMEOUT", "99")
    assert text_sync_timeout_seconds() == 99.0

    monkeypatch.setenv("ERIS_TTS_TEXT_SYNC_TIMEOUT", "bad")
    assert text_sync_timeout_seconds() == 30.0


def test_send_decision_to_body_releases_text_when_tts_never_starts(monkeypatch) -> None:
    from runtime.coordinator import RuntimeCoordinator

    monkeypatch.setenv("ERIS_TTS_SYNC_TEXT", "1")
    monkeypatch.setenv("ERIS_TTS_TEXT_SYNC_TIMEOUT", "0.2")
    monkeypatch.setattr(
        "runtime.runtime_settings_store.runtime_text",
        lambda section, key, default=None: "ja" if (section, key) == ("tts", "language") else default,
    )

    class _Transport:
        def __init__(self):
            self.messages = []

        def send_json(self, payload):
            self.messages.append(payload)

    class _StageFrame:
        language_hint = "ja"

        def __init__(self):
            self.display_text = "bubble text"
            self.memory_text = "bubble text"
            self.tts_text = "bubble text"
            self.emotion = "neutral"
            self.motion = "stand"
            self.actions = ()
            self.prosody_style = "neutral"
            self.prosody_notes = ""
            self.delivery = {}
            self.stage_act = {}
            self.show_plan = {}
            self.speech_contract = {}
            self.body_timeline = {}
            self.interruptible = True
            self.body_only = False
            self.source = "test"
            self.speech_act = ""
            self.preset_id = ""
            self.audio_asset = ""
            self.turn_id = ""
            self.segment_id = 0

        def to_payload_patch(self):
            return {"display_text": self.display_text, "stage": {"segment_count": 1, "protocol": "eris.stage", "protocol_version": 1}}

    class _StageBuilder:
        language_hint = "ja"

        def build(self, *_args, **_kwargs):
            return _StageFrame()

    class _Dispatcher:
        def __init__(self):
            self.calls = 0

        def dispatch_tts(self, *_args, **_kwargs):
            self.calls += 1
            return True

    class _Decision:
        text = "ignored"
        should_speak = True
        parse_mode = ""
        intent = "chat"
        director_trace_id = ""

        def to_payload(self):
            return {"text": "ignored", "should_speak": True, "stage": {}}

    owner = object.__new__(RuntimeCoordinator)
    owner.logger = logging.getLogger("test")
    owner.transport = _Transport()
    owner.ai_runtime_enabled = False
    owner.ai_state_reducer = None
    owner._stage_channel_blocked = lambda _channel: False
    owner._build_body_bias_payload = lambda: {}
    owner._private_mind_digest_for_payload = lambda: {}
    owner._private_life_digest_for_payload = lambda: {}
    owner._build_emotion_debug_payload = lambda: {}
    owner._build_depth_v2_block = lambda **_kwargs: {}
    owner._record_public_turn = lambda *args, **kwargs: None
    owner._get_runtime_provider = lambda _name: SimpleNamespace(engine=SimpleNamespace(_ok=True))
    owner.subconscious_runtime_enabled = False
    owner.stage_event_bus = None
    owner.stage_frame_builder = _StageBuilder()
    owner.stage_output_pipeline = SimpleNamespace(frames_for_tts=lambda frame: (frame,))
    owner.stage_dispatcher = _Dispatcher()
    owner.current_stage_user_text = ""
    owner.last_ai_intention_plan = None
    owner.memory_state = None

    owner._send_decision_to_body(_Decision(), channel="chat")
    time.sleep(0.35)

    assert any(message.get("text") == "bubble text" for message in owner.transport.messages)


def test_send_decision_to_body_emits_stage_text_before_waiting_for_tts(monkeypatch) -> None:
    from runtime.coordinator import RuntimeCoordinator

    monkeypatch.setenv("ERIS_TTS_SYNC_TEXT", "1")
    monkeypatch.setenv("ERIS_TTS_TEXT_SYNC_TIMEOUT", "30")
    monkeypatch.setattr(
        "runtime.runtime_settings_store.runtime_text",
        lambda section, key, default=None: "ja" if (section, key) == ("tts", "language") else default,
    )

    class _Transport:
        def __init__(self):
            self.messages = []

        def send_json(self, payload):
            self.messages.append(payload)

    class _StageFrame:
        language_hint = "ja"

        def __init__(self):
            self.display_text = "bubble text"
            self.memory_text = "bubble text"
            self.tts_text = "bubble text"
            self.emotion = "neutral"
            self.motion = "stand"
            self.actions = ()
            self.prosody_style = "neutral"
            self.prosody_notes = ""
            self.delivery = {}
            self.stage_act = {}
            self.show_plan = {}
            self.speech_contract = {}
            self.body_timeline = {}
            self.interruptible = True
            self.body_only = False
            self.source = "test"
            self.speech_act = ""
            self.preset_id = ""
            self.audio_asset = ""
            self.turn_id = "turn-chat"
            self.segment_id = 0

        def to_payload_patch(self):
            return {"display_text": self.display_text, "stage": {"segment_count": 1, "protocol": "eris.stage", "protocol_version": 1}}

    class _StageBuilder:
        language_hint = "ja"

        def build(self, *_args, **_kwargs):
            return _StageFrame()

    class _StageBus:
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event.to_payload())
            return True

    class _Dispatcher:
        def dispatch_tts(self, *_args, **_kwargs):
            return True

    class _Decision:
        text = "ignored"
        should_speak = True
        parse_mode = ""
        intent = "chat"
        director_trace_id = ""

        def to_payload(self):
            return {"text": "ignored", "should_speak": True, "stage": {}}

    owner = object.__new__(RuntimeCoordinator)
    owner.logger = logging.getLogger("test")
    owner.transport = _Transport()
    owner.ai_runtime_enabled = False
    owner.ai_state_reducer = None
    owner._stage_channel_blocked = lambda _channel: False
    owner._build_body_bias_payload = lambda: {}
    owner._private_mind_digest_for_payload = lambda: {}
    owner._private_life_digest_for_payload = lambda: {}
    owner._build_emotion_debug_payload = lambda: {}
    owner._build_depth_v2_block = lambda **_kwargs: {}
    owner._record_public_turn = lambda *args, **kwargs: None
    owner._get_runtime_provider = lambda _name: SimpleNamespace(engine=SimpleNamespace(_ok=True))
    owner.subconscious_runtime_enabled = False
    owner.stage_event_bus = _StageBus()
    owner.stage_frame_builder = _StageBuilder()
    owner.stage_output_pipeline = SimpleNamespace(frames_for_tts=lambda frame: (frame,))
    owner.stage_dispatcher = _Dispatcher()
    owner.current_stage_user_text = ""
    owner.last_ai_intention_plan = None
    owner.memory_state = None

    owner._send_decision_to_body(_Decision(), channel="chat")

    assert any(
        event.get("protocol") == "eris.stage"
        and event.get("type") == "stage_segment"
        and event.get("display_text") == "bubble text"
        for event in owner.stage_event_bus.events
    )
    assert not any(message.get("text") == "bubble text" for message in owner.transport.messages)
