using Godot;
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

public partial class UdpListener : Node2D
{
	private enum SettingsModePage
	{
		Basic,
		Advanced,
	}

	private SettingsModePage _settingsModePage = SettingsModePage.Basic;

	private OptionButton _advancedPresetSelect;
	private OptionButton _advancedReasoningSelect;
	private OptionButton _advancedCompletionSelect;
	private OptionButton _advancedTimeoutSelect;
	private OptionButton _advancedConcurrencySelect;
	private OptionButton _advancedPromptCapSelect;
	private OptionButton _advancedMaintenanceBudgetSelect;
	private OptionButton _advancedDispatchSelect;
	private OptionButton _advancedPrefetchWorkersSelect;
	private OptionButton _advancedMaxSegmentsSelect;

	private TextureRect _advancedFallbackSwitch;
	private TextureRect _advancedSelfCritiqueSwitch;
	private TextureRect _advancedSecondPassSwitch;
	private TextureRect _advancedDdsSwitch;
	private TextureRect _advancedStrictGroundingSwitch;
	private TextureRect _advancedMemoryParserSwitch;
	private TextureRect _advancedMemoryMaintenanceSwitch;
	private TextureRect _advancedV3PipelineSwitch;
	private TextureRect _advancedPerformanceSwitch;
	private TextureRect _advancedInterruptSwitch;
	private TextureRect _advancedStageProtocolSwitch;
	private TextureRect _advancedSegmentTtsSwitch;
	private TextureRect _advancedTaskManagerSwitch;
	private TextureRect _advancedStageLocalizeSwitch;
	private TextureRect _advancedAudioPolishSwitch;

	private string _advancedPreset = "Cân bằng";
	private string _advancedReasoningEffort = "medium";
	private int _advancedCompletionTokens = 1280;
	private int _advancedChatTimeoutSeconds = 30;
	private int _advancedMaxConcurrency = 4;
	private bool _advancedAutoFallback = true;
	private bool _advancedSelfCritique = true;
	private bool _advancedDirectorSecondPass;

	private int _advancedPromptHardCapTokens = 4800;
	private bool _advancedDdsEnabled = true;
	private bool _advancedStrictGrounding = true;
	private bool _advancedMemorySemanticParser;
	private bool _advancedMemoryMaintenance = true;
	private string _advancedMemoryMaintenanceBudget = "small";
	private bool _advancedV3Pipeline = true;

	private bool _advancedPerformanceActs = true;
	private bool _advancedInterruptEnabled = true;
	private bool _advancedStageProtocol = true;
	private bool _advancedSegmentTts = true;
	private string _advancedSegmentDispatch = "inline";
	private bool _advancedTtsTaskManager = true;
	private int _advancedPrefetchWorkers = 2;
	private int _advancedMaxTtsSegments = 4;
	private bool _advancedStageLocalize = true;
	private bool _advancedAudioPolish = true;

	private void SwitchSettingsMode(SettingsModePage page)
	{
		if (_settingsModePage == page)
			return;
		_settingsModePage = page;
		BuildSettingsPanelUi();
		SetSettingsStatus(page == SettingsModePage.Advanced
			? "Advanced đang mở. Các mục có dấu restart sẽ áp dụng sau khi khởi động lại Brain."
			: "Đã quay lại Basic.");
	}

	private void ResetSettingsUiReferencesForRebuild()
	{
		_settingsBrainStatusLabel = null;
		_settingsRuntimeDetailLabel = null;
		_settingsRuntimeProviderSummaryLabel = null;
		_settingsRuntimeModelSummaryLabel = null;
		_settingsRuntimeStartButton = null;
		_settingsRuntimeStopButton = null;
		_settingsRuntimeRestartButton = null;
		_settingsConnectionOverlay = null;
		_settingsConnectionFeedbackLabel = null;
		_settingsPoolStatusLabel = null;
		_settingsFallbackStatusLabel = null;
		_settingsPoolHealthLabel = null;
		_settingsTtsEngineStatusLabel = null;
		_settingsStatusNoteLabel = null;
		_settingsTtsSwitch = null;
		_settingsAutoStartSwitch = null;
		_settingsAutoRestartSwitch = null;
		_settingsAlwaysOnTopSwitch = null;
		_settingsTransparentSwitch = null;
		_settingsPassthroughSwitch = null;
		_settingsPositionLockSwitch = null;
		_settingsProviderSelect = null;
		_settingsModelInput = null;
		_settingsBaseUrlInput = null;
		_settingsVoiceSelect = null;
		_settingsLanguageSelect = null;
		_settingsQualitySelect = null;
		_settingsTtsVolumeSlider = null;
		_settingsTtsSpeedSlider = null;
		_settingsTtsVolumeValueLabel = null;
		_settingsTtsSpeedValueLabel = null;
		_settingsImportSecretsDialog = null;
		_settingsKeyRowsBox = null;
		_settingsKeyNameInputs.Clear();
		_settingsKeyInputs.Clear();
		_settingsKeyStatusLabels.Clear();

		_advancedPresetSelect = null;
		_advancedReasoningSelect = null;
		_advancedCompletionSelect = null;
		_advancedTimeoutSelect = null;
		_advancedConcurrencySelect = null;
		_advancedPromptCapSelect = null;
		_advancedMaintenanceBudgetSelect = null;
		_advancedDispatchSelect = null;
		_advancedPrefetchWorkersSelect = null;
		_advancedMaxSegmentsSelect = null;
		_advancedFallbackSwitch = null;
		_advancedSelfCritiqueSwitch = null;
		_advancedSecondPassSwitch = null;
		_advancedDdsSwitch = null;
		_advancedStrictGroundingSwitch = null;
		_advancedMemoryParserSwitch = null;
		_advancedMemoryMaintenanceSwitch = null;
		_advancedV3PipelineSwitch = null;
		_advancedPerformanceSwitch = null;
		_advancedInterruptSwitch = null;
		_advancedStageProtocolSwitch = null;
		_advancedSegmentTtsSwitch = null;
		_advancedTaskManagerSwitch = null;
		_advancedStageLocalizeSwitch = null;
		_advancedAudioPolishSwitch = null;
	}

