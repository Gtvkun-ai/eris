from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from src.memory.memory_kernel import MemoryKernel


def test_build_packet_matches_vietnamese_semantic_cues(tmp_path) -> None:
    kernel = MemoryKernel(base_dir=str(tmp_path / "memory_core"))
    kernel.ingest("tôi tên là Hòa", turn_id="turn:1", mode="fast")
    kernel.ingest("tôi sinh tháng 6", turn_id="turn:2", mode="fast")

    ten_packet = kernel.build_packet("tên")
    thang_packet = kernel.build_packet("tháng 6")

    assert ten_packet.semantic
    assert any("Hòa" in line or "Hoa" in line for line in ten_packet.semantic)

    assert thang_packet.semantic
    assert any("birth month is 6" in line or "tháng 6" in line or "thang 6" in line for line in thang_packet.semantic)
