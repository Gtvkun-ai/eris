using Godot;
using System;
using System.Collections.Generic;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

public partial class UdpListener : Node2D
{
	// Danger Zone không phải một nhóm setting. Đây là command center bảo trì:
	// mỗi thao tác được preview ở Brain, nhận confirmation token rồi mới execute.
	private Label _dangerCatalogStatusLabel;
	private Label _dangerVocalCacheLabel;
	private Label _dangerProviderHealthLabel;
	private Label _dangerSemanticIndexLabel;
	private ConfirmationDialog _dangerConfirmDialog;
	private Label _dangerConfirmSummaryLabel;
	private Label _dangerConfirmPhraseHintLabel;
	private LineEdit _dangerConfirmInput;
	private Button _dangerConfirmButton;
	private string _dangerPendingAction = "";
	private string _dangerPendingToken = "";
	private string _dangerPendingPhrase = "";
	private JsonObject _dangerPendingOptions = new();

	private static readonly Color DangerRed = new(0.72f, 0.12f, 0.22f);
	private static readonly Color DangerRedSoft = new(1.00f, 0.89f, 0.91f, 0.92f);
	private static readonly Color DangerAmber = new(0.68f, 0.36f, 0.06f);

	private void ResetDangerSettingsUiReferences()
	{
		_dangerCatalogStatusLabel = null;
		_dangerVocalCacheLabel = null;
		_dangerProviderHealthLabel = null;
		_dangerSemanticIndexLabel = null;
		_dangerConfirmDialog = null;
		_dangerConfirmSummaryLabel = null;
		_dangerConfirmPhraseHintLabel = null;
		_dangerConfirmInput = null;
		_dangerConfirmButton = null;
	}

