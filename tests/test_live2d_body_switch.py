# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import socket
from pathlib import Path

from live2d_body.stage_state import Live2DStageState
from live2d_body.udp_receiver import Live2DStageReceiver


def test_model_bundle_has_runtime_references() -> None:
    model = Path(__file__).resolve().parents[1] / "src" / "assets" / "live2d" / "infj" / "infj.model3.json"
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
    assert abs(abs(sample.right_x) / sample.left_x - 0.78) < 1e-6


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
