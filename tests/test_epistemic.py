from __future__ import annotations

from cortex.private_mind.inner_diary_renderer import InnerDiaryRenderer


def test_inner_diary_renderer_builds_emotion_board_payload():
    renderer = InnerDiaryRenderer()
    digest = {
        "menu": {
            "current_thought": {"dominant_judgment": "Ổn định"},
            "open_concerns": [{"theme": "Đang bận tâm một chút", "pressure": 0.66}],
            "surface_queue": [{"topic_seed": "Muốn nói chuyện nhẹ nhàng"}],
        }
    }

    payload = renderer.render(digest)

    assert payload["emotion_board"]["title"] == "Bảng cảm xúc"
    assert payload["emotion_board"]["shape"] == "circle"
    assert payload["emotion_board"]["center"]["label"] == "Ổn định"
    assert "vui vẻ" in payload["emotion_board"]["axes"]
    assert payload["sections"][0]["title"] == "Bảng cảm xúc"
