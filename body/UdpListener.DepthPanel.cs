using Godot;
using System;
using System.Collections.Generic;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	// Panel cũ "Chiều sâu" từng phụ thuộc Ni/Fe/ToM legacy. Từ Architecture C v5,
	// nó trở thành bảng Identity & Life Runtime, đọc đúng một contract
	// identity_runtime. Tên method/field cũ được giữ để không làm vỡ UdpListener.
	private static readonly Vector2 DepthPanelMinSize = new(1120f, 760f);
	private const float DepthPanelMargin = 24f;

	private Panel _depthPanel;
	private Button _contextDepthButton;
	private VBoxContainer _depthContentList;
	private Label _depthTitleLabel;
	private Label _depthStatusLabel;
	private Label _depthLearningChip;
	private Label _depthTurnChip;
	private Button _depthFreezeButton;
	private readonly List<Button> _depthTabButtons = new();
	private string _depthActiveTab = "overview";
	private bool _depthLearningEnabled = true;

	private static readonly Color IdentityInk = new(0.20f, 0.16f, 0.25f, 1f);
	private static readonly Color IdentityMuted = new(0.44f, 0.39f, 0.49f, 1f);
	private static readonly Color IdentityAccent = new(0.76f, 0.30f, 0.56f, 1f);
	private static readonly Color IdentityAccentSoft = new(0.97f, 0.87f, 0.92f, 1f);
	private static readonly Color IdentityCard = new(1f, 0.985f, 0.992f, 0.98f);
	private static readonly Color IdentityBorder = new(0.91f, 0.72f, 0.82f, 1f);

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
		float width = Mathf.Min(DepthPanelMinSize.X, Mathf.Max(480f, viewport.X - DepthPanelMargin * 2f));
		float height = Mathf.Min(DepthPanelMinSize.Y, Mathf.Max(420f, viewport.Y - DepthPanelMargin * 2f));
		_depthPanel.Size = new Vector2(width, height);
		_depthPanel.Position = new Vector2(
			Mathf.Max(0f, (viewport.X - width) * 0.5f),
			Mathf.Max(0f, (viewport.Y - height) * 0.5f));
		RefreshDepthPanel();
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
			BgColor = new Color(0.985f, 0.96f, 0.975f, 0.985f),
			BorderColor = IdentityBorder,
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 22,
			CornerRadiusTopRight = 22,
			CornerRadiusBottomLeft = 22,
			CornerRadiusBottomRight = 22,
			ShadowColor = new Color(0.30f, 0.12f, 0.22f, 0.22f),
			ShadowSize = 12,
		});

		var root = new VBoxContainer
		{
			Name = "IdentityRuntimeRoot",
			OffsetLeft = 22f,
			OffsetTop = 18f,
			OffsetRight = -22f,
			OffsetBottom = -18f,
		};
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.AddThemeConstantOverride("separation", 10);
		_depthPanel.AddChild(root);

		var header = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 60f) };
		header.AddThemeConstantOverride("separation", 10);
		root.AddChild(header);

		var titleBlock = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_depthTitleLabel = NewLabel("IDENTITY & LIFE RUNTIME", 24, IdentityInk, true);
		_depthStatusLabel = NewLabel("Đang chờ snapshot Architecture C…", 11, IdentityMuted, false);
		titleBlock.AddChild(_depthTitleLabel);
		titleBlock.AddChild(_depthStatusLabel);
		header.AddChild(titleBlock);

		_depthLearningChip = NewChip("LEARNING ?", IdentityAccentSoft, IdentityAccent);
		_depthTurnChip = NewChip("TURN 0", new Color(0.91f, 0.94f, 1f, 1f), new Color(0.30f, 0.43f, 0.72f, 1f));
		header.AddChild(_depthLearningChip);
		header.AddChild(_depthTurnChip);

		var close = NewButton("Đóng", () => _depthPanel.Visible = false, danger: false);
		close.CustomMinimumSize = new Vector2(82f, 38f);
		header.AddChild(close);

		var tabs = new HBoxContainer();
		tabs.AddThemeConstantOverride("separation", 6);
		root.AddChild(tabs);
		_depthTabButtons.Clear();
		AddDepthTab(tabs, "overview", "Tổng quan");
		AddDepthTab(tabs, "identity", "Giá trị & động cơ");
		AddDepthTab(tabs, "relationship", "Quan hệ & belief");
		AddDepthTab(tabs, "discovery", "Discovery & chủ động");
		AddDepthTab(tabs, "audit", "Ledger & imprint");

		var scroll = new ScrollContainer
		{
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
		};
		root.AddChild(scroll);
		_depthContentList = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkBegin,
		};
		_depthContentList.AddThemeConstantOverride("separation", 10);
		scroll.AddChild(_depthContentList);

		var controls = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 46f) };
		controls.AddThemeConstantOverride("separation", 8);
		root.AddChild(controls);
		_depthFreezeButton = NewButton("Đóng băng học", ToggleIdentityLearning, danger: false);
		controls.AddChild(_depthFreezeButton);
		controls.AddChild(NewButton("Xuất snapshot", () => SendDebugCommand("identity snapshot"), danger: false));
		controls.AddChild(NewButton("Reset mood", () => SendDebugCommand("identity reset mood"), danger: false));
		controls.AddChild(NewButton("Reset quan hệ", () => SendDebugCommand("identity reset relationship"), danger: true));
		controls.AddChild(NewButton("Reset discovery", () => SendDebugCommand("identity reset discovery"), danger: true));

		var spacer = new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		controls.AddChild(spacer);
		controls.AddChild(NewChip("single writer", new Color(0.92f, 0.97f, 0.94f, 1f), new Color(0.25f, 0.56f, 0.38f, 1f)));

		RefreshDepthTabStyle();
		RefreshDepthPanel();
	}

	private void AddDepthTab(HBoxContainer parent, string key, string label)
	{
		var button = NewButton(label, () =>
		{
			_depthActiveTab = key;
			RefreshDepthTabStyle();
			RefreshDepthPanel();
		}, danger: false);
		button.SetMeta("identity_tab", key);
		button.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_depthTabButtons.Add(button);
		parent.AddChild(button);
	}

	private void RefreshDepthTabStyle()
	{
		foreach (Button button in _depthTabButtons)
		{
			string key = button.HasMeta("identity_tab") ? button.GetMeta("identity_tab").AsString() : "";
			bool active = string.Equals(key, _depthActiveTab, StringComparison.Ordinal);
			button.AddThemeColorOverride("font_color", active ? Colors.White : IdentityInk);
			button.AddThemeColorOverride("font_hover_color", active ? Colors.White : IdentityInk);
			button.AddThemeStyleboxOverride("normal", ButtonStyle(active ? IdentityAccent : new Color(1f, 0.96f, 0.98f, 1f), active ? IdentityAccent : IdentityBorder));
			button.AddThemeStyleboxOverride("hover", ButtonStyle(active ? new Color(0.70f, 0.24f, 0.50f, 1f) : IdentityAccentSoft, IdentityAccent));
			button.AddThemeStyleboxOverride("pressed", ButtonStyle(IdentityAccent, IdentityAccent));
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
				? "Compatibility snapshot · nên cập nhật Python nếu thiếu identity_runtime"
				: architecture;

			switch (_depthActiveTab)
			{
				case "identity": RenderIdentityTab(root); break;
				case "relationship": RenderRelationshipTab(root); break;
				case "discovery": RenderDiscoveryTab(root); break;
				case "audit": RenderAuditTab(root); break;
				default: RenderOverviewTab(root); break;
			}
		}
		catch (Exception ex)
		{
			AddInfoCard("Không đọc được snapshot", new[] { ex.Message, "Raw state vẫn được giữ để gói sau có thể sửa lại." });
		}
	}

	private void RenderOverviewTab(JsonElement root)
	{
		JsonElement summary = Obj(root, "summary");
		AddInfoCard("Trạng thái hiện tại", new[]
		{
			$"Mood: {ReadString(summary, "mood")} · valence {ReadFloat(summary, "valence"):0.00} · arousal {ReadFloat(summary, "arousal"):0.00}",
			ReadString(summary, "identity"),
			ReadString(summary, "relationship"),
		});

		JsonElement expression = Obj(root, "expression");
		AddInfoCard("Identity → Stage Expression", new[]
		{
			$"Preset: {ReadString(expression, "preset")} · confidence {ReadFloat(expression, "confidence"):0.00} · intensity {ReadFloat(expression, "intensity"):0.00}",
			$"Sentence bias: {ReadString(expression, "sentence_bias")} · initiative bias {ReadFloat(expression, "initiative_bias"):0.00}",
			"Lý do: " + JoinArray(expression, "reasons", 4),
		});

		AddScoreCard("Motive đang kích hoạt", Arr(root, "active_motives"), "key", "strength", 4);
		AddScoreCard("Defense vừa nổi lên", Arr(root, "active_defenses"), "key", "strength", 4);

		JsonElement conflict = Obj(root, "active_conflict");
		AddInfoCard("Mâu thuẫn nội tại", new[]
		{
			$"{ReadString(conflict, "conflict_id")} · activation {ReadFloat(conflict, "activation"):0.00}",
			$"Bên được chọn: {ReadString(conflict, "chosen_side")} · residue {ReadFloat(conflict, "residue"):0.00}",
		});

		JsonElement initiative = Obj(root, "initiative");
		JsonElement lastDecision = Obj(initiative, "last_decision");
		AddInfoCard("Ngân sách chủ động", new[]
		{
			$"Đã dùng {ReadInt(initiative, "used_last_hour")}/{ReadInt(initiative, "hourly_budget")} trong 1 giờ",
			$"Quyết định gần nhất: {(ReadBool(lastDecision, "allowed", false) ? "cho nói" : "im")} · {ReadString(lastDecision, "reason")}",
		});
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
		label.CustomMinimumSize = new Vector2(126f, 34f);
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
		ContentMarginTop = 6f,
		ContentMarginBottom = 6f,
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
