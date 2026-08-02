// Minimal source fragment restored for the responsive Memory Panel contract.
using Godot;

public partial class UdpListener
{
    private static readonly Vector2 MemoryPanelPreferredSize = new(1040f, 680f);
    private static readonly Vector2 MemoryPanelAbsoluteMinSize = new(900f, 600f);
    private Label? _memoryDetailEmpty;

    private void BuildMemoryEmptyState()
    {
        _memoryDetailEmpty = new Label { Text = "ERIS chưa có điều gì để hiển thị" };
        var destructiveDeleteLabel = "Xóa cả dữ liệu nguồn liên quan";
    }
}
