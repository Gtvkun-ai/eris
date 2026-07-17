from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from runtime.scripted_take import (
    ScriptedTakeBeat,
    ScriptedTakeDefinition,
    ScriptedTakeLoader,
    ScriptedTakeRuntime,
)
from runtime.stage_profiles import stage_profile


class FakeTransport:
    def __init__(self):
        self.payloads = []

    def send_json(self, payload):
        self.payloads.append(payload)


class FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event.to_payload())
        return True


class FakeOwner:
    def __init__(self):
        self.transport = FakeTransport()
        self.stage_event_bus = FakeBus()
        self.logger = SimpleNamespace(warning=lambda *a, **k: None)
        self.answers = []

    def _get_runtime_provider(self, name):
        return None

    def request_tutor_answer(self, topic, **kwargs):
        self.answers.append((topic, kwargs))
        return "Ánh sáng sinh học có thể hỗ trợ phát tán bào tử hoặc thu hút sinh vật."


def test_recording_profile_is_a_coherent_bundle():
    profile = stage_profile("recording")
    assert profile.logical_segment_tts is True
    assert profile.dispatch_mode == "queued"
    assert profile.task_manager_enabled is True
    assert profile.max_tts_segments == 8


def test_loader_accepts_tutor_lookup_shorthand(tmp_path: Path):
    path = tmp_path / "take.json"
    path.write_text(json.dumps({
        "title": "Demo",
        "beats": [
            {"text": "Khoan."},
            {"tutor_lookup": "vì sao nấm phát sáng", "show_panel": True},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    take = ScriptedTakeLoader().load(path)
    assert take.beats[0].kind == "text"
    assert take.beats[1].kind == "tutor_lookup"
    assert take.beats[1].query == "vì sao nấm phát sáng"


def test_scripted_take_runs_text_tutor_then_template_answer():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    take = ScriptedTakeDefinition(
        title="Demo",
        beats=(
            ScriptedTakeBeat(kind="text", text="Tôi có một câu hỏi."),
            ScriptedTakeBeat(kind="tutor_lookup", query="vì sao nấm phát sáng"),
            ScriptedTakeBeat(kind="text", text="À. {{tutor_answer}}"),
        ),
    )

    status = runtime.run_definition(take)

    assert status.state == "completed"
    assert owner.answers and owner.answers[0][0] == "vì sao nấm phát sáng"
    take_texts = [p.get("text", "") for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]
    assert take_texts[0] == "Tôi có một câu hỏi."
    assert "Ánh sáng sinh học" in take_texts[-1]
    tutor_stages = [
        p.get("tutor", {}).get("stage")
        for p in owner.transport.payloads
        if p.get("parse_mode") == "tutor_event"
    ]
    assert tutor_stages == ["open", "asking", "answered", "close"]
    event_types = [item["type"] for item in owner.stage_event_bus.events]
    assert "scripted_take_started" in event_types
    assert "tutor_prop" in event_types
    assert "scripted_take_finished" in event_types


def test_cancel_closes_tutor_prop_owned_by_current_take():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    runtime._active_take_id = "take-old"
    runtime._emit_tutor_prop(
        "open",
        take_id="take-old",
        beat_index=2,
        query="một câu hỏi đang dở",
    )

    runtime.cancel("replaced")

    stages = [
        p.get("tutor", {}).get("stage")
        for p in owner.transport.payloads
        if p.get("parse_mode") == "tutor_event"
    ]
    assert stages == ["open", "close"]


def test_stale_take_thread_cannot_overwrite_new_take_status():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    runtime._active_take_id = "take-new"
    runtime._status = runtime._status.__class__("running", take_id="take-new", title="New")

    runtime._set_status(expected_take_id="take-old", state="completed")

    assert runtime.status().take_id == "take-new"
    assert runtime.status().state == "running"
