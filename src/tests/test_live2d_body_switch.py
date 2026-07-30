# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import socket
from pathlib import Path

from live2d_body.parameter_profile import INFJ_PARAMETER_PROFILE
from live2d_body.stage_state import Live2DStageState
from live2d_body.udp_receiver import Live2DStageReceiver


def test_model_bundle_has_runtime_references() -> None:
    model = Path(__file__).resolve().parents[1] / "assets" / "live2d" / "infj" / "infj.model3.json"
    payload = json.loads(model.read_text(encoding="utf-8"))
    refs = payload["FileReferences"]
    referenced = [refs["Moc"], *refs["Textures"], refs["Physics"], refs["DisplayInfo"]]
    assert all((model.parent / relative).is_file() for relative in referenced)
    groups = {item["Name"]: item["Ids"] for item in payload["Groups"]}
    assert groups["EyeBlink"] == ["ParamEyeLOpen", "ParamEyeROpen"]
    assert groups["LipSync"] == ["ParamMouthOpenY"]


def test_stage_state_tracks_speech_lifecycle() -> None:
    state = Live2DStageState()
    state.handle_payload({"protocol": "eris.stage", "type": "stage_segment", "emotion": "curious"})
    assert state.advance(1 / 60).emotion == "curious"
    state.handle_payload({"protocol": "eris.stage", "type": "audio_playback_started"})
    assert state.advance(1 / 60).speaking is True
    state.handle_payload({"protocol": "eris.stage", "type": "audio_playback_done"})
    assert state.advance(1 / 60).speaking is False


def test_right_click_request_targets_godot_context_menu() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(1.0)
        port = listener.getsockname()[1]
        receiver = Live2DStageReceiver(
            Live2DStageState(),
            port=port + 1,
            body_host="127.0.0.1",
            body_port=port,
        )
        receiver.send_context_menu_request(screen_x=320, screen_y=240)
        raw, _ = listener.recvfrom(4096)
        payload = json.loads(raw.decode("utf-8"))
        assert payload["protocol"] == "eris.body.control"
        assert payload["type"] == "open_context_menu"
        assert payload["screen_x"] == 320
        assert payload["screen_y"] == 240


def test_gaze_keeps_custom_eyes_coupled_without_extreme_crossing() -> None:
    from live2d_body.gaze import GazeController

    gaze = GazeController(strength_x=0.28, strength_y=0.20, right_x_sign=-1.0)
    sample = None
    for _ in range(30):
        sample = gaze.update(
            cursor_screen=(2000.0, 500.0),
            face_screen=(1000.0, 500.0),
            span_x=400.0,
            span_y=300.0,
            dt=1 / 60,
        )
    assert sample is not None
    assert 0.0 < sample.left_x <= 0.28
    assert -0.28 <= sample.right_x < 0.0
    # Mắt nhìn vào sống mũi có biên nhỏ hơn mắt nhìn ra ngoài.
    assert abs(sample.left_x) > abs(sample.right_x)
    assert 0.0 < sample.head_x_degrees <= 2.4
    assert 0.78 <= sample.left_eye_open_scale <= 1.0


def test_window_geometry_is_reported_to_godot_body() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(1.0)
        port = listener.getsockname()[1]
        receiver = Live2DStageReceiver(
            Live2DStageState(),
            port=port + 1,
            body_host="127.0.0.1",
            body_port=port,
        )
        receiver.send_window_geometry(screen_x=1200, screen_y=100, width=520, height=900)
        raw, _ = listener.recvfrom(4096)
        payload = json.loads(raw.decode("utf-8"))
        assert payload["type"] == "window_geometry"
        assert payload["screen_x"] == 1200
        assert payload["height"] == 900


def test_renderer_control_visibility_is_resident_state() -> None:
    receiver = Live2DStageReceiver(Live2DStageState(), port=0)
    assert receiver.desired_visible is True
    assert receiver._handle_renderer_control({
        "protocol": "eris.live2d.control",
        "type": "set_visibility",
        "visible": False,
    }) is True
    assert receiver.desired_visible is False
    receiver._handle_renderer_control({
        "protocol": "eris.live2d.control",
        "type": "set_visibility",
        "visible": True,
    })
    assert receiver.desired_visible is True


def test_renderer_control_window_geometry_is_consumed_once() -> None:
    receiver = Live2DStageReceiver(Live2DStageState(), port=0)
    assert receiver._handle_renderer_control({
        "protocol": "eris.live2d.control",
        "type": "set_window_geometry",
        "screen_x": 120,
        "screen_y": 80,
        "width": 520,
        "height": 900,
    }) is True
    assert receiver.consume_requested_window_geometry() == {
        "x": 120,
        "y": 80,
        "width": 520,
        "height": 900,
    }
    assert receiver.consume_requested_window_geometry() is None


