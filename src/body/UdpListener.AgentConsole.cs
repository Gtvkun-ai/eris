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

    // V3: visual pass bám mockup đã chốt. Agent Console giờ là execution UI thật,
    // không còn cảm giác admin dashboard pastel vô hồn.
    private static readonly Vector2 AgentConsolePreferredSize = new(1120f, 720f);
    private static readonly Vector2 AgentConsoleMinimumSize = new(900f, 590f);
    private static readonly Color AgentConsoleBg = new(0.973f, 0.977f, 0.985f, 0.995f);
    private static readonly Color AgentConsoleCard = new(0.996f, 0.998f, 1.0f, 0.985f);
    private static readonly Color AgentConsoleSoft = new(0.955f, 0.965f, 0.976f, 0.94f);
    private static readonly Color AgentConsoleBorder = new(0.845f, 0.875f, 0.915f, 0.78f);
    private static readonly Color AgentConsoleInk = new(0.135f, 0.170f, 0.250f, 1f);
    private static readonly Color AgentConsoleMuted = new(0.405f, 0.455f, 0.555f, 1f);
    private static readonly Color AgentConsoleFaint = new(0.62f, 0.67f, 0.75f, 1f);
    private static readonly Color AgentConsolePink = new(0.96f, 0.31f, 0.60f, 1f);
    private static readonly Color AgentConsoleGreen = new(0.35f, 0.79f, 0.60f, 1f);
    private static readonly Color AgentConsoleGold = new(0.87f, 0.72f, 0.28f, 1f);
    private static readonly Color AgentConsoleBlue = new(0.41f, 0.51f, 0.98f, 1f);
    private static readonly Color AgentConsoleRed = new(0.95f, 0.32f, 0.42f, 1f);

    private Button _contextAgentConsoleButton;
    private Panel _agentConsolePanel;
    private Label _agentConsoleStatusLabel;
    private Label _agentConsoleExecutorLabel;
    private Label _agentConsoleTaskTitleLabel;
    private Label _agentConsoleTaskMetaLabel;
    private PanelContainer _agentConsoleTaskDrawer;
    private PanelContainer _agentConsoleInspectorDrawer;
    private VBoxContainer _agentConsoleTaskList;
    private VBoxContainer _agentConsoleEventList;
    private ScrollContainer _agentConsoleEventScroll;
    private Label _agentConsoleStepLabel;
    private Label _agentConsoleTestsLabel;
    private Label _agentConsoleFilesLabel;
    private Label _agentConsoleCheckpointLabel;
    private Label _agentConsoleSkillsLabel;
    private Button _agentConsoleTasksToggleButton;
    private Button _agentConsoleInspectorToggleButton;
    private Button _agentConsoleFilterAllButton;
    private Button _agentConsoleFilterConversationButton;
    private Button _agentConsoleFilterToolsButton;
    private Button _agentConsoleFollowButton;
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
    private bool _agentConsoleTaskDrawerVisible;
    private bool _agentConsoleInspectorVisible;
    private bool _agentConsoleAutoFollow = true;
    private string _agentConsoleEventFilter = "all";

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
            AgentConsoleBg,
            new Color(0.82f, 0.88f, 0.94f, 0.80f),
            24,
            1,
            shadow: true));
        GetNode<Control>("CanvasLayer/Control").AddChild(_agentConsolePanel);

        var margin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        margin.AddThemeConstantOverride("margin_left", 22);
        margin.AddThemeConstantOverride("margin_right", 22);
        margin.AddThemeConstantOverride("margin_top", 18);
        margin.AddThemeConstantOverride("margin_bottom", 16);
        _agentConsolePanel.AddChild(margin);

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 12);
        margin.AddChild(root);

        root.AddChild(BuildAgentConsoleHeader());
        root.AddChild(BuildAgentQuickSummary());
        root.AddChild(BuildAgentConsoleBody());
        root.AddChild(BuildAgentConsoleFooter());
        RefreshAgentConsole();
    }





    private Control BuildAgentConsoleHeader()
    {
        var row = new HBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 54f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 10);

        var emblem = new Label
        {
            Text = "◇",
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            CustomMinimumSize = new Vector2(44f, 44f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        emblem.AddThemeFontSizeOverride("font_size", 21);
        emblem.AddThemeColorOverride("font_color", new Color(0.30f, 0.78f, 0.66f, 1f));
        emblem.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.94f, 0.985f, 0.972f, 1f),
            new Color(0.72f, 0.92f, 0.85f, 0.74f),
            14,
            1));
        row.AddChild(emblem);

        var titles = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        titles.AddThemeConstantOverride("separation", 0);
        titles.AddChild(AgentConsoleLabel("Agent", 23, AgentConsoleInk, bold: true));
        _agentConsoleTaskMetaLabel = AgentConsoleLabel("Gemini ↔ Eris · execution session", 10, AgentConsoleMuted);
        titles.AddChild(_agentConsoleTaskMetaLabel);
        row.AddChild(titles);

        _agentConsoleTasksToggleButton = AgentConsoleQuietButton("Công việc", ToggleAgentTaskDrawer, 92f);
        _agentConsoleTasksToggleButton.TooltipText = "Mở lịch sử task";
        row.AddChild(_agentConsoleTasksToggleButton);

        _agentConsoleExecutorLabel = AgentConsoleTinyStatus("EXECUTOR · —", AgentConsoleGreen);
        row.AddChild(_agentConsoleExecutorLabel);
        _agentConsoleStatusLabel = AgentConsoleTinyStatus("IDLE", AgentConsoleMuted);
        row.AddChild(_agentConsoleStatusLabel);

        _agentConsoleInspectorToggleButton = AgentConsoleQuietButton("Chi tiết", ToggleAgentInspector, 82f);
        row.AddChild(_agentConsoleInspectorToggleButton);
        var refresh = AgentConsoleQuietButton("↻", () => SendAgentControl("snapshot"), 38f);
        refresh.TooltipText = "Đồng bộ task";
        row.AddChild(refresh);
        var close = CreateWindowControlButton("×", CloseAgentConsolePanel, 36f, 15);
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
        body.AddThemeConstantOverride("separation", 12);

        _agentConsoleTaskDrawer = BuildAgentTaskPane();
        _agentConsoleTaskDrawer.Visible = _agentConsoleTaskDrawerVisible;
        body.AddChild(_agentConsoleTaskDrawer);
        body.AddChild(BuildAgentStreamPane());
        _agentConsoleInspectorDrawer = BuildAgentInspectorPane();
        _agentConsoleInspectorDrawer.Visible = _agentConsoleInspectorVisible;
        body.AddChild(_agentConsoleInspectorDrawer);
        return body;
    }

    private PanelContainer BuildAgentTaskPane()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(250f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.985f, 0.992f, 1f, 0.98f),
            new Color(0.84f, 0.89f, 0.95f, 0.72f),
            20,
            1));

        var margin = AgentConsoleMargin(14, 14, 14, 14);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 10);
        margin.AddChild(box);

        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        var title = AgentConsoleLabel("Công việc", 15, AgentConsoleInk, bold: true);
        title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        top.AddChild(title);
        var close = AgentConsoleQuietButton("‹", ToggleAgentTaskDrawer, 30f);
        top.AddChild(close);
        box.AddChild(top);
        box.AddChild(AgentConsoleLabel("Task đang chạy và lịch sử gần đây", 10, AgentConsoleMuted));

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
        _agentConsoleTaskList.AddThemeConstantOverride("separation", 8);
        scroll.AddChild(_agentConsoleTaskList);
        return panel;
    }

    private Control BuildAgentStreamPane()
    {
        var root = new VBoxContainer
        {
            CustomMinimumSize = new Vector2(620f, 0f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 7);

        _agentConsoleTaskTitleLabel = AgentConsoleLabel("Chưa có task", 15, AgentConsoleInk, bold: true);
        _agentConsoleTaskTitleLabel.ClipText = true;
        _agentConsoleTaskTitleLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
        root.AddChild(_agentConsoleTaskTitleLabel);

        var streamSurface = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        streamSurface.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            AgentConsoleCard,
            new Color(0.84f, 0.90f, 0.95f, 0.72f),
            18,
            1));
        var streamMargin = AgentConsoleMargin(14, 10, 14, 10);
        streamSurface.AddChild(streamMargin);
        var streamBox = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        streamBox.AddThemeConstantOverride("separation", 9);
        streamMargin.AddChild(streamBox);
        streamBox.AddChild(BuildAgentFilterBar());

        _agentConsoleEventScroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
        };
        streamBox.AddChild(_agentConsoleEventScroll);
        _agentConsoleEventList = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _agentConsoleEventList.AddThemeConstantOverride("separation", 9);
        _agentConsoleEventScroll.AddChild(_agentConsoleEventList);
        root.AddChild(streamSurface);
        return root;
    }

    private Control BuildAgentQuickSummary()
    {
        var strip = new PanelContainer
        {
            CustomMinimumSize = new Vector2(0f, 66f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        strip.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.992f, 0.996f, 1f, 0.96f),
            new Color(0.84f, 0.90f, 0.95f, 0.72f),
            18,
            1));
        var margin = AgentConsoleMargin(12, 8, 12, 8);
        strip.AddChild(margin);
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 8);
        margin.AddChild(row);

        _agentConsoleStepLabel = AgentConsoleMetric("STEP", "—", AgentConsoleBlue);
        _agentConsoleTestsLabel = AgentConsoleMetric("TESTS", "—", AgentConsoleGreen);
        _agentConsoleFilesLabel = AgentConsoleMetric("FILES", "—", new Color(0.28f, 0.67f, 0.78f, 1f));
        _agentConsoleCheckpointLabel = AgentConsoleMetric("CHECKPOINT", "—", AgentConsoleGreen);
        _agentConsoleSkillsLabel = AgentConsoleMetric("SKILLS", "—", new Color(0.52f, 0.49f, 0.91f, 1f));
        row.AddChild(_agentConsoleStepLabel);
        row.AddChild(_agentConsoleTestsLabel);
        row.AddChild(_agentConsoleFilesLabel);
        row.AddChild(_agentConsoleCheckpointLabel);
        row.AddChild(_agentConsoleSkillsLabel);
        return strip;
    }

    private Control BuildAgentFilterBar()
    {
        var row = new HBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 40f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 6);
        _agentConsoleFilterAllButton = AgentConsoleFilterButton("Tất cả", "all");
        _agentConsoleFilterConversationButton = AgentConsoleFilterButton("Hội thoại", "conversation");
        _agentConsoleFilterToolsButton = AgentConsoleFilterButton("Tools", "tools");
        row.AddChild(_agentConsoleFilterAllButton);
        row.AddChild(_agentConsoleFilterConversationButton);
        row.AddChild(_agentConsoleFilterToolsButton);
        var spacer = new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddChild(spacer);
        _agentConsoleFollowButton = AgentConsoleQuietButton("Theo dõi ●", ToggleAgentAutoFollow, 92f);
        _agentConsoleFollowButton.TooltipText = "Tự cuộn xuống event mới";
        row.AddChild(_agentConsoleFollowButton);
        RefreshAgentFilterButtons();
        return row;
    }

    private PanelContainer BuildAgentInspectorPane()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(265f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.991f, 0.996f, 1f, 0.98f),
            new Color(0.84f, 0.90f, 0.95f, 0.72f),
            18,
            1));
        var margin = AgentConsoleMargin(14, 12, 14, 12);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 9);
        margin.AddChild(box);

        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        var title = AgentConsoleLabel("Chi tiết phiên", 14, AgentConsoleInk, bold: true);
        title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        top.AddChild(title);
        top.AddChild(AgentConsoleQuietButton("×", ToggleAgentInspector, 30f));
        box.AddChild(top);
        _agentConsoleInspectorLabel = AgentConsoleLabel("Chưa chọn task", 11, AgentConsoleInk, bold: true);
        _agentConsoleInspectorLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(_agentConsoleInspectorLabel);
        var divider = new ColorRect { Color = new Color(0.86f, 0.90f, 0.95f, 0.80f), CustomMinimumSize = new Vector2(0f, 1f), MouseFilter = Control.MouseFilterEnum.Ignore };
        box.AddChild(divider);
        var scroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
        };
        box.AddChild(scroll);
        _agentConsoleInspectorDetailLabel = AgentConsoleLabel("", 10, AgentConsoleMuted);
        _agentConsoleInspectorDetailLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        _agentConsoleInspectorDetailLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        scroll.AddChild(_agentConsoleInspectorDetailLabel);
        return panel;
    }

    private Control BuildAgentConsoleFooter()
    {
        var root = new VBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 88f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 7);

        var composer = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        composer.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            AgentConsoleCard,
            new Color(0.84f, 0.90f, 0.95f, 0.76f),
            16,
            1));
        var composerMargin = AgentConsoleMargin(9, 7, 8, 7);
        composer.AddChild(composerMargin);
        var composerRow = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        composerRow.AddThemeConstantOverride("separation", 7);
        composerMargin.AddChild(composerRow);
        _agentConsoleDirectiveInput = new LineEdit
        {
            PlaceholderText = "Chỉ thị cho Gemini...  ví dụ: đừng tạo abstraction mới, tìm root cause trước",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            ClearButtonEnabled = true,
        };
        StyleAgentConsoleInput(_agentConsoleDirectiveInput);
        _agentConsoleDirectiveInput.TextSubmitted += _ => SendAgentDirective();
        composerRow.AddChild(_agentConsoleDirectiveInput);
        var send = AgentConsoleButton("Gửi  ➤", SendAgentDirective, primary: true);
        send.CustomMinimumSize = new Vector2(92f, 42f);
        composerRow.AddChild(send);
        root.AddChild(composer);

        var actionRow = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        actionRow.AddThemeConstantOverride("separation", 7);
        _agentConsolePauseButton = AgentConsoleQuietButton("Ⅱ  Tạm dừng", () => SendAgentControl("pause"), 104f);
        _agentConsoleResumeButton = AgentConsoleQuietButton("▶  Tiếp tục", () => SendAgentControl("resume"), 100f);
        _agentConsoleStopButton = AgentConsoleQuietButton("■  Dừng", () => SendAgentControl("stop"), 82f, danger: true);
        _agentConsoleRollbackButton = AgentConsoleQuietButton("↶  Rollback", () => SendAgentControl("rollback", checkpointId: SelectedAgentTask()?.CheckpointId ?? ""), 106f);
        actionRow.AddChild(_agentConsolePauseButton);
        actionRow.AddChild(_agentConsoleResumeButton);
        actionRow.AddChild(_agentConsoleStopButton);
        actionRow.AddChild(_agentConsoleRollbackButton);
        var spacer = new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        actionRow.AddChild(spacer);
        _agentConsoleControlStatusLabel = AgentConsoleLabel("Sẵn sàng.", 9, AgentConsoleFaint);
        _agentConsoleControlStatusLabel.VerticalAlignment = VerticalAlignment.Center;
        actionRow.AddChild(_agentConsoleControlStatusLabel);
        root.AddChild(actionRow);
        return root;
    }

    private void ToggleAgentTaskDrawer()
    {
        _agentConsoleTaskDrawerVisible = !_agentConsoleTaskDrawerVisible;
        if (_agentConsoleTaskDrawer != null)
            _agentConsoleTaskDrawer.Visible = _agentConsoleTaskDrawerVisible;
    }

    private void ToggleAgentInspector()
    {
        _agentConsoleInspectorVisible = !_agentConsoleInspectorVisible;
        if (_agentConsoleInspectorDrawer != null)
            _agentConsoleInspectorDrawer.Visible = _agentConsoleInspectorVisible;
        if (_agentConsoleInspectorToggleButton != null)
            _agentConsoleInspectorToggleButton.Text = _agentConsoleInspectorVisible ? "Chi tiết" : "Chi tiết";
    }

    private void ToggleAgentAutoFollow()
    {
        _agentConsoleAutoFollow = !_agentConsoleAutoFollow;
        if (_agentConsoleFollowButton != null)
            _agentConsoleFollowButton.Text = _agentConsoleAutoFollow ? "Theo dõi ●" : "Theo dõi ○";
        if (_agentConsoleAutoFollow)
            CallDeferred(nameof(ScrollAgentConsoleToBottom));
    }

    private Button AgentConsoleFilterButton(string text, string filter)
    {
        string captured = filter;
        var button = AgentConsoleQuietButton(text, () =>
        {
            _agentConsoleEventFilter = captured;
            RefreshAgentFilterButtons();
            RebuildAgentEventStream();
            if (_agentConsoleAutoFollow)
                CallDeferred(nameof(ScrollAgentConsoleToBottom));
        }, text == "Hội thoại" ? 76f : 62f);
        return button;
    }

    private void RefreshAgentFilterButtons()
    {
        StyleAgentFilterButton(_agentConsoleFilterAllButton, _agentConsoleEventFilter == "all");
        StyleAgentFilterButton(_agentConsoleFilterConversationButton, _agentConsoleEventFilter == "conversation");
        StyleAgentFilterButton(_agentConsoleFilterToolsButton, _agentConsoleEventFilter == "tools");
    }

    private static void StyleAgentFilterButton(Button button, bool active)
    {
        if (button == null)
            return;
        button.AddThemeColorOverride("font_color", active ? Colors.White : AgentConsoleMuted);
        button.AddThemeColorOverride("font_hover_color", active ? Colors.White : AgentConsoleInk);
        button.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            active ? new Color(0.16f, 0.20f, 0.27f, 0.98f) : new Color(0.965f, 0.975f, 0.99f, 0.94f),
            Colors.Transparent,
            11,
            0));
        button.AddThemeStyleboxOverride("hover", AgentConsoleStyle(
            active ? new Color(0.19f, 0.23f, 0.30f, 1f) : new Color(0.93f, 0.96f, 1f, 1f),
            Colors.Transparent,
            11,
            0));
    }

    private static bool AgentEventMatchesFilter(AgentConsoleEventView ev, string filter)
    {
        if (ev == null || string.IsNullOrWhiteSpace(filter) || filter == "all")
            return true;
        string actor = (ev.Actor ?? "").Trim().ToLowerInvariant();
        string type = (ev.Type ?? "").Trim().ToLowerInvariant();
        if (filter == "conversation")
            return actor is "eris" or "executor" or "gemini" or "user"
                || type.StartsWith("supervisor_", StringComparison.Ordinal)
                || type is "agent_summary" or "agent_plan" or "clarification_requested" or "user_directive";
        if (filter == "tools")
            return actor == "tool"
                || type.StartsWith("tool_", StringComparison.Ordinal)
                || type.StartsWith("skill_", StringComparison.Ordinal)
                || type.StartsWith("checkpoint_", StringComparison.Ordinal)
                || type.Contains("test", StringComparison.Ordinal)
                || type.Contains("file", StringComparison.Ordinal)
                || type.StartsWith("permission_", StringComparison.Ordinal);
        return true;
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
                if (_agentConsoleAutoFollow)
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
            if (_agentConsoleAutoFollow)
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
            var empty = AgentConsoleLabel("Chưa có task. Task mới sẽ xuất hiện ở đây khi AgentHarness bắt đầu chạy.", 10, AgentConsoleMuted);
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
                Text = $"{AgentStatusGlyph(task.Status)}  {CompactAgentText(task.Goal, 34)}\n     {AgentStatusLabel(task.Status)} · bước {task.CurrentStep}",
                CustomMinimumSize = new Vector2(0f, 54f),
                SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
                Alignment = HorizontalAlignment.Left,
                FocusMode = Control.FocusModeEnum.None,
                MouseDefaultCursorShape = Control.CursorShape.PointingHand,
            };
            button.AddThemeFontSizeOverride("font_size", 10);
            button.AddThemeColorOverride("font_color", selected ? AgentConsoleInk : AgentConsoleMuted);
            StyleBoxFlat normal = AgentConsoleStyle(
                selected ? new Color(1f, 1f, 1f, 0.86f) : Colors.Transparent,
                selected ? new Color(AgentConsolePink.R, AgentConsolePink.G, AgentConsolePink.B, 0.18f) : Colors.Transparent,
                10,
                selected ? 1 : 0);
            StyleBoxFlat hover = AgentConsoleStyle(
                new Color(1f, 1f, 1f, 0.72f),
                new Color(AgentConsoleBorder.R, AgentConsoleBorder.G, AgentConsoleBorder.B, 0.42f),
                10,
                1);
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
            _agentConsoleEventList.AddChild(BuildAgentEmptyState("Khi Gemini bắt đầu làm việc, tool, checkpoint và intervention của Eris sẽ xuất hiện ở timeline này."));
            return;
        }

        _agentConsoleTaskTitleLabel.Text = string.IsNullOrWhiteSpace(task.ClarifiedGoal) ? task.Goal : task.ClarifiedGoal;
        int start = Math.Max(0, task.Events.Count - 160);
        int rendered = 0;
        for (int i = start; i < task.Events.Count; i++)
        {
            AgentConsoleEventView ev = task.Events[i];
            if (!AgentEventMatchesFilter(ev, _agentConsoleEventFilter))
                continue;
            _agentConsoleEventList.AddChild(BuildAgentEventCard(ev));
            rendered++;
        }
        if (rendered == 0)
        {
            string message = task.Events.Count == 0
                ? "Task đã tồn tại nhưng chưa phát execution event."
                : "Không có event nào khớp bộ lọc hiện tại.";
            _agentConsoleEventList.AddChild(BuildAgentEmptyState(message));
        }
    }

    private Control BuildAgentEventCard(AgentConsoleEventView ev)
    {
        string actor = (ev.Actor ?? "").Trim().ToLowerInvariant();
        string type = (ev.Type ?? "").Trim().ToLowerInvariant();
        bool conversational = actor is "eris" or "executor" or "gemini" or "user"
            || type.StartsWith("supervisor_", StringComparison.Ordinal)
            || type is "agent_summary" or "agent_plan" or "clarification_requested" or "user_directive";
        return conversational ? BuildAgentConversationEvent(ev) : BuildAgentCompactEvent(ev);
    }

    private Control BuildAgentConversationEvent(AgentConsoleEventView ev)
    {
        Color accent = AgentActorColor(ev.Actor, ev.Type);
        var outer = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        outer.AddThemeConstantOverride("separation", 10);

        var marker = new Label
        {
            Text = AgentActorGlyph(ev.Actor, ev.Type),
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            CustomMinimumSize = new Vector2(34f, 34f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        marker.AddThemeFontSizeOverride("font_size", 13);
        marker.AddThemeColorOverride("font_color", accent);
        marker.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(accent.R, accent.G, accent.B, 0.10f),
            new Color(accent.R, accent.G, accent.B, 0.25f),
            17,
            1));
        outer.AddChild(marker);

        var panel = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.998f, 0.999f, 1f, 0.98f),
            new Color(0.87f, 0.91f, 0.96f, 0.72f),
            14,
            1));
        var margin = AgentConsoleMargin(12, 8, 12, 8);
        panel.AddChild(margin);
        var box = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        box.AddThemeConstantOverride("separation", 3);
        margin.AddChild(box);
        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        Label actorLabel = AgentConsoleLabel(AgentActorLabel(ev.Actor, ev.Type), 9, accent, bold: true);
        actorLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        top.AddChild(actorLabel);
        if (ev.CreatedAt > 0)
            top.AddChild(AgentConsoleLabel(AgentTimeText(ev.CreatedAt), 8, AgentConsoleFaint));
        box.AddChild(top);
        Label summary = AgentConsoleLabel(
            string.IsNullOrWhiteSpace(ev.Summary) ? AgentEventLabel(ev.Type) : ev.Summary,
            11,
            AgentConsoleInk);
        summary.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(summary);
        if (!string.IsNullOrWhiteSpace(ev.Detail))
        {
            Label detail = AgentConsoleLabel(CompactAgentText(ev.Detail, 300), 9, AgentConsoleMuted);
            detail.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            box.AddChild(detail);
        }
        AgentConsoleEventView captured = ev;
        panel.GuiInput += input =>
        {
            if (input is InputEventMouseButton mb && mb.ButtonIndex == MouseButton.Left && mb.Pressed)
            {
                ShowAgentEventInspector(captured);
                if (!_agentConsoleInspectorVisible)
                    ToggleAgentInspector();
                GetViewport().SetInputAsHandled();
            }
        };
        outer.AddChild(panel);
        return outer;
    }

    private Control BuildAgentCompactEvent(AgentConsoleEventView ev)
    {
        Color accent = AgentActorColor(ev.Actor, ev.Type);
        var outer = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        outer.AddThemeConstantOverride("separation", 10);
        var dot = AgentConsoleLabel("●", 8, accent, bold: true);
        dot.CustomMinimumSize = new Vector2(34f, 0f);
        dot.HorizontalAlignment = HorizontalAlignment.Center;
        outer.AddChild(dot);

        var panel = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.965f, 0.978f, 0.992f, 0.80f),
            Colors.Transparent,
            11,
            0));
        var margin = AgentConsoleMargin(10, 6, 10, 6);
        panel.AddChild(margin);
        var row = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 8);
        margin.AddChild(row);
        Label kind = AgentConsoleLabel(AgentEventLabel(ev.Type), 9, accent, bold: true);
        kind.CustomMinimumSize = new Vector2(104f, 0f);
        row.AddChild(kind);
        Label summary = AgentConsoleLabel(
            string.IsNullOrWhiteSpace(ev.Summary) ? AgentActorLabel(ev.Actor, ev.Type) : CompactAgentText(ev.Summary, 220),
            10,
            AgentConsoleInk);
        summary.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        summary.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
        summary.ClipText = true;
        row.AddChild(summary);
        if (ev.Step > 0)
            row.AddChild(AgentConsoleLabel($"#{ev.Step}", 8, AgentConsoleFaint));
        AgentConsoleEventView captured = ev;
        panel.GuiInput += input =>
        {
            if (input is InputEventMouseButton mb && mb.ButtonIndex == MouseButton.Left && mb.Pressed)
            {
                ShowAgentEventInspector(captured);
                if (!_agentConsoleInspectorVisible)
                    ToggleAgentInspector();
                GetViewport().SetInputAsHandled();
            }
        };
        outer.AddChild(panel);
        return outer;
    }

    private Control BuildAgentEmptyState(string message)
    {
        var margin = AgentConsoleMargin(16, 42, 16, 18);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 7);
        margin.AddChild(box);
        var icon = AgentConsoleLabel("◇", 24, new Color(0.56f, 0.67f, 0.82f, 1f), bold: true);
        icon.HorizontalAlignment = HorizontalAlignment.Center;
        box.AddChild(icon);
        Label title = AgentConsoleLabel("Chưa có task đang chạy", 14, AgentConsoleInk, bold: true);
        title.HorizontalAlignment = HorizontalAlignment.Center;
        box.AddChild(title);
        Label detail = AgentConsoleLabel(message, 10, AgentConsoleMuted);
        detail.HorizontalAlignment = HorizontalAlignment.Center;
        detail.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(detail);
        return margin;
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
            if (_agentConsoleTaskMetaLabel != null)
                _agentConsoleTaskMetaLabel.Text = "Gemini ↔ Eris · execution session";
            _agentConsoleExecutorLabel.Text = "—";
            _agentConsoleStatusLabel.Text = "IDLE";
            SetAgentQuickSummary(null);
            return;
        }

        _agentConsoleInspectorLabel.Text = CompactAgentText(task.Goal, 90);
        if (_agentConsoleTaskMetaLabel != null)
            _agentConsoleTaskMetaLabel.Text = $"{AgentStatusLabel(task.Status)} · {task.Events.Count} event · Gemini ↔ Eris";
        _agentConsoleExecutorLabel.Text = CompactAgentText(
            string.IsNullOrWhiteSpace(task.Model)
                ? task.Executor.ToUpperInvariant()
                : $"{task.Executor.ToUpperInvariant()} · {task.Model}",
            24);
        _agentConsoleStatusLabel.Text = AgentStatusLabel(task.Status).ToUpperInvariant();
        _agentConsoleStatusLabel.AddThemeColorOverride("font_color", AgentStatusColor(task.Status));
        SetAgentQuickSummary(task);

        var sb = new StringBuilder();
        sb.AppendLine($"Trạng thái   {AgentStatusLabel(task.Status)}");
        sb.AppendLine($"Bước         {task.CurrentStep}");
        if (task.PendingControls > 0)
            sb.AppendLine($"Chỉ thị chờ  {task.PendingControls}");
        sb.AppendLine();
        sb.AppendLine($"Checkpoint   {(string.IsNullOrWhiteSpace(task.CheckpointId) ? "—" : task.CheckpointId)}");
        sb.AppendLine($"Đã lưu       {task.CheckpointCount}");
        sb.AppendLine();
        sb.AppendLine($"Tests        {task.TestsPassed} pass · {task.TestsFailed} fail");
        if (!string.IsNullOrWhiteSpace(task.TestsSummary))
            sb.AppendLine(task.TestsSummary);
        sb.AppendLine();
        sb.AppendLine("Skills");
        if (task.ActiveSkills.Count == 0)
            sb.AppendLine("  — chưa activate");
        else
            foreach (string skill in task.ActiveSkills)
                sb.AppendLine($"  • {skill}");
        sb.AppendLine();
        sb.AppendLine($"Files changed  {task.ChangedFiles.Count}");
        int from = Math.Max(0, task.ChangedFiles.Count - 10);
        for (int i = from; i < task.ChangedFiles.Count; i++)
            sb.AppendLine($"  • {task.ChangedFiles[i]}");
        _agentConsoleInspectorDetailLabel.Text = sb.ToString().TrimEnd();
    }

    private void SetAgentQuickSummary(AgentConsoleTaskView task)
    {
        if (_agentConsoleStepLabel == null)
            return;
        if (task == null)
        {
            SetAgentMetric(_agentConsoleStepLabel, "STEP", "—", AgentConsoleBlue);
            SetAgentMetric(_agentConsoleTestsLabel, "TESTS", "—", AgentConsoleGreen);
            SetAgentMetric(_agentConsoleFilesLabel, "FILES", "—", new Color(0.28f, 0.67f, 0.78f, 1f));
            SetAgentMetric(_agentConsoleCheckpointLabel, "CHECKPOINT", "—", AgentConsoleGreen);
            SetAgentMetric(_agentConsoleSkillsLabel, "SKILLS", "—", new Color(0.52f, 0.49f, 0.91f, 1f));
            return;
        }
        SetAgentMetric(_agentConsoleStepLabel, "STEP", task.CurrentStep.ToString(), AgentConsoleBlue);
        string tests = task.TestsPassed == 0 && task.TestsFailed == 0 ? "—" : $"{task.TestsPassed} pass · {task.TestsFailed} fail";
        SetAgentMetric(_agentConsoleTestsLabel, "TESTS", tests, task.TestsFailed > 0 ? AgentConsoleRed : AgentConsoleGreen);
        SetAgentMetric(_agentConsoleFilesLabel, "FILES", $"{task.ChangedFiles.Count} changed", new Color(0.28f, 0.67f, 0.78f, 1f));
        SetAgentMetric(_agentConsoleCheckpointLabel, "CHECKPOINT", string.IsNullOrWhiteSpace(task.CheckpointId) ? "—" : CompactAgentText(task.CheckpointId, 12), AgentConsoleGreen);
        SetAgentMetric(_agentConsoleSkillsLabel, "SKILLS", task.ActiveSkills.Count == 0 ? "—" : CompactAgentText(string.Join(", ", task.ActiveSkills), 22), new Color(0.52f, 0.49f, 0.91f, 1f));
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
        {
            _agentConsolePauseButton.Visible = status != "paused";
            _agentConsolePauseButton.Disabled = !hasTask || AgentTaskTerminal(status);
        }
        if (_agentConsoleResumeButton != null)
        {
            _agentConsoleResumeButton.Visible = status == "paused";
            _agentConsoleResumeButton.Disabled = !hasTask || status != "paused";
        }
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
        if (value == "eris" || eventType.StartsWith("supervisor_", StringComparison.Ordinal)) return new Color(0.19f, 0.72f, 0.67f, 1f);
        if (value == "executor" || value == "gemini") return new Color(0.43f, 0.48f, 0.95f, 1f);
        if (value == "tool") return new Color(0.28f, 0.72f, 0.48f, 1f);
        if (value == "user") return AgentConsolePink;
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
            "file_changed" => "File changed",
            "test_result" => "Tests",
            "diff_observed" => "Git diff",
            "directive_consumed" => "Directive accepted",
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

    private static Label AgentConsoleTinyStatus(string text, Color color)
    {
        var label = AgentConsoleLabel(text, 10, color, bold: true);
        label.CustomMinimumSize = new Vector2(92f, 42f);
        label.HorizontalAlignment = HorizontalAlignment.Center;
        label.VerticalAlignment = VerticalAlignment.Center;
        label.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.985f, 0.992f, 0.998f, 0.98f),
            new Color(0.86f, 0.91f, 0.96f, 0.72f),
            16,
            1));
        return label;
    }

    private static Label AgentConsoleMetric(string title, string value, Color accent)
    {
        var label = AgentConsoleLabel($"{title}\n{value}", 10, AgentConsoleInk);
        label.CustomMinimumSize = new Vector2(0f, 48f);
        label.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        label.VerticalAlignment = VerticalAlignment.Center;
        label.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        label.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(accent.R, accent.G, accent.B, 0.055f),
            Colors.Transparent,
            11,
            0));
        return label;
    }

    private static void SetAgentMetric(Label label, string title, string value, Color accent)
    {
        if (label == null)
            return;
        label.Text = $"{title}\n{value}";
        label.AddThemeColorOverride("font_color", AgentConsoleInk);
        label.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(accent.R, accent.G, accent.B, 0.055f),
            Colors.Transparent,
            11,
            0));
    }

    private static string AgentActorGlyph(string actor, string eventType)
    {
        string normalized = (actor ?? "").Trim().ToLowerInvariant();
        string type = (eventType ?? "").Trim().ToLowerInvariant();
        if (normalized == "eris" || type.StartsWith("supervisor_", StringComparison.Ordinal)) return "◇";
        if (normalized == "user" || type == "user_directive") return "●";
        if (normalized is "executor" or "gemini") return "✦";
        if (normalized == "tool" || type.StartsWith("tool_", StringComparison.Ordinal)) return "⌘";
        return "·";
    }

    private static Button AgentConsoleQuietButton(string text, Action onPressed, float width, bool danger = false)
    {
        Color accent = danger ? AgentConsoleRed : AgentConsoleMuted;
        var button = new Button
        {
            Text = text,
            CustomMinimumSize = new Vector2(width, 34f),
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        button.AddThemeFontSizeOverride("font_size", 10);
        button.AddThemeColorOverride("font_color", accent);
        button.AddThemeColorOverride("font_hover_color", danger ? AgentConsoleRed : AgentConsoleInk);
        button.AddThemeColorOverride("font_disabled_color", new Color(AgentConsoleFaint.R, AgentConsoleFaint.G, AgentConsoleFaint.B, 0.42f));
        button.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.985f, 0.992f, 0.998f, 0.82f),
            new Color(0.86f, 0.91f, 0.96f, 0.55f),
            11,
            1));
        button.AddThemeStyleboxOverride("hover", AgentConsoleStyle(
            danger ? new Color(1f, 0.95f, 0.96f, 1f) : new Color(0.95f, 0.98f, 1f, 1f),
            danger ? new Color(AgentConsoleRed.R, AgentConsoleRed.G, AgentConsoleRed.B, 0.22f) : new Color(0.80f, 0.89f, 0.98f, 0.80f),
            11,
            1));
        button.AddThemeStyleboxOverride("pressed", AgentConsoleStyle(new Color(accent.R, accent.G, accent.B, 0.08f), Colors.Transparent, 11, 0));
        button.AddThemeStyleboxOverride("disabled", new StyleBoxEmpty());
        button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
        if (onPressed != null)
            button.Pressed += onPressed;
        return button;
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
            style.ShadowColor = new Color(0.12f, 0.08f, 0.10f, 0.14f);
            style.ShadowSize = 10;
        }
        return style;
    }

    private static Button AgentConsoleButton(string text, Action onPressed, bool primary, bool danger = false)
    {
        Color accent = danger ? AgentConsoleRed : (primary ? AgentConsolePink : AgentConsoleMuted);
        var button = new Button
        {
            Text = text,
            CustomMinimumSize = new Vector2(96f, 42f),
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        StyleBoxFlat normal = AgentConsoleStyle(
            primary ? new Color(0.96f, 0.33f, 0.60f, 0.98f) : new Color(1f, 1f, 1f, 0.90f),
            primary ? new Color(0.96f, 0.33f, 0.60f, 0.90f) : new Color(accent.R, accent.G, accent.B, 0.24f),
            16,
            1,
            shadow: primary);
        StyleBoxFlat hover = (StyleBoxFlat)normal.Duplicate();
        hover.BgColor = primary ? new Color(0.98f, 0.39f, 0.65f, 1f) : new Color(0.97f, 0.98f, 1f, 1f);
        StyleBoxFlat disabled = (StyleBoxFlat)normal.Duplicate();
        disabled.BgColor = new Color(0.96f, 0.94f, 0.95f, 0.46f);
        disabled.BorderColor = new Color(0.82f, 0.78f, 0.80f, 0.28f);
        button.AddThemeStyleboxOverride("normal", normal);
        button.AddThemeStyleboxOverride("hover", hover);
        button.AddThemeStyleboxOverride("pressed", hover);
        button.AddThemeStyleboxOverride("disabled", disabled);
        button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
        button.AddThemeColorOverride("font_color", primary ? Colors.White : accent);
        button.AddThemeColorOverride("font_hover_color", primary ? Colors.White : AgentConsoleInk);
        button.AddThemeColorOverride("font_disabled_color", new Color(0.55f, 0.50f, 0.52f, 0.42f));
        button.AddThemeFontSizeOverride("font_size", 12);
        if (onPressed != null)
            button.Pressed += onPressed;
        return button;
    }

    private static void StyleAgentConsoleInput(LineEdit input)
    {
        if (input == null)
            return;
        input.CustomMinimumSize = new Vector2(260f, 40f);
        input.AddThemeFontSizeOverride("font_size", 11);
        input.AddThemeColorOverride("font_color", AgentConsoleInk);
        input.AddThemeColorOverride("font_placeholder_color", new Color(AgentConsoleMuted.R, AgentConsoleMuted.G, AgentConsoleMuted.B, 0.68f));
        input.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.985f, 0.990f, 0.997f, 0.92f), Colors.Transparent, 12, 0));
        input.AddThemeStyleboxOverride("focus", AgentConsoleStyle(
            new Color(1f, 1f, 1f, 1f), new Color(0.78f, 0.88f, 0.98f, 0.76f), 12, 1));
    }
}
