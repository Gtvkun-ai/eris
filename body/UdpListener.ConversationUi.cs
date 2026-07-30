using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

public partial class UdpListener
{
    private sealed class ConversationEntry
    {
        public string Role { get; set; } = "";
        public string Text { get; set; } = "";
        public string Time { get; set; } = "";
    }

    private sealed class ConversationDayStore
    {
        public string Date { get; set; } = "";
        public List<ConversationEntry> Entries { get; set; } = new();
    }

    private const string ConversationTodayStatePath = "user://eris_conversation_today.json";
    private static readonly Vector2 ConversationHistoryPreferredSize = new(1040f, 680f);
    private static readonly Vector2 ConversationHistoryCompactSize = new(620f, 480f);
    private static readonly Color ErisGreen = new(0.21f, 0.79f, 0.47f, 1f);
    private static readonly Color ErisGreenDeep = new(0.035f, 0.085f, 0.055f, 0.985f);
    private static readonly Color ErisGreenCard = new(0.075f, 0.19f, 0.12f, 0.985f);
    private static readonly Color ErisGreenUser = new(0.10f, 0.34f, 0.21f, 0.985f);
    private static readonly Color ErisText = new(0.91f, 0.98f, 0.94f, 1f);
    private static readonly Color ErisMuted = new(0.56f, 0.69f, 0.61f, 1f);
    private static readonly Color ErisBorder = new(0.14f, 0.38f, 0.23f, 0.96f);

    private readonly List<ConversationEntry> _conversationEntries = new();
    private Panel _conversationHistoryPanel;
    private HBoxContainer _conversationShell;
    private PanelContainer _todayConversationPanel;
    private VBoxContainer _todayTopicList;
    private Label _todayCurrentTopicLabel;
    private Label _todayStatsLabel;
    private Label _conversationHeaderStatus;
    private PanelContainer _conversationStatusChip;
    private Label _conversationHeaderDate;
    private ScrollContainer _conversationScroll;
    private VBoxContainer _conversationMessageList;
    private PanelContainer _conversationEmptyState;
    private PanelContainer _conversationThinkingRow;
    private Label _conversationThinkingLabel;
    private Button _conversationHistoryCloseButton;
    private bool _conversationHistoryUserPositioned;
    private ulong _conversationLastDotTickMs;
    private ulong _conversationStateChangedAtMs;
    private int _conversationDotPhase;
    private string _conversationState = "idle";
    private string _conversationStateLabel = "Sẵn sàng";
    private string _lastAssistantConversationText = "";
    private ulong _lastAssistantConversationAtMs;
    private string _conversationStoreDate = "";
    private Vector2 _conversationLastViewportSize = Vector2.Zero;

    private void BuildConversationUi()
    {
        if (_conversationHistoryPanel != null)
            return;

        LoadConversationToday();
        _conversationHistoryPanel = new Panel
        {
            Name = "ConversationHistoryPanel",
            Visible = false,
            CustomMinimumSize = Vector2.Zero,
            Size = ConversationHistoryPreferredSize,
            ZIndex = 99,
            ClipContents = true,
        };
        GetNode<Control>("CanvasLayer/Control").AddChild(_conversationHistoryPanel);
        BuildConversationPanelTree();
        RebuildConversationMessages();
        RefreshTodayConversationPanel();
        RefreshConversationPresence();
        UpdateConversationUiLayout(force: true);
    }

    private void OnContextConversationHistoryPressed()
    {
        if (_conversationHistoryPanel == null)
            return;
        _bodyAutonomy?.RecordUserInteraction();
        CloseCharacterContextMenu();
        if (_conversationHistoryPanel.Visible)
            CloseConversationHistoryPanel();
        else
            ShowConversationHistoryPanel();
    }

    private void ShowConversationHistoryPanel()
    {
        if (_conversationHistoryPanel == null)
            return;

        EnsureConversationDateCurrent();
        CloseCharacterContextMenu();
        _conversationHistoryPanel.Visible = true;
        _conversationHistoryPanel.ZIndex = 99;
        _conversationHistoryPanel.MoveToFront();
        UpdateConversationUiLayout(force: true);
        RefreshConversationPresenceFromRuntime();
        RefreshTodayConversationPanel();
        RefreshConversationEmptyState();
        UpdateMousePassthrough();
        CallDeferred(nameof(ScrollConversationToBottom));
    }

