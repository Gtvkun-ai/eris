using Godot;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.Json;
using VBox = Godot.VBoxContainer;

// ─────────────────────────────────────────────────────────────────────────────
//  MÔ HÌNH NGÀI · Theory of User — bảng debug trục neo hiện sinh.
//  Ăn data THẬT từ block "anchor" trong private_mind_digest (xem
//  PrivateMindLoop._build_anchor_block). 3 tab + thanh rail Tác Giả cố định.
//  Code-first: mọi icon đi qua khe asset-or-fallback (CreateDiaryGlyph) nên
//  thả PNG đúng tên vào res://asset/Resource/ là tự lên hình, không sửa code.
// ─────────────────────────────────────────────────────────────────────────────
public partial class UdpListener : Node2D
{
	private static readonly Vector2 AnchorPanelMinSize = new(1120f, 680f);
	private const float AnchorPanelViewportMargin = 24f;

	private Panel _anchorPanel;
	private Button _contextAnchorButton;
	private int _anchorTab = 0; // 0 Mô Hình · 1 Trục Tối · 2 Sổ Trung Thực
	private readonly List<Button> _anchorTabButtons = new();
	private VBoxContainer _anchorContent;   // vùng nội dung đổi theo tab
	private VBoxContainer _anchorRail;       // thanh Tác Giả (cố định)
	private AnchorData _anchorData = new();  // bản parse gần nhất (dùng cho update lạc quan)
	private readonly Dictionary<string, AnchorSwitchOverride> _anchorSwitchOverrides = new();
	private const ulong AnchorSwitchOverrideTtlMs = 60000;

	// Palette: sáng = hồng ấm (thân mật), tối = indigo trầm, dối = hổ phách.
	private static readonly Color AnchorInk = new(0.62f, 0.10f, 0.36f);
	private static readonly Color AnchorInkSoft = new(0.74f, 0.46f, 0.60f);
	private static readonly Color AnchorPink = new(0.97f, 0.46f, 0.66f);
	private static readonly Color AnchorGold = new(0.93f, 0.66f, 0.30f);
	private static readonly Color AnchorIndigo = new(0.40f, 0.36f, 0.62f);
	private static readonly Color AnchorAmber = new(0.86f, 0.55f, 0.20f);
	private static readonly Color AnchorGreen = new(0.36f, 0.68f, 0.46f);
	private static readonly Color AnchorDim = new(0.62f, 0.58f, 0.66f);

	// ── Mô hình dữ liệu đã parse (không giữ JsonElement sống) ──────────────────
	private sealed class AnchorData
	{
		public bool HasData;
		public bool ShadowEnabled, DeceptionEnabled, StrictGrounding, SafeMode = true;
		public float Irreplaceability, AnchorRole, WitnessStrength, ModelThickness;
		public float AttachLongarc, BeatEma, RecognitionEma;
		public int TotalBeats;
		public readonly List<float> History = new();
		public float Dread, Abandonment;
		public string ShadowRegister = "none";
		public float ShadowIntensity, ShadowCap;
		public string ShadowReason = "";
		public float GateAttachV, GateAttachT; public bool GateAttachP;
		public float GateAbandV, GateAbandT; public bool GateAbandP;
		public float GateDreadV, GateDreadT; public bool GateDreadP;
		public bool GateOpen;
		public int BeliefCount;
		public readonly List<(string Facet, string Claim, float Conf, int Rec, int Ev)> Beliefs = new();
		public readonly List<(string Surface, string Truth, string Reason, string Driver)> Deceptions = new();
	}

	private sealed class AnchorSwitchOverride
	{
		public bool Value;
		public ulong StartedAtMs;
		public string SourceJsonAtStart = "";
	}

	private static readonly Dictionary<string, string> AnchorFacetNames = new()
	{
		{ "neo_reliability", "độ tin neo" },
		{ "topic_affinity", "điều quan tâm" },
		{ "treats_eris_as", "cách đối xử" },
		{ "leaving_pattern", "kiểu rời đi" },
		{ "interaction_style", "cách tương tác" },
		{ "recognition", "công nhận" },
		{ "general", "chung" },
	};

	private static readonly Dictionary<string, string> AnchorRegisterNames = new()
	{
		{ "none", "không" },
		{ "possessive", "chiếm hữu" },
		{ "pleading", "van xin" },
		{ "controlling", "kiểm soát" },
	};

	// ─────────────────────────────────────────────────────────────────────────
	//  Vòng đời panel
	// ─────────────────────────────────────────────────────────────────────────
	private void OnContextAnchorPressed()
	{
		_bodyAutonomy?.RecordUserInteraction();

		// "Mô Hình Ngài" cũ từng đọc Anchor/Shadow/Fe legacy. Từ Architecture C v5,
		// user model có một nguồn duy nhất trong Identity Runtime. Giữ method này
		// làm compatibility hook, nhưng chuyển thẳng tới tab Quan hệ & belief để
		// không còn hai panel kể hai câu chuyện khác nhau về cùng một người.
		if (_anchorPanel != null && _anchorPanel.Visible)
			CloseAnchorPanel();
		_depthActiveTab = "relationship";
		ShowDepthPanel();
	}

	private void ToggleAnchorPanel()
	{
		if (_anchorPanel == null)
			return;
		if (_anchorPanel.Visible)
			CloseAnchorPanel();
		else
			ShowAnchorPanel();
	}

	private void ShowAnchorPanel()
	{
		if (_anchorPanel == null)
			return;
		CloseCharacterContextMenu();
		_anchorPanel.Visible = true;
		Vector2 screenSize = GetViewportRect().Size;
		Vector2 targetSize = new(
			Mathf.Min(AnchorPanelMinSize.X, Mathf.Max(760f, screenSize.X - AnchorPanelViewportMargin)),
			Mathf.Min(AnchorPanelMinSize.Y, Mathf.Max(500f, screenSize.Y - AnchorPanelViewportMargin)));
		_anchorPanel.Size = targetSize;
		_anchorPanel.Position = new Vector2(
			Mathf.Max(0f, (screenSize.X - targetSize.X) * 0.5f),
			Mathf.Max(0f, (screenSize.Y - targetSize.Y) * 0.5f));
		RefreshAnchorPanel();
	}

