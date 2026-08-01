from pathlib import Path


def test_memory_panel_uses_compact_responsive_empty_state():
    source = (Path(__file__).parents[2] / "body" / "UdpListener.MemoryPanel.cs").read_text(encoding="utf-8")
    assert "MemoryPanelPreferredSize = new(1040f, 680f)" in source
    assert "MemoryPanelAbsoluteMinSize = new(900f, 600f)" in source
    assert "_memoryDetailEmpty" in source
    assert "ERIS chưa có điều gì để hiển thị" in source
    assert "Xóa cả dữ liệu nguồn liên quan" in source
    assert "MemoryPanelMinSize" not in source
    assert "Ít nhất panel không bịa" not in source