	private void BuildAdvancedSettingsPage(Control root)
	{
		var reasoningCard = AddSettingsCard(root, new Rect2(32f, 205f, 318f, 380f), "Suy luận");
		BuildAdvancedReasoningCard(reasoningCard);

		var memoryCard = AddSettingsCard(root, new Rect2(370f, 205f, 420f, 380f), "Ngữ cảnh & Memory");
		BuildAdvancedMemoryCard(memoryCard);

		var stageCard = AddSettingsCard(root, new Rect2(810f, 205f, 338f, 380f), "Biểu diễn & Pipeline");
		BuildAdvancedStageCard(stageCard);

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

		var note = CreateUiLabel("Advanced ghi config thật vào user settings + secrets/.env.", 13, SettingsInkSoft);
		note.Position = new Vector2(112f, 628f);
		note.Size = new Vector2(420f, 24f);
		root.AddChild(note);

		_settingsStatusNoteLabel = CreateUiLabel("", 10, SettingsInk);
		_settingsStatusNoteLabel.Position = new Vector2(112f, 646f);
		_settingsStatusNoteLabel.Size = new Vector2(420f, 16f);
		_settingsStatusNoteLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_settingsStatusNoteLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		root.AddChild(_settingsStatusNoteLabel);

		var defaults = CreateSettingsButton("Mặc định", ResetAdvancedSettingsDefaults, primary: false);
		defaults.Position = new Vector2(668f, 622f);
		defaults.Size = new Vector2(82f, 38f);
		root.AddChild(defaults);

		var memory = CreateSettingsButton("Mở memory", OpenAdvancedMemoryDirectory, primary: false);
		memory.Position = new Vector2(756f, 622f);
		memory.Size = new Vector2(96f, 38f);
		root.AddChild(memory);

		var apply = CreateSettingsButton("Áp dụng live", ApplyAdvancedSettingsLive, primary: false);
		apply.Position = new Vector2(858f, 622f);
		apply.Size = new Vector2(100f, 38f);
		apply.AddThemeFontSizeOverride("font_size", 10);
		root.AddChild(apply);

		var save = CreateSettingsButton("Lưu", SaveSettingsState, primary: true);
		save.Position = new Vector2(964f, 620f);
		save.Size = new Vector2(76f, 42f);
		root.AddChild(save);

		var saveRestart = CreateSettingsButton("Lưu & Restart", SaveSettingsAndRestart, primary: true);
		saveRestart.Position = new Vector2(1046f, 620f);
		saveRestart.Size = new Vector2(98f, 42f);
		saveRestart.AddThemeFontSizeOverride("font_size", 9);
		root.AddChild(saveRestart);
	}

	private void BuildAdvancedReasoningCard(Control parent)
	{
		_advancedPresetSelect = AddAdvancedOptionRow(parent, 48f, "Preset", new[] { "Nhanh", "Cân bằng", "Sâu", "Tùy chỉnh" }, _advancedPreset, value =>
		{
			if (value == "Tùy chỉnh")
			{
				_advancedPreset = value;
				MarkAdvancedChanged("preset");
				return;
			}
			ApplyAdvancedPreset(value);
			BuildSettingsPanelUi();
			SetSettingsStatus($"Đã nạp preset {value}. Bấm Lưu hoặc Áp dụng live.");
		});

		_advancedReasoningSelect = AddAdvancedOptionRow(parent, 88f, "Reasoning", new[] { "low", "medium", "high" }, _advancedReasoningEffort, value =>
		{
			_advancedReasoningEffort = value;
			MarkAdvancedChanged("reasoning");
		});

		_advancedCompletionSelect = AddAdvancedOptionRow(parent, 128f, "Output", new[] { "768", "1024", "1280", "1536", "2048" }, _advancedCompletionTokens.ToString(), value =>
		{
			_advancedCompletionTokens = ParseAdvancedInt(value, 1280, 384, 2048);
			MarkAdvancedChanged("output token");
		});

		_advancedTimeoutSelect = AddAdvancedOptionRow(parent, 168f, "Timeout", new[] { "15", "20", "30", "45", "60" }, _advancedChatTimeoutSeconds.ToString(), value =>
		{
			_advancedChatTimeoutSeconds = ParseAdvancedInt(value, 30, 5, 120);
			MarkAdvancedChanged("timeout");
		});

		_advancedConcurrencySelect = AddAdvancedOptionRow(parent, 208f, "Đồng thời", new[] { "1", "2", "3", "4", "6", "8" }, _advancedMaxConcurrency.ToString(), value =>
		{
			_advancedMaxConcurrency = ParseAdvancedInt(value, 4, 1, 16);
			MarkAdvancedChanged("concurrency · cần restart");
		});

		_advancedFallbackSwitch = AddAdvancedToggleRow(parent, 250f, "Tự dùng model dự phòng", () => _advancedAutoFallback, value => _advancedAutoFallback = value, "fallback");
		_advancedSelfCritiqueSwitch = AddAdvancedToggleRow(parent, 278f, "Tự kiểm tra câu trả lời", () => _advancedSelfCritique, value => _advancedSelfCritique = value, "self critique");
		_advancedSecondPassSwitch = AddAdvancedToggleRow(parent, 306f, "Director kiểm tra lần hai", () => _advancedDirectorSecondPass, value => _advancedDirectorSecondPass = value, "second pass");
	}