	private void BuildDangerSettingsPage(Control root)
	{
		var intro = CreateUiLabel(
			"Chỉ reset, xóa hoặc sửa trạng thái thật. Body không tự đụng file memory; Brain sẽ backup và reset cả object trong RAM.",
			12,
			DangerAmber);
		intro.Position = new Vector2(44f, 202f);
		intro.Size = new Vector2(1090f, 30f);
		intro.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		root.AddChild(intro);

		var sessionCard = AddSettingsCard(root, new Rect2(32f, 232f, 350f, 350f), "Phiên hiện tại");
		AddDangerActionRow(sessionCard, 52f, "Làm mới cuộc trò chuyện", "Xóa context, public/session ledger và interrupt của phiên.", "refresh_conversation", "Làm mới");
		AddDangerActionRow(sessionCard, 122f, "Hủy tác vụ đang chờ", "Hủy TTS, future nền và queue chưa phát.", "cancel_pending", "Hủy ngay");
		AddDangerActionRow(sessionCard, 192f, "Reset cảm xúc phiên", "Đưa affect/pressure về baseline, giữ quan hệ.", "reset_session_affect", "Reset");
		AddDangerActionRow(sessionCard, 262f, "Reset quan hệ runtime", "Reset state quan hệ đang chạy, chưa xóa memory dài hạn.", "reset_runtime_relationship", "Reset");

		var memoryCard = AddSettingsCard(root, new Rect2(400f, 232f, 360f, 350f), "Ký ức & quan hệ");
		AddDangerActionRow(memoryCard, 52f, "Đặt lại mô hình về Ngài", "Reset user model, epistemic user và ToM history.", "reset_user_model", "Quên mô hình");
		AddDangerActionRow(memoryCard, 132f, "Reset quan hệ dài hạn", "Xóa relational/affective memory và reset anchor.", "reset_long_term_relationship", "Reset sâu");
		AddDangerActionRow(memoryCard, 212f, "Xóa repair & xung đột", "Xóa repair memory cùng rupture/repair state hiện hành.", "clear_repair_history", "Xóa lịch sử");

		_dangerSemanticIndexLabel = CreateUiLabel("Semantic index: đang đọc…", 10, SettingsInkSoft);
		_dangerSemanticIndexLabel.Position = new Vector2(18f, 274f);
		_dangerSemanticIndexLabel.Size = new Vector2(320f, 18f);
		memoryCard.AddChild(_dangerSemanticIndexLabel);
		var reindex = CreateDangerButton("Dựng lại index", () => RequestMaintenancePreview("reindex_semantic_memory"), critical: false);
		reindex.Position = new Vector2(18f, 298f);
		reindex.Size = new Vector2(150f, 34f);
		memoryCard.AddChild(reindex);
		var exportBackup = CreateDangerButton("Xuất backup ZIP", () => RequestMaintenancePreview("export_backup"), critical: false);
		exportBackup.Position = new Vector2(178f, 298f);
		exportBackup.Size = new Vector2(164f, 34f);
		memoryCard.AddChild(exportBackup);

		var internalCard = AddSettingsCard(root, new Rect2(778f, 232f, 370f, 350f), "Nội tâm & hệ thống");
		AddDangerActionRow(internalCard, 52f, "Reset dòng suy nghĩ", "Xóa concern, thought stream, inner diary và private queue.", "reset_private_mind", "Reset");
		AddDangerActionRow(internalCard, 122f, "Reset đời sống riêng", "Đưa PrivateLifeCore về baseline, không đụng user model.", "reset_private_life", "Reset");
		AddDangerActionRow(internalCard, 192f, "Xóa Vocal Cache", "Chỉ xóa cache giọng đã sinh; preset và key được giữ.", "clear_vocal_cache", "Dọn cache");
		_dangerVocalCacheLabel = CreateUiLabel("Cache: đang đọc từ Brain…", 10, SettingsInkSoft);
		_dangerVocalCacheLabel.Position = new Vector2(18f, 246f);
		_dangerVocalCacheLabel.Size = new Vector2(160f, 18f);
		internalCard.AddChild(_dangerVocalCacheLabel);
		_dangerProviderHealthLabel = CreateUiLabel("Key pool: đang đọc…", 10, SettingsInkSoft);
		_dangerProviderHealthLabel.Position = new Vector2(176f, 246f);
		_dangerProviderHealthLabel.Size = new Vector2(176f, 18f);
		_dangerProviderHealthLabel.HorizontalAlignment = HorizontalAlignment.Right;
		internalCard.AddChild(_dangerProviderHealthLabel);

		var rotateKey = CreateDangerButton("Xoay key", () => RequestMaintenancePreview("rotate_provider_key"), critical: false);
		rotateKey.Position = new Vector2(18f, 268f);
		rotateKey.Size = new Vector2(104f, 32f);
		rotateKey.TooltipText = "Xoay key trong pool đang chọn ở Basic.";
		internalCard.AddChild(rotateKey);
		var quarantineKey = CreateDangerButton("Cách ly", () => RequestMaintenancePreview("quarantine_provider_key"), critical: false);
		quarantineKey.Position = new Vector2(130f, 268f);
		quarantineKey.Size = new Vector2(104f, 32f);
		quarantineKey.TooltipText = "Cách ly key active trong pool đang chọn; không xóa secret.";
		internalCard.AddChild(quarantineKey);
		var restoreKey = CreateDangerButton("Khôi phục", () => RequestMaintenancePreview("restore_provider_key"), critical: false);
		restoreKey.Position = new Vector2(242f, 268f);
		restoreKey.Size = new Vector2(110f, 32f);
		restoreKey.TooltipText = "Khôi phục key quarantined/cooldown đầu tiên trong pool đang chọn.";
		internalCard.AddChild(restoreKey);

		var factory = CreateDangerButton("KHÔI PHỤC TOÀN BỘ", () => RequestMaintenancePreview("factory_reset"), critical: true);
		factory.Position = new Vector2(18f, 306f);
		factory.Size = new Vector2(334f, 30f);
		factory.TooltipText = "Mặc định không xóa API key, raw event ledger, settings hoặc backup.";
		internalCard.AddChild(factory);

		var divider = new ColorRect
		{
			Color = new Color(0.82f, 0.22f, 0.30f, 0.34f),
			Position = new Vector2(32f, 604f),
			Size = new Vector2(1116f, 1.4f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		root.AddChild(divider);

		_dangerCatalogStatusLabel = CreateUiLabel("Đang kết nối maintenance service…", 11, SettingsInkSoft);
		_dangerCatalogStatusLabel.Position = new Vector2(44f, 620f);
		_dangerCatalogStatusLabel.Size = new Vector2(520f, 22f);
		root.AddChild(_dangerCatalogStatusLabel);

		_settingsStatusNoteLabel = CreateUiLabel("", 10, DangerRed);
		_settingsStatusNoteLabel.Position = new Vector2(44f, 642f);
		_settingsStatusNoteLabel.Size = new Vector2(650f, 18f);
		_settingsStatusNoteLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		root.AddChild(_settingsStatusNoteLabel);

		var refresh = CreateSettingsButton("↻ Đọc lại trạng thái", RequestMaintenanceCatalog, primary: false);
		refresh.Position = new Vector2(742f, 622f);
		refresh.Size = new Vector2(138f, 38f);
		root.AddChild(refresh);

		var openMemory = CreateSettingsButton("Mở memory", OpenAdvancedMemoryDirectory, primary: false);
		openMemory.Position = new Vector2(888f, 622f);
		openMemory.Size = new Vector2(106f, 38f);
		root.AddChild(openMemory);

		var close = CreateSettingsButton("Đóng", CloseSettingsPanel, primary: false);
		close.Position = new Vector2(1002f, 622f);
		close.Size = new Vector2(70f, 38f);
		root.AddChild(close);

		var restart = CreateSettingsButton("Restart", RestartVisionProcess, primary: true);
		restart.Position = new Vector2(1080f, 620f);
		restart.Size = new Vector2(64f, 42f);
		restart.AddThemeFontSizeOverride("font_size", 9);
		root.AddChild(restart);

		BuildDangerConfirmationDialog();
	}

	private void AddDangerActionRow(Control parent, float y, string title, string description, string action, string buttonText)
	{
		var titleLabel = CreateUiLabel(title, 13, SettingsInk);
		titleLabel.Position = new Vector2(18f, y);
		titleLabel.Size = new Vector2(200f, 22f);
		parent.AddChild(titleLabel);

		var descriptionLabel = CreateUiLabel(description, 10, SettingsInkSoft);
		descriptionLabel.Position = new Vector2(18f, y + 23f);
		descriptionLabel.Size = new Vector2(210f, 36f);
		descriptionLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		parent.AddChild(descriptionLabel);

		bool critical = action is "reset_user_model" or "reset_long_term_relationship" or "clear_repair_history" or "reset_private_mind" or "reset_private_life";
		var button = CreateDangerButton(buttonText, () => RequestMaintenancePreview(action), critical);
		button.Position = new Vector2(parent.Size.X - 124f, y + 6f);
		button.Size = new Vector2(106f, 36f);
		parent.AddChild(button);
	}

	private Button CreateDangerButton(string text, Action onPressed, bool critical)
	{
		var button = CreateSettingsButton(text, onPressed, primary: false);
		var normal = new StyleBoxFlat
		{
			BgColor = critical ? new Color(0.74f, 0.12f, 0.22f, 0.90f) : DangerRedSoft,
			BorderColor = critical ? new Color(0.98f, 0.46f, 0.53f, 0.95f) : new Color(0.88f, 0.38f, 0.46f, 0.84f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10,
			CornerRadiusTopRight = 10,
			CornerRadiusBottomLeft = 10,
			CornerRadiusBottomRight = 10,
		};
		var hover = (StyleBoxFlat)normal.Duplicate();
		hover.BgColor = critical ? new Color(0.84f, 0.16f, 0.28f, 0.96f) : new Color(1.00f, 0.82f, 0.86f, 0.96f);
		button.AddThemeStyleboxOverride("normal", normal);
		button.AddThemeStyleboxOverride("hover", hover);
		button.AddThemeStyleboxOverride("pressed", hover);
		button.AddThemeColorOverride("font_color", critical ? Colors.White : DangerRed);
		button.AddThemeColorOverride("font_hover_color", critical ? Colors.White : DangerRed);
		button.AddThemeFontSizeOverride("font_size", 10);
		return button;
	}

	private void BuildDangerConfirmationDialog()
	{
		_dangerConfirmDialog = new ConfirmationDialog
		{
			Title = "Xác nhận thao tác Danger Zone",
			Size = new Vector2I(610, 320),
			MinSize = new Vector2I(610, 320),
			OkButtonText = "Thực thi",
			CancelButtonText = "Hủy",
		};
		_dangerConfirmDialog.Confirmed += ExecutePendingMaintenance;
		_settingsPanel.AddChild(_dangerConfirmDialog);

		var content = new VBoxContainer
		{
			Position = new Vector2(24f, 58f),
			Size = new Vector2(562f, 182f),
		};
		content.AddThemeConstantOverride("separation", 10);
		_dangerConfirmDialog.AddChild(content);

		_dangerConfirmSummaryLabel = CreateUiLabel("", 13, SettingsInk);
		_dangerConfirmSummaryLabel.CustomMinimumSize = new Vector2(550f, 104f);
		_dangerConfirmSummaryLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		content.AddChild(_dangerConfirmSummaryLabel);

		_dangerConfirmPhraseHintLabel = CreateUiLabel("", 11, DangerRed);
		_dangerConfirmPhraseHintLabel.CustomMinimumSize = new Vector2(550f, 24f);
		content.AddChild(_dangerConfirmPhraseHintLabel);

		_dangerConfirmInput = new LineEdit
		{
			PlaceholderText = "Nhập câu xác nhận",
			CustomMinimumSize = new Vector2(550f, 38f),
		};
		_dangerConfirmInput.TextChanged += _ => RefreshDangerConfirmButton();
		content.AddChild(_dangerConfirmInput);

		_dangerConfirmButton = _dangerConfirmDialog.GetOkButton();
		RefreshDangerConfirmButton();
	}

	private void RequestMaintenanceCatalog()
	{
		if (_chatSend == null || _processes == null || !_processes.IsVisionRunning)
		{
			SetSettingsStatus("Brain đang dừng; không thể đọc maintenance catalog.");
			return;
		}
		var payload = new { type = "maintenance_catalog", request_id = Guid.NewGuid().ToString("N") };
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload)));
		if (error == Error.Ok)
		{
			if (_dangerCatalogStatusLabel != null)
				_dangerCatalogStatusLabel.Text = "Đang đọc trạng thái maintenance từ Brain…";
		}
		else
			SetSettingsStatus($"Không gửi được maintenance_catalog: {error}");
	}

