using Godot;
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

public partial class UdpListener : Node2D
{
	private sealed class SettingsKeyHealth
	{
		public int Index { get; init; } = -1;
		public string Fingerprint { get; init; } = "";
		public string Status { get; init; } = "unknown";
		public string Reason { get; init; } = "";
		public int CooldownMs { get; init; }
		public bool Active { get; init; }
	}

	private Panel _settingsPanel;
	private Label _settingsBrainStatusLabel;
	private Label _settingsRuntimeDetailLabel;
	private Label _settingsRuntimeProviderSummaryLabel;
	private Label _settingsRuntimeModelSummaryLabel;
	private Button _settingsRuntimeStartButton;
	private Button _settingsRuntimeStopButton;
	private Button _settingsRuntimeRestartButton;
	private Control _settingsConnectionOverlay;
	private Label _settingsConnectionFeedbackLabel;
	private Button _settingsPoolStatusLabel;
	private Button _settingsFallbackStatusLabel;
	private Label _settingsPoolHealthLabel;
	private Label _settingsTtsEngineStatusLabel;
	private Label _settingsStatusNoteLabel;
	private TextureRect _settingsTtsSwitch;
	private TextureRect _settingsAutoStartSwitch;
	private TextureRect _settingsAutoRestartSwitch;
	private TextureRect _settingsAlwaysOnTopSwitch;
	private TextureRect _settingsTransparentSwitch;
	private TextureRect _settingsPassthroughSwitch;
	private TextureRect _settingsPositionLockSwitch;
	private OptionButton _settingsProviderSelect;
	private LineEdit _settingsModelInput;
	private LineEdit _settingsBaseUrlInput;
	private OptionButton _settingsVoiceSelect;
	private OptionButton _settingsLanguageSelect;
	private OptionButton _settingsQualitySelect;
	private HSlider _settingsTtsVolumeSlider;
	private HSlider _settingsTtsSpeedSlider;
	private Label _settingsTtsVolumeValueLabel;
	private Label _settingsTtsSpeedValueLabel;
	private FileDialog _settingsImportSecretsDialog;
	private VBoxContainer _settingsKeyRowsBox;
	private readonly List<LineEdit> _settingsKeyNameInputs = new();
	private readonly List<LineEdit> _settingsKeyInputs = new();
	private readonly List<Label> _settingsKeyStatusLabels = new();
	private readonly Dictionary<string, List<SettingsKeyHealth>> _settingsKeyHealth = new(StringComparer.OrdinalIgnoreCase);
	private readonly Dictionary<string, string> _settingsPoolHealthSummary = new(StringComparer.OrdinalIgnoreCase);

	// Giữ bản nháp riêng cho từng pool. Tên hiển thị không ghi vào secrets.json;
	// chúng được lưu an toàn trong user://eris_settings.json theo fingerprint của key.
	private readonly Dictionary<string, List<string>> _settingsKeyDrafts = new(StringComparer.OrdinalIgnoreCase);
	private readonly Dictionary<string, List<string>> _settingsKeyNameDrafts = new(StringComparer.OrdinalIgnoreCase);
	private readonly Dictionary<string, string> _settingsKeyAliases = new(StringComparer.OrdinalIgnoreCase);
	private bool _settingsSkipKeyDraftCaptureOnce;
	private string _settingsKeyPoolKind = "";
	private ulong _settingsNextRuntimeRefreshMs;
	private bool _settingsTtsEnabled = true;
	private string _settingsTtsVoice = "Aoede";
	private string _settingsTtsLanguage = "auto";
	private string _settingsTtsQuality = "high";
	private float _settingsTtsVolume = 1.00f;
	private float _settingsTtsSpeed = 1.00f;

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
		if (_processes != null && _processes.IsVisionRunning)
			TestSettingsPool();
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

		// Rebuild panel không được nuốt mất key người dùng đang gõ dở.
		if (_settingsSkipKeyDraftCaptureOnce)
			_settingsSkipKeyDraftCaptureOnce = false;
		else
			CaptureCurrentSettingsKeyDraft();

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
		ResetSettingsUiReferencesForRebuild();

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
		controls.Position = new Vector2(1040f, 34f);
		root.AddChild(controls);

		AddSettingsMainTabs(root);
		AddSettingsModeStrip(root);

		if (_settingsModePage == SettingsModePage.Advanced)
		{
			BuildAdvancedSettingsPage(root);
			RefreshSettingsPanel();
			return;
		}

		if (_settingsModePage == SettingsModePage.Danger)
		{
			BuildDangerSettingsPage(root);
			RefreshSettingsPanel();
			RequestMaintenanceCatalog();
			return;
		}

		var statusCard = AddSettingsCard(root, new Rect2(32f, 205f, 318f, 380f), "Runtime");
		BuildSettingsStatusColumn(statusCard);

		var poolCard = AddSettingsCard(root, new Rect2(370f, 205f, 420f, 380f), "Key pool");
		BuildSettingsKeyPoolColumn(poolCard);

		var displayCard = AddSettingsCard(root, new Rect2(810f, 205f, 338f, 380f), "Giọng & cửa sổ");
		BuildSettingsDisplayColumn(displayCard);

