# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import socket
from pathlib import Path

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
