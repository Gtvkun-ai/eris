using Godot;
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

public partial class UdpListener : Node2D
{
	private Panel _settingsPanel;
	private Label _settingsBrainStatusLabel;
	private Label _settingsPoolStatusLabel;
	private Label _settingsFallbackStatusLabel;
	private Label _settingsStatusNoteLabel;
	private TextureRect _settingsTtsSwitch;
	private TextureRect _settingsAlwaysOnTopSwitch;
	private TextureRect _settingsTransparentSwitch;
	private TextureRect _settingsPassthroughSwitch;
	private OptionButton _settingsProviderSelect;
	private OptionButton _settingsKeyPoolSelect;
	private LineEdit _settingsModelInput;
	private LineEdit _settingsBaseUrlInput;
	private OptionButton _settingsVoiceSelect;
	private OptionButton _settingsLanguageSelect;
	private OptionButton _settingsQualitySelect;
	private FileDialog _settingsImportSecretsDialog;
	private VBoxContainer _settingsKeyRowsBox;
	private readonly List<LineEdit> _settingsKeyInputs = new();
	private string _settingsKeyPoolKind = "";
	private bool _settingsTtsEnabled = true;
	private string _settingsTtsVoice = "Aoede";
	private string _settingsTtsLanguage = "auto";
	private string _settingsTtsQuality = "high";

	private const string SettingsStatePath = "user://eris_settings.json";
	private const string SettingsExportFileName = "eris_settings_export.json";

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

		var root = new Control { MouseFilter = Control.MouseFilterEnum.Ignore };
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_settingsPanel.AddChild(root);

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

		var statusCard = AddSettingsCard(root, new Rect2(32f, 205f, 302f, 342f), "Runtime");
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

		var note = CreateUiLabel("Basic ghi config thật: user settings + config/secrets.json local.", 13, SettingsInkSoft);
		note.Position = new Vector2(112f, 592f);
		note.Size = new Vector2(450f, 24f);
		root.AddChild(note);

		_settingsStatusNoteLabel = CreateUiLabel("", 12, SettingsInk);
		_settingsStatusNoteLabel.Position = new Vector2(112f, 608f);
		_settingsStatusNoteLabel.Size = new Vector2(438f, 16f);
		_settingsStatusNoteLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_settingsStatusNoteLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_settingsStatusNoteLabel.AddThemeFontSizeOverride("font_size", 10);
		root.AddChild(_settingsStatusNoteLabel);

		var backup = CreateSettingsButton("Sao lưu", BackupSettingsAndSecrets, primary: false);
		backup.Position = new Vector2(560f, 584f);
		backup.Size = new Vector2(104f, 38f);
		root.AddChild(backup);

		var export = CreateSettingsButton("Xuất config", ExportSanitizedSettings, primary: false);
		export.Position = new Vector2(674f, 584f);
		export.Size = new Vector2(118f, 38f);
		root.AddChild(export);

		var save = CreateSettingsButton("Lưu", SaveSettingsState, primary: true);
		save.Position = new Vector2(812f, 582f);
		save.Size = new Vector2(118f, 42f);
		root.AddChild(save);

		var cancel = CreateSettingsButton("Hủy", CloseSettingsPanel, primary: false);
		cancel.Position = new Vector2(942f, 582f);
		cancel.Size = new Vector2(82f, 42f);
		root.AddChild(cancel);

		_settingsImportSecretsDialog = new FileDialog
		{
			Title = "Nhập secrets.json",
			Access = FileDialog.AccessEnum.Filesystem,
			FileMode = FileDialog.FileModeEnum.OpenFile,
			Filters = new[] { "*.json ; JSON secrets" },
			Size = new Vector2I(720, 520),
		};
		_settingsImportSecretsDialog.FileSelected += ImportSecretsFile;
		_settingsPanel.AddChild(_settingsImportSecretsDialog);

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
		_settingsBrainStatusLabel = CreateSettingsChip("Brain", true);
		_settingsBrainStatusLabel.Position = new Vector2(18f, 56f);
		_settingsBrainStatusLabel.Size = new Vector2(150f, 30f);
		parent.AddChild(_settingsBrainStatusLabel);

		_settingsProviderSelect = AddSettingsOptionRow(parent, 96f, "Provider", new[] { "gemini", "openai_compatible", "groq" }, RemoteApiProvider);
		_settingsProviderSelect.ItemSelected += _ =>
		{
			SyncSettingsInputsToFields(applyProviderDefaults: true);
			_settingsKeyPoolKind = KeyPoolKindFromProvider(RemoteApiProvider, RemoteApiBaseUrl);
			RefreshSettingsProviderInputs();
			BuildSettingsPanelUi();
			SetSettingsStatus("Đã đổi provider và pool key đang chỉnh. Bấm Lưu hoặc Restart để áp dụng.");
		};
		_settingsModelInput = AddSettingsLineEditRow(parent, 142f, "Model", RemoteApiModelName);
		_settingsBaseUrlInput = AddSettingsLineEditRow(parent, 188f, "Base URL", RemoteApiBaseUrl);

		var start = CreateSettingsButton("Start", StartVisionProcess, primary: false);
		start.Position = new Vector2(18f, 238f);
		start.Size = new Vector2(80f, 34f);
		parent.AddChild(start);
		var stop = CreateSettingsButton("Stop", StopVisionProcess, primary: false);
		stop.Position = new Vector2(102f, 238f);
		stop.Size = new Vector2(80f, 34f);
		parent.AddChild(stop);
		var restart = CreateSettingsButton("Restart", () =>
		{
			SyncSettingsInputsToFields();
			RestartVisionProcess();
			SetSettingsStatus("Đã restart brain với cấu hình Basic hiện tại.");
		}, primary: false);
		restart.Position = new Vector2(186f, 238f);
		restart.Size = new Vector2(96f, 34f);
		parent.AddChild(restart);

