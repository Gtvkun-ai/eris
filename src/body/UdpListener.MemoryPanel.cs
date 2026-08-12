using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	// Panel này chỉ gửi request có cấu trúc cho Brain. Không ghi trực tiếp JSON
	// memory từ Godot, vì hai tiến trình cùng sửa một file là cách rất hiệu quả để
	// biến dữ liệu người dùng thành món mì trộn không còn parse được.
	private const string MemoryPanelCachePath = "user://living_user_panel_cache.json";
	private static readonly Vector2 MemoryPanelPreferredSize = new(1040f, 680f);
	private static readonly Vector2 MemoryPanelAbsoluteMinSize = new(900f, 600f);

	private sealed class MemoryPanelRecord
	{
		public string Id { get; init; } = "";
		public string Path { get; init; } = "";
		public string Label { get; init; } = "";
		public string Category { get; init; } = "other";
		public string DisplayValue { get; init; } = "";
		public string Explicitness { get; init; } = "inferred";
		public string ExplicitnessLabel { get; init; } = "ERIS đang suy đoán";
		public string CertaintyLabel { get; init; } = "Cần xác nhận";
		public string ScopeKind { get; init; } = "global";
		public string ScopeKey { get; init; } = "";
		public string ScopeLabel { get; init; } = "Mọi cuộc trò chuyện";
		public string Source { get; init; } = "";
		public float Confidence { get; init; }
		public int EvidenceCount { get; init; }
		public int Recurrence { get; init; }
		public double UpdatedAt { get; init; }
	}

	private sealed class MemoryPanelActionItem
	{
		public string Kind { get; init; } = "";
		public string Title { get; init; } = "";
		public string Detail { get; init; } = "";
		public string Status { get; init; } = "";
	}

	private Panel _memoryPanel;
	private Button _contextMemoryButton;
	private VBoxContainer _memoryItemList;
	private Label _memorySummaryLabel;
	private Label _memoryCountLabel;
	private Label _memoryStatusLabel;
	private LineEdit _memorySearchInput;
	private OptionButton _memoryCategorySelect;
	private CheckButton _memoryIncludeInferredToggle;
	private CheckButton _memoryAutoCleanupToggle;
	private Button _memoryCleanupNowButton;
	private Label _memoryCleanupLabel;
	private Label _memoryFeedTraceLabel;
	private bool _memoryApplyingCleanupSnapshot;
	private bool _memoryCleanupPolling;
	private ulong _memoryCleanupPollAtMs;
	private Label _memoryDetailTitle;
	private Label _memoryDetailMeta;
	private Label _memoryDetailPath;
	private TextEdit _memoryEditValue;
	private OptionButton _memoryScopeSelect;
	private LineEdit _memoryProjectInput;
	private CheckButton _memoryHardDeleteToggle;
	private Button _memorySaveButton;
	private Button _memoryConfirmButton;
	private Button _memoryExplainButton;
	private Button _memoryMoveScopeButton;
	private Button _memoryForgetButton;
	private Label _memoryExplanationLabel;
	private Control _memoryDetailEmpty;
	private VBoxContainer _memoryDetailContent;
	private ScrollContainer _memoryDetailScroll;

	private readonly List<MemoryPanelRecord> _memoryRecords = new();
	private readonly List<MemoryPanelActionItem> _memoryActions = new();
	private MemoryPanelRecord _selectedMemoryRecord;
	private string _memorySummaryText = "ERIS chưa gửi bản tổng hợp.";
	private string _memoryLastRequestId = "";
	private ulong _memoryRequestSentAtMs;
	private bool _memoryRequestPending;
	private string _memoryPendingAction = "";
	private string _memoryHardDeleteArmedPath = "";

	private static readonly Color MemoryInk = new(0.39f, 0.08f, 0.25f);
	private static readonly Color MemoryInkSoft = new(0.48f, 0.27f, 0.38f);
	private static readonly Color MemoryPink = new(0.95f, 0.34f, 0.62f);
	private static readonly Color MemoryBorder = new(0.91f, 0.66f, 0.79f, 0.96f);
	private static readonly Color MemoryCard = new(1f, 0.99f, 0.995f, 0.98f);

	private void InitializeMemoryPanel()
	{
		_memoryPanel = new Panel
		{
			Name = "MemoryPanel",
			Visible = false,
			CustomMinimumSize = MemoryPanelAbsoluteMinSize,
			Size = MemoryPanelPreferredSize,
			ZIndex = 99,
		};
		GetNode<Control>("CanvasLayer/Control").AddChild(_memoryPanel);
		BuildMemoryPanelUi();
		LoadMemoryPanelCache();
		if (_contextMemoryButton != null)
			_contextMemoryButton.Pressed += OnContextMemoryPressed;
	}

	private void OnContextMemoryPressed()
	{
		if (_memoryPanel == null)
			return;
		if (_memoryPanel.Visible)
			CloseMemoryPanel();
		else
			ShowMemoryPanel();
	}

	private void ShowMemoryPanel()
	{
		if (_memoryPanel == null)
			return;
		CloseCharacterContextMenu();
		_memoryPanel.Visible = true;
		Vector2 viewport = GetViewportRect().Size;
		// Panel co theo viewport nhưng không chiếm gần hết màn hình. Bản cũ dùng
		// kích thước cố định 1120x720 nên trên màn 1080p trông như một tờ khai thuế.
		Vector2 target = new(
			Mathf.Clamp(viewport.X - 120f, MemoryPanelAbsoluteMinSize.X, MemoryPanelPreferredSize.X),
			Mathf.Clamp(viewport.Y - 100f, MemoryPanelAbsoluteMinSize.Y, MemoryPanelPreferredSize.Y));
		_memoryPanel.Size = target;
		_memoryPanel.Position = new Vector2(
			Mathf.Max(16f, (viewport.X - target.X) * 0.5f),
			Mathf.Max(16f, (viewport.Y - target.Y) * 0.5f));
		RefreshMemoryPanel();
		SendMemoryPanelRequest("snapshot");
	}

	private void CloseMemoryPanel()
	{
		if (_memoryPanel != null)
			_memoryPanel.Visible = false;
	}

	private void BuildMemoryPanelUi()
	{
		if (_memoryPanel == null)
			return;

		_memoryPanel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.985f, 0.993f, 0.995f),
			BorderColor = MemoryBorder,
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 20,
			CornerRadiusTopRight = 20,
			CornerRadiusBottomLeft = 20,
			CornerRadiusBottomRight = 20,
			ShadowColor = new Color(0.55f, 0.10f, 0.30f, 0.20f),
			ShadowSize = 10,
		});
		_memoryPanel.ClipContents = true;

		var margin = new MarginContainer();
		margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		margin.AddThemeConstantOverride("margin_left", 24);
		margin.AddThemeConstantOverride("margin_right", 24);
		margin.AddThemeConstantOverride("margin_top", 18);
		margin.AddThemeConstantOverride("margin_bottom", 18);
		_memoryPanel.AddChild(margin);

		var root = new VBoxContainer();
		root.AddThemeConstantOverride("separation", 10);
		margin.AddChild(root);

		var header = new HBoxContainer();
		header.AddThemeConstantOverride("separation", 10);
		root.AddChild(header);
		var title = CreateUiLabel("ERIS nhớ gì về bạn?", 26, MemoryInk);
		title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		header.AddChild(title);
		var refresh = CreateMemoryButton("Đọc lại", () => SendMemoryPanelRequest("snapshot"), primary: false);
		refresh.CustomMinimumSize = new Vector2(96f, 34f);
		header.AddChild(refresh);
		var controls = CreateWindowControlCapsule(() => _memoryPanel.Visible = false, CloseMemoryPanel);
		header.AddChild(controls);

		var summaryCard = CreateMemoryCard(new Color(1f, 0.955f, 0.978f, 0.98f), 18);
		summaryCard.CustomMinimumSize = new Vector2(0f, 88f);
		root.AddChild(summaryCard);
		var summaryMargin = new MarginContainer();
		summaryMargin.AddThemeConstantOverride("margin_left", 18);
		summaryMargin.AddThemeConstantOverride("margin_right", 18);
		summaryMargin.AddThemeConstantOverride("margin_top", 12);
		summaryMargin.AddThemeConstantOverride("margin_bottom", 12);
		summaryCard.AddChild(summaryMargin);
		var summaryBox = new VBoxContainer();
		summaryBox.AddThemeConstantOverride("separation", 5);
		summaryMargin.AddChild(summaryBox);
		_memorySummaryLabel = CreateUiLabel(_memorySummaryText, 14, MemoryInk);
		_memorySummaryLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_memorySummaryLabel.MaxLinesVisible = 4;
		_memorySummaryLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		summaryBox.AddChild(_memorySummaryLabel);
		_memoryCountLabel = CreateUiLabel("Chưa có thống kê", 11, MemoryInkSoft);
		summaryBox.AddChild(_memoryCountLabel);

		// V41: DeepSeek chỉ đề xuất cleanup; Brain validator mới được quyền ghi store.
		// UI điều khiển authority service, tuyệt đối không xóa JSON/SQLite trực tiếp.
		var curatorCard = CreateMemoryCard(new Color(0.985f, 0.965f, 1f, 0.96f), 14);
		root.AddChild(curatorCard);
		var curatorMargin = new MarginContainer();
		curatorMargin.AddThemeConstantOverride("margin_left", 14);
		curatorMargin.AddThemeConstantOverride("margin_right", 14);
		curatorMargin.AddThemeConstantOverride("margin_top", 8);
		curatorMargin.AddThemeConstantOverride("margin_bottom", 8);
		curatorCard.AddChild(curatorMargin);
		var curatorRow = new HBoxContainer();
		curatorRow.AddThemeConstantOverride("separation", 10);
		curatorMargin.AddChild(curatorRow);
		var curatorTitle = CreateUiLabel("DeepSeek Memory Curator", 12, MemoryInk);
		curatorTitle.CustomMinimumSize = new Vector2(170f, 34f);
		curatorTitle.VerticalAlignment = VerticalAlignment.Center;
		curatorRow.AddChild(curatorTitle);
		_memoryAutoCleanupToggle = new CheckButton { Text = "Tự động dọn", ButtonPressed = false };
		_memoryAutoCleanupToggle.AddThemeFontSizeOverride("font_size", 11);
		_memoryAutoCleanupToggle.AddThemeColorOverride("font_color", MemoryInkSoft);
		_memoryAutoCleanupToggle.Toggled += enabled =>
		{
			if (_memoryApplyingCleanupSnapshot) return;
			SendMemoryPanelRequest("set_auto_cleanup", new Dictionary<string, object> { ["enabled"] = enabled });
		};
		curatorRow.AddChild(_memoryAutoCleanupToggle);
		_memoryCleanupNowButton = CreateMemoryButton("DeepSeek dọn ngay", StartMemoryCleanup, primary: true);
		_memoryCleanupNowButton.CustomMinimumSize = new Vector2(144f, 34f);
		curatorRow.AddChild(_memoryCleanupNowButton);
		_memoryCleanupLabel = CreateUiLabel("Chưa chạy cleanup.", 10, MemoryInkSoft);
		_memoryCleanupLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_memoryCleanupLabel.VerticalAlignment = VerticalAlignment.Center;
		_memoryCleanupLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		curatorRow.AddChild(_memoryCleanupLabel);
		_memoryFeedTraceLabel = CreateUiLabel("Memory feed: chưa có trace.", 10, new Color(0.45f, 0.30f, 0.52f));
		_memoryFeedTraceLabel.CustomMinimumSize = new Vector2(240f, 34f);
		_memoryFeedTraceLabel.VerticalAlignment = VerticalAlignment.Center;
		_memoryFeedTraceLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		curatorRow.AddChild(_memoryFeedTraceLabel);

		var filters = new HBoxContainer();
		filters.AddThemeConstantOverride("separation", 10);
		root.AddChild(filters);
		_memoryCategorySelect = new OptionButton { CustomMinimumSize = new Vector2(176f, 38f) };
		foreach (string label in new[] { "Tất cả", "Về bạn", "Sở thích", "Dự án & mục tiêu", "Cách làm việc", "Chưa chắc" })
			_memoryCategorySelect.AddItem(label);
		_memoryCategorySelect.ItemSelected += _ => RefreshMemoryPanelList();
		StyleMemoryInput(_memoryCategorySelect);
		filters.AddChild(_memoryCategorySelect);

		_memorySearchInput = new LineEdit
		{
			PlaceholderText = "Tìm trong những gì ERIS nhớ...",
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(260f, 38f),
		};
		_memorySearchInput.TextChanged += _ => RefreshMemoryPanelList();
		StyleMemoryInput(_memorySearchInput);
		filters.AddChild(_memorySearchInput);

		_memoryIncludeInferredToggle = new CheckButton { Text = "Hiện suy đoán", ButtonPressed = true };
		_memoryIncludeInferredToggle.AddThemeFontSizeOverride("font_size", 12);
		_memoryIncludeInferredToggle.AddThemeColorOverride("font_color", MemoryInkSoft);
		_memoryIncludeInferredToggle.Toggled += enabled =>
		{
			RefreshMemoryPanelList();
			SendMemoryPanelRequest("snapshot", new Dictionary<string, object> { ["include_inferred"] = enabled });
		};
		filters.AddChild(_memoryIncludeInferredToggle);

		_memoryStatusLabel = CreateUiLabel("Đang dùng dữ liệu gần nhất.", 11, MemoryInkSoft);
		_memoryStatusLabel.CustomMinimumSize = new Vector2(172f, 38f);
		_memoryStatusLabel.VerticalAlignment = VerticalAlignment.Center;
		filters.AddChild(_memoryStatusLabel);

		var body = new HBoxContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill };
		body.AddThemeConstantOverride("separation", 12);
		root.AddChild(body);

		var listCard = CreateMemoryCard(MemoryCard, 18);
		listCard.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		listCard.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		body.AddChild(listCard);
		var listMargin = new MarginContainer();
		listMargin.AddThemeConstantOverride("margin_left", 12);
		listMargin.AddThemeConstantOverride("margin_right", 8);
		listMargin.AddThemeConstantOverride("margin_top", 12);
		listMargin.AddThemeConstantOverride("margin_bottom", 12);
		listCard.AddChild(listMargin);
		var scroll = new ScrollContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
		};
		listMargin.AddChild(scroll);
		_memoryItemList = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_memoryItemList.AddThemeConstantOverride("separation", 8);
		scroll.AddChild(_memoryItemList);

		var detailCard = CreateMemoryCard(new Color(1f, 0.955f, 0.978f, 0.96f), 18);
		detailCard.CustomMinimumSize = new Vector2(360f, 0f);
		detailCard.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		body.AddChild(detailCard);
		BuildMemoryDetailPane(detailCard);
	}

	private void BuildMemoryDetailPane(PanelContainer card)
	{
		var outer = new MarginContainer();
		outer.AddThemeConstantOverride("margin_left", 16);
		outer.AddThemeConstantOverride("margin_right", 16);
		outer.AddThemeConstantOverride("margin_top", 16);
		outer.AddThemeConstantOverride("margin_bottom", 16);
		card.AddChild(outer);

		var stack = new VBoxContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill };
		outer.AddChild(stack);

		// Empty state riêng thay cho cả một form bị disable màu xám. Người dùng chưa
		// chọn gì thì panel nên hướng dẫn, không nên trông như ứng dụng vừa mất điện.
		var emptyCard = CreateMemoryCard(new Color(1f, 0.985f, 0.993f, 1f), 16);
		emptyCard.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		stack.AddChild(emptyCard);
		_memoryDetailEmpty = emptyCard;
		var emptyMargin = new MarginContainer();
		emptyMargin.AddThemeConstantOverride("margin_left", 24);
		emptyMargin.AddThemeConstantOverride("margin_right", 24);
		emptyMargin.AddThemeConstantOverride("margin_top", 32);
		emptyMargin.AddThemeConstantOverride("margin_bottom", 32);
		emptyCard.AddChild(emptyMargin);
		var emptyBox = new VBoxContainer { Alignment = BoxContainer.AlignmentMode.Center };
		emptyBox.AddThemeConstantOverride("separation", 10);
		emptyMargin.AddChild(emptyBox);
		var emptyTitle = CreateUiLabel("Chọn một điều ERIS đang nhớ", 18, MemoryInk);
		emptyTitle.HorizontalAlignment = HorizontalAlignment.Center;
		emptyTitle.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		emptyBox.AddChild(emptyTitle);
		var emptyText = CreateUiLabel("Bạn có thể xem nguồn, sửa lại, xác nhận, đổi phạm vi hoặc yêu cầu quên.", 12, MemoryInkSoft);
		emptyText.HorizontalAlignment = HorizontalAlignment.Center;
		emptyText.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		emptyBox.AddChild(emptyText);

		_memoryDetailScroll = new ScrollContainer
		{
			Visible = false,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
		};
		stack.AddChild(_memoryDetailScroll);
		_memoryDetailContent = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_memoryDetailContent.AddThemeConstantOverride("separation", 9);
		_memoryDetailScroll.AddChild(_memoryDetailContent);

		_memoryDetailTitle = CreateUiLabel("", 19, MemoryInk);
		_memoryDetailTitle.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_memoryDetailContent.AddChild(_memoryDetailTitle);
		_memoryDetailMeta = CreateUiLabel("", 11, MemoryInkSoft);
		_memoryDetailMeta.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_memoryDetailContent.AddChild(_memoryDetailMeta);
		_memoryDetailPath = CreateUiLabel("", 9, new Color(0.58f, 0.39f, 0.49f));
		_memoryDetailPath.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_memoryDetailContent.AddChild(_memoryDetailPath);

		_memoryDetailContent.AddChild(CreateUiLabel("Giá trị đang dùng", 11, MemoryInkSoft));
		_memoryEditValue = new TextEdit
		{
			CustomMinimumSize = new Vector2(0f, 96f),
			WrapMode = TextEdit.LineWrappingMode.Boundary,
			PlaceholderText = "Nhập giá trị đúng...",
		};
		StyleMemoryInput(_memoryEditValue);
		_memoryDetailContent.AddChild(_memoryEditValue);

		var editRow = new HBoxContainer();
		editRow.AddThemeConstantOverride("separation", 8);
		_memoryDetailContent.AddChild(editRow);
		_memorySaveButton = CreateMemoryButton("Lưu thay đổi", SaveSelectedMemory, primary: true);
		_memoryConfirmButton = CreateMemoryButton("Xác nhận đúng", ConfirmSelectedMemory, primary: false);
		editRow.AddChild(_memorySaveButton);
		editRow.AddChild(_memoryConfirmButton);

		var sourceRow = new HBoxContainer();
		sourceRow.AddThemeConstantOverride("separation", 8);
		_memoryDetailContent.AddChild(sourceRow);
		_memoryExplainButton = CreateMemoryButton("Xem nguồn", ExplainSelectedMemory, primary: false);
		_memoryMoveScopeButton = CreateMemoryButton("Áp dụng phạm vi", MoveSelectedMemoryScope, primary: false);
		sourceRow.AddChild(_memoryExplainButton);
		sourceRow.AddChild(_memoryMoveScopeButton);

		_memoryDetailContent.AddChild(CreateUiLabel("Phạm vi sử dụng", 11, MemoryInkSoft));
		_memoryScopeSelect = new OptionButton();
		_memoryScopeSelect.AddItem("Mọi cuộc trò chuyện");
		_memoryScopeSelect.AddItem("Chỉ một dự án");
		_memoryScopeSelect.ItemSelected += index => _memoryProjectInput.Visible = index == 1;
		StyleMemoryInput(_memoryScopeSelect);
		_memoryDetailContent.AddChild(_memoryScopeSelect);
		_memoryProjectInput = new LineEdit { PlaceholderText = "Mã dự án, ví dụ: eris", Visible = false };
		StyleMemoryInput(_memoryProjectInput);
		_memoryDetailContent.AddChild(_memoryProjectInput);

		_memoryDetailContent.AddChild(new HSeparator());
		_memoryHardDeleteToggle = new CheckButton { Text = "Xóa cả dữ liệu nguồn liên quan" };
		_memoryHardDeleteToggle.AddThemeFontSizeOverride("font_size", 11);
		_memoryHardDeleteToggle.AddThemeColorOverride("font_color", new Color(0.68f, 0.16f, 0.25f));
		_memoryDetailContent.AddChild(_memoryHardDeleteToggle);
		_memoryForgetButton = CreateMemoryButton("Quên mục này", ForgetSelectedMemory, primary: false, danger: true);
		_memoryDetailContent.AddChild(_memoryForgetButton);

		_memoryDetailContent.AddChild(CreateUiLabel("Nguồn hình thành", 11, MemoryInkSoft));
		_memoryExplanationLabel = CreateUiLabel("Bấm “Xem nguồn” để đọc evidence.", 11, MemoryInkSoft);
		_memoryExplanationLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_memoryExplanationLabel.CustomMinimumSize = new Vector2(0f, 90f);
		_memoryDetailContent.AddChild(_memoryExplanationLabel);
		SetMemoryDetailEnabled(false);
	}

	private void SendMemoryPanelRequest(string action, Dictionary<string, object> extra = null)
	{
		if (_chatSend == null)
			return;
		_memoryLastRequestId = $"memory-{Time.GetTicksMsec()}-{GD.Randi()}";
		var payload = new Dictionary<string, object>
		{
			["type"] = "memory_panel_request",
			["action"] = action,
			["request_id"] = _memoryLastRequestId,
			["include_inferred"] = _memoryIncludeInferredToggle?.ButtonPressed ?? true,
		};
		if (extra != null)
			foreach (var pair in extra)
				payload[pair.Key] = pair.Value;
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		if (error != Error.Ok)
		{
			SetMemoryStatus($"Không gửi được request: {error}", true);
			return;
		}
		_memoryRequestPending = true;
		_memoryPendingAction = action;
		_memoryRequestSentAtMs = Time.GetTicksMsec();
		SetMemoryStatus(action == "snapshot" ? "Đang đọc memory..." : "Đang áp dụng thay đổi...");
	}

	private bool TryHandleMemoryPanelPacket(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return false;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object
				|| !root.TryGetProperty("type", out JsonElement typeNode)
				|| !string.Equals(typeNode.GetString(), "memory_panel_ack", StringComparison.Ordinal))
				return false;

			string requestId = ReadJsonString(root, "request_id");
			if (!string.IsNullOrWhiteSpace(_memoryLastRequestId)
				&& !string.IsNullOrWhiteSpace(requestId)
				&& !string.Equals(requestId, _memoryLastRequestId, StringComparison.Ordinal))
				return true;

			_memoryRequestPending = false;
			_memoryPendingAction = "";
			string status = ReadJsonString(root, "status");
			string message = ReadJsonString(root, "message");
			if (root.TryGetProperty("memory_panel", out JsonElement panel) && panel.ValueKind == JsonValueKind.Object)
			{
				ApplyMemoryPanelSnapshot(panel);
				SaveMemoryPanelCache(panel.GetRawText());
			}
			SetMemoryStatus(string.IsNullOrWhiteSpace(message) ? "Đã cập nhật." : message, status == "error");
			return true;
		}
		catch (JsonException)
		{
			return false;
		}
		catch (Exception ex)
		{
			SetMemoryStatus($"Không đọc được dữ liệu memory: {ex.Message}", true);
			return true;
		}
	}

	private void ApplyMemoryPanelSnapshot(JsonElement panel)
	{
		_memoryRecords.Clear();
		_memoryActions.Clear();
		_memorySummaryText = ReadJsonString(panel, "summary_text");
		if (string.IsNullOrWhiteSpace(_memorySummaryText))
			_memorySummaryText = "ERIS chưa có đủ thông tin bền vững để tổng hợp về bạn.";

		if (panel.TryGetProperty("records", out JsonElement records) && records.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement row in records.EnumerateArray())
			{
				if (row.ValueKind != JsonValueKind.Object)
					continue;
				_memoryRecords.Add(new MemoryPanelRecord
				{
					Id = ReadJsonString(row, "id"),
					Path = ReadJsonString(row, "path"),
					Label = ReadJsonString(row, "label"),
					Category = ReadJsonString(row, "category"),
					DisplayValue = ReadJsonString(row, "display_value"),
					Explicitness = ReadJsonString(row, "explicitness"),
					ExplicitnessLabel = ReadJsonString(row, "explicitness_label"),
					CertaintyLabel = ReadJsonString(row, "certainty_label"),
					ScopeKind = ReadJsonString(row, "scope_kind"),
					ScopeKey = ReadJsonString(row, "scope_key"),
					ScopeLabel = ReadJsonString(row, "scope_label"),
					Source = ReadJsonString(row, "source"),
					Confidence = ReadJsonFloat(row, "confidence"),
					EvidenceCount = ReadJsonInt(row, "evidence_count"),
					Recurrence = ReadJsonInt(row, "recurrence"),
					UpdatedAt = ReadJsonDouble(row, "updated_at"),
				});
			}
		}
		ReadMemoryActionRows(panel, "goals", "goal");
		ReadMemoryActionRows(panel, "commitments", "commitment");
		ReadMemoryActionRows(panel, "workflows", "workflow");

		if (panel.TryGetProperty("counts", out JsonElement counts) && counts.ValueKind == JsonValueKind.Object)
		{
			_memoryCountLabel.Text = $"{ReadJsonInt(counts, "confirmed")} đã xác nhận  ·  "
				+ $"{ReadJsonInt(counts, "observed")} quan sát  ·  "
				+ $"{ReadJsonInt(counts, "inferred")} suy đoán  ·  "
				+ $"{ReadJsonInt(counts, "goals")} mục tiêu  ·  "
				+ $"{ReadJsonInt(counts, "workflows")} quy trình";
		}

		if (panel.TryGetProperty("cleanup", out JsonElement cleanup) && cleanup.ValueKind == JsonValueKind.Object)
		{
			bool available = ReadJsonBool(cleanup, "available");
			bool autoCleanup = ReadJsonBool(cleanup, "auto_cleanup");
			_memoryApplyingCleanupSnapshot = true;
			if (_memoryAutoCleanupToggle != null)
			{
				_memoryAutoCleanupToggle.Disabled = !available;
				_memoryAutoCleanupToggle.ButtonPressed = autoCleanup;
			}
			_memoryApplyingCleanupSnapshot = false;
			bool running = ReadJsonBool(cleanup, "running");
			_memoryCleanupPolling = running;
			if (running) _memoryCleanupPollAtMs = Time.GetTicksMsec() + 2500UL;
			if (_memoryCleanupNowButton != null) _memoryCleanupNowButton.Disabled = !available || running;
			if (_memoryCleanupLabel != null) _memoryCleanupLabel.Text = FormatCleanupStatus(cleanup);
		}
		if (panel.TryGetProperty("memory_feed_trace", out JsonElement feed) && feed.ValueKind == JsonValueKind.Object
			&& _memoryFeedTraceLabel != null)
			_memoryFeedTraceLabel.Text = FormatMemoryFeedTrace(feed);

		if (panel.TryGetProperty("cleanup_report", out JsonElement cleanupReport) && cleanupReport.ValueKind == JsonValueKind.Object
			&& _memoryCleanupLabel != null)
			_memoryCleanupLabel.Text = FormatCleanupReport(cleanupReport);

		if (panel.TryGetProperty("explanation", out JsonElement explanation))
			_memoryExplanationLabel.Text = FormatMemoryExplanation(explanation);
		RefreshMemoryPanel();
	}

	private void ReadMemoryActionRows(JsonElement panel, string property, string kind)
	{
		if (!panel.TryGetProperty(property, out JsonElement rows) || rows.ValueKind != JsonValueKind.Array)
			return;
		foreach (JsonElement row in rows.EnumerateArray())
		{
			if (row.ValueKind != JsonValueKind.Object)
				continue;
			string title = kind switch
			{
				"goal" => ReadJsonString(row, "title"),
				"commitment" => ReadJsonString(row, "action"),
				_ => ReadJsonString(row, "trigger"),
			};
			string detail = kind == "workflow" && row.TryGetProperty("steps", out JsonElement steps)
				? JoinJsonArray(steps, " → ")
				: ReadJsonString(row, "description");
			_memoryActions.Add(new MemoryPanelActionItem
			{
				Kind = kind,
				Title = title,
				Detail = detail,
				Status = ReadJsonString(row, "status"),
			});
		}
	}

	private void RefreshMemoryPanel()
	{
		if (_memorySummaryLabel != null)
			_memorySummaryLabel.Text = CompactSummaryForPanel(_memorySummaryText);
		RefreshMemoryPanelList();
		if (_selectedMemoryRecord != null)
		{
			MemoryPanelRecord current = _memoryRecords.FirstOrDefault(x => x.Path == _selectedMemoryRecord.Path && x.ScopeKey == _selectedMemoryRecord.ScopeKey);
			SelectMemoryRecord(current);
		}
	}

	private void RefreshMemoryPanelList()
	{
		if (_memoryItemList == null)
			return;
		foreach (Node child in _memoryItemList.GetChildren())
		{
			_memoryItemList.RemoveChild(child);
			child.QueueFree();
		}

		string query = (_memorySearchInput?.Text ?? "").Trim();
		int tab = _memoryCategorySelect?.Selected ?? 0;
		bool includeInferred = _memoryIncludeInferredToggle?.ButtonPressed ?? true;
		IEnumerable<MemoryPanelRecord> rows = _memoryRecords.Where(record =>
			(includeInferred || record.Explicitness != "inferred")
			&& MemoryRecordMatchesTab(record, tab)
			&& MemoryRecordMatchesSearch(record, query));

		int shown = 0;
		foreach (MemoryPanelRecord record in rows)
		{
			_memoryItemList.AddChild(CreateMemoryRecordCard(record));
			shown++;
		}

		if (tab == 0 || tab == 3 || tab == 4)
		{
			foreach (MemoryPanelActionItem action in _memoryActions.Where(a => ActionMatchesTab(a, tab) && ActionMatchesSearch(a, query)))
			{
				_memoryItemList.AddChild(CreateMemoryActionCard(action));
				shown++;
			}
		}

		if (shown == 0)
		{
			bool hasAnyMemory = _memoryRecords.Count > 0 || _memoryActions.Count > 0;
			_memoryItemList.AddChild(CreateMemoryEmptyState(
				hasAnyMemory ? "Không có mục nào khớp" : "ERIS chưa có điều gì để hiển thị",
				hasAnyMemory
					? "Thử đổi bộ lọc hoặc từ khóa tìm kiếm."
					: "Hãy trò chuyện tự nhiên. Những điều bền vững và hữu ích sẽ xuất hiện ở đây."));
		}
	}

	private Control CreateMemoryEmptyState(string titleText, string detailText)
	{
		var card = CreateMemoryCard(new Color(1f, 0.985f, 0.993f, 0.96f), 16);
		card.CustomMinimumSize = new Vector2(0f, 170f);
		var margin = new MarginContainer();
		margin.AddThemeConstantOverride("margin_left", 24);
		margin.AddThemeConstantOverride("margin_right", 24);
		margin.AddThemeConstantOverride("margin_top", 34);
		margin.AddThemeConstantOverride("margin_bottom", 34);
		card.AddChild(margin);
		var box = new VBoxContainer { Alignment = BoxContainer.AlignmentMode.Center };
		box.AddThemeConstantOverride("separation", 8);
		margin.AddChild(box);
		var title = CreateUiLabel(titleText, 17, MemoryInk);
		title.HorizontalAlignment = HorizontalAlignment.Center;
		title.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		box.AddChild(title);
		var detail = CreateUiLabel(detailText, 12, MemoryInkSoft);
		detail.HorizontalAlignment = HorizontalAlignment.Center;
		detail.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		box.AddChild(detail);
		return card;
	}

	private Control CreateMemoryRecordCard(MemoryPanelRecord record)
	{
		Color accent = record.Explicitness switch
		{
			"explicit" => new Color(0.30f, 0.67f, 0.42f),
			"observed" => new Color(0.32f, 0.56f, 0.86f),
			_ => new Color(0.88f, 0.58f, 0.22f),
		};
		var card = CreateMemoryCard(new Color(1f, 1f, 1f, 0.88f), 13, accent);
		var margin = new MarginContainer();
		margin.AddThemeConstantOverride("margin_left", 13);
		margin.AddThemeConstantOverride("margin_right", 10);
		margin.AddThemeConstantOverride("margin_top", 10);
		margin.AddThemeConstantOverride("margin_bottom", 10);
		card.AddChild(margin);
		var box = new VBoxContainer();
		box.AddThemeConstantOverride("separation", 4);
		margin.AddChild(box);

		var header = new HBoxContainer();
		box.AddChild(header);
		var title = CreateUiLabel(record.Label, 14, MemoryInk);
		title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		title.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		header.AddChild(title);
		var badge = CreateUiLabel(record.CertaintyLabel, 9, accent);
		header.AddChild(badge);

		var value = CreateUiLabel(record.DisplayValue, 13, new Color(0.47f, 0.18f, 0.32f));
		value.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		value.MaxLinesVisible = 3;
		value.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		box.AddChild(value);
		var footer = new HBoxContainer();
		box.AddChild(footer);
		var meta = CreateUiLabel($"{record.ExplicitnessLabel}  ·  {record.ScopeLabel}  ·  {record.EvidenceCount} nguồn", 10, MemoryInkSoft);
		meta.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		footer.AddChild(meta);
		var view = CreateMemoryButton("Xem", () => SelectMemoryRecord(record), primary: false);
		view.CustomMinimumSize = new Vector2(70f, 30f);
		footer.AddChild(view);
		return card;
	}

	private Control CreateMemoryActionCard(MemoryPanelActionItem action)
	{
		Color accent = action.Kind == "goal" ? new Color(0.64f, 0.38f, 0.88f)
			: action.Kind == "workflow" ? new Color(0.23f, 0.63f, 0.68f)
			: new Color(0.90f, 0.45f, 0.45f);
		var card = CreateMemoryCard(new Color(0.985f, 0.965f, 1f, 0.90f), 13, accent);
		var margin = new MarginContainer();
		margin.AddThemeConstantOverride("margin_left", 13);
		margin.AddThemeConstantOverride("margin_right", 13);
		margin.AddThemeConstantOverride("margin_top", 10);
		margin.AddThemeConstantOverride("margin_bottom", 10);
		card.AddChild(margin);
		var box = new VBoxContainer();
		margin.AddChild(box);
		string kind = action.Kind == "goal" ? "Mục tiêu" : action.Kind == "workflow" ? "Quy trình" : "Cam kết";
		var title = CreateUiLabel($"{kind}: {action.Title}", 12, MemoryInk);
		title.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		box.AddChild(title);
		if (!string.IsNullOrWhiteSpace(action.Detail))
		{
			var detail = CreateUiLabel(action.Detail, 10, MemoryInkSoft);
			detail.AutowrapMode = TextServer.AutowrapMode.WordSmart;
			box.AddChild(detail);
		}
		return card;
	}

	private void SelectMemoryRecord(MemoryPanelRecord record)
	{
		_selectedMemoryRecord = record;
		bool enabled = record != null;
		SetMemoryDetailEnabled(enabled);
		_memoryExplanationLabel.Text = "Chưa đọc nguồn.";
		if (!enabled)
		{
			_memoryEditValue.Text = "";
			return;
		}
		_memoryDetailTitle.Text = record.Label;
		_memoryDetailMeta.Text = $"{record.ExplicitnessLabel} · {record.CertaintyLabel} · {record.ScopeLabel}\n"
			+ $"Độ chắc chắn hiển thị: {Mathf.RoundToInt(record.Confidence * 100f)}% · lặp lại {record.Recurrence} lần";
		_memoryDetailPath.Text = $"Mã memory: {record.Path}";
		_memoryEditValue.Text = record.DisplayValue;
		_memoryScopeSelect.Select(record.ScopeKind == "project" ? 1 : 0);
		_memoryProjectInput.Visible = record.ScopeKind == "project";
		_memoryProjectInput.Text = record.ScopeKey;
		_memoryHardDeleteToggle.ButtonPressed = false;
		_memoryHardDeleteArmedPath = "";
		_memoryForgetButton.Text = "Quên mục này";
	}

	private void SaveSelectedMemory()
	{
		if (_selectedMemoryRecord == null)
			return;
		SendMemoryPanelRequest("correct", new Dictionary<string, object>
		{
			["path"] = _selectedMemoryRecord.Path,
			["value"] = _memoryEditValue.Text,
			["project_id"] = _selectedMemoryRecord.ScopeKind == "project" ? _selectedMemoryRecord.ScopeKey : "",
		});
	}

	private void ConfirmSelectedMemory()
	{
		if (_selectedMemoryRecord == null)
			return;
		SendMemoryPanelRequest("confirm", new Dictionary<string, object>
		{
			["path"] = _selectedMemoryRecord.Path,
			["project_id"] = _selectedMemoryRecord.ScopeKind == "project" ? _selectedMemoryRecord.ScopeKey : "",
		});
	}

	private void ExplainSelectedMemory()
	{
		if (_selectedMemoryRecord == null)
			return;
		_memoryExplanationLabel.Text = "Đang đọc nguồn...";
		SendMemoryPanelRequest("explain", new Dictionary<string, object>
		{
			["path"] = _selectedMemoryRecord.Path,
			["project_id"] = _selectedMemoryRecord.ScopeKind == "project" ? _selectedMemoryRecord.ScopeKey : "",
		});
	}

	private void MoveSelectedMemoryScope()
	{
		if (_selectedMemoryRecord == null)
			return;
		bool project = _memoryScopeSelect.Selected == 1;
		SendMemoryPanelRequest("move_scope", new Dictionary<string, object>
		{
			["path"] = _selectedMemoryRecord.Path,
			["project_id"] = _selectedMemoryRecord.ScopeKind == "project" ? _selectedMemoryRecord.ScopeKey : "",
			["target_scope_kind"] = project ? "project" : "global",
			["target_scope_key"] = project ? _memoryProjectInput.Text.Trim() : "",
		});
	}

	private void ForgetSelectedMemory()
	{
		if (_selectedMemoryRecord == null)
			return;
		bool hard = _memoryHardDeleteToggle.ButtonPressed;
		if (hard && !string.Equals(_memoryHardDeleteArmedPath, _selectedMemoryRecord.Path, StringComparison.Ordinal))
		{
			_memoryHardDeleteArmedPath = _selectedMemoryRecord.Path;
			_memoryForgetButton.Text = "Bấm lần nữa để xóa";
			SetMemoryStatus("Xóa hoàn toàn không thể hoàn tác. Bấm nút lần nữa để xác nhận.", true);
			return;
		}
		_memoryHardDeleteArmedPath = "";
		_memoryForgetButton.Text = "Quên mục này";
		SendMemoryPanelRequest("forget", new Dictionary<string, object>
		{
			["path"] = _selectedMemoryRecord.Path,
			["project_id"] = _selectedMemoryRecord.ScopeKind == "project" ? _selectedMemoryRecord.ScopeKey : "",
			["hard"] = hard,
		});
	}

	private void StartMemoryCleanup()
	{
		_memoryCleanupPolling = true;
		_memoryCleanupPollAtMs = Time.GetTicksMsec() + 2500UL;
		if (_memoryCleanupNowButton != null) _memoryCleanupNowButton.Disabled = true;
		if (_memoryCleanupLabel != null) _memoryCleanupLabel.Text = "DeepSeek đang rà memory...";
		SendMemoryPanelRequest("cleanup_now");
	}

	private static string FormatCleanupStatus(JsonElement cleanup)
	{
		if (!ReadJsonBool(cleanup, "available")) return "Curator chưa sẵn sàng.";
		if (ReadJsonBool(cleanup, "running")) return "DeepSeek đang rà; runtime sẽ validate trước khi ghi.";
		string prefix = ReadJsonBool(cleanup, "auto_cleanup") ? "Auto cleanup đang bật" : "Auto cleanup đang tắt";
		if (!cleanup.TryGetProperty("last_result", out JsonElement last) || last.ValueKind != JsonValueKind.Object)
			return prefix + ".";
		int dropped = ReadJsonInt(last, "ds_dropped") + ReadJsonInt(last, "living_applied")
			+ ReadJsonInt(last, "behavior_removed") + ReadJsonInt(last, "thought_removed");
		return dropped > 0 ? $"{prefix} · lần gần nhất áp dụng {dropped} thay đổi" : prefix + " · lần gần nhất không cần đổi";
	}

	private static string FormatCleanupReport(JsonElement report)
	{
		int reviewed = ReadJsonInt(report, "ds_reviewed") + ReadJsonInt(report, "living_reviewed");
		int changed = ReadJsonInt(report, "ds_dropped") + ReadJsonInt(report, "living_applied")
			+ ReadJsonInt(report, "behavior_removed") + ReadJsonInt(report, "thought_removed");
		return $"DeepSeek rà {reviewed} · runtime áp dụng {changed} thay đổi an toàn";
	}

	private static string FormatMemoryFeedTrace(JsonElement feed)
	{
		if (!feed.TryGetProperty("latest", out JsonElement latest) || latest.ValueKind != JsonValueKind.Object)
			return "Memory feed: chưa có trace.";
		int retrieved = ReadJsonInt(latest, "retrieved");
		int admitted = ReadJsonInt(latest, "admitted");
		int rejected = ReadJsonInt(latest, "rejected");
		int rendered = ReadJsonInt(latest, "rendered");
		return $"Feed {retrieved} → nhận {admitted} / loại {rejected} → prompt {rendered}";
	}

	private void TickMemoryPanelStatus()
	{
		ulong now = Time.GetTicksMsec();
		if (!_memoryRequestPending && _memoryCleanupPolling && now >= _memoryCleanupPollAtMs)
		{
			_memoryCleanupPollAtMs = now + 2500UL;
			SendMemoryPanelRequest("snapshot");
			return;
		}
		if (!_memoryRequestPending)
			return;
		ulong elapsed = now - _memoryRequestSentAtMs;
		if (elapsed > 6500UL)
		{
			_memoryRequestPending = false;
			SetMemoryStatus("Brain chưa trả lời; vẫn đang hiển thị cache gần nhất.", true);
		}
	}

	private void SetMemoryStatus(string text, bool error = false)
	{
		if (_memoryStatusLabel == null)
			return;
		_memoryStatusLabel.Text = text;
		_memoryStatusLabel.AddThemeColorOverride("font_color", error ? new Color(0.76f, 0.18f, 0.28f) : MemoryInkSoft);
	}

	private void SetMemoryDetailEnabled(bool enabled)
	{
		if (_memoryDetailEmpty != null)
			_memoryDetailEmpty.Visible = !enabled;
		if (_memoryDetailContent != null)
			_memoryDetailContent.Visible = enabled;
		if (_memoryDetailScroll != null)
			_memoryDetailScroll.Visible = enabled;
		foreach (BaseButton button in new BaseButton[] { _memorySaveButton, _memoryConfirmButton, _memoryExplainButton, _memoryMoveScopeButton, _memoryForgetButton })
			if (button != null) button.Disabled = !enabled;
		if (_memoryEditValue != null) _memoryEditValue.Editable = enabled;
		if (_memoryScopeSelect != null) _memoryScopeSelect.Disabled = !enabled;
		if (_memoryProjectInput != null) _memoryProjectInput.Editable = enabled;
		if (_memoryHardDeleteToggle != null) _memoryHardDeleteToggle.Disabled = !enabled;
	}

	private Button CreateMemoryButton(string text, Action onPressed, bool primary, bool danger = false)
	{
		var button = new Button
		{
			Text = text,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			CustomMinimumSize = new Vector2(112f, 34f),
			ClipText = true,
			TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis,
		};
		Color bg = danger ? new Color(0.98f, 0.88f, 0.90f) : primary ? MemoryPink : new Color(1f, 0.98f, 0.99f);
		Color border = danger ? new Color(0.88f, 0.42f, 0.48f) : MemoryBorder;
		var normal = new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = border,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10,
			CornerRadiusTopRight = 10,
			CornerRadiusBottomLeft = 10,
			CornerRadiusBottomRight = 10,
			ContentMarginLeft = 8,
			ContentMarginRight = 8,
			ContentMarginTop = 4,
			ContentMarginBottom = 4,
		};
		var hover = (StyleBoxFlat)normal.Duplicate();
		hover.BgColor = danger ? new Color(1f, 0.82f, 0.86f) : primary ? new Color(0.98f, 0.43f, 0.68f) : new Color(1f, 0.92f, 0.96f);
		button.AddThemeStyleboxOverride("normal", normal);
		button.AddThemeStyleboxOverride("hover", hover);
		button.AddThemeStyleboxOverride("pressed", hover);
		button.AddThemeStyleboxOverride("focus", hover);
		button.AddThemeColorOverride("font_color", primary ? Colors.White : danger ? new Color(0.72f, 0.15f, 0.23f) : MemoryInk);
		button.AddThemeColorOverride("font_hover_color", primary ? Colors.White : MemoryPink);
		button.AddThemeFontSizeOverride("font_size", 11);
		button.Pressed += onPressed;
		return button;
	}

	private static PanelContainer CreateMemoryCard(Color background, int radius, Color? leftAccent = null)
	{
		var card = new PanelContainer();
		var style = new StyleBoxFlat
		{
			BgColor = background,
			BorderColor = new Color(0.95f, 0.78f, 0.86f, 0.82f),
			BorderWidthLeft = leftAccent.HasValue ? 4 : 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = radius,
			CornerRadiusTopRight = radius,
			CornerRadiusBottomLeft = radius,
			CornerRadiusBottomRight = radius,
		};
		if (leftAccent.HasValue)
			style.BorderColor = leftAccent.Value;
		card.AddThemeStyleboxOverride("panel", style);
		return card;
	}

	private static void StyleMemoryInput(Control control)
	{
		var normal = new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0.86f),
			BorderColor = MemoryBorder,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10,
			CornerRadiusTopRight = 10,
			CornerRadiusBottomLeft = 10,
			CornerRadiusBottomRight = 10,
			ContentMarginLeft = 9,
			ContentMarginRight = 9,
			ContentMarginTop = 6,
			ContentMarginBottom = 6,
		};
		control.AddThemeStyleboxOverride("normal", normal);
		control.AddThemeStyleboxOverride("focus", normal);
		control.AddThemeColorOverride("font_color", MemoryInk);
		control.AddThemeFontSizeOverride("font_size", 12);
	}

	private static bool MemoryRecordMatchesTab(MemoryPanelRecord record, int tab) => tab switch
	{
		1 => record.Category == "about" || record.Category == "communication" || record.Category == "interaction",
		2 => record.Category == "preferences",
		3 => record.Category == "projects",
		4 => record.Category == "workflow",
		5 => record.Explicitness == "inferred" || record.Confidence < 0.72f,
		_ => true,
	};

	private static bool ActionMatchesTab(MemoryPanelActionItem action, int tab) => tab switch
	{
		3 => action.Kind is "goal" or "commitment",
		4 => action.Kind == "workflow",
		_ => true,
	};

	private static bool MemoryRecordMatchesSearch(MemoryPanelRecord record, string query)
	{
		if (string.IsNullOrWhiteSpace(query)) return true;
		return ContainsIgnoreCase(record.Label, query)
			|| ContainsIgnoreCase(record.DisplayValue, query)
			|| ContainsIgnoreCase(record.Path, query)
			|| ContainsIgnoreCase(record.ScopeLabel, query);
	}

	private static bool ActionMatchesSearch(MemoryPanelActionItem action, string query)
	{
		if (string.IsNullOrWhiteSpace(query)) return true;
		return ContainsIgnoreCase(action.Title, query) || ContainsIgnoreCase(action.Detail, query);
	}

	private static bool ContainsIgnoreCase(string value, string query) =>
		(value ?? "").IndexOf(query ?? "", StringComparison.OrdinalIgnoreCase) >= 0;

	private static string CompactSummaryForPanel(string text)
	{
		string clean = (text ?? "").Replace("\r", "").Trim();
		if (clean.Length <= 620) return clean;
		return clean[..617].TrimEnd() + "...";
	}

	private static string FormatMemoryExplanation(JsonElement explanation)
	{
		if (explanation.ValueKind != JsonValueKind.Array || explanation.GetArrayLength() == 0)
			return "Không tìm thấy evidence chi tiết. Memory có thể đến từ dữ liệu legacy hoặc bản tổng hợp cũ.";
		var lines = new List<string>();
		foreach (JsonElement row in explanation.EnumerateArray())
		{
			if (row.ValueKind != JsonValueKind.Object) continue;
			string summary = ReadJsonString(row, "summary");
			string reason = ReadJsonString(row, "reason");
			string note = ReadJsonString(row, "note");
			if (string.IsNullOrWhiteSpace(summary)) summary = ReadJsonString(row, "detail");
			if (!string.IsNullOrWhiteSpace(summary)) lines.Add("• " + summary);
			if (!string.IsNullOrWhiteSpace(note)) lines.Add("• " + note);
			if (!string.IsNullOrWhiteSpace(reason)) lines.Add("  " + reason);
			JsonElement evidence = default;
			bool hasEvidence = row.TryGetProperty("evidence", out evidence) || row.TryGetProperty("sources", out evidence);
			if (hasEvidence && evidence.ValueKind == JsonValueKind.Array)
			{
				foreach (JsonElement item in evidence.EnumerateArray().Take(4))
				{
					string excerpt = item.ValueKind == JsonValueKind.Object ? ReadJsonString(item, "excerpt") : item.ToString();
					if (!string.IsNullOrWhiteSpace(excerpt)) lines.Add("  - " + excerpt);
				}
			}
		}
		return lines.Count > 0 ? string.Join("\n", lines) : "Nguồn tồn tại nhưng không có đoạn trích hiển thị.";
	}

	private static string ReadJsonString(JsonElement root, string name)
	{
		if (!root.TryGetProperty(name, out JsonElement value)) return "";
		return value.ValueKind switch
		{
			JsonValueKind.String => value.GetString() ?? "",
			JsonValueKind.Null => "",
			_ => value.ToString(),
		};
	}

	private static bool ReadJsonBool(JsonElement root, string name)
	{
		if (!root.TryGetProperty(name, out JsonElement value)) return false;
		if (value.ValueKind == JsonValueKind.True) return true;
		if (value.ValueKind == JsonValueKind.False) return false;
		return bool.TryParse(value.ToString(), out bool parsed) && parsed;
	}

	private static int ReadJsonInt(JsonElement root, string name)
	{
		if (!root.TryGetProperty(name, out JsonElement value)) return 0;
		if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int number)) return number;
		return int.TryParse(value.ToString(), out int parsed) ? parsed : 0;
	}

	private static float ReadJsonFloat(JsonElement root, string name)
	{
		if (!root.TryGetProperty(name, out JsonElement value)) return 0f;
		if (value.ValueKind == JsonValueKind.Number && value.TryGetSingle(out float number)) return number;
		return float.TryParse(value.ToString(), out float parsed) ? parsed : 0f;
	}

	private static double ReadJsonDouble(JsonElement root, string name)
	{
		if (!root.TryGetProperty(name, out JsonElement value)) return 0.0;
		if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double number)) return number;
		return double.TryParse(value.ToString(), out double parsed) ? parsed : 0.0;
	}

	private static string JoinJsonArray(JsonElement value, string separator)
	{
		if (value.ValueKind != JsonValueKind.Array) return "";
		return string.Join(separator, value.EnumerateArray().Select(x => x.ValueKind == JsonValueKind.String ? x.GetString() : x.ToString()).Where(x => !string.IsNullOrWhiteSpace(x)));
	}

	private void SaveMemoryPanelCache(string json)
	{
		try
		{
			using var file = Godot.FileAccess.Open(MemoryPanelCachePath, Godot.FileAccess.ModeFlags.Write);
			file?.StoreString(json);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[MemoryPanel] Cache save failed: {ex.Message}");
		}
	}

	private void LoadMemoryPanelCache()
	{
		try
		{
			if (!Godot.FileAccess.FileExists(MemoryPanelCachePath)) return;
			using var file = Godot.FileAccess.Open(MemoryPanelCachePath, Godot.FileAccess.ModeFlags.Read);
			string json = file?.GetAsText() ?? "";
			if (string.IsNullOrWhiteSpace(json)) return;
			using JsonDocument doc = JsonDocument.Parse(json);
			if (doc.RootElement.ValueKind == JsonValueKind.Object)
				ApplyMemoryPanelSnapshot(doc.RootElement);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[MemoryPanel] Cache load failed: {ex.Message}");
		}
	}
}
