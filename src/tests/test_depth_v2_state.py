from __future__ import annotations

import json
import time


def test_build_depth_v2_state_uses_private_mind_as_primary_source(tmp_path, monkeypatch):
    monkeypatch.setenv("ERIS_MEMORY_CORE_DIR", str(tmp_path))
    now = time.time()

    (tmp_path / "development_profile.json").write_text(
        json.dumps(
            {
                "axes": {
                    "warmth_temperature": {"delta": 0.22},
                    "preferred_distance": {"delta": -0.14},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "anchor_state.json").write_text(
        json.dumps({"attachment_longarc": 0.63}),
        encoding="utf-8",
    )
    (tmp_path / "panel_snapshot.json").write_text(
        json.dumps(
            {
                "ts": now,
                "signal_log": [
                    {"kind": "tom_read", "time": "21:53:19"},
                    {"kind": "expanded", "time": "21:53:20"},
                ],
            }
        ),
        encoding="utf-8",
    )

    from runtime.depth_v2_state import build_depth_v2_state

    digest = {
        "last_tick_at": 198.4,
        "affect": {
            "valence": 0.32,
            "arousal": 0.28,
            "tenderness": 0.66,
            "irritation": 0.08,
        },
        "inner_diary": {
            "sections": [
                {
                    "title": "Suy nghĩ hiện tại",
                    "items": [{"text": "Ngài đang muốn làm việc về kiến trúc.", "badge": ""}],
                },
                {
                    "title": "Suy nghĩ tương lai",
                    "items": [{"text": "Tôi sẽ ưu tiên trả lời theo hướng kỹ thuật rõ ràng.", "badge": ""}],
                },
                {
                    "title": "Đang bận tâm",
                    "items": [{"text": "Architecture / implementation details", "badge": "áp lực 0.89"}],
                },
                {
                    "title": "Phân tích gần đây",
                    "items": [{"text": "Đây là chủ đề Ngài quan tâm.", "badge": "score 0.81"}],
                },
                {
                    "title": "Muốn nói",
                    "items": [{"text": "Tôi muốn trả lời ngắn, kỹ thuật, và trực tiếp.", "badge": ""}],
                },
            ],
            "emotion_board": {
                "center": {"label": "calm", "subtext": "listening closely"},
                "quadrants": {
                    "top": {"label": "energized", "intensity": "0.21"},
                    "left": {"label": "bright", "intensity": "0.55"},
                    "right": {"label": "tense", "intensity": "0.12"},
                    "bottom": {"label": "steady", "intensity": "0.88"},
                },
            },
        },
        "menu": {
            "current_thought": {"dominant_judgment": "User wants architecture work."},
            "future_bias": {
                "speech_bias": {
                    "intent": "technical answer",
                    "next_move": "explain panel architecture",
                },
                "inquiry_plan": [{"question": "Should I remove the old panel contract first?"}],
            },
            "open_concerns": [{"theme": "architecture implementation", "pressure": 0.89}],
            "surface_queue": [{"topic_seed": "panel contract cleanup", "confidence": 0.74}],
        },
    }

    state = build_depth_v2_state(
        private_mind_digest=digest,
        flags={"private_mind": True, "tom_advisor": True},
        expression_gate={
            "want_to_say": 0.73,
            "suppression_pressure": 0.42,
            "allowed_expression": 0.30,
            "stance": "guarded_tender",
        },
        tom_read="tom_read: You may be focused on architecture (~0.72).",
        identity={"name": "ERIS", "channel": "chat", "alive": True},
        affect_history=[],
        now=now,
    )

    assert state["version"] == 2
    assert state["identity"]["name"] == "ERIS"
    assert state["status"]["focus_mode"] == "deep_work"
    assert state["affect"]["headline"] == "calm"
    assert state["tom"]["confidence"] == 0.72
    assert state["expression"]["want"] == 0.73
    assert state["priorities"][0]["key"] == "technical"
    assert state["interiority"]["current"]["title"] == "Suy nghĩ hiện tại"
    assert state["interiority"]["concern"]["title"] == "Đang bận tâm"
    assert state["n2"]["attachment"]["value"] == 0.63
    assert len(state["n2"]["axes"]) == 2
    assert state["signal_log"][0]["text"] == "updated user-reading"
    assert state["journal"][0]["source"] == "current"
    assert len(state["affect_history"]) == 1


def test_build_depth_v2_state_rolls_affect_history_without_duplicate_spam(tmp_path, monkeypatch):
    monkeypatch.setenv("ERIS_MEMORY_CORE_DIR", str(tmp_path))

    from runtime.depth_v2_state import build_depth_v2_state

    digest = {
        "affect": {"valence": 0.10, "arousal": 0.20, "tenderness": 0.30, "irritation": 0.05},
        "inner_diary": {"sections": []},
        "menu": {},
    }

    first = build_depth_v2_state(
        private_mind_digest=digest,
        flags={},
        expression_gate={},
        tom_read="",
        identity={},
        affect_history=[],
        now=100.0,
    )
    second = build_depth_v2_state(
        private_mind_digest=digest,
        flags={},
        expression_gate={},
        tom_read="",
        identity={},
        affect_history=first["affect_history"],
        now=101.0,
    )
    shifted = build_depth_v2_state(
        private_mind_digest={
            **digest,
            "affect": {"valence": -0.40, "arousal": 0.65, "tenderness": 0.22, "irritation": 0.42},
        },
        flags={},
        expression_gate={},
        tom_read="",
        identity={},
        affect_history=second["affect_history"],
        now=102.0,
    )

    assert len(first["affect_history"]) == 1
    assert len(second["affect_history"]) == 1
    assert len(shifted["affect_history"]) == 2
    assert shifted["affect_history"][-1]["value"] != shifted["affect_history"][0]["value"]