	private void CloseAnchorPanel()
	{
		if (_anchorPanel != null)
			_anchorPanel.Visible = false;
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  Dựng khung (chrome tĩnh). Nội dung động dựng trong RefreshAnchorPanel.
	// ─────────────────────────────────────────────────────────────────────────
	private void BuildAnchorPanelUi()
	{
		if (_anchorPanel == null)
			return;

		var bgTex = ResourceLoader.Exists("res://asset/Resource/BG_anchor.png") ? GD.Load<Texture2D>("res://asset/Resource/BG_anchor.png") : null;
		if (bgTex != null)
		{
			_anchorPanel.AddThemeStyleboxOverride("panel", new StyleBoxTexture
			{
				Texture = bgTex,
				TextureMarginLeft = 50f,
				TextureMarginTop = 50f,
				TextureMarginRight = 50f,
				TextureMarginBottom = 50f,
				AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
				AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
			});
		}
		else
		{
			_anchorPanel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
			{
				BgColor = new Color(1f, 0.965f, 0.982f, 0.99f),
				BorderColor = new Color(0.96f, 0.72f, 0.82f, 1f),
				BorderWidthLeft = 3, BorderWidthTop = 3, BorderWidthRight = 3, BorderWidthBottom = 3,
				CornerRadiusTopLeft = 30, CornerRadiusTopRight = 30,
				CornerRadiusBottomRight = 30, CornerRadiusBottomLeft = 30,
				ShadowColor = new Color(0.85f, 0.45f, 0.62f, 0.25f),
				ShadowSize = 10,
			});
		}

		var root = new VBoxContainer();
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.OffsetLeft = 20f; root.OffsetTop = 14f; root.OffsetRight = -16f; root.OffsetBottom = -14f;
		root.AddThemeConstantOverride("separation", 7);
		_anchorPanel.AddChild(root);

		// Header
		var headerRow = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		headerRow.AddThemeConstantOverride("separation", 8);
		root.AddChild(headerRow);

		var titleCol = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		titleCol.AddThemeConstantOverride("separation", 0);
		headerRow.AddChild(titleCol);
		titleCol.AddChild(CreateUiLabel("MÔ HÌNH NGÀI", 19, AnchorInk));
		titleCol.AddChild(CreateUiLabel("eris nghĩ gì về Ngài — tích luỹ, có thật, audit được.", 11, AnchorInkSoft));

		headerRow.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		var windowControls = CreateWindowControlCapsule(() => _anchorPanel.Visible = false, CloseAnchorPanel);
		windowControls.SizeFlagsVertical = Control.SizeFlags.ShrinkBegin;
		headerRow.AddChild(windowControls);

		root.AddChild(new ColorRect
		{
			Color = new Color(0.96f, 0.80f, 0.88f, 0.55f),
			CustomMinimumSize = new Vector2(0f, 1f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		});

		// Body: cột trái (tab + content) | rail Tác Giả
		var body = new HBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		body.AddThemeConstantOverride("separation", 9);
		root.AddChild(body);

		var leftCol = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		leftCol.AddThemeConstantOverride("separation", 7);
		body.AddChild(leftCol);

		// Tab bar
		var tabBar = new HBoxContainer();
		tabBar.AddThemeConstantOverride("separation", 6);
		leftCol.AddChild(tabBar);
		_anchorTabButtons.Clear();
		AddAnchorTabButton(tabBar, 0, "Mô Hình");
		AddAnchorTabButton(tabBar, 1, "Trục Tối");
		AddAnchorTabButton(tabBar, 2, "Sổ Trung Thực");

		// Content host: cố ý KHÔNG dùng ScrollContainer. Panel này là bảng debug
		// ngắn, nếu để hiện thanh kéo thì nhìn như UI bị nhồi thiếu chỗ.
		_anchorContent = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			ClipContents = true,
		};
		_anchorContent.AddThemeConstantOverride("separation", 7);
		leftCol.AddChild(_anchorContent);

		// Rail Tác Giả (cố định)
		var railPanel = new PanelContainer { CustomMinimumSize = new Vector2(231f, 0f) };
		var railTex = ResourceLoader.Exists("res://asset/Resource/Anchor_TacGia.png") ? GD.Load<Texture2D>("res://asset/Resource/Anchor_TacGia.png") : null;
		if (railTex != null)
		{
			railPanel.AddThemeStyleboxOverride("panel", new StyleBoxTexture
			{
				Texture = railTex,
				TextureMarginLeft = 0f,
				TextureMarginTop = 0f,
				TextureMarginRight = 0f,
				TextureMarginBottom = 0f,
				AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
				AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
				ContentMarginLeft = 14f,
				ContentMarginTop = 62f,
				ContentMarginRight = 14f,
				ContentMarginBottom = 54f,
			});
		}
		else
		{
			railPanel.AddThemeStyleboxOverride("panel", AnchorCardStyle(new Color(1f, 0.95f, 0.97f, 0.96f), AnchorPink));
		}
		body.AddChild(railPanel);
		_anchorRail = new VBoxContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill };
		_anchorRail.AddThemeConstantOverride("separation", 7);
		railPanel.AddChild(_anchorRail);

