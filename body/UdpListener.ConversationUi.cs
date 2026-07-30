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
    private static readonly Color ErisGreen = new(0.21f, 0.79f, 0.47f, 1f);
    private static readonly Color ErisGreenDeep = new(0.04f, 0.10f, 0.07f, 0.98f);
    private static readonly Color ErisGreenCard = new(0.09f, 0.22f, 0.14f, 0.98f);
    private static readonly Color ErisGreenUser = new(0.12f, 0.40f, 0.25f, 0.98f);
    private static readonly Color ErisText = new(0.91f, 0.98f, 0.94f, 1f);
    private static readonly Color ErisMuted = new(0.56f, 0.69f, 0.61f, 1f);
    private static readonly Color ErisBorder = new(0.16f, 0.38f, 0.24f, 0.95f);

    private readonly List<ConversationEntry> _conversationEntries = new();
    private HBoxContainer _conversationShell;
    private PanelContainer _todayConversationPanel;
    private VBoxContainer _todayTopicList;
    private Label _todayCurrentTopicLabel;
    private Label _todayStatsLabel;
    private PanelContainer _conversationMainCard;
    private Label _conversationHeaderStatus;
    private ScrollContainer _conversationScroll;
    private VBoxContainer _conversationMessageList;
    private PanelContainer _conversationThinkingRow;
    private Label _conversationThinkingLabel;
    private ulong _conversationLastDotTickMs;
    private ulong _conversationStateChangedAtMs;
    private int _conversationDotPhase;
    private string _conversationState = "idle";
    private string _conversationStateLabel = "Sẵn sàng";
    private string _lastAssistantConversationText = "";

    private PanelContainer _spriteSpeechBubble;
    private RichTextLabel _spriteSpeechLabel;
    private Label _spriteSpeechStatus;
    private PanelContainer _live2DSpeechBubble;
    private RichTextLabel _live2DSpeechLabel;
    private Label _live2DSpeechStatus;

    private void BuildConversationUi()
    {
        if (_chatPanel == null)
            return;

        LoadConversationToday();
        ClearChatPanelChildren();
        BuildConversationPanelTree();
        BuildSeparatedSpeechBubbles();
        RebuildConversationMessages();
        RefreshTodayConversationPanel();
        RefreshConversationPresence();
        UpdateConversationUiLayout();
    }

    private void ClearChatPanelChildren()
    {
        foreach (Node child in _chatPanel.GetChildren())
        {
            _chatPanel.RemoveChild(child);
            child.QueueFree();
        }
    }

    private void BuildConversationPanelTree()
    {
        _chatPanel.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            ErisGreenDeep,
            ErisBorder,
            22,
            1,
            14f,
            shadow: true));
        _chatPanel.ZIndex = 130;

        var outerMargin = new MarginContainer
        {
            Name = "ConversationMargin",
            AnchorRight = 1f,
            AnchorBottom = 1f,
            OffsetLeft = 14f,
            OffsetTop = 14f,
            OffsetRight = -14f,
            OffsetBottom = -14f,
        };
        _chatPanel.AddChild(outerMargin);

        _conversationShell = new HBoxContainer
        {
            Name = "ConversationShell",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        _conversationShell.AddThemeConstantOverride("separation", 14);
        outerMargin.AddChild(_conversationShell);

        _todayConversationPanel = BuildTodayConversationPanel();
        _conversationShell.AddChild(_todayConversationPanel);

        _conversationMainCard = BuildConversationMainCard();
        _conversationShell.AddChild(_conversationMainCard);
    }

    private PanelContainer BuildTodayConversationPanel()
    {
        var panel = new PanelContainer
        {
            Name = "TodayConversationPanel",
            CustomMinimumSize = new Vector2(254f, 0f),
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        panel.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.05f, 0.20f, 0.12f, 0.98f),
            new Color(0.16f, 0.48f, 0.28f, 0.92f),
            18,
            1,
            16f));

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        root.AddThemeConstantOverride("separation", 12);
        panel.AddChild(root);

        var eyebrow = new Label { Text = "HỘI THOẠI HÔM NAY" };
        eyebrow.AddThemeColorOverride("font_color", ErisGreen);
        eyebrow.AddThemeFontSizeOverride("font_size", 12);
        root.AddChild(eyebrow);

        var title = new Label
        {
            Text = "Eris đang ở đây",
            AutowrapMode = TextServer.AutowrapMode.WordSmart,
        };
        title.AddThemeColorOverride("font_color", ErisText);
        title.AddThemeFontSizeOverride("font_size", 22);
        root.AddChild(title);

        _todayStatsLabel = new Label
        {
            Text = "Chưa có tin nhắn hôm nay",
            AutowrapMode = TextServer.AutowrapMode.WordSmart,
        };
        _todayStatsLabel.AddThemeColorOverride("font_color", ErisMuted);
        _todayStatsLabel.AddThemeFontSizeOverride("font_size", 13);
        root.AddChild(_todayStatsLabel);

        root.AddChild(MakeSeparator());

        var currentTitle = new Label { Text = "ĐANG NÓI VỀ" };
        currentTitle.AddThemeColorOverride("font_color", ErisGreen);
        currentTitle.AddThemeFontSizeOverride("font_size", 11);
        root.AddChild(currentTitle);

        _todayCurrentTopicLabel = new Label
        {
            Text = "Chưa có chủ đề",
            AutowrapMode = TextServer.AutowrapMode.WordSmart,
        };
        _todayCurrentTopicLabel.AddThemeColorOverride("font_color", ErisText);
        _todayCurrentTopicLabel.AddThemeFontSizeOverride("font_size", 15);
        root.AddChild(_todayCurrentTopicLabel);

        root.AddChild(MakeSeparator());

        var recentTitle = new Label { Text = "ĐÃ NHẮC TỚI" };
        recentTitle.AddThemeColorOverride("font_color", ErisGreen);
        recentTitle.AddThemeFontSizeOverride("font_size", 11);
        root.AddChild(recentTitle);

        _todayTopicList = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        _todayTopicList.AddThemeConstantOverride("separation", 8);
        root.AddChild(_todayTopicList);

        var footer = new Label
        {
            Text = "Lịch sử được giữ riêng theo ngày trên máy này.",
            AutowrapMode = TextServer.AutowrapMode.WordSmart,
            VerticalAlignment = VerticalAlignment.Bottom,
            SizeFlagsVertical = Control.SizeFlags.ShrinkEnd,
        };
        footer.AddThemeColorOverride("font_color", new Color(0.43f, 0.58f, 0.49f, 1f));
        footer.AddThemeFontSizeOverride("font_size", 11);
        root.AddChild(footer);

        return panel;
    }

    private PanelContainer BuildConversationMainCard()
    {
        var card = new PanelContainer
        {
            Name = "ConversationMainCard",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        card.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.035f, 0.075f, 0.055f, 0.98f),
            new Color(0.10f, 0.24f, 0.16f, 0.95f),
            18,
            1,
            0f));

        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        root.AddThemeConstantOverride("separation", 0);
        card.AddChild(root);

        root.AddChild(BuildConversationHeader());
        root.AddChild(BuildConversationBody());
        root.AddChild(BuildConversationComposer());
        return card;
    }

    private Control BuildConversationHeader()
    {
        var margin = new MarginContainer();
        margin.AddThemeConstantOverride("margin_left", 20);
        margin.AddThemeConstantOverride("margin_right", 18);
        margin.AddThemeConstantOverride("margin_top", 16);
        margin.AddThemeConstantOverride("margin_bottom", 14);

        var row = new HBoxContainer();
        row.AddThemeConstantOverride("separation", 12);
        margin.AddChild(row);

        var titles = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        titles.AddThemeConstantOverride("separation", 2);
        row.AddChild(titles);

        var eyebrow = new Label { Text = "TRÒ CHUYỆN TRỰC TIẾP" };
        eyebrow.AddThemeColorOverride("font_color", ErisGreen);
        eyebrow.AddThemeFontSizeOverride("font_size", 11);
        titles.AddChild(eyebrow);

        var title = new Label { Text = "Hôm nay bạn thế nào?" };
        title.AddThemeColorOverride("font_color", ErisText);
        title.AddThemeFontSizeOverride("font_size", 21);
        titles.AddChild(title);

        _conversationHeaderStatus = new Label
        {
            Text = "● Sẵn sàng",
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Center,
        };
        _conversationHeaderStatus.AddThemeColorOverride("font_color", ErisMuted);
        _conversationHeaderStatus.AddThemeFontSizeOverride("font_size", 13);
        row.AddChild(_conversationHeaderStatus);

        _chatCloseButton = new Button
        {
            Name = "CloseButton",
            Text = "×",
            CustomMinimumSize = new Vector2(38f, 38f),
            Flat = true,
            FocusMode = Control.FocusModeEnum.None,
        };
        _chatCloseButton.AddThemeColorOverride("font_color", ErisMuted);
        _chatCloseButton.AddThemeColorOverride("font_hover_color", ErisText);
        _chatCloseButton.AddThemeFontSizeOverride("font_size", 24);
        row.AddChild(_chatCloseButton);

        return margin;
    }

    private Control BuildConversationBody()
    {
        var body = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        body.AddChild(MakeSeparator());

        _conversationScroll = new ScrollContainer
        {
            Name = "ConversationScroll",
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
            VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        body.AddChild(_conversationScroll);

        var scrollMargin = new MarginContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        scrollMargin.AddThemeConstantOverride("margin_left", 18);
        scrollMargin.AddThemeConstantOverride("margin_right", 18);
        scrollMargin.AddThemeConstantOverride("margin_top", 16);
        scrollMargin.AddThemeConstantOverride("margin_bottom", 16);
        _conversationScroll.AddChild(scrollMargin);

        _conversationMessageList = new VBoxContainer
        {
            Name = "ConversationMessageList",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ShrinkBegin,
        };
        _conversationMessageList.AddThemeConstantOverride("separation", 12);
        scrollMargin.AddChild(_conversationMessageList);

        _conversationThinkingRow = BuildThinkingRow();
        _conversationMessageList.AddChild(_conversationThinkingRow);
        return body;
    }

    private PanelContainer BuildThinkingRow()
    {
        var row = new PanelContainer
        {
            Name = "ThinkingRow",
            Visible = false,
            CustomMinimumSize = new Vector2(280f, 46f),
            SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin,
        };
        row.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.08f, 0.17f, 0.12f, 0.98f),
            new Color(0.12f, 0.31f, 0.19f, 0.9f),
            14,
            1,
            12f));
        _conversationThinkingLabel = new Label
        {
            Text = "Eris đang suy nghĩ…",
            VerticalAlignment = VerticalAlignment.Center,
        };
        _conversationThinkingLabel.AddThemeColorOverride("font_color", ErisMuted);
        _conversationThinkingLabel.AddThemeFontSizeOverride("font_size", 14);
        row.AddChild(_conversationThinkingLabel);
        return row;
    }

    private Control BuildConversationComposer()
    {
        var outer = new VBoxContainer();
        outer.AddChild(MakeSeparator());

        var margin = new MarginContainer();
        margin.AddThemeConstantOverride("margin_left", 16);
        margin.AddThemeConstantOverride("margin_right", 16);
        margin.AddThemeConstantOverride("margin_top", 12);
        margin.AddThemeConstantOverride("margin_bottom", 14);
        outer.AddChild(margin);

        var row = new HBoxContainer();
        row.AddThemeConstantOverride("separation", 10);
        margin.AddChild(row);

        _chatInput = new LineEdit
        {
            Name = "LineEdit",
            PlaceholderText = "Nhắn gì đó cho Eris…",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            CustomMinimumSize = new Vector2(200f, 48f),
            ClearButtonEnabled = true,
        };
        _chatInput.AddThemeColorOverride("font_color", ErisText);
        _chatInput.AddThemeColorOverride("font_placeholder_color", ErisMuted);
        _chatInput.AddThemeFontSizeOverride("font_size", 15);
        _chatInput.AddThemeStyleboxOverride("normal", MakeFlatStyle(
            new Color(0.055f, 0.12f, 0.085f, 1f),
            new Color(0.12f, 0.30f, 0.19f, 0.95f),
            14,
            1,
            13f));
        _chatInput.AddThemeStyleboxOverride("focus", MakeFlatStyle(
            new Color(0.055f, 0.12f, 0.085f, 1f),
            ErisGreen,
            14,
            2,
            12f));
        row.AddChild(_chatInput);

        _chatSendButton = new Button
        {
            Name = "SendButton",
            Text = "➤",
            CustomMinimumSize = new Vector2(52f, 48f),
            FocusMode = Control.FocusModeEnum.None,
            MouseDefaultCursorShape = Control.CursorShape.PointingHand,
        };
        _chatSendButton.AddThemeFontSizeOverride("font_size", 20);
        _chatSendButton.AddThemeColorOverride("font_color", new Color(0.02f, 0.09f, 0.05f, 1f));
        _chatSendButton.AddThemeStyleboxOverride("normal", MakeFlatStyle(ErisGreen, ErisGreen, 14, 0, 8f));
        _chatSendButton.AddThemeStyleboxOverride("hover", MakeFlatStyle(new Color(0.28f, 0.88f, 0.55f, 1f), ErisGreen, 14, 0, 8f));
        _chatSendButton.AddThemeStyleboxOverride("pressed", MakeFlatStyle(new Color(0.16f, 0.65f, 0.37f, 1f), ErisGreen, 14, 0, 8f));
        row.AddChild(_chatSendButton);

        return outer;
    }

    private void BuildSeparatedSpeechBubbles()
    {
        BuildSpriteSpeechBubble();
        BuildLive2DSpeechBubble();
        SyncSpeechBubbleMode();
    }

    private void BuildSpriteSpeechBubble()
    {
        Node parent = GetNodeOrNull<Node>("Monika2/Monika");
        if (parent == null)
            return;

        Control legacy = GetNodeOrNull<Control>("Monika2/Monika/BubbleContainer");
        if (legacy != null)
            legacy.Visible = false;

        _spriteSpeechBubble = new PanelContainer
        {
            Name = "SpriteSpeechBubbleV2",
            Visible = false,
            Position = new Vector2(-258f, -296f),
            Size = new Vector2(516f, 184f),
            CustomMinimumSize = new Vector2(516f, 184f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
            ZIndex = 25,
        };
        _spriteSpeechBubble.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.965f, 0.99f, 0.975f, 0.98f),
            new Color(0.31f, 0.82f, 0.52f, 0.95f),
            18,
            2,
            18f,
            shadow: true));
        parent.AddChild(_spriteSpeechBubble);

        var root = BuildSpeechBubbleContent(out _spriteSpeechStatus, out _spriteSpeechLabel, darkText: true);
        _spriteSpeechBubble.AddChild(root);

        var tail = new Polygon2D
        {
            Polygon = new Vector2[]
            {
                new(228f, 182f),
                new(278f, 182f),
                new(254f, 210f),
            },
            Color = new Color(0.965f, 0.99f, 0.975f, 0.98f),
            ZIndex = -1,
        };
        _spriteSpeechBubble.AddChild(tail);

        _bubble = _spriteSpeechBubble;
        _label = _spriteSpeechLabel;
    }

    private void BuildLive2DSpeechBubble()
    {
        Control root = GetNodeOrNull<Control>("CanvasLayer/Control");
        if (root == null)
            return;

        _live2DSpeechBubble = new PanelContainer
        {
            Name = "Live2DSpeechBubbleV2",
            Visible = false,
            Size = new Vector2(500f, 174f),
            CustomMinimumSize = new Vector2(500f, 174f),
            MouseFilter = Control.MouseFilterEnum.Ignore,
            ZIndex = 140,
        };
        _live2DSpeechBubble.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            new Color(0.035f, 0.10f, 0.065f, 0.97f),
            new Color(0.20f, 0.72f, 0.41f, 0.95f),
            18,
            1,
            18f,
            shadow: true));
        root.AddChild(_live2DSpeechBubble);

        var content = BuildSpeechBubbleContent(out _live2DSpeechStatus, out _live2DSpeechLabel, darkText: false);
        _live2DSpeechBubble.AddChild(content);
    }

    private VBoxContainer BuildSpeechBubbleContent(out Label status, out RichTextLabel text, bool darkText)
    {
        var root = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
        };
        root.AddThemeConstantOverride("separation", 8);

        var header = new HBoxContainer();
        header.AddThemeConstantOverride("separation", 8);
        root.AddChild(header);

        var dot = new Label { Text = "◆" };
        dot.AddThemeColorOverride("font_color", ErisGreen);
        dot.AddThemeFontSizeOverride("font_size", 13);
        header.AddChild(dot);

        var name = new Label { Text = "ERIS" };
        name.AddThemeColorOverride("font_color", darkText ? new Color(0.12f, 0.27f, 0.18f, 1f) : ErisText);
        name.AddThemeFontSizeOverride("font_size", 13);
        header.AddChild(name);

        status = new Label
        {
            Text = "đang trả lời",
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        status.AddThemeColorOverride("font_color", darkText ? new Color(0.36f, 0.49f, 0.41f, 1f) : ErisMuted);
        status.AddThemeFontSizeOverride("font_size", 12);
        header.AddChild(status);

        text = new RichTextLabel
        {
            BbcodeEnabled = false,
            FitContent = false,
            ScrollActive = false,
            AutowrapMode = TextServer.AutowrapMode.WordSmart,
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        text.AddThemeColorOverride("default_color", darkText ? new Color(0.08f, 0.16f, 0.11f, 1f) : ErisText);
        text.AddThemeFontSizeOverride("normal_font_size", 17);
        root.AddChild(text);
        return root;
    }

    private void UpdateConversationUiLayout()
    {
        if (_chatPanel == null || _conversationShell == null)
            return;

        Vector2 viewport = GetViewportRect().Size;
        float targetWidth = Mathf.Clamp(viewport.X - 36f, 700f, 1080f);
        float targetHeight = Mathf.Clamp(viewport.Y - 76f, 460f, 680f);
        targetWidth = Mathf.Min(targetWidth, Mathf.Max(420f, viewport.X - 20f));
        targetHeight = Mathf.Min(targetHeight, Mathf.Max(360f, viewport.Y - 20f));

        _chatPanel.CustomMinimumSize = new Vector2(targetWidth, targetHeight);
        _chatPanel.Size = new Vector2(targetWidth, targetHeight);
        _chatPanel.Position = new Vector2(
            Mathf.Max(10f, (viewport.X - targetWidth) * 0.5f),
            Mathf.Max(10f, (viewport.Y - targetHeight) * 0.5f));

        bool compact = targetWidth < 790f;
        if (_todayConversationPanel != null)
            _todayConversationPanel.Visible = true;
        if (_conversationShell != null)
            _conversationShell.AddThemeConstantOverride("separation", compact ? 8 : 14);
    }

    private void ConversationAppendUserMessage(string text)
    {
        ConversationAppendMessage("user", text);
    }

    private void ConversationAppendAssistantMessage(string text)
    {
        string cleaned = NormalizeConversationText(text);
        if (string.IsNullOrWhiteSpace(cleaned))
            return;
        if (string.Equals(cleaned, _lastAssistantConversationText, StringComparison.Ordinal))
            return;
        _lastAssistantConversationText = cleaned;
        ConversationAppendMessage("assistant", cleaned);
    }

    private void ConversationAppendMessage(string role, string text)
    {
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
        MarkChatActivity();
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
        RefreshTodayConversationPanel();
        CallDeferred(nameof(ScrollConversationToBottom));
    }

    private Control BuildConversationMessageRow(ConversationEntry entry)
    {
        bool user = string.Equals(entry.Role, "user", StringComparison.Ordinal);
        var row = new HBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
        };
        row.AddThemeConstantOverride("separation", 10);

        var spacer = new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        var bubble = new PanelContainer
        {
            CustomMinimumSize = new Vector2(360f, 0f),
            SizeFlagsHorizontal = user ? Control.SizeFlags.ShrinkEnd : Control.SizeFlags.ShrinkBegin,
        };
        bubble.AddThemeStyleboxOverride("panel", MakeFlatStyle(
            user ? ErisGreenUser : ErisGreenCard,
            user ? new Color(0.21f, 0.64f, 0.39f, 0.9f) : new Color(0.13f, 0.31f, 0.20f, 0.92f),
            14,
            1,
            12f));

        var content = new VBoxContainer();
        content.AddThemeConstantOverride("separation", 5);
        bubble.AddChild(content);

        var meta = new Label
        {
            Text = user ? $"BẠN  ·  {entry.Time}" : $"ERIS  ·  {entry.Time}",
        };
        meta.AddThemeColorOverride("font_color", user ? new Color(0.73f, 0.94f, 0.82f, 1f) : ErisGreen);
        meta.AddThemeFontSizeOverride("font_size", 11);
        content.AddChild(meta);

        var message = new Label
        {
            Text = entry.Text,
            AutowrapMode = TextServer.AutowrapMode.WordSmart,
            CustomMinimumSize = new Vector2(330f, 0f),
        };
        message.AddThemeColorOverride("font_color", ErisText);
        message.AddThemeFontSizeOverride("font_size", 14);
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
            if (child == _conversationThinkingRow)
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
        _todayCurrentTopicLabel.Text = latestUser == null
            ? "Chưa có chủ đề"
            : ShortTopic(latestUser.Text, 72);

        foreach (Node child in _todayTopicList.GetChildren())
        {
            _todayTopicList.RemoveChild(child);
            child.QueueFree();
        }

        List<string> recentTopics = _conversationEntries
            .Where(e => e.Role == "user")
            .Select(e => ShortTopic(e.Text, 56))
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Reverse()
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(5)
            .ToList();

        if (recentTopics.Count == 0)
        {
            var empty = new Label { Text = "• Chưa có mục nào", AutowrapMode = TextServer.AutowrapMode.WordSmart };
            empty.AddThemeColorOverride("font_color", ErisMuted);
            empty.AddThemeFontSizeOverride("font_size", 13);
            _todayTopicList.AddChild(empty);
            return;
        }

        foreach (string topic in recentTopics)
        {
            var label = new Label
            {
                Text = "• " + topic,
                AutowrapMode = TextServer.AutowrapMode.WordSmart,
            };
            label.AddThemeColorOverride("font_color", ErisText);
            label.AddThemeFontSizeOverride("font_size", 13);
            _todayTopicList.AddChild(label);
        }
    }

    private void ConversationSetState(string state, string label = "")
    {
        _conversationState = string.IsNullOrWhiteSpace(state) ? "idle" : state.Trim().ToLowerInvariant();
        _conversationStateChangedAtMs = Time.GetTicksMsec();
        _conversationStateLabel = string.IsNullOrWhiteSpace(label)
            ? ConversationStateLabel(_conversationState)
            : label.Trim();
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
            _conversationHeaderStatus.Text = "● " + _conversationStateLabel;
            _conversationHeaderStatus.AddThemeColorOverride("font_color", statusColor);
        }
        if (thinking)
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
                ? "Eris đang suy nghĩ…"
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
        _conversationThinkingLabel.Text = baseText + new string('·', _conversationDotPhase + 1);
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
        return _isLive2DMode ? _live2DSpeechBubble : _spriteSpeechBubble;
    }

    private RichTextLabel ActiveSpeechLabel()
    {
        return _isLive2DMode ? _live2DSpeechLabel : _spriteSpeechLabel;
    }

    private Label ActiveSpeechStatusLabel()
    {
        return _isLive2DMode ? _live2DSpeechStatus : _spriteSpeechStatus;
    }

    private void SyncSpeechBubbleMode()
    {
        bool wasVisible = (_spriteSpeechBubble?.Visible ?? false) || (_live2DSpeechBubble?.Visible ?? false);
        string currentText = (_spriteSpeechLabel?.Text ?? "").Trim();
        if (string.IsNullOrWhiteSpace(currentText))
            currentText = (_live2DSpeechLabel?.Text ?? "").Trim();

        if (_isLive2DMode)
        {
            if (_spriteSpeechBubble != null)
                _spriteSpeechBubble.Visible = false;
            if (_live2DSpeechLabel != null && !string.IsNullOrWhiteSpace(currentText))
                _live2DSpeechLabel.Text = currentText;
            if (_live2DSpeechBubble != null)
                _live2DSpeechBubble.Visible = wasVisible;
        }
        else
        {
            if (_live2DSpeechBubble != null)
                _live2DSpeechBubble.Visible = false;
            if (_spriteSpeechLabel != null && !string.IsNullOrWhiteSpace(currentText))
                _spriteSpeechLabel.Text = currentText;
            if (_spriteSpeechBubble != null)
                _spriteSpeechBubble.Visible = wasVisible;
        }
    }

    private void HideAllSpeechBubbles()
    {
        if (_spriteSpeechBubble != null)
            _spriteSpeechBubble.Visible = false;
        if (_live2DSpeechBubble != null)
            _live2DSpeechBubble.Visible = false;
    }

    private Control Live2DSpeechBubbleControl()
    {
        return _live2DSpeechBubble;
    }

    private void LoadConversationToday()
    {
        _conversationEntries.Clear();
        string path = ProjectSettings.GlobalizePath(ConversationTodayStatePath);
        try
        {
            if (!System.IO.File.Exists(path))
                return;
            string raw = System.IO.File.ReadAllText(path);
            ConversationDayStore store = JsonSerializer.Deserialize<ConversationDayStore>(raw);
            if (store == null || store.Date != DateTime.Now.ToString("yyyy-MM-dd") || store.Entries == null)
                return;
            foreach (ConversationEntry entry in store.Entries.TakeLast(80))
            {
                if (entry == null || string.IsNullOrWhiteSpace(entry.Text))
                    continue;
                _conversationEntries.Add(entry);
            }
            _lastAssistantConversationText = _conversationEntries.LastOrDefault(e => e.Role == "assistant")?.Text ?? "";
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
                Date = DateTime.Now.ToString("yyyy-MM-dd"),
                Entries = _conversationEntries.TakeLast(80).ToList(),
            };
            System.IO.File.WriteAllText(path, JsonSerializer.Serialize(store, new JsonSerializerOptions
            {
                WriteIndented = true,
            }));
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
        return value.Substring(0, Math.Max(1, maxLength - 1)).TrimEnd() + "…";
    }

    private static string ConversationStateLabel(string state)
    {
        return state switch
        {
            "thinking" => "Eris đang suy nghĩ…",
            "preparing" => "Eris đang chuẩn bị trả lời…",
            "buffering" => "Eris đang chuẩn bị giọng nói…",
            "speaking" => "Eris đang nói",
            _ => "Sẵn sàng",
        };
    }

    private static string PrefixErisStatus(string label)
    {
        string clean = (label ?? "").Trim();
        if (string.IsNullOrWhiteSpace(clean))
            return "Eris đang suy nghĩ…";
        if (clean.StartsWith("Eris", StringComparison.OrdinalIgnoreCase))
            return clean;
        return "Eris " + char.ToLowerInvariant(clean[0]) + clean.Substring(1);
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
