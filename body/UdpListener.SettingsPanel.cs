using Godot;
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	private Panel _settingsPanel;
	private Label _settingsBrainStatusLabel;
	private Label _settingsProviderValueLabel;
	private Label _settingsModelValueLabel;
	private Label _settingsPoolStatusLabel;
	private Label _settingsFallbackStatusLabel;
	private Label _settingsStatusNoteLabel;
	private TextureRect _settingsTtsSwitch;
	private TextureRect _settingsAlwaysOnTopSwitch;
	private TextureRect _settingsTransparentSwitch;
	private TextureRect _settingsPassthroughSwitch;
	private bool _settingsTtsEnabled = true;

	private static readonly Color SettingsInk = new(0.42f, 0.07f, 0.27f);
	private static readonly Color SettingsInkSoft = new(0.63f, 0.32f, 0.48f);
	private static readonly Color SettingsPink = new(0.96f, 0.34f, 0.62f);
	private static readonly Color SettingsBorder = new(0.96f, 0.76f, 0.86f, 0.80f);
	private static readonly Color SettingsCard = new(1.00f, 0.965f, 0.982f, 0.70f);

	private void OnContextSettingsPressed()
	{
		ToggleSettingsPanel();
	}

	private void ToggleSettingsPanel()
	{
		if (_settingsPanel == null)
			return;
		if (_settingsPanel.Visible)
			CloseSettingsPanel();
		else
			ShowSettingsPanel();
	}

	private void ShowSettingsPanel()
	{
		if (_settingsPanel == null)
			return;
		CloseCharacterContextMenu();
		_settingsPanel.Visible = true;
		_settingsPanel.Size = SettingsPanelMinSize;
		Vector2 screenSize = GetViewportRect().Size;
		_settingsPanel.Position = new Vector2(
			Mathf.Max(0f, (screenSize.X - SettingsPanelMinSize.X) * 0.5f),
			Mathf.Max(0f, (screenSize.Y - SettingsPanelMinSize.Y) * 0.5f));
		RefreshSettingsPanel();
	}

	private void CloseSettingsPanel()
	{
		if (_settingsPanel != null)
			_settingsPanel.Visible = false;
	}

	private void BuildSettingsPanelUi()
	{
		if (_settingsPanel == null)
			return;

		var bgTex = ResourceLoader.Exists("res://asset/Resource/SettingPanel.png")
			? GD.Load<Texture2D>("res://asset/Resource/SettingPanel.png")
			: null;
		if (bgTex != null)
		{
			_settingsPanel.AddThemeStyleboxOverride("panel", new StyleBoxTexture
			{
				Texture = bgTex,
				TextureMarginLeft = 0f,
				TextureMarginTop = 0f,
				TextureMarginRight = 0f,
				TextureMarginBottom = 0f,
				AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
				AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
			});
		}
		else
		{
			_settingsPanel.AddThemeStyleboxOverride("panel", new StyleBoxEmpty());
		}
		_settingsPanel.ClipContents = true;
		foreach (Node child in _settingsPanel.GetChildren())
		{
			_settingsPanel.RemoveChild(child);
			child.QueueFree();
		}

		_switchOnTexture ??= GD.Load<Texture2D>("res://asset/Resource/on.png");
		_switchOffTexture ??= GD.Load<Texture2D>("res://asset/Resource/off.png");
		_settingsTtsEnabled = true;

		var root = new Control { MouseFilter = Control.MouseFilterEnum.Ignore };
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_settingsPanel.AddChild(root);

		// Nền cố ý để trống. Ông có thể gắn TextureRect background riêng sau mà
		// không phải đập lại layout/control bên dưới.
		var title = CreateUiLabel("Cài đặt", 34, SettingsInk);
		title.Position = new Vector2(54f, 34f);
		title.Size = new Vector2(260f, 52f);
		root.AddChild(title);

		var heart = CreateUiLabel("♡", 26, SettingsPink);
		heart.Position = new Vector2(222f, 42f);
		heart.Size = new Vector2(42f, 36f);
		root.AddChild(heart);

		var controls = CreateWindowControlCapsule(() => _settingsPanel.Visible = false, CloseSettingsPanel);
		controls.Position = new Vector2(900f, 34f);
		root.AddChild(controls);

		AddSettingsMainTabs(root);
		AddSettingsModeStrip(root);

		var statusCard = AddSettingsCard(root, new Rect2(32f, 205f, 302f, 342f), "Trạng thái Eris");
		BuildSettingsStatusColumn(statusCard);

		var poolCard = AddSettingsCard(root, new Rect2(356f, 205f, 328f, 342f), "Key pool");
		BuildSettingsKeyPoolColumn(poolCard);

		var displayCard = AddSettingsCard(root, new Rect2(706f, 205f, 302f, 342f), "Giọng & cửa sổ");
		BuildSettingsDisplayColumn(displayCard);

		var divider = new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.84f, 0.38f),
			Position = new Vector2(32f, 566f),
			Size = new Vector2(976f, 1.4f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		root.AddChild(divider);

		var noteHeart = CreateUiLabel("♡", 24, SettingsPink);
		noteHeart.Position = new Vector2(72f, 586f);
		noteHeart.Size = new Vector2(32f, 30f);
		root.AddChild(noteHeart);

		var note = CreateUiLabel("Key chỉ lưu local. Không cần sửa .env hay secrets.json.", 13, SettingsInkSoft);
		note.Position = new Vector2(112f, 592f);
		note.Size = new Vector2(430f, 24f);
		root.AddChild(note);

		_settingsStatusNoteLabel = CreateUiLabel("", 12, SettingsInk);
		_settingsStatusNoteLabel.Position = new Vector2(112f, 608f);
		_settingsStatusNoteLabel.Size = new Vector2(392f, 16f);
		_settingsStatusNoteLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_settingsStatusNoteLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_settingsStatusNoteLabel.AddThemeFontSizeOverride("font_size", 10);
		root.AddChild(_settingsStatusNoteLabel);

		var backup = CreateSettingsButton("Sao lưu", () => SetSettingsStatus("Chưa bật sao lưu tự động trong bản này."), primary: false);
		backup.Position = new Vector2(520f, 584f);
		backup.Size = new Vector2(116f, 38f);
		root.AddChild(backup);

		var export = CreateSettingsButton("Xuất config", () => SetSettingsStatus("Chưa xuất config ở bản UI preview."), primary: false);
		export.Position = new Vector2(650f, 584f);
		export.Size = new Vector2(126f, 38f);
		root.AddChild(export);

		var save = CreateSettingsButton("Lưu", () => SetSettingsStatus("Đã giữ thay đổi trong phiên UI. Persistence sẽ nối sau."), primary: true);
		save.Position = new Vector2(812f, 582f);
		save.Size = new Vector2(118f, 42f);
		root.AddChild(save);

		var cancel = CreateSettingsButton("Hủy", CloseSettingsPanel, primary: false);
		cancel.Position = new Vector2(942f, 582f);
		cancel.Size = new Vector2(82f, 42f);
		root.AddChild(cancel);

		RefreshSettingsPanel();
	}

	private void AddSettingsMainTabs(Control root)
	{
		AddSettingsTab(root, new Rect2(42f, 118f, 300f, 40f), "♡  Cơ bản", true);
		AddSettingsTab(root, new Rect2(370f, 118f, 300f, 40f), "♬  Giọng nói", false);
		AddSettingsTab(root, new Rect2(698f, 118f, 300f, 40f), "▤  Dữ liệu", false);
	}

	private void AddSettingsModeStrip(Control root)
	{
		var label = CreateUiLabel("Chế độ cấu hình", 13, SettingsInkSoft);
		label.Position = new Vector2(44f, 172f);
		label.Size = new Vector2(160f, 24f);
		root.AddChild(label);

		AddSettingsSmallTab(root, new Rect2(560f, 168f, 132f, 32f), "Cơ bản", true);
		AddSettingsSmallTab(root, new Rect2(706f, 168f, 132f, 32f), "Advanced", false);
		AddSettingsSmallTab(root, new Rect2(852f, 168f, 148f, 32f), "△ Danger Zone", false);
	}

	private Panel AddSettingsCard(Control parent, Rect2 rect, string title)
	{
		var panel = new Panel
		{
			Position = rect.Position,
			Size = rect.Size,
			ClipContents = true,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		panel.AddThemeStyleboxOverride("panel", SettingsCardStyle(SettingsCard, SettingsBorder, 16));
		parent.AddChild(panel);

		var titleLabel = CreateUiLabel(title, 20, SettingsInk);
		titleLabel.Position = new Vector2(18f, 14f);
		titleLabel.Size = new Vector2(rect.Size.X - 36f, 28f);
		panel.AddChild(titleLabel);
		return panel;
	}

	private void BuildSettingsStatusColumn(Control parent)
	{
		_settingsBrainStatusLabel = CreateSettingsChip("Brain đang chạy", true);
		_settingsBrainStatusLabel.Position = new Vector2(18f, 62f);
		_settingsBrainStatusLabel.Size = new Vector2(150f, 30f);
		parent.AddChild(_settingsBrainStatusLabel);

		float y = 106f;
		_settingsProviderValueLabel = AddSettingsInfoRow(parent, y, "Provider chính", RemoteApiProvider);
		y += 48f;
		_settingsModelValueLabel = AddSettingsInfoRow(parent, y, "Model chính", RemoteApiModelName);
		y += 48f;
		_settingsPoolStatusLabel = AddSettingsInfoRow(parent, y, "Pool Gemini", "—");
		y += 48f;
		_settingsFallbackStatusLabel = AddSettingsInfoRow(parent, y, "Fallback", "Bật");

		var start = CreateSettingsButton("Start", StartVisionProcess, primary: false);
		start.Position = new Vector2(18f, 252f);
		start.Size = new Vector2(80f, 34f);
		parent.AddChild(start);
		var stop = CreateSettingsButton("Stop", StopVisionProcess, primary: false);
		stop.Position = new Vector2(102f, 252f);
		stop.Size = new Vector2(80f, 34f);
		parent.AddChild(stop);
		var restart = CreateSettingsButton("Restart", RestartVisionProcess, primary: false);
		restart.Position = new Vector2(186f, 252f);
		restart.Size = new Vector2(96f, 34f);
		parent.AddChild(restart);

		var test = CreateSettingsButton("Test toàn hệ", TestSettingsSystem, primary: false);
		test.Position = new Vector2(18f, 294f);
		test.Size = new Vector2(264f, 36f);
		parent.AddChild(test);
	}

	private void BuildSettingsKeyPoolColumn(Control parent)
	{
		var list = new Panel
		{
			Position = new Vector2(18f, 58f),
			Size = new Vector2(292f, 156f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		list.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.72f), SettingsBorder, 14));
		parent.AddChild(list);

		string[] keys = { "A91F", "7C20", "D4B8", "9EA1" };
		string[] states = { "Sẵn sàng", "Sẵn sàng", "Cooldown 42s", "Sẵn sàng" };
		for (int i = 0; i < 4; i++)
			AddSettingsKeyRow(list, i, keys[i], states[i], i == 2);

		var add = CreateSettingsButton("Thêm key", () => SetSettingsStatus("Thêm key sẽ nối Credential Manager ở bước sau."), primary: false);
		add.Position = new Vector2(18f, 228f);
		add.Size = new Vector2(88f, 34f);
		parent.AddChild(add);
		var paste = CreateSettingsButton("Dán nhiều key", () => SetSettingsStatus("Dán nhiều key: UI đã có chỗ, parser sẽ nối sau."), primary: false);
		paste.Position = new Vector2(116f, 228f);
		paste.Size = new Vector2(104f, 34f);
		parent.AddChild(paste);
		var import = CreateSettingsButton("Nhập file key", () => SetSettingsStatus("Sẽ import secrets.json/key pool ở bước persistence."), primary: false);
		import.Position = new Vector2(230f, 228f);
		import.Size = new Vector2(80f, 34f);
		parent.AddChild(import);

		var rotate = CreateSettingsButton("Xoay thử", () => SetSettingsStatus("Đã gửi yêu cầu xoay thử ở UI. Backend nối sau."), primary: false);
		rotate.Position = new Vector2(18f, 282f);
		rotate.Size = new Vector2(132f, 38f);
		parent.AddChild(rotate);
		var test = CreateSettingsButton("Test pool", TestSettingsPool, primary: false);
		test.Position = new Vector2(166f, 282f);
		test.Size = new Vector2(144f, 38f);
		parent.AddChild(test);
	}

	private void BuildSettingsDisplayColumn(Control parent)
	{
		_settingsTtsSwitch = AddSettingsSwitch(parent, new Vector2(234f, 58f), _settingsTtsEnabled, () =>
		{
			_settingsTtsEnabled = !_settingsTtsEnabled;
			ApplySettingsSwitch(_settingsTtsSwitch, _settingsTtsEnabled);
			SetSettingsStatus(_settingsTtsEnabled ? "TTS bật trong phiên UI." : "TTS tắt trong phiên UI.");
		});
		var tts = CreateUiLabel("Bật TTS", 14, SettingsInk);
		tts.Position = new Vector2(18f, 62f);
		tts.Size = new Vector2(160f, 24f);
		parent.AddChild(tts);

		AddSettingsDropdownRow(parent, 104f, "TTS dùng", "Gemini pool");
		AddSettingsDropdownRow(parent, 152f, "Giọng", "Aoede");
		AddSettingsSegmentedLanguage(parent, 200f);

		var line = new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.84f, 0.45f),
			Position = new Vector2(18f, 242f),
			Size = new Vector2(264f, 1.2f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		parent.AddChild(line);

		AddSettingsToggleRow(parent, 252f, "Luôn nổi", KeepWindowAlwaysOnTop, ref _settingsAlwaysOnTopSwitch, () =>
		{
			KeepWindowAlwaysOnTop = !KeepWindowAlwaysOnTop;
			ApplySettingsSwitch(_settingsAlwaysOnTopSwitch, KeepWindowAlwaysOnTop);
			ConfigureDesktopOverlayWindow();
		});
		AddSettingsToggleRow(parent, 280f, "Trong suốt", UseTransparentWindow, ref _settingsTransparentSwitch, () =>
		{
			UseTransparentWindow = !UseTransparentWindow;
			ApplySettingsSwitch(_settingsTransparentSwitch, UseTransparentWindow);
			ConfigureDesktopOverlayWindow();
		});
		AddSettingsToggleRow(parent, 308f, "Click xuyên", EnableMousePassthrough, ref _settingsPassthroughSwitch, () =>
		{
			EnableMousePassthrough = !EnableMousePassthrough;
			ApplySettingsSwitch(_settingsPassthroughSwitch, EnableMousePassthrough);
			ConfigureDesktopOverlayWindow();
		});
	}

	private Label AddSettingsInfoRow(Control parent, float y, string label, string value)
	{
		var row = new Panel
		{
			Position = new Vector2(18f, y),
			Size = new Vector2(264f, 42f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.62f), SettingsBorder, 10));
		parent.AddChild(row);

		var left = CreateUiLabel(label, 11, SettingsInkSoft);
		left.Position = new Vector2(12f, 10f);
		left.Size = new Vector2(104f, 22f);
		StyleSettingsSingleLineLabel(left);
		row.AddChild(left);

		var right = CreateUiLabel(value, 11, SettingsInk);
		right.Position = new Vector2(118f, 10f);
		right.Size = new Vector2(134f, 22f);
		StyleSettingsSingleLineLabel(right, HorizontalAlignment.Right);
		row.AddChild(right);
		return right;
	}

	private void AddSettingsKeyRow(Control parent, int index, string suffix, string state, bool warn)
	{
		float y = 8f + index * 36f;
		var name = CreateUiLabel($"Key {index + 1:00}", 12, SettingsInk);
		name.Position = new Vector2(14f, y + 8f);
		name.Size = new Vector2(56f, 22f);
		StyleSettingsSingleLineLabel(name);
		parent.AddChild(name);

		var key = CreateUiLabel($"••••••••{suffix}", 12, SettingsInk);
		key.Position = new Vector2(76f, y + 8f);
		key.Size = new Vector2(106f, 22f);
		StyleSettingsSingleLineLabel(key);
		parent.AddChild(key);

		var dot = CreateUiLabel("●", 10, warn ? new Color(1.00f, 0.52f, 0.08f) : new Color(0.12f, 0.75f, 0.20f));
		dot.Position = new Vector2(188f, y + 9f);
		dot.Size = new Vector2(14f, 18f);
		StyleSettingsSingleLineLabel(dot, HorizontalAlignment.Center);
		parent.AddChild(dot);

		var st = CreateUiLabel(state, 9, warn ? new Color(0.96f, 0.42f, 0.10f) : new Color(0.10f, 0.50f, 0.14f));
		st.Position = new Vector2(202f, y + 8f);
		st.Size = new Vector2(58f, 22f);
		StyleSettingsSingleLineLabel(st);
		parent.AddChild(st);

		var menu = CreateUiLabel("⋮", 17, SettingsInkSoft);
		menu.Position = new Vector2(266f, y + 4f);
		menu.Size = new Vector2(16f, 24f);
		StyleSettingsSingleLineLabel(menu, HorizontalAlignment.Center);
		parent.AddChild(menu);
	}

	private void AddSettingsDropdownRow(Control parent, float y, string label, string value)
	{
		var row = new Panel
		{
			Position = new Vector2(18f, y),
			Size = new Vector2(264f, 38f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.62f), SettingsBorder, 12));
		parent.AddChild(row);

		var left = CreateUiLabel(label, 11, SettingsInkSoft);
		left.Position = new Vector2(12f, 9f);
		left.Size = new Vector2(78f, 22f);
		StyleSettingsSingleLineLabel(left);
		row.AddChild(left);
		var right = CreateUiLabel(value, 11, SettingsInk);
		right.Position = new Vector2(96f, 9f);
		right.Size = new Vector2(126f, 22f);
		StyleSettingsSingleLineLabel(right, HorizontalAlignment.Right);
		row.AddChild(right);
		var arrow = CreateUiLabel("⌄", 16, SettingsInkSoft);
		arrow.Position = new Vector2(226f, 7f);
		arrow.Size = new Vector2(20f, 24f);
		StyleSettingsSingleLineLabel(arrow, HorizontalAlignment.Center);
		row.AddChild(arrow);
	}

	private void AddSettingsSegmentedLanguage(Control parent, float y)
	{
		var row = new Panel
		{
			Position = new Vector2(18f, y),
			Size = new Vector2(264f, 38f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.62f), SettingsBorder, 12));
		parent.AddChild(row);

		var left = CreateUiLabel("Ngôn ngữ", 11, SettingsInkSoft);
		left.Position = new Vector2(12f, 9f);
		left.Size = new Vector2(78f, 22f);
		StyleSettingsSingleLineLabel(left);
		row.AddChild(left);

		AddSettingsSegment(row, new Rect2(136f, 6f, 40f, 26f), "Auto", true);
		AddSettingsSegment(row, new Rect2(180f, 6f, 36f, 26f), "VI", false);
		AddSettingsSegment(row, new Rect2(220f, 6f, 36f, 26f), "JA", false);
	}

	private void AddSettingsToggleRow(Control parent, float y, string label, bool initial, ref TextureRect target, Action onToggle)
	{
		var lbl = CreateUiLabel(label, 12, SettingsInk);
		lbl.Position = new Vector2(18f, y + 5f);
		lbl.Size = new Vector2(150f, 24f);
		StyleSettingsSingleLineLabel(lbl);
		parent.AddChild(lbl);
		target = AddSettingsSwitch(parent, new Vector2(234f, y), initial, onToggle);
	}

	private void StyleSettingsSingleLineLabel(Label label, HorizontalAlignment alignment = HorizontalAlignment.Left)
	{
		if (label == null)
			return;
		label.HorizontalAlignment = alignment;
		label.VerticalAlignment = VerticalAlignment.Center;
		label.AutowrapMode = TextServer.AutowrapMode.Off;
		label.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
	}

	private TextureRect AddSettingsSwitch(Control parent, Vector2 pos, bool initial, Action onToggle)
	{
		var tex = new TextureRect
		{
			Texture = initial ? _switchOnTexture : _switchOffTexture,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			Position = pos,
			Size = new Vector2(58f, 34f),
			CustomMinimumSize = new Vector2(58f, 34f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		tex.GuiInput += ev =>
		{
			if (ev is InputEventMouseButton mouse && mouse.ButtonIndex == MouseButton.Left && mouse.Pressed)
			{
				onToggle?.Invoke();
				tex.AcceptEvent();
			}
		};
		parent.AddChild(tex);
		return tex;
	}

	private void ApplySettingsSwitch(TextureRect tex, bool on)
	{
		if (tex != null)
			tex.Texture = on ? _switchOnTexture : _switchOffTexture;
	}

	private void AddSettingsTab(Control parent, Rect2 rect, string text, bool active)
	{
		var btn = CreateSettingsButton(text, () => SetSettingsStatus(active ? "Đang ở tab Cơ bản." : "Tab này sẽ nối UI sau."), primary: active);
		btn.Position = rect.Position;
		btn.Size = rect.Size;
		parent.AddChild(btn);
	}

	private void AddSettingsSmallTab(Control parent, Rect2 rect, string text, bool active)
	{
		var btn = CreateSettingsButton(text, () => SetSettingsStatus(active ? "Đang ở chế độ cơ bản." : $"{text} sẽ mở ở bước sau."), primary: active);
		btn.Position = rect.Position;
		btn.Size = rect.Size;
		btn.AddThemeFontSizeOverride("font_size", 12);
		parent.AddChild(btn);
	}

	private void AddSettingsSegment(Control parent, Rect2 rect, string text, bool active)
	{
		var btn = CreateSettingsButton(text, () => SetSettingsStatus($"Ngôn ngữ: {text}"), primary: active);
		btn.Position = rect.Position;
		btn.Size = rect.Size;
		btn.AddThemeFontSizeOverride("font_size", 10);
		parent.AddChild(btn);
	}

	private Button CreateSettingsButton(string text, Action onPressed, bool primary)
	{
		var btn = new Button
		{
			Text = text,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			Alignment = HorizontalAlignment.Center,
			ClipText = true,
			TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis,
		};

		var normal = new StyleBoxFlat
		{
			BgColor = primary ? new Color(0.96f, 0.34f, 0.62f, 0.82f) : new Color(1f, 0.97f, 0.985f, 0.76f),
			BorderColor = primary ? new Color(1f, 0.66f, 0.80f, 0.95f) : SettingsBorder,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 13,
			CornerRadiusTopRight = 13,
			CornerRadiusBottomLeft = 13,
			CornerRadiusBottomRight = 13,
			ContentMarginLeft = 5f,
			ContentMarginRight = 5f,
			ContentMarginTop = 4f,
			ContentMarginBottom = 4f,
		};
		var hover = (StyleBoxFlat)normal.Duplicate();
		hover.BgColor = primary ? new Color(0.98f, 0.42f, 0.68f, 0.92f) : new Color(1f, 0.92f, 0.96f, 0.86f);
		var pressed = (StyleBoxFlat)hover.Duplicate();
		pressed.BgColor = primary ? new Color(0.92f, 0.26f, 0.55f, 0.92f) : new Color(0.99f, 0.86f, 0.92f, 0.90f);

		btn.AddThemeStyleboxOverride("normal", normal);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", pressed);
		btn.AddThemeStyleboxOverride("focus", hover);
		btn.AddThemeColorOverride("font_color", primary ? Colors.White : SettingsInk);
		btn.AddThemeColorOverride("font_hover_color", primary ? Colors.White : SettingsPink);
		btn.AddThemeColorOverride("font_pressed_color", primary ? Colors.White : SettingsInk);
		btn.AddThemeFontSizeOverride("font_size", 12);
		btn.Pressed += onPressed;
		return btn;
	}

	private Label CreateSettingsChip(string text, bool good)
	{
		var chip = CreateUiLabel(text, 12, good ? new Color(0.10f, 0.42f, 0.14f) : new Color(0.64f, 0.34f, 0.08f));
		chip.HorizontalAlignment = HorizontalAlignment.Center;
		chip.VerticalAlignment = VerticalAlignment.Center;
		chip.AddThemeStyleboxOverride("normal", SettingsCardStyle(
			good ? new Color(0.84f, 1.00f, 0.86f, 0.88f) : new Color(1.00f, 0.94f, 0.80f, 0.88f),
			good ? new Color(0.40f, 0.84f, 0.48f, 0.80f) : new Color(1.00f, 0.62f, 0.24f, 0.75f),
			10));
		return chip;
	}

	private static StyleBoxFlat SettingsCardStyle(Color bg, Color border, int radius)
	{
		return new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = border,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = radius,
			CornerRadiusTopRight = radius,
			CornerRadiusBottomLeft = radius,
			CornerRadiusBottomRight = radius,
		};
	}

	private void RestartVisionProcess()
	{
		StopVisionProcess();
		StartVisionProcess();
	}

	private void TestSettingsSystem()
	{
		int keys = CountConfiguredGeminiKeys();
		string brain = _processes != null && _processes.IsVisionRunning ? "brain chạy" : "brain dừng";
		SetSettingsStatus($"Test nhanh: {brain}, Gemini pool {keys} key, TTS {_settingsTtsEnabledText()}.");
	}

	private void TestSettingsPool()
	{
		int keys = CountConfiguredGeminiKeys();
		SetSettingsStatus(keys > 0 ? $"Tìm thấy {keys} key Gemini trong secrets/env." : "Chưa thấy key Gemini trong config/secrets.json.");
	}

	private string _settingsTtsEnabledText() => _settingsTtsEnabled ? "bật" : "tắt";

	private void SetSettingsStatus(string text)
	{
		if (_settingsStatusNoteLabel != null)
			_settingsStatusNoteLabel.Text = text ?? "";
		RunLogger.Log($"[Settings] {text}");
	}

	private void RefreshSettingsPanel()
	{
		if (_settingsPanel == null)
			return;

		bool running = _processes != null && _processes.IsVisionRunning;
		if (_settingsBrainStatusLabel != null)
		{
			_settingsBrainStatusLabel.Text = running ? "●  Brain đang chạy" : "●  Brain đang dừng";
			_settingsBrainStatusLabel.AddThemeStyleboxOverride("normal", SettingsCardStyle(
				running ? new Color(0.84f, 1.00f, 0.86f, 0.88f) : new Color(1.00f, 0.94f, 0.80f, 0.88f),
				running ? new Color(0.40f, 0.84f, 0.48f, 0.80f) : new Color(1.00f, 0.62f, 0.24f, 0.75f),
				10));
			_settingsBrainStatusLabel.AddThemeColorOverride(
				"font_color",
				running ? new Color(0.10f, 0.42f, 0.14f) : new Color(0.64f, 0.34f, 0.08f));
		}

		if (_settingsProviderValueLabel != null)
			_settingsProviderValueLabel.Text = string.IsNullOrWhiteSpace(RemoteApiProvider) ? "Gemini" : RemoteApiProvider;
		if (_settingsModelValueLabel != null)
			_settingsModelValueLabel.Text = string.IsNullOrWhiteSpace(RemoteApiModelName) ? "gemini-2.5-flash" : RemoteApiModelName;

		int geminiKeys = CountConfiguredGeminiKeys();
		if (_settingsPoolStatusLabel != null)
			_settingsPoolStatusLabel.Text = geminiKeys > 0 ? $"{geminiKeys}/{geminiKeys} sống" : "chưa có";
		if (_settingsFallbackStatusLabel != null)
			_settingsFallbackStatusLabel.Text = CountConfiguredGroqKeys() > 0 ? "Bật" : "Chưa khai";

		ApplySettingsSwitch(_settingsTtsSwitch, _settingsTtsEnabled);
		ApplySettingsSwitch(_settingsAlwaysOnTopSwitch, KeepWindowAlwaysOnTop);
		ApplySettingsSwitch(_settingsTransparentSwitch, UseTransparentWindow);
		ApplySettingsSwitch(_settingsPassthroughSwitch, EnableMousePassthrough);
	}

	private int CountConfiguredGeminiKeys()
	{
		return CountSecretsKeys("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "ERIS_SPEECH_API_KEY", "ERIS_PRIVATE_MIND_FALLBACK_API_KEYS", "ERIS_GEMINI_FALLBACK_API_KEYS");
	}

	private int CountConfiguredGroqKeys()
	{
		return CountSecretsKeys("ERIS_GROQ_API_KEY", "ERIS_GROQ_FALLBACK_API_KEYS", "ERIS_CHAT_FALLBACK_API_KEY", "ERIS_AGGREGATOR_API_KEY");
	}

	private int CountSecretsKeys(params string[] names)
	{
		var keys = new HashSet<string>(StringComparer.Ordinal);

		foreach (string name in names)
			AddSplitKeys(keys, System.Environment.GetEnvironmentVariable(name) ?? "");

		try
		{
			string path = Path.Combine(ProjectSettings.GlobalizePath("res://"), "config", "secrets.json");
			if (!File.Exists(path))
				return keys.Count;

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return keys.Count;

			CollectSecretsKeysFromObject(root, keys, names);
			foreach (string sectionName in new[] { "api_keys", "env", "secrets" })
				if (root.TryGetProperty(sectionName, out JsonElement section) && section.ValueKind == JsonValueKind.Object)
					CollectSecretsKeysFromObject(section, keys, names);
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Settings] Khong doc duoc key pool: {ex.Message}");
		}

		return keys.Count;
	}

	private static void CollectSecretsKeysFromObject(JsonElement source, HashSet<string> keys, string[] names)
	{
		foreach (string name in names)
		{
			if (!source.TryGetProperty(name, out JsonElement value))
				continue;
			if (value.ValueKind == JsonValueKind.String)
				AddSplitKeys(keys, value.GetString() ?? "");
			else if (value.ValueKind == JsonValueKind.Array)
			{
				foreach (JsonElement item in value.EnumerateArray())
					if (item.ValueKind == JsonValueKind.String)
						AddSplitKeys(keys, item.GetString() ?? "");
			}
		}
	}

	private static void AddSplitKeys(HashSet<string> keys, string raw)
	{
		foreach (string part in (raw ?? "").Replace("\n", ",").Replace(";", ",").Split(','))
		{
			string key = part.Trim();
			if (key.Length > 0 && !key.StartsWith("PASTE_", StringComparison.OrdinalIgnoreCase))
				keys.Add(key);
		}
	}
}