		var divider = new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.84f, 0.38f),
			Position = new Vector2(32f, 604f),
			Size = new Vector2(1116f, 1.4f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		root.AddChild(divider);

		var noteHeart = CreateUiLabel("♡", 24, SettingsPink);
		noteHeart.Position = new Vector2(72f, 624f);
		noteHeart.Size = new Vector2(32f, 30f);
		root.AddChild(noteHeart);

		var note = CreateUiLabel("Basic ghi config thật: user settings + config/secrets.json local.", 13, SettingsInkSoft);
		note.Position = new Vector2(112f, 630f);
		note.Size = new Vector2(420f, 24f);
		root.AddChild(note);

		_settingsStatusNoteLabel = CreateUiLabel("", 12, SettingsInk);
		_settingsStatusNoteLabel.Position = new Vector2(112f, 646f);
		_settingsStatusNoteLabel.Size = new Vector2(420f, 16f);
		_settingsStatusNoteLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_settingsStatusNoteLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_settingsStatusNoteLabel.AddThemeFontSizeOverride("font_size", 10);
		root.AddChild(_settingsStatusNoteLabel);

		var backup = CreateSettingsButton("Sao lưu", BackupSettingsAndSecrets, primary: false);
		backup.Position = new Vector2(668f, 622f);
		backup.Size = new Vector2(92f, 38f);
		root.AddChild(backup);

		var export = CreateSettingsButton("Xuất config", ExportSanitizedSettings, primary: false);
		export.Position = new Vector2(766f, 622f);
		export.Size = new Vector2(104f, 38f);
		root.AddChild(export);

		var cancel = CreateSettingsButton("Hủy", CloseSettingsPanel, primary: false);
		cancel.Position = new Vector2(876f, 622f);
		cancel.Size = new Vector2(70f, 38f);
		root.AddChild(cancel);

		var save = CreateSettingsButton("Lưu", SaveSettingsState, primary: true);
		save.Position = new Vector2(952f, 620f);
		save.Size = new Vector2(78f, 42f);
		root.AddChild(save);

		var saveRestart = CreateSettingsButton("Lưu & Restart", SaveSettingsAndRestart, primary: true);
		saveRestart.Position = new Vector2(1036f, 620f);
		saveRestart.Size = new Vector2(108f, 42f);
		saveRestart.AddThemeFontSizeOverride("font_size", 10);
		root.AddChild(saveRestart);

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

		BuildSettingsConnectionOverlay(root);
		RefreshSettingsPanel();
	}

	private void AddSettingsMainTabs(Control root)
	{
		AddSettingsTab(root, new Rect2(42f, 118f, 340f, 40f), "♡  Cơ bản", true);
		AddSettingsTab(root, new Rect2(420f, 118f, 340f, 40f), "♬  Giọng nói", false);
		AddSettingsTab(root, new Rect2(798f, 118f, 340f, 40f), "▤  Dữ liệu", false);
	}

	private void AddSettingsModeStrip(Control root)
	{
		var label = CreateUiLabel("Chế độ cấu hình", 13, SettingsInkSoft);
		label.Position = new Vector2(44f, 172f);
		label.Size = new Vector2(160f, 24f);
		root.AddChild(label);

		AddSettingsSmallTab(root, new Rect2(690f, 168f, 132f, 32f), "Cơ bản", _settingsModePage == SettingsModePage.Basic, () => SwitchSettingsMode(SettingsModePage.Basic));
		AddSettingsSmallTab(root, new Rect2(836f, 168f, 132f, 32f), "Advanced", _settingsModePage == SettingsModePage.Advanced, () => SwitchSettingsMode(SettingsModePage.Advanced));
		AddSettingsSmallTab(root, new Rect2(982f, 168f, 156f, 32f), "△ Danger Zone", _settingsModePage == SettingsModePage.Danger, () => SwitchSettingsMode(SettingsModePage.Danger));
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
		// Runtime chỉ điều khiển tiến trình. Cấu hình model/API được mở ở một editor riêng,
		// tránh bắt người dùng vừa nhìn PID vừa giải mã endpoint trong cùng một ô bé tí.
		_settingsBrainStatusLabel = CreateSettingsChip("Brain", true);
		_settingsBrainStatusLabel.Position = new Vector2(18f, 48f);
		_settingsBrainStatusLabel.Size = new Vector2(264f, 30f);
		parent.AddChild(_settingsBrainStatusLabel);

		_settingsRuntimeDetailLabel = CreateUiLabel("PID — · chưa chạy", 10, SettingsInkSoft);
		_settingsRuntimeDetailLabel.Position = new Vector2(20f, 80f);
		_settingsRuntimeDetailLabel.Size = new Vector2(260f, 20f);
		StyleSettingsSingleLineLabel(_settingsRuntimeDetailLabel);
		parent.AddChild(_settingsRuntimeDetailLabel);

		AddSettingsCompactToggle(parent, 104f, "Tự khởi động cùng Eris", AutoStartVision, ref _settingsAutoStartSwitch, () =>
		{
			AutoStartVision = !AutoStartVision;
			ApplySettingsSwitch(_settingsAutoStartSwitch, AutoStartVision);
			SetSettingsStatus(AutoStartVision
				? "Brain sẽ tự khởi động khi mở Eris."
				: "Đã tắt tự khởi động Brain khi mở Eris.");
		});
		AddSettingsCompactToggle(parent, 132f, "Tự phục hồi khi gặp lỗi", AutoRestartVisionOnCrash, ref _settingsAutoRestartSwitch, () =>
		{
			AutoRestartVisionOnCrash = !AutoRestartVisionOnCrash;
			ApplySettingsSwitch(_settingsAutoRestartSwitch, AutoRestartVisionOnCrash);
			SetSettingsStatus(AutoRestartVisionOnCrash
				? "Đã bật tự phục hồi Brain sau crash."
				: "Đã tắt tự phục hồi Brain sau crash.");
		});

		_settingsRuntimeStartButton = CreateSettingsButton("▶  Khởi động Brain", () =>
		{
			SyncSettingsInputsToFields();
			StartVisionProcess();
			SetSettingsStatus("Đang khởi động Brain...");
			RefreshSettingsRuntimeStatus();
		}, primary: true);
		_settingsRuntimeStartButton.Position = new Vector2(18f, 166f);
		_settingsRuntimeStartButton.Size = new Vector2(264f, 34f);
		parent.AddChild(_settingsRuntimeStartButton);

		_settingsRuntimeStopButton = CreateSettingsButton("■  Dừng", () =>
		{
			StopVisionProcess();
			SetSettingsStatus("Đã yêu cầu dừng Brain.");
			RefreshSettingsRuntimeStatus();
		}, primary: false);
		_settingsRuntimeStopButton.Position = new Vector2(18f, 166f);
		_settingsRuntimeStopButton.Size = new Vector2(104f, 34f);
		parent.AddChild(_settingsRuntimeStopButton);

		_settingsRuntimeRestartButton = CreateSettingsButton("↻  Khởi động lại", () =>
		{
			SyncSettingsInputsToFields();
			RestartVisionProcess();
			SetSettingsStatus("Đang khởi động lại Brain với cấu hình hiện tại...");
			RefreshSettingsRuntimeStatus();
		}, primary: true);
		_settingsRuntimeRestartButton.Position = new Vector2(128f, 166f);
		_settingsRuntimeRestartButton.Size = new Vector2(154f, 34f);
		parent.AddChild(_settingsRuntimeRestartButton);

		var divider = new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.84f, 0.42f),
			Position = new Vector2(18f, 202f),
			Size = new Vector2(264f, 1.2f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		parent.AddChild(divider);

		var modelTitle = CreateUiLabel("Model đang dùng", 10, SettingsInkSoft);
		modelTitle.Position = new Vector2(20f, 208f);
		modelTitle.Size = new Vector2(150f, 18f);
		StyleSettingsSingleLineLabel(modelTitle);
		parent.AddChild(modelTitle);

		var modelSummaryPanel = new Panel
		{
			Position = new Vector2(18f, 226f),
			Size = new Vector2(264f, 44f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		modelSummaryPanel.AddThemeStyleboxOverride("panel", SettingsCardStyle(
			new Color(1f, 0.98f, 0.99f, 0.66f), SettingsBorder, 12));
		parent.AddChild(modelSummaryPanel);

		_settingsRuntimeProviderSummaryLabel = CreateUiLabel("Provider: —", 9, SettingsInkSoft);
		_settingsRuntimeProviderSummaryLabel.Position = new Vector2(12f, 3f);
		_settingsRuntimeProviderSummaryLabel.Size = new Vector2(240f, 19f);
		StyleSettingsSingleLineLabel(_settingsRuntimeProviderSummaryLabel);
		modelSummaryPanel.AddChild(_settingsRuntimeProviderSummaryLabel);

		_settingsRuntimeModelSummaryLabel = CreateUiLabel("Model: —", 10, SettingsInk);
		_settingsRuntimeModelSummaryLabel.Position = new Vector2(12f, 22f);
		_settingsRuntimeModelSummaryLabel.Size = new Vector2(240f, 21f);
		_settingsRuntimeModelSummaryLabel.TooltipText = RemoteApiModelName ?? "";
		StyleSettingsSingleLineLabel(_settingsRuntimeModelSummaryLabel);
		modelSummaryPanel.AddChild(_settingsRuntimeModelSummaryLabel);

		var editModel = CreateSettingsButton("Model & kết nối", ShowSettingsConnectionEditor, primary: false);
		editModel.Position = new Vector2(18f, 278f);
		editModel.Size = new Vector2(264f, 28f);
		parent.AddChild(editModel);

		var test = CreateSettingsButton("Chẩn đoán", TestSettingsSystem, primary: false);
		test.Position = new Vector2(18f, 312f);
		test.Size = new Vector2(128f, 26f);
		parent.AddChild(test);

		var logs = CreateSettingsButton("Mở logs", OpenSettingsLogs, primary: false);
		logs.Position = new Vector2(154f, 312f);
		logs.Size = new Vector2(128f, 26f);
		parent.AddChild(logs);
	}


	private void BuildSettingsConnectionOverlay(Control root)
	{
		_settingsConnectionOverlay = new Control
		{
			Visible = false,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		_settingsConnectionOverlay.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.AddChild(_settingsConnectionOverlay);

		var dim = new ColorRect
		{
			Color = new Color(0.24f, 0.05f, 0.15f, 0.22f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		dim.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		dim.GuiInput += ev =>
		{
			if (ev is InputEventMouseButton mouse && mouse.ButtonIndex == MouseButton.Left && mouse.Pressed)
				HideSettingsConnectionEditor();
		};
		_settingsConnectionOverlay.AddChild(dim);

		var card = new Panel
		{
			Position = new Vector2(260f, 171f),
			Size = new Vector2(660f, 338f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		card.AddThemeStyleboxOverride("panel", SettingsCardStyle(
			new Color(1.00f, 0.97f, 0.985f, 0.985f),
			new Color(0.96f, 0.62f, 0.79f, 0.92f),
			20));
		_settingsConnectionOverlay.AddChild(card);

		var title = CreateUiLabel("Model & kết nối", 22, SettingsInk);
		title.Position = new Vector2(22f, 16f);
		title.Size = new Vector2(300f, 32f);
		card.AddChild(title);

		var close = CreateSettingsButton("×", HideSettingsConnectionEditor, primary: false);
		close.Position = new Vector2(608f, 14f);
		close.Size = new Vector2(34f, 30f);
		close.AddThemeFontSizeOverride("font_size", 16);
		card.AddChild(close);

		var hint = CreateUiLabel("Đổi provider/model ở đây. Runtime chỉ giữ các nút chạy, dừng và phục hồi.", 10, SettingsInkSoft);
		hint.Position = new Vector2(24f, 50f);
		hint.Size = new Vector2(590f, 22f);
		StyleSettingsSingleLineLabel(hint);
		card.AddChild(hint);

		_settingsProviderSelect = AddSettingsOptionRow(card, 80f, "Provider", new[] { "gemini", "groq", "openai_compatible" }, RemoteApiProvider);
		_settingsModelInput = AddSettingsLineEditRow(card, 124f, "Model", RemoteApiModelName);
		_settingsBaseUrlInput = AddSettingsLineEditRow(card, 168f, "Base URL", RemoteApiBaseUrl);

		_settingsProviderSelect.ItemSelected += _ =>
		{
			RemoteApiProvider = SelectedOptionText(_settingsProviderSelect, "gemini");
			ApplyProviderDefaults(RemoteApiProvider);
			RefreshSettingsProviderInputs();
			RefreshSettingsRuntimeModelSummary();
			SetSettingsConnectionStatus("Đã nạp preset provider. Bấm Áp dụng & Restart để Brain dùng cấu hình mới.");
		};
		_settingsModelInput.TextChanged += _ =>
		{
			SyncSettingsInputsToFields();
			RefreshSettingsRuntimeModelSummary();
			SetSettingsConnectionStatus("Model đã thay đổi, chưa áp dụng xuống Brain.");
		};
		_settingsBaseUrlInput.TextChanged += _ =>
		{
			SyncSettingsInputsToFields();
			RefreshSettingsRuntimeModelSummary();
			SetSettingsConnectionStatus("Base URL đã thay đổi, chưa áp dụng xuống Brain.");
		};

		var infoPanel = new Panel
		{
			Position = new Vector2(310f, 80f),
			Size = new Vector2(326f, 126f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		infoPanel.AddThemeStyleboxOverride("panel", SettingsCardStyle(
			new Color(1f, 0.985f, 0.995f, 0.82f), SettingsBorder, 14));
		card.AddChild(infoPanel);

		var infoTitle = CreateUiLabel("Trạng thái cấu hình", 12, SettingsInk);
		infoTitle.Position = new Vector2(14f, 10f);
		infoTitle.Size = new Vector2(250f, 22f);
		StyleSettingsSingleLineLabel(infoTitle);
		infoPanel.AddChild(infoTitle);

		_settingsConnectionFeedbackLabel = CreateUiLabel("Chưa có thay đổi.", 10, SettingsInkSoft);
		_settingsConnectionFeedbackLabel.Position = new Vector2(14f, 36f);
		_settingsConnectionFeedbackLabel.Size = new Vector2(298f, 72f);
		_settingsConnectionFeedbackLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_settingsConnectionFeedbackLabel.VerticalAlignment = VerticalAlignment.Top;
		infoPanel.AddChild(_settingsConnectionFeedbackLabel);

		var test = CreateSettingsButton("Kiểm tra cấu hình", TestSettingsConnectionEditor, primary: false);
		test.Position = new Vector2(310f, 216f);
		test.Size = new Vector2(156f, 32f);
		card.AddChild(test);

		var logs = CreateSettingsButton("Mở logs", OpenSettingsLogs, primary: false);
		logs.Position = new Vector2(474f, 216f);
		logs.Size = new Vector2(162f, 32f);
		card.AddChild(logs);

		var cancel = CreateSettingsButton("Đóng", HideSettingsConnectionEditor, primary: false);
		cancel.Position = new Vector2(310f, 274f);
		cancel.Size = new Vector2(92f, 36f);
		card.AddChild(cancel);

		var save = CreateSettingsButton("Lưu", () =>
		{
			SaveSettingsState(false, writeSecrets: true);
			RefreshSettingsRuntimeModelSummary();
			SetSettingsConnectionStatus("Đã lưu cấu hình. Brain đang chạy vẫn dùng cấu hình cũ cho tới khi restart.");
		}, primary: false);
		save.Position = new Vector2(410f, 274f);
		save.Size = new Vector2(86f, 36f);
		card.AddChild(save);

		var apply = CreateSettingsButton("Áp dụng & Restart", () =>
		{
			SaveSettingsState(false, writeSecrets: true);
			RestartVisionProcess();
			RefreshSettingsRuntimeModelSummary();
			HideSettingsConnectionEditor();
			SetSettingsStatus("Đã lưu model/kết nối và khởi động lại Brain.");
		}, primary: true);
		apply.Position = new Vector2(504f, 272f);
		apply.Size = new Vector2(132f, 40f);
		apply.AddThemeFontSizeOverride("font_size", 10);
		card.AddChild(apply);
	}

	private void ShowSettingsConnectionEditor()
	{
		if (_settingsConnectionOverlay == null)
			return;
		RefreshSettingsProviderInputs();
		SetSettingsConnectionStatus(_processes != null && _processes.IsVisionRunning
			? "Brain đang chạy. Thay đổi provider/model cần Restart để áp dụng."
			: "Brain đang dừng. Lưu cấu hình rồi khởi động khi sẵn sàng.");
		_settingsConnectionOverlay.Visible = true;
		_settingsConnectionOverlay.MoveToFront();
	}

	private void HideSettingsConnectionEditor()
	{
		if (_settingsConnectionOverlay != null)
			_settingsConnectionOverlay.Visible = false;
	}

	private void SetSettingsConnectionStatus(string text)
	{
		if (_settingsConnectionFeedbackLabel != null)
			_settingsConnectionFeedbackLabel.Text = text ?? "";
	}

	private void TestSettingsConnectionEditor()
	{
		SyncSettingsInputsToFields();
		var problems = new List<string>();
		if (string.IsNullOrWhiteSpace(RemoteApiProvider))
			problems.Add("thiếu provider");
		if (string.IsNullOrWhiteSpace(RemoteApiModelName))
			problems.Add("thiếu model");
		if (!string.Equals(RemoteApiProvider, "gemini", StringComparison.OrdinalIgnoreCase)
			&& string.IsNullOrWhiteSpace(RemoteApiBaseUrl))
			problems.Add("thiếu Base URL");

		string pool = KeyPoolKindFromProvider(RemoteApiProvider, RemoteApiBaseUrl);
		int keys = IsGroqPool(pool) ? CountConfiguredGroqKeys() : CountConfiguredGeminiKeys();
		if (keys <= 0)
			problems.Add($"pool {pool} chưa có key");

		if (problems.Count > 0)
		{
			SetSettingsConnectionStatus("Chưa ổn: " + string.Join(", ", problems) + ".");
			return;
		}

		string runtime = _processes != null && _processes.IsVisionRunning
			? $"Brain đang chạy PID {_processes.VisionProcessId}."
			: "Brain đang dừng.";
		SetSettingsConnectionStatus($"Cấu hình hợp lệ cục bộ: {DisplaySettingsProviderName(RemoteApiProvider)}, {RemoteApiModelName}, {keys} key. {runtime}");
	}

	private static string DisplaySettingsProviderName(string provider)
	{
		string normalized = (provider ?? "").Trim().ToLowerInvariant();
		return normalized switch
		{
			"gemini" => "Gemini",
			"groq" => "Groq",
			"openai_compatible" => "OpenAI-compatible",
			_ => string.IsNullOrWhiteSpace(provider) ? "Chưa chọn" : provider,
		};
	}


	private void BuildSettingsKeyPoolColumn(Control parent)
	{
		if (string.IsNullOrWhiteSpace(_settingsKeyPoolKind))
			_settingsKeyPoolKind = KeyPoolKindFromProvider(RemoteApiProvider, RemoteApiBaseUrl);
		else
			_settingsKeyPoolKind = NormalizeSettingsPoolKind(_settingsKeyPoolKind);

		int geminiCount = _settingsKeyDrafts.TryGetValue("gemini", out List<string> geminiRows)
			? NormalizeSettingsKeyRows(geminiRows).Count
			: ReadEditableKeysForPool("gemini").Count;
		int groqCount = _settingsKeyDrafts.TryGetValue("groq", out List<string> groqRows)
			? NormalizeSettingsKeyRows(groqRows).Count
			: ReadEditableKeysForPool("groq").Count;

		_settingsPoolStatusLabel = CreateSettingsButton($"Gemini · {geminiCount}", () => SwitchSettingsKeyPool("gemini"), primary: _settingsKeyPoolKind == "gemini");
		_settingsPoolStatusLabel.Position = new Vector2(18f, 46f);
		_settingsPoolStatusLabel.Size = new Vector2(184f, 30f);
		_settingsPoolStatusLabel.TooltipText = "Chỉnh pool key Gemini";
		parent.AddChild(_settingsPoolStatusLabel);

		_settingsFallbackStatusLabel = CreateSettingsButton($"Groq · {groqCount}", () => SwitchSettingsKeyPool("groq"), primary: _settingsKeyPoolKind == "groq");
		_settingsFallbackStatusLabel.Position = new Vector2(218f, 46f);
		_settingsFallbackStatusLabel.Size = new Vector2(184f, 30f);
		_settingsFallbackStatusLabel.TooltipText = "Chỉnh pool key Groq / OpenAI-compatible";
		parent.AddChild(_settingsFallbackStatusLabel);

		_settingsPoolHealthLabel = CreateUiLabel("Chưa đọc trạng thái runtime", 10, SettingsInkSoft);
		_settingsPoolHealthLabel.Position = new Vector2(20f, 78f);
		_settingsPoolHealthLabel.Size = new Vector2(382f, 18f);
		StyleSettingsSingleLineLabel(_settingsPoolHealthLabel);
		parent.AddChild(_settingsPoolHealthLabel);

		var nameHeader = CreateUiLabel("Tên key", 9, SettingsInkSoft);
		nameHeader.Position = new Vector2(28f, 97f);
		nameHeader.Size = new Vector2(130f, 16f);
		StyleSettingsSingleLineLabel(nameHeader);
		parent.AddChild(nameHeader);

		var keyHeader = CreateUiLabel("API key", 9, SettingsInkSoft);
		keyHeader.Position = new Vector2(172f, 97f);
		keyHeader.Size = new Vector2(120f, 16f);
		StyleSettingsSingleLineLabel(keyHeader);
		parent.AddChild(keyHeader);

		var actionHeader = CreateUiLabel("Ưu tiên / xóa", 9, SettingsInkSoft);
		actionHeader.Position = new Vector2(300f, 97f);
		actionHeader.Size = new Vector2(100f, 16f);
		StyleSettingsSingleLineLabel(actionHeader, HorizontalAlignment.Right);
		parent.AddChild(actionHeader);

		var list = new Panel
		{
			Position = new Vector2(18f, 116f),
			Size = new Vector2(384f, 194f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		list.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.72f), SettingsBorder, 14));
		parent.AddChild(list);

		_settingsKeyNameInputs.Clear();
		_settingsKeyInputs.Clear();
		_settingsKeyStatusLabels.Clear();
		var scroller = new ScrollContainer
		{
			Position = new Vector2(6f, 6f),
			Size = new Vector2(372f, 182f),
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
		_settingsKeyRowsBox.AddThemeConstantOverride("separation", 6);
		scroller.AddChild(_settingsKeyRowsBox);

		var keys = ReadSettingsKeysForEditor(_settingsKeyPoolKind);
		var names = ReadSettingsKeyNamesForEditor(_settingsKeyPoolKind, keys);
		for (int i = 0; i < keys.Count; i++)
			AddSettingsEditableKeyRow(keys[i], i < names.Count ? names[i] : "");

		if (keys.Count == 0)
			AddSettingsEditableKeyRow("", DefaultSettingsKeyName(_settingsKeyPoolKind, 1));

		var add = CreateSettingsButton("＋ Thêm key", () =>
		{
			int next = _settingsKeyInputs.Count + 1;
			AddSettingsEditableKeyRow("", DefaultSettingsKeyName(_settingsKeyPoolKind, next));
			if (_settingsKeyNameInputs.Count > 0)
			{
				LineEdit newestName = _settingsKeyNameInputs[_settingsKeyNameInputs.Count - 1];
				newestName.GrabFocus();
				newestName.SelectAll();
			}
			CaptureCurrentSettingsKeyDraft();
			RefreshSettingsPoolSelectorCounts();
			SetSettingsStatus("Đã thêm một dòng đầy đủ. Điền Tên key và API key rồi bấm Lưu & Restart.");
		}, primary: true);
		add.Position = new Vector2(18f, 318f);
		add.Size = new Vector2(124f, 30f);
		parent.AddChild(add);

		var import = CreateSettingsButton("Nhập tệp…", OpenImportSecretsDialog, primary: false);
		import.Position = new Vector2(150f, 318f);
		import.Size = new Vector2(112f, 30f);
		import.TooltipText = "Nhập secrets.json; file cũ sẽ được sao lưu";
		parent.AddChild(import);

		var reload = CreateSettingsButton("↻ Đọc lại", () =>
		{
			_settingsKeyDrafts.Remove(_settingsKeyPoolKind);
			_settingsKeyNameDrafts.Remove(_settingsKeyPoolKind);
			_settingsSkipKeyDraftCaptureOnce = true;
			BuildSettingsPanelUi();
			SetSettingsStatus($"Đã bỏ bản nháp và đọc lại pool {_settingsKeyPoolKind} từ secrets.");
		}, primary: false);
		reload.Position = new Vector2(270f, 318f);
		reload.Size = new Vector2(132f, 30f);
		reload.TooltipText = "Bỏ thay đổi chưa lưu của pool đang mở";
		parent.AddChild(reload);

		var test = CreateSettingsButton("Kiểm tra trạng thái key", TestSettingsPool, primary: false);
		test.Position = new Vector2(18f, 354f);
		test.Size = new Vector2(384f, 26f);
		test.TooltipText = "Đọc key đang dùng, key sẵn sàng và cooldown từ Brain";
		parent.AddChild(test);

		RefreshSettingsKeyRowHealthIndicators();
	}

	private void SwitchSettingsKeyPool(string requestedKind)
	{
		string next = NormalizeSettingsPoolKind(requestedKind);
		if (next == _settingsKeyPoolKind)
			return;

		CaptureCurrentSettingsKeyDraft();
		_settingsKeyPoolKind = next;
		_settingsSkipKeyDraftCaptureOnce = true;
		BuildSettingsPanelUi();
		SetSettingsStatus($"Đang chỉnh pool {DisplaySettingsPoolName(next)}. Bản nháp pool trước vẫn được giữ.");
	}

	private static string NormalizeSettingsPoolKind(string poolKind)
	{
		return IsGroqPool(poolKind) ? "groq" : "gemini";
	}

	private static string DisplaySettingsPoolName(string poolKind)
	{
		return NormalizeSettingsPoolKind(poolKind) == "groq" ? "Groq" : "Gemini";
	}

	private void CaptureCurrentSettingsKeyDraft()
	{
		if (_settingsKeyInputs.Count == 0 || string.IsNullOrWhiteSpace(_settingsKeyPoolKind))
			return;

		var rows = new List<string>();
		var names = new List<string>();
		for (int i = 0; i < _settingsKeyInputs.Count; i++)
		{
			LineEdit input = _settingsKeyInputs[i];
			LineEdit nameInput = i < _settingsKeyNameInputs.Count ? _settingsKeyNameInputs[i] : null;
			rows.Add(input != null && IsInstanceValid(input) ? input.Text ?? "" : "");
			names.Add(nameInput != null && IsInstanceValid(nameInput) ? nameInput.Text ?? "" : "");
		}

		string kind = NormalizeSettingsPoolKind(_settingsKeyPoolKind);
		_settingsKeyDrafts[kind] = rows;
		_settingsKeyNameDrafts[kind] = names;
	}

	private List<string> ReadSettingsKeysForEditor(string poolKind)
	{
		string kind = NormalizeSettingsPoolKind(poolKind);
		if (_settingsKeyDrafts.TryGetValue(kind, out List<string> draft))
			return new List<string>(draft);

		var loaded = ReadEditableKeysForPool(kind);
		_settingsKeyDrafts[kind] = new List<string>(loaded);
		return loaded;
	}

	private List<string> ReadSettingsKeyNamesForEditor(string poolKind, List<string> keys)
	{
		string kind = NormalizeSettingsPoolKind(poolKind);
		if (_settingsKeyNameDrafts.TryGetValue(kind, out List<string> draft))
		{
			var copy = new List<string>(draft);
			while (copy.Count < keys.Count)
				copy.Add(DefaultSettingsKeyName(kind, copy.Count + 1));
			return copy;
		}

		var names = new List<string>();
		for (int i = 0; i < keys.Count; i++)
		{
			string fingerprint = SettingsKeyFingerprint(keys[i]);
			string aliasKey = SettingsKeyAliasMapKey(kind, fingerprint);
			string fallback = DefaultSettingsKeyName(kind, i + 1);
			names.Add(!string.IsNullOrWhiteSpace(fingerprint) && _settingsKeyAliases.TryGetValue(aliasKey, out string alias) && !string.IsNullOrWhiteSpace(alias)
				? alias.Trim()
				: fallback);
		}
		_settingsKeyNameDrafts[kind] = new List<string>(names);
		return names;
	}

	private static string DefaultSettingsKeyName(string poolKind, int rowNumber)
	{
		string provider = NormalizeSettingsPoolKind(poolKind) == "groq" ? "Groq" : "Gemini";
		return $"{provider} {Math.Max(1, rowNumber):00}";
	}

	private static string SettingsKeyAliasMapKey(string poolKind, string fingerprint)
	{
		return $"{NormalizeSettingsPoolKind(poolKind)}:{(fingerprint ?? "").Trim().ToLowerInvariant()}";
	}

	private void RefreshSettingsPoolSelectorCounts()
	{
		int gemini = _settingsKeyDrafts.TryGetValue("gemini", out List<string> geminiRows)
			? NormalizeSettingsKeyRows(geminiRows).Count
			: ReadEditableKeysForPool("gemini").Count;
		int groq = _settingsKeyDrafts.TryGetValue("groq", out List<string> groqRows)
			? NormalizeSettingsKeyRows(groqRows).Count
			: ReadEditableKeysForPool("groq").Count;

		if (_settingsPoolStatusLabel != null)
			_settingsPoolStatusLabel.Text = $"Gemini · {gemini}";
		if (_settingsFallbackStatusLabel != null)
			_settingsFallbackStatusLabel.Text = $"Groq · {groq}";
	}


	private void BuildSettingsDisplayColumn(Control parent)
	{
		_settingsTtsSwitch = AddSettingsSwitch(parent, new Vector2(234f, 44f), _settingsTtsEnabled, () =>
		{
			_settingsTtsEnabled = !_settingsTtsEnabled;
			ApplySettingsSwitch(_settingsTtsSwitch, _settingsTtsEnabled);
			SendTtsRuntimeSettingsUpdate();
			SetSettingsStatus(_settingsTtsEnabled ? "Đã bật TTS." : "Đã tắt TTS.");
		});
		var tts = CreateUiLabel("Bật TTS", 14, SettingsInk);
		tts.Position = new Vector2(18f, 50f);
		tts.Size = new Vector2(160f, 24f);
		parent.AddChild(tts);

		_settingsVoiceSelect = AddSettingsOptionRow(parent, 78f, "Giọng", new[] { "Aoede", "Leda", "Achernar", "Kore", "Callirrhoe" }, _settingsTtsVoice);
		_settingsLanguageSelect = AddSettingsOptionRow(parent, 118f, "Ngôn ngữ", new[] { "auto", "vi", "ja", "en" }, _settingsTtsLanguage);
		_settingsQualitySelect = AddSettingsOptionRow(parent, 158f, "Chất lượng", new[] { "balanced", "high" }, _settingsTtsQuality);
		_settingsVoiceSelect.ItemSelected += _ => ApplyLiveTtsSettingsFromPanel("giọng");
		_settingsLanguageSelect.ItemSelected += _ => ApplyLiveTtsSettingsFromPanel("ngôn ngữ");
		_settingsQualitySelect.ItemSelected += _ => ApplyLiveTtsSettingsFromPanel("chất lượng");

		var preview = CreateSettingsButton("▶ Nghe thử", RequestTtsPreview, primary: false);
		preview.Position = new Vector2(18f, 198f);
		preview.Size = new Vector2(98f, 28f);
		parent.AddChild(preview);
		_settingsTtsEngineStatusLabel = CreateUiLabel("Engine: chưa kiểm tra", 9, SettingsInkSoft);
		_settingsTtsEngineStatusLabel.Position = new Vector2(124f, 201f);
		_settingsTtsEngineStatusLabel.Size = new Vector2(158f, 22f);
		StyleSettingsSingleLineLabel(_settingsTtsEngineStatusLabel);
		parent.AddChild(_settingsTtsEngineStatusLabel);

		_settingsTtsVolumeSlider = AddSettingsSliderRow(parent, 228f, "Âm lượng", 0d, 100d, 1d, _settingsTtsVolume * 100d,
			v => $"{Mathf.RoundToInt((float)v)}%", out _settingsTtsVolumeValueLabel);
		_settingsTtsVolumeSlider.ValueChanged += value =>
		{
			_settingsTtsVolume = Mathf.Clamp((float)value / 100f, 0f, 1f);
			_settingsTtsVolumeValueLabel.Text = $"{Mathf.RoundToInt(_settingsTtsVolume * 100f)}%";
			SendTtsRuntimeSettingsUpdate();
		};

		_settingsTtsSpeedSlider = AddSettingsSliderRow(parent, 256f, "Tốc độ", 0.85d, 1.15d, 0.05d, _settingsTtsSpeed,
			v => $"{v:0.00}×", out _settingsTtsSpeedValueLabel);
		_settingsTtsSpeedSlider.ValueChanged += value =>
		{
			_settingsTtsSpeed = Mathf.Clamp((float)value, 0.85f, 1.15f);
			_settingsTtsSpeedValueLabel.Text = $"{_settingsTtsSpeed:0.00}×";
			SendTtsRuntimeSettingsUpdate();
		};

		var line = new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.84f, 0.45f),
			Position = new Vector2(18f, 286f),
			Size = new Vector2(264f, 1.2f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		parent.AddChild(line);

		AddSettingsMiniToggle(parent, new Vector2(18f, 294f), "Luôn nổi", KeepWindowAlwaysOnTop, ref _settingsAlwaysOnTopSwitch, () =>
		{
			KeepWindowAlwaysOnTop = !KeepWindowAlwaysOnTop;
			ApplySettingsSwitch(_settingsAlwaysOnTopSwitch, KeepWindowAlwaysOnTop);
			ConfigureDesktopOverlayWindow();
		});
		AddSettingsMiniToggle(parent, new Vector2(150f, 294f), "Trong suốt", UseTransparentWindow, ref _settingsTransparentSwitch, () =>
		{
			UseTransparentWindow = !UseTransparentWindow;
			ApplySettingsSwitch(_settingsTransparentSwitch, UseTransparentWindow);
			ConfigureDesktopOverlayWindow();
		});
		AddSettingsMiniToggle(parent, new Vector2(18f, 318f), "Click xuyên", EnableMousePassthrough, ref _settingsPassthroughSwitch, () =>
		{
			EnableMousePassthrough = !EnableMousePassthrough;
			ApplySettingsSwitch(_settingsPassthroughSwitch, EnableMousePassthrough);
			ConfigureDesktopOverlayWindow();
		});
		AddSettingsMiniToggle(parent, new Vector2(150f, 318f), "Khóa vị trí", LockCharacterPosition, ref _settingsPositionLockSwitch, () =>
		{
			LockCharacterPosition = !LockCharacterPosition;
			ApplySettingsSwitch(_settingsPositionLockSwitch, LockCharacterPosition);
			if (LockCharacterPosition)
				CancelGrabMode();
		});
	}


	private void AddSettingsCompactToggle(Control parent, float y, string label, bool initial, ref TextureRect target, Action onToggle)
	{
		var lbl = CreateUiLabel(label, 10, SettingsInk);
		lbl.Position = new Vector2(18f, y + 1f);
		lbl.Size = new Vector2(178f, 22f);
		StyleSettingsSingleLineLabel(lbl);
		parent.AddChild(lbl);
		target = AddSettingsSwitch(parent, new Vector2(238f, y - 2f), initial, onToggle);
		target.Size = new Vector2(44f, 26f);
		target.CustomMinimumSize = target.Size;
	}

	private void AddSettingsMiniToggle(Control parent, Vector2 pos, string label, bool initial, ref TextureRect target, Action onToggle)
	{
		var lbl = CreateUiLabel(label, 9, SettingsInk);
		lbl.Position = pos;
		lbl.Size = new Vector2(82f, 20f);
		StyleSettingsSingleLineLabel(lbl);
		parent.AddChild(lbl);
		target = AddSettingsSwitch(parent, pos + new Vector2(88f, -2f), initial, onToggle);
		target.Size = new Vector2(38f, 22f);
		target.CustomMinimumSize = target.Size;
	}

	private HSlider AddSettingsSliderRow(
		Control parent, float y, string label, double min, double max, double step, double value,
		Func<double, string> formatter, out Label valueLabel)
	{
		var title = CreateUiLabel(label, 9, SettingsInk);
		title.Position = new Vector2(18f, y + 1f);
		title.Size = new Vector2(62f, 22f);
		StyleSettingsSingleLineLabel(title);
		parent.AddChild(title);

		var slider = new HSlider
		{
			Position = new Vector2(78f, y),
			Size = new Vector2(142f, 24f),
			MinValue = min,
			MaxValue = max,
			Step = step,
			Value = value,
			MouseFilter = Control.MouseFilterEnum.Stop,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		parent.AddChild(slider);

		valueLabel = CreateUiLabel(formatter(value), 9, SettingsInkSoft);
		valueLabel.Position = new Vector2(224f, y + 1f);
		valueLabel.Size = new Vector2(58f, 22f);
		StyleSettingsSingleLineLabel(valueLabel, HorizontalAlignment.Right);
		parent.AddChild(valueLabel);
		return slider;
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

	private void AddSettingsEditableKeyRow(string value, string displayName = "")
	{
		if (_settingsKeyRowsBox == null)
			return;

		int rowNumber = _settingsKeyInputs.Count + 1;
		var row = new Panel
		{
			CustomMinimumSize = new Vector2(356f, 68f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.58f), new Color(0.96f, 0.76f, 0.86f, 0.45f), 10));
		_settingsKeyRowsBox.AddChild(row);

		var statusLabel = CreateUiLabel($"○ Chưa lưu · Ưu tiên {rowNumber}", 8, new Color(0.56f, 0.50f, 0.54f));
		statusLabel.Position = new Vector2(8f, 2f);
		statusLabel.Size = new Vector2(226f, 18f);
		statusLabel.TooltipText = "Chưa có trạng thái runtime";
		StyleSettingsSingleLineLabel(statusLabel);
		row.AddChild(statusLabel);
		_settingsKeyStatusLabels.Add(statusLabel);

		var nameInput = new LineEdit
		{
			Text = string.IsNullOrWhiteSpace(displayName) ? DefaultSettingsKeyName(_settingsKeyPoolKind, rowNumber) : displayName.Trim(),
			PlaceholderText = "Tên key",
			Position = new Vector2(8f, 28f),
			Size = new Vector2(138f, 28f),
			Flat = false,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		nameInput.AddThemeFontSizeOverride("font_size", 9);
		nameInput.AddThemeColorOverride("font_color", SettingsInk);
		nameInput.AddThemeColorOverride("font_placeholder_color", SettingsInkSoft);
		nameInput.TooltipText = "Tên riêng để phân biệt key, ví dụ: Gemini chính, Groq dự phòng";
		nameInput.TextChanged += _ =>
		{
			CaptureCurrentSettingsKeyDraft();
			RefreshSettingsKeyRowHealthIndicators();
			SetSettingsStatus("Đã sửa tên key. Tên chỉ lưu cục bộ, không gửi xuống provider.");
		};
		row.AddChild(nameInput);
		_settingsKeyNameInputs.Add(nameInput);

		var input = new LineEdit
		{
			Text = value ?? "",
			PlaceholderText = "API key",
			Position = new Vector2(152f, 28f),
			Size = new Vector2(144f, 28f),
			Flat = false,
			Secret = true,
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		input.AddThemeFontSizeOverride("font_size", 9);
		input.AddThemeColorOverride("font_color", SettingsInk);
		input.AddThemeColorOverride("font_placeholder_color", SettingsInkSoft);
		UpdateSettingsKeyInputTooltip(input, value);
		input.TextChanged += text =>
		{
			UpdateSettingsKeyInputTooltip(input, text);
			CaptureCurrentSettingsKeyDraft();
			RefreshSettingsPoolSelectorCounts();
			RefreshSettingsKeyRowHealthIndicators();
			SetSettingsStatus($"Đã sửa pool {DisplaySettingsPoolName(_settingsKeyPoolKind)}. Bấm Lưu & Restart để áp dụng.");
		};
		row.AddChild(input);
		_settingsKeyInputs.Add(input);

		var moveUp = CreateSettingsCompactButton("↑", () => MoveSettingsKeyRow(input, row, -1), 10);
		moveUp.TooltipText = "Tăng ưu tiên key";
		moveUp.Position = new Vector2(244f, 2f);
		moveUp.Size = new Vector2(24f, 18f);
		row.AddChild(moveUp);

		var moveDown = CreateSettingsCompactButton("↓", () => MoveSettingsKeyRow(input, row, 1), 10);
		moveDown.TooltipText = "Giảm ưu tiên key";
		moveDown.Position = new Vector2(272f, 2f);
		moveDown.Size = new Vector2(24f, 18f);
		row.AddChild(moveDown);

		Button reveal = null;
		reveal = CreateSettingsCompactButton("Hiện", () =>
		{
			input.Secret = !input.Secret;
			reveal.Text = input.Secret ? "Hiện" : "Ẩn";
			SetSettingsStatus(input.Secret ? "Đã ẩn API key." : "Đang hiện API key; đừng chia sẻ màn hình lúc này.");
		}, 8);
		reveal.TooltipText = "Hiện/ẩn API key";
		reveal.Position = new Vector2(302f, 28f);
		reveal.Size = new Vector2(54f, 28f);
		row.AddChild(reveal);

		var remove = CreateSettingsCompactButton("×", () =>
		{
			_settingsKeyNameInputs.Remove(nameInput);
			_settingsKeyInputs.Remove(input);
			_settingsKeyStatusLabels.Remove(statusLabel);
			row.QueueFree();
			CaptureCurrentSettingsKeyDraft();
			RefreshSettingsPoolSelectorCounts();
			RefreshSettingsKeyRowHealthIndicators();
			SetSettingsStatus("Đã bỏ key khỏi bản nháp. Bấm Lưu để ghi thay đổi vào secrets.");
		}, 11);
		remove.TooltipText = "Xóa key này";
		remove.Position = new Vector2(332f, 2f);
		remove.Size = new Vector2(24f, 18f);
		row.AddChild(remove);

		RefreshSettingsKeyRowHealthIndicators();
	}

	private void MoveSettingsKeyRow(LineEdit input, Panel row, int delta)
	{
		if (input == null || row == null || _settingsKeyRowsBox == null)
			return;
		int index = _settingsKeyInputs.IndexOf(input);
		int target = index + delta;
		if (index < 0 || target < 0 || target >= _settingsKeyInputs.Count)
		{
			SetSettingsStatus(delta < 0 ? "Key này đã ở ưu tiên cao nhất." : "Key này đã ở cuối danh sách fallback.");
			return;
		}

		LineEdit inputSwap = _settingsKeyInputs[target];
		_settingsKeyInputs[target] = _settingsKeyInputs[index];
		_settingsKeyInputs[index] = inputSwap;
		LineEdit nameSwap = _settingsKeyNameInputs[target];
		_settingsKeyNameInputs[target] = _settingsKeyNameInputs[index];
		_settingsKeyNameInputs[index] = nameSwap;
		Label statusSwap = _settingsKeyStatusLabels[target];
		_settingsKeyStatusLabels[target] = _settingsKeyStatusLabels[index];
		_settingsKeyStatusLabels[index] = statusSwap;
		_settingsKeyRowsBox.MoveChild(row, target);

		CaptureCurrentSettingsKeyDraft();
		RefreshSettingsKeyRowHealthIndicators();
		SetSettingsStatus($"Đã đổi thứ tự ưu tiên key trong pool {DisplaySettingsPoolName(_settingsKeyPoolKind)}.");
	}

	private static void UpdateSettingsKeyInputTooltip(LineEdit input, string rawValue)
	{
		if (input == null)
			return;
		string value = (rawValue ?? "").Trim();
		string tail = value.Length == 0 ? "trống" : value.Length <= 6 ? value : value.Substring(value.Length - 6);
		input.TooltipText = value.Length == 0 ? "Dòng key trống" : $"API key kết thúc bằng …{tail}";
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

	private void AddSettingsSmallTab(Control parent, Rect2 rect, string text, bool active, Action customAction = null)
	{
		var btn = CreateSettingsButton(text, customAction ?? (() => SetSettingsStatus(SettingsTabHint(text, active))), primary: active);
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

	private Button CreateSettingsCompactButton(string text, Action onPressed, int fontSize = 9)
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
			BgColor = new Color(1f, 0.97f, 0.985f, 0.76f),
			BorderColor = SettingsBorder,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 8,
			CornerRadiusTopRight = 8,
			CornerRadiusBottomLeft = 8,
			CornerRadiusBottomRight = 8,
			ContentMarginLeft = 2f,
			ContentMarginRight = 2f,
			ContentMarginTop = 1f,
			ContentMarginBottom = 1f,
		};
		var hover = (StyleBoxFlat)normal.Duplicate();
		hover.BgColor = new Color(1f, 0.92f, 0.96f, 0.90f);
		var pressed = (StyleBoxFlat)hover.Duplicate();
		pressed.BgColor = new Color(0.99f, 0.86f, 0.92f, 0.94f);
		btn.AddThemeStyleboxOverride("normal", normal);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", pressed);
		btn.AddThemeStyleboxOverride("focus", hover);
		btn.AddThemeColorOverride("font_color", SettingsInk);
		btn.AddThemeColorOverride("font_hover_color", SettingsPink);
		btn.AddThemeFontSizeOverride("font_size", fontSize);
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

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return;

			if (TryReadBool(root, "tts_enabled", out bool tts))
				_settingsTtsEnabled = tts;
			if (TryReadBool(root, "auto_start_brain", out bool autoStart))
				AutoStartVision = autoStart;
			if (TryReadBool(root, "auto_restart_brain", out bool autoRestart))
				AutoRestartVisionOnCrash = autoRestart;
			if (TryReadBool(root, "lock_character_position", out bool lockPosition))
				LockCharacterPosition = lockPosition;
			if (TryReadFloat(root, "tts_volume", out float ttsVolume))
				_settingsTtsVolume = Mathf.Clamp(ttsVolume, 0f, 1f);
			if (TryReadFloat(root, "tts_speed", out float ttsSpeed))
				_settingsTtsSpeed = Mathf.Clamp(ttsSpeed, 0.85f, 1.15f);
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
			LoadSettingsKeyAliases(root);
			LoadAdvancedSettingsState(root);
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
			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
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
			if (float.TryParse(ReadSecretString(root, "ERIS_TTS_VOLUME", _settingsTtsVolume.ToString(System.Globalization.CultureInfo.InvariantCulture)), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float volume))
				_settingsTtsVolume = Mathf.Clamp(volume, 0f, 1f);
			if (float.TryParse(ReadSecretString(root, "ERIS_TTS_SPEED", _settingsTtsSpeed.ToString(System.Globalization.CultureInfo.InvariantCulture)), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float speed))
				_settingsTtsSpeed = Mathf.Clamp(speed, 0.85f, 1.15f);
			LoadAdvancedSettingsFromSecrets(root);
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

	private void SaveSettingsAndRestart()
	{
		SaveSettingsState(false, writeSecrets: true);
		RestartVisionProcess();
		SetSettingsStatus("Đã lưu cấu hình và restart Brain.");
	}

	private void SaveSettingsState(bool showStatus, bool writeSecrets)
	{
		SyncSettingsInputsToFields();
		SyncAdvancedSettingsInputsToFields();
		CaptureCurrentSettingsKeyDraft();
		try
		{
			string path = ProjectSettings.GlobalizePath(SettingsStatePath);
			string dir = Path.GetDirectoryName(path);
			if (!string.IsNullOrWhiteSpace(dir))
				Directory.CreateDirectory(dir);

			var state = BuildSanitizedSettingsNode();
			state["saved_at"] = DateTime.Now.ToString("O");
			File.WriteAllText(path, state.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
			// Ghi schema runtime riêng để Brain khởi động lại vẫn dùng đúng settings,
			// không phải bói lại từ một rừng env key.
			PersistRuntimeSettingsJson();
			if (writeSecrets)
			{
				WriteRuntimeSettingsToSecrets(backup: true);
				WriteRuntimeSettingsToDotEnv();
				if (_settingsModePage == SettingsModePage.Basic)
					SendTtsRuntimeSettingsUpdate();
			}
			if (showStatus)
				SetSettingsStatus(writeSecrets
					? (_settingsModePage == SettingsModePage.Advanced ? "Đã lưu Advanced. Dùng Áp dụng live hoặc Restart cho mục có cache." : _settingsModePage == SettingsModePage.Danger ? "Danger Zone không dùng Lưu; thao tác được thực thi qua maintenance protocol." : "Đã lưu Basic và áp dụng TTS xuống runtime.")
					: "Đã lưu user settings.");
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
		env["ERIS_TTS_LANGUAGE"] = NormalizeSettingsTtsLanguage(_settingsTtsLanguage);
		env["ERIS_TTS_QUALITY"] = _settingsTtsQuality ?? "high";
		env["ERIS_TTS_VOLUME"] = _settingsTtsVolume.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
		env["ERIS_TTS_SPEED"] = _settingsTtsSpeed.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
		WriteAdvancedSettingsToSecrets(env);

		// Ghi cả hai bản nháp. Đổi tab pool rồi lưu không còn làm mất phần đã sửa
		// ở tab trước, cũng không bắt người dùng lưu riêng từng provider.
		foreach (string kind in new[] { "gemini", "groq" })
		{
			if (_settingsKeyDrafts.TryGetValue(kind, out List<string> draftRows))
				ReplaceEditableKeysForPool(root, kind, NormalizeSettingsKeyRows(draftRows));
		}

		File.WriteAllText(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
	}

	private void WriteRuntimeSettingsToDotEnv()
	{
		string path = Path.Combine(GetRuntimeBaseDirForSettings(), ".env");
		var updates = new Dictionary<string, string>(StringComparer.Ordinal)
		{
			["ERIS_TTS_ENABLED"] = _settingsTtsEnabled ? "1" : "0",
			["ERIS_TTS_VOICE"] = string.IsNullOrWhiteSpace(_settingsTtsVoice) ? "Aoede" : _settingsTtsVoice.Trim(),
			["ERIS_TTS_LANGUAGE"] = NormalizeSettingsTtsLanguage(_settingsTtsLanguage),
			["ERIS_TTS_QUALITY"] = string.IsNullOrWhiteSpace(_settingsTtsQuality) ? "high" : _settingsTtsQuality.Trim().ToLowerInvariant(),
			["ERIS_TTS_VOLUME"] = _settingsTtsVolume.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture),
			["ERIS_TTS_SPEED"] = _settingsTtsSpeed.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture),
		};
		AppendAdvancedSettingsToDotEnv(updates);

		var lines = File.Exists(path)
			? new List<string>(File.ReadAllLines(path, Encoding.UTF8))
			: new List<string>();
		var written = new HashSet<string>(StringComparer.Ordinal);
		for (int i = 0; i < lines.Count; i++)
		{
			string trimmed = (lines[i] ?? "").Trim().TrimStart('\uFEFF');
			if (trimmed.StartsWith("export ", StringComparison.OrdinalIgnoreCase))
				trimmed = trimmed.Substring(7).Trim();
			int equals = trimmed.IndexOf('=');
			if (equals <= 0)
				continue;
			string key = trimmed.Substring(0, equals).Trim();
			if (!updates.TryGetValue(key, out string value))
				continue;
			lines[i] = $"{key}={value}";
			written.Add(key);
		}
		foreach (var pair in updates)
		{
			if (!written.Contains(pair.Key))
				lines.Add($"{pair.Key}={pair.Value}");
		}

		File.WriteAllLines(path, lines, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
	}

	private void ApplyLiveTtsSettingsFromPanel(string changedField)
	{
		SyncSettingsInputsToFields();
		SaveSettingsState(false, writeSecrets: true);
		SetSettingsStatus($"Đã áp dụng {changedField} TTS: {NormalizeSettingsTtsLanguage(_settingsTtsLanguage)}.");
	}

	private void SendTtsRuntimeSettingsUpdate()
	{
		if (_chatSend == null)
			return;
		var payload = new
		{
			type = "settings_update",
			scope = "tts",
			tts_enabled = _settingsTtsEnabled,
			tts_language = NormalizeSettingsTtsLanguage(_settingsTtsLanguage),
			tts_voice = string.IsNullOrWhiteSpace(_settingsTtsVoice) ? "Aoede" : _settingsTtsVoice.Trim(),
			tts_quality = string.IsNullOrWhiteSpace(_settingsTtsQuality) ? "high" : _settingsTtsQuality.Trim().ToLowerInvariant(),
			tts_volume = Math.Round(_settingsTtsVolume, 2),
			tts_speed = Math.Round(_settingsTtsSpeed, 2),
		};
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		if (error != Error.Ok)
			RunLogger.LogErr($"[Settings] Khong gui duoc TTS settings_update: {error}");
		else
			RunLogger.Log($"[Settings] Da gui TTS settings_update language={payload.tts_language} voice={payload.tts_voice} volume={payload.tts_volume} speed={payload.tts_speed}");
	}


	private void TryApplySettingsUpdateAck(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw)
			|| (!raw.Contains("settings_update_ack", StringComparison.Ordinal)
				&& !raw.Contains("settings_health_ack", StringComparison.Ordinal)
				&& !raw.Contains("tts_preview_ack", StringComparison.Ordinal)
				&& !raw.Contains("maintenance_", StringComparison.Ordinal)))
			return;

		if (raw.Contains("maintenance_", StringComparison.Ordinal))
			TryApplyMaintenanceMessage(raw);

		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;

			if (root.TryGetProperty("settings_update_ack", out JsonElement ack) && ack.ValueKind == JsonValueKind.Object)
			{
				string scope = ack.TryGetProperty("scope", out JsonElement scopeEl) ? scopeEl.GetString() ?? "tts" : "tts";
				if (string.Equals(scope, "advanced", StringComparison.OrdinalIgnoreCase))
				{
					int appliedCount = ack.TryGetProperty("applied", out JsonElement appliedEl) && appliedEl.ValueKind == JsonValueKind.Array ? appliedEl.GetArrayLength() : 0;
					int rejectedCount = ack.TryGetProperty("rejected", out JsonElement rejectedEl) && rejectedEl.ValueKind == JsonValueKind.Array ? rejectedEl.GetArrayLength() : 0;
					int restartCount = ack.TryGetProperty("restart_required", out JsonElement restartEl) && restartEl.ValueKind == JsonValueKind.Array ? restartEl.GetArrayLength() : 0;
					SetSettingsStatus($"Brain đã nhận {appliedCount} thiết lập Advanced{(restartCount > 0 ? $" · {restartCount} mục cần restart" : "")}{(rejectedCount > 0 ? $" · {rejectedCount} mục bị từ chối" : "")}.");
				}
				else
				{
				string language = ack.TryGetProperty("language", out JsonElement langEl) ? langEl.GetString() ?? "" : "";
				string voice = ack.TryGetProperty("voice", out JsonElement voiceEl) ? voiceEl.GetString() ?? "" : "";
				bool rebuilt = ack.TryGetProperty("worker_rebuilt", out JsonElement rebuiltEl) && rebuiltEl.ValueKind == JsonValueKind.True;
				bool ready = ack.TryGetProperty("engine_ready", out JsonElement readyEl) && readyEl.ValueKind == JsonValueKind.True;
				float volume = ack.TryGetProperty("volume", out JsonElement volumeEl) && volumeEl.TryGetSingle(out float parsedVolume) ? parsedVolume : _settingsTtsVolume;
				float speed = ack.TryGetProperty("speed", out JsonElement speedEl) && speedEl.TryGetSingle(out float parsedSpeed) ? parsedSpeed : _settingsTtsSpeed;
				if (_settingsTtsEngineStatusLabel != null)
					_settingsTtsEngineStatusLabel.Text = ready ? $"Engine: sẵn sàng · {volume * 100f:0}% · {speed:0.00}×" : "Engine: chưa sẵn sàng";
				SetSettingsStatus(ready
					? $"Backend đã nhận TTS: {language}, {voice}{(rebuilt ? " · worker đã nạp lại" : "")}"
					: "Backend đã nhận setting nhưng TTS chưa sẵn sàng; kiểm tra key hoặc Lưu & Restart.");
				}
			}

			if (root.TryGetProperty("settings_health_ack", out JsonElement healthAck) && healthAck.ValueKind == JsonValueKind.Object)
			{
				if (healthAck.TryGetProperty("pools", out JsonElement pools) && pools.ValueKind == JsonValueKind.Object)
				{
					foreach (string kind in new[] { "gemini", "groq" })
					{
						if (!pools.TryGetProperty(kind, out JsonElement pool) || pool.ValueKind != JsonValueKind.Object)
							continue;
						int size = pool.TryGetProperty("size", out JsonElement sizeEl) ? sizeEl.GetInt32() : 0;
						int available = pool.TryGetProperty("available", out JsonElement availableEl) ? availableEl.GetInt32() : 0;
						int dead = pool.TryGetProperty("dead", out JsonElement deadEl) ? deadEl.GetInt32() : 0;
						int cooldownMs = pool.TryGetProperty("global_cooldown_ms", out JsonElement cooldownEl) ? cooldownEl.GetInt32() : 0;
						_settingsPoolHealthSummary[kind] = cooldownMs > 0
							? $"{available}/{size} khả dụng · pool nghỉ {Mathf.CeilToInt(cooldownMs / 1000f)}s"
							: $"{available}/{size} khả dụng · {dead} cooldown/lỗi";

						var keyHealth = new List<SettingsKeyHealth>();
						if (pool.TryGetProperty("keys", out JsonElement keys) && keys.ValueKind == JsonValueKind.Array)
						{
							foreach (JsonElement key in keys.EnumerateArray())
							{
								keyHealth.Add(new SettingsKeyHealth
								{
									Index = key.TryGetProperty("index", out JsonElement indexEl) && indexEl.TryGetInt32(out int parsedIndex) ? parsedIndex : -1,
									Fingerprint = key.TryGetProperty("fingerprint", out JsonElement fingerprintEl) ? fingerprintEl.GetString() ?? "" : "",
									Status = key.TryGetProperty("status", out JsonElement statusEl) ? statusEl.GetString() ?? "unknown" : "unknown",
									Reason = key.TryGetProperty("reason", out JsonElement reasonEl) ? reasonEl.GetString() ?? "" : "",
									CooldownMs = key.TryGetProperty("cooldown_ms", out JsonElement keyCooldownEl) ? keyCooldownEl.GetInt32() : 0,
									Active = key.TryGetProperty("active", out JsonElement activeEl) && activeEl.ValueKind == JsonValueKind.True,
								});
							}
						}
						_settingsKeyHealth[kind] = keyHealth;
					}
				}
				if (healthAck.TryGetProperty("tts", out JsonElement tts) && tts.ValueKind == JsonValueKind.Object)
				{
					bool ready = tts.TryGetProperty("ready", out JsonElement readyEl) && readyEl.ValueKind == JsonValueKind.True;
					if (_settingsTtsEngineStatusLabel != null)
						_settingsTtsEngineStatusLabel.Text = ready ? "Engine: sẵn sàng" : "Engine: chưa sẵn sàng";
				}
				RefreshSettingsKeyRowHealthIndicators();
				SetSettingsStatus("Đã đọc trạng thái key pool thật từ Brain.");
			}

			if (root.TryGetProperty("tts_preview_ack", out JsonElement previewAck) && previewAck.ValueKind == JsonValueKind.Object)
			{
				bool accepted = previewAck.TryGetProperty("accepted", out JsonElement acceptedEl) && acceptedEl.ValueKind == JsonValueKind.True;
				string reason = previewAck.TryGetProperty("reason", out JsonElement reasonEl) ? reasonEl.GetString() ?? "" : "";
				if (_settingsTtsEngineStatusLabel != null)
					_settingsTtsEngineStatusLabel.Text = accepted ? "Engine: đang phát mẫu" : "Engine: không phát được";
				SetSettingsStatus(accepted ? "Đã gửi câu nghe thử xuống TTS." : $"Không nghe thử được: {reason}");
			}
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Settings] ack loi: {ex.Message}");
		}
	}


	private static string NormalizeSettingsTtsLanguage(string value)
	{
		string lang = (value ?? "").Trim().ToLowerInvariant();
		return lang switch
		{
			"" => "ja",
			"auto" => "ja",
			"jp" => "ja",
			"japanese" => "ja",
			"ja-jp" => "ja",
			_ => lang,
		};
	}

	private void LoadSettingsKeyAliases(JsonElement root)
	{
		_settingsKeyAliases.Clear();
		if (!root.TryGetProperty("key_aliases", out JsonElement aliasesRoot) || aliasesRoot.ValueKind != JsonValueKind.Object)
			return;

		foreach (JsonProperty poolProperty in aliasesRoot.EnumerateObject())
		{
			string kind = NormalizeSettingsPoolKind(poolProperty.Name);
			if (poolProperty.Value.ValueKind != JsonValueKind.Object)
				continue;
			foreach (JsonProperty aliasProperty in poolProperty.Value.EnumerateObject())
			{
				if (aliasProperty.Value.ValueKind != JsonValueKind.String)
					continue;
				string fingerprint = (aliasProperty.Name ?? "").Trim().ToLowerInvariant();
				string name = (aliasProperty.Value.GetString() ?? "").Trim();
				if (!string.IsNullOrWhiteSpace(fingerprint) && !string.IsNullOrWhiteSpace(name))
					_settingsKeyAliases[SettingsKeyAliasMapKey(kind, fingerprint)] = name;
			}
		}
	}

	private JsonObject BuildSettingsKeyAliasesNode()
	{
		var root = new JsonObject();
		foreach (string kind in new[] { "gemini", "groq" })
		{
			List<string> values = _settingsKeyDrafts.TryGetValue(kind, out List<string> draftValues)
				? new List<string>(draftValues)
				: ReadEditableKeysForPool(kind);
			List<string> names = _settingsKeyNameDrafts.TryGetValue(kind, out List<string> draftNames)
				? new List<string>(draftNames)
				: ReadSettingsKeyNamesForEditor(kind, values);

			var pool = new JsonObject();
			for (int i = 0; i < values.Count; i++)
			{
				string rawKey = (values[i] ?? "").Trim();
				string fingerprint = SettingsKeyFingerprint(rawKey);
				if (string.IsNullOrWhiteSpace(fingerprint))
					continue;

				string name = i < names.Count ? (names[i] ?? "").Trim() : "";
				if (string.IsNullOrWhiteSpace(name))
					name = DefaultSettingsKeyName(kind, i + 1);
				pool[fingerprint] = name;
				_settingsKeyAliases[SettingsKeyAliasMapKey(kind, fingerprint)] = name;
			}
			root[kind] = pool;
		}
		return root;
	}

	private JsonObject BuildSanitizedSettingsNode()
	{
		var state = new JsonObject
		{
			["version"] = 4,
			["remote_api_enabled"] = EnableRemoteCognitionApi,
			["auto_start_brain"] = AutoStartVision,
			["auto_restart_brain"] = AutoRestartVisionOnCrash,
			["remote_provider"] = RemoteApiProvider ?? "",
			["remote_base_url"] = RemoteApiBaseUrl ?? "",
			["remote_model"] = RemoteApiModelName ?? "",
			["tts_enabled"] = _settingsTtsEnabled,
			["tts_voice"] = _settingsTtsVoice ?? "Aoede",
			["tts_language"] = _settingsTtsLanguage ?? "auto",
			["tts_quality"] = _settingsTtsQuality ?? "high",
			["tts_volume"] = Math.Round(_settingsTtsVolume, 2),
			["tts_speed"] = Math.Round(_settingsTtsSpeed, 2),
			["always_on_top"] = KeepWindowAlwaysOnTop,
			["transparent_window"] = UseTransparentWindow,
			["mouse_passthrough"] = EnableMousePassthrough,
			["lock_character_position"] = LockCharacterPosition,
			["editing_key_pool"] = _settingsKeyPoolKind ?? "",
			["editing_key_count"] = CollectEditedSettingsKeys().Count,
			["key_aliases"] = BuildSettingsKeyAliasesNode(),
		};
		AddAdvancedSettingsToState(state);
		return state;
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
		string brain = _processes != null && _processes.IsVisionRunning
			? $"brain chạy PID {_processes.VisionProcessId}"
			: "brain dừng";
		string secrets = File.Exists(GetSecretsPath()) ? "có secrets" : "thiếu secrets";
		SetSettingsStatus($"OK: {brain}, provider {RemoteApiProvider}, Gemini {gemini}, Groq {groq}, TTS {_settingsTtsEnabledText()}, {secrets}.");
	}

	private void TestSettingsPool()
	{
		if (_processes == null || !_processes.IsVisionRunning)
		{
			int gemini = CountConfiguredGeminiKeys();
			int groq = CountConfiguredGroqKeys();
			SetSettingsStatus($"Brain đang dừng; chỉ đếm local: Gemini {gemini}, Groq {groq}.");
			return;
		}
		if (_chatSend == null)
		{
			SetSettingsStatus("Kênh UDP chưa sẵn sàng nên chưa đọc được trạng thái key pool.");
			return;
		}

		if (_settingsPoolHealthLabel != null)
			_settingsPoolHealthLabel.Text = "Đang đọc trạng thái runtime…";
		var payload = new { type = "settings_health" };
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		SetSettingsStatus(error == Error.Ok ? "Đang đọc trạng thái hai key pool..." : $"Không gửi được yêu cầu trạng thái: {error}");
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

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(selectedPath, Encoding.UTF8));
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
			_settingsKeyDrafts.Clear();
			_settingsKeyNameDrafts.Clear();
			_settingsSkipKeyDraftCaptureOnce = true;
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

		RefreshSettingsRuntimeStatus();

		CaptureCurrentSettingsKeyDraft();
		RefreshSettingsPoolSelectorCounts();

		ApplySettingsSwitch(_settingsTtsSwitch, _settingsTtsEnabled);
		ApplySettingsSwitch(_settingsAutoStartSwitch, AutoStartVision);
		ApplySettingsSwitch(_settingsAutoRestartSwitch, AutoRestartVisionOnCrash);
		ApplySettingsSwitch(_settingsAlwaysOnTopSwitch, KeepWindowAlwaysOnTop);
		ApplySettingsSwitch(_settingsTransparentSwitch, UseTransparentWindow);
		ApplySettingsSwitch(_settingsPassthroughSwitch, EnableMousePassthrough);
		ApplySettingsSwitch(_settingsPositionLockSwitch, LockCharacterPosition);
		RefreshSettingsKeyRowHealthIndicators();
	}


	private string BuildHardeningRuntimeSummary()
	{
		if (string.IsNullOrWhiteSpace(_latestHardeningStatusJson))
			return "";
		try
		{
			using JsonDocument doc = JsonDocument.Parse(_latestHardeningStatusJson);
			JsonElement root = doc.RootElement;
			string releaseStatus = "";
			string phase7Status = "";
			int phase7Turns = 0;
			int phase7Target = 0;

			if (root.TryGetProperty("release", out JsonElement release)
				&& release.ValueKind == JsonValueKind.Object
				&& release.TryGetProperty("status", out JsonElement releaseNode))
				releaseStatus = releaseNode.GetString() ?? "";

			if (root.TryGetProperty("phase7", out JsonElement phase7)
				&& phase7.ValueKind == JsonValueKind.Object)
			{
				if (phase7.TryGetProperty("status", out JsonElement statusNode))
					phase7Status = statusNode.GetString() ?? "";
				if (phase7.TryGetProperty("public_turns", out JsonElement turnsNode)
					&& turnsNode.ValueKind == JsonValueKind.Number)
					turnsNode.TryGetInt32(out phase7Turns);
				if (phase7.TryGetProperty("target_turns", out JsonElement targetNode)
					&& targetNode.ValueKind == JsonValueKind.Number)
					targetNode.TryGetInt32(out phase7Target);
			}

			if (string.Equals(phase7Status, "running", StringComparison.OrdinalIgnoreCase))
				return $"Phase 7 {phase7Turns}/{Math.Max(phase7Target, 1)}";
			if (!string.IsNullOrWhiteSpace(releaseStatus))
				return $"Hardening {releaseStatus}";
			if (!string.IsNullOrWhiteSpace(phase7Status) && phase7Status != "disabled")
				return $"Phase 7 {phase7Status}";
		}
		catch (Exception)
		{
			// Status chỉ là phụ trợ UI; payload hỏng không được phép kéo sập Settings.
		}
		return "";
	}

	private void TickSettingsPanelRuntimeStatus()
	{
		if (_settingsPanel == null || !_settingsPanel.Visible)
			return;
		ulong now = Time.GetTicksMsec();
		if (now < _settingsNextRuntimeRefreshMs)
			return;
		_settingsNextRuntimeRefreshMs = now + 1000;
		RefreshSettingsRuntimeStatus();
	}

	private void RefreshSettingsRuntimeStatus()
	{
		bool running = _processes != null && _processes.IsVisionRunning;
		bool recovering = _visionRestartPending && !running;
		if (_settingsBrainStatusLabel != null)
		{
			_settingsBrainStatusLabel.Text = recovering
				? "●  Brain đang phục hồi..."
				: running ? "●  Brain đang chạy" : "●  Brain đã dừng";
			_settingsBrainStatusLabel.AddThemeStyleboxOverride("normal", SettingsCardStyle(
				running ? new Color(0.84f, 1.00f, 0.86f, 0.88f)
					: recovering ? new Color(1.00f, 0.96f, 0.82f, 0.90f)
					: new Color(1.00f, 0.94f, 0.80f, 0.88f),
				running ? new Color(0.40f, 0.84f, 0.48f, 0.80f)
					: recovering ? new Color(0.96f, 0.66f, 0.24f, 0.82f)
					: new Color(1.00f, 0.62f, 0.24f, 0.75f),
				10));
			_settingsBrainStatusLabel.AddThemeColorOverride(
				"font_color",
				running ? new Color(0.10f, 0.42f, 0.14f)
					: new Color(0.64f, 0.34f, 0.08f));
		}

		if (_settingsRuntimeDetailLabel != null)
		{
			if (running)
			{
				TimeSpan uptime = _processes.VisionUptime;
				string uptimeText = uptime.TotalHours >= 1d
					? $"{(int)uptime.TotalHours} giờ {uptime.Minutes:00} phút"
					: $"{uptime.Minutes:00} phút {uptime.Seconds:00} giây";
				string hardeningSummary = BuildHardeningRuntimeSummary();
				_settingsRuntimeDetailLabel.Text = $"PID {_processes.VisionProcessId} · Đã chạy {uptimeText}"
					+ (string.IsNullOrWhiteSpace(hardeningSummary) ? "" : $" · {hardeningSummary}");
				_settingsRuntimeDetailLabel.TooltipText = _processes.VisionStartedAtUtc.HasValue
					? $"Khởi động lúc {_processes.VisionStartedAtUtc.Value.ToLocalTime():HH:mm:ss}"
					: "Brain đang chạy";
			}
			else if (recovering)
			{
				_settingsRuntimeDetailLabel.Text = "Đang chờ 2 giây trước khi tự khởi động lại";
				_settingsRuntimeDetailLabel.TooltipText = "Tự phục hồi đang hoạt động";
			}
			else
			{
				_settingsRuntimeDetailLabel.Text = _processes?.LastVisionExitCode is int code
					? $"Lần thoát gần nhất · mã {code}"
					: "Chưa có tiến trình Brain đang chạy";
				_settingsRuntimeDetailLabel.TooltipText = _processes?.LastVisionExitCode is int lastCode
					? $"Exit code gần nhất: {lastCode}"
					: "Bấm Khởi động Brain để chạy runtime";
			}
		}

		if (_settingsRuntimeStartButton != null)
		{
			_settingsRuntimeStartButton.Visible = !running;
			_settingsRuntimeStartButton.Disabled = recovering;
			_settingsRuntimeStartButton.Text = recovering ? "Đang phục hồi..." : "▶  Khởi động Brain";
		}
		if (_settingsRuntimeStopButton != null)
		{
			_settingsRuntimeStopButton.Visible = running;
			_settingsRuntimeStopButton.Disabled = !running;
		}
		if (_settingsRuntimeRestartButton != null)
		{
			_settingsRuntimeRestartButton.Visible = running;
			_settingsRuntimeRestartButton.Disabled = !running;
		}

		RefreshSettingsRuntimeModelSummary();
	}

	private void RefreshSettingsRuntimeModelSummary()
	{
		if (_settingsRuntimeProviderSummaryLabel != null)
			_settingsRuntimeProviderSummaryLabel.Text = $"Provider: {DisplaySettingsProviderName(RemoteApiProvider)}";
		if (_settingsRuntimeModelSummaryLabel != null)
		{
			string model = string.IsNullOrWhiteSpace(RemoteApiModelName) ? "Chưa chọn model" : RemoteApiModelName.Trim();
			_settingsRuntimeModelSummaryLabel.Text = model;
			_settingsRuntimeModelSummaryLabel.TooltipText = model;
		}
	}


	private void RefreshSettingsKeyRowHealthIndicators()
	{
		string kind = NormalizeSettingsPoolKind(_settingsKeyPoolKind);
		if (_settingsPoolHealthLabel != null)
			_settingsPoolHealthLabel.Text = _settingsPoolHealthSummary.TryGetValue(kind, out string summary) ? summary : "Chưa đọc trạng thái runtime";

		_settingsKeyHealth.TryGetValue(kind, out List<SettingsKeyHealth> health);
		for (int i = 0; i < _settingsKeyStatusLabels.Count; i++)
		{
			Label label = _settingsKeyStatusLabels[i];
			if (label == null || !IsInstanceValid(label))
				continue;

			int priority = i + 1;
			string rawKey = i < _settingsKeyInputs.Count && _settingsKeyInputs[i] != null ? (_settingsKeyInputs[i].Text ?? "").Trim() : "";
			string displayName = i < _settingsKeyNameInputs.Count && _settingsKeyNameInputs[i] != null
				? (_settingsKeyNameInputs[i].Text ?? "").Trim()
				: DefaultSettingsKeyName(kind, priority);
			if (string.IsNullOrWhiteSpace(displayName))
				displayName = DefaultSettingsKeyName(kind, priority);

			string fingerprint = SettingsKeyFingerprint(rawKey);
			SettingsKeyHealth item = health?.Find(candidate => string.Equals(candidate.Fingerprint, fingerprint, StringComparison.OrdinalIgnoreCase));

			if (string.IsNullOrWhiteSpace(rawKey))
			{
				label.Text = $"○ Trống · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.56f, 0.50f, 0.54f));
				label.TooltipText = $"{displayName}: chưa nhập API key; dòng này sẽ không được lưu";
				continue;
			}

			if (item == null)
			{
				label.Text = $"○ Chưa nạp · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.56f, 0.50f, 0.54f));
				label.TooltipText = $"{displayName}: chưa có trong runtime; Lưu & Restart để đồng bộ";
				continue;
			}

			if (string.Equals(item.Status, "quarantined", StringComparison.OrdinalIgnoreCase))
			{
				label.Text = $"● Cách ly · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.74f, 0.12f, 0.18f));
				label.TooltipText = $"{displayName}: key bị cách ly trong runtime{(string.IsNullOrWhiteSpace(item.Reason) ? "" : $" · {item.Reason}")}";
			}
			else if (string.Equals(item.Status, "cooldown", StringComparison.OrdinalIgnoreCase))
			{
				label.Text = $"● Cooldown · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.78f, 0.43f, 0.08f));
				label.TooltipText = $"{displayName}: đang cooldown, còn khoảng {Mathf.CeilToInt(item.CooldownMs / 1000f)} giây";
			}
			else if (string.Equals(item.Status, "error", StringComparison.OrdinalIgnoreCase)
				|| string.Equals(item.Status, "invalid", StringComparison.OrdinalIgnoreCase))
			{
				label.Text = $"● Lỗi · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.74f, 0.12f, 0.18f));
				label.TooltipText = $"{displayName}: runtime đánh dấu key lỗi hoặc không hợp lệ";
			}
			else if (item.Active)
			{
				label.Text = $"● Đang dùng · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.08f, 0.58f, 0.18f));
				label.TooltipText = $"{displayName}: runtime đang dùng cho request kế tiếp";
			}
			else
			{
				label.Text = $"● Sẵn sàng · Ưu tiên {priority}";
				label.AddThemeColorOverride("font_color", new Color(0.20f, 0.46f, 0.24f));
				label.TooltipText = $"{displayName}: key sẵn sàng trong pool";
			}
		}
	}


	private static string SettingsKeyFingerprint(string rawKey)
	{
		if (string.IsNullOrWhiteSpace(rawKey))
			return "";
		byte[] hash = System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(rawKey.Trim()));
		return Convert.ToHexString(hash).Substring(0, 12).ToLowerInvariant();
	}


	private void RequestTtsPreview()
	{
		SyncSettingsInputsToFields();
		if (_processes == null || !_processes.IsVisionRunning)
		{
			SetSettingsStatus("Brain đang dừng nên chưa thể nghe thử TTS.");
			return;
		}
		SendTtsRuntimeSettingsUpdate();
		string language = NormalizeSettingsTtsLanguage(_settingsTtsLanguage);
		string sample = language switch
		{
			"ja" => "こんにちは、エリスです。音声設定を確認しています。",
			"en" => "Hello, this is Eris. I am checking the current voice settings.",
			_ => "Xin chào Ngài, tôi là Eris. Tôi đang kiểm tra thiết lập giọng nói.",
		};
		var payload = new { type = "tts_preview", text = sample };
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		SetSettingsStatus(error == Error.Ok ? "Đang tạo câu nghe thử..." : $"Không gửi được câu nghe thử: {error}");
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
		var rows = new List<string>();
		foreach (LineEdit input in _settingsKeyInputs)
		{
			if (input != null && IsInstanceValid(input))
				rows.Add(input.Text ?? "");
		}
		return NormalizeSettingsKeyRows(rows);
	}

	private static List<string> NormalizeSettingsKeyRows(IEnumerable<string> rows)
	{
		var keys = new List<string>();
		var unique = new HashSet<string>(StringComparer.Ordinal);
		if (rows == null)
			return keys;

		foreach (string raw in rows)
		{
			foreach (string key in ExtractClipboardKeys(raw ?? ""))
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

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
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

			using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
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
		JsonNode parsed = JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8));
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

	private static bool TryReadFloat(JsonElement root, string name, out float value)
	{
		value = 0f;
		if (!root.TryGetProperty(name, out JsonElement item))
			return false;
		if (item.ValueKind == JsonValueKind.Number && item.TryGetSingle(out value))
			return true;
		if (item.ValueKind == JsonValueKind.String)
			return float.TryParse(item.GetString(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value);
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