		var test = CreateSettingsButton("Test hệ", TestSettingsSystem, primary: false);
		test.Position = new Vector2(18f, 286f);
		test.Size = new Vector2(128f, 36f);
		parent.AddChild(test);

		var logs = CreateSettingsButton("Mở logs", OpenSettingsLogs, primary: false);
		logs.Position = new Vector2(154f, 286f);
		logs.Size = new Vector2(128f, 36f);
		parent.AddChild(logs);
	}

	private void BuildSettingsKeyPoolColumn(Control parent)
	{
		if (string.IsNullOrWhiteSpace(_settingsKeyPoolKind))
			_settingsKeyPoolKind = KeyPoolKindFromProvider(RemoteApiProvider, RemoteApiBaseUrl);

		_settingsPoolStatusLabel = CreateSettingsChip("Gemini: —", true);
		_settingsPoolStatusLabel.Position = new Vector2(18f, 52f);
		_settingsPoolStatusLabel.Size = new Vector2(132f, 28f);
		parent.AddChild(_settingsPoolStatusLabel);

		_settingsFallbackStatusLabel = CreateSettingsChip("Fallback: —", true);
		_settingsFallbackStatusLabel.Position = new Vector2(162f, 52f);
		_settingsFallbackStatusLabel.Size = new Vector2(148f, 28f);
		parent.AddChild(_settingsFallbackStatusLabel);

		_settingsKeyPoolSelect = AddSettingsOptionRow(parent, 88f, "Đang sửa", new[] { "gemini", "groq" }, _settingsKeyPoolKind);
		_settingsKeyPoolSelect.ItemSelected += _ =>
		{
			_settingsKeyPoolKind = SelectedOptionText(_settingsKeyPoolSelect, "gemini");
			BuildSettingsPanelUi();
			SetSettingsStatus($"Đang sửa pool {_settingsKeyPoolKind}. Sửa xong bấm Lưu.");
		};

		var list = new Panel
		{
			Position = new Vector2(18f, 132f),
			Size = new Vector2(292f, 94f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		list.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.72f), SettingsBorder, 14));
		parent.AddChild(list);

		_settingsKeyInputs.Clear();
		var scroller = new ScrollContainer
		{
			Position = new Vector2(6f, 6f),
			Size = new Vector2(280f, 82f),
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
			VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		list.AddChild(scroller);

		_settingsKeyRowsBox = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		_settingsKeyRowsBox.AddThemeConstantOverride("separation", 4);
		scroller.AddChild(_settingsKeyRowsBox);

		var keys = ReadEditableKeysForPool(_settingsKeyPoolKind);
		foreach (string key in keys)
			AddSettingsEditableKeyRow(key);
		if (keys.Count == 0)
			AddSettingsEditableKeyRow("");

		var add = CreateSettingsButton("Thêm dòng", () =>
		{
			AddSettingsEditableKeyRow("");
			SetSettingsStatus("Đã thêm dòng trống. Dán key vào rồi bấm Lưu.");
		}, primary: false);
		add.Position = new Vector2(18f, 238f);
		add.Size = new Vector2(84f, 34f);
		parent.AddChild(add);
		var paste = CreateSettingsButton("Dán nhiều", () => AddKeysFromClipboard(false), primary: false);
		paste.Position = new Vector2(108f, 238f);
		paste.Size = new Vector2(92f, 34f);
		parent.AddChild(paste);
		var import = CreateSettingsButton("Nhập file", OpenImportSecretsDialog, primary: false);
		import.Position = new Vector2(206f, 238f);
		import.Size = new Vector2(104f, 34f);
		parent.AddChild(import);

		var reload = CreateSettingsButton("Nạp lại pool", () =>
		{
			BuildSettingsPanelUi();
			SetSettingsStatus("Đã đọc lại key pool từ secrets/env.");
		}, primary: false);
		reload.Position = new Vector2(18f, 286f);
		reload.Size = new Vector2(132f, 36f);
		parent.AddChild(reload);
		var test = CreateSettingsButton("Test pool", TestSettingsPool, primary: false);
		test.Position = new Vector2(166f, 286f);
		test.Size = new Vector2(144f, 36f);
		parent.AddChild(test);
	}

	private void BuildSettingsDisplayColumn(Control parent)
	{
		_settingsTtsSwitch = AddSettingsSwitch(parent, new Vector2(234f, 56f), _settingsTtsEnabled, () =>
		{
			_settingsTtsEnabled = !_settingsTtsEnabled;
			ApplySettingsSwitch(_settingsTtsSwitch, _settingsTtsEnabled);
			SaveSettingsState(false, writeSecrets: false);
			SetSettingsStatus(_settingsTtsEnabled ? "TTS bật. Restart để Python nhận nếu đang chạy." : "TTS tắt. Restart để Python nhận nếu đang chạy.");
		});
		var tts = CreateUiLabel("Bật TTS", 14, SettingsInk);
		tts.Position = new Vector2(18f, 60f);
		tts.Size = new Vector2(160f, 24f);
		parent.AddChild(tts);

		_settingsVoiceSelect = AddSettingsOptionRow(parent, 100f, "Giọng", new[] { "Aoede", "Leda", "Achernar", "Kore", "Callirrhoe" }, _settingsTtsVoice);
		_settingsLanguageSelect = AddSettingsOptionRow(parent, 146f, "Ngôn ngữ", new[] { "auto", "vi", "ja", "en" }, _settingsTtsLanguage);
		_settingsQualitySelect = AddSettingsOptionRow(parent, 192f, "Chất lượng", new[] { "balanced", "high" }, _settingsTtsQuality);

		var line = new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.84f, 0.45f),
			Position = new Vector2(18f, 238f),
			Size = new Vector2(264f, 1.2f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		parent.AddChild(line);

		AddSettingsToggleRow(parent, 248f, "Luôn nổi", KeepWindowAlwaysOnTop, ref _settingsAlwaysOnTopSwitch, () =>
		{
			KeepWindowAlwaysOnTop = !KeepWindowAlwaysOnTop;
			ApplySettingsSwitch(_settingsAlwaysOnTopSwitch, KeepWindowAlwaysOnTop);
			ConfigureDesktopOverlayWindow();
			SaveSettingsState(false, writeSecrets: false);
		});
		AddSettingsToggleRow(parent, 278f, "Trong suốt", UseTransparentWindow, ref _settingsTransparentSwitch, () =>
		{
			UseTransparentWindow = !UseTransparentWindow;
			ApplySettingsSwitch(_settingsTransparentSwitch, UseTransparentWindow);
			ConfigureDesktopOverlayWindow();
			SaveSettingsState(false, writeSecrets: false);
		});
		AddSettingsToggleRow(parent, 308f, "Click xuyên", EnableMousePassthrough, ref _settingsPassthroughSwitch, () =>
		{
			EnableMousePassthrough = !EnableMousePassthrough;
			ApplySettingsSwitch(_settingsPassthroughSwitch, EnableMousePassthrough);
			ConfigureDesktopOverlayWindow();
			SaveSettingsState(false, writeSecrets: false);
		});
	}

	private LineEdit AddSettingsLineEditRow(Control parent, float y, string label, string value)
	{
		var row = new Panel
		{
			Position = new Vector2(18f, y),
			Size = new Vector2(264f, 38f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.62f), SettingsBorder, 12));
		parent.AddChild(row);

		var left = CreateUiLabel(label, 10, SettingsInkSoft);
		left.Position = new Vector2(12f, 8f);
		left.Size = new Vector2(76f, 22f);
		StyleSettingsSingleLineLabel(left);
		row.AddChild(left);

		var input = new LineEdit
		{
			Text = value ?? "",
			Position = new Vector2(90f, 5f),
			Size = new Vector2(162f, 28f),
			MouseFilter = Control.MouseFilterEnum.Stop,
			PlaceholderText = label,
			Flat = true,
		};
		input.AddThemeColorOverride("font_color", SettingsInk);
		input.AddThemeColorOverride("font_placeholder_color", SettingsInkSoft);
		input.AddThemeFontSizeOverride("font_size", 10);
		input.TextSubmitted += _ =>
		{
			SyncSettingsInputsToFields();
			SetSettingsStatus("Đã nhận giá trị. Bấm Lưu để ghi config.");
		};
		row.AddChild(input);
		return input;
	}

	private OptionButton AddSettingsOptionRow(Control parent, float y, string label, string[] values, string selected)
	{
		var row = new Panel
		{
			Position = new Vector2(18f, y),
			Size = new Vector2(264f, 38f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.62f), SettingsBorder, 12));
		parent.AddChild(row);

		var left = CreateUiLabel(label, 10, SettingsInkSoft);
		left.Position = new Vector2(12f, 8f);
		left.Size = new Vector2(82f, 22f);
		StyleSettingsSingleLineLabel(left);
		row.AddChild(left);

		var option = new OptionButton
		{
			Position = new Vector2(96f, 5f),
			Size = new Vector2(156f, 28f),
			MouseFilter = Control.MouseFilterEnum.Stop,
			ClipText = true,
			TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis,
		};
		option.AddThemeFontSizeOverride("font_size", 10);
		option.AddThemeColorOverride("font_color", SettingsInk);
		for (int i = 0; i < values.Length; i++)
		{
			option.AddItem(values[i]);
			if (string.Equals(values[i], selected, StringComparison.OrdinalIgnoreCase))
				option.Select(i);
		}
		option.ItemSelected += _ => SyncSettingsInputsToFields();
		row.AddChild(option);
		return option;
	}

	private void AddSettingsEditableKeyRow(string value)
	{
		if (_settingsKeyRowsBox == null)
			return;

		var row = new Panel
		{
			CustomMinimumSize = new Vector2(260f, 28f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.58f), new Color(0.96f, 0.76f, 0.86f, 0.45f), 9));
		_settingsKeyRowsBox.AddChild(row);

		int rowNumber = _settingsKeyInputs.Count + 1;
		var name = CreateUiLabel($"{rowNumber:00}", 10, SettingsInkSoft);
		name.Position = new Vector2(8f, 3f);
		name.Size = new Vector2(24f, 22f);
		StyleSettingsSingleLineLabel(name);
		row.AddChild(name);

		var input = new LineEdit
		{
			Text = value ?? "",
			PlaceholderText = "paste API key",
			Position = new Vector2(34f, 2f),
			Size = new Vector2(176f, 24f),
			Flat = true,
			Secret = true,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		input.AddThemeFontSizeOverride("font_size", 9);
		input.AddThemeColorOverride("font_color", SettingsInk);
		input.AddThemeColorOverride("font_placeholder_color", SettingsInkSoft);
		input.TextChanged += _ => SetSettingsStatus($"Đã sửa key trong pool {_settingsKeyPoolKind}. Bấm Lưu để ghi secrets.");
		row.AddChild(input);
		_settingsKeyInputs.Add(input);

		var reveal = CreateSettingsButton("M", () =>
		{
			input.Secret = !input.Secret;
			SetSettingsStatus(input.Secret ? "Đã ẩn key." : "Đang hiện key để sửa.");
		}, primary: false);
		reveal.TooltipText = "Mo/an key";
		reveal.Position = new Vector2(216f, 3f);
		reveal.Size = new Vector2(24f, 22f);
		reveal.AddThemeFontSizeOverride("font_size", 9);
		row.AddChild(reveal);

		var remove = CreateSettingsButton("X", () =>
		{
			_settingsKeyInputs.Remove(input);
			row.QueueFree();
			SetSettingsStatus("Đã đánh dấu xóa dòng key. Bấm Lưu để ghi secrets.");
		}, primary: false);
		remove.Position = new Vector2(242f, 3f);
		remove.Size = new Vector2(24f, 22f);
		remove.AddThemeFontSizeOverride("font_size", 10);
		row.AddChild(remove);
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
		var btn = CreateSettingsButton(text, () => SetSettingsStatus(SettingsTabHint(text, active)), primary: active);
		btn.Position = rect.Position;
		btn.Size = rect.Size;
		parent.AddChild(btn);
	}

	private void AddSettingsSmallTab(Control parent, Rect2 rect, string text, bool active)
	{
		var btn = CreateSettingsButton(text, () => SetSettingsStatus(SettingsTabHint(text, active)), primary: active);
		btn.Position = rect.Position;
		btn.Size = rect.Size;
		btn.AddThemeFontSizeOverride("font_size", 12);
		parent.AddChild(btn);
	}

	private static string SettingsTabHint(string text, bool active)
	{
		if (active)
			return "Đang chỉnh Basic: runtime, key pool, TTS, overlay.";
		if (text.Contains("Giọng", StringComparison.OrdinalIgnoreCase))
			return "Giọng nói cơ bản nằm ở card Giọng & cửa sổ.";
		if (text.Contains("Dữ liệu", StringComparison.OrdinalIgnoreCase))
			return "Dữ liệu cơ bản: key pool, backup, export config.";
		if (text.Contains("Advanced", StringComparison.OrdinalIgnoreCase))
			return "Advanced chưa tách màn; Basic hiện đã ghi config thật.";
		if (text.Contains("Danger", StringComparison.OrdinalIgnoreCase))
			return "Danger Zone: import secrets sẽ backup file cũ trước khi ghi đè.";
		return "Cấu hình nằm trong các card bên dưới.";
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
		var chip = CreateUiLabel(text, 11, good ? new Color(0.10f, 0.42f, 0.14f) : new Color(0.64f, 0.34f, 0.08f));
		chip.HorizontalAlignment = HorizontalAlignment.Center;
		chip.VerticalAlignment = VerticalAlignment.Center;
		chip.AutowrapMode = TextServer.AutowrapMode.Off;
		chip.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
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

	private void LoadSettingsState()
	{
		LoadSettingsFromSecrets();
		try
		{
			string path = ProjectSettings.GlobalizePath(SettingsStatePath);
			if (!File.Exists(path))
				return;

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return;

			if (TryReadBool(root, "tts_enabled", out bool tts))
				_settingsTtsEnabled = tts;
			if (TryReadBool(root, "always_on_top", out bool top))
				KeepWindowAlwaysOnTop = top;
			if (TryReadBool(root, "transparent_window", out bool transparent))
				UseTransparentWindow = transparent;
			if (TryReadBool(root, "mouse_passthrough", out bool pass))
				EnableMousePassthrough = pass;
			RemoteApiProvider = ReadString(root, "remote_provider", RemoteApiProvider);
			RemoteApiBaseUrl = ReadString(root, "remote_base_url", RemoteApiBaseUrl);
			RemoteApiModelName = ReadString(root, "remote_model", RemoteApiModelName);
			_settingsTtsVoice = ReadString(root, "tts_voice", _settingsTtsVoice);
			_settingsTtsLanguage = ReadString(root, "tts_language", _settingsTtsLanguage);
			_settingsTtsQuality = ReadString(root, "tts_quality", _settingsTtsQuality);
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Settings] Khong doc duoc user settings: {ex.Message}");
		}
	}

	private void LoadSettingsFromSecrets()
	{
		try
		{
			string path = GetSecretsPath();
			if (!File.Exists(path))
				return;
			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return;

			RemoteApiProvider = ReadSecretString(root, "ERIS_REMOTE_PROVIDER", RemoteApiProvider);
			RemoteApiBaseUrl = ReadSecretString(root, "ERIS_REMOTE_BASE_URL", RemoteApiBaseUrl);
			RemoteApiModelName = ReadSecretString(root, "ERIS_REMOTE_MODEL", RemoteApiModelName);
			string tts = ReadSecretString(root, "ERIS_TTS_ENABLED", _settingsTtsEnabled ? "1" : "0");
			_settingsTtsEnabled = IsTruthy(tts);
			_settingsTtsVoice = ReadSecretString(root, "ERIS_TTS_VOICE", _settingsTtsVoice);
			_settingsTtsLanguage = ReadSecretString(root, "ERIS_TTS_LANGUAGE", _settingsTtsLanguage);
			_settingsTtsQuality = ReadSecretString(root, "ERIS_TTS_QUALITY", _settingsTtsQuality);
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Settings] Khong doc duoc config/secrets.json: {ex.Message}");
		}
	}

	private void SaveSettingsState()
	{
		SaveSettingsState(true, writeSecrets: true);
	}

	private void SaveSettingsState(bool showStatus, bool writeSecrets)
	{
		SyncSettingsInputsToFields();
		try
		{
			string path = ProjectSettings.GlobalizePath(SettingsStatePath);
			string dir = Path.GetDirectoryName(path);
			if (!string.IsNullOrWhiteSpace(dir))
				Directory.CreateDirectory(dir);

			var state = BuildSanitizedSettingsNode();
			state["saved_at"] = DateTime.Now.ToString("O");
			File.WriteAllText(path, state.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
			if (writeSecrets)
				WriteRuntimeSettingsToSecrets(backup: true);
			if (showStatus)
				SetSettingsStatus(writeSecrets ? "Đã lưu Basic vào user settings + secrets.json." : "Đã lưu user settings.");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Không lưu được settings: {ex.Message}");
		}
	}

	private void WriteRuntimeSettingsToSecrets(bool backup)
	{
		string path = GetSecretsPath();
		Directory.CreateDirectory(Path.GetDirectoryName(path) ?? GetRuntimeBaseDirForSettings());
		if (backup)
			BackupFileIfExists(path, "secrets_before_basic_save");

		JsonObject root = LoadSecretsRoot();
		JsonObject env = EnsureObject(root, "env");
		env["ERIS_REMOTE_API_ENABLED"] = EnableRemoteCognitionApi ? "1" : "0";
		env["ERIS_REMOTE_PROVIDER"] = RemoteApiProvider ?? "";
		env["ERIS_REMOTE_BASE_URL"] = RemoteApiBaseUrl ?? "";
		env["ERIS_REMOTE_MODEL"] = RemoteApiModelName ?? "";
		env["ERIS_TTS_ENABLED"] = _settingsTtsEnabled ? "1" : "0";
		env["ERIS_TTS_VOICE"] = _settingsTtsVoice ?? "Aoede";
		env["ERIS_TTS_LANGUAGE"] = _settingsTtsLanguage ?? "auto";
		env["ERIS_TTS_QUALITY"] = _settingsTtsQuality ?? "high";

		if (_settingsKeyInputs.Count > 0)
			ReplaceEditableKeysForPool(root, _settingsKeyPoolKind, CollectEditedSettingsKeys());

		File.WriteAllText(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
	}

	private JsonObject BuildSanitizedSettingsNode()
	{
		return new JsonObject
		{
			["version"] = 1,
			["remote_api_enabled"] = EnableRemoteCognitionApi,
			["remote_provider"] = RemoteApiProvider ?? "",
			["remote_base_url"] = RemoteApiBaseUrl ?? "",
			["remote_model"] = RemoteApiModelName ?? "",
			["tts_enabled"] = _settingsTtsEnabled,
			["tts_voice"] = _settingsTtsVoice ?? "Aoede",
			["tts_language"] = _settingsTtsLanguage ?? "auto",
			["tts_quality"] = _settingsTtsQuality ?? "high",
			["always_on_top"] = KeepWindowAlwaysOnTop,
			["transparent_window"] = UseTransparentWindow,
			["mouse_passthrough"] = EnableMousePassthrough,
			["editing_key_pool"] = _settingsKeyPoolKind ?? "",
			["editing_key_count"] = CollectEditedSettingsKeys().Count,
		};
	}

	private void SyncSettingsInputsToFields(bool applyProviderDefaults = false)
	{
		if (_settingsProviderSelect != null && _settingsProviderSelect.Selected >= 0)
			RemoteApiProvider = _settingsProviderSelect.GetItemText(_settingsProviderSelect.Selected);
		if (applyProviderDefaults)
			ApplyProviderDefaults(RemoteApiProvider);
		if (_settingsModelInput != null)
			RemoteApiModelName = _settingsModelInput.Text.Trim();
		if (_settingsBaseUrlInput != null)
			RemoteApiBaseUrl = _settingsBaseUrlInput.Text.Trim();
		if (_settingsVoiceSelect != null && _settingsVoiceSelect.Selected >= 0)
			_settingsTtsVoice = _settingsVoiceSelect.GetItemText(_settingsVoiceSelect.Selected);
		if (_settingsLanguageSelect != null && _settingsLanguageSelect.Selected >= 0)
			_settingsTtsLanguage = _settingsLanguageSelect.GetItemText(_settingsLanguageSelect.Selected);
		if (_settingsQualitySelect != null && _settingsQualitySelect.Selected >= 0)
			_settingsTtsQuality = _settingsQualitySelect.GetItemText(_settingsQualitySelect.Selected);
	}

	private void ApplyProviderDefaults(string provider)
	{
		string normalized = (provider ?? "").Trim().ToLowerInvariant();
		if (normalized == "groq" || normalized == "openai_compatible")
		{
			if (string.IsNullOrWhiteSpace(RemoteApiBaseUrl) || RemoteApiBaseUrl.Contains("googleapis", StringComparison.OrdinalIgnoreCase))
				RemoteApiBaseUrl = "https://api.groq.com/openai/v1";
			if (string.IsNullOrWhiteSpace(RemoteApiModelName) || RemoteApiModelName.Contains("gemini", StringComparison.OrdinalIgnoreCase) || RemoteApiModelName.Contains("gemma", StringComparison.OrdinalIgnoreCase))
				RemoteApiModelName = "llama-3.1-8b-instant";
			RemoteApiProvider = normalized == "groq" ? "groq" : "openai_compatible";
			return;
		}
		if (string.IsNullOrWhiteSpace(RemoteApiBaseUrl) || RemoteApiBaseUrl.Contains("groq.com", StringComparison.OrdinalIgnoreCase))
			RemoteApiBaseUrl = "https://generativelanguage.googleapis.com/v1beta";
		if (string.IsNullOrWhiteSpace(RemoteApiModelName) || RemoteApiModelName.StartsWith("llama", StringComparison.OrdinalIgnoreCase))
			RemoteApiModelName = "gemini-2.5-flash";
		RemoteApiProvider = "gemini";
	}

	private void RefreshSettingsProviderInputs()
	{
		if (_settingsModelInput != null)
			_settingsModelInput.Text = RemoteApiModelName ?? "";
		if (_settingsBaseUrlInput != null)
			_settingsBaseUrlInput.Text = RemoteApiBaseUrl ?? "";
		if (_settingsProviderSelect != null)
			SelectOptionText(_settingsProviderSelect, RemoteApiProvider);
	}

	private void RestartVisionProcess()
	{
		StopVisionProcess();
		StartVisionProcess();
	}

	private void TestSettingsSystem()
	{
		SyncSettingsInputsToFields();
		int gemini = CountConfiguredGeminiKeys();
		int groq = CountConfiguredGroqKeys();
		string brain = _processes != null && _processes.IsVisionRunning ? "brain chạy" : "brain dừng";
		string secrets = File.Exists(GetSecretsPath()) ? "có secrets" : "thiếu secrets";
		SetSettingsStatus($"OK: {brain}, provider {RemoteApiProvider}, Gemini {gemini}, Groq {groq}, TTS {_settingsTtsEnabledText()}, {secrets}.");
	}

	private void TestSettingsPool()
	{
		int gemini = CountConfiguredGeminiKeys();
		int groq = CountConfiguredGroqKeys();
		int editing = CollectEditedSettingsKeys().Count;
		SetSettingsStatus($"Pool: Gemini {gemini} key, Groq/fallback {groq} key. Đang sửa {_settingsKeyPoolKind}: {editing} key.");
	}

	private void BackupSettingsAndSecrets()
	{
		try
		{
			string backupDir = GetSettingsBackupDir();
			Directory.CreateDirectory(backupDir);
			string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
			int copied = 0;

			string secrets = GetSecretsPath();
			if (File.Exists(secrets))
			{
				File.Copy(secrets, Path.Combine(backupDir, $"secrets_{stamp}.json"), overwrite: false);
				copied++;
			}

			string settings = ProjectSettings.GlobalizePath(SettingsStatePath);
			if (File.Exists(settings))
			{
				File.Copy(settings, Path.Combine(backupDir, $"eris_settings_{stamp}.json"), overwrite: false);
				copied++;
			}

			SetSettingsStatus(copied > 0 ? $"Đã sao lưu {copied} file vào {backupDir}" : "Chưa có secrets/settings để sao lưu.");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Sao lưu lỗi: {ex.Message}");
		}
	}

	private void ExportSanitizedSettings()
	{
		try
		{
			SyncSettingsInputsToFields();
			string exportPath = Path.Combine(GetRuntimeBaseDirForSettings(), "config", SettingsExportFileName);
			Directory.CreateDirectory(Path.GetDirectoryName(exportPath) ?? GetRuntimeBaseDirForSettings());

			var node = BuildSanitizedSettingsNode();
			node["exported_at"] = DateTime.Now.ToString("O");
			node["gemini_key_count"] = CountConfiguredGeminiKeys();
			node["groq_key_count"] = CountConfiguredGroqKeys();
			node["note"] = "No raw API keys are exported.";

			File.WriteAllText(exportPath, node.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
			SetSettingsStatus($"Đã xuất config sạch: {exportPath}");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Xuất config lỗi: {ex.Message}");
		}
	}

	private void OpenSettingsLogs()
	{
		try
		{
			string logPath = RunLogger.LogFilePath ?? "";
			string logDir = string.IsNullOrWhiteSpace(logPath)
				? Path.Combine(GetRuntimeBaseDirForSettings(), "logs")
				: Path.GetDirectoryName(logPath);
			if (string.IsNullOrWhiteSpace(logDir))
				logDir = Path.Combine(GetRuntimeBaseDirForSettings(), "logs");
			Directory.CreateDirectory(logDir);
			OS.ShellOpen(logDir);
			SetSettingsStatus($"Đã mở logs: {logDir}");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Không mở được logs: {ex.Message}");
		}
	}

	private void AddKeysFromClipboard(bool onlyFirst)
	{
		try
		{
			string raw = DisplayServer.ClipboardGet();
			var keys = ExtractClipboardKeys(raw);
			if (onlyFirst && keys.Count > 1)
				keys.RemoveRange(1, keys.Count - 1);
			if (keys.Count == 0)
			{
				SetSettingsStatus("Clipboard không có key hợp lệ.");
				return;
			}

			int added = AppendKeysToEditor(keys);
			SetSettingsStatus(added > 0 ? $"Đã dán {added} key vào pool {_settingsKeyPoolKind}. Bấm Lưu để ghi secrets." : "Key trong clipboard đã có sẵn trong editor.");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Thêm key lỗi: {ex.Message}");
		}
	}

	private int AppendKeysToEditor(List<string> keys)
	{
		var existing = new HashSet<string>(CollectEditedSettingsKeys(), StringComparer.Ordinal);
		int added = 0;
		foreach (string key in keys)
		{
			if (!existing.Add(key))
				continue;
			AddSettingsEditableKeyRow(key);
			added++;
		}
		return added;
	}

	private void OpenImportSecretsDialog()
	{
		if (_settingsImportSecretsDialog == null)
		{
			SetSettingsStatus("FileDialog chưa sẵn sàng.");
			return;
		}
		_settingsImportSecretsDialog.PopupCentered(new Vector2I(720, 520));
	}

	private void ImportSecretsFile(string selectedPath)
	{
		try
		{
			if (string.IsNullOrWhiteSpace(selectedPath) || !File.Exists(selectedPath))
			{
				SetSettingsStatus("File secrets không tồn tại.");
				return;
			}

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(selectedPath));
			if (doc.RootElement.ValueKind != JsonValueKind.Object)
			{
				SetSettingsStatus("secrets.json phải là JSON object.");
				return;
			}

			string target = GetSecretsPath();
			Directory.CreateDirectory(Path.GetDirectoryName(target) ?? GetRuntimeBaseDirForSettings());
			BackupFileIfExists(target, "secrets_before_import");
			File.Copy(selectedPath, target, overwrite: true);
			LoadSettingsFromSecrets();
			BuildSettingsPanelUi();
			SetSettingsStatus($"Đã nhập secrets.json: {target}");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Nhập secrets lỗi: {ex.Message}");
		}
	}

	private void BackupFileIfExists(string path, string prefix)
	{
		if (!File.Exists(path))
			return;
		string backupDir = GetSettingsBackupDir();
		Directory.CreateDirectory(backupDir);
		string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
		File.Copy(path, Path.Combine(backupDir, $"{prefix}_{stamp}.json"), overwrite: false);
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

		int geminiKeys = CountConfiguredGeminiKeys();
		if (_settingsPoolStatusLabel != null)
			_settingsPoolStatusLabel.Text = geminiKeys > 0 ? $"Gemini {geminiKeys}" : "Gemini trống";
		int groqKeys = CountConfiguredGroqKeys();
		if (_settingsFallbackStatusLabel != null)
			_settingsFallbackStatusLabel.Text = groqKeys > 0 ? $"Fallback {groqKeys}" : "Fallback trống";

		ApplySettingsSwitch(_settingsTtsSwitch, _settingsTtsEnabled);
		ApplySettingsSwitch(_settingsAlwaysOnTopSwitch, KeepWindowAlwaysOnTop);
		ApplySettingsSwitch(_settingsTransparentSwitch, UseTransparentWindow);
		ApplySettingsSwitch(_settingsPassthroughSwitch, EnableMousePassthrough);
	}

	private int CountConfiguredGeminiKeys()
	{
		return ReadConfiguredGeminiKeys().Count;
	}

	private int CountConfiguredGroqKeys()
	{
		return ReadConfiguredGroqKeys().Count;
	}

	private List<string> ReadConfiguredGeminiKeys()
	{
		return ReadConfiguredKeys("ERIS_PRIVATE_MIND_API_KEY", "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "ERIS_SPEECH_API_KEY", "ERIS_PRIVATE_MIND_FALLBACK_API_KEYS", "ERIS_GEMINI_FALLBACK_API_KEYS");
	}

	private List<string> ReadConfiguredGroqKeys()
	{
		return ReadConfiguredKeys("ERIS_GROQ_API_KEY", "ERIS_GROQ_FALLBACK_API_KEYS", "ERIS_CHAT_FALLBACK_API_KEY", "ERIS_AGGREGATOR_API_KEY");
	}

	private List<string> ReadEditableKeysForPool(string poolKind)
	{
		return IsGroqPool(poolKind)
			? ReadConfiguredKeysFromSecretsOnly("ERIS_GROQ_API_KEY", "ERIS_GROQ_FALLBACK_API_KEYS")
			: ReadConfiguredKeysFromSecretsOnly("ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "ERIS_PRIVATE_MIND_FALLBACK_API_KEYS", "ERIS_GEMINI_FALLBACK_API_KEYS");
	}

	private List<string> CollectEditedSettingsKeys()
	{
		var keys = new List<string>();
		var unique = new HashSet<string>(StringComparer.Ordinal);
		foreach (LineEdit input in _settingsKeyInputs)
		{
			if (input == null || !IsInstanceValid(input))
				continue;
			foreach (string key in ExtractClipboardKeys(input.Text ?? ""))
			{
				if (unique.Add(key))
					keys.Add(key);
			}
		}
		return keys;
	}

	private static void ReplaceEditableKeysForPool(JsonObject root, string poolKind, List<string> keys)
	{
		bool groq = IsGroqPool(poolKind);
		string[] controlled = groq
			? new[] { "ERIS_GROQ_API_KEY", "ERIS_GROQ_FALLBACK_API_KEYS" }
			: new[] { "ERIS_REMOTE_API_KEY", "GEMINI_API_KEY", "ERIS_PRIVATE_MIND_FALLBACK_API_KEYS", "ERIS_GEMINI_FALLBACK_API_KEYS" };

		RemoveControlledKeys(root, controlled);
		foreach (string sectionName in new[] { "api_keys", "env", "secrets" })
		{
			if (root[sectionName] is JsonObject section)
				RemoveControlledKeys(section, controlled);
		}

		JsonObject apiKeys = EnsureObject(root, "api_keys");
		if (keys.Count == 0)
			return;

		if (groq)
		{
			apiKeys["ERIS_GROQ_API_KEY"] = keys[0];
			JsonArray fallback = new();
			for (int i = 1; i < keys.Count; i++)
				fallback.Add(keys[i]);
			apiKeys["ERIS_GROQ_FALLBACK_API_KEYS"] = fallback;
			return;
		}

		apiKeys["ERIS_REMOTE_API_KEY"] = keys[0];
		apiKeys["GEMINI_API_KEY"] = keys[0];
		JsonArray privateMindFallback = new();
		JsonArray geminiFallback = new();
		for (int i = 1; i < keys.Count; i++)
		{
			privateMindFallback.Add(keys[i]);
			geminiFallback.Add(keys[i]);
		}
		apiKeys["ERIS_PRIVATE_MIND_FALLBACK_API_KEYS"] = privateMindFallback;
		apiKeys["ERIS_GEMINI_FALLBACK_API_KEYS"] = geminiFallback;
	}

	private static void RemoveControlledKeys(JsonObject obj, string[] names)
	{
		foreach (string name in names)
			obj.Remove(name);
	}

	private List<string> ReadConfiguredKeys(params string[] names)
	{
		var unique = new HashSet<string>(StringComparer.Ordinal);
		var keys = new List<string>();

		foreach (string name in names)
			AddSplitKeys(keys, unique, System.Environment.GetEnvironmentVariable(name) ?? "");

		try
		{
			string path = GetSecretsPath();
			if (!File.Exists(path))
				return keys;

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return keys;

			CollectSecretsKeysFromObject(root, keys, unique, names);
			foreach (string sectionName in new[] { "api_keys", "env", "secrets" })
				if (root.TryGetProperty(sectionName, out JsonElement section) && section.ValueKind == JsonValueKind.Object)
					CollectSecretsKeysFromObject(section, keys, unique, names);
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Settings] Khong doc duoc key pool: {ex.Message}");
		}

		return keys;
	}

	private List<string> ReadConfiguredKeysFromSecretsOnly(params string[] names)
	{
		var unique = new HashSet<string>(StringComparer.Ordinal);
		var keys = new List<string>();
		try
		{
			string path = GetSecretsPath();
			if (!File.Exists(path))
				return keys;

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return keys;

			CollectSecretsKeysFromObject(root, keys, unique, names);
			foreach (string sectionName in new[] { "api_keys", "env", "secrets" })
				if (root.TryGetProperty(sectionName, out JsonElement section) && section.ValueKind == JsonValueKind.Object)
					CollectSecretsKeysFromObject(section, keys, unique, names);
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Settings] Khong doc duoc editable key pool: {ex.Message}");
		}
		return keys;
	}

	private static void CollectSecretsKeysFromObject(JsonElement source, List<string> keys, HashSet<string> unique, string[] names)
	{
		foreach (string name in names)
		{
			if (!source.TryGetProperty(name, out JsonElement value))
				continue;
			if (value.ValueKind == JsonValueKind.String)
				AddSplitKeys(keys, unique, value.GetString() ?? "");
			else if (value.ValueKind == JsonValueKind.Array)
			{
				foreach (JsonElement item in value.EnumerateArray())
					if (item.ValueKind == JsonValueKind.String)
						AddSplitKeys(keys, unique, item.GetString() ?? "");
			}
		}
	}

	private static void AddSplitKeys(List<string> keys, HashSet<string> unique, string raw)
	{
		foreach (string part in (raw ?? "").Replace("\n", ",").Replace(";", ",").Split(','))
		{
			string key = part.Trim();
			if (key.Length > 0 && !key.StartsWith("PASTE_", StringComparison.OrdinalIgnoreCase) && unique.Add(key))
				keys.Add(key);
		}
	}

	private static List<string> ExtractClipboardKeys(string raw)
	{
		var keys = new List<string>();
		var unique = new HashSet<string>(StringComparer.Ordinal);
		foreach (string token in (raw ?? "").Split(new[] { '\r', '\n', '\t', ' ', ',', ';', '"', '\'', '[', ']' }, StringSplitOptions.RemoveEmptyEntries))
		{
			string key = token.Trim();
			if (key.Length < 20 || key.Contains('=') || key.StartsWith("PASTE_", StringComparison.OrdinalIgnoreCase))
				continue;
			bool validChars = true;
			foreach (char ch in key)
			{
				if (!(char.IsLetterOrDigit(ch) || ch == '_' || ch == '-' || ch == '.'))
				{
					validChars = false;
					break;
				}
			}
			if (validChars && unique.Add(key))
				keys.Add(key);
		}
		return keys;
	}

	private static bool IsGroqPool(string poolKind)
	{
		string kind = (poolKind ?? "").Trim().ToLowerInvariant();
		return kind == "groq" || kind == "openai" || kind == "openai_compatible" || kind == "compatible" || kind == "remote";
	}

	private static string KeyPoolKindFromProvider(string provider, string baseUrl)
	{
		string normalized = (provider ?? "").Trim().ToLowerInvariant();
		if (IsGroqPool(normalized))
			return "groq";
		string url = (baseUrl ?? "").Trim().ToLowerInvariant();
		return url.Contains("groq.com") || url.Contains("openai") || url.Contains("shopaikey") ? "groq" : "gemini";
	}

	private static JsonObject LoadSecretsRoot()
	{
		string path = GetSecretsPath();
		if (!File.Exists(path))
			return new JsonObject();
		JsonNode parsed = JsonNode.Parse(File.ReadAllText(path));
		return parsed as JsonObject ?? new JsonObject();
	}

	private static JsonObject EnsureObject(JsonObject root, string name)
	{
		if (root[name] is JsonObject obj)
			return obj;
		obj = new JsonObject();
		root[name] = obj;
		return obj;
	}

	private static bool TryReadBool(JsonElement root, string name, out bool value)
	{
		value = false;
		if (!root.TryGetProperty(name, out JsonElement item))
			return false;
		if (item.ValueKind == JsonValueKind.True || item.ValueKind == JsonValueKind.False)
		{
			value = item.GetBoolean();
			return true;
		}
		if (item.ValueKind == JsonValueKind.String)
		{
			value = IsTruthy(item.GetString() ?? "");
			return true;
		}
		return false;
	}

	private static string ReadString(JsonElement root, string name, string fallback)
	{
		return root.TryGetProperty(name, out JsonElement item) && item.ValueKind == JsonValueKind.String
			? item.GetString() ?? fallback
			: fallback;
	}

	private static string ReadSecretString(JsonElement root, string name, string fallback)
	{
		string direct = ReadString(root, name, "");
		if (!string.IsNullOrWhiteSpace(direct))
			return direct;
		foreach (string sectionName in new[] { "env", "api_keys", "secrets" })
		{
			if (root.TryGetProperty(sectionName, out JsonElement section) && section.ValueKind == JsonValueKind.Object)
			{
				string value = ReadString(section, name, "");
				if (!string.IsNullOrWhiteSpace(value))
					return value;
			}
		}
		return fallback;
	}

	private static bool IsTruthy(string value)
	{
		string v = (value ?? "").Trim().ToLowerInvariant();
		return v is "1" or "true" or "yes" or "on";
	}

	private static void SelectOptionText(OptionButton option, string value)
	{
		if (option == null)
			return;
		for (int i = 0; i < option.ItemCount; i++)
		{
			if (string.Equals(option.GetItemText(i), value, StringComparison.OrdinalIgnoreCase))
			{
				option.Select(i);
				return;
			}
		}
	}

	private static string SelectedOptionText(OptionButton option, string fallback)
	{
		return option != null && option.Selected >= 0 ? option.GetItemText(option.Selected) : fallback;
	}

	private static string GetRuntimeBaseDirForSettings()
	{
		if (OS.HasFeature("editor"))
			return ProjectSettings.GlobalizePath("res://");
		string exeDir = Path.GetDirectoryName(OS.GetExecutablePath());
		return string.IsNullOrWhiteSpace(exeDir) ? ProjectSettings.GlobalizePath("res://") : exeDir;
	}

	private static string GetSecretsPath()
	{
		return Path.Combine(GetRuntimeBaseDirForSettings(), "config", "secrets.json");
	}

	private static string GetSettingsBackupDir()
	{
		return Path.Combine(GetRuntimeBaseDirForSettings(), "backups", "settings");
	}
}