	private void RequestMaintenancePreview(string action)
	{
		if (_chatSend == null || _processes == null || !_processes.IsVisionRunning)
		{
			SetSettingsStatus("Brain đang dừng. Khởi động Brain trước khi reset để backend khóa và đồng bộ store.");
			return;
		}

		string requestId = Guid.NewGuid().ToString("N");
		JsonObject options = BuildMaintenanceOptions(action);
		var payload = new JsonObject
		{
			["type"] = "maintenance_request",
			["request_id"] = requestId,
			["action"] = action,
			["dry_run"] = true,
			["options"] = options.DeepClone(),
		};
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(payload.ToJsonString()));
		SetSettingsStatus(error == Error.Ok ? $"Đang preview thao tác {action}…" : $"Không gửi được preview: {error}");
	}

	private JsonObject BuildMaintenanceOptions(string action)
	{
		if (string.Equals(action, "factory_reset", StringComparison.OrdinalIgnoreCase))
		{
			// Factory reset mặc định giữ settings, key, raw event ledger và backup.
			return new JsonObject
			{
				["components"] = new JsonArray(
					"refresh_conversation",
					"reset_session_affect",
					"reset_user_model",
					"reset_long_term_relationship",
					"clear_repair_history",
					"reset_private_mind",
					"reset_private_life",
					"clear_vocal_cache")
			};
		}

		if (action is "rotate_provider_key" or "quarantine_provider_key" or "restore_provider_key")
		{
			string provider = NormalizeSettingsPoolKind(_settingsKeyPoolKind);
			if (string.IsNullOrWhiteSpace(provider))
				provider = "gemini";
			_settingsKeyHealth.TryGetValue(provider, out List<SettingsKeyHealth> health);
			SettingsKeyHealth target = null;
			if (string.Equals(action, "restore_provider_key", StringComparison.OrdinalIgnoreCase))
				target = health?.Find(item => string.Equals(item.Status, "quarantined", StringComparison.OrdinalIgnoreCase))
					?? health?.Find(item => string.Equals(item.Status, "cooldown", StringComparison.OrdinalIgnoreCase));
			else
				target = health?.Find(item => item.Active);

			var options = new JsonObject { ["provider"] = provider };
			if (target != null)
			{
				options["index"] = target.Index;
				options["fingerprint"] = target.Fingerprint;
			}
			return options;
		}

		return new JsonObject();
	}

	private void TryApplyMaintenanceMessage(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw) || !raw.Contains("maintenance_", StringComparison.Ordinal))
			return;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;
			if (root.TryGetProperty("maintenance_catalog_ack", out JsonElement catalog) && catalog.ValueKind == JsonValueKind.Object)
			{
				int actions = catalog.TryGetProperty("actions", out JsonElement actionsEl) && actionsEl.ValueKind == JsonValueKind.Array ? actionsEl.GetArrayLength() : 0;
				if (_dangerCatalogStatusLabel != null)
					_dangerCatalogStatusLabel.Text = $"Brain sẵn sàng · {actions} thao tác maintenance có backend thật";
				if (catalog.TryGetProperty("provider_health", out JsonElement providerHealth) && providerHealth.ValueKind == JsonValueKind.Object)
				{
					string provider = NormalizeSettingsPoolKind(_settingsKeyPoolKind);
					if (string.IsNullOrWhiteSpace(provider)) provider = "gemini";
					if (providerHealth.TryGetProperty(provider, out JsonElement pool) && pool.ValueKind == JsonValueKind.Object)
					{
						int available = pool.TryGetProperty("available", out JsonElement availableEl) ? availableEl.GetInt32() : 0;
						int size = pool.TryGetProperty("size", out JsonElement sizeEl) ? sizeEl.GetInt32() : 0;
						if (_dangerProviderHealthLabel != null) _dangerProviderHealthLabel.Text = $"{provider}: {available}/{size} key";
					}
				}
				if (catalog.TryGetProperty("semantic_index", out JsonElement semantic) && semantic.ValueKind == JsonValueKind.Object)
				{
					bool backend = semantic.TryGetProperty("embedding_backend_ready", out JsonElement backendEl) && backendEl.ValueKind == JsonValueKind.True;
					bool supported = semantic.TryGetProperty("rebuild_supported", out JsonElement supportedEl) && supportedEl.ValueKind == JsonValueKind.True;
					if (_dangerSemanticIndexLabel != null) _dangerSemanticIndexLabel.Text = supported ? (backend ? "Semantic index: sẵn sàng" : "Semantic index: chưa có embedding backend") : "Semantic index: không hỗ trợ rebuild";
				}
				if (catalog.TryGetProperty("vocal_cache", out JsonElement cache) && cache.ValueKind == JsonValueKind.Object)
				{
					long bytes = cache.TryGetProperty("bytes", out JsonElement bytesEl) && bytesEl.TryGetInt64(out long parsed) ? parsed : 0L;
					int items = cache.TryGetProperty("items", out JsonElement itemsEl) && itemsEl.TryGetInt32(out int count) ? count : 0;
					if (_dangerVocalCacheLabel != null)
						_dangerVocalCacheLabel.Text = $"Cache: {FormatDangerBytes(bytes)} · {items} file";
				}
				return;
			}

			if ((root.TryGetProperty("maintenance_preview_ack", out JsonElement preview)
				|| root.TryGetProperty("maintenance_preview", out preview))
				&& preview.ValueKind == JsonValueKind.Object)
			{
				RunLogger.LogStructured("DangerZone.preview", preview.GetRawText());
				ShowMaintenancePreview(preview);
				return;
			}

			if ((root.TryGetProperty("maintenance_execute_ack", out JsonElement result)
				|| root.TryGetProperty("maintenance_result", out result))
				&& result.ValueKind == JsonValueKind.Object)
			{
				RunLogger.LogStructured("DangerZone.execute", result.GetRawText());
				bool ok = result.TryGetProperty("ok", out JsonElement okEl) && okEl.ValueKind == JsonValueKind.True;
				string action = result.TryGetProperty("action", out JsonElement actionEl) ? actionEl.GetString() ?? "maintenance" : "maintenance";
				int changed = result.TryGetProperty("changed", out JsonElement changedEl) && changedEl.ValueKind == JsonValueKind.Array ? changedEl.GetArrayLength() : 0;
				int errors = result.TryGetProperty("errors", out JsonElement errorsEl) && errorsEl.ValueKind == JsonValueKind.Array ? errorsEl.GetArrayLength() : 0;
				string backup = result.TryGetProperty("backup_dir", out JsonElement backupEl) ? backupEl.GetString() ?? "" : "";
				if (result.TryGetProperty("details", out JsonElement details) && details.ValueKind == JsonValueKind.Object
					&& details.TryGetProperty("backup_path", out JsonElement backupPathEl))
					backup = backupPathEl.GetString() ?? backup;
				SetSettingsStatus(ok
					? $"Đã thực thi {action}: {changed} thành phần{(string.IsNullOrWhiteSpace(backup) ? "" : " · đã tạo backup")}"
					: $"Maintenance {action} lỗi: {errors} lỗi. Xem log để biết chi tiết.");
				if (ok)
					ApplyMaintenanceResultToUi(action, result);
				RequestMaintenanceCatalog();
			}
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[DangerZone] Khong parse duoc maintenance message: {ex.Message}");
		}
	}

	private void ShowMaintenancePreview(JsonElement preview)
	{
		_dangerPendingAction = preview.TryGetProperty("action", out JsonElement actionEl) ? actionEl.GetString() ?? "" : "";
		_dangerPendingToken = preview.TryGetProperty("confirmation_token", out JsonElement tokenEl) ? tokenEl.GetString() ?? "" : "";
		string title = preview.TryGetProperty("title", out JsonElement titleEl) ? titleEl.GetString() ?? _dangerPendingAction : _dangerPendingAction;
		string description = preview.TryGetProperty("description", out JsonElement descEl) ? descEl.GetString() ?? "" : "";
		long totalBytes = preview.TryGetProperty("total_bytes", out JsonElement bytesEl) && bytesEl.TryGetInt64(out long parsed) ? parsed : 0L;
		int files = preview.TryGetProperty("affected", out JsonElement affectedEl) && affectedEl.ValueKind == JsonValueKind.Array ? affectedEl.GetArrayLength() : 0;
		bool reversible = preview.TryGetProperty("reversible", out JsonElement reversibleEl) && reversibleEl.ValueKind == JsonValueKind.True;
		bool requiresConfirmation = !preview.TryGetProperty("requires_confirmation", out JsonElement confirmEl) || confirmEl.ValueKind != JsonValueKind.False;
		_dangerPendingOptions = preview.TryGetProperty("options", out JsonElement optionsEl) && optionsEl.ValueKind == JsonValueKind.Object
			? JsonNode.Parse(optionsEl.GetRawText())?.AsObject() ?? new JsonObject()
			: new JsonObject();

		_dangerPendingPhrase = preview.TryGetProperty("typed_confirmation", out JsonElement phraseEl)
			? phraseEl.GetString() ?? DangerConfirmationPhrase(_dangerPendingAction)
			: DangerConfirmationPhrase(_dangerPendingAction);
		if (!requiresConfirmation)
		{
			SendPendingMaintenanceExecute(skipPhrase: true);
			return;
		}

		if (_dangerConfirmSummaryLabel != null)
			_dangerConfirmSummaryLabel.Text = $"{title}\n{description}\n\nẢnh hưởng: {files} đường dẫn · {FormatDangerBytes(totalBytes)}\n{(reversible ? "Backup sẽ được tạo trước khi thay đổi." : "Thao tác này không có backup tự động.")}";
		if (_dangerConfirmPhraseHintLabel != null)
			_dangerConfirmPhraseHintLabel.Text = $"Nhập chính xác: {_dangerPendingPhrase}";
		if (_dangerConfirmInput != null)
			_dangerConfirmInput.Text = "";
		RefreshDangerConfirmButton();
		_dangerConfirmDialog?.PopupCentered();
		SetSettingsStatus("Brain đã trả manifest. Kiểm tra phạm vi trước khi xác nhận.");
	}

	private string DangerConfirmationPhrase(string action) => action switch
	{
		"factory_reset" => "FACTORY RESET",
		"reset_user_model" => "FORGET USER MODEL",
		"reset_long_term_relationship" => "RESET RELATIONSHIP",
		"reset_private_mind" => "RESET PRIVATE MIND",
		"reset_private_life" => "RESET PRIVATE LIFE",
		"clear_repair_history" => "CLEAR REPAIR HISTORY",
		"clear_vocal_cache" => "CLEAR VOCAL CACHE",
		"quarantine_provider_key" => "QUARANTINE KEY",
		"reset_anchor_state" => "RESET ANCHOR",
		_ => "CONFIRM",
	};

	private void RefreshDangerConfirmButton()
	{
		if (_dangerConfirmButton == null)
			return;
		_dangerConfirmButton.Disabled = string.IsNullOrWhiteSpace(_dangerPendingToken)
			|| _dangerConfirmInput == null
			|| !string.Equals(_dangerConfirmInput.Text.Trim(), _dangerPendingPhrase, StringComparison.Ordinal);
	}

	private void ExecutePendingMaintenance()
	{
		SendPendingMaintenanceExecute(skipPhrase: false);
	}

	private void SendPendingMaintenanceExecute(bool skipPhrase)
	{
		if (_chatSend == null || string.IsNullOrWhiteSpace(_dangerPendingAction) || string.IsNullOrWhiteSpace(_dangerPendingToken))
			return;
		if (!skipPhrase && (_dangerConfirmInput == null || !string.Equals(_dangerConfirmInput.Text.Trim(), _dangerPendingPhrase, StringComparison.Ordinal)))
		{
			SetSettingsStatus("Câu xác nhận không khớp; thao tác chưa được gửi.");
			return;
		}

		var payload = new JsonObject
		{
			["type"] = "maintenance_execute",
			["request_id"] = Guid.NewGuid().ToString("N"),
			["action"] = _dangerPendingAction,
			["dry_run"] = false,
			["preview_id"] = _dangerPendingToken,
			["confirmation_token"] = _dangerPendingToken,
			["typed_confirmation"] = skipPhrase ? _dangerPendingPhrase : (_dangerConfirmInput?.Text.Trim() ?? ""),
			["options"] = _dangerPendingOptions.DeepClone(),
		};
		Error error = _chatSend.PutPacket(Encoding.UTF8.GetBytes(payload.ToJsonString()));
		SetSettingsStatus(error == Error.Ok ? $"Đã gửi lệnh {_dangerPendingAction}; Brain đang khóa và đồng bộ store…" : $"Không gửi được maintenance execute: {error}");
		_dangerPendingToken = "";
		RefreshDangerConfirmButton();
	}

	private static string FormatDangerBytes(long bytes)
	{
		if (bytes < 1024L) return $"{bytes} B";
		if (bytes < 1024L * 1024L) return $"{bytes / 1024d:0.0} KB";
		if (bytes < 1024L * 1024L * 1024L) return $"{bytes / (1024d * 1024d):0.0} MB";
		return $"{bytes / (1024d * 1024d * 1024d):0.00} GB";
	}
}