	private void BuildAdvancedMemoryCard(Control parent)
	{
		_advancedPromptCapSelect = AddAdvancedOptionRow(parent, 48f, "Prompt tổng", new[] { "3600", "4200", "4800", "5200", "6000" }, _advancedPromptHardCapTokens.ToString(), value =>
		{
			_advancedPromptHardCapTokens = ParseAdvancedInt(value, 4800, 1024, 12000);
			MarkAdvancedChanged("prompt cap");
		});

		_advancedDdsSwitch = AddAdvancedToggleRow(parent, 92f, "Nén DDS khi prompt lớn", () => _advancedDdsEnabled, value => _advancedDdsEnabled = value, "DDS");
		_advancedStrictGroundingSwitch = AddAdvancedToggleRow(parent, 122f, "Grounding chặt", () => _advancedStrictGrounding, value => _advancedStrictGrounding = value, "grounding · cần restart");
		_advancedMemoryParserSwitch = AddAdvancedToggleRow(parent, 152f, "Parser memory ngữ nghĩa", () => _advancedMemorySemanticParser, value => _advancedMemorySemanticParser = value, "memory parser · cần restart");
		_advancedMemoryMaintenanceSwitch = AddAdvancedToggleRow(parent, 182f, "Bảo trì memory nền", () => _advancedMemoryMaintenance, value => _advancedMemoryMaintenance = value, "memory maintenance");

		_advancedMaintenanceBudgetSelect = AddAdvancedOptionRow(parent, 214f, "Mức bảo trì", new[] { "small", "medium", "large" }, _advancedMemoryMaintenanceBudget, value =>
		{
			_advancedMemoryMaintenanceBudget = value;
			MarkAdvancedChanged("maintenance budget");
		});

		_advancedV3PipelineSwitch = AddAdvancedToggleRow(parent, 258f, "Cognitive Pipeline V3", () => _advancedV3Pipeline, value => _advancedV3Pipeline = value, "V3 pipeline · cần restart");

		var hint = CreateUiLabel("Parser memory, Grounding và V3 được khởi tạo lúc Brain start.", 9, SettingsInkSoft);
		hint.Position = new Vector2(18f, 292f);
		hint.Size = new Vector2(parent.Size.X - 36f, 34f);
		hint.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		hint.VerticalAlignment = VerticalAlignment.Top;
		parent.AddChild(hint);
	}

	private void BuildAdvancedStageCard(Control parent)
	{
		_advancedPerformanceSwitch = AddAdvancedToggleRow(parent, 48f, "Performance Act", () => _advancedPerformanceActs, value => _advancedPerformanceActs = value, "performance act");
		_advancedInterruptSwitch = AddAdvancedToggleRow(parent, 78f, "Cho phép ngắt lời", () => _advancedInterruptEnabled, value => _advancedInterruptEnabled = value, "interrupt");
		_advancedStageProtocolSwitch = AddAdvancedToggleRow(parent, 108f, "Stage protocol", () => _advancedStageProtocol, value => _advancedStageProtocol = value, "stage protocol");
		_advancedSegmentTtsSwitch = AddAdvancedToggleRow(parent, 138f, "TTS theo segment", () => _advancedSegmentTts, value => _advancedSegmentTts = value, "segment TTS");

		_advancedDispatchSelect = AddAdvancedOptionRow(parent, 170f, "Cách phát", new[] { "inline", "queued" }, _advancedSegmentDispatch, value =>
		{
			_advancedSegmentDispatch = value;
			MarkAdvancedChanged("dispatch");
		});

		_advancedTaskManagerSwitch = AddAdvancedToggleRow(parent, 214f, "TTS Task Manager", () => _advancedTtsTaskManager, value => _advancedTtsTaskManager = value, "task manager");

		_advancedPrefetchWorkersSelect = AddAdvancedOptionRow(parent, 244f, "Prefetch", new[] { "1", "2", "3", "4" }, _advancedPrefetchWorkers.ToString(), value =>
		{
			_advancedPrefetchWorkers = ParseAdvancedInt(value, 2, 1, 8);
			MarkAdvancedChanged("prefetch worker");
		});

		_advancedMaxSegmentsSelect = AddAdvancedOptionRow(parent, 284f, "Max segment", new[] { "2", "3", "4", "6" }, _advancedMaxTtsSegments.ToString(), value =>
		{
			_advancedMaxTtsSegments = ParseAdvancedInt(value, 4, 1, 12);
			MarkAdvancedChanged("max segment");
		});

		_advancedStageLocalizeSwitch = AddAdvancedMiniToggle(parent, new Vector2(18f, 320f), "Localize", () => _advancedStageLocalize, value => _advancedStageLocalize = value, "speech localize");
		_advancedAudioPolishSwitch = AddAdvancedMiniToggle(parent, new Vector2(150f, 320f), "Audio polish", () => _advancedAudioPolish, value => _advancedAudioPolish = value, "audio polish");
	}

