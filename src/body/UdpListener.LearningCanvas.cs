using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;

public partial class UdpListener
{
    private Panel _learningCanvasPanel;
    private Button _contextLearningCanvasButton, _canvasMapToggle, _canvasReadToggle;
    private Label _canvasStatus, _canvasPinLabel;
    private HBoxContainer _canvasColumns;
    private ScrollContainer _canvasMapScroll, _canvasDetailScroll;
    private VBoxContainer _canvasGraph, _canvasDetail;
    private readonly Dictionary<string, Button> _canvasNodeButtons = new();
    private readonly Dictionary<string, JsonElement> _canvasDetailCache = new();
    private JsonElement _canvasSnapshot;
    private string _canvasSelectedNode = "", _canvasDesiredNode = "";
    private long _canvasRevision = -1;
    private bool _canvasShowMap = true, _canvasNarrow, _canvasPreview;
    private Vector2 _canvasViewportSize;
    private Dictionary<string, object> _canvasPendingRequest;
    private ulong _canvasSentAt;
    private int _canvasSendCount;
    // Preview injection uses the very same protocol and UI, entirely in memory.
    private Action<Dictionary<string, object>> _canvasPreviewSend;

    private void InitializeLearningCanvas()
    {
        _learningCanvasPanel = new Panel { Name = "LearningCanvas", Visible = false, ZIndex = 99, ClipContents = true };
        _learningCanvasPanel.AddThemeStyleboxOverride("panel", MakeFlatStyle(ErisSurface, ErisBorder, 20, 1, 0, shadow: true));
        GetNode<Control>("CanvasLayer/Control").AddChild(_learningCanvasPanel);
        var margin = new MarginContainer();
        margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        foreach (string side in new[] { "left", "right", "top", "bottom" })
            margin.AddThemeConstantOverride("margin_" + side, 16);
        _learningCanvasPanel.AddChild(margin);
        var root = new VBoxContainer();
        root.AddThemeConstantOverride("separation", 10);
        margin.AddChild(root);
        var header = new HBoxContainer();
        root.AddChild(header);
        var heading = CanvasLabel("Learning Canvas", 22);
        heading.AutowrapMode = TextServer.AutowrapMode.Off;
        heading.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
        heading.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        header.AddChild(heading);
        var refresh = CreateMemoryButton("↻", () => SendLearningCanvasRequest("open"), primary: false);
        var close = CreateMemoryButton("×", CloseLearningCanvas, primary: false);
        refresh.CustomMinimumSize = close.CustomMinimumSize = new Vector2(34, 34);
        refresh.TooltipText = "Đồng bộ lại Canvas";
        close.TooltipText = "Đóng Canvas (Escape)";
        header.AddChild(refresh);
        header.AddChild(close);
        var subtitle = CanvasLabel("Dependency Injection · Java", 13, MemoryInkSoft);
        root.AddChild(subtitle);
        var modes = new HBoxContainer();
        root.AddChild(modes);
        _canvasMapToggle = CreateMemoryButton("Bản đồ", () => { _canvasShowMap = true; UpdateLearningCanvasColumns(); }, primary: false);
        _canvasReadToggle = CreateMemoryButton("Nội dung", () => { _canvasShowMap = false; UpdateLearningCanvasColumns(); }, primary: false);
        _canvasMapToggle.CustomMinimumSize = _canvasReadToggle.CustomMinimumSize = new Vector2(86, 34);
        modes.AddChild(_canvasMapToggle);
        modes.AddChild(_canvasReadToggle);
        _canvasPinLabel = CanvasLabel("", 11, MemoryInkSoft);
        _canvasPinLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        _canvasPinLabel.HorizontalAlignment = HorizontalAlignment.Right;
        modes.AddChild(_canvasPinLabel);
        InitializeLearningCanvasPlaybackUi(root);
        _canvasColumns = new HBoxContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill };
        _canvasColumns.AddThemeConstantOverride("separation", 20);
        root.AddChild(_canvasColumns);
        _canvasMapScroll = new ScrollContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill, HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled };
        _canvasDetailScroll = new ScrollContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill, HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled };
        _canvasColumns.AddChild(_canvasMapScroll);
        _canvasColumns.AddChild(_canvasDetailScroll);
        _canvasGraph = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        _canvasGraph.AddThemeConstantOverride("separation", 28);
        _canvasGraph.Draw += DrawLearningCanvasLinks;
        _canvasMapScroll.AddChild(_canvasGraph);
        _canvasDetail = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        _canvasDetail.AddThemeConstantOverride("separation", 14);
        _canvasDetailScroll.AddChild(_canvasDetail);
        _canvasStatus = CanvasLabel("Mở Canvas để tải nội dung học.", 11, MemoryInkSoft);
        root.AddChild(_canvasStatus);
        if (_contextLearningCanvasButton != null) _contextLearningCanvasButton.Pressed += ShowLearningCanvas;
        RenderLearningCanvas();
    }

    private static Label CanvasLabel(string text, int size, Color? color = null)
    {
        var label = new Label { Text = text, AutowrapMode = TextServer.AutowrapMode.WordSmart,
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        label.AddThemeColorOverride("font_color", color ?? MemoryInk);
        label.AddThemeFontSizeOverride("font_size", size);
        return label;
    }

    private void ShowLearningCanvas()
    {
        if (!_canvasPreview) CloseCharacterContextMenu();
        _learningCanvasPanel.Visible = true;
        UpdateLearningCanvasLayout();
        if (_canvasPendingRequest == null) SendLearningCanvasRequest("open");
    }

    private void CloseLearningCanvas() => _learningCanvasPanel.Visible = false;

    private void UpdateLearningCanvasLayout()
    {
        if (_learningCanvasPanel?.Visible != true) return;
        Vector2 viewport = GetViewportRect().Size;
        _canvasViewportSize = viewport;
        Vector2 size = new(Mathf.Max(0, Mathf.Min(1180, viewport.X - 24)), Mathf.Max(0, Mathf.Min(840, viewport.Y - 24)));
        _learningCanvasPanel.Size = size;
        _learningCanvasPanel.Position = (viewport - size) * 0.5f;
        _canvasNarrow = size.X < 950;
        _canvasMapScroll.CustomMinimumSize = new Vector2(_canvasNarrow ? 0 : 390, 0);
        _canvasDetailScroll.SizeFlagsStretchRatio = 1.5f;
        UpdateLearningCanvasColumns();
    }

    private void UpdateLearningCanvasColumns()
    {
        _canvasMapToggle.Visible = _canvasNarrow;
        _canvasReadToggle.Visible = _canvasNarrow;
        StyleCapabilityModeButton(_canvasMapToggle, _canvasShowMap);
        StyleCapabilityModeButton(_canvasReadToggle, !_canvasShowMap);
        _canvasMapScroll.Visible = !_canvasNarrow || _canvasShowMap;
        _canvasDetailScroll.Visible = !_canvasNarrow || !_canvasShowMap;
    }

    private static void CanvasClear(Control container)
    {
        foreach (Node child in container.GetChildren()) { container.RemoveChild(child); child.QueueFree(); }
    }

    private static string CanvasStateLabel(string state) => state switch
    {
        "learning" => "Đang học", "practicing" => "Đang luyện", "mastered" => "Đã vững", _ => "Có thể học"
    };

    private static Color CanvasStateColor(string state) => state switch
    {
        "learning" => new Color("fce6f1"), "practicing" => new Color("fff0cf"),
        "mastered" => new Color("dff1e9"), _ => new Color("f1edf8")
    };

    private IEnumerable<JsonElement> CanvasNodes() =>
        _canvasSnapshot.ValueKind == JsonValueKind.Object && _canvasSnapshot.TryGetProperty("nodes", out var nodes)
        && nodes.ValueKind == JsonValueKind.Array ? nodes.EnumerateArray().ToArray() : Array.Empty<JsonElement>();

    private void RenderLearningCanvas()
    {
        if (_canvasGraph == null) return;
        CanvasClear(_canvasGraph);
        _canvasNodeButtons.Clear();
        UpdateCanvasSpeakingChip();
        var nodes = CanvasNodes().ToArray();
        if (nodes.Length == 0)
        {
            _canvasGraph.AddChild(CanvasLabel("Chưa có nhóm kiến thức.\nBấm ↻ để thử tải lại.", 15, MemoryInkSoft));
            CanvasClear(_canvasDetail);
            _canvasDetail.AddChild(CanvasLabel("Chọn một nút để đọc giải thích và ví dụ Java.", 16));
            return;
        }
        foreach (var layer in nodes.GroupBy(n => n.GetProperty("level").GetInt32()).OrderBy(g => g.Key))
        {
            var level = new VBoxContainer();
            level.AddThemeConstantOverride("separation", 8);
            _canvasGraph.AddChild(level);
            level.AddChild(CanvasLabel($"TẦNG {layer.Key + 1}", 10, MemoryInkSoft));
            // One row per DAG level, prerequisite links drawn in the gaps.
            var row = new HBoxContainer();
            row.AddThemeConstantOverride("separation", 8);
            level.AddChild(row);
            foreach (var node in layer)
            {
                string id = ReadJsonString(node, "id"), state = ReadJsonString(node, "state");
                bool selected = id == _canvasSelectedNode;
                var button = new Button { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
                    CustomMinimumSize = new Vector2(0, 112), ClipContents = true,
                    TooltipText = ReadJsonString(node, "title"), ToggleMode = true, ButtonPressed = selected };
                var style = MakeFlatStyle(CanvasStateColor(state), selected ? MemoryPink : ErisBorder, 12, selected ? 2 : 1, 0);
                foreach (string kind in new[] { "normal", "hover", "pressed", "hover_pressed" }) button.AddThemeStyleboxOverride(kind, style);
                row.AddChild(button);
                var textMargin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
                textMargin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
                foreach (string side in new[] { "left", "right", "top", "bottom" }) textMargin.AddThemeConstantOverride("margin_" + side, 10);
                button.AddChild(textMargin);
                string due = node.GetProperty("due").GetBoolean() ? " · Đến hạn ôn" : "";
                string suggested = _canvasSnapshot.TryGetProperty("focus", out var focus) ? ReadJsonString(focus, "suggested_node_id") : "";
                int resultCount = node.TryGetProperty("result_count", out var count) ? count.GetInt32() : 0;
                var title = CanvasLabel(ReadJsonString(node, "title") + "\n" + CanvasStateLabel(state) + due
                    + (suggested == id ? "\nEris gợi ý →" : "") + (resultCount > 0 ? $"\nCó {resultCount} kết quả" : ""), 13);
                textMargin.AddChild(title);
                title.Resized += () => button.CustomMinimumSize = new Vector2(0, Mathf.Max(112, title.GetMinimumSize().Y + 20));
                button.Pressed += () => SelectLearningCanvasNode(id);
                _canvasNodeButtons[id] = button;
            }
        }
        RenderLearningCanvasDetail();
        _canvasGraph.QueueRedraw();
    }

    private void DrawLearningCanvasLinks()
    {
        foreach (var node in CanvasNodes())
        {
            if (!_canvasNodeButtons.TryGetValue(ReadJsonString(node, "id"), out var target)) continue;
            foreach (var prerequisite in node.GetProperty("prerequisites").EnumerateArray())
            {
                if (!_canvasNodeButtons.TryGetValue(prerequisite.GetString() ?? "", out var source)) continue;
                Vector2 a = source.GlobalPosition + new Vector2(source.Size.X / 2, source.Size.Y) - _canvasGraph.GlobalPosition;
                Vector2 b = target.GlobalPosition + new Vector2(target.Size.X / 2, 0) - _canvasGraph.GlobalPosition;
                _canvasGraph.DrawLine(a, b, MemoryPink, 1.5f, true);
                _canvasGraph.DrawCircle(b, 3, MemoryPink);
            }
        }
    }

    private string CanvasNodeTitle(string id) => CanvasNodes().Where(n => ReadJsonString(n, "id") == id)
        .Select(n => ReadJsonString(n, "title")).FirstOrDefault() ?? id;

    private void RenderLearningCanvasDetail()
    {
        CanvasClear(_canvasDetail);
        _canvasBlockControls.Clear();
        _canvasDetail.AddChild(CanvasLabel(CanvasNodeTitle(_canvasSelectedNode), 24));
        var summaryNode = CanvasNodes().FirstOrDefault(n => ReadJsonString(n, "id") == _canvasSelectedNode);
        if (summaryNode.ValueKind == JsonValueKind.Object)
        {
            var warnings = summaryNode.GetProperty("prerequisite_warnings").EnumerateArray().Select(p => CanvasNodeTitle(p.GetString() ?? "")).ToArray();
            if (warnings.Length > 0) _canvasDetail.AddChild(CanvasLabel("Nên ôn trước: " + string.Join(", ", warnings) + ". Bạn vẫn có thể đọc nút này.", 12, new Color("8a5a22")));
        }
        if (!_canvasDetailCache.TryGetValue(_canvasSelectedNode, out var detail))
        {
            _canvasDetail.AddChild(CanvasLabel("Đang tải nội dung…", 14, MemoryInkSoft));
            return;
        }
        _canvasDetail.AddChild(CanvasLabel(ReadJsonString(detail, "summary"), 14, MemoryInkSoft));
        foreach (var block in detail.GetProperty("blocks").EnumerateArray())
        {
            var card = new PanelContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
            _canvasBlockControls[ReadJsonString(block, "id")] = card;
            _canvasDetail.AddChild(card);
            var content = new VBoxContainer();
            content.AddThemeConstantOverride("separation", 8);
            card.AddChild(content);
            content.AddChild(CanvasLabel(ReadJsonString(block, "title"), 17));
            string text = ReadJsonString(block, "text");
            if (ReadJsonString(block, "kind") == "java")
            {
                var code = new RichTextLabel { Text = text, BbcodeEnabled = false, FitContent = true,
                    ScrollActive = false, SelectionEnabled = true, CustomMinimumSize = new Vector2(0, 50),
                    SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, AutowrapMode = TextServer.AutowrapMode.WordSmart };
                code.AddThemeFontOverride("normal_font", new SystemFont { FontNames = new[] { "Consolas", "Cascadia Mono", "monospace" } });
                code.AddThemeFontSizeOverride("normal_font_size", 13);
                code.AddThemeColorOverride("default_color", MemoryInk);
                code.AddThemeStyleboxOverride("normal", MakeFlatStyle(new Color("f4f1f8"), ErisBorder, 10, 1, 12));
                content.AddChild(code);
            }
            else content.AddChild(CanvasLabel(text, 15));
        }
        if (_canvasSnapshot.TryGetProperty("late_results", out var results) && results.ValueKind == JsonValueKind.Array)
            foreach (var result in results.EnumerateArray())
                _canvasDetail.AddChild(CanvasLabel("Kết quả đã có · " + ReadJsonString(result, "summary"), 13, MemoryInkSoft));
        UpdateCanvasBlockHighlight();
        RenderLearningCanvasExercises(detail);
    }

    private void SelectLearningCanvasNode(string nodeId)
    {
        if (!CanvasNodes().Any(n => ReadJsonString(n, "id") == nodeId)) return;
        _canvasSelectedNode = _canvasDesiredNode = nodeId;
        _canvasShowMap = false;
        _canvasDetailScroll.ScrollVertical = 0;
        RenderLearningCanvas();
        UpdateLearningCanvasColumns();
        FlushLearningCanvasNavigation();
    }

    private void FlushLearningCanvasNavigation()
    {
        if (_canvasPendingRequest != null || _canvasDesiredNode == "" || _canvasRevision < 0) return;
        SendLearningCanvasRequest("navigate", _canvasDesiredNode);
    }

    private void SendLearningCanvasRequest(string action, string nodeId = "", string causeId = "", Dictionary<string, object> extra = null)
    {
        if (_canvasPendingRequest != null) return;
        var request = new Dictionary<string, object> { ["type"] = "learning_canvas_request", ["action"] = action,
            ["group_id"] = "java-di", ["request_id"] = "canvas-" + Guid.NewGuid().ToString("N") };
        if (nodeId != "") request["node_id"] = nodeId;
        if (causeId != "") request["cause_id"] = causeId;
        if (action != "open") request["base_revision"] = _canvasRevision;
        if (extra != null) foreach (var pair in extra) request[pair.Key] = pair.Value;
        _canvasPendingRequest = request;
        _canvasSendCount = 0;
        TransmitLearningCanvasRequest();
    }

    private void TransmitLearningCanvasRequest()
    {
        _canvasSentAt = Time.GetTicksMsec();
        _canvasSendCount++;
        _canvasStatus.Text = "Đang đồng bộ…";
        if (_canvasPreview) { _canvasPreviewSend?.Invoke(new Dictionary<string, object>(_canvasPendingRequest)); return; }
        if (_chatSend == null || _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(_canvasPendingRequest))) != Error.Ok)
            _canvasStatus.Text = "Chưa kết nối được backend. Đang thử lại…";
    }

    private bool TryHandleLearningCanvasPacket(string raw)
    {
        try
        {
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            string type = ReadJsonString(root, "type");
            if (type is "canvas_highlight" or "canvas_playback") { ApplyLearningCanvasPlayback(root); return true; }
            if (type != "learning_canvas_ack" && type != "learning_canvas_state") return false;
            bool ack = type == "learning_canvas_ack";
            if (ack && (_canvasPendingRequest == null || ReadJsonString(root, "request_id") != (string)_canvasPendingRequest["request_id"])) return true;
            string action = ack ? (string)_canvasPendingRequest["action"] : "";
            string requestedNode = ack && _canvasPendingRequest.TryGetValue("node_id", out var id) ? (string)id : "";
            if (ack) _canvasPendingRequest = null;
            string status = ReadJsonString(root, "status");
            if (root.TryGetProperty("exercise_update", out var exerciseUpdate)) ApplyLearningCanvasExercise(exerciseUpdate);
            if (root.TryGetProperty("learning_canvas", out var snapshot) && snapshot.ValueKind == JsonValueKind.Object
                && ReadJsonString(snapshot, "schema") == "eris.learning.canvas.v1")
            {
                var focus = snapshot.GetProperty("focus");
                long revision = focus.GetProperty("revision").GetInt64();
                if (revision >= _canvasRevision)
                {
                    _canvasSnapshot = snapshot.Clone();
                    ObserveCanvasPlaybackStream(ReadJsonString(snapshot, "playback_stream_id"));
                    if (snapshot.TryGetProperty("playback", out var playback)) ApplyLearningCanvasPlayback(playback);
                    if (snapshot.TryGetProperty("activity", out var activity)) ApplyLearningCanvasExercise(activity);
                    _canvasRevision = revision;
                    if (snapshot.TryGetProperty("detail", out var detail) && detail.ValueKind == JsonValueKind.Object)
                        _canvasDetailCache[ReadJsonString(detail, "id")] = detail.Clone();
                    if (ack && status == "ok" && action == "navigate" && requestedNode == _canvasDesiredNode)
                        _canvasDesiredNode = "";
                    if (ack && status is "error" or "unavailable") _canvasDesiredNode = "";
                    _canvasSelectedNode = _canvasDesiredNode != "" ? _canvasDesiredNode : ReadJsonString(focus, "node_id");
                    _canvasPinLabel.Text = focus.GetProperty("pinned").GetBoolean() ? "Đã ghim" : "Theo Eris";
                    RenderLearningCanvas();
                    if (_canvasDeferredPlayback.ValueKind == JsonValueKind.Object)
                    {
                        var deferred = _canvasDeferredPlayback;
                        _canvasDeferredPlayback = default;
                        ApplyLearningCanvasPlayback(deferred);
                    }
                    // Applying an Eris state is an acknowledgment, never navigate.
                    string cause = ReadJsonString(focus, "cause_id");
                    if (!ack && _canvasPendingRequest == null && _canvasDesiredNode == "" && cause != ""
                        && cause != ReadJsonString(focus, "acknowledged_cause_id"))
                    {
                        SendLearningCanvasRequest("ack_eris_focus", causeId: cause);
                    }
                }
            }
            if (!ack && root.TryGetProperty("open_panel", out var openPanel) && openPanel.ValueKind == JsonValueKind.True)
            {
                _learningCanvasPanel.Visible = true;
                UpdateLearningCanvasLayout();
            }
            if (ack && status is "error" or "unavailable")
            {
                _canvasDesiredNode = "";
                if (_canvasSnapshot.ValueKind == JsonValueKind.Object)
                {
                    _canvasSelectedNode = ReadJsonString(_canvasSnapshot.GetProperty("focus"), "node_id");
                    RenderLearningCanvas();
                }
            }
            _canvasStatus.Text = status == "ok" ? "Đã đồng bộ · Tiến độ dựa trên bài làm" : ReadJsonString(root, "message");
            if (ack && status is "ok" or "conflict") FlushLearningCanvasNavigation();
            return true;
        }
        catch (JsonException) { return false; }
        catch (InvalidOperationException) { return false; }
        catch (KeyNotFoundException) { return false; }
    }

    private void TickLearningCanvas()
    {
        TickLearningCanvasExercise();
        if (_learningCanvasPanel?.Visible == true)
        {
            if (_canvasViewportSize != GetViewportRect().Size) UpdateLearningCanvasLayout();
            _canvasGraph.QueueRedraw();
        }
        if (_canvasPendingRequest == null || Time.GetTicksMsec() - _canvasSentAt < 900) return;
        if (_canvasSendCount < 3) { TransmitLearningCanvasRequest(); return; }
        _canvasPendingRequest = null;
        _canvasDesiredNode = "";
        if (_canvasSnapshot.ValueKind == JsonValueKind.Object)
        {
            _canvasSelectedNode = ReadJsonString(_canvasSnapshot.GetProperty("focus"), "node_id");
            RenderLearningCanvas();
        }
        _canvasStatus.Text = "Chưa nhận được xác nhận. Bấm ↻ để đồng bộ lại.";
    }
}
