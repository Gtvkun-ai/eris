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

	// Đây là projection public do Surface worker viết. Nó KHÔNG phải truth store.
	// Canonical record vẫn nằm ở MemoryPanelRecord và chỉ xuất hiện khi user mở Quản lý.
	private sealed class MemoryPortraitItem
	{
		public string Title { get; init; } = "";
		public string Body { get; init; } = "";
		public string Aside { get; init; } = "";
	}

	private sealed class MemoryPortraitSection
	{
		public string Kind { get; init; } = "";
		public string Title { get; init; } = "";
		public List<MemoryPortraitItem> Items { get; init; } = new();
	}

	private Panel _memoryPanel;
	private Button _contextMemoryButton;
	private VBoxContainer _memoryItemList;
	private VBoxContainer _memoryPortraitRoot;
	private VBoxContainer _memoryManagerRoot;
	private VBoxContainer _memoryPortraitLeftList;
	private VBoxContainer _memoryPortraitRightList;
	private Label _memorySummaryLabel;
	private Label _memoryPortraitAsideLabel;
	private Label _memoryCountLabel;
	private Button _memoryModeButton;
	private Label _memoryStatusLabel;
	private LineEdit _memorySearchInput;
	private OptionButton _memoryCategorySelect;
	private CheckButton _memoryIncludeInferredToggle;
	private CheckButton _memoryAutoCleanupToggle;
	private Button _memoryCleanupNowButton;
	private Label _memoryCleanupLabel;
	private bool _memoryApplyingCleanupSnapshot;
	private bool _memoryCleanupPolling;
	// Gemini viết ở nền: chỉ hỏi Brain lại khi bản lưu chưa hoàn tất.
	private bool _memoryPortraitPolling;
	private ulong _memoryPortraitPollAtMs;
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
	private readonly List<MemoryPortraitSection> _memoryPortraitSections = new();
	private MemoryPanelRecord _selectedMemoryRecord;
	private string _memorySummaryText = "ERIS chưa gửi bản tổng hợp.";
	private string _memoryPortraitAside = "";
	private bool _memoryManagerVisible;
	private string _memoryLastRequestId = "";
	private ulong _memoryRequestSentAtMs;
	private bool _memoryRequestPending;
	private string _memoryPendingAction = "";
	private string _memoryHardDeleteArmedPath = "";

	private static readonly Color MemoryInk = new(0.39f, 0.08f, 0.25f);
	private static readonly Color MemoryInkSoft = new(0.48f, 0.27f, 0.38f);
	private static readonly Color MemoryPink = new(0.86f, 0.28f, 0.56f);
	private static readonly Color MemoryBorder = new(0.86f, 0.72f, 0.79f, 0.82f);
	private static readonly Color MemoryCard = new(1f, 0.995f, 0.998f, 0.98f);
	private static readonly Color MemoryPaper = new(0.985f, 0.972f, 0.978f, 0.995f);
	private static readonly Color MemoryHero = new(0.992f, 0.955f, 0.972f, 0.96f);
	private static readonly Color MemoryAside = new(0.62f, 0.34f, 0.47f);

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
		// Portrait có nguồn lưu bền ở Python. Bỏ cache Godot cũ để không hồi sinh
		// ký ức mà user đã yêu cầu quên ở phiên trước.
		try { System.IO.File.Delete(ProjectSettings.GlobalizePath(MemoryPanelCachePath)); }
		catch (Exception ex) { GD.PrintErr($"[MemoryPanel] Không dọn được cache cũ: {ex.Message}"); }
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
		SetMemoryManagerMode(false);
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
			BgColor = MemoryPaper,
			BorderColor = MemoryBorder,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 20,
			CornerRadiusTopRight = 20,
			CornerRadiusBottomLeft = 20,
			CornerRadiusBottomRight = 20,
			ShadowColor = new Color(0.30f, 0.08f, 0.19f, 0.16f),
			ShadowSize = 12,
		});
		_memoryPanel.ClipContents = true;

		var margin = new MarginContainer();
		margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		margin.AddThemeConstantOverride("margin_left", 26);
		margin.AddThemeConstantOverride("margin_right", 26);
		margin.AddThemeConstantOverride("margin_top", 20);
		margin.AddThemeConstantOverride("margin_bottom", 20);
		_memoryPanel.AddChild(margin);

		var root = new VBoxContainer();
		root.AddThemeConstantOverride("separation", 14);
		margin.AddChild(root);

		// Header mang giọng của ERIS trước, control kỹ thuật lùi xuống sau.
		// Mục tiêu của màn này là: user mở ra và có cảm giác đang nhìn vào
		// cách ERIS nhớ mình, không phải đang mở bảng quản trị dữ liệu.
		var header = new HBoxContainer();
		header.AddThemeConstantOverride("separation", 10);
		root.AddChild(header);

		var titleBox = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		titleBox.AddThemeConstantOverride("separation", 1);
		header.AddChild(titleBox);
		var eyebrow = CreateUiLabel("ERIS // MEMORY", 9, MemoryAside);
		titleBox.AddChild(eyebrow);
		var title = CreateUiLabel("Những chuyện tôi vẫn chưa quên", 25, MemoryInk);
		titleBox.AddChild(title);
		var subtitle = CreateUiLabel("…đừng có nhìn tôi kiểu đó. Tôi chỉ nhớ hơi nhiều thôi.", 10, MemoryInkSoft);
		titleBox.AddChild(subtitle);

		_memoryModeButton = CreateMemoryButton("Quản lý", () => SetMemoryManagerMode(!_memoryManagerVisible), primary: false);
		_memoryModeButton.CustomMinimumSize = new Vector2(86f, 34f);
		header.AddChild(_memoryModeButton);
		var refresh = CreateMemoryButton("Viết lại", () => SendMemoryPanelRequest(
			"snapshot", new Dictionary<string, object> { ["refresh_portrait"] = true }), primary: true);
		refresh.CustomMinimumSize = new Vector2(82f, 34f);
		header.AddChild(refresh);
		var controls = CreateWindowControlCapsule(() => _memoryPanel.Visible = false, CloseMemoryPanel);
		header.AddChild(controls);

		// ------------------------------------------------------------------
		// Character-facing portrait. Hai cột cố ý không cân nhau hoàn toàn:
		// bên trái là "ERIS nhìn bạn thế nào", bên phải là ký ức chung và
		// những điều ERIS còn ngập ngừng. Cảm giác gần visual-novel/diary hơn
		// một danh sách record nối đuôi nhau.
		// ------------------------------------------------------------------
		_memoryPortraitRoot = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		_memoryPortraitRoot.AddThemeConstantOverride("separation", 10);
		root.AddChild(_memoryPortraitRoot);

		var columns = new HBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		columns.AddThemeConstantOverride("separation", 14);
		_memoryPortraitRoot.AddChild(columns);

		var leftColumn = new VBoxContainer
		{
			CustomMinimumSize = new Vector2(408f, 0f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		leftColumn.AddThemeConstantOverride("separation", 10);
		columns.AddChild(leftColumn);

		var heroEyebrow = CreateUiLabel("●  HÔM NAY TÔI NGHĨ VỀ BẠN THẾ NÀY", 10, MemoryAside);
		leftColumn.AddChild(heroEyebrow);
		var hero = CreateMemoryPortraitSurface(new Color(1f, 0.992f, 0.996f, 0.92f), new Color(0.77f, 0.30f, 0.52f, 0.70f));
		hero.CustomMinimumSize = new Vector2(0f, 170f);
		leftColumn.AddChild(hero);
		var heroMargin = new MarginContainer();
		heroMargin.AddThemeConstantOverride("margin_left", 20);
		heroMargin.AddThemeConstantOverride("margin_right", 20);
		heroMargin.AddThemeConstantOverride("margin_top", 16);
		heroMargin.AddThemeConstantOverride("margin_bottom", 16);
		hero.AddChild(heroMargin);
		var heroBox = new VBoxContainer();
		heroBox.AddThemeConstantOverride("separation", 8);
		heroMargin.AddChild(heroBox);
		_memorySummaryLabel = CreateUiLabel(_memorySummaryText, 17, MemoryInk);
		_memorySummaryLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_memorySummaryLabel.MaxLinesVisible = 7;
		_memorySummaryLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		heroBox.AddChild(_memorySummaryLabel);

		var leftScroll = new ScrollContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
		};
		leftColumn.AddChild(leftScroll);
		_memoryPortraitLeftList = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_memoryPortraitLeftList.AddThemeConstantOverride("separation", 8);
		leftScroll.AddChild(_memoryPortraitLeftList);

		var rightColumn = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		rightColumn.AddThemeConstantOverride("separation", 10);
		columns.AddChild(rightColumn);

		var rightScroll = new ScrollContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
		};
		rightColumn.AddChild(rightScroll);
		_memoryPortraitRightList = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_memoryPortraitRightList.AddThemeConstantOverride("separation", 8);
		rightScroll.AddChild(_memoryPortraitRightList);

		// Lời chen này dùng output Surface, chỉ là cách ERIS kể lại state hiện tại.
		// Nó không bao giờ được ghi ngược thành canonical memory.
		var asideSurface = CreateMemoryPortraitSurface(new Color(0.985f, 0.955f, 0.970f, 0.82f), new Color(0.84f, 0.53f, 0.66f, 0.40f));
		asideSurface.CustomMinimumSize = new Vector2(0f, 64f);
		rightColumn.AddChild(asideSurface);
		var asideMargin = new MarginContainer();
		asideMargin.AddThemeConstantOverride("margin_left", 16);
		asideMargin.AddThemeConstantOverride("margin_right", 16);
		asideMargin.AddThemeConstantOverride("margin_top", 10);
		asideMargin.AddThemeConstantOverride("margin_bottom", 10);
		asideSurface.AddChild(asideMargin);
		var asideRow = new HBoxContainer();
		asideRow.AddThemeConstantOverride("separation", 8);
		asideMargin.AddChild(asideRow);
		asideRow.AddChild(CreateUiLabel("✦", 14, MemoryPink));
		_memoryPortraitAsideLabel = CreateUiLabel("", 11, MemoryAside);
		_memoryPortraitAsideLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_memoryPortraitAsideLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		asideRow.AddChild(_memoryPortraitAsideLabel);

		// ------------------------------------------------------------------
		// Inspector: user vẫn có quyền audit/sửa/quên canonical memory, nhưng đây
		// là một mode quản lý riêng thay vì bắt technical metadata đóng vai content.
		// ------------------------------------------------------------------
		_memoryManagerRoot = new VBoxContainer
		{
			Visible = false,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		_memoryManagerRoot.AddThemeConstantOverride("separation", 10);
		root.AddChild(_memoryManagerRoot);

		var managerHeader = new HBoxContainer();
		managerHeader.AddThemeConstantOverride("separation", 12);
		_memoryManagerRoot.AddChild(managerHeader);
		var managerTitle = CreateUiLabel("Quản lý trí nhớ", 16, MemoryInk);
		managerTitle.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		managerHeader.AddChild(managerTitle);
		_memoryStatusLabel = CreateUiLabel("Sẵn sàng.", 10, MemoryInkSoft);
		_memoryStatusLabel.VerticalAlignment = VerticalAlignment.Center;
		managerHeader.AddChild(_memoryStatusLabel);
		_memoryCountLabel = CreateUiLabel("Chưa có thống kê", 10, MemoryInkSoft);
		_memoryCountLabel.VerticalAlignment = VerticalAlignment.Center;
		managerHeader.AddChild(_memoryCountLabel);

		var curatorCard = CreateMemoryCard(new Color(0.985f, 0.972f, 0.982f, 0.96f), 13);
		_memoryManagerRoot.AddChild(curatorCard);
		var curatorMargin = new MarginContainer();
		curatorMargin.AddThemeConstantOverride("margin_left", 14);
		curatorMargin.AddThemeConstantOverride("margin_right", 14);
		curatorMargin.AddThemeConstantOverride("margin_top", 8);
		curatorMargin.AddThemeConstantOverride("margin_bottom", 8);
		curatorCard.AddChild(curatorMargin);
		var curatorRow = new HBoxContainer();
		curatorRow.AddThemeConstantOverride("separation", 10);
		curatorMargin.AddChild(curatorRow);
		var curatorTitle = CreateUiLabel("Dọn trí nhớ", 12, MemoryInk);
		curatorTitle.CustomMinimumSize = new Vector2(112f, 34f);
		curatorTitle.VerticalAlignment = VerticalAlignment.Center;
		curatorRow.AddChild(curatorTitle);
		_memoryAutoCleanupToggle = new CheckButton { Text = "Tự động", ButtonPressed = false };
		_memoryAutoCleanupToggle.AddThemeFontSizeOverride("font_size", 11);
		_memoryAutoCleanupToggle.AddThemeColorOverride("font_color", MemoryInkSoft);
		_memoryAutoCleanupToggle.Toggled += enabled =>
		{
			if (_memoryApplyingCleanupSnapshot) return;
			SendMemoryPanelRequest("set_auto_cleanup", new Dictionary<string, object> { ["enabled"] = enabled });
		};
		curatorRow.AddChild(_memoryAutoCleanupToggle);
		_memoryCleanupNowButton = CreateMemoryButton("Dọn ngay", StartMemoryCleanup, primary: false);
		_memoryCleanupNowButton.CustomMinimumSize = new Vector2(96f, 34f);
		curatorRow.AddChild(_memoryCleanupNowButton);
		_memoryCleanupLabel = CreateUiLabel("Chưa chạy cleanup.", 10, MemoryInkSoft);
		_memoryCleanupLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_memoryCleanupLabel.VerticalAlignment = VerticalAlignment.Center;
		_memoryCleanupLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		curatorRow.AddChild(_memoryCleanupLabel);

		var filters = new HBoxContainer();
		filters.AddThemeConstantOverride("separation", 10);
		_memoryManagerRoot.AddChild(filters);
		_memoryCategorySelect = new OptionButton { CustomMinimumSize = new Vector2(170f, 38f) };
		foreach (string label in new[] { "Tất cả", "Về bạn", "Sở thích", "Dự án & mục tiêu", "Cách làm việc", "Chưa chắc" })
			_memoryCategorySelect.AddItem(label);
		_memoryCategorySelect.ItemSelected += _ => RefreshMemoryPanelList();
		StyleMemoryInput(_memoryCategorySelect);
		filters.AddChild(_memoryCategorySelect);

		_memorySearchInput = new LineEdit
		{
			PlaceholderText = "Tìm trong trí nhớ thật…",
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(260f, 38f),
		};
		_memorySearchInput.TextChanged += _ => RefreshMemoryPanelList();
		StyleMemoryInput(_memorySearchInput);
		filters.AddChild(_memorySearchInput);

		_memoryIncludeInferredToggle = new CheckButton { Text = "Hiện phần chưa chắc", ButtonPressed = true };
		_memoryIncludeInferredToggle.AddThemeFontSizeOverride("font_size", 11);
		_memoryIncludeInferredToggle.AddThemeColorOverride("font_color", MemoryInkSoft);
		_memoryIncludeInferredToggle.Toggled += enabled =>
		{
			RefreshMemoryPanelList();
			SendMemoryPanelRequest("snapshot", new Dictionary<string, object> { ["include_inferred"] = enabled });
		};
		filters.AddChild(_memoryIncludeInferredToggle);

		var body = new HBoxContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill };
		body.AddThemeConstantOverride("separation", 12);
		_memoryManagerRoot.AddChild(body);

		var listCard = CreateMemoryCard(MemoryCard, 16);
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
		_memoryItemList.AddThemeConstantOverride("separation", 7);
		scroll.AddChild(_memoryItemList);

		var detailCard = CreateMemoryCard(new Color(0.992f, 0.972f, 0.982f, 0.96f), 16);
		detailCard.CustomMinimumSize = new Vector2(360f, 0f);
		detailCard.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		body.AddChild(detailCard);
		BuildMemoryDetailPane(detailCard);

		SetMemoryManagerMode(false);
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
				// Không tạo thêm bản sao memory tại Godot; đọc từ Brain đã lưu.
			}
			SetMemoryStatus(status == "ok" && _memoryPortraitPolling
				? "Gemini đang viết lại ký ức ở nền; bản mới sẽ tự xuất hiện."
				: string.IsNullOrWhiteSpace(message) ? "Đã cập nhật." : message, status == "error");
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
		_memoryPortraitSections.Clear();
		_memoryPortraitAside = "";
		_memorySummaryText = ReadJsonString(panel, "summary_text");
		ReadMemoryPortrait(panel);
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
		if (panel.TryGetProperty("cleanup_report", out JsonElement cleanupReport) && cleanupReport.ValueKind == JsonValueKind.Object
			&& _memoryCleanupLabel != null)
			_memoryCleanupLabel.Text = FormatCleanupReport(cleanupReport);

		if (panel.TryGetProperty("explanation", out JsonElement explanation))
			_memoryExplanationLabel.Text = FormatMemoryExplanation(explanation);
		RefreshMemoryPanel();
	}

	private void ReadMemoryPortrait(JsonElement panel)
	{
		if (!panel.TryGetProperty("portrait", out JsonElement portrait) || portrait.ValueKind != JsonValueKind.Object)
			return;

		// Không đợi Gemini trong UI: chỉ poll khi writer báo đang chạy.
		_memoryPortraitPolling = ReadJsonString(portrait, "generation_status") == "writing";
		if (_memoryPortraitPolling)
			_memoryPortraitPollAtMs = Time.GetTicksMsec() + 2500UL;
		string opening = ReadJsonString(portrait, "opening");
		if (!string.IsNullOrWhiteSpace(opening))
			_memorySummaryText = opening;
		_memoryPortraitAside = ReadJsonString(portrait, "aside");

		if (!portrait.TryGetProperty("sections", out JsonElement sections) || sections.ValueKind != JsonValueKind.Array)
			return;
		foreach (JsonElement rawSection in sections.EnumerateArray())
		{
			if (rawSection.ValueKind != JsonValueKind.Object)
				continue;
			var section = new MemoryPortraitSection
			{
				Kind = ReadJsonString(rawSection, "kind"),
				Title = ReadJsonString(rawSection, "title"),
			};
			if (rawSection.TryGetProperty("items", out JsonElement items) && items.ValueKind == JsonValueKind.Array)
			{
				foreach (JsonElement rawItem in items.EnumerateArray())
				{
					if (rawItem.ValueKind != JsonValueKind.Object)
						continue;
					string body = ReadJsonString(rawItem, "body");
					if (string.IsNullOrWhiteSpace(body))
						continue;
					section.Items.Add(new MemoryPortraitItem
					{
						Title = ReadJsonString(rawItem, "title"),
						Body = body,
						Aside = ReadJsonString(rawItem, "aside"),
					});
				}
			}
			if (section.Items.Count > 0)
				_memoryPortraitSections.Add(section);
		}
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
		if (_memoryPortraitAsideLabel != null)
			_memoryPortraitAsideLabel.Text = _memoryPortraitAside;
		RefreshMemoryPortrait();
		RefreshMemoryPanelList();
		if (_selectedMemoryRecord != null)
		{
			MemoryPanelRecord current = _memoryRecords.FirstOrDefault(x => x.Path == _selectedMemoryRecord.Path && x.ScopeKey == _selectedMemoryRecord.ScopeKey);
			SelectMemoryRecord(current);
		}
	}

	private void SetMemoryManagerMode(bool managerVisible)
	{
		_memoryManagerVisible = managerVisible;
		if (_memoryPortraitRoot != null)
			_memoryPortraitRoot.Visible = !managerVisible;
		if (_memoryManagerRoot != null)
			_memoryManagerRoot.Visible = managerVisible;
		if (_memoryModeButton != null)
			_memoryModeButton.Text = managerVisible ? "Quay lại" : "Quản lý";
	}

	private void RefreshMemoryPortrait()
	{
		if (_memoryPortraitLeftList == null || _memoryPortraitRightList == null)
			return;

		ClearMemoryPortraitColumn(_memoryPortraitLeftList);
		ClearMemoryPortraitColumn(_memoryPortraitRightList);

		if (_memoryPortraitSections.Count == 0)
		{
			_memoryPortraitLeftList.AddChild(CreateMemoryPortraitEmptyState());
			return;
		}

		foreach (MemoryPortraitSection section in _memoryPortraitSections)
		{
			// Ký ức chung + phần ERIS chưa chắc nằm bên phải để tạo nhịp như
			// diary/VN. Những gì ERIS hiểu về user và sở thích nằm bên trái.
			VBoxContainer target = section.Kind is "our_memories" or "not_sure"
				? _memoryPortraitRightList
				: _memoryPortraitLeftList;
			AddMemoryPortraitSection(target, section);
		}
	}

	private static void ClearMemoryPortraitColumn(VBoxContainer column)
	{
		foreach (Node child in column.GetChildren())
		{
			column.RemoveChild(child);
			child.QueueFree();
		}
	}

	private void AddMemoryPortraitSection(VBoxContainer target, MemoryPortraitSection section)
	{
		string sectionTitle = string.IsNullOrWhiteSpace(section.Title)
			? PortraitSectionTitle(section.Kind)
			: section.Title;
		var title = CreateUiLabel($"●  {sectionTitle.ToUpperInvariant()}", 10, MemoryAside);
		title.CustomMinimumSize = new Vector2(0f, 26f);
		title.VerticalAlignment = VerticalAlignment.Center;
		target.AddChild(title);

		foreach (MemoryPortraitItem item in section.Items)
			target.AddChild(CreateMemoryPortraitCard(section.Kind, item));
	}

	private Control CreateMemoryPortraitEmptyState()
	{
		var surface = CreateMemoryPortraitSurface(new Color(1f, 0.992f, 0.996f, 0.78f), MemoryBorder);
		surface.CustomMinimumSize = new Vector2(0f, 150f);
		var margin = new MarginContainer();
		margin.AddThemeConstantOverride("margin_left", 24);
		margin.AddThemeConstantOverride("margin_right", 24);
		margin.AddThemeConstantOverride("margin_top", 34);
		margin.AddThemeConstantOverride("margin_bottom", 34);
		surface.AddChild(margin);
		var box = new VBoxContainer { Alignment = BoxContainer.AlignmentMode.Center };
		box.AddThemeConstantOverride("separation", 8);
		margin.AddChild(box);
		var title = CreateUiLabel("Chưa có chuyện nào đủ rõ để tôi kể", 16, MemoryInk);
		title.HorizontalAlignment = HorizontalAlignment.Center;
		box.AddChild(title);
		var text = CreateUiLabel("Cứ nói chuyện bình thường thôi. Những thứ lặp lại và thật sự có ý nghĩa sẽ tự ở lại.", 11, MemoryInkSoft);
		text.HorizontalAlignment = HorizontalAlignment.Center;
		text.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		box.AddChild(text);
		return surface;
	}

	private Control CreateMemoryPortraitCard(string kind, MemoryPortraitItem item)
	{
		Color accent = kind switch
		{
			"things_you_like" => new Color(0.68f, 0.47f, 0.66f, 0.78f),
			"our_memories" => new Color(0.45f, 0.55f, 0.70f, 0.74f),
			"not_sure" => new Color(0.73f, 0.54f, 0.35f, 0.74f),
			_ => new Color(0.77f, 0.30f, 0.52f, 0.72f),
		};
		Color background = kind == "not_sure"
			? new Color(1f, 0.982f, 0.965f, 0.90f)
			: new Color(1f, 0.997f, 0.999f, 0.90f);
		var surface = CreateMemoryPortraitSurface(background, accent);
		if (kind == "our_memories")
			surface.CustomMinimumSize = new Vector2(0f, 126f);
		var margin = new MarginContainer();
		margin.AddThemeConstantOverride("margin_left", 18);
		margin.AddThemeConstantOverride("margin_right", 18);
		margin.AddThemeConstantOverride("margin_top", 12);
		margin.AddThemeConstantOverride("margin_bottom", 12);
		surface.AddChild(margin);
		var box = new VBoxContainer();
		box.AddThemeConstantOverride("separation", 5);
		margin.AddChild(box);

		var title = CreateUiLabel(item.Title, kind == "our_memories" ? 15 : 13, MemoryInk);
		title.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		box.AddChild(title);
		var body = CreateUiLabel(item.Body, kind == "our_memories" ? 13 : 12, new Color(0.31f, 0.18f, 0.24f));
		body.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		box.AddChild(body);
		if (!string.IsNullOrWhiteSpace(item.Aside))
		{
			var aside = CreateUiLabel(item.Aside, 11, MemoryAside);
			aside.AutowrapMode = TextServer.AutowrapMode.WordSmart;
			box.AddChild(aside);
		}
		return surface;
	}

	private static string PortraitSectionTitle(string kind) => kind switch
	{
		"things_you_like" => "Mấy thứ bạn thích",
		"our_memories" => "Chuyện của hai đứa",
		"not_sure" => "Có vài chuyện tôi chưa dám chắc",
		_ => "Trong mắt tôi",
	};

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
		if (_memoryCleanupLabel != null) _memoryCleanupLabel.Text = "Đang rà và dọn trí nhớ…";
		SendMemoryPanelRequest("cleanup_now");
	}

	private static string FormatCleanupStatus(JsonElement cleanup)
	{
		if (!ReadJsonBool(cleanup, "available")) return "Curator chưa sẵn sàng.";
		if (ReadJsonBool(cleanup, "running")) return "Đang rà và gộp trí nhớ…";
		string prefix = ReadJsonBool(cleanup, "auto_cleanup") ? "Tự dọn đang bật" : "Tự dọn đang tắt";
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
		return $"Đã rà {reviewed} mục · áp dụng {changed} thay đổi";
	}

	private void TickMemoryPanelStatus()
	{
		ulong now = Time.GetTicksMsec();
		if (_memoryPanel != null && _memoryPanel.Visible && !_memoryRequestPending
			&& _memoryPortraitPolling && now >= _memoryPortraitPollAtMs)
		{
			_memoryPortraitPollAtMs = now + 2500UL;
			SendMemoryPanelRequest("snapshot");
			return;
		}
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

	private static PanelContainer CreateMemoryPortraitSurface(Color background, Color accent)
	{
		var surface = new PanelContainer();
		surface.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = background,
			BorderColor = accent,
			BorderWidthLeft = 3,
			BorderWidthTop = 0,
			BorderWidthRight = 0,
			BorderWidthBottom = 0,
			CornerRadiusTopLeft = 13,
			CornerRadiusTopRight = 13,
			CornerRadiusBottomLeft = 13,
			CornerRadiusBottomRight = 13,
			ShadowColor = new Color(0.25f, 0.08f, 0.16f, 0.05f),
			ShadowSize = 3,
		});
		return surface;
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

}
