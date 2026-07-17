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


def test_loader_parses_tutor_reaction_arc(tmp_path: Path):
    path = tmp_path / "reaction_take.json"
    path.write_text(json.dumps({
        "title": "Reaction",
        "beats": [
            {"tutor_lookup": "một câu hỏi"},
            {
                "kind": "tutor_reaction",
                "lead_in": "À...",
                "summary": "Hóa ra chuyện đó có nguyên nhân.",
                "afterthought": "Khá khéo.",
                "response_hold_ms": 410,
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")

    take = ScriptedTakeLoader().load(path)

    assert take.beats[1].kind == "tutor_reaction"
    assert take.beats[1].locked_summary == "Hóa ra chuyện đó có nguyên nhân."
    assert take.beats[1].afterthought == "Khá khéo."
    assert take.beats[1].response_hold_ms == 410


def test_tutor_reaction_keeps_panel_open_and_speaks_a_reaction_arc():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    take = ScriptedTakeDefinition(
        title="Human reaction",
        beats=(
            ScriptedTakeBeat(kind="tutor_lookup", query="vì sao nấm phát sáng"),
            ScriptedTakeBeat(
                kind="tutor_reaction",
                lead_in="À...",
                locked_summary="Ở một số loài, ánh sáng có thể thu hút côn trùng.",
                afterthought="Một cái biển quảng cáo sống. Khá gian.",
                response_hold_ms=80,
                pause_after_ms=320,
            ),
        ),
    )

    status = runtime.run_definition(take)

    assert status.state == "completed"
    stages = [
        p.get("tutor", {}).get("stage")
        for p in owner.transport.payloads
        if p.get("parse_mode") == "tutor_event"
    ]
    assert stages == ["open", "asking", "answered", "assimilating", "close"]

    take_payloads = [p for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]
    take_texts = [p.get("text", "") for p in take_payloads]
    assert take_texts == [
        "À...",
        "Ở một số loài, ánh sáng có thể thu hút côn trùng.",
        "Một cái biển quảng cáo sống. Khá gian.",
    ]
    phases = [p["stage"]["delivery"]["active_beat"].get("arc_phase") for p in take_payloads]
    assert phases == ["recognition", "reframe", "afterthought"]
    assert stages.index("close") > stages.index("assimilating")



def test_tutor_reaction_exposes_belief_update_when_expectation_exists():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    take = ScriptedTakeDefinition(
        title="Belief update",
        beats=(
            ScriptedTakeBeat(kind="tutor_lookup", query="vì sao nấm phát sáng"),
            ScriptedTakeBeat(
                kind="tutor_reaction",
                lead_in="À...",
                expectation="Tôi cứ tưởng ánh sáng ấy chỉ là một sản phẩm phụ.",
                locked_summary="Nhưng ở một số loài, nó có thể thu hút côn trùng.",
                afterthought="Khá gian, với một cây nấm.",
                response_hold_ms=80,
            ),
        ),
    )

    runtime.run_definition(take)

    payloads = [p for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]
    phases = [p["stage"]["delivery"]["active_beat"].get("arc_phase") for p in payloads]
    assert phases == ["recognition", "contrast", "reframe", "afterthought"]
    assert payloads[1]["text"].startswith("Tôi cứ tưởng")
    assert payloads[1]["stage"]["motion"] == "belief_update"
    assert payloads[1]["animation"] == "stand"
    assert payloads[1]["stage"]["body_timeline"]["events"][0]["facing"] == -1


def test_audio_start_is_the_transport_sync_point_for_segment_body_and_text():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    builder = __import__("runtime.stage_contracts", fromlist=["StageFrameBuilder"]).StageFrameBuilder(language_hint="vi")
    decision = SimpleNamespace(
        text="À...", intent="scripted_take", animation="recognition",
        should_speak=True, delivery_hint="soft_realization", stage_motion="recognition",
    )
    frame = builder.build(
        decision,
        payload={
            "text": "À...",
            "should_speak": True,
            "stage_motion": "recognition",
            "scripted_beat": {"arc_phase": "recognition", "take_beat_index": 2},
        },
        channel="scripted_take",
        turn_id="take-sync",
        segment_id=0,
    )

    runtime._active_take_id = "take-sync"
    runtime._status = runtime._status.__class__("running", take_id="take-sync", title="Sync")
    runtime._emit_frames([frame], take_id="take-sync", title="Sync", send_transport=False)
    assert not [p for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]

    from runtime.stage_audio_bus import StageAudioEvent
    runtime._handle_tts_event(
        StageAudioEvent(type="audio_start", turn_id="take-sync", segment_id=0, text="À..."),
        frame,
    )

    payloads = [p for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]
    assert len(payloads) == 1
    assert payloads[0]["text"] == "À..."
    assert payloads[0]["scripted_take"]["sync"] == "audio_start"
    assert payloads[0]["stage"]["body_timeline"]


def test_template_answer_is_cleaned_before_tts():
    class MarkdownOwner(FakeOwner):
        def request_tutor_answer(self, topic, **kwargs):
            return "- **Ý chính:** Nấm phát sáng.\n- Côn trùng có thể giúp mang bào tử.\nNguồn: https://example.com/paper"

    owner = MarkdownOwner()
    runtime = ScriptedTakeRuntime(owner)
    take = ScriptedTakeDefinition(
        title="Clean",
        beats=(
            ScriptedTakeBeat(kind="tutor_lookup", query="nấm"),
            ScriptedTakeBeat(kind="text", text="À. {{tutor_answer}}"),
        ),
    )

    runtime.run_definition(take)

    spoken = [
        p.get("text", "")
        for p in owner.transport.payloads
        if p.get("parse_mode") == "scripted_take"
    ][-1]
    assert "http" not in spoken
    assert "**" not in spoken
    assert "Nguồn:" not in spoken
    assert "Côn trùng" in spoken


def test_scripted_take_uses_monotonic_segment_ids_across_tutor_boundary():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    take = ScriptedTakeDefinition(
        title="Stable sequence",
        beats=(
            ScriptedTakeBeat(kind="text", text="Câu mở."),
            ScriptedTakeBeat(kind="tutor_lookup", query="một câu hỏi"),
            ScriptedTakeBeat(kind="text", text="Câu sau Tutor."),
        ),
    )

    runtime.run_definition(take)

    payloads = [p for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]
    assert [p["stage"]["segment_id"] for p in payloads] == [0, 1]


def test_stage_segment_is_not_announced_before_audio_start():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    builder = __import__("runtime.stage_contracts", fromlist=["StageFrameBuilder"]).StageFrameBuilder(language_hint="vi")
    frame = builder.build(
        SimpleNamespace(
            text="Đúng nhịp.", intent="scripted_take", animation="stand",
            should_speak=True, delivery_hint="", stage_motion="stand",
        ),
        payload={"text": "Đúng nhịp.", "should_speak": True, "scripted_beat": {}},
        channel="scripted_take",
        turn_id="take-stage-sync",
        segment_id=0,
    )
    runtime._active_take_id = "take-stage-sync"
    runtime._status = runtime._status.__class__("running", take_id="take-stage-sync", title="Sync")

    runtime._emit_frames([frame], take_id="take-stage-sync", title="Sync", send_transport=False)
    assert not [event for event in owner.stage_event_bus.events if event.get("type") == "stage_segment"]

    from runtime.stage_audio_bus import StageAudioEvent
    runtime._handle_tts_event(
        StageAudioEvent(type="audio_start", turn_id="take-stage-sync", segment_id=0, text="Đúng nhịp."),
        frame,
    )
    runtime._handle_tts_event(
        StageAudioEvent(type="audio_start", turn_id="take-stage-sync", segment_id=0, text="Đúng nhịp."),
        frame,
    )

    stage_events = [event for event in owner.stage_event_bus.events if event.get("type") == "stage_segment"]
    payloads = [p for p in owner.transport.payloads if p.get("parse_mode") == "scripted_take"]
    assert len(stage_events) == 1
    assert len(payloads) == 1


def test_take_holds_and_releases_exclusive_stage_ownership():
    from runtime.stage_ownership import stage_ownership_for

    class LeaseAwareOwner(FakeOwner):
        def __init__(self):
            super().__init__()
            self.lease_seen = False

        def request_tutor_answer(self, topic, **kwargs):
            self.lease_seen = stage_ownership_for(self).snapshot().active
            return super().request_tutor_answer(topic, **kwargs)

    owner = LeaseAwareOwner()
    runtime = ScriptedTakeRuntime(owner)
    take = ScriptedTakeDefinition(
        title="Lease",
        beats=(ScriptedTakeBeat(kind="tutor_lookup", query="kiểm tra lease"),),
    )

    runtime.run_definition(take)

    assert owner.lease_seen is True
    assert stage_ownership_for(owner).snapshot().active is False


def test_cancelled_take_rejects_late_audio_start_callback():
    owner = FakeOwner()
    runtime = ScriptedTakeRuntime(owner)
    builder = __import__("runtime.stage_contracts", fromlist=["StageFrameBuilder"]).StageFrameBuilder(language_hint="vi")
    frame = builder.build(
        SimpleNamespace(
            text="Không được xuất hiện muộn.", intent="scripted_take", animation="stand",
            should_speak=True, delivery_hint="", stage_motion="stand",
        ),
        payload={"text": "Không được xuất hiện muộn.", "should_speak": True, "scripted_beat": {}},
        channel="scripted_take",
        turn_id="take-cancelled",
        segment_id=0,
    )
    runtime._active_take_id = "take-cancelled"
    runtime._status = runtime._status.__class__("cancelled", take_id="take-cancelled", title="Cancelled")

    from runtime.stage_audio_bus import StageAudioEvent
    runtime._handle_tts_event(
        StageAudioEvent(type="audio_start", turn_id="take-cancelled", segment_id=0, text=frame.tts_text),
        frame,
    )

    assert not [event for event in owner.stage_event_bus.events if event.get("type") == "stage_segment"]
    assert not [payload for payload in owner.transport.payloads if payload.get("parse_mode") == "scripted_take"]
