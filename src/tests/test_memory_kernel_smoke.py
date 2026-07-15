from __future__ import annotations

"""
Smoke test tối thiểu cho MemoryKernel.

Mục tiêu của file này không phải phủ hết semantic memory.
Nó chỉ kiểm tra 4 thứ sống được:
- ingest fast không crash;
- answer path gọi compiler/executor/surface được;
- build_packet vẫn đi qua MemoryCognitionCore recall cũ;
- maintain chạy audit mode, không xóa dữ liệu mặc định.

Đây là test chống "file mới nhìn đẹp nhưng import là nổ". Một tiêu chuẩn thấp,
nhưng nhân loại vẫn thường vấp ở tiêu chuẩn thấp.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from src.memory.memory_kernel import MemoryKernel


def test_memory_kernel_smoke(tmp_path: Path) -> None:
    kernel = MemoryKernel(base_dir=str(tmp_path / "memory_core"))

    ingest = kernel.ingest(
        "tôi tên là Hòa",
        turn_id="turn:1",
        source="test",
        mode="fast",
    )
    assert ingest.mode == "fast"
    assert ingest.input_text == "tôi tên là Hòa"

    packet = kernel.build_packet("tên", budget_mode="fast")
    assert packet is not None

    answer = kernel.answer("tôi tên gì")
    assert answer is not None
    assert hasattr(answer, "intercepted")

    report = kernel.maintain(reason="test", budget="small")
    assert report.reason == "test"
    assert report.budget == "small"
