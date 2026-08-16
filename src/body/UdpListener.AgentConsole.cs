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
        public double CreatedAt { get; set; }
        public double StartedAt { get; set; }
        public double FinishedAt { get; set; }
        public double UpdatedAt { get; set; }
        public string Source { get; set; } = "";
        public string TaskMode { get; set; } = "execute";
        public string WorkspaceId { get; set; } = "";
        public string WorkspacePath { get; set; } = "";
        public string WorkspaceName { get; set; } = "";
    }
    private sealed class AgentWorkspaceView
    {
        public string WorkspaceId { get; set; } = "";
        public string DisplayName { get; set; } = "";
        public string Path { get; set; } = "";
        public string SourceType { get; set; } = "";
        public string Branch { get; set; } = "";
        public bool Favorite { get; set; }
        public bool Active { get; set; }
        public double LastOpenedAt { get; set; }
    }


    // V3: visual pass bám mockup đã chốt. Agent Console giờ là execution UI thật,
    // không còn cảm giác admin dashboard pastel vô hồn.
    private static readonly Vector2 AgentConsolePreferredSize = new(1440f, 820f);
    private static readonly Vector2 AgentConsoleMinimumSize = new(920f, 620f);
    private const float AgentConsoleViewportPaddingX = 40f;
    private const float AgentConsoleViewportPaddingY = 44f;
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
    private static readonly Color AgentConsoleSidebarBg = new(0.072f, 0.102f, 0.162f, 0.985f);
    private static readonly Color AgentConsoleSidebarAccent = new(0.19f, 0.89f, 0.75f, 1f);

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
    private Button _agentConsoleSendButton;
    private Button _agentConsoleNewTaskButton;
    private Button _agentConsoleWorkspaceToggleButton;
    private Button _agentConsoleStatusToggleButton;
    private Button _agentConsoleAutopilotButton;
    private Control _agentConsoleWorkspaceStrip;
    private OptionButton _agentConsoleWorkspaceSelect;
    private Button _agentConsoleWorkspaceFavoriteButton;
    private HBoxContainer _agentConsoleSavedWorkspaceList;
    private FileDialog _agentConsoleWorkspaceDialog;
    private OptionButton _agentConsoleTaskModeSelect;
    private OptionButton _agentConsoleModelSelect;
    private OptionButton _agentConsoleEventKindSelect;
    private LineEdit _agentConsoleEventSearchInput;
    private Button _agentConsoleEventSearchToggle;
    private ProgressBar _agentConsoleProgressBar;
    private Label _agentConsoleProgressMetaLabel;
    private Label _agentConsoleInspectorWorkspaceLabel;
    private Label _agentConsoleInspectorWorkspaceMetaLabel;
    private VBoxContainer _agentConsoleInspectorSkillsList;
    private Button _agentConsoleInspectorOpenWorkspaceButton;
    private static Font _agentConsoleFontRegular;
    private static Font _agentConsoleFontBold;
    private readonly List<AgentConsoleTaskView> _agentConsoleTasks = new();
    private string _agentSelectedTaskId = "";
    private string _agentLastRequestId = "";
    private ulong _agentLastSnapshotRequestMs;
    private ulong _agentLastPacketMs;
    private bool _agentConsoleTaskDrawerVisible;
    private bool _agentConsoleWorkspaceVisible = true;
    private bool _agentConsoleInspectorVisible = true;
    private bool _agentConsoleAutoFollow = true;
    private bool _agentConsoleCreatingTask;
    private string _agentConsoleEventFilter = "all";
    private string _agentConsoleEventKindFilter = "all";
    private readonly List<AgentWorkspaceView> _agentConsoleWorkspaces = new();
    private string _agentConsoleActiveWorkspaceId = "";
    private string _agentConsoleWorkspaceUiSignature = "";

    private void BuildAgentConsoleUi()
    {
        if (_agentConsolePanel != null)
            return;

        _agentConsolePanel = new Panel
        {
            Name = "AgentConsolePanel",
            Visible = false,
            CustomMinimumSize = Vector2.Zero,
            Size = AgentConsolePreferredSize,
            ZIndex = 100,
            ClipContents = true,
        };
        _agentConsolePanel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.985f, 0.989f, 0.995f, 0.995f),
            new Color(0.84f, 0.88f, 0.93f, 0.88f),
            30,
            1,
            shadow: true));
        ApplyAgentConsoleTheme();
        GetNode<Control>("CanvasLayer/Control").AddChild(_agentConsolePanel);

        var margin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        margin.AddThemeConstantOverride("margin_left", 24);
        margin.AddThemeConstantOverride("margin_right", 24);
        margin.AddThemeConstantOverride("margin_top", 18);
        margin.AddThemeConstantOverride("margin_bottom", 14);
        _agentConsolePanel.AddChild(margin);

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 8);
        margin.AddChild(root);

        root.AddChild(BuildAgentConsoleHeader());
        _agentConsoleWorkspaceStrip = BuildAgentWorkspaceStrip();
        _agentConsoleWorkspaceStrip.Visible = _agentConsoleWorkspaceVisible;
        root.AddChild(_agentConsoleWorkspaceStrip);
        root.AddChild(BuildAgentQuickSummary());
        root.AddChild(BuildAgentConsoleBody());
        root.AddChild(BuildAgentConsoleFooter());
        BuildAgentWorkspaceDialog();
        RefreshAgentConsole();
    }

    private Control BuildAgentSidebar()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(104f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            AgentConsoleSidebarBg,
            new Color(AgentConsoleSidebarAccent.R, AgentConsoleSidebarAccent.G, AgentConsoleSidebarAccent.B, 0.22f),
            24,
            1,
            shadow: false));

        var margin = AgentConsoleMargin(14, 16, 14, 16);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 18);
        margin.AddChild(box);

        var logoWrap = new CenterContainer { CustomMinimumSize = new Vector2(0f, 56f), MouseFilter = Control.MouseFilterEnum.Ignore };
        var logo = new Label
        {
            Text = "◈",
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            CustomMinimumSize = new Vector2(54f, 54f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        logo.AddThemeFontSizeOverride("font_size", 28);
        logo.AddThemeColorOverride("font_color", AgentConsoleSidebarAccent);
        logo.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.08f, 0.16f, 0.24f, 0.84f),
            new Color(AgentConsoleSidebarAccent.R, AgentConsoleSidebarAccent.G, AgentConsoleSidebarAccent.B, 0.25f),
            18,
            1,
            shadow: true));
        logoWrap.AddChild(logo);
        box.AddChild(logoWrap);

        box.AddChild(BuildAgentSidebarNav("⌘", "Công việc", active: true));
        box.AddChild(BuildAgentSidebarNav("◌", "Phiên"));
        box.AddChild(BuildAgentSidebarNav("▦", "Tools"));
        box.AddChild(BuildAgentSidebarNav("⌁", "Logs"));
        box.AddChild(BuildAgentSidebarNav("⚙", "Cài đặt"));

        box.AddChild(new Control { SizeFlagsVertical = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore });

        var status = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        status.AddThemeConstantOverride("separation", 3);
        status.AddChild(AgentConsoleLabel("● Eris Online", 10, new Color(0.57f, 0.95f, 0.75f, 1f), bold: true));
        status.AddChild(AgentConsoleLabel("v1.9.3", 9, new Color(0.60f, 0.72f, 0.82f, 0.90f)));
        box.AddChild(status);
        return panel;
    }

    private Control BuildAgentSidebarNav(string icon, string text, bool active = false)
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(0f, 44f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            active ? new Color(0.13f, 0.22f, 0.30f, 0.96f) : Colors.Transparent,
            Colors.Transparent,
            12,
            0));

        var margin = AgentConsoleMargin(10, 6, 10, 6);
        panel.AddChild(margin);
        var row = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 8);
        margin.AddChild(row);

        var iconLabel = AgentConsoleLabel(icon, 14, active ? AgentConsoleSidebarAccent : new Color(0.72f, 0.82f, 0.90f, 0.88f), bold: true);
        iconLabel.CustomMinimumSize = new Vector2(18f, 0f);
        row.AddChild(iconLabel);
        var textLabel = AgentConsoleLabel(text, 11, active ? new Color(0.78f, 1f, 0.92f, 1f) : new Color(0.70f, 0.78f, 0.86f, 0.88f), bold: active);
        row.AddChild(textLabel);
        return panel;
    }

    private Control BuildAgentConsoleHeader()
    {
        var row = new HBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 54f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 12);

        var avatarShell = new PanelContainer
        {
            CustomMinimumSize = new Vector2(48f, 48f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
            ClipContents = true,
        };
        avatarShell.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.93f, 0.97f, 1f, 1f),
            new Color(0.82f, 0.89f, 0.96f, 1f),
            27,
            1));
        TextureRect avatar = AgentConsoleAssetImage("identity_portrait_eris.png.png", new Vector2(48f, 48f), TextureRect.StretchModeEnum.KeepAspectCovered);
        if (avatar != null)
            avatarShell.AddChild(avatar);
        else
        {
            var fallbackAvatar = AgentConsoleLabel("E", 24, new Color(0.33f, 0.52f, 0.96f, 1f), bold: true);
            fallbackAvatar.HorizontalAlignment = HorizontalAlignment.Center;
            fallbackAvatar.VerticalAlignment = VerticalAlignment.Center;
            avatarShell.AddChild(fallbackAvatar);
        }
        row.AddChild(avatarShell);

        var titleBox = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        titleBox.AddThemeConstantOverride("separation", 3);
        titleBox.AddChild(AgentConsoleLabel("Eris • Agent Console", 24, AgentConsoleInk, bold: true));
        _agentConsoleTaskMetaLabel = AgentConsoleLabel("Gemini-powered AI companion", 10, AgentConsoleMuted);
        titleBox.AddChild(_agentConsoleTaskMetaLabel);
        titleBox.AddChild(AgentConsoleLabel("● Sẵn sàng", 10, AgentConsoleGreen, bold: true));
        row.AddChild(titleBox);

        _agentConsoleNewTaskButton = AgentConsoleButton("＋  Tạo task mới ✦", EnterAgentNewTaskMode, primary: true);
        _agentConsoleNewTaskButton.CustomMinimumSize = new Vector2(148f, 42f);
        row.AddChild(_agentConsoleNewTaskButton);

        _agentConsoleWorkspaceToggleButton = AgentConsoleQuietButton("▦  Workspaces", ToggleAgentWorkspaceStrip, 112f);
        row.AddChild(_agentConsoleWorkspaceToggleButton);

        _agentConsoleAutopilotButton = AgentConsoleQuietButton("〰  AUTOPILOT", ShowAgentAutopilotStatus, 112f);
        _agentConsoleAutopilotButton.AddThemeColorOverride("font_color", AgentConsolePink);
        row.AddChild(_agentConsoleAutopilotButton);

        _agentConsoleStatusToggleButton = AgentConsoleQuietButton("〰  Trạng thái", ToggleAgentTaskDrawer, 104f);
        row.AddChild(_agentConsoleStatusToggleButton);

        _agentConsoleInspectorToggleButton = AgentConsoleQuietButton("ⓘ  Chi tiết", ToggleAgentInspector, 98f);
        row.AddChild(_agentConsoleInspectorToggleButton);
        row.AddChild(AgentConsoleQuietButton("↻", () => SendAgentControl("snapshot"), 44f));
        var close = CreateWindowControlButton("×", CloseAgentConsolePanel, 38f, 18);
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
        body.AddThemeConstantOverride("separation", 16);

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
            CustomMinimumSize = new Vector2(0f, 0f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 0);

        _agentConsoleTaskTitleLabel = AgentConsoleLabel("Chưa có task", 18, AgentConsoleInk, bold: true);
        _agentConsoleTaskTitleLabel.Visible = false;

        var streamSurface = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        streamSurface.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            Colors.White,
            new Color(0.88f, 0.91f, 0.96f, 0.95f),
            22,
            1,
            shadow: true));
        var streamMargin = AgentConsoleMargin(18, 14, 18, 14);
        streamSurface.AddChild(streamMargin);
        var streamBox = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        streamBox.AddThemeConstantOverride("separation", 12);
        streamMargin.AddChild(streamBox);
        streamBox.AddChild(BuildAgentFilterBar());
        _agentConsoleEventScroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
        };
        ApplyHiddenScrollBarTheme(_agentConsoleEventScroll.GetVScrollBar());
        streamBox.AddChild(_agentConsoleEventScroll);
        _agentConsoleEventList = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            CustomMinimumSize = new Vector2(0f, 360f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _agentConsoleEventList.AddThemeConstantOverride("separation", 10);
        _agentConsoleEventScroll.AddChild(_agentConsoleEventList);
        root.AddChild(streamSurface);
        return root;
    }

    private Control BuildAgentWorkspaceStrip()
    {
        var panel = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            Colors.White,
            new Color(0.88f, 0.91f, 0.96f, 0.95f),
            22,
            1,
            shadow: true));
        var margin = AgentConsoleMargin(16, 10, 16, 10);
        panel.AddChild(margin);
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 16);
        margin.AddChild(row);

        var left = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        left.AddThemeConstantOverride("separation", 5);
        left.AddChild(AgentConsoleLabel("WORKSPACE", 9, AgentConsoleFaint, bold: true));
        var workspaceRow = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        workspaceRow.AddThemeConstantOverride("separation", 8);

        _agentConsoleWorkspaceSelect = new OptionButton
        {
            CustomMinimumSize = new Vector2(250f, 38f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            FocusMode = Control.FocusModeEnum.None,
        };
        StyleAgentConsoleOptionButton(_agentConsoleWorkspaceSelect);
        _agentConsoleWorkspaceSelect.ItemSelected += OnAgentWorkspaceSelected;
        workspaceRow.AddChild(_agentConsoleWorkspaceSelect);

        _agentConsoleWorkspaceFavoriteButton = AgentConsoleQuietButton("☆  Lưu", ToggleAgentWorkspaceFavorite, 76f);
        workspaceRow.AddChild(_agentConsoleWorkspaceFavoriteButton);
        workspaceRow.AddChild(AgentConsoleQuietButton("🗁  Mở thư mục", ShowAgentWorkspaceDialog, 116f));
        left.AddChild(workspaceRow);
        row.AddChild(left);

        var divider = new VSeparator();
        divider.Modulate = new Color(0.90f, 0.92f, 0.96f, 1f);
        row.AddChild(divider);

        var right = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        right.AddThemeConstantOverride("separation", 5);
        right.AddChild(AgentConsoleLabel("WORKSPACE ĐÃ LƯU", 9, AgentConsoleFaint, bold: true));
        _agentConsoleSavedWorkspaceList = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        _agentConsoleSavedWorkspaceList.AddThemeConstantOverride("separation", 8);
        right.AddChild(_agentConsoleSavedWorkspaceList);
        row.AddChild(right);
        return panel;
    }

    private Button AgentWorkspaceChip(string text, Color accent)
    {
        var button = AgentConsoleQuietButton(text, null, 124f);
        button.AddThemeColorOverride("font_color", accent);
        return button;
    }

    private Control AgentConsoleToolChip(string text, Color accent)
    {
        var button = AgentConsoleQuietButton(text, null, 36f);
        button.CustomMinimumSize = new Vector2(36f, 32f);
        button.AddThemeFontSizeOverride("font_size", 10);
        button.AddThemeColorOverride("font_color", accent);
        return button;
    }

    private TextureRect AgentConsoleAssetImage(string fileName, Vector2 size, TextureRect.StretchModeEnum stretchMode)
    {
        string path = ResolveIdentityAssetPath(IdentityAsset(fileName));
        if (!ResourceLoader.Exists(path))
            return null;
        return new TextureRect
        {
            Texture = GD.Load<Texture2D>(path),
            CustomMinimumSize = size,
            Size = size,
            ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
            StretchMode = stretchMode,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
    }

    private void ApplyAgentConsoleTheme()
    {
        var theme = _agentConsolePanel.Theme ?? new Theme();
        theme.DefaultFont = AgentConsoleFont(false);
        _agentConsolePanel.Theme = theme;
    }

    private static Font AgentConsoleFont(bool bold)
    {
        if (bold)
        {
            _agentConsoleFontBold ??= new SystemFont
            {
                FontNames = new[] { "Segoe UI Semibold", "Segoe UI", "Inter", "Arial" },
                FontWeight = 650,
            };
            return _agentConsoleFontBold;
        }

        _agentConsoleFontRegular ??= new SystemFont
        {
            FontNames = new[] { "Segoe UI", "Inter", "Arial" },
            FontWeight = 400,
        };
        return _agentConsoleFontRegular;
    }

    private Control BuildAgentQuickSummary()
    {
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 12);
        _agentConsoleStepLabel = AgentConsoleMetric(@"STEP
—
Chưa chạy", new Color(0.97f, 0.985f, 1f, 1f), new Color(0.26f, 0.47f, 0.96f, 1f));
        _agentConsoleTestsLabel = AgentConsoleMetric(@"TESTS
—
Chưa chạy", new Color(0.97f, 0.995f, 0.98f, 1f), new Color(0.30f, 0.76f, 0.56f, 1f));
        _agentConsoleFilesLabel = AgentConsoleMetric(@"FILES
—
Chưa thay đổi", Colors.White, new Color(0.36f, 0.52f, 0.96f, 1f));
        _agentConsoleCheckpointLabel = AgentConsoleMetric(@"CHECKPOINT
—
Chưa thiết lập", new Color(1f, 0.985f, 0.97f, 1f), new Color(0.90f, 0.63f, 0.22f, 1f));
        _agentConsoleSkillsLabel = AgentConsoleMetric(@"SKILLS
—
Chờ task", new Color(0.987f, 0.975f, 1f, 1f), new Color(0.64f, 0.44f, 0.96f, 1f));
        row.AddChild(_agentConsoleStepLabel);
        row.AddChild(_agentConsoleTestsLabel);
        row.AddChild(_agentConsoleFilesLabel);
        row.AddChild(_agentConsoleCheckpointLabel);
        row.AddChild(_agentConsoleSkillsLabel);
        return row;
    }

    private Control BuildAgentFilterBar()
    {
        var root = new VBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 44f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 6);

        var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 8);
        _agentConsoleFilterAllButton = AgentConsoleFilterButton("◈  Timeline", "all");
        _agentConsoleFilterConversationButton = AgentConsoleFilterButton("◌  Hội thoại", "conversation");
        _agentConsoleFilterToolsButton = AgentConsoleFilterButton("⚒  Công cụ", "tools");
        row.AddChild(_agentConsoleFilterAllButton);
        row.AddChild(_agentConsoleFilterConversationButton);
        row.AddChild(_agentConsoleFilterToolsButton);
        row.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore });

        _agentConsoleEventKindSelect = new OptionButton { CustomMinimumSize = new Vector2(148f, 36f), FocusMode = Control.FocusModeEnum.None };
        StyleAgentConsoleOptionButton(_agentConsoleEventKindSelect);
        _agentConsoleEventKindSelect.AddItem("Tất cả sự kiện");
        _agentConsoleEventKindSelect.AddItem("Quan trọng");
        _agentConsoleEventKindSelect.AddItem("Lỗi / cảnh báo");
        _agentConsoleEventKindSelect.AddItem("Thay đổi file");
        _agentConsoleEventKindSelect.AddItem("Tests");
        _agentConsoleEventKindSelect.ItemSelected += OnAgentEventKindSelected;
        row.AddChild(_agentConsoleEventKindSelect);

        _agentConsoleEventSearchToggle = AgentConsoleQuietButton("⌕", ToggleAgentEventSearch, 42f);
        row.AddChild(_agentConsoleEventSearchToggle);
        _agentConsoleFollowButton = AgentConsoleQuietButton("⇅", ToggleAgentAutoFollow, 42f);
        _agentConsoleFollowButton.TooltipText = "Theo dõi event mới";
        row.AddChild(_agentConsoleFollowButton);
        root.AddChild(row);

        _agentConsoleEventSearchInput = new LineEdit
        {
            PlaceholderText = "Tìm trong timeline: tool, file, lỗi, checkpoint...",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            Visible = false,
            ClearButtonEnabled = true,
        };
        StyleAgentConsoleInput(_agentConsoleEventSearchInput);
        _agentConsoleEventSearchInput.CustomMinimumSize = new Vector2(0f, 36f);
        _agentConsoleEventSearchInput.TextChanged += _ => RebuildAgentEventStream();
        root.AddChild(_agentConsoleEventSearchInput);

        RefreshAgentFilterButtons();
        return root;
    }

    private PanelContainer BuildAgentInspectorPane()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(400f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            Colors.White,
            new Color(0.88f, 0.91f, 0.96f, 0.95f),
            22,
            1,
            shadow: true));
        var margin = AgentConsoleMargin(18, 16, 18, 16);
        panel.AddChild(margin);
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 12);
        margin.AddChild(box);

        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        var title = AgentConsoleLabel("Phiên làm việc", 18, AgentConsoleInk, bold: true);
        title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        top.AddChild(title);
        _agentConsoleStatusLabel = AgentConsoleLabel("● Sẵn sàng", 11, AgentConsoleGreen, bold: true);
        top.AddChild(_agentConsoleStatusLabel);
        top.AddChild(AgentConsoleQuietButton("⌃", ToggleAgentInspector, 34f));
        box.AddChild(top);

        box.AddChild(AgentConsoleLabel("Tiến trình tổng quan", 13, AgentConsoleInk, bold: true));
        _agentConsoleProgressBar = new ProgressBar
        {
            MinValue = 0,
            MaxValue = 100,
            Value = 0,
            ShowPercentage = false,
            CustomMinimumSize = new Vector2(0f, 10f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _agentConsoleProgressBar.AddThemeStyleboxOverride("background", AgentConsoleStyle(new Color(0.93f,0.95f,0.98f,1f), Colors.Transparent, 5, 0));
        _agentConsoleProgressBar.AddThemeStyleboxOverride("fill", AgentConsoleStyle(new Color(0.65f,0.76f,1f,1f), Colors.Transparent, 5, 0));
        box.AddChild(_agentConsoleProgressBar);
        _agentConsoleProgressMetaLabel = AgentConsoleLabel("Chưa có task đang chạy.", 11, AgentConsoleMuted);
        _agentConsoleProgressMetaLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(_agentConsoleProgressMetaLabel);

        var detailScroll = new ScrollContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
            VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
            ClipContents = true,
            MouseFilter = Control.MouseFilterEnum.Stop,
        };
        ApplyHiddenScrollBarTheme(detailScroll.GetVScrollBar());
        box.AddChild(detailScroll);

        var detailBox = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        detailBox.AddThemeConstantOverride("separation", 14);
        detailScroll.AddChild(detailBox);

        var workspaceSection = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        workspaceSection.AddThemeConstantOverride("separation", 6);
        var workspaceTop = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        var workspaceTitle = AgentConsoleLabel("Workspace", 16, AgentConsoleInk, bold: true);
        workspaceTitle.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        workspaceTop.AddChild(workspaceTitle);
        _agentConsoleInspectorOpenWorkspaceButton = AgentConsoleQuietButton("Mở thư mục", OpenSelectedTaskWorkspace, 98f);
        workspaceTop.AddChild(_agentConsoleInspectorOpenWorkspaceButton);
        workspaceSection.AddChild(workspaceTop);
        _agentConsoleInspectorWorkspaceLabel = AgentConsoleLabel("Chưa khóa workspace", 13, AgentConsoleInk, bold: true);
        workspaceSection.AddChild(_agentConsoleInspectorWorkspaceLabel);
        _agentConsoleInspectorWorkspaceMetaLabel = AgentConsoleLabel("—", 11, AgentConsoleMuted);
        _agentConsoleInspectorWorkspaceMetaLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        workspaceSection.AddChild(_agentConsoleInspectorWorkspaceMetaLabel);
        detailBox.AddChild(workspaceSection);

        var taskSection = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        taskSection.AddThemeConstantOverride("separation", 6);
        taskSection.AddChild(AgentConsoleLabel("Thông tin task", 16, AgentConsoleInk, bold: true));
        _agentConsoleInspectorLabel = AgentConsoleLabel("Chưa chọn task", 12, AgentConsoleMuted);
        _agentConsoleInspectorLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        taskSection.AddChild(_agentConsoleInspectorLabel);
        _agentConsoleInspectorDetailLabel = AgentConsoleLabel("—", 11, AgentConsoleMuted);
        _agentConsoleInspectorDetailLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        taskSection.AddChild(_agentConsoleInspectorDetailLabel);
        detailBox.AddChild(taskSection);

        var toolSection = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        toolSection.AddThemeConstantOverride("separation", 8);
        toolSection.AddChild(AgentConsoleLabel("Kỹ năng & Công cụ", 16, AgentConsoleInk, bold: true));
        _agentConsoleInspectorSkillsList = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        _agentConsoleInspectorSkillsList.AddThemeConstantOverride("separation", 6);
        toolSection.AddChild(_agentConsoleInspectorSkillsList);
        detailBox.AddChild(toolSection);
        return panel;
    }

    private Control BuildAgentConsoleFooter()
    {
        var panel = new PanelContainer
        {
            CustomMinimumSize = new Vector2(0f, 62f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            Colors.White,
            new Color(0.88f, 0.91f, 0.96f, 0.95f),
            22,
            1,
            shadow: true));
        var margin = AgentConsoleMargin(14, 8, 14, 8);
        panel.AddChild(margin);
        var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 8);
        margin.AddChild(row);

        _agentConsolePauseButton = AgentConsoleQuietButton("Ⅱ  Tạm dừng", () => SendAgentControl("pause"), 106f);
        _agentConsoleResumeButton = AgentConsoleQuietButton("▶  Tiếp tục", () => SendAgentControl("resume"), 106f);
        _agentConsoleStopButton = AgentConsoleQuietButton("□  Dừng", () => SendAgentControl("stop"), 86f);
        _agentConsoleRollbackButton = AgentConsoleQuietButton("⟲  Rollback", () => SendAgentControl("rollback", checkpointId: SelectedAgentTask()?.CheckpointId ?? ""), 108f);
        row.AddChild(_agentConsolePauseButton);
        row.AddChild(_agentConsoleResumeButton);
        row.AddChild(_agentConsoleStopButton);
        row.AddChild(_agentConsoleRollbackButton);

        _agentConsoleTaskModeSelect = new OptionButton { CustomMinimumSize = new Vector2(104f, 42f), FocusMode = Control.FocusModeEnum.None };
        StyleAgentConsoleOptionButton(_agentConsoleTaskModeSelect);
        _agentConsoleTaskModeSelect.AddItem("Execute");
        _agentConsoleTaskModeSelect.AddItem("Inspect");
        _agentConsoleTaskModeSelect.Visible = false;
        row.AddChild(_agentConsoleTaskModeSelect);

        _agentConsoleModelSelect = new OptionButton { CustomMinimumSize = new Vector2(160f, 42f), FocusMode = Control.FocusModeEnum.None };
        StyleAgentConsoleOptionButton(_agentConsoleModelSelect);
        _agentConsoleModelSelect.AddItem("gemini-3-flash", 0);
        _agentConsoleModelSelect.AddItem("gemini-exp", 1);
        _agentConsoleModelSelect.AddItem("playwright/gemini-3-flash", 2);
        _agentConsoleModelSelect.AddItem("atlas/gemini-2.5-pro", 3);
        _agentConsoleModelSelect.Visible = false;
        row.AddChild(_agentConsoleModelSelect);

        _agentConsoleDirectiveInput = new LineEdit
        {
            PlaceholderText = "Chỉ thị cho Gemini...",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            ClearButtonEnabled = true,
        };
        StyleAgentConsoleInput(_agentConsoleDirectiveInput);
        _agentConsoleDirectiveInput.TextSubmitted += _ => SubmitAgentComposer();
        row.AddChild(_agentConsoleDirectiveInput);

        _agentConsoleSendButton = AgentConsoleButton("Gửi ➤", SubmitAgentComposer, primary: true);
        _agentConsoleSendButton.CustomMinimumSize = new Vector2(116f, 46f);
        row.AddChild(_agentConsoleSendButton);

        _agentConsoleControlStatusLabel = AgentConsoleLabel("", 9, AgentConsoleFaint);
        _agentConsoleControlStatusLabel.CustomMinimumSize = new Vector2(155f, 0f);
        _agentConsoleControlStatusLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        row.AddChild(_agentConsoleControlStatusLabel);
        return panel;
    }

    private void ToggleAgentTaskDrawer()
    {
        _agentConsoleTaskDrawerVisible = !_agentConsoleTaskDrawerVisible;
        if (_agentConsoleTaskDrawer != null)
            _agentConsoleTaskDrawer.Visible = _agentConsoleTaskDrawerVisible;
        if (_agentConsoleStatusToggleButton != null)
            _agentConsoleStatusToggleButton.Text = _agentConsoleTaskDrawerVisible ? "〰  Đóng task" : "〰  Trạng thái";
    }

    private void ToggleAgentInspector()
    {
        _agentConsoleInspectorVisible = !_agentConsoleInspectorVisible;
        if (_agentConsoleInspectorDrawer != null)
            _agentConsoleInspectorDrawer.Visible = _agentConsoleInspectorVisible;
        if (_agentConsoleInspectorToggleButton != null)
            _agentConsoleInspectorToggleButton.Text = _agentConsoleInspectorVisible ? "ⓘ  Chi tiết" : "ⓘ  Mở chi tiết";
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
        button.AddThemeColorOverride("font_color", active ? AgentConsolePink : AgentConsoleMuted);
        button.AddThemeColorOverride("font_hover_color", active ? AgentConsolePink : AgentConsoleInk);
        button.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            Colors.Transparent,
            Colors.Transparent,
            8,
            0));
        button.AddThemeStyleboxOverride("hover", AgentConsoleStyle(
            new Color(0.98f,0.985f,0.995f,1f),
            Colors.Transparent,
            8,
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

    private static bool AgentEventMatchesKind(AgentConsoleEventView ev, string kind)
    {
        if (ev == null || string.IsNullOrWhiteSpace(kind) || kind == "all")
            return true;
        string type = (ev.Type ?? "").Trim().ToLowerInvariant();
        if (kind == "important")
            return ev.Importance >= 0.75f;
        if (kind == "errors")
            return type.Contains("fail", StringComparison.Ordinal)
                || type.Contains("error", StringComparison.Ordinal)
                || type.Contains("veto", StringComparison.Ordinal)
                || type.Contains("permission", StringComparison.Ordinal)
                || ev.Importance >= 0.90f;
        if (kind == "files")
            return type.Contains("file", StringComparison.Ordinal)
                || type.Contains("diff", StringComparison.Ordinal)
                || type.Contains("patch", StringComparison.Ordinal);
        if (kind == "tests")
            return type.Contains("test", StringComparison.Ordinal);
        return true;
    }

    private static bool AgentEventMatchesSearch(AgentConsoleEventView ev, string query)
    {
        string needle = (query ?? "").Trim();
        if (ev == null || string.IsNullOrWhiteSpace(needle))
            return true;
        string haystack = string.Join("\n", new[] { ev.Type, ev.Actor, ev.Summary, ev.Detail, ev.DataText });
        return haystack.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
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
        float availableWidth = Mathf.Max(520f, viewport.X - AgentConsoleViewportPaddingX * 2f);
        float availableHeight = Mathf.Max(440f, viewport.Y - AgentConsoleViewportPaddingY * 2f);
        Vector2 target = new(
            Mathf.Min(AgentConsolePreferredSize.X, availableWidth),
            Mathf.Min(AgentConsolePreferredSize.Y, availableHeight));
        if (availableWidth >= AgentConsoleMinimumSize.X)
            target.X = Mathf.Max(target.X, AgentConsoleMinimumSize.X);
        if (availableHeight >= AgentConsoleMinimumSize.Y)
            target.Y = Mathf.Max(target.Y, AgentConsoleMinimumSize.Y);
        _agentConsolePanel.Size = target;
        _agentConsolePanel.Position = new Vector2(
            Mathf.Max(AgentConsoleViewportPaddingX, (viewport.X - target.X) * 0.5f),
            Mathf.Max(AgentConsoleViewportPaddingY, (viewport.Y - target.Y) * 0.5f));
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

    private void BuildAgentWorkspaceDialog()
    {
        if (_agentConsoleWorkspaceDialog != null || _agentConsolePanel == null)
            return;
        _agentConsoleWorkspaceDialog = new FileDialog
        {
            Title = "Chọn workspace cho Eris",
            Access = FileDialog.AccessEnum.Filesystem,
            FileMode = FileDialog.FileModeEnum.OpenDir,
            Size = new Vector2I(860, 600),
        };
        _agentConsoleWorkspaceDialog.DirSelected += path =>
        {
            string selected = (path ?? "").Trim();
            if (!string.IsNullOrWhiteSpace(selected))
                SendAgentControl("workspace_open", workspaceRef: selected);
        };
        _agentConsolePanel.AddChild(_agentConsoleWorkspaceDialog);
    }

    private void ShowAgentWorkspaceDialog()
    {
        BuildAgentWorkspaceDialog();
        _agentConsoleWorkspaceDialog?.PopupCentered(new Vector2I(860, 600));
    }

    private void ToggleAgentWorkspaceStrip()
    {
        _agentConsoleWorkspaceVisible = !_agentConsoleWorkspaceVisible;
        if (_agentConsoleWorkspaceStrip != null)
            _agentConsoleWorkspaceStrip.Visible = _agentConsoleWorkspaceVisible;
        if (_agentConsoleWorkspaceToggleButton != null)
            _agentConsoleWorkspaceToggleButton.Text = _agentConsoleWorkspaceVisible ? "▦  Workspaces" : "▦  Workspaces";
    }

    private void ShowAgentAutopilotStatus()
    {
        SetAgentConsoleControlStatus("AUTOPILOT: read/search/patch/test/build/shell dev chạy tự động; protected boundary bị chặn.");
    }

    private void EnterAgentNewTaskMode()
    {
        _agentConsoleCreatingTask = true;
        if (_agentConsoleTaskModeSelect != null)
            _agentConsoleTaskModeSelect.Visible = true;
        if (_agentConsoleModelSelect != null)
            _agentConsoleModelSelect.Visible = true;
        if (_agentConsoleSendButton != null)
            _agentConsoleSendButton.Text = "Tạo Task ✦";
        if (_agentConsoleDirectiveInput != null)
        {
            _agentConsoleDirectiveInput.Editable = true;
            _agentConsoleDirectiveInput.PlaceholderText = "Mục tiêu hoặc yêu cầu sửa lỗi...";
            _agentConsoleDirectiveInput.GrabFocus();
        }
        SetAgentConsoleControlStatus("Task mới sẽ khóa workspace đang chọn và chạy bằng Gemini autopilot.");
        RefreshAgentConsoleControls();
    }

    private void ExitAgentNewTaskMode()
    {
        _agentConsoleCreatingTask = false;
        if (_agentConsoleTaskModeSelect != null)
            _agentConsoleTaskModeSelect.Visible = false;
        if (_agentConsoleModelSelect != null)
            _agentConsoleModelSelect.Visible = false;
        if (_agentConsoleSendButton != null)
            _agentConsoleSendButton.Text = "Gửi ➤";
        if (_agentConsoleDirectiveInput != null)
            _agentConsoleDirectiveInput.PlaceholderText = "Chỉ thị cho Gemini...";
        RefreshAgentConsoleControls();
    }

    private void SubmitAgentComposer()
    {
        string text = (_agentConsoleDirectiveInput?.Text ?? "").Trim();
        if (string.IsNullOrWhiteSpace(text))
        {
            SetAgentConsoleControlStatus(_agentConsoleCreatingTask ? "Mục tiêu task đang trống." : "Chỉ thị đang trống.", error: true);
            return;
        }

        if (_agentConsoleCreatingTask || SelectedAgentTask() == null)
        {
            string mode = (_agentConsoleTaskModeSelect?.Selected ?? 0) == 1 ? "inspect" : "execute";
            string model = "gemini-3-flash";
            if (_agentConsoleModelSelect != null)
                model = _agentConsoleModelSelect.GetItemText(_agentConsoleModelSelect.Selected);

            SendAgentControl(
                "create_task",
                text: text,
                workspaceRef: _agentConsoleActiveWorkspaceId,
                taskMode: mode,
                model: model);
            if (_agentConsoleDirectiveInput != null)
                _agentConsoleDirectiveInput.Text = "";
            ExitAgentNewTaskMode();
            return;
        }

        SendAgentDirective();
    }

    private void OnAgentWorkspaceSelected(long index)
    {
        int selected = (int)index;
        if (selected < 0 || selected >= _agentConsoleWorkspaces.Count)
            return;
        AgentWorkspaceView workspace = _agentConsoleWorkspaces[selected];
        if (!string.IsNullOrWhiteSpace(workspace.WorkspaceId)
            && !string.Equals(workspace.WorkspaceId, _agentConsoleActiveWorkspaceId, StringComparison.Ordinal))
            SendAgentControl("workspace_switch", workspaceRef: workspace.WorkspaceId);
    }

    private void ToggleAgentWorkspaceFavorite()
    {
        AgentWorkspaceView active = ActiveAgentWorkspace();
        if (active == null)
        {
            SetAgentConsoleControlStatus("Chưa có workspace để lưu.", error: true);
            return;
        }
        SendAgentControl(active.Favorite ? "workspace_unfavorite" : "workspace_favorite", workspaceRef: active.WorkspaceId);
    }

    private AgentWorkspaceView ActiveAgentWorkspace()
    {
        foreach (AgentWorkspaceView item in _agentConsoleWorkspaces)
            if (string.Equals(item.WorkspaceId, _agentConsoleActiveWorkspaceId, StringComparison.Ordinal))
                return item;
        return null;
    }

    private void OpenSelectedTaskWorkspace()
    {
        AgentConsoleTaskView task = SelectedAgentTask();
        string path = task?.WorkspacePath ?? "";
        if (string.IsNullOrWhiteSpace(path))
            path = ActiveAgentWorkspace()?.Path ?? "";
        if (string.IsNullOrWhiteSpace(path))
        {
            SetAgentConsoleControlStatus("Task chưa có workspace để mở.", error: true);
            return;
        }
        Error error = OS.ShellOpen(path);
        SetAgentConsoleControlStatus(error == Error.Ok ? $"Đã mở {path}" : $"Không mở được workspace: {error}", error: error != Error.Ok);
    }

    private void OnAgentEventKindSelected(long index)
    {
        _agentConsoleEventKindFilter = index switch
        {
            1 => "important",
            2 => "errors",
            3 => "files",
            4 => "tests",
            _ => "all",
        };
        RebuildAgentEventStream();
    }

    private void ToggleAgentEventSearch()
    {
        if (_agentConsoleEventSearchInput == null)
            return;
        _agentConsoleEventSearchInput.Visible = !_agentConsoleEventSearchInput.Visible;
        if (_agentConsoleEventSearchInput.Visible)
            _agentConsoleEventSearchInput.GrabFocus();
        else if (!string.IsNullOrWhiteSpace(_agentConsoleEventSearchInput.Text))
        {
            _agentConsoleEventSearchInput.Text = "";
            RebuildAgentEventStream();
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
        if (SelectedAgentTask() == null)
        {
            EnterAgentNewTaskMode();
            SubmitAgentComposer();
            return;
        }
        SendAgentControl("directive", text: text);
        if (_agentConsoleDirectiveInput != null)
            _agentConsoleDirectiveInput.Text = "";
    }

    private void SendAgentControl(
        string action,
        string text = "",
        string checkpointId = "",
        bool quiet = false,
        string workspaceRef = "",
        string taskMode = "",
        string model = "")
    {
        if (_chatSend == null)
            return;
        string normalized = (action ?? "").Trim().ToLowerInvariant();
        bool taskRequired = normalized is "pause" or "resume" or "stop" or "rollback" or "directive";
        if (taskRequired && string.IsNullOrWhiteSpace(_agentSelectedTaskId))
        {
            SetAgentConsoleControlStatus("Chưa chọn task để điều khiển.", error: true);
            return;
        }

        _agentLastRequestId = $"agent-{Time.GetTicksMsec()}-{GD.Randi()}";
        var payload = new Dictionary<string, object>
        {
            ["type"] = "agent_control",
            ["action"] = normalized,
            ["request_id"] = _agentLastRequestId,
            ["task_id"] = taskRequired ? _agentSelectedTaskId : "",
            ["selected_task_id"] = _agentSelectedTaskId,
        };
        if (!string.IsNullOrWhiteSpace(text))
            payload["text"] = text;
        if (!string.IsNullOrWhiteSpace(checkpointId))
            payload["checkpoint_id"] = checkpointId;
        if (!string.IsNullOrWhiteSpace(workspaceRef))
            payload["workspace_ref"] = workspaceRef;
        if (!string.IsNullOrWhiteSpace(taskMode))
            payload["task_mode"] = taskMode;
        if (!string.IsNullOrWhiteSpace(model))
            payload["model"] = model;

        Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
        if (error != Error.Ok)
        {
            SetAgentConsoleControlStatus($"Không gửi được Agent control: {error}", error: true);
            return;
        }
        _agentLastSnapshotRequestMs = Time.GetTicksMsec();
        if (!quiet)
        {
            string status = normalized switch
            {
                "create_task" => "Đã giao task; đang chờ Gemini khởi tạo phiên.",
                "workspace_open" => "Đang đăng ký workspace...",
                "workspace_switch" => "Đang chuyển workspace...",
                "workspace_favorite" => "Đang lưu workspace thường dùng...",
                "workspace_unfavorite" => "Đang bỏ ghim workspace...",
                "snapshot" => "Đang đồng bộ Agent Console...",
                _ => $"Đã gửi {normalized}; executor sẽ nhận ở node boundary.",
            };
            SetAgentConsoleControlStatus(status);
        }
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

        if (console.TryGetProperty("workspace_state", out JsonElement workspaceState)
            && workspaceState.ValueKind == JsonValueKind.Object)
            ApplyAgentWorkspaceSnapshot(workspaceState);
    }

    private void ApplyAgentWorkspaceSnapshot(JsonElement state)
    {
        _agentConsoleActiveWorkspaceId = AgentReadJsonString(state, "active_workspace_id");
        _agentConsoleWorkspaces.Clear();
        if (state.TryGetProperty("workspaces", out JsonElement items) && items.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement node in items.EnumerateArray())
            {
                if (node.ValueKind != JsonValueKind.Object)
                    continue;
                var workspace = new AgentWorkspaceView
                {
                    WorkspaceId = AgentReadJsonString(node, "workspace_id"),
                    DisplayName = AgentReadJsonString(node, "display_name"),
                    Path = AgentReadJsonString(node, "path"),
                    SourceType = AgentReadJsonString(node, "source_type"),
                    Branch = AgentReadJsonString(node, "default_branch"),
                    Favorite = AgentReadJsonBool(node, "favorite"),
                    Active = AgentReadJsonBool(node, "active"),
                    LastOpenedAt = AgentReadJsonDouble(node, "last_opened_at"),
                };
                if (!string.IsNullOrWhiteSpace(workspace.WorkspaceId))
                    _agentConsoleWorkspaces.Add(workspace);
            }
        }
        RefreshAgentWorkspaceUi();
    }

    private void RefreshAgentWorkspaceUi()
    {
        var signatureBuilder = new StringBuilder(_agentConsoleActiveWorkspaceId);
        foreach (AgentWorkspaceView item in _agentConsoleWorkspaces)
            signatureBuilder.Append('|').Append(item.WorkspaceId).Append(':').Append(item.DisplayName).Append(':').Append(item.Branch).Append(':').Append(item.Favorite).Append(':').Append(item.Active);
        string signature = signatureBuilder.ToString();
        if (string.Equals(signature, _agentConsoleWorkspaceUiSignature, StringComparison.Ordinal)
            && _agentConsoleWorkspaceSelect != null
            && _agentConsoleWorkspaceSelect.ItemCount > 0
            && _agentConsoleSavedWorkspaceList != null
            && _agentConsoleSavedWorkspaceList.GetChildCount() > 0)
            return;
        _agentConsoleWorkspaceUiSignature = signature;

        if (_agentConsoleWorkspaceSelect != null)
        {
            _agentConsoleWorkspaceSelect.ItemSelected -= OnAgentWorkspaceSelected;
            _agentConsoleWorkspaceSelect.Clear();
            int selectedIndex = -1;
            for (int i = 0; i < _agentConsoleWorkspaces.Count; i++)
            {
                AgentWorkspaceView workspace = _agentConsoleWorkspaces[i];
                string branch = string.IsNullOrWhiteSpace(workspace.Branch) ? "" : $" / {workspace.Branch}";
                _agentConsoleWorkspaceSelect.AddItem($"🗀  {workspace.DisplayName}{branch}");
                if (workspace.Active || string.Equals(workspace.WorkspaceId, _agentConsoleActiveWorkspaceId, StringComparison.Ordinal))
                    selectedIndex = i;
            }
            if (_agentConsoleWorkspaces.Count == 0)
            {
                _agentConsoleWorkspaceSelect.AddItem("Chưa có workspace");
                _agentConsoleWorkspaceSelect.Disabled = true;
            }
            else
            {
                _agentConsoleWorkspaceSelect.Disabled = false;
                _agentConsoleWorkspaceSelect.Selected = Math.Max(0, selectedIndex);
            }
            _agentConsoleWorkspaceSelect.ItemSelected += OnAgentWorkspaceSelected;
        }

        AgentWorkspaceView active = ActiveAgentWorkspace();
        if (_agentConsoleWorkspaceFavoriteButton != null)
        {
            _agentConsoleWorkspaceFavoriteButton.Disabled = active == null;
            _agentConsoleWorkspaceFavoriteButton.Text = active?.Favorite == true ? "★  Đã lưu" : "☆  Lưu";
        }

        if (_agentConsoleSavedWorkspaceList != null)
        {
            ClearAgentChildren(_agentConsoleSavedWorkspaceList);
            int count = 0;
            foreach (AgentWorkspaceView workspace in _agentConsoleWorkspaces)
            {
                if (!workspace.Favorite || count >= 4)
                    continue;
                string workspaceId = workspace.WorkspaceId;
                var chip = AgentWorkspaceChip(
                    $"{(workspace.Active ? "●" : "✧")}  {CompactAgentText(workspace.DisplayName, 20)}",
                    workspace.Active ? AgentConsoleGreen : AgentConsoleMuted);
                chip.Pressed += () => SendAgentControl("workspace_switch", workspaceRef: workspaceId);
                _agentConsoleSavedWorkspaceList.AddChild(chip);
                count++;
            }
            var add = AgentWorkspaceChip("＋  Thêm", AgentConsoleFaint);
            add.Pressed += ShowAgentWorkspaceDialog;
            _agentConsoleSavedWorkspaceList.AddChild(add);
        }
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
        target.CreatedAt = source.CreatedAt;
        target.StartedAt = source.StartedAt;
        target.FinishedAt = source.FinishedAt;
        target.UpdatedAt = source.UpdatedAt;
        target.Source = source.Source;
        target.TaskMode = source.TaskMode;
        target.WorkspaceId = source.WorkspaceId;
        target.WorkspacePath = source.WorkspacePath;
        target.WorkspaceName = source.WorkspaceName;
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
            CreatedAt = AgentReadJsonDouble(node, "created_at"),
            StartedAt = AgentReadJsonDouble(node, "started_at"),
            FinishedAt = AgentReadJsonDouble(node, "finished_at"),
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
        if (node.TryGetProperty("metadata", out JsonElement metadata) && metadata.ValueKind == JsonValueKind.Object)
        {
            task.Source = AgentReadJsonString(metadata, "source");
            task.TaskMode = AgentReadJsonString(metadata, "task_mode");
            task.WorkspaceId = AgentReadJsonString(metadata, "workspace_id");
            task.WorkspacePath = AgentReadJsonString(metadata, "workspace_path");
            task.WorkspaceName = AgentReadJsonString(metadata, "workspace_name");
        }
        if (string.IsNullOrWhiteSpace(task.TaskMode)) task.TaskMode = "execute";
        if (node.TryGetProperty("events", out JsonElement events) && events.ValueKind == JsonValueKind.Array)
            foreach (JsonElement eventNode in events.EnumerateArray())
            {
                AgentConsoleEventView ev = ParseAgentEvent(eventNode);
                if (ev != null)
                    task.Events.Add(ev);
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
        RefreshAgentWorkspaceUi();
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
            var empty = AgentConsoleLabel("Chưa có task. Bấm Tạo task mới hoặc giao việc dài hạn từ chat Eris.", 10, AgentConsoleMuted);
            empty.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            _agentConsoleTaskList.AddChild(empty);
            return;
        }

        foreach (AgentConsoleTaskView task in _agentConsoleTasks)
        {
            AgentConsoleTaskView captured = task;
            bool selected = string.Equals(task.TaskId, _agentSelectedTaskId, StringComparison.Ordinal);
            string mode = string.Equals(task.TaskMode, "inspect", StringComparison.OrdinalIgnoreCase) ? "inspect" : "execute";
            string source = string.IsNullOrWhiteSpace(task.Source) ? "agent" : task.Source.Replace('_', ' ');
            var button = new Button
            {
                Text = $"{AgentStatusGlyph(task.Status)}  {CompactAgentText(task.Goal, 36)}\n     {AgentStatusLabel(task.Status)} · {mode} · {source}",
                CustomMinimumSize = new Vector2(0f, 60f),
                SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
                Alignment = HorizontalAlignment.Left,
                FocusMode = Control.FocusModeEnum.None,
                MouseDefaultCursorShape = Control.CursorShape.PointingHand,
            };
            button.AddThemeFontOverride("font", AgentConsoleFont(false));
            button.AddThemeFontSizeOverride("font_size", 10);
            button.AddThemeColorOverride("font_color", selected ? AgentConsoleInk : AgentConsoleMuted);
            StyleBoxFlat normal = AgentConsoleStyle(
                selected ? new Color(1f, 0.975f, 0.99f, 0.94f) : Colors.Transparent,
                selected ? new Color(AgentConsolePink.R, AgentConsolePink.G, AgentConsolePink.B, 0.22f) : Colors.Transparent,
                12,
                selected ? 1 : 0);
            StyleBoxFlat hover = AgentConsoleStyle(
                new Color(1f, 1f, 1f, 0.82f),
                new Color(AgentConsoleBorder.R, AgentConsoleBorder.G, AgentConsoleBorder.B, 0.48f),
                12,
                1);
            button.AddThemeStyleboxOverride("normal", normal);
            button.AddThemeStyleboxOverride("hover", hover);
            button.AddThemeStyleboxOverride("pressed", hover);
            button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
            button.Pressed += () =>
            {
                _agentSelectedTaskId = captured.TaskId;
                ExitAgentNewTaskMode();
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
            _agentConsoleEventList.AddChild(BuildAgentEmptyState("Giao việc từ chat Eris hoặc tạo task trực tiếp tại đây. Timeline sẽ chỉ hiển thị event thật."));
            CallDeferred(nameof(ResetAgentConsoleEventScrollTop));
            return;
        }

        _agentConsoleTaskTitleLabel.Text = string.IsNullOrWhiteSpace(task.ClarifiedGoal) ? task.Goal : task.ClarifiedGoal;
        int start = Math.Max(0, task.Events.Count - 200);
        int rendered = 0;
        for (int i = start; i < task.Events.Count; i++)
        {
            AgentConsoleEventView ev = task.Events[i];
            if (!AgentEventMatchesFilter(ev, _agentConsoleEventFilter))
                continue;
            if (!AgentEventMatchesKind(ev, _agentConsoleEventKindFilter))
                continue;
            if (!AgentEventMatchesSearch(ev, _agentConsoleEventSearchInput?.Text ?? ""))
                continue;
            _agentConsoleEventList.AddChild(BuildAgentEventCard(ev));
            rendered++;
        }
        if (rendered == 0)
        {
            string message = task.Events.Count == 0
                ? "Task đã được tạo. Đang chờ event đầu tiên từ AgentHarness."
                : "Không có event nào khớp bộ lọc / tìm kiếm hiện tại.";
            _agentConsoleEventList.AddChild(BuildAgentEmptyState(message));
            CallDeferred(nameof(ResetAgentConsoleEventScrollTop));
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
        bool isEris = string.Equals(ev.Actor, "eris", StringComparison.OrdinalIgnoreCase)
            || (ev.Type ?? "").StartsWith("supervisor_", StringComparison.Ordinal);
        bool isUser = string.Equals(ev.Actor, "user", StringComparison.OrdinalIgnoreCase)
            || string.Equals(ev.Type, "user_directive", StringComparison.OrdinalIgnoreCase);

        var outer = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        outer.AddThemeConstantOverride("separation", 8);

        // Eris và user lệch nhẹ sang phải để timeline có nhịp hội thoại thay vì
        // một cột card giống nhau từ trên xuống dưới.
        if (isEris || isUser)
        {
            var indent = new Control
            {
                CustomMinimumSize = new Vector2(isUser ? 72f : 34f, 0f),
                MouseFilter = Control.MouseFilterEnum.Ignore,
            };
            outer.AddChild(indent);
        }

        var panel = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        Color bubble = isEris
            ? new Color(1.0f, 0.955f, 0.973f, 0.96f)
            : isUser
                ? new Color(0.955f, 0.970f, 0.995f, 0.96f)
                : new Color(0.968f, 0.982f, 0.973f, 0.96f);
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            bubble,
            new Color(accent.R, accent.G, accent.B, ev.Importance >= 0.85f ? 0.34f : 0.18f),
            13,
            1));
        var margin = AgentConsoleMargin(12, 9, 12, 9);
        panel.AddChild(margin);
        var box = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        box.AddThemeConstantOverride("separation", 4);
        margin.AddChild(box);

        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        Label actorLabel = AgentConsoleLabel(AgentActorLabel(ev.Actor, ev.Type), 9, accent, bold: true);
        actorLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        top.AddChild(actorLabel);
        if (ev.Step > 0)
            top.AddChild(AgentConsoleLabel($"{ev.Step}", 8, AgentConsoleFaint));
        box.AddChild(top);

        Label summary = AgentConsoleLabel(
            string.IsNullOrWhiteSpace(ev.Summary) ? AgentEventLabel(ev.Type) : ev.Summary,
            12,
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
        if (!(isEris || isUser))
        {
            var rightBreathingRoom = new Control
            {
                CustomMinimumSize = new Vector2(38f, 0f),
                MouseFilter = Control.MouseFilterEnum.Ignore,
            };
            outer.AddChild(rightBreathingRoom);
        }
        return outer;
    }

    private Control BuildAgentCompactEvent(AgentConsoleEventView ev)
    {
        Color accent = AgentActorColor(ev.Actor, ev.Type);
        var panel = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        panel.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(AgentConsoleSoft.R, AgentConsoleSoft.G, AgentConsoleSoft.B, 0.56f),
            new Color(accent.R, accent.G, accent.B, 0.10f),
            10,
            1));
        var margin = AgentConsoleMargin(10, 6, 10, 6);
        panel.AddChild(margin);
        var row = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 8);
        margin.AddChild(row);

        Label dot = AgentConsoleLabel("●", 8, accent, bold: true);
        dot.CustomMinimumSize = new Vector2(12f, 0f);
        row.AddChild(dot);
        Label kind = AgentConsoleLabel(AgentEventLabel(ev.Type), 9, accent, bold: true);
        kind.CustomMinimumSize = new Vector2(92f, 0f);
        row.AddChild(kind);
        Label summary = AgentConsoleLabel(
            string.IsNullOrWhiteSpace(ev.Summary) ? AgentActorLabel(ev.Actor, ev.Type) : CompactAgentText(ev.Summary, 190),
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
        return panel;
    }

    private Control BuildAgentEmptyState(string message)
    {
        var outer = new CenterContainer
        {
            CustomMinimumSize = new Vector2(0f, 235f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        var box = new VBoxContainer { CustomMinimumSize = new Vector2(420f, 180f), MouseFilter = Control.MouseFilterEnum.Ignore };
        box.AddThemeConstantOverride("separation", 8);
        outer.AddChild(box);
        TextureRect thread = AgentConsoleAssetImage("identity_trace_thread_crystal.png", new Vector2(250f, 92f), TextureRect.StretchModeEnum.KeepAspectCentered);
        if (thread != null)
        {
            thread.Modulate = new Color(1f, 1f, 1f, 0.72f);
            var imageWrap = new CenterContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
            imageWrap.AddChild(thread);
            box.AddChild(imageWrap);
        }
        else
        {
            var icon = AgentConsoleLabel("◇", 48, new Color(0.97f, 0.68f, 0.84f, 1f), bold: true);
            icon.HorizontalAlignment = HorizontalAlignment.Center;
            box.AddChild(icon);
        }
        Label title = AgentConsoleLabel("Chưa có task đang chạy", 16, AgentConsoleInk, bold: true);
        title.HorizontalAlignment = HorizontalAlignment.Center;
        box.AddChild(title);
        Label detail = AgentConsoleLabel(@"Hãy giao việc cho Eris. Gemini sẽ lập kế hoạch, sử dụng công cụ,
chạy task và cập nhật tiến trình tại đây.", 11, AgentConsoleMuted);
        detail.HorizontalAlignment = HorizontalAlignment.Center;
        box.AddChild(detail);
        var cta = AgentConsoleButton("＋  Tạo task mới", EnterAgentNewTaskMode, primary: false);
        cta.CustomMinimumSize = new Vector2(146f, 38f);
        var wrap = new CenterContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        wrap.AddChild(cta);
        box.AddChild(wrap);
        return outer;
    }





    private void RefreshAgentInspectorForTask()
    {
        AgentConsoleTaskView task = SelectedAgentTask();
        if (_agentConsoleInspectorLabel == null || _agentConsoleInspectorDetailLabel == null)
            return;

        if (task == null)
        {
            _agentConsoleInspectorLabel.Text = "Chưa chọn task";
            _agentConsoleInspectorDetailLabel.Text = "Tạo task mới hoặc chọn một task trong Trạng thái.";
            if (_agentConsoleTaskMetaLabel != null)
                _agentConsoleTaskMetaLabel.Text = "Gemini-powered AI companion";
            if (_agentConsoleStatusLabel != null)
            {
                _agentConsoleStatusLabel.Text = "● Sẵn sàng";
                _agentConsoleStatusLabel.AddThemeColorOverride("font_color", AgentConsoleGreen);
            }
            AgentWorkspaceView active = ActiveAgentWorkspace();
            if (_agentConsoleInspectorWorkspaceLabel != null)
                _agentConsoleInspectorWorkspaceLabel.Text = active == null ? "Chưa có workspace" : active.DisplayName;
            if (_agentConsoleInspectorWorkspaceMetaLabel != null)
                _agentConsoleInspectorWorkspaceMetaLabel.Text = active == null
                    ? "Mở một thư mục để dùng làm workspace mặc định."
                    : $"{active.Path}\nNhánh: {(string.IsNullOrWhiteSpace(active.Branch) ? "—" : active.Branch)} · active";
            if (_agentConsoleInspectorOpenWorkspaceButton != null)
                _agentConsoleInspectorOpenWorkspaceButton.Disabled = active == null;
            if (_agentConsoleProgressBar != null)
                _agentConsoleProgressBar.Value = 0;
            if (_agentConsoleProgressMetaLabel != null)
                _agentConsoleProgressMetaLabel.Text = "Chưa có task đang chạy.";
            RefreshAgentInspectorSkills(null);
            SetAgentQuickSummary(null);
            return;
        }

        _agentConsoleInspectorLabel.Text = CompactAgentText(task.Goal, 150);
        if (_agentConsoleTaskMetaLabel != null)
            _agentConsoleTaskMetaLabel.Text = $"{AgentStatusLabel(task.Status)} · {task.Events.Count} event · {task.Executor}";
        if (_agentConsoleStatusLabel != null)
        {
            _agentConsoleStatusLabel.Text = $"● {AgentStatusLabel(task.Status)}";
            _agentConsoleStatusLabel.AddThemeColorOverride("font_color", AgentStatusColor(task.Status));
        }
        SetAgentQuickSummary(task);

        string workspaceName = string.IsNullOrWhiteSpace(task.WorkspaceName) ? "Không khóa workspace" : task.WorkspaceName;
        if (_agentConsoleInspectorWorkspaceLabel != null)
            _agentConsoleInspectorWorkspaceLabel.Text = workspaceName;
        if (_agentConsoleInspectorWorkspaceMetaLabel != null)
        {
            var ws = new StringBuilder();
            ws.AppendLine(string.IsNullOrWhiteSpace(task.WorkspacePath) ? "—" : task.WorkspacePath);
            if (!string.IsNullOrWhiteSpace(task.WorkspaceId)) ws.AppendLine($"ID: {task.WorkspaceId}");
            ws.Append($"Task locked: {(string.IsNullOrWhiteSpace(task.WorkspacePath) ? "không" : "có")}");
            _agentConsoleInspectorWorkspaceMetaLabel.Text = ws.ToString();
        }
        if (_agentConsoleInspectorOpenWorkspaceButton != null)
            _agentConsoleInspectorOpenWorkspaceButton.Disabled = string.IsNullOrWhiteSpace(task.WorkspacePath);

        double started = task.StartedAt > 0 ? task.StartedAt : task.CreatedAt;
        double end = task.FinishedAt > 0 ? task.FinishedAt : DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        double elapsed = started > 0 ? Math.Max(0, end - started) : 0;
        double progress = AgentTaskProgressEstimate(task);
        if (_agentConsoleProgressBar != null)
            _agentConsoleProgressBar.Value = progress;
        if (_agentConsoleProgressMetaLabel != null)
            _agentConsoleProgressMetaLabel.Text = $"Ước tính {progress:0}% · bước {task.CurrentStep} · {AgentDurationText(elapsed)} · {AgentStatusLabel(task.Status)}";

        var sb = new StringBuilder();
        sb.AppendLine($"Task ID          {task.TaskId}");
        sb.AppendLine($"Nguồn            {(string.IsNullOrWhiteSpace(task.Source) ? "—" : task.Source)}");
        sb.AppendLine($"Chế độ           {(string.Equals(task.TaskMode, "inspect", StringComparison.OrdinalIgnoreCase) ? "Inspect-only" : "Execute / Autopilot")}");
        sb.AppendLine($"Executor         {task.Executor}{(string.IsNullOrWhiteSpace(task.Model) ? "" : $" · {task.Model}")}");
        sb.AppendLine($"Trạng thái       {AgentStatusLabel(task.Status)}");
        sb.AppendLine($"Bước             {task.CurrentStep}");
        if (task.CreatedAt > 0) sb.AppendLine($"Tạo lúc           {AgentDateTimeText(task.CreatedAt)}");
        if (task.StartedAt > 0) sb.AppendLine($"Bắt đầu           {AgentDateTimeText(task.StartedAt)}");
        if (task.FinishedAt > 0) sb.AppendLine($"Kết thúc          {AgentDateTimeText(task.FinishedAt)}");
        if (task.PendingControls > 0) sb.AppendLine($"Chỉ thị chờ       {task.PendingControls}");
        sb.AppendLine();
        sb.AppendLine($"Tests             {task.TestsPassed} pass · {task.TestsFailed} fail");
        if (!string.IsNullOrWhiteSpace(task.TestsSummary)) sb.AppendLine(task.TestsSummary);
        sb.AppendLine($"Files changed     {task.ChangedFiles.Count}");
        sb.AppendLine($"Checkpoint        {(string.IsNullOrWhiteSpace(task.CheckpointId) ? "—" : task.CheckpointId)}");
        _agentConsoleInspectorDetailLabel.Text = sb.ToString().TrimEnd();
        RefreshAgentInspectorSkills(task);
    }

    private void RefreshAgentInspectorSkills(AgentConsoleTaskView task)
    {
        if (_agentConsoleInspectorSkillsList == null)
            return;
        ClearAgentChildren(_agentConsoleInspectorSkillsList);
        if (task == null || task.ActiveSkills.Count == 0)
        {
            _agentConsoleInspectorSkillsList.AddChild(AgentConsoleLabel("Chưa activate skill nào.", 10, AgentConsoleMuted));
            return;
        }
        int shown = 0;
        foreach (string skill in task.ActiveSkills)
        {
            if (shown++ >= 10) break;
            _agentConsoleInspectorSkillsList.AddChild(AgentConsoleChip(CompactAgentText(skill, 36), AgentConsoleBlue));
        }
    }

    private void SetAgentQuickSummary(AgentConsoleTaskView task)
    {
        if (_agentConsoleStepLabel == null)
            return;
        if (task == null)
        {
            _agentConsoleStepLabel.Text = "STEP\n—\nChưa chạy";
            _agentConsoleTestsLabel.Text = "TESTS\n—\nChưa chạy";
            _agentConsoleFilesLabel.Text = "FILES\n—\nChưa thay đổi";
            _agentConsoleCheckpointLabel.Text = "CHECKPOINT\n—\nChưa thiết lập";
            _agentConsoleSkillsLabel.Text = "SKILLS\n—\nChờ task";
            return;
        }
        _agentConsoleStepLabel.Text = $"STEP\n{task.CurrentStep}\n{AgentStatusLabel(task.Status)}";
        _agentConsoleTestsLabel.Text = task.TestsPassed == 0 && task.TestsFailed == 0
            ? "TESTS\n—\nChưa chạy"
            : $"TESTS\n{task.TestsPassed}✓  {task.TestsFailed}×\n{CompactAgentText(task.TestsSummary, 22)}";
        _agentConsoleFilesLabel.Text = task.ChangedFiles.Count == 0
            ? "FILES\n—\nChưa thay đổi"
            : $"FILES\n{task.ChangedFiles.Count}\nĐã thay đổi";
        _agentConsoleCheckpointLabel.Text = string.IsNullOrWhiteSpace(task.CheckpointId)
            ? "CHECKPOINT\n—\nChưa thiết lập"
            : $"CHECKPOINT\n{CompactAgentText(task.CheckpointId, 14)}\n{task.CheckpointCount} bản lưu";
        _agentConsoleSkillsLabel.Text = task.ActiveSkills.Count == 0
            ? "SKILLS\n—\nĐang discovery"
            : $"SKILLS\n{task.ActiveSkills.Count}\n{CompactAgentText(string.Join(", ", task.ActiveSkills), 24)}";
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
        bool terminal = AgentTaskTerminal(status);

        if (_agentConsolePauseButton != null)
        {
            _agentConsolePauseButton.Visible = status != "paused";
            _agentConsolePauseButton.Disabled = _agentConsoleCreatingTask || !hasTask || terminal || status != "running";
        }
        if (_agentConsoleResumeButton != null)
        {
            _agentConsoleResumeButton.Visible = status == "paused";
            _agentConsoleResumeButton.Disabled = _agentConsoleCreatingTask || !hasTask || status != "paused";
        }
        if (_agentConsoleStopButton != null)
            _agentConsoleStopButton.Disabled = _agentConsoleCreatingTask || !hasTask || terminal;
        if (_agentConsoleRollbackButton != null)
            _agentConsoleRollbackButton.Disabled = _agentConsoleCreatingTask || !hasTask || string.IsNullOrWhiteSpace(task?.CheckpointId);
        if (_agentConsoleTaskModeSelect != null)
            _agentConsoleTaskModeSelect.Visible = _agentConsoleCreatingTask;
        if (_agentConsoleDirectiveInput != null)
            _agentConsoleDirectiveInput.Editable = _agentConsoleCreatingTask || (hasTask && !terminal);
        if (_agentConsoleSendButton != null)
            _agentConsoleSendButton.Disabled = !_agentConsoleCreatingTask && (!hasTask || terminal);
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
        AgentConsoleTaskView task = SelectedAgentTask();
        if (task == null || task.Events.Count == 0)
        {
            ResetAgentConsoleEventScrollTop();
            return;
        }
        VScrollBar bar = _agentConsoleEventScroll.GetVScrollBar();
        if (bar != null)
            bar.Value = bar.MaxValue;
    }

    private void ResetAgentConsoleEventScrollTop()
    {
        if (_agentConsoleEventScroll == null)
            return;
        VScrollBar bar = _agentConsoleEventScroll.GetVScrollBar();
        if (bar != null)
            bar.Value = 0;
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

    private static bool AgentReadJsonBool(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out JsonElement node))
            return false;
        if (node.ValueKind == JsonValueKind.True) return true;
        if (node.ValueKind == JsonValueKind.False) return false;
        return bool.TryParse(node.ToString(), out bool value) && value;
    }

    private static double AgentReadJsonDouble(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out JsonElement node))
            return 0.0;
        if (node.ValueKind == JsonValueKind.Number && node.TryGetDouble(out double value))
            return value;
        return double.TryParse(node.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out value) ? value : 0.0;
    }

    private static double AgentTaskProgressEstimate(AgentConsoleTaskView task)
    {
        if (task == null) return 0.0;
        string status = (task.Status ?? "").ToLowerInvariant();
        if (status == "completed") return 100.0;
        if (status is "failed" or "stopped") return 100.0;
        if (status == "queued") return 3.0;
        double byStep = 8.0 + Math.Min(82.0, Math.Max(0, task.CurrentStep) * 7.0);
        if (status == "paused") return Math.Min(92.0, byStep);
        return Math.Min(92.0, byStep);
    }

    private static string AgentDurationText(double seconds)
    {
        TimeSpan span = TimeSpan.FromSeconds(Math.Max(0, seconds));
        if (span.TotalHours >= 1)
            return $"{(int)span.TotalHours:00}:{span.Minutes:00}:{span.Seconds:00}";
        return $"{span.Minutes:00}:{span.Seconds:00}";
    }

    private static string AgentDateTimeText(double unix)
    {
        try
        {
            return DateTimeOffset.FromUnixTimeMilliseconds((long)(unix * 1000.0)).ToLocalTime().ToString("dd/MM HH:mm:ss", CultureInfo.InvariantCulture);
        }
        catch (ArgumentOutOfRangeException)
        {
            return "—";
        }
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
        label.AddThemeFontOverride("font", AgentConsoleFont(bold));
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
            Colors.White,
            new Color(0.86f, 0.91f, 0.96f, 0.72f),
            16,
            1));
        return label;
    }

    private static Label AgentConsoleMetric(string text, Color bg, Color accent)
    {
        var label = AgentConsoleLabel(text, 13, AgentConsoleInk);
        label.CustomMinimumSize = new Vector2(0f, 66f);
        label.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        label.VerticalAlignment = VerticalAlignment.Center;
        label.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        label.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            bg,
            new Color(accent.R, accent.G, accent.B, 0.16f),
            18,
            1));
        return label;
    }

    private static Button AgentConsoleQuietButton(string text, Action onPressed, float width, bool danger = false)
    {
        Color accent = danger ? AgentConsoleRed : AgentConsoleMuted;
        var button = new Button
        {
            Text = text,
            CustomMinimumSize = new Vector2(width, 40f),
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        button.AddThemeFontOverride("font", AgentConsoleFont(false));
        button.AddThemeFontSizeOverride("font_size", 11);
        button.AddThemeConstantOverride("h_separation", 8);
        button.AddThemeColorOverride("font_color", accent);
        button.AddThemeColorOverride("font_hover_color", danger ? AgentConsoleRed : AgentConsoleInk);
        button.AddThemeColorOverride("font_disabled_color", new Color(AgentConsoleFaint.R, AgentConsoleFaint.G, AgentConsoleFaint.B, 0.45f));
        StyleBoxFlat normal = AgentConsoleStyle(
            Colors.White,
            new Color(0.88f, 0.91f, 0.96f, 0.85f),
            14,
            1,
            shadow: true);
        normal.ShadowSize = 4;
        normal.ShadowColor = new Color(0.12f, 0.16f, 0.24f, 0.055f);
        normal.ContentMarginLeft = 12f;
        normal.ContentMarginRight = 12f;
        button.AddThemeStyleboxOverride("normal", normal);
        StyleBoxFlat hover = AgentConsoleStyle(
            new Color(0.985f, 0.989f, 0.997f, 1f),
            new Color(0.72f, 0.80f, 0.92f, 0.90f),
            14,
            1,
            shadow: true);
        hover.ShadowSize = 6;
        hover.ShadowColor = new Color(0.12f, 0.16f, 0.24f, 0.085f);
        hover.ContentMarginLeft = 12f;
        hover.ContentMarginRight = 12f;
        button.AddThemeStyleboxOverride("hover", hover);
        StyleBoxFlat pressed = AgentConsoleStyle(
            new Color(accent.R, accent.G, accent.B, 0.08f),
            new Color(accent.R, accent.G, accent.B, 0.20f),
            14,
            1);
        pressed.ContentMarginLeft = 12f;
        pressed.ContentMarginRight = 12f;
        button.AddThemeStyleboxOverride("pressed", pressed);
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
        Color accent = danger ? AgentConsoleRed : (primary ? AgentConsolePink : AgentConsolePink);
        var button = new Button
        {
            Text = text,
            CustomMinimumSize = new Vector2(96f, 42f),
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        button.AddThemeFontOverride("font", AgentConsoleFont(primary));
        StyleBoxFlat normal = AgentConsoleStyle(
            primary ? new Color(0.96f, 0.29f, 0.60f, 0.98f) : new Color(1f, 0.96f, 0.98f, 0.98f),
            new Color(accent.R, accent.G, accent.B, primary ? 0.88f : 0.28f),
            16,
            1,
            shadow: primary);
        normal.ContentMarginLeft = primary ? 18f : 14f;
        normal.ContentMarginRight = primary ? 18f : 14f;
        normal.ShadowSize = primary ? 12 : 4;
        normal.ShadowColor = primary
            ? new Color(0.82f, 0.12f, 0.42f, 0.22f)
            : new Color(0.20f, 0.15f, 0.22f, 0.06f);
        StyleBoxFlat hover = (StyleBoxFlat)normal.Duplicate();
        hover.BgColor = primary ? new Color(0.98f, 0.36f, 0.64f, 1f) : new Color(1f, 0.98f, 0.995f, 1f);
        hover.BorderColor = new Color(accent.R, accent.G, accent.B, primary ? 0.95f : 0.40f);
        StyleBoxFlat disabled = (StyleBoxFlat)normal.Duplicate();
        disabled.BgColor = new Color(0.96f, 0.94f, 0.95f, 0.46f);
        disabled.BorderColor = new Color(0.82f, 0.78f, 0.80f, 0.28f);
        button.AddThemeStyleboxOverride("normal", normal);
        button.AddThemeStyleboxOverride("hover", hover);
        button.AddThemeStyleboxOverride("pressed", hover);
        button.AddThemeStyleboxOverride("disabled", disabled);
        button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
        button.AddThemeColorOverride("font_color", primary ? Colors.White : AgentConsolePink);
        button.AddThemeColorOverride("font_hover_color", primary ? Colors.White : AgentConsolePink);
        button.AddThemeColorOverride("font_disabled_color", new Color(0.55f, 0.50f, 0.52f, 0.42f));
        button.AddThemeFontSizeOverride("font_size", 12);
        button.AddThemeConstantOverride("h_separation", 9);
        if (onPressed != null)
            button.Pressed += onPressed;
        return button;
    }

    private static void StyleAgentConsoleOptionButton(OptionButton option)
    {
        if (option == null)
            return;
        option.AddThemeFontOverride("font", AgentConsoleFont(false));
        option.AddThemeFontSizeOverride("font_size", 11);
        option.AddThemeColorOverride("font_color", AgentConsoleInk);
        option.AddThemeColorOverride("font_hover_color", AgentConsoleInk);
        option.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.995f, 0.997f, 1f, 0.98f),
            new Color(0.84f, 0.89f, 0.95f, 0.82f),
            14,
            1));
        option.AddThemeStyleboxOverride("hover", AgentConsoleStyle(
            Colors.White,
            new Color(0.78f, 0.86f, 0.97f, 0.95f),
            14,
            1));
        option.AddThemeStyleboxOverride("pressed", AgentConsoleStyle(
            Colors.White,
            new Color(0.78f, 0.86f, 0.97f, 0.95f),
            14,
            1));
        option.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
    }

    private static void StyleAgentConsoleInput(LineEdit input)
    {
        if (input == null)
            return;
        input.CustomMinimumSize = new Vector2(260f, 44f);
        input.AddThemeFontOverride("font", AgentConsoleFont(false));
        input.AddThemeFontSizeOverride("font_size", 12);
        input.AddThemeColorOverride("font_color", AgentConsoleInk);
        input.AddThemeColorOverride("font_placeholder_color", new Color(AgentConsoleMuted.R, AgentConsoleMuted.G, AgentConsoleMuted.B, 0.72f));
        input.AddThemeStyleboxOverride("normal", AgentConsoleStyle(
            new Color(0.995f, 0.997f, 1f, 0.98f), new Color(0.84f, 0.89f, 0.95f, 0.82f), 16, 1));
        input.AddThemeStyleboxOverride("focus", AgentConsoleStyle(
            Colors.White, new Color(0.80f, 0.87f, 0.97f, 0.95f), 16, 1));
    }
}
