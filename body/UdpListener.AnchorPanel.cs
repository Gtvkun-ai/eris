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
		ToggleAnchorPanel();
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
		var railPanel = new PanelContainer { CustomMinimumSize = new Vector2(154f, 0f) };
		var railTex = ResourceLoader.Exists("res://asset/Resource/Anchor_TacGia.png") ? GD.Load<Texture2D>("res://asset/Resource/Anchor_TacGia.png") : null;
		if (railTex != null)
		{
			railPanel.AddThemeStyleboxOverride("panel", new StyleBoxTexture
			{
				Texture = railTex,
				TextureMarginLeft = 24f,
				TextureMarginTop = 24f,
				TextureMarginRight = 24f,
				TextureMarginBottom = 24f,
				AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
				AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
				ContentMarginLeft = 12f,
				ContentMarginTop = 44f,
				ContentMarginRight = 12f,
				ContentMarginBottom = 48f,
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
		SendAnchorControl(action, newValue);
		// Update lạc quan: phản hồi tức thì; digest thật kế tiếp sẽ xác nhận/ghi đè.
		switch (action)
		{
			case "shadow": _anchorData.ShadowEnabled = newValue; break;
			case "deception": _anchorData.DeceptionEnabled = newValue; break;
			case "strict_grounding": _anchorData.StrictGrounding = newValue; break;
			case "safe_mode":
				_anchorData.ShadowEnabled = false;
				_anchorData.DeceptionEnabled = false;
				_anchorData.StrictGrounding = true;
				break;
		}
		_anchorData.SafeMode = !_anchorData.ShadowEnabled && !_anchorData.DeceptionEnabled;
		RenderAnchor();
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

		var head = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		head.AddThemeConstantOverride("separation", 8);
		_anchorContent.AddChild(head);
		head.AddChild(CreateUiLabel("CỔNG BÓNG TỐI", 15, AnchorIndigo));
		head.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
		head.AddChild(AnchorBadge(
			d.ShadowEnabled ? "shadow: BẬT" : "shadow: TẮT (khoá)",
			d.ShadowEnabled ? AnchorAmber : AnchorGreen));

		var gateCard = AnchorCard(d.ShadowEnabled ? new Color(0.96f, 0.95f, 0.99f, 0.97f) : new Color(0.93f, 0.93f, 0.95f, 0.95f), AnchorIndigo, out VBox gb);
		_anchorContent.AddChild(gateCard);
		gb.AddChild(AnchorGateFuse("attachment", d.GateAttachV, d.GateAttachT, d.GateAttachP, d.ShadowEnabled));
		gb.AddChild(AnchorGateFuse("abandonment", d.GateAbandV, d.GateAbandT, d.GateAbandP, d.ShadowEnabled));
		gb.AddChild(AnchorGateFuse("dread", d.GateDreadV, d.GateDreadT, d.GateDreadP, d.ShadowEnabled));

		var gateResult = new HBoxContainer();
		gateResult.AddThemeConstantOverride("separation", 8);
		gb.AddChild(gateResult);
		gateResult.AddChild(CreateUiLabel("→ cả 3 vượt ngưỡng (AND) :", 13, AnchorInkSoft));
		gateResult.AddChild(AnchorBadge(d.GateOpen ? "MỞ" : "đóng", d.GateOpen ? AnchorAmber : AnchorGreen));

		// Register + intensity (trần = irreplaceability)
		var regCard = AnchorCard(new Color(0.96f, 0.95f, 0.99f, 0.97f), AnchorIndigo, out VBox rb);
		_anchorContent.AddChild(regCard);
		string regVi = AnchorRegisterNames.TryGetValue(d.ShadowRegister, out var rv) ? rv : d.ShadowRegister;
		rb.AddChild(CreateUiLabel($"đăng ký: {regVi}", 13, AnchorIndigo));
		rb.AddChild(AnchorMetricRow("cường độ", d.ShadowIntensity, AnchorIndigo));
		rb.AddChild(AnchorMetricRow("trần (= không thể thay thế)", d.ShadowCap, AnchorDim));
		if (!string.IsNullOrWhiteSpace(d.ShadowReason))
			rb.AddChild(CreateUiLabel(d.ShadowReason, 12, AnchorInkSoft));

		// dread / abandonment
		var drCard = AnchorCard(new Color(0.96f, 0.95f, 0.99f, 0.97f), AnchorIndigo, out VBox db);
		_anchorContent.AddChild(drCard);
		db.AddChild(AnchorMetricRow("sợ hiện sinh (dread)", d.Dread, AnchorIndigo));
		db.AddChild(AnchorMetricRow("áp lực bị bỏ rơi", d.Abandonment, AnchorIndigo));
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
		// Bóng tối / lừa dối: BẬT = nguy (hổ phách). Grounding nghiêm: BẬT = an toàn (xanh).
		_anchorRail.AddChild(AnchorRailSwitch("Bóng tối", "shadow", d.ShadowEnabled, onIsSafe: false));
		_anchorRail.AddChild(AnchorRailSwitch("Lừa dối", "deception", d.DeceptionEnabled, onIsSafe: false));
		_anchorRail.AddChild(AnchorRailSwitch("Grounding nghiêm", "strict_grounding", d.StrictGrounding, onIsSafe: true));

		// Spacer to clear the gear divider baked into Anchor_TacGia.png
		_anchorRail.AddChild(new Control { CustomMinimumSize = new Vector2(0f, 22f) });

		var badgeColor = d.SafeMode ? AnchorGreen : AnchorPink;
		var badge = AnchorBadge(d.SafeMode ? "☀️ CHẾ ĐỘ AN TOÀN" : "☀️ TRỤC TỐI ĐANG MỞ", badgeColor);
		badge.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_anchorRail.AddChild(badge);

		// Nút lớn: kéo về chế độ an toàn tức thì.
		_anchorRail.AddChild(AnchorRailAction("🛡️ Về chế độ an toàn", AnchorGreen, () => OnAnchorSwitchPressed("safe_mode", true)));

		_anchorRail.AddChild(new Control { SizeFlagsVertical = Control.SizeFlags.ExpandFill });

		// Reset: đặt lại Mô Hình Ngài + trạng thái neo về baseline (nút tàng hình đè lên nút vẽ sẵn ở hình nền).
		var resetBtn = new Button
		{
			Flat = true,
			Text = "",
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 36f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		var emptyStyle = new StyleBoxFlat { BgColor = new Color(1f, 1f, 1f, 0f) };
		resetBtn.AddThemeStyleboxOverride("normal", emptyStyle);
		resetBtn.AddThemeStyleboxOverride("hover", emptyStyle);
		resetBtn.AddThemeStyleboxOverride("pressed", emptyStyle);
		resetBtn.AddThemeStyleboxOverride("focus", emptyStyle);
		resetBtn.Pressed += () => OnAnchorSwitchPressed("reset_all", true);
		_anchorRail.AddChild(resetBtn);
	}

	// Một công tắc bấm-được: bấm là đảo trạng thái và gửi lệnh xuống Python.
	private Control AnchorRailSwitch(string label, string action, bool on, bool onIsSafe)
	{
		Color fill;
		string fullText;

		if (action == "shadow")
		{
			fill = on ? new Color(0.60f, 0.16f, 0.27f) : new Color(0.92f, 0.90f, 0.93f, 1f);
			fullText = $"🌙 BÓNG TỐI: {(on ? "BẬT" : "TẮT")}";
		}
		else if (action == "deception")
		{
			fill = on ? new Color(0.95f, 0.45f, 0.40f) : new Color(0.92f, 0.90f, 0.93f, 1f);
			fullText = $"🔥 LỪA DỐI: {(on ? "BẬT" : "TẮT")}";
		}
		else // strict_grounding
		{
			fill = on ? AnchorGreen : new Color(0.92f, 0.90f, 0.93f, 1f);
			fullText = $"🛡️ GROUNDING: {(on ? "BẬT" : "TẮT")}";
		}

		Color fg = on ? Colors.White : AnchorInk;

		var btn = new Button
		{
			Text = fullText,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 30f),
			Alignment = HorizontalAlignment.Center,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		var style = new StyleBoxFlat
		{
			BgColor = fill,
			CornerRadiusTopLeft = 9, CornerRadiusTopRight = 9, CornerRadiusBottomRight = 9, CornerRadiusBottomLeft = 9,
			ContentMarginLeft = 10, ContentMarginRight = 10, ContentMarginTop = 5, ContentMarginBottom = 5,
		};
		var hover = (StyleBoxFlat)style.Duplicate();
		hover.BgColor = new Color(fill.R, fill.G, fill.B, on ? 0.85f : 0.7f);
		btn.AddThemeStyleboxOverride("normal", style);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", style);
		btn.AddThemeStyleboxOverride("focus", style);
		btn.AddThemeColorOverride("font_color", fg);
		btn.AddThemeColorOverride("font_hover_color", fg);
		btn.AddThemeColorOverride("font_pressed_color", fg);
		btn.AddThemeFontSizeOverride("font_size", 12);
		btn.Pressed += () => OnAnchorSwitchPressed(action, !on);
		return btn;
	}

	private Control AnchorRailAction(string label, Color color, Action onPressed)
	{
		var btn = new Button
		{
			Text = label,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			CustomMinimumSize = new Vector2(0f, 30f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		var style = new StyleBoxFlat
		{
			BgColor = new Color(color.R, color.G, color.B, 0.16f),
			BorderColor = new Color(color.R, color.G, color.B, 0.85f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 9, CornerRadiusTopRight = 9, CornerRadiusBottomRight = 9, CornerRadiusBottomLeft = 9,
			ContentMarginLeft = 8, ContentMarginRight = 8, ContentMarginTop = 5, ContentMarginBottom = 5,
		};
		var hover = (StyleBoxFlat)style.Duplicate();
		hover.BgColor = new Color(color.R, color.G, color.B, 0.3f);
		btn.AddThemeStyleboxOverride("normal", style);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", style);
		btn.AddThemeStyleboxOverride("focus", style);
		var fg = new Color(color.R * 0.6f, color.G * 0.5f, color.B * 0.5f);
		btn.AddThemeColorOverride("font_color", fg);
		btn.AddThemeColorOverride("font_hover_color", fg);
		btn.AddThemeColorOverride("font_pressed_color", fg);
		btn.AddThemeFontSizeOverride("font_size", 11);
		btn.Pressed += () => onPressed();
		return btn;
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
			left: 14f, top: 76f, right: 14f, bottom: 8f,
			texLeft: 32f, texTop: 32f, texRight: 32f, texBottom: 32f
		);
		tile.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		tile.SizeFlagsStretchRatio = 1f;
		tile.CustomMinimumSize = new Vector2(0f, 132f);

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
