using Godot;
using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

public partial class UdpListener : Node2D
{
	// Đồng bộ cache/UI sau khi Brain đã thực thi maintenance thành công.
	// Mục tiêu: dữ liệu backend đã reset thì panel không được tiếp tục dựng từ
	// snapshot cũ trong RAM hoặc file user://. Các panel chỉ hiện baseline/chờ dữ
	// liệu mới, thay vì giữ "bóng ma" của state trước khi reset.
	[Flags]
	private enum MaintenanceUiScope
	{
		None = 0,
		Conversation = 1 << 0,
		Emotion = 1 << 1,
		PrivateMind = 1 << 2,
		Anchor = 1 << 3,
		Depth = 1 << 4,
		AnchorUserModel = 1 << 5,
		AnchorControls = 1 << 6,
	}

	private void ApplyMaintenanceResultToUi(string action, JsonElement result)
	{
		MaintenanceUiScope scope = ResolveMaintenanceUiScope(action, result);
		if (scope == MaintenanceUiScope.None)
			return;

		bool clearPrivateMind = scope.HasFlag(MaintenanceUiScope.PrivateMind);
		bool clearAnchor = scope.HasFlag(MaintenanceUiScope.Anchor);
		bool clearAnchorUserModel = scope.HasFlag(MaintenanceUiScope.AnchorUserModel);
		bool resetAnchorControls = scope.HasFlag(MaintenanceUiScope.AnchorControls);

		if (scope.HasFlag(MaintenanceUiScope.Conversation))
			ResetConversationSurfaceUi();
		if (scope.HasFlag(MaintenanceUiScope.Emotion))
			ResetEmotionUi();
		if (clearPrivateMind || clearAnchor || clearAnchorUserModel || resetAnchorControls)
			ResetPrivateMindAndAnchorUi(
				clearPrivateMind,
				clearAnchor,
				clearAnchorUserModel,
				resetAnchorControls);
		if (scope.HasFlag(MaintenanceUiScope.Depth))
			ResetDepthUi();

		RunLogger.LogStructured(
			"DangerZone.ui_sync",
			JsonSerializer.Serialize(new
			{
				action,
				scope = scope.ToString(),
				private_mind_cache = string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson) ? "cleared" : "sanitized",
				depth_cache = string.IsNullOrWhiteSpace(_latestDepthV2Json) ? "cleared" : "retained",
			}));
	}

	private static MaintenanceUiScope ResolveMaintenanceUiScope(string action, JsonElement result)
	{
		string normalized = (action ?? "").Trim().ToLowerInvariant();
		MaintenanceUiScope scope = normalized switch
		{
			"refresh_conversation" => MaintenanceUiScope.Conversation | MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Depth,
			"cancel_pending" => MaintenanceUiScope.Conversation,
			"reset_session_affect" => MaintenanceUiScope.Emotion | MaintenanceUiScope.Depth,
			"reset_runtime_relationship" => MaintenanceUiScope.Emotion | MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Depth,
			"reset_user_model" => MaintenanceUiScope.PrivateMind | MaintenanceUiScope.AnchorUserModel | MaintenanceUiScope.Depth,
			"reset_long_term_relationship" => MaintenanceUiScope.Emotion | MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Anchor | MaintenanceUiScope.Depth,
			"clear_repair_history" => MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Depth,
			"reset_private_mind" => MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Depth,
			"reset_private_life" => MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Depth,
			"reset_anchor_state" => MaintenanceUiScope.AnchorControls,
			"factory_reset" => MaintenanceUiScope.Conversation | MaintenanceUiScope.Emotion | MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Anchor | MaintenanceUiScope.Depth,
			_ => MaintenanceUiScope.None,
		};

		// Hàng rào tương thích: nếu backend cũ/nhánh khác trả action chung nhưng
		// changed cho biết rõ state nào bị đụng, vẫn làm sạch đúng panel.
		if (result.ValueKind == JsonValueKind.Object
			&& result.TryGetProperty("changed", out JsonElement changed)
			&& changed.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in changed.EnumerateArray())
			{
				string value = item.ValueKind == JsonValueKind.String ? item.GetString() ?? "" : "";
				string key = value.Trim().ToLowerInvariant();
				if (key.Length == 0)
					continue;

				if (key.Contains("chat_history", StringComparison.Ordinal)
					|| key.Contains("conversation_context", StringComparison.Ordinal)
					|| key.Contains("interrupt_ledger", StringComparison.Ordinal)
					|| key.Contains("tts_pending", StringComparison.Ordinal))
					scope |= MaintenanceUiScope.Conversation;

				if (key.Contains("internal_state.affect", StringComparison.Ordinal)
					|| key.Contains("relationship_runtime", StringComparison.Ordinal)
					|| key.Contains("affective_residue", StringComparison.Ordinal))
					scope |= MaintenanceUiScope.Emotion | MaintenanceUiScope.Depth;

				if (key.Contains("private_mind", StringComparison.Ordinal)
					|| key.Contains("inner_diary", StringComparison.Ordinal)
					|| key.Contains("thought_stream", StringComparison.Ordinal)
					|| key.Contains("private_life", StringComparison.Ordinal)
					|| key.Contains("repair", StringComparison.Ordinal))
					scope |= MaintenanceUiScope.PrivateMind | MaintenanceUiScope.Depth;

				if (key.Contains("user_model", StringComparison.Ordinal)
					|| key.Contains("epistemic", StringComparison.Ordinal)
					|| key.Contains("tom_history", StringComparison.Ordinal))
					scope |= MaintenanceUiScope.AnchorUserModel | MaintenanceUiScope.Depth;

				if (key.Contains("anchor_author_controls", StringComparison.Ordinal))
					scope |= MaintenanceUiScope.AnchorControls;

				if (key.Contains("anchor_store", StringComparison.Ordinal)
					|| key.Equals("relational", StringComparison.Ordinal)
					|| key.Contains("relational_memory", StringComparison.Ordinal))
					scope |= MaintenanceUiScope.Anchor | MaintenanceUiScope.Depth;
			}
		}

		return scope;
	}

	private void ResetConversationSurfaceUi()
	{
		if (_textTween != null && _textTween.IsValid())
			_textTween.Kill();
		_textTween = null;
		_bubbleHideAtMs = 0;
		if (_bubble != null)
			_bubble.Visible = false;
		if (_label != null)
		{
			_label.Text = "";
			_label.VisibleCharacters = -1;
		}
		if (_chatInput != null)
			_chatInput.Text = "";

		_bodyTimelineQueue.Clear();
		_bodyTimelineStartedAtMs = 0;
		_bodyTimelineActiveUntilMs = 0;
		_bodyTimelineTurnId = "";
	}

	private void ResetEmotionUi()
	{
		_latestEmotionDebug = null;
		_moodDotValence = 0f;
		_moodDotArousal = 0f;
		_moodStateName = "";
		_moodStateDesc = "";
		_moodDotCanvas?.QueueRedraw();

		if (_casualNarrativeLabel != null)
			_casualNarrativeLabel.Text = "\"Chưa có frame cảm xúc.\"";
		for (int i = 0; i < _casualBars.Count && i < CasualBarDefs.Length; i++)
			UpdateCasualBar(i, 0f, CasualBarDefs[i].Levels);

		if (_devItemList != null && _devHeaderLabel != null)
			RefreshDevMode();

		if (_emotionSummaryLabel != null)
			_emotionSummaryLabel.Text = "Cảm xúc";
		if (_emotionHintLabel != null)
			_emotionHintLabel.Text = "Chưa có frame cảm xúc.";
		if (_emotionText != null)
			_emotionText.Text = "[i]Chưa có frame cảm xúc.[/i]";

		for (int i = 0; i < _emotionRows.Count && i < EmotionPanelSlots.Length; i++)
		{
			EmotionPanelSlot slot = EmotionPanelSlots[i];
			UpdateEmotionRow(_emotionRows[i], slot.Title, slot.Note, 0f);
		}

		// Sidebar mood của panel nội tâm dùng cùng emotion frame; refresh để nó
		// không tiếp tục hiện valence/arousal cũ.
		if (_privateMindSectionList != null && _privateMindText != null)
			RefreshPrivateMindPanel();
	}

	private void ResetPrivateMindAndAnchorUi(
		bool clearPrivateMind,
		bool clearAnchor,
		bool clearAnchorUserModel,
		bool resetAnchorControls)
	{
		// reset_anchor_state chỉ reset switch/override của Tác Giả. Không được xóa
		// significance, attachment hay user model vốn không bị backend đụng tới.
		if (resetAnchorControls && !clearAnchor && !clearAnchorUserModel && !clearPrivateMind)
		{
			_latestPrivateMindDebugJson = ApplyAnchorControlsBaselineToCache(_latestPrivateMindDebugJson);
			PersistPrivateMindCacheAfterMaintenance();
			_anchorSwitchOverrides.Clear();
			ApplyAnchorResetAfterMaintenance();
			return;
		}

		_latestPrivateMindDebugJson = SanitizePrivateMindCache(
			_latestPrivateMindDebugJson,
			clearPrivateMind,
			clearAnchor,
			clearAnchorUserModel);

		PersistPrivateMindCacheAfterMaintenance();

		if (clearPrivateMind)
		{
			_diaryConcernData.Clear();
			_diaryConcernExpanded = false;
			if (_privateMindSectionList != null && _privateMindText != null)
				RefreshPrivateMindPanel();
		}

		if (clearAnchor || clearAnchorUserModel || resetAnchorControls)
		{
			_anchorSwitchOverrides.Clear();
			_anchorData = new AnchorData();
			if (resetAnchorControls && !clearAnchor)
				ApplyAnchorResetAfterMaintenance();
			else if (_anchorContent != null && _anchorRail != null)
				RefreshAnchorPanel();
		}
	}

	private static string SanitizePrivateMindCache(
		string raw,
		bool clearPrivateMind,
		bool clearAnchor,
		bool clearAnchorUserModel)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return "";
		if (clearPrivateMind && clearAnchor)
			return "";

		try
		{
			JsonNode rootNode = JsonNode.Parse(raw);
			if (rootNode is not JsonObject root)
				return "";

			JsonObject digest = SelectPrivateMindDigestNode(root);
			if (digest == null)
				return clearPrivateMind ? "" : raw;

			if (clearPrivateMind)
			{
				if (digest["anchor"] is not JsonObject anchorObject)
					return "";

				JsonObject keptAnchor = CloneJsonNode(anchorObject) as JsonObject;
				if (keptAnchor == null)
					return "";
				if (clearAnchorUserModel)
					keptAnchor.Remove("user_model");

				return new JsonObject
				{
					["anchor"] = keptAnchor,
				}.ToJsonString();
			}

			if (clearAnchor)
				digest.Remove("anchor");
			else if (clearAnchorUserModel && digest["anchor"] is JsonObject anchor)
				anchor.Remove("user_model");

			return root.ToJsonString();
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[DangerZone][UI] Không sanitize được private-mind cache: {ex.Message}");
			return "";
		}
	}

	private static string ApplyAnchorControlsBaselineToCache(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return "";

		try
		{
			JsonNode rootNode = JsonNode.Parse(raw);
			if (rootNode is not JsonObject root)
				return raw;

			JsonObject digest = SelectPrivateMindDigestNode(root);
			if (digest?["anchor"] is not JsonObject anchor)
				return raw;

			JsonObject switches = anchor["switches"] as JsonObject ?? new JsonObject();
			anchor["switches"] = switches;
			switches["shadow_enabled"] = false;
			switches["deception_enabled"] = false;
			switches["strict_grounding"] = true;
			switches["safe_mode"] = true;
			return root.ToJsonString();
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[DangerZone][UI] Không cập nhật được anchor switch cache: {ex.Message}");
			return raw;
		}
	}

	private static JsonObject SelectPrivateMindDigestNode(JsonObject root)
	{
		if (root["private_mind_digest"] is JsonObject wrapped)
			return wrapped;
		if (root["emotion_debug"] is JsonObject emotion
			&& emotion["private_mind"] is JsonObject privateMind)
			return privateMind;
		return root;
	}

	private static JsonNode CloneJsonNode(JsonNode node)
	{
		return node == null ? null : JsonNode.Parse(node.ToJsonString());
	}

	private void PersistPrivateMindCacheAfterMaintenance()
	{
		if (string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson))
		{
			DeleteUserStateFile(PrivateMindStatePath);
			return;
		}

		try
		{
			using Godot.FileAccess file = Godot.FileAccess.Open(PrivateMindStatePath, Godot.FileAccess.ModeFlags.Write);
			file?.StoreString(_latestPrivateMindDebugJson);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[DangerZone][UI] Không ghi lại private-mind cache đã sanitize: {ex.Message}");
		}
	}

	private void ResetDepthUi()
	{
		_latestDepthV2Json = "";
		DeleteUserStateFile(DepthV2StatePath);
		if (_depthPanelContentRoot != null || _depthPanel != null)
			RefreshDepthPanel();
	}

	private static void DeleteUserStateFile(string userPath)
	{
		if (string.IsNullOrWhiteSpace(userPath))
			return;
		try
		{
			string absolute = ProjectSettings.GlobalizePath(userPath);
			if (File.Exists(absolute))
				File.Delete(absolute);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[DangerZone][UI] Không xóa được cache {userPath}: {ex.Message}");
		}
	}
}
