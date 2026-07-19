using Godot;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	// Panel cũ "Chiều sâu" từng phụ thuộc Ni/Fe/ToM legacy. Từ Architecture C v5,
	// nó trở thành bảng Identity & Life Runtime, đọc đúng một contract
	// identity_runtime. Tên method/field cũ được giữ để không làm vỡ UdpListener.
	private static readonly Vector2 DepthPanelMinSize = new(1400f, 820f);
	private const float DepthPanelMargin = 8f;

	private Panel _depthPanel;
	private Button _contextDepthButton;
	private VBoxContainer _depthContentList;
	private Label _depthTitleLabel;
	private Label _depthStatusLabel;
	private Label _depthLearningChip;
	private Label _depthTurnChip;
	private Button _depthFreezeButton;
	private bool _depthResetScrollOnRefresh = true;
	private ScrollContainer _depthScrollContainer;
	private Control _depthScrollDecorationLayer;
	private TextureRect _depthScrollTrackRect;
	private TextureRect _depthScrollFillRect;
	private TextureRect _depthScrollCapRect;
	private Texture2D _depthScrollTrackTexture;
	private Texture2D _depthScrollFillTexture;
	private Texture2D _depthScrollCapTexture;
	private readonly List<Button> _depthTabButtons = new();
	private string _depthActiveTab = "overview";
	private bool _depthLearningEnabled = true;

	private static readonly Color IdentityInk = new(0.20f, 0.16f, 0.25f, 1f);
	private static readonly Color IdentityMuted = new(0.44f, 0.39f, 0.49f, 1f);
	private static readonly Color IdentityAccent = new(0.76f, 0.30f, 0.56f, 1f);
	private static readonly Color IdentityAccentSoft = new(0.97f, 0.87f, 0.92f, 1f);
	private static readonly Color IdentityCard = new(1f, 0.985f, 0.992f, 0.98f);
	private static readonly Color IdentityBorder = new(0.91f, 0.72f, 0.82f, 1f);
	private static readonly Color IdentityPink = new(0.94f, 0.25f, 0.52f, 1f);
	private static readonly Color IdentityPurple = new(0.58f, 0.31f, 0.84f, 1f);
	private static readonly Color IdentityBlue = new(0.35f, 0.48f, 0.88f, 1f);
	private static readonly Color IdentityOrange = new(0.96f, 0.55f, 0.18f, 1f);
	private static readonly Color IdentityGreen = new(0.20f, 0.65f, 0.45f, 1f);

	// Bộ asset mới dành riêng cho Identity Runtime. Tất cả ảnh đều là PNG nền trong suốt.
	// Panel vẫn chạy bằng fallback glyph nếu người dùng chưa thả đủ asset.
	private const string IdentityAssetRoot = "res://asset/";

	private static string IdentityAsset(string fileName) => IdentityAssetRoot + fileName;

	private sealed class IdentityLiveEvent
	{
		public string Title = "";
		public string Detail = "";
		public string Tag = "observing";
		public string IconPath = "";
		public string FallbackGlyph = "·";
		public Color Accent = IdentityAccent;
	}

	private void OnContextDepthPressed()
	{
		_bodyAutonomy?.RecordUserInteraction();
		ToggleDepthPanel();
	}

	private void ToggleDepthPanel()
	{
		if (_depthPanel == null)
			return;
		if (_depthPanel.Visible)
			_depthPanel.Visible = false;
		else
			ShowDepthPanel();
	}

	private void ShowDepthPanel()
	{
		if (_depthPanel == null)
			return;
		CloseCharacterContextMenu();
		_depthPanel.Visible = true;
		Vector2 viewport = GetViewportRect().Size;
		float width = Mathf.Min(DepthPanelMinSize.X, Mathf.Max(640f, viewport.X - DepthPanelMargin * 2f));
		float height = Mathf.Min(DepthPanelMinSize.Y, Mathf.Max(500f, viewport.Y - DepthPanelMargin * 2f));
		_depthPanel.Size = new Vector2(width, height);
		_depthPanel.Position = new Vector2(
			Mathf.Max(0f, (viewport.X - width) * 0.5f),
			Mathf.Max(0f, (viewport.Y - height) * 0.5f));
		_depthResetScrollOnRefresh = true;
		RefreshDepthPanel();
		Callable.From(UpdateDepthScrollDecor).CallDeferred();
	}

	private void BuildDepthPanelUi()
	{
		if (_depthPanel == null)
			return;
		if (string.IsNullOrWhiteSpace(_latestDepthV2Json))
			LoadDepthV2State();

		foreach (Node child in _depthPanel.GetChildren())
			child.QueueFree();

		_depthPanel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.978f, 0.988f, 0.995f),
			BorderColor = new Color(0.95f, 0.73f, 0.84f, 1f),
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 28,
			CornerRadiusTopRight = 28,
			CornerRadiusBottomLeft = 28,
			CornerRadiusBottomRight = 28,
			ShadowColor = new Color(0.30f, 0.10f, 0.22f, 0.18f),
			ShadowSize = 16,
		});
		_depthPanel.ClipContents = true;

		var root = new VBoxContainer
		{
			Name = "IdentityRuntimeRoot",
			OffsetLeft = 18f,
			OffsetTop = 14f,
			OffsetRight = -18f,
			OffsetBottom = -14f,
		};
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.AddThemeConstantOverride("separation", 7);
		_depthPanel.AddChild(root);

		var header = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 62f) };
		header.AddThemeConstantOverride("separation", 10);
		root.AddChild(header);

		header.AddChild(NewIconBadge(IdentityAsset("identity_brand.png"), "♥", new Vector2(68f, 54f), IdentityPink, false));

		var titleBlock = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		titleBlock.AddThemeConstantOverride("separation", -1);
		_depthTitleLabel = NewLabel("IDENTITY & LIFE RUNTIME", 22, new Color(0.86f, 0.15f, 0.44f), true);
		_depthTitleLabel.ClipText = true;
		_depthStatusLabel = NewLabel("v5.3.0  •  ai_orchestrated", 10, IdentityMuted, false);
		_depthStatusLabel.ClipText = true;
		titleBlock.AddChild(_depthTitleLabel);
		titleBlock.AddChild(_depthStatusLabel);
		header.AddChild(titleBlock);

		_depthLearningChip = NewChip("LEARNING ?", new Color(0.93f, 0.99f, 0.96f), IdentityGreen);
		_depthLearningChip.CustomMinimumSize = new Vector2(180f, 36f);
		_depthLearningChip.SizeFlagsHorizontal = Control.SizeFlags.ShrinkEnd;
		_depthTurnChip = NewChip("TURN 0 · STATE 0", new Color(0.95f, 0.97f, 1f), IdentityBlue);
		_depthTurnChip.CustomMinimumSize = new Vector2(180f, 36f);
		_depthTurnChip.SizeFlagsHorizontal = Control.SizeFlags.ShrinkEnd;
		header.AddChild(_depthLearningChip);
		header.AddChild(_depthTurnChip);

		// Dùng chung cụm điều khiển cửa sổ với panel Cảm xúc để giữ hình dáng và hành vi nhất quán.
		var windowControls = CreateWindowControlCapsule(
			() => _depthPanel.Visible = false,
			() => _depthPanel.Visible = false);
		header.AddChild(windowControls);

		var tabs = new HBoxContainer
		{
			CustomMinimumSize = new Vector2(0f, 48f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		tabs.AddThemeConstantOverride("separation", 6);
		root.AddChild(tabs);
		_depthTabButtons.Clear();
		AddDepthTab(tabs, "overview", "Tổng quan", IdentityAsset("identity_tab_overview.png"), "▦");
		AddDepthTab(tabs, "identity", "Giá trị & động cơ", IdentityAsset("identity_tab_values.png"), "♡");
		AddDepthTab(tabs, "relationship", "Quan hệ & belief", IdentityAsset("identity_tab_relationship.png"), "♧");
		AddDepthTab(tabs, "discovery", "Discovery & chủ động", IdentityAsset("identity_tab_discovery.png"), "✧");
		AddDepthTab(tabs, "audit", "Ledger & imprint", IdentityAsset("identity_tab_ledger.png"), "▤");

		var scroll = new ScrollContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
			VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
			ClipContents = true,
		};
		scroll.AddThemeConstantOverride("v_scrollbar_separation", 0);
		root.AddChild(scroll);
		_depthScrollContainer = scroll;

		// Mượn đúng cấu trúc cuộn của Inner Diary: chừa một rail riêng bên phải,
		// ẩn scrollbar Godot và vẽ topcap/track/fill bằng asset đã có.
		var scrollPad = new MarginContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkBegin,
		};
		scrollPad.AddThemeConstantOverride("margin_right", 30);
		scrollPad.AddThemeConstantOverride("margin_top", 4);
		scrollPad.AddThemeConstantOverride("margin_bottom", 8);
		scroll.AddChild(scrollPad);

		_depthContentList = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 0f),
			SizeFlagsVertical = Control.SizeFlags.ShrinkBegin,
		};
		_depthContentList.AddThemeConstantOverride("separation", 12);
		scrollPad.AddChild(_depthContentList);

		ApplyHiddenScrollBarTheme(scroll.GetVScrollBar());
		scroll.GetVScrollBar().ValueChanged += _ => UpdateDepthScrollDecor();
		scroll.Resized += UpdateDepthScrollDecor;

		// Action dock tách thao tác bảo trì khỏi nội dung sống, có khối nền và độ nổi riêng.
		var actionDock = new PanelContainer
		{
			CustomMinimumSize = new Vector2(0f, 58f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		actionDock.AddThemeStyleboxOverride("panel", IdentityActionDockStyle());
		root.AddChild(actionDock);

		var actionPad = new MarginContainer();
		actionPad.AddThemeConstantOverride("margin_left", 8);
		actionPad.AddThemeConstantOverride("margin_top", 6);
		actionPad.AddThemeConstantOverride("margin_right", 8);
		actionPad.AddThemeConstantOverride("margin_bottom", 6);
		actionDock.AddChild(actionPad);

		var controls = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 46f) };
		controls.AddThemeConstantOverride("separation", 10);
		actionPad.AddChild(controls);
		_depthFreezeButton = NewFooterButton("Đóng băng học", IdentityAsset("identity_action_freeze.png"), "❄", ToggleIdentityLearning, IdentityBlue);
		controls.AddChild(WrapHBoxControl(_depthFreezeButton, 46f));
		controls.AddChild(WrapHBoxControl(NewFooterButton("Xuất snapshot", IdentityAsset("identity_action_export.png"), "⇩", () => SendDebugCommand("identity snapshot"), new Color(0.42f, 0.48f, 0.88f, 1f)), 46f));
		controls.AddChild(WrapHBoxControl(NewFooterButton("Reset mood", IdentityAsset("identity_action_reset_mood.png"), "☺", () => SendDebugCommand("identity reset mood"), IdentityPink), 46f));
		controls.AddChild(WrapHBoxControl(NewFooterButton("Reset quan hệ", IdentityAsset("identity_action_reset_relationship.png"), "♧", () => SendDebugCommand("identity reset relationship"), IdentityAccent), 46f));
		controls.AddChild(WrapHBoxControl(NewFooterButton("Reset discovery", IdentityAsset("identity_action_reset_discovery.png"), "✦", () => SendDebugCommand("identity reset discovery"), IdentityOrange), 46f));

		BuildDepthScrollDecoration();
		RefreshDepthTabStyle();
		RefreshDepthPanel();
	}


	private void BuildDepthScrollDecoration()
	{
		_depthScrollCapTexture ??= LoadResourceTexture("res://asset/Resource/topcap.png");
		_depthScrollTrackTexture ??= LoadResourceTexture("res://asset/Resource/scrolltrack.png");
		_depthScrollFillTexture ??= LoadResourceTexture("res://asset/Resource/scrollfill.png");

		_depthScrollDecorationLayer = new Control
		{
			Name = "IdentityScrollDecoration",
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		_depthScrollDecorationLayer.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_depthPanel.AddChild(_depthScrollDecorationLayer);

		_depthScrollTrackRect = CreateDecorTextureRect(_depthScrollTrackTexture, new Vector2(14f, 220f));
		_depthScrollFillRect = CreateDecorTextureRect(_depthScrollFillTexture, new Vector2(14f, 72f));
		_depthScrollCapRect = CreateDecorTextureRect(_depthScrollCapTexture, new Vector2(28f, 28f));
		_depthScrollDecorationLayer.AddChild(_depthScrollTrackRect);
		_depthScrollDecorationLayer.AddChild(_depthScrollFillRect);
		_depthScrollDecorationLayer.AddChild(_depthScrollCapRect);

		Callable.From(UpdateDepthScrollDecor).CallDeferred();
	}

	private void UpdateDepthScrollDecor()
	{
		if (_depthScrollContainer == null || _depthPanel == null)
			return;

		VScrollBar scrollBar = _depthScrollContainer.GetVScrollBar();
		if (scrollBar == null)
			return;

		Vector2 panelOrigin = _depthPanel.GlobalPosition;
		Vector2 scPos = _depthScrollContainer.GlobalPosition - panelOrigin;
		Vector2 scSize = _depthScrollContainer.Size;

		float railWidth = 12f;
		float trackX = scPos.X + scSize.X - railWidth - 8f;
		float trackTop = scPos.Y + 5f;
		float trackHeight = Mathf.Max(52f, scSize.Y - 10f);
		bool canScroll = scrollBar.MaxValue > scrollBar.Page + 0.5;

		if (_depthScrollTrackRect != null)
		{
			_depthScrollTrackRect.Position = new Vector2(trackX, trackTop);
			_depthScrollTrackRect.Size = new Vector2(railWidth, trackHeight);
			_depthScrollTrackRect.Visible = canScroll;
		}

		float thumbMinHeight = 56f;
		float thumbMaxHeight = Mathf.Min(trackHeight, 160f);
		float thumbHeight = thumbMinHeight;
		double maxVal = scrollBar.MaxValue;
		if (maxVal > 0.001 && scrollBar.Page > 0)
		{
			float pageRatio = Mathf.Clamp((float)(scrollBar.Page / maxVal), 0.12f, 1f);
			thumbHeight = Mathf.Clamp(trackHeight * pageRatio, thumbMinHeight, thumbMaxHeight);
		}

		float scrollRange = Mathf.Max(0f, (float)(scrollBar.MaxValue - scrollBar.Page));
		float scrollRatio = scrollRange > 0.001f
			? Mathf.Clamp((float)(scrollBar.Value / scrollRange), 0f, 1f)
			: 0f;
		float thumbY = trackTop + scrollRatio * Mathf.Max(0f, trackHeight - thumbHeight);

		if (_depthScrollFillRect != null)
		{
			_depthScrollFillRect.Position = new Vector2(trackX, thumbY);
			_depthScrollFillRect.Size = new Vector2(railWidth, thumbHeight);
			_depthScrollFillRect.Visible = canScroll;
		}

		if (_depthScrollCapRect != null)
		{
			float capWidth = railWidth + 14f;
			float capHeight = capWidth;
			if (_depthScrollCapTexture != null)
			{
				Vector2 texSize = _depthScrollCapTexture.GetSize();
				if (texSize.X > 0f && texSize.Y > 0f)
					capHeight = capWidth * (texSize.Y / texSize.X);
			}
			_depthScrollCapRect.Position = new Vector2(
				trackX + (railWidth - capWidth) * 0.5f,
				thumbY - capHeight * 0.40f);
			_depthScrollCapRect.Size = new Vector2(capWidth, capHeight);
			_depthScrollCapRect.Visible = canScroll;
		}
	}


	private void AddDepthTab(HBoxContainer parent, string key, string label, string iconPath, string fallbackGlyph)
	{
		string resolvedIconPath = ResolveIdentityAssetPath(iconPath);
		bool hasIcon = ResourceLoader.Exists(resolvedIconPath);
		var button = NewButton(hasIcon ? label : $"{fallbackGlyph}  {label}", () =>
		{
			_depthActiveTab = key;
			_depthResetScrollOnRefresh = true;
			RefreshDepthTabStyle();
			RefreshDepthPanel();
		}, danger: false);
		button.SetMeta("identity_tab", key);
		button.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		button.SizeFlagsStretchRatio = 1f;
		button.CustomMinimumSize = new Vector2(0f, 46f);
		button.AddThemeFontSizeOverride("font_size", 12);
		button.ClipText = true;
		if (hasIcon)
		{
			button.Icon = GD.Load<Texture2D>(resolvedIconPath);
			button.ExpandIcon = true;
			button.AddThemeConstantOverride("icon_max_width", 26);
		}
		_depthTabButtons.Add(button);
		parent.AddChild(WrapHBoxControl(button, 46f));
	}

	private Control WrapHBoxControl(Control child, float height)
	{
		var slot = new Control
		{
			CustomMinimumSize = new Vector2(0f, height),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsStretchRatio = 1f,
			ClipContents = true,
		};
		child.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		child.OffsetLeft = 0f;
		child.OffsetTop = 0f;
		child.OffsetRight = 0f;
		child.OffsetBottom = 0f;
		child.CustomMinimumSize = new Vector2(0f, height);
		child.SizeFlagsHorizontal = Control.SizeFlags.Fill;
		slot.AddChild(child);
		return slot;
	}


	private void RefreshDepthTabStyle()
	{
		foreach (Button button in _depthTabButtons)
		{
			string key = button.HasMeta("identity_tab") ? button.GetMeta("identity_tab").AsString() : "";
			bool active = string.Equals(key, _depthActiveTab, StringComparison.Ordinal);
			button.AddThemeColorOverride("font_color", active ? Colors.White : new Color(0.40f, 0.21f, 0.34f));
			button.AddThemeColorOverride("font_hover_color", active ? Colors.White : new Color(0.35f, 0.16f, 0.31f));
			// PNG Identity đã có màu hoàn chỉnh. Không được dùng theme icon color để
			// nhuộm chúng thành một mảng hồng như icon monochrome.
			button.AddThemeColorOverride("icon_normal_color", Colors.White);
			button.AddThemeColorOverride("icon_hover_color", Colors.White);
			button.AddThemeColorOverride("icon_pressed_color", Colors.White);
			button.AddThemeColorOverride("icon_focus_color", Colors.White);
			button.AddThemeStyleboxOverride("normal", IdentityTabStyle(active, false));
			button.AddThemeStyleboxOverride("hover", IdentityTabStyle(active, true));
			button.AddThemeStyleboxOverride("pressed", IdentityTabPressedStyle());
			button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
		}
	}


	private void ToggleIdentityLearning()
	{
		SendDebugCommand(_depthLearningEnabled ? "identity freeze on" : "identity freeze off");
	}

	private void TryCaptureDepthV2Block(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;
			JsonElement block;
			if (root.ValueKind == JsonValueKind.Object
				&& root.TryGetProperty("identity_runtime", out block)
				&& block.ValueKind == JsonValueKind.Object)
			{
				_latestDepthV2Json = block.GetRawText();
			}
			else if (root.ValueKind == JsonValueKind.Object
				&& root.TryGetProperty("depth_v2", out block)
				&& block.ValueKind == JsonValueKind.Object)
			{
				_latestDepthV2Json = block.GetRawText();
			}
			else
			{
				return;
			}
			SaveDepthV2State();
			if (_depthPanel != null && _depthPanel.Visible)
				RefreshDepthPanel();
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[IdentityPanel] capture failed: {ex.Message}");
		}
	}

	private void SaveDepthV2State()
	{
		if (string.IsNullOrWhiteSpace(_latestDepthV2Json))
			return;
		try
		{
			using var file = Godot.FileAccess.Open(DepthV2StatePath, Godot.FileAccess.ModeFlags.Write);
			file?.StoreString(_latestDepthV2Json);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[IdentityPanel] save failed: {ex.Message}");
		}
	}

	private void LoadDepthV2State()
	{
		try
		{
			if (!Godot.FileAccess.FileExists(DepthV2StatePath))
				return;
			using var file = Godot.FileAccess.Open(DepthV2StatePath, Godot.FileAccess.ModeFlags.Read);
			if (file != null)
				_latestDepthV2Json = file.GetAsText();
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[IdentityPanel] load failed: {ex.Message}");
		}
	}

	private void RefreshDepthPanel()
	{
		if (_depthContentList == null)
			return;
		foreach (Node child in _depthContentList.GetChildren())
		{
			_depthContentList.RemoveChild(child);
			child.QueueFree();
		}

		if (string.IsNullOrWhiteSpace(_latestDepthV2Json))
		{
			AddInfoCard("Chưa có dữ liệu", new[]
			{
				"Panel đang chờ identity_runtime từ Python.",
				"Nếu Architecture C đã bật mà panel vẫn trắng, kiểm tra panel_state_update và UDP ack.",
			});
			Callable.From(UpdateDepthScrollDecor).CallDeferred();
			ResetDepthScrollIfNeeded();
			return;
		}

		try
		{
			using JsonDocument doc = JsonDocument.Parse(_latestDepthV2Json);
			JsonElement root = doc.RootElement;
			int turn = ReadInt(root, "turn_seq");
			int version = ReadInt(root, "state_version");
			_depthTurnChip.Text = $"TURN {turn} · STATE {version}";

			JsonElement learning = Obj(root, "learning");
			_depthLearningEnabled = ReadBool(learning, "enabled", true);
			_depthLearningChip.Text = _depthLearningEnabled ? "LEARNING NORMAL" : "OBSERVE ONLY";
			_depthLearningChip.AddThemeColorOverride("font_color", _depthLearningEnabled ? new Color(0.22f, 0.55f, 0.36f) : new Color(0.78f, 0.34f, 0.23f));
			if (_depthFreezeButton != null)
				_depthFreezeButton.Text = _depthLearningEnabled ? "Đóng băng học" : "Mở lại học";

			string architecture = ReadString(root, "architecture");
			_depthStatusLabel.Text = string.IsNullOrWhiteSpace(architecture)
				? "ai_orchestrated · compatibility snapshot"
				: architecture.Replace("ai_orchestrated.", "v");

			switch (_depthActiveTab)
			{
				case "identity": RenderIdentityTab(root); break;
				case "relationship": RenderRelationshipTab(root); break;
				case "discovery": RenderDiscoveryTab(root); break;
				case "audit": RenderAuditTab(root); break;
				default: RenderOverviewTab(root); break;
			}
			Callable.From(UpdateDepthScrollDecor).CallDeferred();
			ResetDepthScrollIfNeeded();
		}
		catch (Exception ex)
		{
			AddInfoCard("Không đọc được snapshot", new[] { ex.Message, "Raw state vẫn được giữ để gói sau có thể sửa lại." });
			ResetDepthScrollIfNeeded();
		}
	}

	private void RenderOverviewTab(JsonElement root)
	{
		if (_depthContentList == null)
			return;

		var body = new HBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			ClipContents = true,
			CustomMinimumSize = new Vector2(0f, 742f),
		};
		body.AddThemeConstantOverride("separation", 14);
		_depthContentList.AddChild(body);

		var left = new VBoxContainer { CustomMinimumSize = new Vector2(330f, 0f), SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin };
		left.AddThemeConstantOverride("separation", 10);
		body.AddChild(left);

		var right = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		right.AddThemeConstantOverride("separation", 12);
		body.AddChild(right);

		RenderOverviewMood(left, root);
		RenderSpeechDrive(left, root);
		RenderTopMotives(left, root);
		RenderDefenseAndConflict(left, root);

		RenderLiveTimeline(right, root);
		var bottom = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 258f) };
		bottom.AddThemeConstantOverride("separation", 12);
		right.AddChild(bottom);
		RenderStageExpression(bottom, root);
		RenderReadyDiscovery(bottom, root);
		RenderRelationshipPreview(bottom, root);
	}


	private void RenderOverviewMood(VBoxContainer parent, JsonElement root)
	{
		JsonElement summary = Obj(root, "summary");
		var card = NewIdentityCard("Tâm thế hiện tại", IdentityAsset("identity_card_mood.png"), "✧", IdentityPink, 160f);
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		var row = new HBoxContainer();
		row.AddThemeConstantOverride("separation", 12);
		box.AddChild(row);
		row.AddChild(NewMoodOrb(IdentityAsset("identity_mood_neutral.png"), BuildMoodSubtitle(summary, root)));
		var textBox = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		textBox.AddThemeConstantOverride("separation", 2);
		string mood = PrettyIdentityKey(ReadString(summary, "mood"));
		textBox.AddChild(NewLabel(string.IsNullOrWhiteSpace(mood) ? "Trung tính" : mood, 20, IdentityInk, true));
		textBox.AddChild(NewLabel(BuildMoodSubtitle(summary, root), 14, new Color(0.39f, 0.23f, 0.47f), false));
		textBox.AddChild(NewLabel("Bình ổn · Quan sát · Chọn lọc", 11, IdentityMuted, false));
		row.AddChild(textBox);
	}


	private void RenderSpeechDrive(VBoxContainer parent, JsonElement root)
	{
		JsonElement speech = Obj(root, "speech_drive");
		JsonElement initiative = Obj(root, "initiative");
		JsonElement decision = Obj(speech, "decision");
		if (decision.ValueKind != JsonValueKind.Object)
			decision = Obj(initiative, "last_decision");

		float want = ReadFirstFloat(speech, "want_to_speak", "expression_urge", "urge", "speech_drive");
		float content = ReadFirstFloat(speech, "content_readiness", "has_content", "content");
		float toward = ReadFirstFloat(speech, "user_directed_motivation", "toward_user", "user_motivation");
		float restraint = ReadFirstFloat(speech, "restraint", "self_restraint", "inhibition");
		JsonElement discovery = Obj(root, "discovery");
		if (content <= 0f && Arr(discovery, "ready_to_share").ValueKind == JsonValueKind.Array)
			content = Arr(discovery, "ready_to_share").GetArrayLength() > 0 ? 0.72f : 0f;
		if (want <= 0f)
			want = Mathf.Clamp(content * 0.52f + toward * 0.30f + ReadFloat(Obj(root, "expression"), "initiative_bias") * 0.18f, 0f, 1f);
		if (restraint <= 0f)
			restraint = ReadTopScore(Arr(root, "defenses_top"), "intellectualization", 0.34f);

		bool allowed = ReadBool(decision, "allowed", false);
		string reason = ReadString(decision, "reason");
		string status = allowed ? "Sẵn sàng nói" : (want >= 0.35f ? "Đang giữ lại" : "Đang yên");
		var card = NewIdentityCard("Xung lực chủ động", IdentityAsset("identity_card_speech_drive.png"), "ϟ", IdentityPink, 190f);
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		var stateRow = new HBoxContainer();
		stateRow.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		stateRow.AddChild(NewPill(status, allowed ? IdentityGreen : IdentityPink, false));
		box.AddChild(stateRow);
		AddMetricBar(box, "Muốn nói", want, IdentityPink);
		AddMetricBar(box, "Có nội dung", content, new Color(0.92f, 0.35f, 0.60f));
		AddMetricBar(box, "Hướng tới bạn", toward, new Color(0.86f, 0.37f, 0.68f));
		AddMetricBar(box, "Tự kìm", restraint, IdentityPurple);
		if (!string.IsNullOrWhiteSpace(reason))
			box.AddChild(NewLabel("Giữ lại vì " + PrettyIdentityKey(reason), 10, IdentityMuted, false));
	}


	private void RenderTopMotives(VBoxContainer parent, JsonElement root)
	{
		var card = NewIdentityCard("Motive chính", IdentityAsset("identity_card_motive.png"), "✦", IdentityAccent, 112f);
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		JsonElement motiveArray = Arr(root, "active_motives");
		if (motiveArray.ValueKind != JsonValueKind.Array || motiveArray.GetArrayLength() == 0)
			motiveArray = Arr(root, "motives_top");
		int rank = 1;
		if (motiveArray.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in motiveArray.EnumerateArray())
			{
				string key = ReadString(item, "key");
				float value = ReadFirstFloat(item, "strength", "value");
				AddRankRow(box, rank, PrettyIdentityKey(key), value, rank == 1 ? IdentityPink : IdentityPurple);
				if (++rank > 2) break;
			}
		}
		if (rank == 1) box.AddChild(NewLabel("Chưa có motive đủ rõ.", 11, IdentityMuted, false));
	}


	private void RenderDefenseAndConflict(VBoxContainer parent, JsonElement root)
	{
		JsonElement defenses = Arr(root, "active_defenses");
		string defenseKey = "";
		float defenseValue = 0f;
		if (defenses.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in defenses.EnumerateArray())
			{
				defenseKey = ReadString(item, "key");
				defenseValue = ReadFirstFloat(item, "strength", "value");
				break;
			}
		}
		var defense = NewIdentityCard("Defense", IdentityAsset("identity_card_defense.png"), "♢", IdentityPurple, 82f);
		parent.AddChild(defense);
		var defenseBox = (VBoxContainer)defense.GetChild(0);
		AddCompactValue(defenseBox, PrettyIdentityKey(defenseKey), defenseValue, IdentityPurple);

		JsonElement conflict = Obj(root, "active_conflict");
		var conflictCard = NewIdentityCard("Mâu thuẫn nội tại", IdentityAsset("identity_card_conflict.png"), "⚖", IdentityPink, 82f);
		parent.AddChild(conflictCard);
		var conflictBox = (VBoxContainer)conflictCard.GetChild(0);
		AddCompactValue(conflictBox, PrettyIdentityKey(ReadString(conflict, "conflict_id")), ReadFloat(conflict, "activation"), IdentityPink);
	}


	private void RenderLiveTimeline(VBoxContainer parent, JsonElement root)
	{
		var card = NewIdentityCard("Dòng trạng thái sống", IdentityAsset("identity_card_timeline.png"), "⌁", IdentityPink, 355f);
		card.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		var meta = new HBoxContainer();
		meta.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		meta.AddChild(NewLabel("◷  5 sự kiện gần nhất", 10, IdentityMuted, false));
		box.AddChild(meta);
		var events = BuildLiveEvents(root);
		int index = 0;
		foreach (IdentityLiveEvent item in events)
		{
			AddTimelineRow(box, item, index++);
			if (index >= 5) break;
		}
		while (index < 5)
		{
			AddTimelineRow(box, new IdentityLiveEvent
			{
				Title = "Đang chờ thêm một tín hiệu đáng kể",
				Detail = "Observer chưa ghi nhận sự kiện mới.",
				Tag = "quiet",
				IconPath = IdentityAsset("identity_event_quiet.png"),
				FallbackGlyph = "·",
				Accent = new Color(0.72f, 0.60f, 0.70f),
			}, index++);
		}
	}


	private void RenderStageExpression(HBoxContainer parent, JsonElement root)
	{
		JsonElement expression = Obj(root, "expression");
		var card = NewIdentityCard("Identity → Stage Expression", IdentityAsset("identity_card_stage.png"), "✧", IdentityPink, 245f);
		card.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		card.SizeFlagsStretchRatio = 1.04f;
		card.CustomMinimumSize = new Vector2(248f, 245f);
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		var content = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		content.AddThemeConstantOverride("separation", 10);
		box.AddChild(content);
		var metrics = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		metrics.AddThemeConstantOverride("separation", 7);
		content.AddChild(metrics);
		AddKeyValueRow(metrics, "Preset", PrettyStageText(ReadString(expression, "preset")), IdentityPink);
		AddHeartConfidence(metrics, ReadFloat(expression, "confidence"));
		AddMetricBar(metrics, "Intensity", ReadFloat(expression, "intensity"), IdentityPurple);
		AddKeyValueRow(metrics, "Sentence bias", PrettyStageText(ReadString(expression, "sentence_bias")), IdentityPurple);
		AddKeyValueRow(metrics, "Stage", PrettyStageText(ReadString(expression, "preset")), IdentityPink);
		content.AddChild(NewIconBadge(IdentityAsset("identity_stage_silhouette.png"), "♙", new Vector2(88f, 136f), IdentityPink, false));
	}


	private void RenderReadyDiscovery(HBoxContainer parent, JsonElement root)
	{
		JsonElement discovery = Obj(root, "discovery");
		JsonElement readyArray = Arr(discovery, "ready_to_share");
		JsonElement first = default;
		if (readyArray.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in readyArray.EnumerateArray()) { first = item; break; }
		}
		var card = NewIdentityCard("Discovery sẵn sàng", IdentityAsset("identity_card_discovery.png"), "♢", IdentityOrange, 245f);
		card.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		card.SizeFlagsStretchRatio = 0.96f;
		card.CustomMinimumSize = new Vector2(248f, 245f);
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		var badgeRow = new HBoxContainer();
		badgeRow.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		badgeRow.AddChild(NewPill(first.ValueKind == JsonValueKind.Object ? "1 sẵn sàng" : "chưa có", IdentityGreen, false));
		box.AddChild(badgeRow);
		var main = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		main.AddThemeConstantOverride("separation", 10);
		box.AddChild(main);
		main.AddChild(NewIconBadge(IdentityAsset("identity_discovery_mascot.png"), "♡", new Vector2(96f, 106f), IdentityOrange, false));
		var copy = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		main.AddChild(copy);
		if (first.ValueKind != JsonValueKind.Object)
		{
			copy.AddChild(NewLabel("Chưa có discovery nào chờ kể.", 12, IdentityMuted, false));
		}
		else
		{
			var topicLabel = NewLabel(TrimForPanel(ReadString(first, "topic"), 58), 14, IdentityInk, true);
			topicLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
			copy.AddChild(topicLabel);
			string take = ReadString(first, "eris_take");
			if (string.IsNullOrWhiteSpace(take)) take = ReadString(first, "summary");
			var teaser = NewLabel(TrimForPanel(take, 110), 10, IdentityMuted, false);
			teaser.AutowrapMode = TextServer.AutowrapMode.WordSmart;
			copy.AddChild(teaser);
		}
		var open = NewFooterButton("Mở discovery", IdentityAsset("identity_action_open_discovery.png"), "➤", () =>
		{
			_depthActiveTab = "discovery";
			RefreshDepthTabStyle();
			RefreshDepthPanel();
		}, IdentityPink);
		open.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		box.AddChild(open);
	}


	private void RenderRelationshipPreview(HBoxContainer parent, JsonElement root)
	{
		JsonElement rel = Obj(root, "relationship");
		var card = NewIdentityCard("Quan hệ & belief", IdentityAsset("identity_card_relationship.png"), "♧", IdentityAccent, 245f);
		card.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		card.SizeFlagsStretchRatio = 1.00f;
		card.CustomMinimumSize = new Vector2(248f, 245f);
		parent.AddChild(card);
		var box = (VBoxContainer)card.GetChild(0);
		AddRelationshipBar(box, "Tin tưởng", ReadFirstFloat(rel, "relational_trust", "trust"), IdentityPink, "♥");
		AddRelationshipBar(box, "Thân quen", ReadFloat(rel, "familiarity"), IdentityPurple, "♥");
		AddRelationshipBar(box, "Tôn trọng", ReadFloat(rel, "respect"), IdentityBlue, "♥");
		AddRelationshipBar(box, "Gắn kết", ReadFirstFloat(rel, "attachment_intensity", "closeness"), IdentityOrange, "♥");
		string belief = FindTopUserBelief(Obj(root, "beliefs"));
		box.AddChild(NewBeliefBox(string.IsNullOrWhiteSpace(belief) ? "Belief về bạn chưa đủ chắc để hiển thị." : belief));
	}


	private PanelContainer NewIdentityCard(string title, string iconPath, string fallbackGlyph, Color accent, float minHeight)
	{
		var card = new PanelContainer { CustomMinimumSize = new Vector2(0f, minHeight), SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		card.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.994f, 0.998f, 0.995f),
			BorderColor = new Color(accent.R, accent.G, accent.B, 0.27f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 18,
			CornerRadiusTopRight = 18,
			CornerRadiusBottomLeft = 18,
			CornerRadiusBottomRight = 18,
			ContentMarginLeft = 14f,
			ContentMarginTop = 11f,
			ContentMarginRight = 14f,
			ContentMarginBottom = 11f,
			ShadowColor = new Color(0.56f, 0.18f, 0.40f, 0.10f),
			ShadowSize = 9,
			ShadowOffset = new Vector2(0f, 3f),
		});
		var box = new VBoxContainer();
		box.AddThemeConstantOverride("separation", 5);
		card.AddChild(box);
		var header = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 24f) };
		header.AddThemeConstantOverride("separation", 6);
		header.AddChild(NewIconBadge(iconPath, fallbackGlyph, new Vector2(32f, 32f), accent, true));
		header.AddChild(NewLabel(title, 14, new Color(0.55f, 0.17f, 0.38f), true));
		box.AddChild(header);
		return card;
	}


	private static string ResolveIdentityAssetPath(string path)
	{
		if (string.IsNullOrWhiteSpace(path))
			return path ?? "";
		if (ResourceLoader.Exists(path))
			return path;

		// Chấp nhận lỗi đặt tên phổ biến "identity_mood_neutral.png.png" để asset
		// vẫn hiển thị trong lúc người dùng đang thay bộ icon.
		if (path.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
		{
			string doubled = path + ".png";
			if (ResourceLoader.Exists(doubled))
				return doubled;
		}
		return path;
	}


	private TextureRect NewIdentityTexture(string path, Vector2 size)
	{
		string resolvedPath = ResolveIdentityAssetPath(path);
		var rect = new TextureRect
		{
			CustomMinimumSize = size,
			Size = size,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
			MouseFilter = Control.MouseFilterEnum.Ignore,
			Modulate = Colors.White,
			SelfModulate = Colors.White,
			TextureFilter = CanvasItem.TextureFilterEnum.Linear,
		};
		if (ResourceLoader.Exists(resolvedPath))
			rect.Texture = GD.Load<Texture2D>(resolvedPath);
		return rect;
	}

	private Control NewIconBadge(string path, string fallbackGlyph, Vector2 size, Color accent, bool circular)
	{
		string resolvedPath = ResolveIdentityAssetPath(path);
		bool hasTexture = ResourceLoader.Exists(resolvedPath);
		var badge = new PanelContainer
		{
			CustomMinimumSize = size,
			Size = size,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		int radius = circular ? (int)Mathf.Round(Mathf.Min(size.X, size.Y) * 0.5f) : 14;

		// Ảnh màu hoàn chỉnh không cần thêm lớp nền hồng/border phủ phía sau. Khung
		// pastel chỉ dành cho glyph fallback khi asset còn thiếu.
		badge.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = hasTexture ? new Color(1f, 1f, 1f, 0f) : new Color(accent.R, accent.G, accent.B, 0.075f),
			BorderColor = hasTexture ? new Color(1f, 1f, 1f, 0f) : new Color(accent.R, accent.G, accent.B, 0.20f),
			BorderWidthLeft = hasTexture ? 0 : 1,
			BorderWidthTop = hasTexture ? 0 : 1,
			BorderWidthRight = hasTexture ? 0 : 1,
			BorderWidthBottom = hasTexture ? 0 : 1,
			CornerRadiusTopLeft = radius,
			CornerRadiusTopRight = radius,
			CornerRadiusBottomLeft = radius,
			CornerRadiusBottomRight = radius,
			ContentMarginLeft = hasTexture ? 0f : 3f,
			ContentMarginTop = hasTexture ? 0f : 3f,
			ContentMarginRight = hasTexture ? 0f : 3f,
			ContentMarginBottom = hasTexture ? 0f : 3f,
		});
		if (hasTexture)
		{
			badge.AddChild(NewIdentityTexture(resolvedPath, size));
		}
		else
		{
			var glyph = NewLabel(fallbackGlyph, Math.Max(12, (int)(Mathf.Min(size.X, size.Y) * 0.45f)), accent, true);
			glyph.HorizontalAlignment = HorizontalAlignment.Center;
			glyph.VerticalAlignment = VerticalAlignment.Center;
			badge.AddChild(glyph);
		}
		return badge;
	}

	private Control NewMoodOrb(string path, string subtitle)
	{
		string resolvedPath = ResolveIdentityAssetPath(path);
		if (ResourceLoader.Exists(resolvedPath))
			return NewIdentityTexture(resolvedPath, new Vector2(112f, 112f));
		var orb = new PanelContainer { CustomMinimumSize = new Vector2(112f, 112f) };
		orb.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.98f, 0.68f, 0.84f, 0.82f),
			BorderColor = new Color(0.74f, 0.45f, 0.90f, 0.55f),
			BorderWidthLeft = 3,
			BorderWidthTop = 3,
			BorderWidthRight = 3,
			BorderWidthBottom = 3,
			CornerRadiusTopLeft = 56,
			CornerRadiusTopRight = 56,
			CornerRadiusBottomLeft = 56,
			CornerRadiusBottomRight = 56,
		});
		var face = NewLabel("• ᴗ •", 21, new Color(0.33f, 0.21f, 0.38f), true);
		face.HorizontalAlignment = HorizontalAlignment.Center;
		face.VerticalAlignment = VerticalAlignment.Center;
		face.TooltipText = subtitle;
		orb.AddChild(face);
		return orb;
	}


	private void AddMetricBar(VBoxContainer parent, string label, float value, Color fill)
	{
		value = Mathf.Clamp(value, 0f, 1f);
		var row = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 22f) };
		row.AddThemeConstantOverride("separation", 8);
		var name = NewLabel(label, 11, IdentityInk, false);
		name.CustomMinimumSize = new Vector2(80f, 0f);
		name.SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin;
		row.AddChild(name);
		var bar = new ProgressBar
		{
			MinValue = 0,
			MaxValue = 1,
			Value = value,
			ShowPercentage = false,
			CustomMinimumSize = new Vector2(90f, 8f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		bar.AddThemeStyleboxOverride("background", RoundedBarStyle(new Color(0.97f, 0.90f, 0.94f), 6));
		bar.AddThemeStyleboxOverride("fill", RoundedBarStyle(fill, 6));
		row.AddChild(bar);
		var percent = NewLabel($"{value:0%}", 10, new Color(0.48f, 0.20f, 0.38f), true);
		percent.CustomMinimumSize = new Vector2(34f, 0f);
		percent.HorizontalAlignment = HorizontalAlignment.Right;
		row.AddChild(percent);
		parent.AddChild(row);
	}


	private static StyleBoxFlat RoundedBarStyle(Color color, int radius) => new()
	{
		BgColor = color,
		CornerRadiusTopLeft = radius,
		CornerRadiusTopRight = radius,
		CornerRadiusBottomLeft = radius,
		CornerRadiusBottomRight = radius,
	};

	private Label NewPill(string text, Color accent, bool alignRight)
	{
		var label = NewLabel(text, 9, accent, true);
		label.ClipText = true;
		label.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		label.TooltipText = text;
		label.HorizontalAlignment = HorizontalAlignment.Center;
		label.VerticalAlignment = VerticalAlignment.Center;
		label.CustomMinimumSize = new Vector2(78f, 24f);
		label.SizeFlagsHorizontal = alignRight ? Control.SizeFlags.ShrinkEnd : Control.SizeFlags.ShrinkBegin;
		label.AddThemeStyleboxOverride("normal", new StyleBoxFlat
		{
			BgColor = new Color(accent.R, accent.G, accent.B, 0.08f),
			BorderColor = new Color(accent.R, accent.G, accent.B, 0.24f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 13,
			CornerRadiusTopRight = 13,
			CornerRadiusBottomLeft = 13,
			CornerRadiusBottomRight = 13,
		});
		return label;
	}


	private Button NewFooterButton(string text, string iconPath, string fallbackGlyph, Action action, Color accent)
	{
		string resolvedIconPath = ResolveIdentityAssetPath(iconPath);
		bool hasIcon = ResourceLoader.Exists(resolvedIconPath);
		var button = NewButton(hasIcon ? text : $"{fallbackGlyph}  {text}", action, false);
		button.CustomMinimumSize = new Vector2(0f, 46f);
		button.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		button.SizeFlagsStretchRatio = 1f;
		button.FocusMode = Control.FocusModeEnum.None;
		button.AddThemeFontSizeOverride("font_size", 12);
		button.AddThemeConstantOverride("h_separation", 8);
		button.AddThemeColorOverride("font_color", new Color(0.31f, 0.20f, 0.31f));
		button.AddThemeColorOverride("font_hover_color", new Color(0.25f, 0.12f, 0.25f));
		button.AddThemeColorOverride("font_pressed_color", new Color(0.25f, 0.12f, 0.25f));
		button.AddThemeStyleboxOverride("normal", IdentityActionButtonStyle(accent, false, false));
		button.AddThemeStyleboxOverride("hover", IdentityActionButtonStyle(accent, true, false));
		button.AddThemeStyleboxOverride("pressed", IdentityActionButtonStyle(accent, true, true));
		button.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
		if (hasIcon)
		{
			button.Icon = GD.Load<Texture2D>(resolvedIconPath);
			button.ExpandIcon = true;
			button.AddThemeConstantOverride("icon_max_width", 22);
			button.AddThemeColorOverride("icon_normal_color", Colors.White);
			button.AddThemeColorOverride("icon_hover_color", Colors.White);
			button.AddThemeColorOverride("icon_pressed_color", Colors.White);
			button.AddThemeColorOverride("icon_focus_color", Colors.White);
		}
		return button;
	}


	// Chỉ reset khi mở panel hoặc đổi tab; refresh telemetry thường vẫn giữ vị trí người đang xem.
	private void ResetDepthScrollIfNeeded()
	{
		if (!_depthResetScrollOnRefresh || _depthScrollContainer == null)
			return;
		_depthResetScrollOnRefresh = false;
		Callable.From(() =>
		{
			if (_depthScrollContainer == null)
				return;
			_depthScrollContainer.ScrollVertical = 0;
			UpdateDepthScrollDecor();
		}).CallDeferred();
	}

	private static StyleBoxFlat IdentityActionDockStyle() => new()
	{
		BgColor = new Color(1f, 0.987f, 0.994f, 0.985f),
		BorderColor = new Color(0.94f, 0.78f, 0.86f, 0.92f),
		BorderWidthLeft = 1,
		BorderWidthTop = 1,
		BorderWidthRight = 1,
		BorderWidthBottom = 1,
		CornerRadiusTopLeft = 19,
		CornerRadiusTopRight = 19,
		CornerRadiusBottomLeft = 19,
		CornerRadiusBottomRight = 19,
		ShadowColor = new Color(0.50f, 0.16f, 0.36f, 0.12f),
		ShadowSize = 10,
		ShadowOffset = new Vector2(0f, 3f),
	};

	private static StyleBoxFlat IdentityActionButtonStyle(Color accent, bool hover, bool pressed)
	{
		float alpha = pressed ? 0.19f : hover ? 0.13f : 0.065f;
		float borderAlpha = pressed ? 0.72f : hover ? 0.58f : 0.34f;
		return new StyleBoxFlat
		{
			BgColor = new Color(accent.R, accent.G, accent.B, alpha),
			BorderColor = new Color(accent.R, accent.G, accent.B, borderAlpha),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 15,
			CornerRadiusTopRight = 15,
			CornerRadiusBottomLeft = 15,
			CornerRadiusBottomRight = 15,
			ContentMarginLeft = 14f,
			ContentMarginTop = 7f,
			ContentMarginRight = 14f,
			ContentMarginBottom = 7f,
			ShadowColor = new Color(accent.R, accent.G, accent.B, hover ? 0.14f : 0.07f),
			ShadowSize = hover ? 8 : 5,
			ShadowOffset = new Vector2(0f, pressed ? 1f : 2f),
		};
	}

	private static StyleBoxFlat IdentityTabStyle(bool active, bool hover)
	{
		Color bg = active
			? new Color(0.95f, hover ? 0.14f : 0.18f, 0.48f, 1f)
			: new Color(1f, hover ? 0.945f : 0.982f, hover ? 0.972f : 0.991f, 1f);
		Color border = active ? new Color(0.95f, 0.18f, 0.48f, 1f) : new Color(0.95f, 0.73f, 0.84f, hover ? 0.92f : 0.72f);
		return new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = border,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 15,
			CornerRadiusTopRight = 15,
			CornerRadiusBottomLeft = 15,
			CornerRadiusBottomRight = 15,
			ContentMarginLeft = 12f,
			ContentMarginRight = 12f,
			ShadowColor = new Color(0.55f, 0.14f, 0.37f, active ? 0.15f : hover ? 0.08f : 0.03f),
			ShadowSize = active ? 8 : hover ? 6 : 3,
			ShadowOffset = new Vector2(0f, active ? 3f : 1f),
		};
	}

	private static StyleBoxFlat IdentityTabPressedStyle() => new()
	{
		BgColor = new Color(0.88f, 0.12f, 0.42f, 1f),
		BorderColor = new Color(0.84f, 0.08f, 0.37f, 1f),
		BorderWidthLeft = 1,
		BorderWidthTop = 1,
		BorderWidthRight = 1,
		BorderWidthBottom = 1,
		CornerRadiusTopLeft = 15,
		CornerRadiusTopRight = 15,
		CornerRadiusBottomLeft = 15,
		CornerRadiusBottomRight = 15,
		ContentMarginLeft = 12f,
		ContentMarginRight = 12f,
		ShadowColor = new Color(0.45f, 0.08f, 0.28f, 0.12f),
		ShadowSize = 4,
		ShadowOffset = new Vector2(0f, 1f),
	};


	private void AddRankRow(VBoxContainer parent, int rank, string label, float value, Color accent)
	{
		var row = new PanelContainer { CustomMinimumSize = new Vector2(0f, 32f) };
		row.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(accent.R, accent.G, accent.B, 0.035f),
			BorderColor = new Color(accent.R, accent.G, accent.B, 0.12f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 11,
			CornerRadiusTopRight = 11,
			CornerRadiusBottomLeft = 11,
			CornerRadiusBottomRight = 11,
			ContentMarginLeft = 5f,
			ContentMarginRight = 7f,
		});
		parent.AddChild(row);
		var h = new HBoxContainer();
		h.AddThemeConstantOverride("separation", 8);
		row.AddChild(h);
		var badge = NewPill(rank.ToString(CultureInfo.InvariantCulture), accent, false);
		badge.CustomMinimumSize = new Vector2(30f, 24f);
		h.AddChild(badge);
		h.AddChild(NewLabel(string.IsNullOrWhiteSpace(label) ? "Chưa rõ" : label, 12, IdentityInk, false));
		h.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		h.AddChild(NewLabel($"{value:0.00}", 11, IdentityMuted, true));
	}


	private void AddCompactValue(VBoxContainer parent, string label, float value, Color accent)
	{
		var row = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 26f) };
		row.AddChild(NewLabel(string.IsNullOrWhiteSpace(label) || label == "—" ? "Chưa có tín hiệu rõ" : label, 11, IdentityMuted, false));
		row.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		row.AddChild(NewPill($"INT {Mathf.Clamp(value, 0f, 1f):0.00}", accent, false));
		parent.AddChild(row);
	}


	private void AddKeyValueRow(VBoxContainer parent, string key, string value, Color accent)
	{
		string fullValue = value ?? "";
		value = TrimForPanel(PrettyStageText(fullValue), 24);
		var row = new HBoxContainer();
		var name = NewLabel(key, 11, IdentityInk, true);
		name.CustomMinimumSize = new Vector2(80f, 0f);
		row.AddChild(name);
		var pill = NewPill(string.IsNullOrWhiteSpace(value) ? "—" : value, accent, false);
		pill.TooltipText = fullValue;
		pill.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		row.AddChild(pill);
		parent.AddChild(row);
	}

	private void AddTimelineRow(VBoxContainer parent, IdentityLiveEvent item, int index)
	{
		var row = new PanelContainer { CustomMinimumSize = new Vector2(0f, 60f) };
		row.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = index % 2 == 0 ? new Color(1f, 0.988f, 0.995f, 0.96f) : new Color(1f, 1f, 1f, 0.88f),
			BorderColor = new Color(item.Accent.R, item.Accent.G, item.Accent.B, 0.17f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14,
			CornerRadiusTopRight = 14,
			CornerRadiusBottomLeft = 14,
			CornerRadiusBottomRight = 14,
			ContentMarginLeft = 10f,
			ContentMarginTop = 4f,
			ContentMarginRight = 10f,
			ContentMarginBottom = 4f,
		});
		parent.AddChild(row);
		var h = new HBoxContainer();
		h.AddThemeConstantOverride("separation", 10);
		row.AddChild(h);
		var sequence = NewLabel($"{index + 1:00}", 10, IdentityMuted, true);
		sequence.CustomMinimumSize = new Vector2(30f, 0f);
		sequence.SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin;
		sequence.HorizontalAlignment = HorizontalAlignment.Center;
		h.AddChild(sequence);
		h.AddChild(NewIconBadge(item.IconPath, item.FallbackGlyph, new Vector2(48f, 48f), item.Accent, true));
		var copy = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		copy.AddThemeConstantOverride("separation", -1);
		var title = NewLabel(TrimForPanel(item.Title, 52), 11, IdentityInk, true);
		title.ClipText = true;
		copy.AddChild(title);
		var detail = NewLabel(TrimForPanel(item.Detail, 76), 9, IdentityMuted, false);
		detail.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		copy.AddChild(detail);
		h.AddChild(copy);
		h.AddChild(NewPill(item.Tag, item.Accent, false));
	}


	private List<IdentityLiveEvent> BuildLiveEvents(JsonElement root)
	{
		var events = new List<IdentityLiveEvent>();
		JsonElement discovery = Obj(root, "discovery");
		JsonElement activity = Obj(discovery, "current_activity");
		string activityTopic = ReadString(activity, "topic");
		if (!string.IsNullOrWhiteSpace(activityTopic))
		{
			events.Add(new IdentityLiveEvent
			{
				Title = "Nhận ra một chủ đề đáng tìm hiểu",
				Detail = activityTopic,
				Tag = "curious",
				IconPath = IdentityAsset("identity_event_curiosity.png"),
				FallbackGlyph = "♡",
				Accent = IdentityPink,
			});
			events.Add(new IdentityLiveEvent
			{
				Title = "Tạo discovery để chuẩn bị chia sẻ",
				Detail = activityTopic,
				Tag = "discovering",
				IconPath = IdentityAsset("identity_event_discovery.png"),
				FallbackGlyph = "▣",
				Accent = IdentityPurple,
			});
		}

		JsonElement ready = Arr(discovery, "ready_to_share");
		if (ready.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in ready.EnumerateArray())
			{
				events.Add(new IdentityLiveEvent
				{
					Title = "Muốn khoe nhưng đang giữ lại",
					Detail = ReadString(item, "topic"),
					Tag = "withholding",
					IconPath = IdentityAsset("identity_event_withholding.png"),
					FallbackGlyph = "▢",
					Accent = IdentityOrange,
				});
				break;
			}
		}

		JsonElement expression = Obj(root, "expression");
		string preset = ReadString(expression, "preset");
		if (!string.IsNullOrWhiteSpace(preset))
		{
			events.Add(new IdentityLiveEvent
			{
				Title = "Biểu hiện sân khấu: " + PrettyStageText(preset),
				Detail = "Cường độ " + ReadFloat(expression, "intensity").ToString("0.00", CultureInfo.InvariantCulture),
				Tag = "expressing",
				IconPath = IdentityAsset("identity_event_expression.png"),
				FallbackGlyph = "♙",
				Accent = IdentityPink,
			});
		}

		JsonElement observation = Obj(root, "latest_observation");
		string meaning = ReadString(observation, "relationship_meaning");
		if (!string.IsNullOrWhiteSpace(meaning))
		{
			events.Add(new IdentityLiveEvent
			{
				Title = "Tiếp tục quan sát phản ứng của bạn",
				Detail = PrettyIdentityKey(meaning),
				Tag = "observing",
				IconPath = IdentityAsset("identity_event_observing.png"),
				FallbackGlyph = "…",
				Accent = IdentityBlue,
			});
		}

		JsonElement speech = Obj(root, "speech_drive");
		JsonElement speechDecision = Obj(speech, "decision");
		float want = ReadFirstFloat(speech, "want_to_speak", "expression_urge", "urge", "speech_drive");
		if (want >= 0.25f && events.Count < 5)
		{
			bool allowed = ReadBool(speechDecision, "allowed", false);
			events.Add(new IdentityLiveEvent
			{
				Title = allowed ? "Đang có động lực chủ động nói" : "Muốn nói nhưng chọn giữ lại",
				Detail = PrettyIdentityKey(ReadString(speechDecision, "reason")),
				Tag = allowed ? "ready" : "withholding",
				IconPath = allowed ? IdentityAsset("identity_event_ready.png") : IdentityAsset("identity_event_withholding.png"),
				FallbackGlyph = allowed ? "➤" : "▢",
				Accent = allowed ? IdentityGreen : IdentityOrange,
			});
		}
		return events;
	}


	private void AddHeartConfidence(VBoxContainer parent, float confidence)
	{
		confidence = Mathf.Clamp(confidence, 0f, 1f);
		var row = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 22f) };
		var label = NewLabel("Confidence", 11, IdentityInk, false);
		label.CustomMinimumSize = new Vector2(80f, 0f);
		row.AddChild(label);
		int filled = Mathf.Clamp((int)Mathf.Round(confidence * 5f), 0, 5);
		var hearts = NewLabel(new string('♥', filled) + new string('♡', 5 - filled), 15, IdentityPink, true);
		hearts.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		row.AddChild(hearts);
		row.AddChild(NewLabel($"{confidence:0%}", 10, IdentityMuted, true));
		parent.AddChild(row);
	}

	private void AddRelationshipBar(VBoxContainer parent, string label, float value, Color fill, string glyph)
	{
		value = Mathf.Clamp(value, 0f, 1f);
		var row = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 22f) };
		row.AddThemeConstantOverride("separation", 7);
		var name = NewLabel(label, 10, IdentityInk, false);
		name.CustomMinimumSize = new Vector2(65f, 0f);
		row.AddChild(name);
		var bar = new ProgressBar
		{
			MinValue = 0,
			MaxValue = 1,
			Value = value,
			ShowPercentage = false,
			CustomMinimumSize = new Vector2(68f, 7f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		bar.AddThemeStyleboxOverride("background", RoundedBarStyle(new Color(0.96f, 0.90f, 0.94f), 5));
		bar.AddThemeStyleboxOverride("fill", RoundedBarStyle(fill, 5));
		row.AddChild(bar);
		row.AddChild(NewLabel($"{value:0.00}", 10, IdentityMuted, true));
		row.AddChild(NewLabel(glyph, 13, fill, true));
		parent.AddChild(row);
	}

	private PanelContainer NewBeliefBox(string belief)
	{
		var panel = new PanelContainer { CustomMinimumSize = new Vector2(0f, 54f) };
		panel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.94f, 0.97f, 0.80f),
			BorderColor = new Color(IdentityPink.R, IdentityPink.G, IdentityPink.B, 0.14f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 12,
			CornerRadiusTopRight = 12,
			CornerRadiusBottomLeft = 12,
			CornerRadiusBottomRight = 12,
			ContentMarginLeft = 10f,
			ContentMarginTop = 7f,
			ContentMarginRight = 10f,
			ContentMarginBottom = 7f,
		});
		var label = NewLabel("✧  Belief hiện tại\n“" + TrimForPanel(belief, 92) + "”", 10, new Color(0.46f, 0.25f, 0.41f), false);
		label.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		panel.AddChild(label);
		return panel;
	}

	private static float ReadFirstFloat(JsonElement root, params string[] keys)
	{
		foreach (string key in keys)
		{
			float value = ReadFloat(root, key);
			if (value > 0f) return Mathf.Clamp(value, 0f, 1f);
		}
		return 0f;
	}

	private static float ReadTopScore(JsonElement array, string preferredKey, float fallback)
	{
		if (array.ValueKind != JsonValueKind.Array) return fallback;
		foreach (JsonElement item in array.EnumerateArray())
		{
			if (string.Equals(ReadString(item, "key"), preferredKey, StringComparison.OrdinalIgnoreCase))
				return ReadFirstFloat(item, "strength", "value");
		}
		return fallback;
	}

	private static string BuildMoodSubtitle(JsonElement summary, JsonElement root)
	{
		JsonElement motives = Arr(root, "active_motives");
		var words = new List<string>();
		if (ReadFloat(summary, "arousal") < 0.35f) words.Add("bình ổn");
		if (motives.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in motives.EnumerateArray())
			{
				string key = ReadString(item, "key");
				if (key.Contains("curiosity", StringComparison.OrdinalIgnoreCase)) words.Add("tò mò");
				if (key.Contains("autonomy", StringComparison.OrdinalIgnoreCase)) words.Add("tự chủ");
				if (words.Count >= 2) break;
			}
		}
		if (words.Count == 0) words.Add("quan sát");
		return string.Join(" · ", words);
	}

	private static string FindTopUserBelief(JsonElement beliefs)
	{
		if (beliefs.ValueKind != JsonValueKind.Object) return "";
		string best = "";
		float score = 0f;
		foreach (JsonProperty property in beliefs.EnumerateObject())
		{
			if (!property.Name.StartsWith("user.", StringComparison.OrdinalIgnoreCase)) continue;
			float value = ReadFloat(property.Value, "strength") * ReadFloat(property.Value, "confidence");
			if (value <= score) continue;
			score = value;
			best = PrettyIdentityKey(property.Name.Replace("user.", "", StringComparison.OrdinalIgnoreCase));
		}
		return best;
	}

	private static string TrimForPanel(string text, int max)
	{
		text = (text ?? "").Trim();
		if (text.Length <= max) return text;
		return text[..Math.Max(0, max - 1)].TrimEnd() + "…";
	}

	private static string PrettyStageText(string value)
	{
		if (string.IsNullOrWhiteSpace(value)) return "—";
		string normalized = value.Trim().ToLowerInvariant();
		if (normalized.Contains("open with a concise", StringComparison.Ordinal)
			|| normalized.Contains("engaging greeting", StringComparison.Ordinal))
			return "Mở đầu gọn, có nhịp";
		if (normalized.Contains("dry tease", StringComparison.Ordinal)) return "Trêu khô";
		if (normalized.Contains("focused", StringComparison.Ordinal)) return "Tập trung";
		if (normalized.Contains("curious", StringComparison.Ordinal)) return "Tò mò";
		if (normalized.Contains("initiative", StringComparison.Ordinal)) return "Chủ động";
		if (normalized.Contains("compact", StringComparison.Ordinal)) return "Nói gọn rồi mở đường";
		return TrimForPanel(PrettyIdentityKey(value), 28);
	}

	private static string PrettyIdentityKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key)) return "—";
		return key.Trim().ToLowerInvariant() switch
		{
			"trung_tinh" or "neutral" => "Trung tính",
			"kho_chiu" => "Khó chịu",
			"vui" => "Vui",
			"curiosity_drive" => "Khao khát khám phá",
			"need_for_autonomy" => "Nhu cầu tự chủ",
			"need_for_dignity" => "Nhu cầu giữ phẩm giá",
			"need_to_understand" => "Muốn hiểu cho đến tận cùng",
			"intellectualization" => "Che cảm xúc bằng phân tích",
			"withdrawal" => "Rút vào khoảng riêng",
			"sarcastic_deflection" => "Lách bằng mỉa mai",
			"curiosity_vs_self_protection" => "Tò mò ↔ Tự bảo vệ",
			"attachment_vs_pride" => "Gắn bó ↔ Tự trọng",
			"compact_then_invite" => "Nói ngắn rồi mở đường",
			"active_curiosity" => "Tò mò đang hoạt động",
			"cooldown" or "initiative_cooldown" => "vừa chủ động gần đây",
			"post_chat_grace" => "vừa trò chuyện xong",
			"user_busy" => "bạn đang bận",
			_ => Pretty(key),
		};
	}

	private void RenderIdentityTab(JsonElement root)
	{
		AddScoreCard("Giá trị cốt lõi", Arr(root, "values_top"), "key", "value", 8);
		AddScoreCard("Động cơ nền", Arr(root, "motives_top"), "key", "value", 8);
		AddScoreCard("Cơ chế phòng vệ", Arr(root, "defenses_top"), "key", "value", 8);
		AddScoreCard("Giá trị tự hình thành", Arr(root, "emergent_values_top"), "key", "value", 8);

		JsonElement forms = Obj(root, "derived_forms");
		var formLines = new List<string>();
		if (forms.ValueKind == JsonValueKind.Object)
		{
			foreach (JsonProperty item in forms.EnumerateObject())
				formLines.Add($"{Pretty(item.Name)}  {ReadNumber(item.Value):0.00}");
		}
		formLines.Sort(StringComparer.Ordinal);
		AddInfoCard("Derived attractors · chỉ debug", formLines.Count > 0 ? formLines : new[] { "Chưa có attractor đáng kể." });
	}

	private void RenderRelationshipTab(JsonElement root)
	{
		JsonElement rel = Obj(root, "relationship");
		var relLines = new List<string>();
		if (rel.ValueKind == JsonValueKind.Object)
		{
			foreach (JsonProperty item in rel.EnumerateObject())
			{
				if (item.Value.ValueKind == JsonValueKind.Number)
					relLines.Add($"{Pretty(item.Name)}  {ReadNumber(item.Value):0.00}");
			}
		}
		AddInfoCard("Relationship profile · primary_user", relLines);

		JsonElement beliefs = Obj(root, "beliefs");
		var beliefLines = new List<string>();
		if (beliefs.ValueKind == JsonValueKind.Object)
		{
			foreach (JsonProperty item in beliefs.EnumerateObject())
			{
				if (!item.Name.StartsWith("user.", StringComparison.Ordinal) && !item.Name.StartsWith("self.", StringComparison.Ordinal))
					continue;
				JsonElement record = item.Value;
				beliefLines.Add($"{item.Name} · strength {ReadFloat(record, "strength"):0.00} · conf {ReadFloat(record, "confidence"):0.00}");
				if (beliefLines.Count >= 12) break;
			}
		}
		AddInfoCard("Beliefs đang có trọng lượng", beliefLines);
		AddInfoCard("Pending strategies", FormatObjectArray(Arr(root, "pending_strategies"), new[] { "strategy", "goal", "status" }, 6));
	}

	private void RenderDiscoveryTab(JsonElement root)
	{
		JsonElement discovery = Obj(root, "discovery");
		JsonElement activity = Obj(discovery, "current_activity");
		AddInfoCard("Activity thật", new[]
		{
			$"{ReadString(activity, "status")} · {ReadString(activity, "kind")}",
			ReadString(activity, "topic"),
			ReadString(activity, "detail"),
		});
		AddInfoCard("Sẵn sàng mang về khoe", FormatObjectArray(Arr(discovery, "ready_to_share"), new[] { "topic", "eris_take", "share_readiness" }, 6));
		AddInfoCard("Discovery gần đây", FormatObjectArray(Arr(discovery, "recent"), new[] { "lane", "topic", "shared" }, 8));

		JsonElement initiative = Obj(root, "initiative");
		AddInfoCard("Initiative policy", new[]
		{
			$"Enabled: {ReadBool(initiative, "enabled", true)}",
			$"Hourly budget: {ReadInt(initiative, "used_last_hour")}/{ReadInt(initiative, "hourly_budget")}",
			$"Minimum interval: {ReadFloat(initiative, "minimum_interval_seconds"):0}s",
		});
	}

	private void RenderAuditTab(JsonElement root)
	{
		JsonElement observation = Obj(root, "latest_observation");
		AddInfoCard("Objective Observer + Self Reflection", new[]
		{
			$"User act: {ReadString(observation, "user_act")} · meaning {ReadString(observation, "relationship_meaning")}",
			$"Confidence {ReadFloat(observation, "confidence"):0.00} · repair {ReadBool(observation, "repair_needed", false)}",
			ReadString(Obj(observation, "self_interpretation"), "summary"),
			ReadString(observation, "notes"),
		});
		AddInfoCard("Identity ledger", FormatObjectArray(Arr(root, "recent_identity_ledger"), new[] { "dimension", "key", "applied_delta", "outcome" }, 12));
		AddInfoCard("Personality trajectory", FormatObjectArray(Arr(root, "recent_personality_trajectory"), new[] { "category", "trait", "applied_delta", "source" }, 10));
		AddInfoCard("Formative imprints", FormatObjectArray(Arr(root, "imprints"), new[] { "theme", "strength", "valence", "preferred_defense" }, 8));

		JsonElement consolidation = Obj(root, "consolidation");
		AddInfoCard("Persistence & consolidation", new[]
		{
			$"Last write: {ReadFloat(consolidation, "last_write_at"):0}",
			$"Pending accepted events: {ReadInt(consolidation, "accepted_since_write")}",
			ReadString(consolidation, "snapshot_path"),
		});
	}

	private void AddScoreCard(string title, JsonElement array, string keyName, string valueName, int limit)
	{
		var lines = new List<string>();
		if (array.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in array.EnumerateArray())
			{
				lines.Add($"{Pretty(ReadString(item, keyName))}  {ReadFloat(item, valueName):0.00}");
				if (lines.Count >= limit) break;
			}
		}
		AddInfoCard(title, lines);
	}

	private void AddInfoCard(string title, IEnumerable<string> rawLines)
	{
		if (_depthContentList == null)
			return;
		var card = new PanelContainer();
		card.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = IdentityCard,
			BorderColor = IdentityBorder,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14,
			CornerRadiusTopRight = 14,
			CornerRadiusBottomLeft = 14,
			CornerRadiusBottomRight = 14,
			ContentMarginLeft = 16f,
			ContentMarginTop = 12f,
			ContentMarginRight = 16f,
			ContentMarginBottom = 12f,
		});
		_depthContentList.AddChild(card);
		var box = new VBoxContainer();
		box.AddThemeConstantOverride("separation", 5);
		card.AddChild(box);
		box.AddChild(NewLabel(title, 16, IdentityInk, true));
		int count = 0;
		foreach (string raw in rawLines ?? Array.Empty<string>())
		{
			string line = (raw ?? "").Trim();
			if (string.IsNullOrWhiteSpace(line)) continue;
			var label = NewLabel(line, 12, IdentityMuted, false);
			label.AutowrapMode = TextServer.AutowrapMode.WordSmart;
			box.AddChild(label);
			count++;
		}
		if (count == 0)
			box.AddChild(NewLabel("Chưa có dữ liệu đủ tin cậy.", 12, IdentityMuted, false));
	}

	private static List<string> FormatObjectArray(JsonElement array, string[] fields, int limit)
	{
		var lines = new List<string>();
		if (array.ValueKind != JsonValueKind.Array)
			return lines;
		foreach (JsonElement item in array.EnumerateArray())
		{
			var parts = new List<string>();
			foreach (string field in fields)
			{
				if (!item.TryGetProperty(field, out JsonElement value)) continue;
				string text = value.ValueKind switch
				{
					JsonValueKind.String => value.GetString() ?? "",
					JsonValueKind.Number => ReadNumber(value).ToString("0.00"),
					JsonValueKind.True => "true",
					JsonValueKind.False => "false",
					_ => "",
				};
				if (!string.IsNullOrWhiteSpace(text)) parts.Add($"{field}: {text}");
			}
			if (parts.Count > 0) lines.Add(string.Join(" · ", parts));
			if (lines.Count >= limit) break;
		}
		return lines;
	}

	private Label NewLabel(string text, int size, Color color, bool bold)
	{
		var label = new Label
		{
			Text = text ?? "",
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		label.AddThemeFontSizeOverride("font_size", size);
		label.AddThemeColorOverride("font_color", color);
		return label;
	}

	private Label NewChip(string text, Color bg, Color ink)
	{
		var label = NewLabel(text, 11, ink, true);
		label.HorizontalAlignment = HorizontalAlignment.Center;
		label.VerticalAlignment = VerticalAlignment.Center;
		label.CustomMinimumSize = new Vector2(112f, 32f);
		label.SizeFlagsHorizontal = Control.SizeFlags.ShrinkEnd;
		label.ClipText = true;
		label.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		label.AddThemeStyleboxOverride("normal", new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = ink,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 12,
			CornerRadiusTopRight = 12,
			CornerRadiusBottomLeft = 12,
			CornerRadiusBottomRight = 12,
		});
		return label;
	}

	private Button NewButton(string text, Action action, bool danger)
	{
		var button = new Button
		{
			Text = text,
			CustomMinimumSize = new Vector2(126f, 38f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		button.AddThemeFontSizeOverride("font_size", 12);
		Color bg = danger ? new Color(1f, 0.91f, 0.92f, 1f) : new Color(1f, 0.96f, 0.98f, 1f);
		Color border = danger ? new Color(0.78f, 0.29f, 0.34f, 1f) : IdentityBorder;
		button.AddThemeStyleboxOverride("normal", ButtonStyle(bg, border));
		button.AddThemeStyleboxOverride("hover", ButtonStyle(IdentityAccentSoft, IdentityAccent));
		button.AddThemeStyleboxOverride("pressed", ButtonStyle(new Color(0.92f, 0.79f, 0.86f, 1f), IdentityAccent));
		button.AddThemeColorOverride("font_color", danger ? new Color(0.68f, 0.20f, 0.25f, 1f) : IdentityInk);
		button.Pressed += action;
		return button;
	}

	private static StyleBoxFlat ButtonStyle(Color bg, Color border) => new()
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
		ContentMarginLeft = 10f,
		ContentMarginRight = 10f,
		ContentMarginTop = 4f,
		ContentMarginBottom = 4f,
	};

	private static JsonElement Obj(JsonElement root, string key)
	{
		return root.ValueKind == JsonValueKind.Object && root.TryGetProperty(key, out JsonElement value) && value.ValueKind == JsonValueKind.Object
			? value
			: default;
	}

	private static JsonElement Arr(JsonElement root, string key)
	{
		return root.ValueKind == JsonValueKind.Object && root.TryGetProperty(key, out JsonElement value) && value.ValueKind == JsonValueKind.Array
			? value
			: default;
	}

	private static string ReadString(JsonElement root, string key)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)) return "";
		return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : value.ToString();
	}

	private static float ReadFloat(JsonElement root, string key)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)) return 0f;
		return (float)ReadNumber(value);
	}

	private static double ReadNumber(JsonElement value)
	{
		if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double number)) return number;
		if (value.ValueKind == JsonValueKind.String && double.TryParse(value.GetString(), out number)) return number;
		return 0.0;
	}

	private static int ReadInt(JsonElement root, string key) => (int)Math.Round(ReadFloat(root, key));

	private static bool ReadBool(JsonElement root, string key, bool fallback)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)) return fallback;
		if (value.ValueKind == JsonValueKind.True) return true;
		if (value.ValueKind == JsonValueKind.False) return false;
		return fallback;
	}

	private static string JoinArray(JsonElement root, string key, int limit)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value) || value.ValueKind != JsonValueKind.Array)
			return "—";
		var items = new List<string>();
		foreach (JsonElement item in value.EnumerateArray())
		{
			if (item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString()))
				items.Add(item.GetString());
			if (items.Count >= limit) break;
		}
		return items.Count > 0 ? string.Join(", ", items) : "—";
	}

	private static string Pretty(string key) => string.IsNullOrWhiteSpace(key)
		? "—"
		: key.Replace("_", " ").Replace(".", " › ");
}
