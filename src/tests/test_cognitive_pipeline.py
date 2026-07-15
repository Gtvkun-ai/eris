import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from core.cognitive_frame import CognitiveFrame
from core.evidence import RawSignal
from core.evidence_normalizer import EvidenceNormalizer, normalize_signals
from runtime.cognitive_pipeline import CognitivePipeline
from runtime.debug_trace import render_frame_trace, render_frame_trace_json


def _signals():
    return [
        RawSignal.from_chat("ERIS, build gì tiếp theo cho V3?"),
        RawSignal.from_active_window("Visual Studio Code - cognitive_pipeline.py"),
        RawSignal.from_telemetry({"idle_seconds": 12, "cpu": 0.31}),
    ]


# ---------------------------------------------------------------------------
# Phase 1: contract RawSignal -> EvidenceItem
# ---------------------------------------------------------------------------

def test_normalizer_produces_evidence_for_each_signal():
    items = normalize_signals(_signals())
    assert len(items) == 3
    # mọi evidence neo vào đúng một raw signal và là raw, không phải suy diễn
    for ev in items:
        assert ev.source_signal_id
        assert ev.raw_or_inferred == "raw"
        assert ev.claim
        assert 0.0 <= ev.confidence <= 1.0


def test_user_chat_evidence_has_high_confidence():
    items = normalize_signals([RawSignal.from_chat("xin chào")])
    assert items[0].source == "user_chat"
    assert items[0].confidence >= 0.95


def test_normalize_into_frame_adds_evidence_and_note():
    frame = CognitiveFrame.start(raw_signals=_signals(), channel="chat")
    result = EvidenceNormalizer().normalize_into_frame(frame)
    assert result.count == 3
    assert len(frame.evidence) == 3
    assert any("evidence_normalizer" in note for note in frame.debug_notes)


# ---------------------------------------------------------------------------
# Phase 2 + 4: backbone + attention/budget/working_memory/workspace
# ---------------------------------------------------------------------------

def test_pipeline_fills_all_phase1_slots():
    pipeline = CognitivePipeline()
    result = pipeline.run_from_signals(_signals(), channel="chat")
    frame = result.frame

    # evidence được sinh
    assert len(frame.evidence) == 3
    # bốn slot Phase 1 đều có giá trị
    assert frame.salience is not None
    assert frame.budget_mode in ("fast", "normal", "deep", "reflection")
    assert frame.working_memory is not None
    assert frame.workspace is not None
    # frame đóng sạch, không failed
    assert frame.status == "closed"


def test_pipeline_records_module_reports():
    pipeline = CognitivePipeline()
    result = pipeline.run_from_signals(_signals(), channel="chat")
    reports = result.frame.module_reports
    assert "cognitive_budget" in reports
    # attention/working_memory/workspace tự add report qua add_report
    assert any(name in reports for name in ("attention_salience", "working_memory", "global_workspace"))


def test_chat_channel_not_downgraded_to_fast_blindly():
    # chat có user text thật: budget không nên là fast (chat_minimum_mode=normal)
    pipeline = CognitivePipeline()
    result = pipeline.run_from_signals(
        [RawSignal.from_chat("giải thích kiến trúc cognitive pipeline và sửa lỗi budget")],
        channel="chat",
    )
    assert result.budget_mode != "fast"


# ---------------------------------------------------------------------------
# Phase 3: debug trace
# ---------------------------------------------------------------------------

def test_debug_trace_is_human_readable():
    pipeline = CognitivePipeline()
    result = pipeline.run_from_signals(_signals(), channel="chat")
    trace = render_frame_trace(result.frame)

    assert trace["frame_id"]
    assert trace["budget"] in ("fast", "normal", "deep", "reflection")
    assert trace["evidence_count"] == 3
    # JSON serialize được, không ném lỗi
    text = render_frame_trace_json(result.frame)
    assert "frame_id" in text


def test_debug_trace_survives_minimal_frame():
    # trace không được làm chết runtime kể cả frame gần như rỗng
    frame = CognitiveFrame.start(channel="test")
    trace = render_frame_trace(frame)
    assert trace["frame_id"]
    assert "debug_trace_error" not in trace
