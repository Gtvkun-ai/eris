using Godot;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.Json;

public partial class UdpListener
{
    // Agent Console là control surface cho executor (Gemini/Codex/...). Nó chỉ
    // render typed events từ Brain; tuyệt đối không parse log để đoán Agent đang làm gì.
    private sealed class AgentConsoleEventView
    {
        public string EventId { get; set; } = "";
        public string Type { get; set; } = "";
        public string Actor { get; set; } = "system";
        public string Summary { get; set; } = "";
        public string Detail { get; set; } = "";
        public string DataText { get; set; } = "";
        public int Step { get; set; }
        public float Importance { get; set; }
        public double CreatedAt { get; set; }
    }

    private sealed class AgentConsoleTaskView
    {
        public string TaskId { get; set; } = "";
        public string Goal { get; set; } = "";
        public string ClarifiedGoal { get; set; } = "";
        public string Status { get; set; } = "queued";
        public string Executor { get; set; } = "gemini";
        public string Model { get; set; } = "";
        public int CurrentStep { get; set; }
        public int PendingControls { get; set; }
        public string CheckpointId { get; set; } = "";
        public int CheckpointCount { get; set; }
        public int TestsPassed { get; set; }
        public int TestsFailed { get; set; }
        public string TestsSummary { get; set; } = "";
        public List<string> ActiveSkills { get; set; } = new();
        public List<string> ChangedFiles { get; set; } = new();
        public List<AgentConsoleEventView> Events { get; set; } = new();
        public double UpdatedAt { get; set; }
    }

    private static readonly Vector2 AgentConsolePreferredSize = new(1280f, 760f);
    private static readonly Vector2 AgentConsoleMinimumSize = new(980f, 620f);
    private static readonly Color AgentConsoleBg = new(1.00f, 0.985f, 0.992f, 0.995f);
    private static readonly Color AgentConsoleCard = new(1.00f, 0.998f, 1.00f, 0.96f);
    private static readonly Color AgentConsoleBorder = new(0.94f, 0.84f, 0.89f, 0.95f);
    private static readonly Color AgentConsoleInk = new(0.29f, 0.13f, 0.21f, 1f);
    private static readonly Color AgentConsoleMuted = new(0.56f, 0.42f, 0.49f, 1f);
    private static readonly Color AgentConsolePink = new(0.91f, 0.29f, 0.56f, 1f);
    private static readonly Color AgentConsoleGreen = new(0.24f, 0.56f, 0.40f, 1f);
    private static readonly Color AgentConsoleGold = new(0.78f, 0.52f, 0.16f, 1f);
    private static readonly Color AgentConsoleBlue = new(0.27f, 0.47f, 0.76f, 1f);
    private static readonly Color AgentConsoleRed = new(0.75f, 0.18f, 0.28f, 1f);

    private Button _contextAgentConsoleButton;
    private Panel _agentConsolePanel;
    private Label _agentConsoleStatusLabel;
    private Label _agentConsoleExecutorLabel;
    private Label _agentConsoleTaskTitleLabel;
    private Label _agentConsoleTaskMetaLabel;
    private VBoxContainer _agentConsoleTaskList;
    private VBoxContainer _agentConsoleEventList;
    private ScrollContainer _agentConsoleEventScroll;
    private Label _agentConsoleInspectorLabel;
    private Label _agentConsoleInspectorDetailLabel;
    private Label _agentConsoleControlStatusLabel;
    private LineEdit _agentConsoleDirectiveInput;
    private Button _agentConsolePauseButton;
    private Button _agentConsoleResumeButton;
    private Button _agentConsoleStopButton;
    private Button _agentConsoleRollbackButton;
    private readonly List<AgentConsoleTaskView> _agentConsoleTasks = new();
    private string _agentSelectedTaskId = "";
    private string _agentLastRequestId = "";
    private ulong _agentLastSnapshotRequestMs;
    private ulong _agentLastPacketMs;

