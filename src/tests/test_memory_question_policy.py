from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from src.memory.memory_kernel import MemoryKernel
from src.memory.understanding.semantic_parser import FallbackSurfaceSemanticParser
from src.memory.understanding.meaning_frame import EntityRef, MeaningFrame, MeaningParseResult


class RecordingSemanticParser:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, text: str, *, structured=None) -> MeaningParseResult:
        self.calls.append(text)
        return MeaningParseResult(
            frames=tuple(_frames_for(text)),
            source="test_recording_parser",
            confidence=0.91,
            diagnostics=(),
        )


def _frames_for(text: str) -> Iterable[MeaningFrame]:
    normalized = " ".join(text.casefold().replace("?", "").split())
    if normalized == "ban nho toi ten gi khong":
        return (
            MeaningFrame(
                frame_type="session_event",
                relation="asked_about",
                target=EntityRef(text="user.name", kind="memory_query", canonical="user.name", confidence=0.95),
                modality="observation",
                time_scope="session",
                certainty=0.84,
                stability="session",
                evidence_span=text,
            ),
        )
    if normalized == "toi ten gi":
        return (
            MeaningFrame(
                frame_type="identity",
                relation="name",
                target=EntityRef(text="gi", kind="person_name", canonical="gi", confidence=0.95),
                modality="fact",
                time_scope="stable",
                certainty=0.94,
                stability="stable",
                evidence_span=text,
            ),
        )
    if "toi ten la hoa" in normalized:
        return (
            MeaningFrame(
                frame_type="identity",
                relation="name",
                target=EntityRef(text="Hoa", kind="person_name", canonical="hoa", confidence=0.95),
                modality="fact",
                time_scope="stable",
                certainty=0.94,
                stability="stable",
                evidence_span=text,
            ),
        )
    return ()


def _kernel(tmp_path: Path) -> tuple[MemoryKernel, RecordingSemanticParser]:
    parser = RecordingSemanticParser()
    return MemoryKernel(base_dir=str(tmp_path / "memory_core"), semantic_parser=parser), parser


def test_semantic_digest_parses_and_commits_explicit_name(tmp_path: Path) -> None:
    kernel, parser = _kernel(tmp_path)

    result = kernel.ingest("toi ten la Hoa", turn_id="turn:name", mode="semantic_digest")

    assert parser.calls == ["toi ten la Hoa"]
    assert result.committed_count == 1
    semantic_items = kernel.core.load()["semantic_memory"]
    assert semantic_items[0]["metadata"]["predicate"] == "name_is"
    assert semantic_items[0]["metadata"]["value"] == "Hoa"


def test_semantic_digest_parses_memory_question_but_commits_nothing(tmp_path: Path) -> None:
    kernel, parser = _kernel(tmp_path)

    result = kernel.ingest("ban nho toi ten gi khong?", turn_id="turn:question", mode="semantic_digest")

    assert parser.calls == ["ban nho toi ten gi khong?"]
    assert result.committed_count == 0
    assert result.decisions == []
    assert kernel.core.load()["semantic_memory"] == []


def test_semantic_digest_rejects_question_even_if_parser_misreads_name_as_gi(tmp_path: Path) -> None:
    kernel, parser = _kernel(tmp_path)

    result = kernel.ingest("toi ten gi?", turn_id="turn:bad-question", mode="semantic_digest")

    assert parser.calls == ["toi ten gi?"]
    assert result.committed_count == 0
    assert result.decisions == []
    assert kernel.core.load()["semantic_memory"] == []


def test_fast_question_gate_skips_parser_and_commits_nothing(tmp_path: Path) -> None:
    kernel, parser = _kernel(tmp_path)

    result = kernel.ingest("ban nho toi ten gi khong?", turn_id="turn:fast-question", mode="fast")

    assert parser.calls == []
    assert result.committed_count == 0
    assert result.decisions == []
    assert kernel.core.load()["semantic_memory"] == []


def test_fallback_parser_can_emit_session_event_for_memory_question() -> None:
    result = FallbackSurfaceSemanticParser().parse("ban nho toi ten gi khong?")

    assert len(result.frames) == 1
    frame = result.frames[0]
    assert frame.frame_type == "session_event"
    assert frame.relation == "asked_about"
    assert frame.target is not None
    assert frame.target.text == "user.name"
    assert frame.target.kind == "memory_query"


def test_semantic_digest_allows_explicit_memory_request_with_question_mark(tmp_path: Path) -> None:
    kernel, parser = _kernel(tmp_path)

    result = kernel.ingest("nho rang toi ten la Hoa?", turn_id="turn:remember-question", mode="semantic_digest")

    assert parser.calls == ["nho rang toi ten la Hoa?"]
    assert result.committed_count == 1
    semantic_items = kernel.core.load()["semantic_memory"]
    assert semantic_items[0]["metadata"]["predicate"] == "name_is"
    assert semantic_items[0]["metadata"]["value"] == "Hoa"
