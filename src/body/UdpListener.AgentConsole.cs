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
    private static Font _agentConsoleFontRegular;
    private static Font _agentConsoleFontBold;
    private readonly List<AgentConsoleTaskView> _agentConsoleTasks = new();
    private string _agentSelectedTaskId = "";
    private string _agentLastRequestId = "";
    private ulong _agentLastSnapshotRequestMs;
    private ulong _agentLastPacketMs;
    private bool _agentConsoleTaskDrawerVisible;
    private bool _agentConsoleInspectorVisible = true;
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
        root.AddChild(BuildAgentWorkspaceStrip());
        root.AddChild(BuildAgentQuickSummary());
        root.AddChild(BuildAgentConsoleBody());
        root.AddChild(BuildAgentConsoleFooter());
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

        var newTask = AgentConsoleButton("＋  Tạo task mới ✦", () =>
        {
            _agentConsoleDirectiveInput?.GrabFocus();
            _agentConsoleDirectiveInput?.SelectAll();
        }, primary: true);
        newTask.CustomMinimumSize = new Vector2(148f, 42f);
        row.AddChild(newTask);
        row.AddChild(AgentConsoleQuietButton("▦  Workspaces", null, 112f));
        var autopilot = AgentConsoleQuietButton("〰  AUTOPILOT", null, 112f);
        autopilot.AddThemeColorOverride("font_color", AgentConsolePink);
        row.AddChild(autopilot);
        row.AddChild(AgentConsoleQuietButton("〰  Trạng thái", null, 104f));
        _agentConsoleInspectorToggleButton = AgentConsoleQuietButton("ⓘ  Chi tiết", ToggleAgentInspector, 98f);
        row.AddChild(_agentConsoleInspectorToggleButton);
        row.AddChild(AgentConsoleQuietButton("⋯", () => SendAgentControl("snapshot"), 44f));
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
            16,
            1,
            shadow: true));
        var margin = AgentConsoleMargin(14, 9, 14, 9);
        panel.AddChild(margin);
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 14);
        margin.AddChild(row);

        var left = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        left.AddThemeConstantOverride("separation", 6);
        left.AddChild(AgentConsoleLabel("WORKSPACE", 9, AgentConsoleFaint, bold: true));
        var workspaceRow = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        workspaceRow.AddThemeConstantOverride("separation", 10);
        var workspaceSelect = AgentConsoleQuietButton("🗀  Eris-Core / build-beta  ▾", null, 250f);
        workspaceSelect.Alignment = HorizontalAlignment.Left;
        workspaceRow.AddChild(workspaceSelect);
        workspaceRow.AddChild(AgentConsoleQuietButton("☆  Lưu", null, 72f));
        workspaceRow.AddChild(AgentConsoleQuietButton("🗁  Mở thư mục", null, 112f));
        left.AddChild(workspaceRow);
        row.AddChild(left);

        var divider = new VSeparator();
        divider.Modulate = new Color(0.90f, 0.92f, 0.96f, 1f);
        row.AddChild(divider);

        var right = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        right.AddThemeConstantOverride("separation", 6);
        right.AddChild(AgentConsoleLabel("WORKSPACE ĐÃ LƯU", 9, AgentConsoleFaint, bold: true));
        var chips = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        chips.AddThemeConstantOverride("separation", 10);
        chips.AddChild(AgentWorkspaceChip("●  Eris-Core / main", new Color(0.34f, 0.79f, 0.61f, 1f)));
        chips.AddChild(AgentWorkspaceChip("✧  Research / eris-v2", new Color(0.56f, 0.56f, 0.94f, 1f)));
        chips.AddChild(AgentWorkspaceChip("▣  Docs", new Color(0.64f, 0.66f, 0.77f, 1f)));
        chips.AddChild(AgentWorkspaceChip("＋  Thêm", AgentConsoleFaint));
        right.AddChild(chips);
        row.AddChild(right);
        return panel;
    }

    private Control AgentWorkspaceChip(string text, Color accent)
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
0 / 12", new Color(0.97f, 0.985f, 1f, 1f), new Color(0.26f, 0.47f, 0.96f, 1f));
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
8
Sẵn sàng", new Color(0.987f, 0.975f, 1f, 1f), new Color(0.64f, 0.44f, 0.96f, 1f));
        row.AddChild(_agentConsoleStepLabel);
        row.AddChild(_agentConsoleTestsLabel);
        row.AddChild(_agentConsoleFilesLabel);
        row.AddChild(_agentConsoleCheckpointLabel);
        row.AddChild(_agentConsoleSkillsLabel);
        return row;
    }

    private Control BuildAgentFilterBar()
    {
        var row = new HBoxContainer
        {
            CustomMinimumSize = new Vector2(0f, 44f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 8);
        _agentConsoleFilterAllButton = AgentConsoleFilterButton("◈  Timeline", "all");
        _agentConsoleFilterConversationButton = AgentConsoleFilterButton("◌  Hội thoại", "conversation");
        _agentConsoleFilterToolsButton = AgentConsoleFilterButton("⚒  Công cụ", "tools");
        row.AddChild(_agentConsoleFilterAllButton);
        row.AddChild(_agentConsoleFilterConversationButton);
        row.AddChild(_agentConsoleFilterToolsButton);
        row.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore });
        row.AddChild(AgentConsoleQuietButton("Tất cả sự kiện  ▾", null, 136f));
        row.AddChild(AgentConsoleQuietButton("⌕", null, 44f));
        _agentConsoleFollowButton = AgentConsoleQuietButton("⇅", ToggleAgentAutoFollow, 44f);
        row.AddChild(_agentConsoleFollowButton);
        RefreshAgentFilterButtons();
        return row;
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
        top.AddChild(AgentConsoleLabel("● Sẵn sàng", 11, AgentConsoleGreen, bold: true));
        top.AddChild(AgentConsoleQuietButton("⌃", ToggleAgentInspector, 34f));
        box.AddChild(top);

        box.AddChild(AgentConsoleLabel("Tiến trình tổng quan", 13, AgentConsoleInk, bold: true));
        var progress = new ProgressBar { MinValue = 0, MaxValue = 100, Value = 0, ShowPercentage = false, CustomMinimumSize = new Vector2(0f, 10f), MouseFilter = Control.MouseFilterEnum.Ignore };
        progress.AddThemeStyleboxOverride("background", AgentConsoleStyle(new Color(0.93f,0.95f,0.98f,1f), Colors.Transparent, 5, 0));
        progress.AddThemeStyleboxOverride("fill", AgentConsoleStyle(new Color(0.65f,0.76f,1f,1f), Colors.Transparent, 5, 0));
        box.AddChild(progress);
        var progressMeta = AgentConsoleLabel("Bước hoàn thành  0 / 12    Thời gian  00:00:00    Ước tính còn lại  —", 11, AgentConsoleMuted);
        progressMeta.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(progressMeta);

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

        var detailBox = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        detailBox.AddThemeConstantOverride("separation", 12);
        detailScroll.AddChild(detailBox);

        var section = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        section.AddThemeConstantOverride("separation", 6);
        section.AddChild(AgentConsoleLabel("Workspace", 16, AgentConsoleInk, bold: true));
        section.AddChild(AgentConsoleLabel("🗀  Eris-Core / build-beta", 13, AgentConsoleInk, bold: true));
        section.AddChild(AgentConsoleLabel(@"Đường dẫn         ~/workspace/eris-core/build-beta
Nhánh               main
Cập nhật            2 phút trước", 11, AgentConsoleMuted));
        detailBox.AddChild(section);

        var taskSection = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        taskSection.AddThemeConstantOverride("separation", 6);
        taskSection.AddChild(AgentConsoleLabel("Thông tin task", 16, AgentConsoleInk, bold: true));
        _agentConsoleInspectorLabel = AgentConsoleLabel("Chưa chọn task", 12, AgentConsoleMuted, bold: false);
        taskSection.AddChild(_agentConsoleInspectorLabel);
        _agentConsoleInspectorDetailLabel = AgentConsoleLabel(@"Task ID            —
Trạng thái         Chưa chạy
Chế độ               Thủ công
Tạo lúc              —
Mô tả                 —", 11, AgentConsoleMuted);
        _agentConsoleInspectorDetailLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        taskSection.AddChild(_agentConsoleInspectorDetailLabel);
        detailBox.AddChild(taskSection);

        var toolSection = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        toolSection.AddThemeConstantOverride("separation", 8);
        toolSection.AddChild(AgentConsoleLabel("Kỹ năng & Công cụ", 16, AgentConsoleInk, bold: true));
        var chips = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        chips.AddThemeConstantOverride("separation", 8);
        chips.AddChild(AgentConsoleToolChip("</>", new Color(0.36f,0.52f,0.96f,1f)));
        chips.AddChild(AgentConsoleToolChip("☷", new Color(0.64f,0.66f,0.77f,1f)));
        chips.AddChild(AgentConsoleToolChip("🗄", new Color(0.64f,0.66f,0.77f,1f)));
        chips.AddChild(AgentConsoleToolChip("⌘", new Color(0.56f,0.44f,0.96f,1f)));
        chips.AddChild(AgentConsoleToolChip("⌕", new Color(0.64f,0.66f,0.77f,1f)));
        chips.AddChild(AgentConsoleToolChip("⚒", new Color(0.64f,0.66f,0.77f,1f)));
        chips.AddChild(AgentConsoleToolChip("⊕2", new Color(0.64f,0.66f,0.77f,1f)));
        toolSection.AddChild(chips);
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
        var margin = AgentConsoleMargin(14, 10, 14, 10);
        panel.AddChild(margin);
        var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 10);
        margin.AddChild(row);

        _agentConsolePauseButton = AgentConsoleQuietButton("Ⅱ  Tạm dừng", () => SendAgentControl("pause"), 116f);
        _agentConsoleStopButton = AgentConsoleQuietButton("□  Dừng", () => SendAgentControl("stop"), 96f, danger: false);
        _agentConsoleRollbackButton = AgentConsoleQuietButton("⟲  Rollback", () => SendAgentControl("rollback", checkpointId: SelectedAgentTask()?.CheckpointId ?? ""), 118f);
        row.AddChild(_agentConsolePauseButton);
        row.AddChild(_agentConsoleStopButton);
        row.AddChild(_agentConsoleRollbackButton);

        _agentConsoleDirectiveInput = new LineEdit
        {
            PlaceholderText = "Chỉ thị cho Gemini... (ví dụ: 'Viết module xác thực người dùng')",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            ClearButtonEnabled = true,
        };
        StyleAgentConsoleInput(_agentConsoleDirectiveInput);
        _agentConsoleDirectiveInput.TextSubmitted += _ => SendAgentDirective();
        row.AddChild(_agentConsoleDirectiveInput);

        var send = AgentConsoleButton("Gửi ➤", SendAgentDirective, primary: true);
        send.CustomMinimumSize = new Vector2(124f, 46f);
        row.AddChild(send);
        var statusRow = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        statusRow.AddThemeConstantOverride("separation", 8);
        TextureRect botanical = AgentConsoleAssetImage("identity_botanical_footer.png", new Vector2(48f, 26f), TextureRect.StretchModeEnum.KeepAspectCentered);
        if (botanical != null)
        {
            botanical.Modulate = new Color(1f, 1f, 1f, 0.48f);
            statusRow.AddChild(botanical);
        }
        statusRow.AddChild(AgentConsoleLabel("Eris đang chờ chỉ thị của bạn     ●", 11, AgentConsoleMuted));
        row.AddChild(statusRow);
        _agentConsoleResumeButton = null;
        _agentConsoleControlStatusLabel = AgentConsoleLabel("", 10, AgentConsoleFaint);
        return panel;
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
            _agentConsoleEventList.AddChild(BuildAgentPreviewTimeline());
            CallDeferred(nameof(ResetAgentConsoleEventScrollTop));
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
            if (task.Events.Count == 0)
            {
                _agentConsoleEventList.AddChild(BuildAgentPreviewTimeline());
                CallDeferred(nameof(ResetAgentConsoleEventScrollTop));
            }
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
        var cta = AgentConsoleButton("＋  Tạo task mới", () => _agentConsoleDirectiveInput?.GrabFocus(), primary: false);
        cta.CustomMinimumSize = new Vector2(146f, 38f);
        var wrap = new CenterContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        wrap.AddChild(cta);
        box.AddChild(wrap);
        return outer;
    }

    private Control BuildAgentPreviewTimeline()
    {
        var box = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 8);
        box.AddChild(BuildAgentPreviewRow("Gemini", "Đã khởi tạo phiên làm việc. Phân tích yêu cầu và lập kế hoạch...", AgentConsoleBlue, "14:32:10"));
        box.AddChild(BuildAgentPreviewRow("Planner", "Đang chờ task để tạo kế hoạch bước tiếp theo.", new Color(0.56f, 0.44f, 0.96f, 1f), "14:32:11"));
        box.AddChild(BuildAgentPreviewRow("Eris", "Sẵn sàng. Chờ xác nhận để bắt đầu thực thi.", AgentConsoleGreen, "14:32:12"));
        box.AddChild(BuildAgentPreviewRow("Hệ thống", "Workspace: Eris-Core / build-beta đã được nạp.", AgentConsoleMuted, "14:32:12"));
        return box;
    }

    private Control BuildAgentPreviewRow(string actor, string summary, Color accent, string time)
    {
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 12);

        var dotWrap = new CenterContainer
        {
            CustomMinimumSize = new Vector2(34f, 42f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        var dot = AgentConsoleLabel("●", 14, accent, bold: true);
        dot.HorizontalAlignment = HorizontalAlignment.Center;
        dotWrap.AddChild(dot);
        row.AddChild(dotWrap);

        var card = new PanelContainer
        {
            CustomMinimumSize = new Vector2(0f, 48f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        card.AddThemeStyleboxOverride("panel", AgentConsoleStyle(
            new Color(0.995f, 0.997f, 1f, 0.94f),
            new Color(accent.R, accent.G, accent.B, 0.14f),
            12,
            1));
        var margin = AgentConsoleMargin(14, 7, 14, 7);
        card.AddChild(margin);
        var lines = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        lines.AddThemeConstantOverride("separation", 2);
        margin.AddChild(lines);

        var top = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        top.AddChild(AgentConsoleLabel(actor, 10, accent, bold: true));
        var spacer = new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        top.AddChild(spacer);
        top.AddChild(AgentConsoleLabel(time, 9, AgentConsoleFaint));
        lines.AddChild(top);
        lines.AddChild(AgentConsoleLabel(summary, 10, AgentConsoleInk));
        row.AddChild(card);
        return row;
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
                _agentConsoleTaskMetaLabel.Text = "Gemini-powered AI companion";
            if (_agentConsoleExecutorLabel != null)
                _agentConsoleExecutorLabel.Text = "—";
            if (_agentConsoleStatusLabel != null)
                _agentConsoleStatusLabel.Text = "IDLE";
            SetAgentQuickSummary(null);
            return;
        }

        _agentConsoleInspectorLabel.Text = CompactAgentText(task.Goal, 90);
        if (_agentConsoleTaskMetaLabel != null)
            _agentConsoleTaskMetaLabel.Text = $"{AgentStatusLabel(task.Status)} · {task.Events.Count} event · Gemini ↔ Eris";
        if (_agentConsoleExecutorLabel != null)
        {
            _agentConsoleExecutorLabel.Text = CompactAgentText(
                string.IsNullOrWhiteSpace(task.Model)
                    ? task.Executor.ToUpperInvariant()
                    : $"{task.Executor.ToUpperInvariant()} · {task.Model}",
                24);
        }
        if (_agentConsoleStatusLabel != null)
        {
            _agentConsoleStatusLabel.Text = AgentStatusLabel(task.Status).ToUpperInvariant();
            _agentConsoleStatusLabel.AddThemeColorOverride("font_color", AgentStatusColor(task.Status));
        }
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
            _agentConsoleStepLabel.Text = "step\n—";
            _agentConsoleTestsLabel.Text = "tests\n—";
            _agentConsoleFilesLabel.Text = "files\n—";
            _agentConsoleCheckpointLabel.Text = "checkpoint\n—";
            _agentConsoleSkillsLabel.Text = "skills\n—";
            return;
        }
        _agentConsoleStepLabel.Text = $"step\n{task.CurrentStep} / {Math.Max(task.CurrentStep, 24)}";
        _agentConsoleTestsLabel.Text = task.TestsPassed == 0 && task.TestsFailed == 0
            ? "tests\n—"
            : $"tests\n{task.TestsPassed} passed   {task.TestsFailed} failed";
        _agentConsoleFilesLabel.Text = $"files\n{task.ChangedFiles.Count} changed";
        _agentConsoleCheckpointLabel.Text = string.IsNullOrWhiteSpace(task.CheckpointId)
            ? "checkpoint\n—"
            : $"checkpoint\n{CompactAgentText(task.CheckpointId, 14)}";
        _agentConsoleSkillsLabel.Text = task.ActiveSkills.Count == 0
            ? "skills\n—"
            : $"skills\n{CompactAgentText(string.Join(", ", task.ActiveSkills), 28)}";
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