def test_renderer_control_shutdown_is_recorded() -> None:
    receiver = Live2DStageReceiver(Live2DStageState(), port=0)
    receiver._handle_renderer_control({
        "protocol": "eris.live2d.control",
        "type": "shutdown",
    })
    assert receiver.shutdown_requested is True


def test_parameter_profile_matches_viewer_semantics() -> None:
    profile = INFJ_PARAMETER_PROFILE
    assert profile.clamp_angle_x(-99.0) == -30.0
    assert profile.clamp_angle_x(99.0) == 10.0
    assert profile.mouth_open_from_ratio(0.0) == -1.0
    assert profile.mouth_open_from_ratio(0.5) == 0.0
    assert profile.mouth_open_from_ratio(1.0) == 1.0


def test_stage_state_closes_custom_mouth_at_minus_one() -> None:
    state = Live2DStageState()
    snapshot = state.advance(0.0, now=0.0)
    assert snapshot.parameters["ParamMouthOpenY"] == -1.0


def test_warm_expression_does_not_raise_both_brows() -> None:
    state = Live2DStageState()
    state.handle_payload({"protocol": "eris.stage", "type": "stage_segment", "emotion": "warm_soft"})
    snapshot = state.advance(0.0, now=0.0)
    assert snapshot.parameters["ParamBrowLAngle"] <= 0.0
    assert snapshot.parameters["ParamBrowRAngle"] <= 0.0
    assert snapshot.parameters["ParamMouthForm"] > 0.0


def test_gaze_left_uses_larger_viewer_left_head_range() -> None:
    from live2d_body.gaze import GazeController

    gaze = GazeController(
        strength_x=0.30,
        strength_y=0.18,
        head_follow_left_degrees=4.8,
        head_follow_right_degrees=2.4,
    )
    sample = None
    for _ in range(60):
        sample = gaze.update(
            cursor_screen=(0.0, 500.0),
            face_screen=(1000.0, 500.0),
            span_x=400.0,
            span_y=300.0,
            dt=1 / 60,
        )
    assert sample is not None
    assert -4.8 <= sample.head_x_degrees < 0.0
    assert sample.left_x < 0.0 < sample.right_x
    assert abs(sample.right_x) > abs(sample.left_x)


def test_eyelid_scaling_reads_current_frame_value_not_cached_snapshot() -> None:
    from live2d_body.renderer import Live2DRenderer

    class FakeParameter:
        id = "ParamEyeLOpen"
        value = 1.0  # stale load-time snapshot

    class FakeModel:
        def __init__(self) -> None:
            self.writes: list[tuple[str, float]] = []

        def GetParameterValue(self, index: int) -> float:
            assert index == 3
            return 0.20  # auto-blink value generated by model.Update() this frame

        def GetParameter(self, index: int) -> FakeParameter:
            return FakeParameter()

        def SetParameterValue(self, parameter_id: str, value: float) -> None:
            self.writes.append((parameter_id, value))

    renderer = object.__new__(Live2DRenderer)
    renderer._parameter_indices = {"ParamEyeLOpen": 3}
    model = FakeModel()

    renderer._scale_eye_parameter(model, "ParamEyeLOpen", 0.5)

    assert model.writes == [("ParamEyeLOpen", 0.10)]


def test_stage_state_deduplicates_direct_and_godot_mirrors() -> None:
    state = Live2DStageState()
    started = {
        "protocol": "eris.stage",
        "type": "audio_playback_started",
        "event_id": "evt_same_packet",
        "tts_text": "Xin chào.",
    }
    state.handle_payload(started)
    assert state.advance(0.0).speaking is True

    # A duplicate with the same event_id must not mutate state a second time.
    duplicate = dict(started)
    duplicate["type"] = "audio_playback_done"
    state.handle_payload(duplicate)
    assert state.advance(0.0).speaking is True


def test_stage_bus_directly_mirrors_events_to_live2d(monkeypatch) -> None:
    from runtime.stage_event_bus import StageEventBus
    from runtime.stage_protocol import StageProtocolEvent

    class FakeTransport:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def send_json(self, payload: dict) -> None:
            self.payloads.append(payload)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(1.0)
        port = listener.getsockname()[1]
        monkeypatch.setenv("ERIS_LIVE2D_DIRECT_MIRROR", "1")
        monkeypatch.setenv("ERIS_LIVE2D_PORT", str(port))
        monkeypatch.setattr("runtime.stage_event_bus.stage_protocol_enabled", lambda: True)

        transport = FakeTransport()
        bus = StageEventBus(transport=transport)
        assert bus.emit(StageProtocolEvent(type="audio_playback_started", tts_text="Chào.")) is True

        raw, _ = listener.recvfrom(65507)
        mirrored = json.loads(raw.decode("utf-8"))
        assert mirrored["protocol"] == "eris.stage"
        assert mirrored["type"] == "audio_playback_started"
        assert mirrored["event_id"]
        assert transport.payloads[0]["event_id"] == mirrored["event_id"]