    private void CloseConversationHistoryPanel()
    {
        if (_conversationHistoryPanel == null)
            return;
        if (_draggingPanel == _conversationHistoryPanel)
            _draggingPanel = null;
        _conversationHistoryPanel.Visible = false;
        UpdateMousePassthrough();
    }

    private void BuildConversationPanelTree()
    {
        _conversationHistoryPanel.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            ErisGreenDeep,
            ErisBorder,
            20,
            1,
            0f,
            shadow: true));

        var outerMargin = new MarginContainer
        {
            Name = "ConversationHistoryMargin",
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        outerMargin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        outerMargin.AddThemeConstantOverride("margin_left", 16);
        outerMargin.AddThemeConstantOverride("margin_right", 16);
        outerMargin.AddThemeConstantOverride("margin_top", 16);
        outerMargin.AddThemeConstantOverride("margin_bottom", 16);
        _conversationHistoryPanel.AddChild(outerMargin);

        _conversationShell = new HBoxContainer
        {
            Name = "ConversationHistoryShell",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _conversationShell.AddThemeConstantOverride("separation", 14);
        outerMargin.AddChild(_conversationShell);

        _todayConversationPanel = BuildTodayConversationPanel();
        _conversationShell.AddChild(_todayConversationPanel);

        PanelContainer main = BuildConversationMainCard();
        _conversationShell.AddChild(main);
    }

    private PanelContainer BuildTodayConversationPanel()
    {
        var panel = new PanelContainer
        {
            Name = "TodayConversationPanel",
            CustomMinimumSize = new Vector2(250f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.045f, 0.18f, 0.105f, 0.99f),
            new Color(0.14f, 0.46f, 0.26f, 0.94f),
            16,
            1,
            16f));

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 10);
        panel.AddChild(root);

        Label eyebrow = ConversationLabel("HỘI THOẠI HÔM NAY", 11, ErisGreen);
        root.AddChild(eyebrow);

        Label title = ConversationLabel("Một ngày với Eris", 21, ErisText);
        title.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        root.AddChild(title);

        _todayStatsLabel = ConversationLabel("Chưa có tin nhắn hôm nay", 13, ErisMuted);
        _todayStatsLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        root.AddChild(_todayStatsLabel);

        root.AddChild(MakeSeparator());
        root.AddChild(ConversationLabel("ĐANG NÓI VỀ", 11, ErisGreen));

        _todayCurrentTopicLabel = ConversationLabel("Chưa có chủ đề", 15, ErisText);
        _todayCurrentTopicLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        _todayCurrentTopicLabel.MaxLinesVisible = 4;
        _todayCurrentTopicLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
        root.AddChild(_todayCurrentTopicLabel);

        root.AddChild(MakeSeparator());
        root.AddChild(ConversationLabel("ĐÃ NHẮC TỚI", 11, ErisGreen));

        var topicScroll = new ScrollContainer
        {
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
            VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
        };
        root.AddChild(topicScroll);

        _todayTopicList = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ShrinkBegin,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _todayTopicList.AddThemeConstantOverride("separation", 8);
        topicScroll.AddChild(_todayTopicList);

        Label footer = ConversationLabel("Lịch sử hôm nay được lưu cục bộ trên máy này.", 11, new Color(0.43f, 0.58f, 0.49f, 1f));
        footer.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        root.AddChild(footer);

        return panel;
    }

    private PanelContainer BuildConversationMainCard()
    {
        var card = new PanelContainer
        {
            Name = "ConversationHistoryMainCard",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        card.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.025f, 0.065f, 0.043f, 0.995f),
            new Color(0.09f, 0.24f, 0.15f, 0.96f),
            16,
            1,
            0f));

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        root.AddThemeConstantOverride("separation", 0);
        card.AddChild(root);

        root.AddChild(BuildConversationHeader());
        root.AddChild(BuildConversationBody());
        return card;
    }

    private Control BuildConversationHeader()
    {
        var margin = new MarginContainer
        {
            CustomMinimumSize = new Vector2(0f, 76f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        margin.AddThemeConstantOverride("margin_left", 20);
        margin.AddThemeConstantOverride("margin_right", 14);
        margin.AddThemeConstantOverride("margin_top", 13);
        margin.AddThemeConstantOverride("margin_bottom", 11);

        var row = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        row.AddThemeConstantOverride("separation", 10);
        margin.AddChild(row);

        var titles = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        titles.AddThemeConstantOverride("separation", 1);
        row.AddChild(titles);

        Label eyebrow = ConversationLabel("LỊCH SỬ HỘI THOẠI", 11, ErisGreen);
        titles.AddChild(eyebrow);

        Label title = ConversationLabel("Hôm nay đã nói gì", 21, ErisText);
        title.ClipText = true;
        title.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
        titles.AddChild(title);

        _conversationHeaderDate = ConversationLabel(DateTime.Now.ToString("dd/MM/yyyy"), 11, ErisMuted);
        _conversationHeaderDate.HorizontalAlignment = HorizontalAlignment.Right;
        _conversationHeaderDate.VerticalAlignment = VerticalAlignment.Center;
        _conversationHeaderDate.CustomMinimumSize = new Vector2(76f, 0f);
        row.AddChild(_conversationHeaderDate);

        _conversationStatusChip = new PanelContainer
        {
            CustomMinimumSize = new Vector2(142f, 34f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _conversationStatusChip.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.055f, 0.15f, 0.095f, 0.98f),
            new Color(0.12f, 0.33f, 0.20f, 0.9f),
            10,
            1,
            8f));
        _conversationHeaderStatus = ConversationLabel("• Sẵn sàng", 12, ErisMuted);
        _conversationHeaderStatus.HorizontalAlignment = HorizontalAlignment.Center;
        _conversationHeaderStatus.VerticalAlignment = VerticalAlignment.Center;
        _conversationHeaderStatus.ClipText = true;
        _conversationStatusChip.AddChild(_conversationHeaderStatus);
        row.AddChild(_conversationStatusChip);

        _conversationHistoryCloseButton = new Button
        {
            Name = "ConversationHistoryCloseButton",
            Text = "×",
            CustomMinimumSize = new Vector2(38f, 38f),
            Flat = true,
            FocusMode = Control.FocusModeEnum.None,
            MouseFilter = Control.MouseFilterEnum.Stop,
            TooltipText = "Đóng lịch sử hội thoại",
        };
        _conversationHistoryCloseButton.AddThemeColorOverride("font_color", ErisMuted);
        _conversationHistoryCloseButton.AddThemeColorOverride("font_hover_color", ErisText);
        _conversationHistoryCloseButton.AddThemeColorOverride("font_pressed_color", ErisGreen);
        _conversationHistoryCloseButton.AddThemeFontSizeOverride("font_size", 22);
        _conversationHistoryCloseButton.Pressed += CloseConversationHistoryPanel;
        row.AddChild(_conversationHistoryCloseButton);

        return margin;
    }

    private Control BuildConversationBody()
    {
        var body = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        body.AddChild(MakeSeparator());

        _conversationScroll = new ScrollContainer
        {
            Name = "ConversationHistoryScroll",
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
            VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Stop,
        };
        body.AddChild(_conversationScroll);

        var scrollMargin = new MarginContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        scrollMargin.AddThemeConstantOverride("margin_left", 18);
        scrollMargin.AddThemeConstantOverride("margin_right", 18);
        scrollMargin.AddThemeConstantOverride("margin_top", 16);
        scrollMargin.AddThemeConstantOverride("margin_bottom", 16);
        _conversationScroll.AddChild(scrollMargin);

        _conversationMessageList = new VBoxContainer
        {
            Name = "ConversationHistoryMessageList",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ShrinkBegin,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        _conversationMessageList.AddThemeConstantOverride("separation", 12);
        scrollMargin.AddChild(_conversationMessageList);

        _conversationEmptyState = BuildConversationEmptyState();
        _conversationMessageList.AddChild(_conversationEmptyState);

        _conversationThinkingRow = BuildThinkingRow();
        _conversationMessageList.AddChild(_conversationThinkingRow);
        return body;
    }

    private PanelContainer BuildConversationEmptyState()
    {
        var panel = new PanelContainer
        {
            Name = "ConversationHistoryEmptyState",
            CustomMinimumSize = new Vector2(0f, 132f),
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        panel.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.045f, 0.12f, 0.078f, 0.78f),
            new Color(0.10f, 0.27f, 0.17f, 0.78f),
            14,
            1,
            18f));

        var box = new VBoxContainer
        {
            Alignment = BoxContainer.AlignmentMode.Center,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        box.AddThemeConstantOverride("separation", 6);
        panel.AddChild(box);

        Label title = ConversationLabel("Chưa có hội thoại nào hôm nay", 17, ErisText);
        title.HorizontalAlignment = HorizontalAlignment.Center;
        box.AddChild(title);

        Label hint = ConversationLabel("Tin nhắn của bạn và phản hồi công khai của Eris sẽ xuất hiện ở đây.", 13, ErisMuted);
        hint.HorizontalAlignment = HorizontalAlignment.Center;
        hint.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        box.AddChild(hint);
        return panel;
    }

    private PanelContainer BuildThinkingRow()
    {
        var row = new PanelContainer
        {
            Name = "ThinkingRow",
            Visible = false,
            CustomMinimumSize = new Vector2(260f, 44f),
            SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.065f, 0.16f, 0.105f, 0.99f),
            new Color(0.11f, 0.31f, 0.19f, 0.92f),
            12,
            1,
            12f));
        _conversationThinkingLabel = ConversationLabel("Eris đang suy nghĩ...", 14, ErisMuted);
        _conversationThinkingLabel.VerticalAlignment = VerticalAlignment.Center;
        row.AddChild(_conversationThinkingLabel);
        return row;
    }

    private void UpdateConversationUiLayout(bool force = false)
    {
        if (_conversationHistoryPanel == null || _conversationShell == null)
            return;

        Vector2 viewport = GetViewportRect().Size;
        if (!force && viewport.DistanceTo(_conversationLastViewportSize) < 1f)
            return;
        _conversationLastViewportSize = viewport;

        float availableWidth = Mathf.Max(1f, viewport.X - 24f);
        float availableHeight = Mathf.Max(1f, viewport.Y - 24f);
        float width = Mathf.Min(ConversationHistoryPreferredSize.X, availableWidth);
        float height = Mathf.Min(ConversationHistoryPreferredSize.Y, availableHeight);
        if (availableWidth >= ConversationHistoryCompactSize.X)
            width = Mathf.Max(width, ConversationHistoryCompactSize.X);
        if (availableHeight >= ConversationHistoryCompactSize.Y)
            height = Mathf.Max(height, ConversationHistoryCompactSize.Y);

        Vector2 target = new(width, height);
        _conversationHistoryPanel.CustomMinimumSize = Vector2.Zero;
        _conversationHistoryPanel.Size = target;

        if (_conversationHistoryUserPositioned)
            ClampConversationHistoryPanelToScreen();
        else
            _conversationHistoryPanel.Position = new Vector2(
                Mathf.Max(0f, (viewport.X - target.X) * 0.5f),
                Mathf.Max(0f, (viewport.Y - target.Y) * 0.5f));

        bool showToday = target.X >= 900f && target.Y >= 520f;
        if (_todayConversationPanel != null)
            _todayConversationPanel.Visible = showToday;
        _conversationShell.AddThemeConstantOverride("separation", showToday ? 14 : 0);

        if (_conversationHeaderDate != null)
            _conversationHeaderDate.Visible = target.X >= 720f;
        if (_conversationStatusChip != null)
            _conversationStatusChip.Visible = target.X >= 520f;
    }

    private void ClampConversationHistoryPanelToScreen()
    {
        if (_conversationHistoryPanel == null)
            return;
        Vector2 screen = GetViewportRect().Size;
        Vector2 pos = _conversationHistoryPanel.Position;
        pos.X = Mathf.Clamp(pos.X, 0f, Mathf.Max(0f, screen.X - _conversationHistoryPanel.Size.X));
        pos.Y = Mathf.Clamp(pos.Y, 0f, Mathf.Max(0f, screen.Y - _conversationHistoryPanel.Size.Y));
        _conversationHistoryPanel.Position = pos;
    }

    private void RecordConversationUserMessage(string text)
    {
        ConversationAppendMessage("user", text);
        ConversationSetState("thinking", "Eris đang suy nghĩ...");
    }

    private void RecordConversationAssistantMessage(string text)
    {
        if ((text ?? "").Trim().StartsWith("[Chủ nhân]:", StringComparison.OrdinalIgnoreCase))
            return;
        string cleaned = NormalizeConversationText(text);
        if (string.IsNullOrWhiteSpace(cleaned))
            return;
        ulong now = Time.GetTicksMsec();
        if (string.Equals(cleaned, _lastAssistantConversationText, StringComparison.Ordinal)
            && _lastAssistantConversationAtMs > 0
            && now - _lastAssistantConversationAtMs < 5000)
            return;
        _lastAssistantConversationText = cleaned;
        _lastAssistantConversationAtMs = now;
        ConversationAppendMessage("assistant", cleaned);
    }

    private void ConversationAppendMessage(string role, string text)
    {
        EnsureConversationDateCurrent();
        string cleaned = NormalizeConversationText(text);
        if (string.IsNullOrWhiteSpace(cleaned))
            return;

        var entry = new ConversationEntry
        {
            Role = role == "user" ? "user" : "assistant",
            Text = cleaned,
            Time = DateTime.Now.ToString("HH:mm"),
        };
        _conversationEntries.Add(entry);
        while (_conversationEntries.Count > 80)
            _conversationEntries.RemoveAt(0);

        if (_conversationMessageList != null)
        {
            int thinkingIndex = _conversationThinkingRow?.GetIndex() ?? _conversationMessageList.GetChildCount();
            Control row = BuildConversationMessageRow(entry);
            _conversationMessageList.AddChild(row);
            if (_conversationThinkingRow != null)
                _conversationMessageList.MoveChild(row, Math.Max(0, thinkingIndex));
        }

        SaveConversationToday();
        RefreshConversationEmptyState();
        RefreshTodayConversationPanel();
        if (_conversationHistoryPanel?.Visible ?? false)
            CallDeferred(nameof(ScrollConversationToBottom));
    }

    private Control BuildConversationMessageRow(ConversationEntry entry)
    {
        bool user = string.Equals(entry.Role, "user", StringComparison.Ordinal);
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        row.AddThemeConstantOverride("separation", 12);

        var spacer = new Control
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsStretchRatio = 0.24f,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        var bubble = new PanelContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsStretchRatio = 0.76f,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        bubble.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            user ? ErisGreenUser : ErisGreenCard,
            user ? new Color(0.19f, 0.60f, 0.36f, 0.92f) : new Color(0.12f, 0.31f, 0.19f, 0.94f),
            12,
            1,
            12f));

        var content = new VBoxContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        content.AddThemeConstantOverride("separation", 5);
        bubble.AddChild(content);

        Label meta = ConversationLabel(user ? $"BẠN  •  {entry.Time}" : $"ERIS  •  {entry.Time}", 11,
            user ? new Color(0.73f, 0.94f, 0.82f, 1f) : ErisGreen);
        content.AddChild(meta);

        Label message = ConversationLabel(entry.Text, 14, ErisText);
        message.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        message.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        content.AddChild(message);

        if (user)
        {
            row.AddChild(spacer);
            row.AddChild(bubble);
        }
        else
        {
            row.AddChild(bubble);
            row.AddChild(spacer);
        }
        return row;
    }

    private void RebuildConversationMessages()
    {
        if (_conversationMessageList == null)
            return;
        foreach (Node child in _conversationMessageList.GetChildren())
        {
            if (child == _conversationThinkingRow || child == _conversationEmptyState)
                continue;
            _conversationMessageList.RemoveChild(child);
            child.QueueFree();
        }
        foreach (ConversationEntry entry in _conversationEntries)
        {
            Control row = BuildConversationMessageRow(entry);
            _conversationMessageList.AddChild(row);
            if (_conversationThinkingRow != null)
                _conversationMessageList.MoveChild(row, _conversationThinkingRow.GetIndex());
        }
        RefreshConversationEmptyState();
    }

    private void RefreshConversationEmptyState()
    {
        if (_conversationEmptyState != null)
            _conversationEmptyState.Visible = _conversationEntries.Count == 0;
    }

    private void RefreshTodayConversationPanel()
    {
        if (_todayStatsLabel == null || _todayCurrentTopicLabel == null || _todayTopicList == null)
            return;

        int userCount = _conversationEntries.Count(e => e.Role == "user");
        int assistantCount = _conversationEntries.Count(e => e.Role == "assistant");
        _todayStatsLabel.Text = userCount == 0 && assistantCount == 0
            ? "Chưa có tin nhắn hôm nay"
            : $"{userCount} tin của bạn  •  {assistantCount} phản hồi của Eris";

        ConversationEntry latestUser = _conversationEntries.LastOrDefault(e => e.Role == "user");
        _todayCurrentTopicLabel.Text = latestUser == null ? "Chưa có chủ đề" : ShortTopic(latestUser.Text, 86);

        foreach (Node child in _todayTopicList.GetChildren())
        {
            _todayTopicList.RemoveChild(child);
            child.QueueFree();
        }

        List<string> recentTopics = _conversationEntries
            .Where(e => e.Role == "user")
            .Select(e => ShortTopic(e.Text, 62))
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Reverse()
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(6)
            .ToList();

        if (recentTopics.Count == 0)
        {
            Label empty = ConversationLabel("• Chưa có mục nào", 13, ErisMuted);
            _todayTopicList.AddChild(empty);
            return;
        }

        foreach (string topic in recentTopics)
        {
            Label label = ConversationLabel("• " + topic, 13, ErisText);
            label.AutowrapMode = TextServer.AutowrapMode.WordSmart;
            label.MaxLinesVisible = 3;
            label.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
            _todayTopicList.AddChild(label);
        }
    }

    private void ConversationSetState(string state, string label = "")
    {
        _conversationState = string.IsNullOrWhiteSpace(state) ? "idle" : state.Trim().ToLowerInvariant();
        _conversationStateChangedAtMs = Time.GetTicksMsec();
        _conversationStateLabel = string.IsNullOrWhiteSpace(label) ? ConversationStateLabel(_conversationState) : label.Trim();
        RefreshConversationPresence();
    }

    private void RefreshConversationPresence()
    {
        bool thinking = _conversationState is "thinking" or "preparing" or "buffering";
        if (_conversationThinkingRow != null)
            _conversationThinkingRow.Visible = thinking;
        if (_conversationThinkingLabel != null)
            _conversationThinkingLabel.Text = thinking ? _conversationStateLabel : "";

        if (_conversationHeaderStatus != null)
        {
            Color statusColor = _conversationState == "speaking" ? ErisGreen
                : thinking ? new Color(0.69f, 0.84f, 0.74f, 1f)
                : ErisMuted;
            _conversationHeaderStatus.Text = "• " + _conversationStateLabel;
            _conversationHeaderStatus.AddThemeColorOverride("font_color", statusColor);
        }
        if (thinking && (_conversationHistoryPanel?.Visible ?? false))
            CallDeferred(nameof(ScrollConversationToBottom));
    }

    private void RefreshConversationPresenceFromRuntime()
    {
        if (_runtimePresence.Speaking)
        {
            ConversationSetState("speaking", "Eris đang nói");
            return;
        }
        if (_runtimePresence.Thinking)
        {
            string label = string.IsNullOrWhiteSpace(_runtimePresence.StatusLabel)
                ? "Eris đang suy nghĩ..."
                : PrefixErisStatus(_runtimePresence.StatusLabel);
            string state = _runtimePresence.Stage == "audio_buffering" ? "buffering" : "thinking";
            ConversationSetState(state, label);
            return;
        }

        bool localPending = _conversationState is "thinking" or "preparing" or "buffering";
        if (localPending
            && _conversationStateChangedAtMs > _runtimePresence.LastPacketAtMs
            && Time.GetTicksMsec() - _conversationStateChangedAtMs < 45000)
            return;
        ConversationSetState("idle", "Sẵn sàng");
    }

    private void TickConversationUi()
    {
        EnsureConversationDateCurrent();
        if (_conversationHistoryPanel?.Visible ?? false)
            UpdateConversationUiLayout();

        bool thinking = _conversationState is "thinking" or "preparing" or "buffering";
        if (!thinking || _conversationThinkingLabel == null)
            return;
        ulong now = Time.GetTicksMsec();
        if (!_runtimePresence.Thinking
            && !_runtimePresence.Speaking
            && _conversationStateChangedAtMs > 0
            && now - _conversationStateChangedAtMs > 45000)
        {
            ConversationSetState("idle", "Chưa nhận được phản hồi");
            return;
        }
        if (now - _conversationLastDotTickMs < 360)
            return;
        _conversationLastDotTickMs = now;
        _conversationDotPhase = (_conversationDotPhase + 1) % 4;
        string baseText = _conversationState == "buffering" ? "Eris đang chuẩn bị giọng nói" : "Eris đang suy nghĩ";
        _conversationThinkingLabel.Text = baseText + new string('.', _conversationDotPhase + 1);
    }

    private void ScrollConversationToBottom()
    {
        if (_conversationScroll == null)
            return;
        VScrollBar bar = _conversationScroll.GetVScrollBar();
        if (bar != null)
            bar.Value = bar.MaxValue;
    }

    private Control ActiveSpeechBubble()
    {
        if (_isLive2DMode && _live2DSpeechBubble != null)
            return _live2DSpeechBubble;
        return _bubble;
    }

    private RichTextLabel ActiveSpeechLabel()
    {
        if (_isLive2DMode && _live2DSpeechLabel != null)
            return _live2DSpeechLabel;
        return _label;
    }

    private Label ActiveSpeechStatusLabel()
    {
        if (_isLive2DMode && _live2DSpeechStatus != null)
            return _live2DSpeechStatus;
        return null;
    }

    private void SyncSpeechBubbleMode()
    {
        bool twoDVisible = _bubble != null && _bubble.Visible;
        bool liveVisible = _live2DSpeechBubble != null && _live2DSpeechBubble.Visible;
        bool shouldRemainVisible = twoDVisible || liveVisible;

        string visibleText = twoDVisible
            ? (_label?.Text ?? "")
            : liveVisible
                ? (_live2DSpeechLabel?.Text ?? "")
                : !string.IsNullOrWhiteSpace(_live2DSpeechLabel?.Text)
                    ? _live2DSpeechLabel.Text
                    : (_label?.Text ?? "");
        string statusText = !string.IsNullOrWhiteSpace(_live2DSpeechStatus?.Text)
            ? _live2DSpeechStatus.Text
            : "đang trả lời";

        if (_isLive2DMode)
        {
            BuildLive2DSpeechBubble();
            if (_live2DSpeechLabel != null && !string.IsNullOrWhiteSpace(visibleText))
                _live2DSpeechLabel.Text = visibleText;
            if (_live2DSpeechStatus != null)
                _live2DSpeechStatus.Text = statusText;
            if (_bubble != null)
                _bubble.Visible = false;
            if (_live2DSpeechBubble != null)
            {
                _live2DSpeechBubble.Visible = shouldRemainVisible && !string.IsNullOrWhiteSpace(visibleText);
                if (_live2DSpeechBubble.Visible)
                    ApplyLive2DBubbleVisualState();
            }
        }
        else
        {
            if (_label != null && !string.IsNullOrWhiteSpace(visibleText))
                _label.Text = visibleText;
            if (_live2DSpeechBubble != null)
                _live2DSpeechBubble.Visible = false;
            if (_bubble != null)
            {
                _bubble.Visible = shouldRemainVisible && !string.IsNullOrWhiteSpace(visibleText);
                if (_bubble.Visible)
                {
                    PromoteLegacySpeechBubbleToUiOverlay();
                    SyncLegacySpeechBubbleOverlayTransform();
                }
            }
        }

        ScheduleTransientOverlayRefresh();
    }

    private void HideAllSpeechBubbles()
    {
        if (_bubble != null)
            _bubble.Visible = false;
        if (_live2DSpeechBubble != null)
            _live2DSpeechBubble.Visible = false;
        if (_label != null)
            _label.Text = "";
        if (_live2DSpeechLabel != null)
            _live2DSpeechLabel.Text = "";
        if (_live2DSpeechStatus != null)
            _live2DSpeechStatus.Text = "";
        ScheduleTransientOverlayRefresh();
    }

    private Control Live2DSpeechBubbleControl()
    {
        return _live2DSpeechBubble;
    }

    private void EnsureConversationDateCurrent()
    {
        string today = DateTime.Now.ToString("yyyy-MM-dd");
        if (string.IsNullOrWhiteSpace(_conversationStoreDate))
        {
            _conversationStoreDate = today;
            return;
        }
        if (string.Equals(_conversationStoreDate, today, StringComparison.Ordinal))
            return;

        _conversationStoreDate = today;
        _conversationEntries.Clear();
        _lastAssistantConversationText = "";
        _lastAssistantConversationAtMs = 0;
        RebuildConversationMessages();
        RefreshTodayConversationPanel();
        RefreshConversationEmptyState();
        if (_conversationHeaderDate != null)
            _conversationHeaderDate.Text = DateTime.Now.ToString("dd/MM/yyyy");
        SaveConversationToday();
    }

    private void LoadConversationToday()
    {
        _conversationEntries.Clear();
        _conversationStoreDate = DateTime.Now.ToString("yyyy-MM-dd");
        string path = ProjectSettings.GlobalizePath(ConversationTodayStatePath);
        try
        {
            if (!System.IO.File.Exists(path))
                return;
            string raw = System.IO.File.ReadAllText(path);
            ConversationDayStore store = JsonSerializer.Deserialize<ConversationDayStore>(raw);
            if (store == null || store.Date != _conversationStoreDate || store.Entries == null)
                return;
            foreach (ConversationEntry entry in store.Entries.TakeLast(80))
            {
                if (entry == null || string.IsNullOrWhiteSpace(entry.Text))
                    continue;
                entry.Role = entry.Role == "user" ? "user" : "assistant";
                entry.Text = NormalizeConversationText(entry.Text);
                entry.Time = string.IsNullOrWhiteSpace(entry.Time) ? "--:--" : entry.Time.Trim();
                if (!string.IsNullOrWhiteSpace(entry.Text))
                    _conversationEntries.Add(entry);
            }
            _lastAssistantConversationText = _conversationEntries.LastOrDefault(e => e.Role == "assistant")?.Text ?? "";
            _lastAssistantConversationAtMs = 0;
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[ConversationUi] Không đọc được lịch sử hôm nay: {ex.Message}");
        }
    }

    private void SaveConversationToday()
    {
        string path = ProjectSettings.GlobalizePath(ConversationTodayStatePath);
        try
        {
            string directory = System.IO.Path.GetDirectoryName(path) ?? "";
            if (!string.IsNullOrWhiteSpace(directory))
                System.IO.Directory.CreateDirectory(directory);
            var store = new ConversationDayStore
            {
                Date = string.IsNullOrWhiteSpace(_conversationStoreDate)
                    ? DateTime.Now.ToString("yyyy-MM-dd")
                    : _conversationStoreDate,
                Entries = _conversationEntries.TakeLast(80).ToList(),
            };
            string json = JsonSerializer.Serialize(store, new JsonSerializerOptions { WriteIndented = true });
            string tempPath = path + ".tmp";
            System.IO.File.WriteAllText(tempPath, json);
            System.IO.File.Move(tempPath, path, true);
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[ConversationUi] Không lưu được lịch sử hôm nay: {ex.Message}");
        }
    }

    private static string NormalizeConversationText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "";
        string cleaned = text.Replace("\r\n", "\n").Trim();
        if (cleaned.StartsWith("[Chủ nhân]:", StringComparison.OrdinalIgnoreCase))
            cleaned = cleaned.Substring("[Chủ nhân]:".Length).Trim();
        return cleaned;
    }

    private static string ShortTopic(string text, int maxLength)
    {
        string value = NormalizeConversationText(text).Replace('\n', ' ').Trim();
        int sentenceEnd = value.IndexOfAny(new[] { '.', '?', '!', ';' });
        if (sentenceEnd >= 18)
            value = value.Substring(0, sentenceEnd + 1);
        if (value.Length <= maxLength)
            return value;
        return value.Substring(0, Math.Max(1, maxLength - 1)).TrimEnd() + "...";
    }

    private static string ConversationStateLabel(string state)
    {
        return state switch
        {
            "thinking" => "Eris đang suy nghĩ...",
            "preparing" => "Eris đang chuẩn bị trả lời...",
            "buffering" => "Eris đang chuẩn bị giọng nói...",
            "speaking" => "Eris đang nói",
            _ => "Sẵn sàng",
        };
    }

    private static string PrefixErisStatus(string label)
    {
        string clean = (label ?? "").Trim();
        if (string.IsNullOrWhiteSpace(clean))
            return "Eris đang suy nghĩ...";
        if (clean.StartsWith("Eris", StringComparison.OrdinalIgnoreCase))
            return clean;
        return "Eris " + char.ToLowerInvariant(clean[0]) + clean.Substring(1);
    }

    private static Label ConversationLabel(string text, int fontSize, Color color)
    {
        var label = new Label
        {
            Text = text,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        label.AddThemeColorOverride("font_color", color);
        label.AddThemeFontSizeOverride("font_size", fontSize);
        return label;
    }

    private static Control MakeSeparator()
    {
        return new ColorRect
        {
            Color = new Color(0.12f, 0.25f, 0.17f, 0.8f),
            CustomMinimumSize = new Vector2(0f, 1f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
    }

    private static StyleBoxFlat MakeFlatStyle(
        Color background,
        Color border,
        int radius,
        int borderWidth,
        float padding,
        bool shadow = false)
    {
        return new StyleBoxFlat
        {
            BgColor = background,
            BorderColor = border,
            BorderWidthLeft = borderWidth,
            BorderWidthTop = borderWidth,
            BorderWidthRight = borderWidth,
            BorderWidthBottom = borderWidth,
            CornerRadiusTopLeft = radius,
            CornerRadiusTopRight = radius,
            CornerRadiusBottomLeft = radius,
            CornerRadiusBottomRight = radius,
            ContentMarginLeft = padding,
            ContentMarginTop = padding,
            ContentMarginRight = padding,
            ContentMarginBottom = padding,
            ShadowColor = shadow ? new Color(0f, 0f, 0f, 0.34f) : new Color(0f, 0f, 0f, 0f),
            ShadowSize = shadow ? 8 : 0,
            ShadowOffset = shadow ? new Vector2(0f, 4f) : Vector2.Zero,
        };
    }
}
