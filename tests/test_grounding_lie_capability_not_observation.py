from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from runtime.chat_cycle import ChatCycleMixin


class _Stub(ChatCycleMixin):
    """Chỉ dựng đủ thuộc tính mà _chat_source_grounding_screen_facts cần."""

    def __init__(self, *, captured_at: float = 0.0, facts=(), can_capture: bool = True):
        self.vision_facts = tuple(facts)
        self.vision_last_capture_at = captured_at
        if can_capture:
            self.telemetry_service = SimpleNamespace(
                capture_screen_frame_data_uri=lambda: ""
            )
        else:
            self.telemetry_service = SimpleNamespace()


def _claims(facts) -> list[str]:
    return [str(getattr(f, "get", lambda *_: "")("source") if hasattr(f, "get") else "") for f in facts]


def test_capability_to_capture_is_not_evidence_of_having_seen() -> None:
    # Chưa từng chụp (captured_at=0), không ảnh tươi, không facts — nhưng telemetry
    # CÓ KHẢ NĂNG chụp. ERIS không được bịa "màn hình từng hiện lượt trước".
    stub = _Stub(captured_at=0.0, facts=(), can_capture=True)
    snapshot = SimpleNamespace(vision_facts=())

    facts = stub._chat_source_grounding_screen_facts(snapshot, screen_image_data_uri="")

    assert facts == (), "Khả năng nhìn != đã nhìn: không được phát screen evidence giả."


def test_genuine_prior_capture_yields_stale_marker() -> None:
    # Đã thực sự chụp frame trước đó -> được coi là có màn hình (cũ).
    stub = _Stub(captured_at=time.time() - 30.0, facts=(), can_capture=True)
    snapshot = SimpleNamespace(vision_facts=())

    facts = stub._chat_source_grounding_screen_facts(snapshot, screen_image_data_uri="")

    sources = [f.get("source") for f in facts if isinstance(f, dict)]
    assert "screen_capture_prev_turn" in sources


def test_fresh_capture_yields_live_frame_fact() -> None:
    stub = _Stub(captured_at=0.0, facts=(), can_capture=True)
    snapshot = SimpleNamespace(vision_facts=())

    facts = stub._chat_source_grounding_screen_facts(
        snapshot, screen_image_data_uri="data:image/png;base64,AAAA"
    )

    sources = [f.get("source") for f in facts if isinstance(f, dict)]
    assert "screen_capture" in sources