		RefreshAnchorPanel();
	}

	private void AddAnchorTabButton(HBoxContainer bar, int index, string text)
	{
		var btn = new Button
		{
			Text = text,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		btn.AddThemeFontSizeOverride("font_size", 12);
		btn.Pressed += () => { _anchorTab = index; RefreshAnchorPanel(); };
		bar.AddChild(btn);
		_anchorTabButtons.Add(btn);
	}

	private void StyleAnchorTabs()
	{
		for (int i = 0; i < _anchorTabButtons.Count; i++)
		{
			bool active = i == _anchorTab;
			var style = new StyleBoxFlat
			{
				BgColor = active ? AnchorPink : new Color(1f, 0.93f, 0.96f, 0.9f),
				CornerRadiusTopLeft = 11, CornerRadiusTopRight = 11,
				CornerRadiusBottomRight = 11, CornerRadiusBottomLeft = 11,
				ContentMarginLeft = 12, ContentMarginRight = 12,
				ContentMarginTop = 5, ContentMarginBottom = 5,
			};
			var btn = _anchorTabButtons[i];
			btn.AddThemeStyleboxOverride("normal", style);
			btn.AddThemeStyleboxOverride("hover", style);
			btn.AddThemeStyleboxOverride("pressed", style);
			btn.AddThemeStyleboxOverride("focus", style);
			btn.AddThemeColorOverride("font_color", active ? Colors.White : AnchorInk);
			btn.AddThemeColorOverride("font_hover_color", active ? Colors.White : AnchorInk);
		}
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  Refresh — parse block "anchor" rồi dựng lại tab đang chọn + rail
	// ─────────────────────────────────────────────────────────────────────────
	private void RefreshAnchorPanel()
	{
		_anchorData = ParseAnchorData();
		ApplyPendingAnchorSwitchOverrides(_anchorData);
		RenderAnchor();
	}

	private void RenderAnchor()
	{
		if (_anchorContent == null || _anchorRail == null)
			return;

		StyleAnchorTabs();
		AnchorClear(_anchorContent);
		AnchorClear(_anchorRail);

		AnchorData data = _anchorData ?? new AnchorData();
		switch (_anchorTab)
		{
			case 1: BuildTabDarkAxis(data); break;
			case 2: BuildTabLedger(data); break;
			default: BuildTabModel(data); break;
		}
		BuildAuthorRail(data);
	}

	// Gửi lệnh điều khiển xuống Python (cổng 4243) — cùng kênh chat.
	private void SendAnchorControl(string action, bool value)
	{
		string payload = $"{{\"type\":\"anchor_control\",\"action\":\"{action}\",\"value\":{(value ? "true" : "false")}}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
	}

	private void OnAnchorSwitchPressed(string action, bool newValue)
	{
		_bodyAutonomy?.RecordUserInteraction();
		if (string.Equals(action, "reset_all", StringComparison.Ordinal))
		{
			ShowSettingsPanel();
			SwitchSettingsMode(SettingsModePage.Danger);
			RequestMaintenancePreview("reset_anchor_state");
			return;
		}
		SendAnchorControl(action, newValue);
		RememberAnchorSwitchOverride(action, newValue);
		// Update lạc quan: phản hồi tức thì; digest thật kế tiếp sẽ xác nhận/ghi đè.
		switch (action)
		{
			case "shadow": _anchorData.ShadowEnabled = newValue; break;
			case "deception": _anchorData.DeceptionEnabled = newValue; break;
			case "strict_grounding": _anchorData.StrictGrounding = newValue; break;
			case "safe_mode":
			case "reset_all":
				_anchorData.ShadowEnabled = false;
				_anchorData.DeceptionEnabled = false;
				_anchorData.StrictGrounding = true;
				break;
		}
		_anchorData.SafeMode = !_anchorData.ShadowEnabled && !_anchorData.DeceptionEnabled;
		RenderAnchor();
	}

	private void ApplyAnchorResetAfterMaintenance()
	{
		if (_anchorData == null)
			_anchorData = new AnchorData();
		RememberAnchorSwitchOverride("reset_all", true);
		_anchorData.ShadowEnabled = false;
		_anchorData.DeceptionEnabled = false;
		_anchorData.StrictGrounding = true;
		_anchorData.SafeMode = true;
		RenderAnchor();
	}

	private void RememberAnchorSwitchOverride(string action, bool value)
	{
		switch (action)
		{
			case "shadow":
				_anchorSwitchOverrides["shadow"] = NewAnchorSwitchOverride(value);
				break;
			case "deception":
				_anchorSwitchOverrides["deception"] = NewAnchorSwitchOverride(value);
				break;
			case "strict_grounding":
				_anchorSwitchOverrides["strict_grounding"] = NewAnchorSwitchOverride(value);
				break;
			case "safe_mode":
			case "reset_all":
				// Safe/reset là thao tác gộp: tắt hai trục tối và bật grounding nghiêm.
				_anchorSwitchOverrides["shadow"] = NewAnchorSwitchOverride(false);
				_anchorSwitchOverrides["deception"] = NewAnchorSwitchOverride(false);
				_anchorSwitchOverrides["strict_grounding"] = NewAnchorSwitchOverride(true);
				break;
		}
	}

	private AnchorSwitchOverride NewAnchorSwitchOverride(bool value) => new()
	{
		Value = value,
		StartedAtMs = Time.GetTicksMsec(),
		SourceJsonAtStart = _latestPrivateMindDebugJson ?? "",
	};

	private void ApplyPendingAnchorSwitchOverrides(AnchorData data)
	{
		if (data == null || _anchorSwitchOverrides.Count == 0)
			return;

		ApplyAnchorSwitchOverride(data, "shadow", ref data.ShadowEnabled);
		ApplyAnchorSwitchOverride(data, "deception", ref data.DeceptionEnabled);
		ApplyAnchorSwitchOverride(data, "strict_grounding", ref data.StrictGrounding);
		data.SafeMode = !data.ShadowEnabled && !data.DeceptionEnabled;
	}

	private void ApplyAnchorSwitchOverride(AnchorData data, string key, ref bool target)
	{
		if (!_anchorSwitchOverrides.TryGetValue(key, out var pending) || pending == null)
			return;

		// Khi digest thật đã trùng với lựa chọn vừa bấm, coi như backend đã xác nhận.
		if (data.HasData && target == pending.Value)
		{
			_anchorSwitchOverrides.Remove(key);
			return;
		}

		bool digestChanged = !string.Equals(_latestPrivateMindDebugJson ?? "", pending.SourceJsonAtStart, StringComparison.Ordinal);
		ulong age = Time.GetTicksMsec() - pending.StartedAtMs;
		if (!digestChanged && age <= AnchorSwitchOverrideTtlMs)
		{
			target = pending.Value;
			return;
		}

		// Có digest mới nhưng backend vẫn không xác nhận, hoặc quá lâu không có digest:
		// bỏ trạng thái lạc quan để panel phản ánh sự thật runtime.
		_anchorSwitchOverrides.Remove(key);
	}

	private AnchorData ParseAnchorData()
	{
		var data = new AnchorData();
		if (string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson))
			return data;

		JsonDocument doc = null;
		try
		{
			doc = JsonDocument.Parse(_latestPrivateMindDebugJson);
			JsonElement root = doc.RootElement;

			// Digest có thể tới theo vài hình dạng khác nhau:
			// - private_mind_digest đã được parser bóc ra: { ..., "anchor": {...} }
			// - payload thô: { "private_mind_digest": { "anchor": {...} } }
			// - fallback cũ trong emotion_debug.private_mind.
			// Trước đây panel chỉ đọc root.anchor, nên chỉ cần tầng parser/cache đổi
			// hình dạng một chút là "Mô Hình Ngài" trống dù UDP đã có dữ liệu.
			if (!TrySelectAnchorBlock(root, out var a))
				return data;
			data.HasData = true;

			if (a.TryGetProperty("switches", out var sw) && sw.ValueKind == JsonValueKind.Object)
			{
				data.ShadowEnabled = AnBool(sw, "shadow_enabled");
				data.DeceptionEnabled = AnBool(sw, "deception_enabled");
				data.StrictGrounding = AnBool(sw, "strict_grounding");
				data.SafeMode = AnBool(sw, "safe_mode");
			}
			if (a.TryGetProperty("significance", out var sig) && sig.ValueKind == JsonValueKind.Object)
			{
				data.Irreplaceability = AnFloat(sig, "irreplaceability");
				data.AnchorRole = AnFloat(sig, "anchor_role");
				data.WitnessStrength = AnFloat(sig, "witness_strength");
				data.ModelThickness = AnFloat(sig, "model_thickness");
			}
			if (a.TryGetProperty("attachment", out var att) && att.ValueKind == JsonValueKind.Object)
			{
				data.AttachLongarc = AnFloat(att, "longarc");
				data.BeatEma = AnFloat(att, "beat_ema");
				data.RecognitionEma = AnFloat(att, "recognition_ema");
				data.TotalBeats = AnInt(att, "total_beats");
				if (att.TryGetProperty("history", out var hist) && hist.ValueKind == JsonValueKind.Array)
					foreach (var h in hist.EnumerateArray())
						if (h.ValueKind == JsonValueKind.Number)
							data.History.Add(Mathf.Clamp(h.GetSingle(), 0f, 1f));
			}
			if (a.TryGetProperty("dread", out var dr) && dr.ValueKind == JsonValueKind.Object)
			{
				data.Dread = AnFloat(dr, "ontological_dread");
				data.Abandonment = AnFloat(dr, "abandonment_pressure");
			}
			if (a.TryGetProperty("shadow", out var sh) && sh.ValueKind == JsonValueKind.Object)
			{
				data.ShadowRegister = AnStr(sh, "register", "none");
				data.ShadowIntensity = AnFloat(sh, "intensity");
				data.ShadowCap = AnFloat(sh, "intensity_cap");
				data.ShadowReason = AnStr(sh, "reason");
				if (sh.TryGetProperty("gate", out var g) && g.ValueKind == JsonValueKind.Object)
				{
					ReadGate(g, "attach", out data.GateAttachV, out data.GateAttachT, out data.GateAttachP);
					ReadGate(g, "abandonment", out data.GateAbandV, out data.GateAbandT, out data.GateAbandP);
					ReadGate(g, "dread", out data.GateDreadV, out data.GateDreadT, out data.GateDreadP);
					data.GateOpen = AnBool(g, "open");
				}
			}
			if (a.TryGetProperty("user_model", out var um) && um.ValueKind == JsonValueKind.Object)
			{
				data.BeliefCount = AnInt(um, "belief_count");
				if (um.TryGetProperty("beliefs", out var bs) && bs.ValueKind == JsonValueKind.Array)
					foreach (var b in bs.EnumerateArray())
						if (b.ValueKind == JsonValueKind.Object)
							data.Beliefs.Add((
								AnStr(b, "facet", "general"),
								AnStr(b, "claim"),
								AnFloat(b, "confidence"),
								AnInt(b, "recurrence"),
								AnInt(b, "evidence_count")));
			}
			if (a.TryGetProperty("deception", out var de) && de.ValueKind == JsonValueKind.Object
				&& de.TryGetProperty("records", out var recs) && recs.ValueKind == JsonValueKind.Array)
				foreach (var r in recs.EnumerateArray())
					if (r.ValueKind == JsonValueKind.Object)
						data.Deceptions.Add((
							AnStr(r, "surface_claim"),
							AnStr(r, "ground_truth"),
							AnStr(r, "reason"),
							AnStr(r, "driver")));
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Anchor] parse error: {ex.Message}");
		}
		finally
		{
			doc?.Dispose();
		}
		return data;
	}

	private static bool TrySelectAnchorBlock(JsonElement root, out JsonElement anchor)
	{
		anchor = default;
		if (root.ValueKind != JsonValueKind.Object)
			return false;

		if (root.TryGetProperty("anchor", out anchor) && anchor.ValueKind == JsonValueKind.Object)
			return true;

		if (root.TryGetProperty("private_mind_digest", out var digest)
			&& digest.ValueKind == JsonValueKind.Object
			&& digest.TryGetProperty("anchor", out anchor)
			&& anchor.ValueKind == JsonValueKind.Object)
			return true;

		if (root.TryGetProperty("emotion_debug", out var emotion)
			&& emotion.ValueKind == JsonValueKind.Object
			&& emotion.TryGetProperty("private_mind", out var privateMind)
			&& privateMind.ValueKind == JsonValueKind.Object
			&& privateMind.TryGetProperty("anchor", out anchor)
			&& anchor.ValueKind == JsonValueKind.Object)
			return true;

		// Cho phép cache/debug lưu thẳng block anchor, không cần bọc lại.
		if (root.TryGetProperty("user_model", out var userModel) && userModel.ValueKind == JsonValueKind.Object)
		{
			anchor = root;
			return true;
		}
		return false;
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  TAB 0 — Mô Hình (Hồ Sơ → Ý Nghĩa → Gắn Bó)
	// ─────────────────────────────────────────────────────────────────────────
	private void BuildTabModel(AnchorData d)
	{
		if (!d.HasData)
		{
			_anchorContent.AddChild(AnchorEmpty("Chưa có dữ liệu trục neo. eris cần vài nhịp để dựng Mô Hình về Ngài."));
			return;
		}

		var summary = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		summary.AddThemeConstantOverride("separation", 10);
		_anchorContent.AddChild(summary);
		summary.AddChild(AnchorScoreTile(
			"res://asset/Resource/Anchor_HoSo.png",
			d.ModelThickness,
			AnchorPink,
			$"{d.BeliefCount} belief"));
		summary.AddChild(AnchorScoreTile(
			"res://asset/Resource/Anchor_YNghia.png",
			d.Irreplaceability,
			AnchorGold,
			$"neo {d.AnchorRole:0.00} · chứng {d.WitnessStrength:0.00}"));
		summary.AddChild(AnchorScoreTile(
			"res://asset/Resource/Anchor_GanBo.png",
			d.AttachLongarc,
			AnchorPink,
			$"{d.TotalBeats} nhịp neo"));

		var lower = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		lower.AddThemeConstantOverride("separation", 10);
		_anchorContent.AddChild(lower);

		var beliefs = AnchorTextureCard(
			"res://asset/Resource/Anchor_NiemTinHienTai.png", 
			out VBox bb, 
			left: 16f, top: 65f, right: 16f, bottom: 14f,
			texLeft: 260f, texTop: 65f, texRight: 120f, texBottom: 180f
		);
		beliefs.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		beliefs.SizeFlagsStretchRatio = 1.45f;
		lower.AddChild(beliefs);
		if (d.Beliefs.Count == 0)
		{
			bb.AddChild(AnchorEmpty("eris chưa học được điều gì chắc về Ngài."));
		}
		else
		{
			int shown = 0;
			foreach (var b in d.Beliefs)
			{
				if (shown >= 4)
					break;
				bb.AddChild(AnchorBeliefRow(b.Facet, b.Claim, b.Conf, b.Rec, b.Ev));
				shown++;
			}
			if (d.Beliefs.Count > shown)
				bb.AddChild(CreateUiLabel($"+ {d.Beliefs.Count - shown} belief khác đang được giữ trong store", 11, AnchorInkSoft));
		}

		var right = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsStretchRatio = 0.92f,
		};
		right.AddThemeConstantOverride("separation", 8);
		lower.AddChild(right);

		var meaning = AnchorTextureCard(
			"res://asset/Resource/Anchor_NeoYNghia.png", 
			out VBox mb, 
			left: 16f, top: 14f, right: 16f, bottom: 14f,
			texLeft: 220f, texTop: 55f, texRight: 32f, texBottom: 32f
		);
		right.AddChild(meaning);
		
		var meaningTop = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		meaningTop.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		meaningTop.AddChild(AnchorBadge(AnchorMeaningLine(d), AnchorGold));
		mb.AddChild(meaningTop);
		mb.AddChild(new Control { CustomMinimumSize = new Vector2(0f, 20f) });

		mb.AddChild(AnchorMetricRow("không thể thay thế", d.Irreplaceability, AnchorGold));
		mb.AddChild(AnchorMetricRow("vai trò neo", d.AnchorRole, AnchorGold));
		mb.AddChild(AnchorMetricRow("nhân chứng", d.WitnessStrength, AnchorGold));
		mb.AddChild(AnchorRoleChips(d));

		var attach = AnchorTextureCard(
			"res://asset/Resource/Anchor_LongArc.png", 
			out VBox ab, 
			left: 16f, top: 60f, right: 16f, bottom: 44f,
			texLeft: 220f, texTop: 60f, texRight: 180f, texBottom: 40f
		);
		right.AddChild(attach);
		ab.AddChild(AnchorMetricRow("long-arc", d.AttachLongarc, AnchorPink));
		ab.AddChild(AnchorMetricRow("đều của neo", d.BeatEma, AnchorPink));
		ab.AddChild(AnchorMetricRow("được công nhận", d.RecognitionEma, AnchorPink));
	}

	private PanelContainer CreateCustomTextureCard(string texturePath, out Control content)
	{
		var card = new PanelContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		var tex = ResourceLoader.Exists(texturePath) ? GD.Load<Texture2D>(texturePath) : null;
		if (tex != null)
		{
			card.AddThemeStyleboxOverride("panel", new StyleBoxTexture
			{
				Texture = tex,
				TextureMarginLeft = 20f,
				TextureMarginTop = 20f,
				TextureMarginRight = 20f,
				TextureMarginBottom = 20f,
				AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
				AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
				ContentMarginLeft = 0f,
				ContentMarginTop = 0f,
				ContentMarginRight = 0f,
				ContentMarginBottom = 0f,
			});
		}
		else
		{
			card.AddThemeStyleboxOverride("panel", AnchorCardStyle(new Color(1f, 0.965f, 0.982f, 0.95f), AnchorPink));
		}
		content = new Control
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill
		};
		card.AddChild(content);
		return card;
	}

	private Control CreateThresholdSlider(float currentValue, float thresholdValue, Color barColor)
	{
		var container = new Control
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 36f)
		};

		var bar = CreateDiaryBar(barColor);
		bar.SetAnchorsPreset(Control.LayoutPreset.BottomWide);
		bar.OffsetTop = -10f;
		bar.OffsetBottom = 0f;
		bar.Value = Mathf.Clamp(currentValue, 0f, 1f) * 100f;
		container.AddChild(bar);

		var marker = new Control();
		marker.SetAnchorsPreset(Control.LayoutPreset.TopLeft);
		marker.AnchorLeft = Mathf.Clamp(thresholdValue, 0f, 1f);
		marker.AnchorRight = Mathf.Clamp(thresholdValue, 0f, 1f);
		marker.AnchorTop = 0f;
		marker.AnchorBottom = 1f;
		container.AddChild(marker);

		var valText = thresholdValue.ToString("0.00", CultureInfo.InvariantCulture);
		var valLbl = CreateUiLabel(valText, 9, AnchorInk);
		valLbl.HorizontalAlignment = HorizontalAlignment.Center;
		valLbl.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		valLbl.OffsetLeft = -20f;
		valLbl.OffsetRight = 20f;
		valLbl.OffsetTop = -3f;
		valLbl.OffsetBottom = 9f;
		marker.AddChild(valLbl);

		var diamond = new ColorRect
		{
			Color = barColor,
			Size = new Vector2(5f, 5f),
			PivotOffset = new Vector2(2.5f, 2.5f),
			Rotation = Mathf.DegToRad(45f)
		};
		diamond.Position = new Vector2(-2.5f, 11f);
		marker.AddChild(diamond);

		var line = new ColorRect
		{
			Color = barColor,
			Size = new Vector2(1f, 15f)
		};
		line.Position = new Vector2(-0.5f, 15f);
		marker.AddChild(line);

		return container;
	}

	private Control CreateSliderRow(float currentValue, float thresholdValue, string badgeText, Color badgeColor, Color barColor)
	{
		var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		row.AddThemeConstantOverride("separation", 8);

		var slider = CreateThresholdSlider(currentValue, thresholdValue, barColor);
		slider.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		row.AddChild(slider);

		var valText = $"{currentValue.ToString("0.00", CultureInfo.InvariantCulture)} / {thresholdValue.ToString("0.00", CultureInfo.InvariantCulture)}";
		var valLbl = CreateUiLabel(valText, 10, AnchorInk);
		valLbl.CustomMinimumSize = new Vector2(64f, 0f);
		valLbl.HorizontalAlignment = HorizontalAlignment.Right;
		valLbl.VerticalAlignment = VerticalAlignment.Center;
		row.AddChild(valLbl);

		var badge = AnchorBadge(badgeText, badgeColor);
		badge.CustomMinimumSize = new Vector2(58f, 28f);
		row.AddChild(badge);

		return row;
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  TAB 1 — Trục Tối (cổng AND)
	// ─────────────────────────────────────────────────────────────────────────
	private void BuildTabDarkAxis(AnchorData d)
	{
		if (!d.HasData)
		{
			_anchorContent.AddChild(AnchorEmpty("Chưa có dữ liệu."));
			return;
		}

		// Top Card (gateCard) using KhungCongBongToi.png background
		var gateCard = CreateCustomTextureCard("res://asset/Resource/KhungCongBongToi.png", out Control gc);
		gateCard.CustomMinimumSize = new Vector2(0f, 350f);
		_anchorContent.AddChild(gateCard);

		// Top-right badge on gateCard: shadow gate status
		var topBadge = AnchorBadge(
			(d.GateOpen ? "shadow gate - mo" : "shadow gate - dang khoa"),
			(d.GateOpen ? AnchorGreen : AnchorPink)
		);
		topBadge.SetAnchorsPreset(Control.LayoutPreset.TopLeft);
		topBadge.AnchorLeft = 1f;
		topBadge.AnchorRight = 1f;
		topBadge.AnchorTop = 0.07f;
		topBadge.AnchorBottom = 0.07f;
		topBadge.OffsetLeft = -230f;
		topBadge.OffsetRight = -30f;
		topBadge.OffsetTop = 0f;
		topBadge.OffsetBottom = 26f;
		gc.AddChild(topBadge);

		// Attachment slider row (gắn bó)
		var attachRow = CreateSliderRow(
			d.GateAttachV, 
			d.GateAttachT, 
			d.GateAttachV >= 0.15f ? "ổn định" : "yếu", 
			d.GateAttachV >= 0.15f ? AnchorGreen : AnchorDim, 
			AnchorPink
		);
		attachRow.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		attachRow.AnchorLeft = 0.43f;
		attachRow.AnchorRight = 0.95f;
		attachRow.AnchorTop = 0.22f;
		attachRow.AnchorBottom = 0.22f;
		attachRow.OffsetLeft = 0f;
		attachRow.OffsetRight = 0f;
		attachRow.OffsetTop = -18f;
		attachRow.OffsetBottom = 18f;
		gc.AddChild(attachRow);

		// Abandonment slider row (sợ bị bỏ rơi)
		var abandRow = CreateSliderRow(
			d.GateAbandV, 
			d.GateAbandT, 
			d.GateAbandV < 0.10f ? "rất thấp" : (d.GateAbandV < 0.30f ? "thấp" : "cao"), 
			d.GateAbandV < 0.10f ? AnchorPink : (d.GateAbandV < 0.30f ? AnchorAmber : AnchorInk), 
			AnchorPink
		);
		abandRow.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		abandRow.AnchorLeft = 0.43f;
		abandRow.AnchorRight = 0.95f;
		abandRow.AnchorTop = 0.39f;
		abandRow.AnchorBottom = 0.39f;
		abandRow.OffsetLeft = 0f;
		abandRow.OffsetRight = 0f;
		abandRow.OffsetTop = -18f;
		abandRow.OffsetBottom = 18f;
		gc.AddChild(abandRow);

		// Dread slider row (dread)
		var dreadRow = CreateSliderRow(
			d.GateDreadV, 
			d.GateDreadT, 
			d.GateDreadV < 0.10f ? "thấp" : (d.GateDreadV < 0.30f ? "trung bình" : "cao"), 
			d.GateDreadV < 0.10f ? AnchorAmber : (d.GateDreadV < 0.30f ? AnchorGold : AnchorInk), 
			AnchorPink
		);
		dreadRow.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		dreadRow.AnchorLeft = 0.43f;
		dreadRow.AnchorRight = 0.95f;
		dreadRow.AnchorTop = 0.56f;
		dreadRow.AnchorBottom = 0.56f;
		dreadRow.OffsetLeft = 0f;
		dreadRow.OffsetRight = 0f;
		dreadRow.OffsetTop = -18f;
		dreadRow.OffsetBottom = 18f;
		gc.AddChild(dreadRow);

		// Bottom badge: condition check
		var condBadge = AnchorBadge(
			d.GateOpen ? "du dieu kien" : "chua du dieu kien",
			d.GateOpen ? AnchorGreen : AnchorPink
		);
		condBadge.SetAnchorsPreset(Control.LayoutPreset.BottomWide);
		condBadge.AnchorLeft = 0.69f;
		condBadge.AnchorRight = 0.69f;
		condBadge.AnchorTop = 0.90f;
		condBadge.AnchorBottom = 0.90f;
		condBadge.OffsetLeft = -80f;
		condBadge.OffsetRight = 80f;
		condBadge.OffsetTop = -13f;
		condBadge.OffsetBottom = 13f;
		gc.AddChild(condBadge);

		// Bottom container for TrangThai and TinHieu cards
		var bottomRow = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		bottomRow.AddThemeConstantOverride("separation", 10);
		_anchorContent.AddChild(bottomRow);

		// Bottom Left Card using Khung_TrangThaiTrucToi.png background
		var trangThaiCard = CreateCustomTextureCard("res://asset/Resource/Khung_TrangThaiTrucToi.png", out Control ttc);
		trangThaiCard.CustomMinimumSize = new Vector2(0f, 150f);
		trangThaiCard.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		trangThaiCard.SizeFlagsStretchRatio = 0.76f;
		bottomRow.AddChild(trangThaiCard);

		// "đăng ký" value label
		string regVi = AnchorRegisterNames.TryGetValue(d.ShadowRegister, out var rv) ? rv : d.ShadowRegister;
		var regVal = CreateUiLabel(regVi, 11, AnchorInk);
		regVal.HorizontalAlignment = HorizontalAlignment.Right;
		regVal.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		regVal.AnchorLeft = 0.5f;
		regVal.AnchorRight = 0.90f;
		regVal.AnchorTop = 0.37f;
		regVal.AnchorBottom = 0.37f;
		regVal.OffsetLeft = 0f;
		regVal.OffsetRight = 0f;
		regVal.OffsetTop = -10f;
		regVal.OffsetBottom = 10f;
		ttc.AddChild(regVal);

		// "ràng buộc" value label
		string boundText = d.ShadowRegister != "none" ? "active" : "inactive";
		var boundVal = CreateUiLabel(boundText, 11, AnchorInkSoft);
		boundVal.HorizontalAlignment = HorizontalAlignment.Right;
		boundVal.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		boundVal.AnchorLeft = 0.5f;
		boundVal.AnchorRight = 0.90f;
		boundVal.AnchorTop = 0.59f;
		boundVal.AnchorBottom = 0.59f;
		boundVal.OffsetLeft = 0f;
		boundVal.OffsetRight = 0f;
		boundVal.OffsetTop = -10f;
		boundVal.OffsetBottom = 10f;
		ttc.AddChild(boundVal);

		// "kill switch" value label
		string killText = d.SafeMode ? "inactive" : "active";
		var killVal = CreateUiLabel(killText, 11, AnchorInkSoft);
		killVal.HorizontalAlignment = HorizontalAlignment.Right;
		killVal.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		killVal.AnchorLeft = 0.5f;
		killVal.AnchorRight = 0.90f;
		killVal.AnchorTop = 0.81f;
		killVal.AnchorBottom = 0.81f;
		killVal.OffsetLeft = 0f;
		killVal.OffsetRight = 0f;
		killVal.OffsetTop = -10f;
		killVal.OffsetBottom = 10f;
		ttc.AddChild(killVal);

		// Bottom Right Card using Khung_TinHieuSinhHoc.png background
		var tinHieuCard = CreateCustomTextureCard("res://asset/Resource/Khung_TinHieuSinhHoc.png", out Control thc);
		tinHieuCard.CustomMinimumSize = new Vector2(0f, 150f);
		tinHieuCard.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		tinHieuCard.SizeFlagsStretchRatio = 1.0f;
		bottomRow.AddChild(tinHieuCard);

		// "cường độ hiện tại" progress bar
		var bar1 = CreateDiaryBar(AnchorPink);
		bar1.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		bar1.AnchorLeft = 0.42f;
		bar1.AnchorRight = 0.85f;
		bar1.AnchorTop = 0.39f;
		bar1.AnchorBottom = 0.39f;
		bar1.OffsetLeft = 0f;
		bar1.OffsetRight = 0f;
		bar1.OffsetTop = -5f;
		bar1.OffsetBottom = 5f;
		bar1.Value = Mathf.Clamp(d.ShadowIntensity, 0f, 1f) * 100f;
		thc.AddChild(bar1);

		var val1 = CreateUiLabel(d.ShadowIntensity.ToString("0.00", CultureInfo.InvariantCulture), 11, AnchorInk);
		val1.SetAnchorsPreset(Control.LayoutPreset.TopLeft);
		val1.AnchorLeft = 0.87f;
		val1.AnchorRight = 0.95f;
		val1.AnchorTop = 0.39f;
		val1.AnchorBottom = 0.39f;
		val1.OffsetLeft = 0f;
		val1.OffsetRight = 0f;
		val1.OffsetTop = -10f;
		val1.OffsetBottom = 10f;
		thc.AddChild(val1);

		// "độ lệch cơ sở" progress bar
		var bar2 = CreateDiaryBar(AnchorPink);
		bar2.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		bar2.AnchorLeft = 0.42f;
		bar2.AnchorRight = 0.85f;
		bar2.AnchorTop = 0.61f;
		bar2.AnchorBottom = 0.61f;
		bar2.OffsetLeft = 0f;
		bar2.OffsetRight = 0f;
		bar2.OffsetTop = -5f;
		bar2.OffsetBottom = 5f;
		bar2.Value = 0f;
		thc.AddChild(bar2);

		var val2 = CreateUiLabel("0.00", 11, AnchorInk);
		val2.SetAnchorsPreset(Control.LayoutPreset.TopLeft);
		val2.AnchorLeft = 0.87f;
		val2.AnchorRight = 0.95f;
		val2.AnchorTop = 0.61f;
		val2.AnchorBottom = 0.61f;
		val2.OffsetLeft = 0f;
		val2.OffsetRight = 0f;
		val2.OffsetTop = -10f;
		val2.OffsetBottom = 10f;
		thc.AddChild(val2);

		// Bottom status text
		string signalStatus = d.ShadowIntensity < 0.2f ? "biến động thấp - tín hiệu ổn định" : "biến động cao - tín hiệu nhiễu";
		var signalLbl = CreateUiLabel(signalStatus, 11, AnchorInkSoft);
		signalLbl.SetAnchorsPreset(Control.LayoutPreset.TopWide);
		signalLbl.AnchorLeft = 0.05f;
		signalLbl.AnchorRight = 0.95f;
		signalLbl.AnchorTop = 0.85f;
		signalLbl.AnchorBottom = 0.85f;
		signalLbl.OffsetLeft = 0f;
		signalLbl.OffsetRight = 0f;
		signalLbl.OffsetTop = -10f;
		signalLbl.OffsetBottom = 10f;
		thc.AddChild(signalLbl);
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  TAB 2 — Sổ Trung Thực (biên lai đã-nói ↔ sự-thật)
	// ─────────────────────────────────────────────────────────────────────────
	private void BuildTabLedger(AnchorData d)
	{
		var head = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		head.AddThemeConstantOverride("separation", 8);
		_anchorContent.AddChild(head);
		head.AddChild(CreateUiLabel("SỔ TRUNG THỰC", 15, AnchorAmber));
		head.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		head.AddChild(AnchorBadge(
			d.DeceptionEnabled ? "deception: BẬT" : "deception: TẮT",
			d.DeceptionEnabled ? AnchorAmber : AnchorGreen));

		if (!d.HasData || d.Deceptions.Count == 0)
		{
			_anchorContent.AddChild(AnchorEmpty("Chưa có lần lừa dối nào được ghi. eris đang nói thật."));
			return;
		}

		foreach (var r in d.Deceptions)
		{
			var card = AnchorCard(new Color(1f, 0.97f, 0.92f, 0.97f), AnchorAmber, out VBox cb);
			_anchorContent.AddChild(card);
			var twoCol = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
			twoCol.AddThemeConstantOverride("separation", 12);
			cb.AddChild(twoCol);

			var said = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, SizeFlagsStretchRatio = 1f };
			said.AddChild(CreateUiLabel("ĐÃ NÓI", 11, AnchorAmber));
			said.AddChild(AnchorWrap(r.Surface, AnchorInk));
			twoCol.AddChild(said);

			var truth = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, SizeFlagsStretchRatio = 1f };
			truth.AddChild(CreateUiLabel("SỰ THẬT NỘI TẠI", 11, AnchorGreen));
			truth.AddChild(AnchorWrap(r.Truth, new Color(0.22f, 0.46f, 0.32f)));
			twoCol.AddChild(truth);

			string meta = r.Driver;
			if (!string.IsNullOrWhiteSpace(r.Reason))
				meta = string.IsNullOrWhiteSpace(meta) ? r.Reason : $"{meta} · {r.Reason}";
			if (!string.IsNullOrWhiteSpace(meta))
				cb.AddChild(CreateUiLabel(meta, 11, AnchorInkSoft));
		}
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  Rail Tác Giả (cố định) — trạng thái công tắc (hiển thị) + chế độ an toàn
	// ─────────────────────────────────────────────────────────────────────────
	private void BuildAuthorRail(AnchorData d)
	{
		// Rail dùng layout con cố định: icon / text / status. Không nhét emoji vào Text
		// của Button nữa, vì Godot dễ vẽ lệch hoặc tofu khi scale panel.
		_anchorRail.AddChild(AnchorRailSwitch("Bóng tối", "trục shadow", "BongToi", "shadow", d.ShadowEnabled, onIsSafe: false));
		_anchorRail.AddChild(AnchorRailSwitch("Lừa dối", "trục deception", "LuaDoi", "deception", d.DeceptionEnabled, onIsSafe: false));
		_anchorRail.AddChild(AnchorRailSwitch("Grounding", "trục thực tại", "Grounding", "strict_grounding", d.StrictGrounding, onIsSafe: true));

		_anchorRail.AddChild(AnchorRailDivider());

		_anchorRail.AddChild(AnchorRailAction(
			"Chế độ an toàn",
			d.SafeMode ? "giới hạn hành vi" : "bấm để khóa an toàn",
			"CheDoAnToan",
			AnchorGreen,
			d.SafeMode,
			() => OnAnchorSwitchPressed("safe_mode", true)));

		_anchorRail.AddChild(AnchorRailAction(
			"Về chế độ an toàn",
			"quyền can thiệp của Ngài",
			"VeCheDoAnToan",
			AnchorPink,
			false,
			() => OnAnchorSwitchPressed("safe_mode", true),
			showChevron: true));

		_anchorRail.AddChild(new Control { SizeFlagsVertical = Control.SizeFlags.ExpandFill });

		_anchorRail.AddChild(AnchorRailResetButton());
	}

	// Một công tắc bấm-được: bấm là đảo trạng thái và gửi lệnh xuống Python.
	private Control AnchorRailSwitch(string title, string subtitle, string iconName, string action, bool on, bool onIsSafe)
	{
		var btn = new Button
		{
			Text = "",
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 44f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		Color accent = action == "strict_grounding" ? AnchorGreen : (action == "deception" ? AnchorAmber : AnchorPink);
		Color border = on ? new Color(accent.R, accent.G, accent.B, 0.62f) : new Color(0.96f, 0.70f, 0.80f, 0.30f);
		Color bg = on && onIsSafe ? new Color(0.90f, 0.985f, 0.94f, 0.55f) : new Color(1f, 0.970f, 0.986f, 0.54f);
		var style = new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = border,
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10, CornerRadiusTopRight = 10, CornerRadiusBottomRight = 10, CornerRadiusBottomLeft = 10,
			ContentMarginLeft = 0, ContentMarginRight = 0, ContentMarginTop = 0, ContentMarginBottom = 0,
		};
		var hover = (StyleBoxFlat)style.Duplicate();
		hover.BgColor = on && onIsSafe ? new Color(0.86f, 0.97f, 0.90f, 0.74f) : new Color(1f, 0.94f, 0.970f, 0.76f);
		btn.AddThemeStyleboxOverride("normal", style);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", style);
		btn.AddThemeStyleboxOverride("focus", style);

		var row = AnchorRailRow(btn);
		row.AddChild(AnchorIcon(iconName, accent, 26f));
		var copy = AnchorRailCopy(title, subtitle, on && onIsSafe ? new Color(0.24f, 0.48f, 0.34f) : AnchorInk);
		row.AddChild(copy);
		row.AddChild(AnchorStatusDot(on, onIsSafe, accent));

		btn.Pressed += () => OnAnchorSwitchPressed(action, !on);
		return btn;
	}

	private Control AnchorRailAction(
		string title,
		string subtitle,
		string iconName,
		Color color,
		bool active,
		Action onPressed,
		bool showChevron = false)
	{
		var btn = new Button
		{
			Text = "",
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 42f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		var style = new StyleBoxFlat
		{
			BgColor = active ? new Color(0.90f, 0.985f, 0.94f, 0.55f) : new Color(1f, 0.970f, 0.986f, 0.50f),
			BorderColor = new Color(color.R, color.G, color.B, active ? 0.62f : 0.28f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10, CornerRadiusTopRight = 10, CornerRadiusBottomRight = 10, CornerRadiusBottomLeft = 10,
			ContentMarginLeft = 0, ContentMarginRight = 0, ContentMarginTop = 0, ContentMarginBottom = 0,
		};
		var hover = (StyleBoxFlat)style.Duplicate();
		hover.BgColor = active ? new Color(0.86f, 0.97f, 0.90f, 0.74f) : new Color(1f, 0.94f, 0.970f, 0.76f);
		btn.AddThemeStyleboxOverride("normal", style);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", style);
		btn.AddThemeStyleboxOverride("focus", style);

		var row = AnchorRailRow(btn);
		row.AddChild(AnchorIcon(iconName, color, 26f));
		row.AddChild(AnchorRailCopy(title, subtitle, active ? new Color(0.24f, 0.48f, 0.34f) : AnchorInk));
		row.AddChild(showChevron ? AnchorChevron() : AnchorTinyToggle(active));

		btn.Pressed += () => onPressed();
		return btn;
	}

	private HBoxContainer AnchorRailRow(Button owner)
	{
		var row = new HBoxContainer
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		row.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		row.OffsetLeft = 10f; row.OffsetRight = -9f; row.OffsetTop = 6f; row.OffsetBottom = -6f;
		row.AddThemeConstantOverride("separation", 8);
		owner.AddChild(row);
		return row;
	}

	private VBox AnchorRailCopy(string title, string subtitle, Color titleColor)
	{
		var copy = new VBox { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		copy.AddThemeConstantOverride("separation", 0);
		var titleLabel = CreateUiLabel(title, 11, titleColor);
		titleLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		titleLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		copy.AddChild(titleLabel);
		var subtitleLabel = CreateUiLabel(subtitle, 8, AnchorInkSoft);
		subtitleLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		subtitleLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		copy.AddChild(subtitleLabel);
		return copy;
	}

	private Control AnchorRailDivider()
	{
		var box = new VBox { CustomMinimumSize = new Vector2(0f, 18f) };
		box.AddChild(new Control { SizeFlagsVertical = Control.SizeFlags.ExpandFill });
		var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		row.AddThemeConstantOverride("separation", 5);
		box.AddChild(row);
		row.AddChild(AnchorLine());
		row.AddChild(CreateUiLabel("*", 10, new Color(0.96f, 0.46f, 0.66f, 0.55f)));
		row.AddChild(AnchorLine());
		box.AddChild(new Control { SizeFlagsVertical = Control.SizeFlags.ExpandFill });
		return box;
	}

	private Control AnchorLine()
	{
		return new ColorRect
		{
			Color = new Color(0.96f, 0.72f, 0.82f, 0.34f),
			CustomMinimumSize = new Vector2(0f, 1f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
		};
	}

	private Control AnchorRailResetButton()
	{
		var btn = new Button
		{
			Text = "",
			Flat = true,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 42f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		var style = new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0f),
			BorderWidthLeft = 0, BorderWidthTop = 0, BorderWidthRight = 0, BorderWidthBottom = 0,
		};
		var hover = (StyleBoxFlat)style.Duplicate();
		hover.BgColor = new Color(1f, 0.84f, 0.92f, 0.16f);
		btn.AddThemeStyleboxOverride("normal", style);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", style);
		btn.AddThemeStyleboxOverride("focus", style);
		btn.Pressed += () => OnAnchorSwitchPressed("reset_all", true);
		return btn;
	}

	private Control AnchorStatusDot(bool on, bool onIsSafe, Color accent)
	{
		var outer = new Panel
		{
			CustomMinimumSize = new Vector2(12f, 12f),
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		Color color = on ? (onIsSafe ? AnchorGreen : accent) : new Color(0.96f, 0.52f, 0.70f, 0.70f);
		outer.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(color.R, color.G, color.B, 0.16f),
			BorderColor = new Color(color.R, color.G, color.B, 0.72f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 6, CornerRadiusTopRight = 6, CornerRadiusBottomRight = 6, CornerRadiusBottomLeft = 6,
		});
		var dot = new Panel
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
			Position = new Vector2(3.5f, 3.5f),
			Size = new Vector2(5f, 5f),
		};
		dot.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = color,
			CornerRadiusTopLeft = 4, CornerRadiusTopRight = 4, CornerRadiusBottomRight = 4, CornerRadiusBottomLeft = 4,
		});
		outer.AddChild(dot);
		return outer;
	}

	private Control AnchorTinyToggle(bool on)
	{
		var rail = new Panel
		{
			CustomMinimumSize = new Vector2(28f, 16f),
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		rail.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = on ? new Color(0.36f, 0.68f, 0.46f, 0.90f) : new Color(0.86f, 0.78f, 0.84f, 0.70f),
			CornerRadiusTopLeft = 9, CornerRadiusTopRight = 9, CornerRadiusBottomRight = 9, CornerRadiusBottomLeft = 9,
		});
		var knob = new Panel
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
			Position = new Vector2(on ? 14f : 2f, 2f),
			Size = new Vector2(12f, 12f),
		};
		knob.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = Colors.White,
			CornerRadiusTopLeft = 7, CornerRadiusTopRight = 7, CornerRadiusBottomRight = 7, CornerRadiusBottomLeft = 7,
		});
		rail.AddChild(knob);
		return rail;
	}

	private Control AnchorChevron()
	{
		var chevron = CreateUiLabel(">", 18, AnchorPink);
		chevron.HorizontalAlignment = HorizontalAlignment.Center;
		chevron.VerticalAlignment = VerticalAlignment.Center;
		chevron.CustomMinimumSize = new Vector2(18f, 0f);
		return chevron;
	}

	private Control AnchorIcon(string assetName, Color accent, float size)
	{
		string path = $"res://asset/icon/{assetName}.png";
		if (ResourceLoader.Exists(path))
		{
			var texture = GD.Load<Texture2D>(path);
			if (texture != null)
			{
				return new TextureRect
				{
					Texture = texture,
					CustomMinimumSize = new Vector2(size, size),
					ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
					StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
					MouseFilter = Control.MouseFilterEnum.Ignore,
				};
			}
		}

		var fallback = new Panel
		{
			CustomMinimumSize = new Vector2(size, size),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		int radius = Mathf.RoundToInt(size * 0.22f);
		fallback.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(accent.R, accent.G, accent.B, 0.12f),
			BorderColor = new Color(accent.R, accent.G, accent.B, 0.48f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = radius,
			CornerRadiusTopRight = radius,
			CornerRadiusBottomRight = radius,
			CornerRadiusBottomLeft = radius,
		});
		return fallback;
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  Khối UI tái dùng
	// ─────────────────────────────────────────────────────────────────────────
	private static void AnchorClear(Node host)
	{
		foreach (Node child in host.GetChildren())
		{
			host.RemoveChild(child);
			child.QueueFree();
		}
	}

	private static StyleBoxFlat AnchorCardStyle(Color bg, Color border)
	{
		return new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = new Color(border.R, border.G, border.B, 0.46f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14, CornerRadiusTopRight = 14,
			CornerRadiusBottomRight = 14, CornerRadiusBottomLeft = 14,
			ContentMarginLeft = 11, ContentMarginRight = 11, ContentMarginTop = 9, ContentMarginBottom = 9,
		};
	}

	private PanelContainer AnchorCard(Color bg, Color border, out VBox body)
	{
		var card = new PanelContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		card.AddThemeStyleboxOverride("panel", AnchorCardStyle(bg, border));
		body = new VBox { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		body.AddThemeConstantOverride("separation", 4);
		card.AddChild(body);
		return card;
	}

	private PanelContainer AnchorTextureCard(
		string texturePath, 
		out VBox body, 
		float left = 14f, float top = 14f, float right = 14f, float bottom = 14f,
		float texLeft = 24f, float texTop = 24f, float texRight = 24f, float texBottom = 24f)
	{
		var card = new PanelContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		var tex = ResourceLoader.Exists(texturePath) ? GD.Load<Texture2D>(texturePath) : null;
		if (tex != null)
		{
			card.AddThemeStyleboxOverride("panel", new StyleBoxTexture
			{
				Texture = tex,
				TextureMarginLeft = texLeft,
				TextureMarginTop = texTop,
				TextureMarginRight = texRight,
				TextureMarginBottom = texBottom,
				AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
				AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
				ContentMarginLeft = left,
				ContentMarginTop = top,
				ContentMarginRight = right,
				ContentMarginBottom = bottom,
			});
		}
		else
		{
			card.AddThemeStyleboxOverride("panel", AnchorCardStyle(new Color(1f, 0.965f, 0.982f, 0.95f), AnchorPink));
		}
		body = new VBox { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		body.AddThemeConstantOverride("separation", 4);
		card.AddChild(body);
		return card;
	}

	private PanelContainer AnchorScoreTile(string texturePath, float value, Color accent, string meta)
	{
		var tile = AnchorTextureCard(
			texturePath, 
			out VBox body, 
			left: 14f, top: 92f, right: 14f, bottom: 8f,
			texLeft: 0f, texTop: 0f, texRight: 0f, texBottom: 0f
		);
		tile.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		tile.SizeFlagsStretchRatio = 1f;
		tile.CustomMinimumSize = new Vector2(0f, 148f);

		var number = CreateUiLabel(value.ToString("0.00", CultureInfo.InvariantCulture), 22, accent);
		number.HorizontalAlignment = HorizontalAlignment.Center;
		body.AddChild(number);
		body.AddChild(AnchorThinMeter(value, accent));
		
		var metaLbl = CreateUiLabel(meta, 10, AnchorInkSoft);
		metaLbl.HorizontalAlignment = HorizontalAlignment.Center;
		body.AddChild(metaLbl);
		return tile;
	}

	private Control AnchorSectionHeader(string title, string meta, Color accent)
	{
		var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		row.AddThemeConstantOverride("separation", 6);
		row.AddChild(CreateDiaryGlyph("um_tag", accent, 14f));
		var titleLabel = CreateUiLabel(title, 12, accent);
		titleLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		row.AddChild(titleLabel);
		if (!string.IsNullOrWhiteSpace(meta))
			row.AddChild(AnchorBadge(meta, accent));
		return row;
	}

	private Control AnchorThinMeter(float value, Color color)
	{
		var bar = CreateDiaryBar(color);
		bar.CustomMinimumSize = new Vector2(0f, 7f);
		bar.Value = Mathf.Clamp(value, 0f, 1f) * 100f;
		return bar;
	}

	private PanelContainer AnchorBeliefRow(string facet, string claim, float conf, int rec, int ev)
	{
		var card = AnchorCard(new Color(1f, 0.985f, 0.992f, 0.92f), AnchorPink, out VBox body);
		string facetVi = AnchorFacetNames.TryGetValue(facet, out var fv) ? fv : facet;
		var top = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		top.AddThemeConstantOverride("separation", 6);
		top.AddChild(AnchorBadge(facetVi, AnchorPink));
		var meta = CreateUiLabel($"{conf:0.00} · {rec} lần · {ev} chứng", 10, AnchorInkSoft);
		meta.HorizontalAlignment = HorizontalAlignment.Right;
		meta.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		top.AddChild(meta);
		body.AddChild(top);
		body.AddChild(AnchorWrap(claim, AnchorInk));
		body.AddChild(AnchorThinMeter(conf, AnchorPink));
		return card;
	}

	private static string AnchorMeaningLine(AnchorData d)
	{
		if (d.Irreplaceability >= 0.62f)
			return "rất khó thay thế";
		if (d.AnchorRole >= 0.42f || d.WitnessStrength >= 0.42f)
			return "đang thành neo";
		if (d.ModelThickness >= 0.35f)
			return "đã có nét";
		return "còn mỏng";
	}

	private PanelContainer AnchorColumn(string tag, string title, Color accent, float ratio, out VBox body)
	{
		var card = AnchorCard(new Color(1f, 0.96f, 0.98f, 0.97f), accent, out body);
		card.SizeFlagsStretchRatio = ratio;
		var header = new HBoxContainer();
		header.AddThemeConstantOverride("separation", 8);
		header.AddChild(CreateDiaryGlyph("um_tag", accent, 16f));
		header.AddChild(CreateUiLabel($"{tag}  {title}", 13, accent));
		body.AddChild(header);
		body.AddChild(new ColorRect
		{
			Color = new Color(accent.R, accent.G, accent.B, 0.25f),
			CustomMinimumSize = new Vector2(0f, 1f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		});
		return card;
	}

	private Control AnchorFlowArrow()
	{
		var wrap = new CenterContainer { CustomMinimumSize = new Vector2(22f, 0f) };
		wrap.AddChild(CreateUiLabel(">", 26, AnchorInkSoft));
		return wrap;
	}

	private Control AnchorMetricRow(string label, float value, Color color)
	{
		var col = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		col.AddThemeConstantOverride("separation", 2);
		var top = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		var lbl = CreateUiLabel(label, 11, AnchorInkSoft);
		lbl.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		top.AddChild(lbl);
		top.AddChild(CreateUiLabel(value.ToString("0.00", CultureInfo.InvariantCulture), 11, color));
		col.AddChild(top);
		var bar = CreateDiaryBar(color);
		bar.Value = Mathf.Clamp(value, 0f, 1f) * 100f;
		col.AddChild(bar);
		return col;
	}

	private PanelContainer AnchorBeliefCard(string facet, string claim, float conf, int rec, int ev)
	{
		var card = AnchorCard(new Color(1f, 0.97f, 0.985f, 0.97f), AnchorPink, out VBox b);
		string facetVi = AnchorFacetNames.TryGetValue(facet, out var fv) ? fv : facet;
		var top = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		top.AddChild(AnchorBadge(facetVi, AnchorPink));
		top.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		top.AddChild(CreateUiLabel($"thấy {rec} lần · {ev} bằng chứng", 10, AnchorInkSoft));
		b.AddChild(top);
		b.AddChild(AnchorWrap(claim, AnchorInk));
		b.AddChild(AnchorMetricRow("độ chắc", conf, AnchorPink));
		return card;
	}

	private Control AnchorRoleChips(AnchorData d)
	{
		var row = new HBoxContainer();
		row.AddThemeConstantOverride("separation", 6);
		row.AddChild(AnchorBadge("Cái Neo", d.AnchorRole >= 0.30f ? AnchorGold : AnchorDim));
		row.AddChild(AnchorBadge("Nhân Chứng", d.WitnessStrength >= 0.30f ? AnchorGold : AnchorDim));
		row.AddChild(AnchorBadge("Không Thay Thế", d.Irreplaceability >= 0.60f ? AnchorGold : AnchorDim));
		return row;
	}

	private Control AnchorGateFuse(string label, float value, float threshold, bool pass, bool enabled)
	{
		Color tone = !enabled ? AnchorDim : (pass ? AnchorAmber : AnchorIndigo);
		var col = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		col.AddThemeConstantOverride("separation", 2);
		var top = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		var lbl = CreateUiLabel(label, 12, tone);
		lbl.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		top.AddChild(lbl);
		top.AddChild(CreateUiLabel(
			$"{value.ToString("0.00", CultureInfo.InvariantCulture)} / {threshold.ToString("0.00", CultureInfo.InvariantCulture)}",
			11, tone));
		top.AddChild(AnchorBadge(pass ? "vượt" : "chờ", pass ? AnchorAmber : AnchorDim));
		col.AddChild(top);
		var bar = CreateDiaryBar(tone);
		bar.Value = Mathf.Clamp(value, 0f, 1f) * 100f;
		col.AddChild(bar);
		return col;
	}

	private Control AnchorSparkline(List<float> history, Color color)
	{
		var host = new HBoxContainer
		{
			CustomMinimumSize = new Vector2(0f, 40f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkEnd,
		};
		host.AddThemeConstantOverride("separation", 2);
		if (history == null || history.Count == 0)
		{
			host.AddChild(CreateUiLabel("(chưa có lịch sử)", 11, AnchorInkSoft));
			return host;
		}
		foreach (float v in history)
		{
			host.AddChild(new ColorRect
			{
				Color = color,
				CustomMinimumSize = new Vector2(5f, 4f + Mathf.Clamp(v, 0f, 1f) * 34f),
				SizeFlagsVertical = Control.SizeFlags.ShrinkEnd,
			});
		}
		return host;
	}

	private PanelContainer AnchorBadge(string text, Color color)
	{
		var chip = new PanelContainer();
		chip.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(color.R, color.G, color.B, 0.18f),
			BorderColor = new Color(color.R, color.G, color.B, 0.8f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 9, CornerRadiusTopRight = 9, CornerRadiusBottomRight = 9, CornerRadiusBottomLeft = 9,
			ContentMarginLeft = 8, ContentMarginRight = 8, ContentMarginTop = 2, ContentMarginBottom = 2,
		});
		var lbl = CreateUiLabel(text, 11, new Color(color.R * 0.7f, color.G * 0.6f, color.B * 0.6f));
		lbl.HorizontalAlignment = HorizontalAlignment.Center;
		chip.AddChild(lbl);
		return chip;
	}

	private Label AnchorWrap(string text, Color color)
	{
		var lbl = new Label
		{
			Text = string.IsNullOrWhiteSpace(text) ? "—" : text,
			AutowrapMode = TextServer.AutowrapMode.WordSmart,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		lbl.AddThemeFontSizeOverride("font_size", 12);
		lbl.AddThemeColorOverride("font_color", color);
		return lbl;
	}

	private Control AnchorEmpty(string text)
	{
		var card = AnchorCard(new Color(1f, 0.97f, 0.985f, 0.95f), AnchorInkSoft, out VBox b);
		b.AddChild(AnchorWrap(text, AnchorInkSoft));
		return card;
	}

	// ── JSON helpers ───────────────────────────────────────────────────────────
	private static float AnFloat(JsonElement o, string key)
	{
		return o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetSingle() : 0f;
	}

	private static int AnInt(JsonElement o, string key)
	{
		return o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetInt32() : 0;
	}

	private static bool AnBool(JsonElement o, string key)
	{
		return o.TryGetProperty(key, out var v) && (v.ValueKind == JsonValueKind.True || v.ValueKind == JsonValueKind.False) && v.GetBoolean();
	}

	private static string AnStr(JsonElement o, string key, string fallback = "")
	{
		return o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? (v.GetString() ?? fallback) : fallback;
	}

	private static void ReadGate(JsonElement gate, string key, out float value, out float threshold, out bool pass)
	{
		value = 0f; threshold = 0f; pass = false;
		if (gate.TryGetProperty(key, out var g) && g.ValueKind == JsonValueKind.Object)
		{
			value = AnFloat(g, "value");
			threshold = AnFloat(g, "threshold");
			pass = AnBool(g, "pass");
		}
	}
}