    private void BuildAgentConsoleUi()
    {
        if (_agentConsolePanel != null)
            return;

        _agentConsolePanel = new Panel
        {
            Name = "AgentConsolePanel",
            Visible = false,
            CustomMinimumSize = AgentConsoleMinimumSize,
            Size = AgentConsolePreferredSize,
            ZIndex = 100,
            ClipContents = true,
        };
        _agentConsolePanel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            AgentConsoleBg, AgentConsoleBorder, 22, 1, shadow: true));
        GetNode<Control>("CanvasLayer/Control").AddChild(_agentConsolePanel);

        var margin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        margin.AddThemeConstantOverride("margin_left", 16);
        margin.AddThemeConstantOverride("margin_right", 16);
        margin.AddThemeConstantOverride("margin_top", 14);
        margin.AddThemeConstantOverride("margin_bottom", 14);
        _agentConsolePanel.AddChild(margin);

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 10);
        margin.AddChild(root);

        root.AddChild(BuildAgentConsoleHeader());
        root.AddChild(BuildAgentConsoleBody());
        root.AddChild(BuildAgentConsoleFooter());
        RefreshAgentConsole();
    }

    private Control BuildAgentConsoleHeader()
    {
        var row = new HBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 58f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 10);

        var titles = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        titles.AddThemeConstantOverride("separation", 1);
        titles.AddChild(AgentConsoleLabel("Agent Console", 23, AgentConsoleInk, bold: true));
        _agentConsoleTaskMetaLabel = AgentConsoleLabel(
            "Gemini / LangGraph execution stream · không hiển thị raw chain-of-thought",
            11,
            AgentConsoleMuted);
        titles.AddChild(_agentConsoleTaskMetaLabel);
        row.AddChild(titles);

        _agentConsoleExecutorLabel = AgentConsoleChip("EXECUTOR · —", AgentConsoleBlue);
        row.AddChild(_agentConsoleExecutorLabel);
        _agentConsoleStatusLabel = AgentConsoleChip("IDLE", AgentConsoleMuted);
        row.AddChild(_agentConsoleStatusLabel);

        var refresh = AgentConsoleButton("Đọc lại", () => SendAgentControl("snapshot"), primary: false);
        refresh.CustomMinimumSize = new Vector2(82f, 32f);
        row.AddChild(refresh);

        var close = CreateWindowControlButton("x", CloseAgentConsolePanel, 32f, 13);
        close.TooltipText = "Đóng Agent Console";
        row.AddChild(close);
        return row;
    }

    private Control BuildAgentConsoleBody()
    {
        var body = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        body.AddThemeConstantOverride("separation", 10);

        body.AddChild(BuildAgentTaskPane());
        body.AddChild(BuildAgentStreamPane());
        body.AddChild(BuildAgentInspectorPane());
        return body;
    }

    private Control BuildAgentTaskPane()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(238f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(1f, 0.97f, 0.985f, 0.88f), AgentConsoleBorder, 16, 1));

        var margin = AgentConsoleMargin(12, 12, 12, 12);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 8);
        margin.AddChild(box);

        box.AddChild(AgentConsoleLabel("TASKS", 10, AgentConsolePink, bold: true));
        var hint = AgentConsoleLabel("Chọn task để xem timeline và checkpoint.", 10, AgentConsoleMuted);
        hint.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(hint);

        var scroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
        };
        box.AddChild(scroll);
        _agentConsoleTaskList = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _agentConsoleTaskList.AddThemeConstantOverride("separation", 7);
        scroll.AddChild(_agentConsoleTaskList);
        return panel;
    }

    private Control BuildAgentStreamPane()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(420f, 0f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(AgentConsoleCard, AgentConsoleBorder, 16, 1));
        var margin = AgentConsoleMargin(14, 12, 14, 12);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 8);
        margin.AddChild(box);

        _agentConsoleTaskTitleLabel = AgentConsoleLabel("Chưa có task", 16, AgentConsoleInk, bold: true);
        _agentConsoleTaskTitleLabel.ClipText = true;
        _agentConsoleTaskTitleLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
        box.AddChild(_agentConsoleTaskTitleLabel);

        _agentConsoleEventScroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
        };
        box.AddChild(_agentConsoleEventScroll);
        _agentConsoleEventList = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _agentConsoleEventList.AddThemeConstantOverride("separation", 8);
        _agentConsoleEventScroll.AddChild(_agentConsoleEventList);
        return panel;
    }

    private Control BuildAgentInspectorPane()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(286f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.985f, 0.99f, 1f, 0.92f), new Color(0.83f, 0.87f, 0.95f, 0.94f), 16, 1));
        var margin = AgentConsoleMargin(12, 12, 12, 12);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 8);
        margin.AddChild(box);
        box.AddChild(AgentConsoleLabel("INSPECTOR", 10, AgentConsoleBlue, bold: true));

        _agentConsoleInspectorLabel = AgentConsoleLabel("Chọn một task hoặc event.", 12, AgentConsoleInk, bold: true);
        _agentConsoleInspectorLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(_agentConsoleInspectorLabel);

        var scroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
        };
        box.AddChild(scroll);
        _agentConsoleInspectorDetailLabel = AgentConsoleLabel("", 11, AgentConsoleMuted);
        _agentConsoleInspectorDetailLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        _agentConsoleInspectorDetailLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        scroll.AddChild(_agentConsoleInspectorDetailLabel);
        return panel;
    }

    private Control BuildAgentConsoleFooter()
    {
        var root = new VBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 82f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 6);

        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 7);
        _agentConsolePauseButton = AgentConsoleButton("Tạm dừng", () => SendAgentControl("pause"), primary: false);
        _agentConsoleResumeButton = AgentConsoleButton("Tiếp tục", () => SendAgentControl("resume"), primary: false);
        _agentConsoleStopButton = AgentConsoleButton("Dừng", () => SendAgentControl("stop"), primary: false, danger: true);
        _agentConsoleRollbackButton = AgentConsoleButton("Rollback", () => SendAgentControl("rollback", checkpointId: SelectedAgentTask()?.CheckpointId ?? ""), primary: false);
        row.AddChild(_agentConsolePauseButton);
        row.AddChild(_agentConsoleResumeButton);
        row.AddChild(_agentConsoleStopButton);
        row.AddChild(_agentConsoleRollbackButton);

        _agentConsoleDirectiveInput = new LineEdit
        {
            PlaceholderText = "Nhắn chỉ thị cho task, ví dụ: đừng tạo abstraction mới; tận dụng registry cũ",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            ClearButtonEnabled = true,
        };
        StyleAgentConsoleInput(_agentConsoleDirectiveInput);
        _agentConsoleDirectiveInput.TextSubmitted += _ => SendAgentDirective();
        row.AddChild(_agentConsoleDirectiveInput);
        var send = AgentConsoleButton("Gửi chỉ thị", SendAgentDirective, primary: true);
        send.CustomMinimumSize = new Vector2(104f, 34f);
        row.AddChild(send);
        root.AddChild(row);

        _agentConsoleControlStatusLabel = AgentConsoleLabel("Panel sẵn sàng.", 10, AgentConsoleMuted);
        root.AddChild(_agentConsoleControlStatusLabel);
        return root;
    }

    private void OnContextAgentConsolePressed()
    {
        _bodyAutonomy?.RecordUserInteraction();
        CloseCharacterContextMenu();
        if (_agentConsolePanel == null)
            return;
        if (_agentConsolePanel.Visible)
            CloseAgentConsolePanel();
        else
            ShowAgentConsolePanel();
    }

    private void ShowAgentConsolePanel()
    {
        if (_agentConsolePanel == null)
            return;
        Vector2 viewport = GetViewportRect().Size;
        Vector2 target = new(
            Mathf.Clamp(viewport.X - 100f, AgentConsoleMinimumSize.X, AgentConsolePreferredSize.X),
            Mathf.Clamp(viewport.Y - 90f, AgentConsoleMinimumSize.Y, AgentConsolePreferredSize.Y));
        _agentConsolePanel.Size = target;
        _agentConsolePanel.Position = new Vector2(
            Mathf.Max(12f, (viewport.X - target.X) * 0.5f),
            Mathf.Max(12f, (viewport.Y - target.Y) * 0.5f));
        _agentConsolePanel.Visible = true;
        _agentConsolePanel.MoveToFront();
        RefreshAgentConsole();
        SendAgentControl("snapshot");
        UpdateMousePassthrough();
    }

    private void CloseAgentConsolePanel()
    {
        if (_agentConsolePanel == null)
            return;
        if (_draggingPanel == _agentConsolePanel)
            _draggingPanel = null;
        _agentConsolePanel.Visible = false;
        UpdateMousePassthrough();
    }

    private void TickAgentConsole()
    {
        if (_agentConsolePanel == null || !_agentConsolePanel.Visible)
            return;
        ulong now = Time.GetTicksMsec();
        if (now - _agentLastSnapshotRequestMs >= 2200)
            SendAgentControl("snapshot", quiet: true);

        // Nếu Brain không phản hồi, nói thẳng là stale thay vì giả trạng thái "running".
        if (_agentLastPacketMs > 0 && now - _agentLastPacketMs > 9000 && _agentConsoleControlStatusLabel != null)
        {
            _agentConsoleControlStatusLabel.Text = "Agent stream chưa có packet mới trong 9 giây.";
            _agentConsoleControlStatusLabel.AddThemeColorOverride("font_color", AgentConsoleGold);
        }
    }

    private void SendAgentDirective()
    {
        string text = (_agentConsoleDirectiveInput?.Text ?? "").Trim();
        if (string.IsNullOrWhiteSpace(text))
        {
            SetAgentConsoleControlStatus("Chỉ thị đang trống.", error: true);
            return;
        }
        SendAgentControl("directive", text: text);
        if (_agentConsoleDirectiveInput != null)
            _agentConsoleDirectiveInput.Text = "";
    }

    private void SendAgentControl(string action, string text = "", string checkpointId = "", bool quiet = false)
    {
        if (_chatSend == null)
            return;
        if (action != "snapshot" && string.IsNullOrWhiteSpace(_agentSelectedTaskId))
        {
            SetAgentConsoleControlStatus("Chưa chọn task để điều khiển.", error: true);
            return;
        }

        _agentLastRequestId = $"agent-{Time.GetTicksMsec()}-{GD.Randi()}";
        var payload = new Dictionary<string, object>
        {
            ["type"] = "agent_control",
            ["action"] = action,
            ["request_id"] = _agentLastRequestId,
            ["task_id"] = _agentSelectedTaskId,
            ["selected_task_id"] = _agentSelectedTaskId,
        };
        if (!string.IsNullOrWhiteSpace(text))
            payload["text"] = text;
        if (!string.IsNullOrWhiteSpace(checkpointId))
            payload["checkpoint_id"] = checkpointId;

        Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
        if (error != Error.Ok)
        {
            SetAgentConsoleControlStatus($"Không gửi được Agent control: {error}", error: true);
            return;
        }
        _agentLastSnapshotRequestMs = Time.GetTicksMsec();
        if (!quiet)
            SetAgentConsoleControlStatus(action == "snapshot" ? "Đang đồng bộ task..." : $"Đã gửi {action}; chờ AgentHarness nhận ở node boundary.");
    }

    private bool TryHandleAgentConsolePacket(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)
            || (raw.IndexOf("agent_event", StringComparison.Ordinal) < 0
                && raw.IndexOf("agent_console_ack", StringComparison.Ordinal) < 0))
            return false;
        try
        {
            using JsonDocument doc = JsonDocument.Parse(raw);
            JsonElement root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("type", out JsonElement typeNode))
                return false;
            string type = typeNode.GetString() ?? "";
            if (type == "agent_event")
            {
                if (!root.TryGetProperty("agent", out JsonElement agent) || agent.ValueKind != JsonValueKind.Object)
                    return true;
                AgentConsoleTaskView task = null;
                if (agent.TryGetProperty("task", out JsonElement taskNode) && taskNode.ValueKind == JsonValueKind.Object)
                    task = UpsertAgentTask(taskNode, replaceEvents: false);
                if (agent.TryGetProperty("event", out JsonElement eventNode) && eventNode.ValueKind == JsonValueKind.Object)
                {
                    AgentConsoleEventView ev = ParseAgentEvent(eventNode);
                    if (task != null && ev != null && !AgentEventAlreadyExists(task, ev.EventId))
                        task.Events.Add(ev);
                }
                _agentLastPacketMs = Time.GetTicksMsec();
                RefreshAgentConsole();
                CallDeferred(nameof(ScrollAgentConsoleToBottom));
                return true;
            }
            if (type != "agent_console_ack")
                return false;

            _agentLastPacketMs = Time.GetTicksMsec();
            string status = AgentReadJsonString(root, "status");
            string message = AgentReadJsonString(root, "message");
            if (root.TryGetProperty("agent_console", out JsonElement console) && console.ValueKind == JsonValueKind.Object)
                ApplyAgentConsoleSnapshot(console);
            SetAgentConsoleControlStatus(
                string.IsNullOrWhiteSpace(message) ? "Agent Console đã đồng bộ." : message,
                error: status == "error");
            RefreshAgentConsole();
            CallDeferred(nameof(ScrollAgentConsoleToBottom));
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
        catch (Exception ex)
        {
            SetAgentConsoleControlStatus($"Không đọc được Agent packet: {ex.Message}", error: true);
            return true;
        }
    }

    private void ApplyAgentConsoleSnapshot(JsonElement console)
    {
        string selected = AgentReadJsonString(console, "selected_task_id");
        _agentConsoleTasks.Clear();
        if (console.TryGetProperty("tasks", out JsonElement tasks) && tasks.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement taskNode in tasks.EnumerateArray())
            {
                if (taskNode.ValueKind != JsonValueKind.Object)
                    continue;
                AgentConsoleTaskView task = ParseAgentTask(taskNode);
                if (task != null)
                    _agentConsoleTasks.Add(task);
            }
        }
        if (!string.IsNullOrWhiteSpace(selected))
            _agentSelectedTaskId = selected;
        if (string.IsNullOrWhiteSpace(_agentSelectedTaskId) && _agentConsoleTasks.Count > 0)
            _agentSelectedTaskId = _agentConsoleTasks[0].TaskId;
        if (SelectedAgentTask() == null && _agentConsoleTasks.Count > 0)
            _agentSelectedTaskId = _agentConsoleTasks[0].TaskId;
    }

    private AgentConsoleTaskView UpsertAgentTask(JsonElement node, bool replaceEvents)
    {
        string taskId = AgentReadJsonString(node, "task_id");
        if (string.IsNullOrWhiteSpace(taskId))
            return null;
        AgentConsoleTaskView existing = FindAgentTask(taskId);
        AgentConsoleTaskView parsed = ParseAgentTask(node);
        if (parsed == null)
            return existing;
        if (existing == null)
        {
            _agentConsoleTasks.Insert(0, parsed);
            if (string.IsNullOrWhiteSpace(_agentSelectedTaskId))
                _agentSelectedTaskId = parsed.TaskId;
            return parsed;
        }

        List<AgentConsoleEventView> oldEvents = existing.Events;
        CopyAgentTaskProjection(existing, parsed);
        if (replaceEvents || parsed.Events.Count > 0)
            existing.Events = parsed.Events;
        else
            existing.Events = oldEvents;
        return existing;
    }

    private static void CopyAgentTaskProjection(AgentConsoleTaskView target, AgentConsoleTaskView source)
    {
        target.Goal = source.Goal;
        target.ClarifiedGoal = source.ClarifiedGoal;
        target.Status = source.Status;
        target.Executor = source.Executor;
        target.Model = source.Model;
        target.CurrentStep = source.CurrentStep;
        target.PendingControls = source.PendingControls;
        target.CheckpointId = source.CheckpointId;
        target.CheckpointCount = source.CheckpointCount;
        target.TestsPassed = source.TestsPassed;
        target.TestsFailed = source.TestsFailed;
        target.TestsSummary = source.TestsSummary;
        target.ActiveSkills = source.ActiveSkills;
        target.ChangedFiles = source.ChangedFiles;
        target.UpdatedAt = source.UpdatedAt;
    }

    private AgentConsoleTaskView ParseAgentTask(JsonElement node)
    {
        string taskId = AgentReadJsonString(node, "task_id");
        if (string.IsNullOrWhiteSpace(taskId))
            return null;
        var task = new AgentConsoleTaskView
        {
            TaskId = taskId,
            Goal = AgentReadJsonString(node, "goal"),
            ClarifiedGoal = AgentReadJsonString(node, "clarified_goal"),
            Status = AgentReadJsonString(node, "status"),
            Executor = AgentReadJsonString(node, "executor"),
            Model = AgentReadJsonString(node, "model"),
            CurrentStep = AgentReadJsonInt(node, "current_step"),
            PendingControls = AgentReadJsonInt(node, "pending_controls"),
            CheckpointId = AgentReadJsonString(node, "checkpoint_id"),
            CheckpointCount = AgentReadJsonInt(node, "checkpoint_count"),
            UpdatedAt = AgentReadJsonDouble(node, "updated_at"),
        };
        if (string.IsNullOrWhiteSpace(task.Status)) task.Status = "queued";
        if (string.IsNullOrWhiteSpace(task.Executor)) task.Executor = "executor";

        if (node.TryGetProperty("active_skills", out JsonElement skills) && skills.ValueKind == JsonValueKind.Array)
            foreach (JsonElement item in skills.EnumerateArray())
                if (item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString()))
                    task.ActiveSkills.Add(item.GetString());
        if (node.TryGetProperty("changed_files", out JsonElement files) && files.ValueKind == JsonValueKind.Array)
            foreach (JsonElement item in files.EnumerateArray())
                if (item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString()))
                    task.ChangedFiles.Add(item.GetString());
        if (node.TryGetProperty("tests", out JsonElement tests) && tests.ValueKind == JsonValueKind.Object)
        {
            task.TestsPassed = AgentReadJsonInt(tests, "passed");
            task.TestsFailed = AgentReadJsonInt(tests, "failed");
            task.TestsSummary = AgentReadJsonString(tests, "summary");
        }
        if (node.TryGetProperty("events", out JsonElement events) && events.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement eventNode in events.EnumerateArray())
            {
                AgentConsoleEventView ev = ParseAgentEvent(eventNode);
                if (ev != null)
                    task.Events.Add(ev);
            }
        }
        return task;
    }

    private AgentConsoleEventView ParseAgentEvent(JsonElement node)
    {
        if (node.ValueKind != JsonValueKind.Object)
            return null;
        var ev = new AgentConsoleEventView
        {
            EventId = AgentReadJsonString(node, "event_id"),
            Type = AgentReadJsonString(node, "type"),
            Actor = AgentReadJsonString(node, "actor"),
            Summary = AgentReadJsonString(node, "summary"),
            Detail = AgentReadJsonString(node, "detail"),
            Step = AgentReadJsonInt(node, "step"),
            Importance = (float)AgentReadJsonDouble(node, "importance"),
            CreatedAt = AgentReadJsonDouble(node, "created_at"),
        };
        if (string.IsNullOrWhiteSpace(ev.Actor)) ev.Actor = "system";
        if (string.IsNullOrWhiteSpace(ev.Type)) ev.Type = "agent_status";
        if (node.TryGetProperty("data", out JsonElement data) && data.ValueKind == JsonValueKind.Object)
            ev.DataText = CompactAgentData(data);
        return ev;
    }

    private static bool AgentEventAlreadyExists(AgentConsoleTaskView task, string eventId)
    {
        if (task == null || string.IsNullOrWhiteSpace(eventId))
            return false;
        foreach (AgentConsoleEventView ev in task.Events)
            if (string.Equals(ev.EventId, eventId, StringComparison.Ordinal))
                return true;
        return false;
    }

    private void RefreshAgentConsole()
    {
        if (_agentConsoleTaskList == null || _agentConsoleEventList == null)
            return;
        RebuildAgentTaskList();
        RebuildAgentEventStream();
        RefreshAgentInspectorForTask();
        RefreshAgentConsoleControls();
    }

    private void RebuildAgentTaskList()
    {
        ClearAgentChildren(_agentConsoleTaskList);
        if (_agentConsoleTasks.Count == 0)
        {
            var empty = AgentConsoleLabel("Chưa có task Agent nào. Khi LangGraph bắt đầu execute, task sẽ xuất hiện ở đây.", 11, AgentConsoleMuted);
            empty.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            _agentConsoleTaskList.AddChild(empty);
            return;
        }

        foreach (AgentConsoleTaskView task in _agentConsoleTasks)
        {
            AgentConsoleTaskView captured = task;
            bool selected = string.Equals(task.TaskId, _agentSelectedTaskId, StringComparison.Ordinal);
            var button = new Button
            {
                Text = $"{AgentStatusGlyph(task.Status)}  {CompactAgentText(task.Goal, 42)}\n{AgentStatusLabel(task.Status)} · step {task.CurrentStep}",
                CustomMinimumSize = new Vector2(0f, 60f),
                SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
                Alignment = HorizontalAlignment.Left,
                FocusMode = Control.FocusModeEnum.None,
                MouseDefaultCursorShape = Control.CursorShape.PointingHand,
            };
            button.AddThemeFontSizeOverride("font_size", 11);
            button.AddThemeColorOverride("font_color", selected ? AgentConsoleInk : AgentConsoleMuted);
            StyleBoxFlat normal = AgentConsoleStyle(
                selected ? new Color(1f, 0.91f, 0.95f, 0.98f) : new Color(1f, 1f, 1f, 0.56f),
                selected ? new Color(0.94f, 0.58f, 0.74f, 0.96f) : AgentConsoleBorder,
                12,
                1);
            StyleBoxFlat hover = (StyleBoxFlat)normal.Duplicate();
            hover.BgColor = new Color(1f, 0.94f, 0.97f, 0.98f);
            button.AddThemeStyleboxOverride("normal", normal);
            button.AddThemeStyleboxOverride("hover", hover);
            button.AddThemeStyleboxOverride("pressed", hover);
            button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
            button.Pressed += () =>
            {
                _agentSelectedTaskId = captured.TaskId;
                RefreshAgentConsole();
                SendAgentControl("snapshot", quiet: true);
            };
            _agentConsoleTaskList.AddChild(button);
        }
    }

    private void RebuildAgentEventStream()
    {
        ClearAgentChildren(_agentConsoleEventList);
        AgentConsoleTaskView task = SelectedAgentTask();
        if (task == null)
        {
            _agentConsoleTaskTitleLabel.Text = "Chưa có task";
            var empty = AgentConsoleLabel("Execution stream sẽ hiện tool call, observation, checkpoint và intervention của Eris ở đây.", 12, AgentConsoleMuted);
            empty.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            _agentConsoleEventList.AddChild(empty);
            return;
        }

        _agentConsoleTaskTitleLabel.Text = string.IsNullOrWhiteSpace(task.ClarifiedGoal) ? task.Goal : task.ClarifiedGoal;
        int start = Math.Max(0, task.Events.Count - 120);
        for (int i = start; i < task.Events.Count; i++)
            _agentConsoleEventList.AddChild(BuildAgentEventCard(task.Events[i]));
        if (task.Events.Count == 0)
        {
            var empty = AgentConsoleLabel("Task đã tồn tại nhưng chưa phát execution event.", 12, AgentConsoleMuted);
            empty.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            _agentConsoleEventList.AddChild(empty);
        }
    }

    private Control BuildAgentEventCard(AgentConsoleEventView ev)
    {
        Color accent = AgentActorColor(ev.Actor, ev.Type);
        var panel = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(accent.R, accent.G, accent.B, ev.Importance >= 0.85f ? 0.10f : 0.045f),
            new Color(accent.R, accent.G, accent.B, 0.28f),
            12,
            1));
        var margin = AgentConsoleMargin(11, 8, 11, 8);
        panel.AddChild(margin);
        var box = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        box.AddThemeConstantOverride("separation", 3);
        margin.AddChild(box);

        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        Label actor = AgentConsoleLabel(AgentActorLabel(ev.Actor, ev.Type), 10, accent, bold: true);
        actor.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        top.AddChild(actor);
        string stepText = ev.Step > 0 ? $"STEP {ev.Step}" : "";
        top.AddChild(AgentConsoleLabel(stepText, 9, AgentConsoleMuted));
        box.AddChild(top);

        Label summary = AgentConsoleLabel(string.IsNullOrWhiteSpace(ev.Summary) ? AgentEventLabel(ev.Type) : ev.Summary, 12, AgentConsoleInk);
        summary.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(summary);
        if (!string.IsNullOrWhiteSpace(ev.Detail))
        {
            Label detail = AgentConsoleLabel(CompactAgentText(ev.Detail, 420), 10, AgentConsoleMuted);
            detail.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            box.AddChild(detail);
        }

        AgentConsoleEventView captured = ev;
        panel.GuiInput += input =>
        {
            if (input is InputEventMouseButton mb && mb.ButtonIndex == MouseButton.Left && mb.Pressed)
            {
                ShowAgentEventInspector(captured);
                GetViewport().SetInputAsHandled();
            }
        };
        return panel;
    }

    private void RefreshAgentInspectorForTask()
    {
        AgentConsoleTaskView task = SelectedAgentTask();
        if (_agentConsoleInspectorLabel == null || _agentConsoleInspectorDetailLabel == null)
            return;
        if (task == null)
        {
            _agentConsoleInspectorLabel.Text = "Chưa chọn task";
            _agentConsoleInspectorDetailLabel.Text = "";
            _agentConsoleExecutorLabel.Text = "EXECUTOR · —";
            _agentConsoleStatusLabel.Text = "IDLE";
            return;
        }

        _agentConsoleInspectorLabel.Text = CompactAgentText(task.Goal, 90);
        _agentConsoleExecutorLabel.Text = $"EXECUTOR · {task.Executor.ToUpperInvariant()}" + (string.IsNullOrWhiteSpace(task.Model) ? "" : $" · {task.Model}");
        _agentConsoleStatusLabel.Text = AgentStatusLabel(task.Status).ToUpperInvariant();
        _agentConsoleStatusLabel.AddThemeColorOverride("font_color", AgentStatusColor(task.Status));

        var sb = new StringBuilder();
        sb.AppendLine($"Trạng thái: {AgentStatusLabel(task.Status)}");
        sb.AppendLine($"Step: {task.CurrentStep}");
        sb.AppendLine($"Pending control: {task.PendingControls}");
        sb.AppendLine();
        sb.AppendLine($"Checkpoint: {(string.IsNullOrWhiteSpace(task.CheckpointId) ? "chưa có" : task.CheckpointId)}");
        sb.AppendLine($"Số checkpoint: {task.CheckpointCount}");
        sb.AppendLine();
        sb.AppendLine($"Tests: {task.TestsPassed} pass / {task.TestsFailed} fail");
        if (!string.IsNullOrWhiteSpace(task.TestsSummary))
            sb.AppendLine(task.TestsSummary);
        sb.AppendLine();
        sb.AppendLine("Skills:");
        if (task.ActiveSkills.Count == 0)
            sb.AppendLine("  — chưa activate");
        else
            foreach (string skill in task.ActiveSkills)
                sb.AppendLine($"  • {skill}");
        sb.AppendLine();
        sb.AppendLine($"Files changed: {task.ChangedFiles.Count}");
        int from = Math.Max(0, task.ChangedFiles.Count - 8);
        for (int i = from; i < task.ChangedFiles.Count; i++)
            sb.AppendLine($"  • {task.ChangedFiles[i]}");
        _agentConsoleInspectorDetailLabel.Text = sb.ToString().TrimEnd();
    }

    private void ShowAgentEventInspector(AgentConsoleEventView ev)
    {
        if (_agentConsoleInspectorLabel == null || _agentConsoleInspectorDetailLabel == null || ev == null)
            return;
        _agentConsoleInspectorLabel.Text = $"{AgentActorLabel(ev.Actor, ev.Type)} · {AgentEventLabel(ev.Type)}";
        var sb = new StringBuilder();
        if (ev.Step > 0) sb.AppendLine($"Step: {ev.Step}");
        if (ev.CreatedAt > 0) sb.AppendLine($"Time: {AgentTimeText(ev.CreatedAt)}");
        if (!string.IsNullOrWhiteSpace(ev.Summary))
        {
            sb.AppendLine();
            sb.AppendLine(ev.Summary);
        }
        if (!string.IsNullOrWhiteSpace(ev.Detail))
        {
            sb.AppendLine();
            sb.AppendLine(ev.Detail);
        }
        if (!string.IsNullOrWhiteSpace(ev.DataText))
        {
            sb.AppendLine();
            sb.AppendLine("Metadata:");
            sb.AppendLine(ev.DataText);
        }
        _agentConsoleInspectorDetailLabel.Text = sb.ToString().TrimEnd();
    }

    private void RefreshAgentConsoleControls()
    {
        AgentConsoleTaskView task = SelectedAgentTask();
        bool hasTask = task != null;
        string status = task?.Status ?? "";
        if (_agentConsolePauseButton != null)
            _agentConsolePauseButton.Disabled = !hasTask || status == "paused" || AgentTaskTerminal(status);
        if (_agentConsoleResumeButton != null)
            _agentConsoleResumeButton.Disabled = !hasTask || status != "paused";
        if (_agentConsoleStopButton != null)
            _agentConsoleStopButton.Disabled = !hasTask || AgentTaskTerminal(status);
        if (_agentConsoleRollbackButton != null)
            _agentConsoleRollbackButton.Disabled = !hasTask || string.IsNullOrWhiteSpace(task.CheckpointId);
        if (_agentConsoleDirectiveInput != null)
            _agentConsoleDirectiveInput.Editable = hasTask && !AgentTaskTerminal(status);
    }

    private AgentConsoleTaskView SelectedAgentTask()
    {
        return FindAgentTask(_agentSelectedTaskId);
    }

    private AgentConsoleTaskView FindAgentTask(string taskId)
    {
        if (string.IsNullOrWhiteSpace(taskId))
            return null;
        foreach (AgentConsoleTaskView task in _agentConsoleTasks)
            if (string.Equals(task.TaskId, taskId, StringComparison.Ordinal))
                return task;
        return null;
    }

    private void ScrollAgentConsoleToBottom()
    {
        if (_agentConsoleEventScroll == null)
            return;
        VScrollBar bar = _agentConsoleEventScroll.GetVScrollBar();
        if (bar != null)
            bar.Value = bar.MaxValue;
    }

    private void SetAgentConsoleControlStatus(string text, bool error = false)
    {
        if (_agentConsoleControlStatusLabel == null)
            return;
        _agentConsoleControlStatusLabel.Text = text ?? "";
        _agentConsoleControlStatusLabel.AddThemeColorOverride("font_color", error ? AgentConsoleRed : AgentConsoleMuted);
    }

    private static void ClearAgentChildren(Control parent)
    {
        if (parent == null)
            return;
        foreach (Node child in parent.GetChildren())
            child.QueueFree();
    }

    private static string CompactAgentData(JsonElement data)
    {
        var sb = new StringBuilder();
        int count = 0;
        foreach (JsonProperty prop in data.EnumerateObject())
        {
            if (count++ >= 16)
            {
                sb.AppendLine("…");
                break;
            }
            string value;
            if (prop.Value.ValueKind == JsonValueKind.String)
                value = prop.Value.GetString() ?? "";
            else
                value = prop.Value.GetRawText();
            sb.Append(prop.Name).Append(": ").AppendLine(CompactAgentText(value, 260));
        }
        return sb.ToString().TrimEnd();
    }

    private static string AgentReadJsonString(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out JsonElement node))
            return "";
        if (node.ValueKind == JsonValueKind.String)
            return node.GetString() ?? "";
        if (node.ValueKind is JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False)
            return node.ToString();
        return "";
    }

    private static int AgentReadJsonInt(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out JsonElement node))
            return 0;
        if (node.ValueKind == JsonValueKind.Number && node.TryGetInt32(out int value))
            return value;
        return int.TryParse(node.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out value) ? value : 0;
    }

    private static double AgentReadJsonDouble(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out JsonElement node))
            return 0.0;
        if (node.ValueKind == JsonValueKind.Number && node.TryGetDouble(out double value))
            return value;
        return double.TryParse(node.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out value) ? value : 0.0;
    }

    private static string AgentTimeText(double unix)
    {
        try
        {
            return DateTimeOffset.FromUnixTimeMilliseconds((long)(unix * 1000.0)).ToLocalTime().ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        }
        catch (ArgumentOutOfRangeException)
        {
            return "";
        }
    }

    private static string CompactAgentText(string text, int max)
    {
        string value = (text ?? "").Replace("\r", " ").Trim();
        if (value.Length <= max)
            return value;
        return value.Substring(0, Math.Max(0, max - 1)).TrimEnd() + "…";
    }

    private static string AgentActorLabel(string actor, string eventType)
    {
        string value = (actor ?? "").Trim().ToLowerInvariant();
        if (value == "eris" || eventType.StartsWith("supervisor_", StringComparison.Ordinal)) return "ERIS · SUPERVISOR";
        if (value == "executor" || value == "gemini") return "GEMINI · EXECUTOR";
        if (value == "tool") return "TOOL";
        if (value == "user") return "USER DIRECTIVE";
        return "SYSTEM";
    }

    private static Color AgentActorColor(string actor, string eventType)
    {
        string value = (actor ?? "").Trim().ToLowerInvariant();
        if (value == "eris" || eventType.StartsWith("supervisor_", StringComparison.Ordinal)) return AgentConsolePink;
        if (value == "executor" || value == "gemini") return AgentConsoleGreen;
        if (value == "tool") return AgentConsoleGold;
        if (value == "user") return AgentConsoleBlue;
        if (eventType.Contains("failed", StringComparison.Ordinal) || eventType.Contains("veto", StringComparison.Ordinal)) return AgentConsoleRed;
        return AgentConsoleMuted;
    }

    private static string AgentEventLabel(string eventType)
    {
        return (eventType ?? "") switch
        {
            "task_started" => "Task bắt đầu",
            "task_completed" => "Task hoàn tất",
            "task_failed" => "Task thất bại",
            "agent_plan" => "Kế hoạch bước kế",
            "agent_summary" => "Executor update",
            "skill_search" => "Tìm skill",
            "skill_activated" => "Kích hoạt skill",
            "tool_started" => "Tool call",
            "tool_result" => "Observation",
            "tool_failed" => "Tool lỗi",
            "checkpoint_created" => "Checkpoint",
            "checkpoint_restored" => "Checkpoint restored",
            "rollback_requested" => "Rollback requested",
            "rollback_queued" => "Rollback queued",
            "user_directive" => "Chỉ thị user",
            "supervisor_comment" => "Eris bình luận",
            "supervisor_advisory" => "Eris advisory",
            "supervisor_redirect" => "Eris redirect",
            "supervisor_veto" => "Eris veto",
            "permission_requested" => "Chờ quyền",
            "clarification_requested" => "Cần hỏi user",
            _ => string.IsNullOrWhiteSpace(eventType) ? "Agent event" : eventType.Replace('_', ' '),
        };
    }

    private static string AgentStatusGlyph(string status)
    {
        return (status ?? "").ToLowerInvariant() switch
        {
            "running" => "●",
            "paused" => "Ⅱ",
            "waiting_user" => "?",
            "waiting_permission" => "!",
            "completed" => "✓",
            "failed" => "×",
            "stopped" => "■",
            _ => "○",
        };
    }

    private static string AgentStatusLabel(string status)
    {
        return (status ?? "").ToLowerInvariant() switch
        {
            "running" => "Đang chạy",
            "paused" => "Tạm dừng",
            "waiting_user" => "Chờ user",
            "waiting_permission" => "Chờ quyền",
            "completed" => "Hoàn tất",
            "failed" => "Thất bại",
            "stopped" => "Đã dừng",
            "queued" => "Xếp hàng",
            _ => string.IsNullOrWhiteSpace(status) ? "Không rõ" : status,
        };
    }

    private static Color AgentStatusColor(string status)
    {
        return (status ?? "").ToLowerInvariant() switch
        {
            "running" => AgentConsoleGreen,
            "paused" => AgentConsoleGold,
            "waiting_user" => AgentConsoleBlue,
            "waiting_permission" => AgentConsoleGold,
            "completed" => AgentConsoleGreen,
            "failed" => AgentConsoleRed,
            "stopped" => AgentConsoleRed,
            _ => AgentConsoleMuted,
        };
    }

    private static bool AgentTaskTerminal(string status)
    {
        string value = (status ?? "").ToLowerInvariant();
        return value is "completed" or "failed" or "stopped";
    }

    private static Label AgentConsoleLabel(string text, int size, Color color, bool bold = false)
    {
        var label = new Label
        {
            Text = text ?? "",
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        label.AddThemeFontSizeOverride("font_size", size);
        label.AddThemeColorOverride("font_color", color);
        if (bold)
            label.AddThemeConstantOverride("outline_size", 0);
        return label;
    }

    private static Label AgentConsoleChip(string text, Color color)
    {
        var label = AgentConsoleLabel(text, 10, color, bold: true);
        label.CustomMinimumSize = new Vector2(92f, 30f);
        label.HorizontalAlignment = HorizontalAlignment.Center;
        label.VerticalAlignment = VerticalAlignment.Center;
        label.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(color.R, color.G, color.B, 0.07f),
            new Color(color.R, color.G, color.B, 0.22f),
            10,
            1));
        return label;
    }

    private static MarginContainer AgentConsoleMargin(int left, int top, int right, int bottom)
    {
        var margin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        margin.AddThemeConstantOverride("margin_left", left);
        margin.AddThemeConstantOverride("margin_top", top);
        margin.AddThemeConstantOverride("margin_right", right);
        margin.AddThemeConstantOverride("margin_bottom", bottom);
        return margin;
    }

    private static StyleBoxFlat AgentConsoleStyle(Color bg, Color border, int radius, int borderWidth, bool shadow = false)
    {
        var style = new StyleBoxFlat
        {
            BgColor = bg,
            BorderColor = border,
            BorderWidthLeft = borderWidth,
            BorderWidthTop = borderWidth,
            BorderWidthRight = borderWidth,
            BorderWidthBottom = borderWidth,
            CornerRadiusTopLeft = radius,
            CornerRadiusTopRight = radius,
            CornerRadiusBottomLeft = radius,
            CornerRadiusBottomRight = radius,
            ContentMarginLeft = 7f,
            ContentMarginTop = 5f,
            ContentMarginRight = 7f,
            ContentMarginBottom = 5f,
        };
        if (shadow)
        {
            style.ShadowColor = new Color(0.55f, 0.22f, 0.37f, 0.16f);
            style.ShadowSize = 8;
        }
        return style;
    }

    private static Button AgentConsoleButton(string text, Action onPressed, bool primary, bool danger = false)
    {
        Color accent = danger ? AgentConsoleRed : (primary ? AgentConsolePink : AgentConsoleMuted);
        var button = new Button
        {
            Text = text,
            CustomMinimumSize = new Vector2(84f, 34f),
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        StyleBoxFlat normal = AgentConsoleStyle(
            primary ? new Color(0.97f, 0.36f, 0.63f, 0.90f) : new Color(1f, 1f, 1f, 0.82f),
            new Color(accent.R, accent.G, accent.B, primary ? 0.72f : 0.30f),
            11,
            1);
        StyleBoxFlat hover = (StyleBoxFlat)normal.Duplicate();
        hover.BgColor = primary ? new Color(0.98f, 0.43f, 0.68f, 0.96f) : new Color(1f, 0.93f, 0.97f, 0.98f);
        StyleBoxFlat disabled = (StyleBoxFlat)normal.Duplicate();
        disabled.BgColor = new Color(0.96f, 0.94f, 0.95f, 0.46f);
        disabled.BorderColor = new Color(0.82f, 0.78f, 0.80f, 0.28f);
        button.AddThemeStyleboxOverride("normal", normal);
        button.AddThemeStyleboxOverride("hover", hover);
        button.AddThemeStyleboxOverride("pressed", hover);
        button.AddThemeStyleboxOverride("disabled", disabled);
        button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
        button.AddThemeColorOverride("font_color", primary ? Colors.White : accent);
        button.AddThemeColorOverride("font_hover_color", primary ? Colors.White : AgentConsolePink);
        button.AddThemeColorOverride("font_disabled_color", new Color(0.55f, 0.50f, 0.52f, 0.42f));
        button.AddThemeFontSizeOverride("font_size", 11);
        if (onPressed != null)
            button.Pressed += onPressed;
        return button;
    }

    private static void StyleAgentConsoleInput(LineEdit input)
    {
        if (input == null)
            return;
        input.CustomMinimumSize = new Vector2(260f, 34f);
        input.AddThemeFontSizeOverride("font_size", 11);
        input.AddThemeColorOverride("font_color", AgentConsoleInk);
        input.AddThemeColorOverride("font_placeholder_color", new Color(AgentConsoleMuted.R, AgentConsoleMuted.G, AgentConsoleMuted.B, 0.72f));
        input.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(1f, 1f, 1f, 0.95f), AgentConsoleBorder, 11, 1));
        input.AddThemeStyleboxOverride("focus", AgentConsoleStyle(
            new Color(1f, 1f, 1f, 0.99f), new Color(0.93f, 0.56f, 0.73f, 0.96f), 11, 1));
    }
}