	private OptionButton AddAdvancedOptionRow(Control parent, float y, string label, string[] values, string selected, Action<string> onChanged)
	{
		float rowWidth = Mathf.Max(220f, parent.Size.X - 36f);
		var row = new Panel
		{
			Position = new Vector2(18f, y),
			Size = new Vector2(rowWidth, 34f),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		row.AddThemeStyleboxOverride("panel", SettingsCardStyle(new Color(1f, 0.98f, 0.99f, 0.62f), SettingsBorder, 11));
		parent.AddChild(row);

		var left = CreateUiLabel(label, 9, SettingsInkSoft);
		left.Position = new Vector2(10f, 6f);
		left.Size = new Vector2(104f, 22f);
		StyleSettingsSingleLineLabel(left);
		row.AddChild(left);

		var option = new OptionButton
		{
			Position = new Vector2(114f, 3f),
			Size = new Vector2(rowWidth - 124f, 28f),
			MouseFilter = Control.MouseFilterEnum.Stop,
			ClipText = true,
			TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis,
		};
		option.AddThemeFontSizeOverride("font_size", 9);
		option.AddThemeColorOverride("font_color", SettingsInk);
		int selectedIndex = 0;
		for (int i = 0; i < values.Length; i++)
		{
			option.AddItem(values[i]);
			if (string.Equals(values[i], selected, StringComparison.OrdinalIgnoreCase))
				selectedIndex = i;
		}
		option.Select(selectedIndex);
		option.ItemSelected += index => onChanged?.Invoke(option.GetItemText((int)index));
		row.AddChild(option);
		return option;
	}

	private TextureRect AddAdvancedToggleRow(Control parent, float y, string label, Func<bool> getter, Action<bool> setter, string changedName)
	{
		var text = CreateUiLabel(label, 10, SettingsInk);
		text.Position = new Vector2(18f, y + 2f);
		text.Size = new Vector2(parent.Size.X - 92f, 22f);
		StyleSettingsSingleLineLabel(text);
		parent.AddChild(text);

		TextureRect toggle = null;
		toggle = AddSettingsSwitch(parent, new Vector2(parent.Size.X - 64f, y - 2f), getter(), () =>
		{
			bool value = !getter();
			setter(value);
			ApplySettingsSwitch(toggle, value);
			MarkAdvancedChanged(changedName);
		});
		toggle.Size = new Vector2(44f, 26f);
		toggle.CustomMinimumSize = toggle.Size;
		return toggle;
	}

	private TextureRect AddAdvancedMiniToggle(Control parent, Vector2 pos, string label, Func<bool> getter, Action<bool> setter, string changedName)
	{
		var text = CreateUiLabel(label, 8, SettingsInk);
		text.Position = pos;
		text.Size = new Vector2(76f, 18f);
		StyleSettingsSingleLineLabel(text);
		parent.AddChild(text);

		TextureRect toggle = null;
		toggle = AddSettingsSwitch(parent, pos + new Vector2(82f, -2f), getter(), () =>
		{
			bool value = !getter();
			setter(value);
			ApplySettingsSwitch(toggle, value);
			MarkAdvancedChanged(changedName);
		});
		toggle.Size = new Vector2(34f, 20f);
		toggle.CustomMinimumSize = toggle.Size;
		return toggle;
	}

	private void MarkAdvancedChanged(string field)
	{
		if (!string.Equals(_advancedPreset, "Tùy chỉnh", StringComparison.OrdinalIgnoreCase))
		{
			_advancedPreset = "Tùy chỉnh";
			SelectOptionText(_advancedPresetSelect, "Tùy chỉnh");
		}
		SetSettingsStatus($"Đã đổi {field}. Bấm Áp dụng live hoặc Lưu & Restart.");
	}

	private void ApplyAdvancedPreset(string preset)
	{
		_advancedPreset = preset;
		switch (preset)
		{
			case "Nhanh":
				_advancedReasoningEffort = "low";
				_advancedCompletionTokens = 1024;
				_advancedChatTimeoutSeconds = 20;
				_advancedMaxConcurrency = 4;
				_advancedAutoFallback = true;
				_advancedSelfCritique = false;
				_advancedDirectorSecondPass = false;
				_advancedPromptHardCapTokens = 4200;
				_advancedPrefetchWorkers = 2;
				break;
			case "Sâu":
				_advancedReasoningEffort = "high";
				_advancedCompletionTokens = 1536;
				_advancedChatTimeoutSeconds = 45;
				_advancedMaxConcurrency = 3;
				_advancedAutoFallback = true;
				_advancedSelfCritique = true;
				_advancedDirectorSecondPass = true;
				_advancedPromptHardCapTokens = 5200;
				_advancedPrefetchWorkers = 3;
				break;
			default:
				_advancedPreset = "Cân bằng";
				_advancedReasoningEffort = "medium";
				_advancedCompletionTokens = 1280;
				_advancedChatTimeoutSeconds = 30;
				_advancedMaxConcurrency = 4;
				_advancedAutoFallback = true;
				_advancedSelfCritique = true;
				_advancedDirectorSecondPass = false;
				_advancedPromptHardCapTokens = 4800;
				_advancedPrefetchWorkers = 2;
				break;
		}
	}

	private void ResetAdvancedSettingsDefaults()
	{
		ApplyAdvancedPreset("Cân bằng");
		_advancedDdsEnabled = true;
		_advancedStrictGrounding = true;
		_advancedMemorySemanticParser = false;
		_advancedMemoryMaintenance = true;
		_advancedMemoryMaintenanceBudget = "small";
		_advancedV3Pipeline = true;
		_advancedPerformanceActs = true;
		_advancedInterruptEnabled = true;
		_advancedStageProtocol = true;
		_advancedSegmentTts = true;
		_advancedSegmentDispatch = "inline";
		_advancedTtsTaskManager = true;
		_advancedMaxTtsSegments = 4;
		_advancedStageLocalize = true;
		_advancedAudioPolish = true;
		BuildSettingsPanelUi();
		SetSettingsStatus("Đã khôi phục mặc định Advanced trong bản nháp. Bấm Lưu để ghi.");
	}

	private void SyncAdvancedSettingsInputsToFields()
	{
		if (_advancedPresetSelect != null && _advancedPresetSelect.Selected >= 0)
			_advancedPreset = _advancedPresetSelect.GetItemText(_advancedPresetSelect.Selected);
		if (_advancedReasoningSelect != null && _advancedReasoningSelect.Selected >= 0)
			_advancedReasoningEffort = _advancedReasoningSelect.GetItemText(_advancedReasoningSelect.Selected);
		if (_advancedCompletionSelect != null && _advancedCompletionSelect.Selected >= 0)
			_advancedCompletionTokens = ParseAdvancedInt(_advancedCompletionSelect.GetItemText(_advancedCompletionSelect.Selected), _advancedCompletionTokens, 384, 2048);
		if (_advancedTimeoutSelect != null && _advancedTimeoutSelect.Selected >= 0)
			_advancedChatTimeoutSeconds = ParseAdvancedInt(_advancedTimeoutSelect.GetItemText(_advancedTimeoutSelect.Selected), _advancedChatTimeoutSeconds, 5, 120);
		if (_advancedConcurrencySelect != null && _advancedConcurrencySelect.Selected >= 0)
			_advancedMaxConcurrency = ParseAdvancedInt(_advancedConcurrencySelect.GetItemText(_advancedConcurrencySelect.Selected), _advancedMaxConcurrency, 1, 16);
		if (_advancedPromptCapSelect != null && _advancedPromptCapSelect.Selected >= 0)
			_advancedPromptHardCapTokens = ParseAdvancedInt(_advancedPromptCapSelect.GetItemText(_advancedPromptCapSelect.Selected), _advancedPromptHardCapTokens, 1024, 12000);
		if (_advancedMaintenanceBudgetSelect != null && _advancedMaintenanceBudgetSelect.Selected >= 0)
			_advancedMemoryMaintenanceBudget = _advancedMaintenanceBudgetSelect.GetItemText(_advancedMaintenanceBudgetSelect.Selected);
		if (_advancedDispatchSelect != null && _advancedDispatchSelect.Selected >= 0)
			_advancedSegmentDispatch = _advancedDispatchSelect.GetItemText(_advancedDispatchSelect.Selected);
		if (_advancedPrefetchWorkersSelect != null && _advancedPrefetchWorkersSelect.Selected >= 0)
			_advancedPrefetchWorkers = ParseAdvancedInt(_advancedPrefetchWorkersSelect.GetItemText(_advancedPrefetchWorkersSelect.Selected), _advancedPrefetchWorkers, 1, 8);
		if (_advancedMaxSegmentsSelect != null && _advancedMaxSegmentsSelect.Selected >= 0)
			_advancedMaxTtsSegments = ParseAdvancedInt(_advancedMaxSegmentsSelect.GetItemText(_advancedMaxSegmentsSelect.Selected), _advancedMaxTtsSegments, 1, 12);
	}

	private void LoadAdvancedSettingsState(JsonElement root)
	{
		_advancedPreset = ReadString(root, "advanced_preset", _advancedPreset);
		_advancedReasoningEffort = ReadString(root, "reasoning_effort", _advancedReasoningEffort);
		_advancedCompletionTokens = ReadAdvancedInt(root, "completion_chat_tokens", _advancedCompletionTokens, 384, 2048);
		_advancedChatTimeoutSeconds = ReadAdvancedInt(root, "llm_chat_timeout_seconds", _advancedChatTimeoutSeconds, 5, 120);
		_advancedMaxConcurrency = ReadAdvancedInt(root, "llm_max_concurrency", _advancedMaxConcurrency, 1, 16);
		if (TryReadBool(root, "auto_fallback", out bool autoFallback)) _advancedAutoFallback = autoFallback;
		if (TryReadBool(root, "self_critique_enabled", out bool selfCritique)) _advancedSelfCritique = selfCritique;
		if (TryReadBool(root, "director_second_pass", out bool secondPass)) _advancedDirectorSecondPass = secondPass;
		_advancedPromptHardCapTokens = ReadAdvancedInt(root, "prompt_hard_cap_tokens", _advancedPromptHardCapTokens, 1024, 12000);
		if (TryReadBool(root, "dds_enabled", out bool dds)) _advancedDdsEnabled = dds;
		if (TryReadBool(root, "strict_grounding", out bool grounding)) _advancedStrictGrounding = grounding;
		if (TryReadBool(root, "memory_semantic_parser", out bool parser)) _advancedMemorySemanticParser = parser;
		if (TryReadBool(root, "memory_maintenance", out bool maintenance)) _advancedMemoryMaintenance = maintenance;
		_advancedMemoryMaintenanceBudget = ReadString(root, "memory_maintenance_budget", _advancedMemoryMaintenanceBudget);
		if (TryReadBool(root, "v3_pipeline", out bool v3)) _advancedV3Pipeline = v3;
		if (TryReadBool(root, "performance_acts_enabled", out bool performance)) _advancedPerformanceActs = performance;
		if (TryReadBool(root, "interrupt_enabled", out bool interrupt)) _advancedInterruptEnabled = interrupt;
		if (TryReadBool(root, "stage_protocol", out bool stageProtocol)) _advancedStageProtocol = stageProtocol;
		if (TryReadBool(root, "stage_segment_tts", out bool segmentTts)) _advancedSegmentTts = segmentTts;
		_advancedSegmentDispatch = ReadString(root, "tts_segment_dispatch", _advancedSegmentDispatch);
		if (TryReadBool(root, "tts_task_manager", out bool taskManager)) _advancedTtsTaskManager = taskManager;
		_advancedPrefetchWorkers = ReadAdvancedInt(root, "tts_prefetch_workers", _advancedPrefetchWorkers, 1, 8);
		_advancedMaxTtsSegments = ReadAdvancedInt(root, "stage_max_tts_segments", _advancedMaxTtsSegments, 1, 12);
		if (TryReadBool(root, "tts_stage_localize", out bool localize)) _advancedStageLocalize = localize;
		if (TryReadBool(root, "tts_audio_polish", out bool polish)) _advancedAudioPolish = polish;
	}

	private void LoadAdvancedSettingsFromSecrets(JsonElement root)
	{
		_advancedReasoningEffort = ReadSecretString(root, "ERIS_REASONING_EFFORT", _advancedReasoningEffort);
		_advancedCompletionTokens = ParseAdvancedInt(ReadSecretString(root, "ERIS_LLM_COMPLETION_CHAT_TOKENS", _advancedCompletionTokens.ToString()), _advancedCompletionTokens, 384, 2048);
		_advancedChatTimeoutSeconds = ParseAdvancedInt(ReadSecretString(root, "ERIS_LLM_TIMEOUT_CHAT_S", _advancedChatTimeoutSeconds.ToString()), _advancedChatTimeoutSeconds, 5, 120);
		_advancedMaxConcurrency = ParseAdvancedInt(ReadSecretString(root, "ERIS_LLM_MAX_CONCURRENCY", _advancedMaxConcurrency.ToString()), _advancedMaxConcurrency, 1, 16);
		_advancedAutoFallback = !IsTruthy(ReadSecretString(root, "ERIS_NO_FALLBACK_MODE", _advancedAutoFallback ? "0" : "1"));
		_advancedSelfCritique = IsTruthy(ReadSecretString(root, "ERIS_SELF_CRITIQUE_ENABLED", _advancedSelfCritique ? "1" : "0"));
		_advancedDirectorSecondPass = IsTruthy(ReadSecretString(root, "ERIS_CHAT_DIRECTOR_SECOND_PASS", _advancedDirectorSecondPass ? "1" : "0"));
		_advancedPromptHardCapTokens = ParseAdvancedInt(ReadSecretString(root, "ERIS_LLM_PROMPT_HARD_CAP_TOKENS", _advancedPromptHardCapTokens.ToString()), _advancedPromptHardCapTokens, 1024, 12000);
		_advancedDdsEnabled = IsTruthy(ReadSecretString(root, "ERIS_DDS_ENABLED", _advancedDdsEnabled ? "1" : "0"));
		_advancedStrictGrounding = IsTruthy(ReadSecretString(root, "ERIS_STRICT_GROUNDING", _advancedStrictGrounding ? "1" : "0"));
		_advancedMemorySemanticParser = IsTruthy(ReadSecretString(root, "ERIS_MEMORY_SEMANTIC_PARSER", _advancedMemorySemanticParser ? "1" : "0"));
		_advancedMemoryMaintenance = IsTruthy(ReadSecretString(root, "ERIS_MEMORY_DIGEST_MAINTENANCE", _advancedMemoryMaintenance ? "1" : "0"));
		_advancedMemoryMaintenanceBudget = ReadSecretString(root, "ERIS_MEMORY_MAINTENANCE_BUDGET", _advancedMemoryMaintenanceBudget);
		_advancedV3Pipeline = IsTruthy(ReadSecretString(root, "ERIS_V3_PIPELINE", _advancedV3Pipeline ? "1" : "0"));
		_advancedPerformanceActs = IsTruthy(ReadSecretString(root, "ERIS_PERFORMANCE_ACTS_ENABLED", _advancedPerformanceActs ? "1" : "0"));
		_advancedInterruptEnabled = IsTruthy(ReadSecretString(root, "ERIS_INTERRUPT_ENABLED", _advancedInterruptEnabled ? "1" : "0"));
		_advancedStageProtocol = IsTruthy(ReadSecretString(root, "ERIS_STAGE_PROTOCOL", _advancedStageProtocol ? "1" : "0"));
		_advancedSegmentTts = IsTruthy(ReadSecretString(root, "ERIS_STAGE_SEGMENT_TTS", _advancedSegmentTts ? "1" : "0"));
		_advancedSegmentDispatch = ReadSecretString(root, "ERIS_TTS_SEGMENT_DISPATCH", _advancedSegmentDispatch);
		_advancedTtsTaskManager = IsTruthy(ReadSecretString(root, "ERIS_TTS_TASK_MANAGER", _advancedTtsTaskManager ? "1" : "0"));
		_advancedPrefetchWorkers = ParseAdvancedInt(ReadSecretString(root, "ERIS_TTS_PREFETCH_WORKERS", _advancedPrefetchWorkers.ToString()), _advancedPrefetchWorkers, 1, 8);
		_advancedMaxTtsSegments = ParseAdvancedInt(ReadSecretString(root, "ERIS_STAGE_MAX_TTS_SEGMENTS", _advancedMaxTtsSegments.ToString()), _advancedMaxTtsSegments, 1, 12);
		_advancedStageLocalize = IsTruthy(ReadSecretString(root, "ERIS_TTS_STAGE_LOCALIZE", _advancedStageLocalize ? "1" : "0"));
		_advancedAudioPolish = IsTruthy(ReadSecretString(root, "ERIS_TTS_AUDIO_POLISH", _advancedAudioPolish ? "1" : "0"));
	}

	private void AddAdvancedSettingsToState(JsonObject state)
	{
		state["advanced_preset"] = _advancedPreset;
		state["reasoning_effort"] = _advancedReasoningEffort;
		state["completion_chat_tokens"] = _advancedCompletionTokens;
		state["llm_chat_timeout_seconds"] = _advancedChatTimeoutSeconds;
		state["llm_max_concurrency"] = _advancedMaxConcurrency;
		state["auto_fallback"] = _advancedAutoFallback;
		state["self_critique_enabled"] = _advancedSelfCritique;
		state["director_second_pass"] = _advancedDirectorSecondPass;
		state["prompt_hard_cap_tokens"] = _advancedPromptHardCapTokens;
		state["dds_enabled"] = _advancedDdsEnabled;
		state["strict_grounding"] = _advancedStrictGrounding;
		state["memory_semantic_parser"] = _advancedMemorySemanticParser;
		state["memory_maintenance"] = _advancedMemoryMaintenance;
		state["memory_maintenance_budget"] = _advancedMemoryMaintenanceBudget;
		state["v3_pipeline"] = _advancedV3Pipeline;
		state["performance_acts_enabled"] = _advancedPerformanceActs;
		state["interrupt_enabled"] = _advancedInterruptEnabled;
		state["stage_protocol"] = _advancedStageProtocol;
		state["stage_segment_tts"] = _advancedSegmentTts;
		state["tts_segment_dispatch"] = _advancedSegmentDispatch;
		state["tts_task_manager"] = _advancedTtsTaskManager;
		state["tts_prefetch_workers"] = _advancedPrefetchWorkers;
		state["stage_max_tts_segments"] = _advancedMaxTtsSegments;
		state["tts_stage_localize"] = _advancedStageLocalize;
		state["tts_audio_polish"] = _advancedAudioPolish;
	}

	private Dictionary<string, string> BuildAdvancedEnvironmentValues()
	{
		return new Dictionary<string, string>(StringComparer.Ordinal)
		{
			["ERIS_REASONING_EFFORT"] = NormalizeAdvancedReasoning(_advancedReasoningEffort),
			["ERIS_LLM_COMPLETION_CHAT_TOKENS"] = _advancedCompletionTokens.ToString(),
			["ERIS_LLM_TIMEOUT_CHAT_S"] = _advancedChatTimeoutSeconds.ToString(),
			["ERIS_LLM_MAX_CONCURRENCY"] = _advancedMaxConcurrency.ToString(),
			["ERIS_NO_FALLBACK_MODE"] = _advancedAutoFallback ? "0" : "1",
			["ERIS_SELF_CRITIQUE_ENABLED"] = _advancedSelfCritique ? "1" : "0",
			["ERIS_CHAT_DIRECTOR_SECOND_PASS"] = _advancedDirectorSecondPass ? "1" : "0",
			["ERIS_LLM_PROMPT_TOTAL_TOKENS"] = _advancedPromptHardCapTokens.ToString(),
			["ERIS_LLM_PROMPT_HARD_CAP_TOKENS"] = _advancedPromptHardCapTokens.ToString(),
			["ERIS_DDS_ENABLED"] = _advancedDdsEnabled ? "1" : "0",
			["ERIS_STRICT_GROUNDING"] = _advancedStrictGrounding ? "1" : "0",
			["ERIS_MEMORY_SEMANTIC_PARSER"] = _advancedMemorySemanticParser ? "1" : "0",
			["ERIS_MEMORY_DIGEST_MAINTENANCE"] = _advancedMemoryMaintenance ? "1" : "0",
			["ERIS_MEMORY_MAINTENANCE_BUDGET"] = NormalizeAdvancedMaintenanceBudget(_advancedMemoryMaintenanceBudget),
			["ERIS_V3_PIPELINE"] = _advancedV3Pipeline ? "1" : "0",
			["ERIS_PERFORMANCE_ACTS_ENABLED"] = _advancedPerformanceActs ? "1" : "0",
			["ERIS_INTERRUPT_ENABLED"] = _advancedInterruptEnabled ? "1" : "0",
			["ERIS_STAGE_PROTOCOL"] = _advancedStageProtocol ? "1" : "0",
			["ERIS_STAGE_SEGMENT_TTS"] = _advancedSegmentTts ? "1" : "0",
			["ERIS_TTS_SEGMENT_DISPATCH"] = NormalizeAdvancedDispatch(_advancedSegmentDispatch),
			["ERIS_TTS_TASK_MANAGER"] = _advancedTtsTaskManager ? "1" : "0",
			["ERIS_TTS_PREFETCH_WORKERS"] = _advancedPrefetchWorkers.ToString(),
			["ERIS_STAGE_MAX_TTS_SEGMENTS"] = _advancedMaxTtsSegments.ToString(),
			["ERIS_TTS_STAGE_LOCALIZE"] = _advancedStageLocalize ? "1" : "0",
			["ERIS_TTS_AUDIO_POLISH"] = _advancedAudioPolish ? "1" : "0",
		};
	}

	private void WriteAdvancedSettingsToSecrets(JsonObject env)
	{
		foreach (var pair in BuildAdvancedEnvironmentValues())
			env[pair.Key] = pair.Value;
	}

	private void AppendAdvancedSettingsToDotEnv(Dictionary<string, string> updates)
	{
		foreach (var pair in BuildAdvancedEnvironmentValues())
			updates[pair.Key] = pair.Value;
	}

	private void ApplyAdvancedSettingsLive()
	{
		SyncAdvancedSettingsInputsToFields();
		SaveSettingsState(false, writeSecrets: true);
		SendAdvancedRuntimeSettingsUpdate();
	}

	private void SendAdvancedRuntimeSettingsUpdate()
	{
		if (_chatSend == null)
		{
			SetSettingsStatus("Chưa có UDP transport; đã lưu file nhưng chưa áp dụng live.");
			return;
		}
		var payload = new
		{
			type = "settings_update",
			scope = "advanced",
			advanced_env = BuildAdvancedEnvironmentValues(),
		};
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		SetSettingsStatus(error == Error.Ok
			? "Đã gửi Advanced xuống Brain. Chờ xác nhận; vài mục vẫn cần restart."
			: $"Không gửi được Advanced live: {error}");
	}

	private void OpenAdvancedMemoryDirectory()
	{
		try
		{
			string memoryDir = Path.Combine(GetRuntimeBaseDirForSettings(), "memory_core");
			Directory.CreateDirectory(memoryDir);
			OS.ShellOpen(memoryDir);
			SetSettingsStatus($"Đã mở memory: {memoryDir}");
		}
		catch (Exception ex)
		{
			SetSettingsStatus($"Không mở được memory: {ex.Message}");
		}
	}

	private static int ReadAdvancedInt(JsonElement root, string name, int fallback, int min, int max)
	{
		if (!root.TryGetProperty(name, out JsonElement item))
			return fallback;
		if (item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out int number))
			return Math.Clamp(number, min, max);
		if (item.ValueKind == JsonValueKind.String)
			return ParseAdvancedInt(item.GetString(), fallback, min, max);
		return fallback;
	}

	private static int ParseAdvancedInt(string value, int fallback, int min, int max)
	{
		return int.TryParse(value, out int parsed) ? Math.Clamp(parsed, min, max) : fallback;
	}

	private static string NormalizeAdvancedReasoning(string value)
	{
		string normalized = (value ?? "").Trim().ToLowerInvariant();
		return normalized is "low" or "medium" or "high" ? normalized : "medium";
	}

	private static string NormalizeAdvancedMaintenanceBudget(string value)
	{
		string normalized = (value ?? "").Trim().ToLowerInvariant();
		return normalized is "small" or "medium" or "large" ? normalized : "small";
	}

	private static string NormalizeAdvancedDispatch(string value)
	{
		string normalized = (value ?? "").Trim().ToLowerInvariant();
		return normalized == "queued" ? "queued" : "inline";
	}
}
