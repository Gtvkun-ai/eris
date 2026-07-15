import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from core.cognitive_frame import CognitiveFrame
from runtime.cognitive_pipeline import PipelineResult
from runtime.shadow_pipeline import ShadowPipelineMixin


class _StubCoordinator(ShadowPipelineMixin):
    """Coordinator tối giản chỉ để test mixin shadow độc lập."""

    def __init__(self):
        self.logger = logging.getLogger("shadow_test")
        self.shadow_pipeline_enabled = True
        self.last_shadow_pipeline_result = None
        self.last_shadow_trace = None
        self.last_shadow_comparison = None
        self.last_v3_promotion = None


def _snapshot():
    return SimpleNamespace(
        active_window="Visual Studio Code",
        focus_summary="editing cognitive_pipeline.py",
        idle_seconds=8.0,
        recent_events=("opened file", "ran pytest"),
        evidence=("file saved",),
    )


def test_shadow_disabled_returns_none():
    coord = _StubCoordinator()
    coord.shadow_pipeline_enabled = False
    os.environ.pop("ERIS_SHADOW_PIPELINE", None)
    result = coord._run_shadow_cognitive_pipeline(channel="chat", user_text="hi", snapshot=_snapshot())
    assert result is None


def test_shadow_runs_and_compares_with_old_frame():
    coord = _StubCoordinator()
    # frame "cũ" giả lập: dùng object có broadcast.content để render_frame_trace đọc focus
    old_frame = SimpleNamespace(
        cycle_id="old_123",
        channel="chat",
        broadcast=SimpleNamespace(content="user hỏi build gì tiếp cho V3", label="user_message"),
        evidence=[],
    )
    result = coord._run_shadow_cognitive_pipeline(
        channel="chat",
        user_text="ERIS, build gì tiếp cho V3?",
        snapshot=_snapshot(),
        old_frame=old_frame,
    )
    assert isinstance(result, PipelineResult)
    assert result.budget_mode in ("fast", "normal", "deep", "reflection")

    comparison = coord.last_shadow_comparison
    assert comparison["channel"] == "chat"
    assert comparison["v3_budget"] in ("fast", "normal", "deep", "reflection")
    assert comparison["old_frame_id"] == "old_123"
    assert "focus_overlap" in comparison
    assert comparison["v3_evidence_count"] >= 1


def test_shadow_never_raises_on_bad_snapshot():
    coord = _StubCoordinator()
    # snapshot rác: mixin phải nuốt lỗi, không ném ra hot path
    result = coord._run_shadow_cognitive_pipeline(
        channel="chat",
        user_text="test",
        snapshot=object(),
        old_frame=None,
    )
    # có thể chạy được (object() chỉ làm _snap trả default) hoặc None nếu lỗi; cả hai đều không raise
    assert result is None or isinstance(result, PipelineResult)


def _old_frame():
    return SimpleNamespace(
        cycle_id="old_123",
        channel="chat",
        broadcast=SimpleNamespace(content="user hỏi build gì tiếp cho V3", label="user_message"),
        evidence=[],
        metadata={},
        debug_notes=[],
    )


def test_promotion_off_by_default_does_not_touch_old_frame():
    coord = _StubCoordinator()
    os.environ.pop("ERIS_V3_PROMOTE", None)
    old = _old_frame()
    coord._run_shadow_cognitive_pipeline(
        channel="chat", user_text="hi", snapshot=_snapshot(), old_frame=old
    )
    assert not hasattr(old, "budget_mode") or old.metadata.get("v3_budget_decision") is None
    assert coord.last_v3_promotion["applied"] == {}


def test_promotion_budget_writes_onto_old_frame():
    coord = _StubCoordinator()
    coord.v3_promoted_paths = {"budget"}
    old = _old_frame()
    coord._run_shadow_cognitive_pipeline(
        channel="chat", user_text="ERIS build gì tiếp?", snapshot=_snapshot(), old_frame=old
    )
    applied = coord.last_v3_promotion["applied"]
    assert applied.get("budget") in ("fast", "normal", "deep", "reflection")
    assert old.budget_mode == applied["budget"]
    assert "v3_budget_decision" in old.metadata
    assert any("v3_promoted=" in note for note in old.debug_notes)


def test_promotion_focus_is_advisory_metadata_only():
    coord = _StubCoordinator()
    coord.v3_promoted_paths = {"focus"}
    old = _old_frame()
    original_broadcast = old.broadcast
    coord._run_shadow_cognitive_pipeline(
        channel="chat", user_text="ERIS build gì tiếp?", snapshot=_snapshot(), old_frame=old
    )
    # focus chỉ ghi advisory, không đụng broadcast cũ
    assert old.broadcast is original_broadcast
    if "focus" in coord.last_v3_promotion["applied"]:
        assert old.metadata.get("v3_dominant_focus")


def test_promotion_ignores_unknown_paths():
    coord = _StubCoordinator()
    coord.v3_promoted_paths = {"garbage_path"}
    old = _old_frame()
    coord._run_shadow_cognitive_pipeline(
        channel="chat", user_text="hi", snapshot=_snapshot(), old_frame=old
    )
    assert coord.last_v3_promotion["applied"] == {}


def test_shadow_builds_raw_signals_from_inputs():
    coord = _StubCoordinator()
    signals = coord._build_shadow_raw_signals(
        user_text="câu hỏi",
        snapshot=_snapshot(),
        vision_facts=("thấy editor mở",),
    )
    sources = {s.source for s in signals}
    assert "user_chat" in sources
    assert "active_window" in sources
    assert "telemetry" in sources
    assert "vision" in sources
