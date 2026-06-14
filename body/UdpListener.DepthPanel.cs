using Godot;
using System;
using System.Text.Json;
using System.Collections.Generic;
using VBox = Godot.VBoxContainer;

// ─────────────────────────────────────────────────────────────────────────────
//  Tab "Chiều Sâu" (Depth): dashboard nội tâm SỐNG.
//  Nền là ảnh khung scrapbook ChieuSauKhung.png (gáy, washi, góc gập, tim, header
//  "CHIỀU SÂU" đã baked sẵn). Code CHỈ thả chữ live vào 8 ô đã chừa trống + 1 nút
//  ✕ trong suốt đè lên ✕ vẽ sẵn. Toạ độ ô là TỈ LỆ (constant) nên co giãn được và
//  dễ tinh chỉnh nếu lệch.
//
//  Sáu cờ chiều-sâu (N1–N3) TỰ BẬT lúc khởi động (coordinator.bootstrap_defaults).
//  Panel CHỈ XEM — không toggle.
// ─────────────────────────────────────────────────────────────────────────────
public partial class UdpListener : Node2D
{
	// Ảnh khung gốc 1040×622 — panel giữ đúng tỉ lệ này để nền không méo.
	private static readonly Vector2 DepthPanelMinSize = new(1040f, 622f);
	private const string DepthFramePath = "res://asset/Resource/ChieuSauKhung.png";

	private Panel _depthPanel;
	private Button _contextDepthButton;

	private string _latestDepthJson = "";

	private ProgressBar _depthWantBar, _depthSuppressBar, _depthAllowBar;
	private Label _depthWantVal, _depthSuppressVal, _depthAllowVal;
	private Label _depthStanceLabel, _depthTomLabel, _depthHeaderLabel, _depthAffectLabel, _depthContextLabel;
	private VBox _depthN2Body, _depthInteriorityBody, _depthLogBody;
	private readonly Dictionary<string, Label> _depthFlagChips = new();
	private Font _depthFontRegular, _depthFontBold;

	private static readonly (string Key, string Short)[] DepthFlagChips =
	{
		("emotional_consequence", "N1"),
		("development_growth",    "N2"),
		("interior_surface",      "interiority"),
		("tom_advisor",           "tom"),
		("real_embeddings",       "embed"),
		("private_mind",          "mind"),
	};

	// ── Toạ độ ô theo TỈ LỆ (x0,y0,x1,y1) — đo từ profile khung. Chỉnh ở đây. ──
	private static readonly Rect2 SlotAffect   = RectLTRB(0.080f, 0.130f, 0.490f, 0.295f);
	private static readonly Rect2 SlotN1       = RectLTRB(0.080f, 0.320f, 0.490f, 0.565f);
	private static readonly Rect2 SlotInterior = RectLTRB(0.080f, 0.590f, 0.490f, 0.855f);
	private static readonly Rect2 SlotTom      = RectLTRB(0.515f, 0.130f, 0.930f, 0.295f);
	private static readonly Rect2 SlotN2       = RectLTRB(0.515f, 0.320f, 0.930f, 0.565f);
	private static readonly Rect2 SlotLog      = RectLTRB(0.515f, 0.590f, 0.930f, 0.740f);
	private static readonly Rect2 SlotContext  = RectLTRB(0.515f, 0.765f, 0.930f, 0.855f);
	private static readonly Rect2 SlotCollab   = RectLTRB(0.080f, 0.878f, 0.930f, 0.965f);
	private static readonly Rect2 SlotHeader   = RectLTRB(0.345f, 0.042f, 0.690f, 0.104f);
	private static readonly Rect2 SlotClose    = RectLTRB(0.870f, 0.030f, 0.960f, 0.115f);

	private static Rect2 RectLTRB(float l, float t, float r, float b) => new(l, t, r - l, b - t);

	// ── Palette (đồng bộ tông hồng của app) ──────────────────────────────────
	private static readonly Color DepthInk     = new(0.62f, 0.10f, 0.36f);
	private static readonly Color DepthInkSoft = new(0.74f, 0.42f, 0.56f);
	private static readonly Color DepthBody    = new(0.40f, 0.10f, 0.26f);
	private static readonly Color DepthAccent  = new(0.93f, 0.40f, 0.60f);
	private static readonly Color DepthDim     = new(0.66f, 0.54f, 0.62f);
	private static readonly Color DepthGreen   = new(0.28f, 0.58f, 0.40f);
	private static readonly Color DepthAmber   = new(0.82f, 0.50f, 0.16f);

	// ── Vòng đời ────────────────────────────────────────────────────────────
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
		_depthPanel.ClipContents = true;
		_depthPanel.Size = DepthPanelMinSize;
		Vector2 screenSize = GetViewportRect().Size;
		_depthPanel.Position = new Vector2(
			Mathf.Max(0f, (screenSize.X - DepthPanelMinSize.X) * 0.5f),
			Mathf.Max(0f, (screenSize.Y - DepthPanelMinSize.Y) * 0.5f));
		RefreshDepthPanel();
	}

	// ── Dựng khung: ảnh nền + các ô chữ trong suốt ───────────────────────────
	private void BuildDepthPanelUi()
	{
		if (_depthPanel == null)
			return;

		ApplyDepthFontTheme();

		// Panel không tự vẽ nền (ảnh lo phần đó). Có ảnh -> StyleBoxEmpty; thiếu ảnh
		// -> fallback nền hồng phẳng cho khỏi trống trơn.
		var frameTex = ResourceLoader.Exists(DepthFramePath) ? GD.Load<Texture2D>(DepthFramePath) : null;
		if (frameTex != null)
		{
			_depthPanel.AddThemeStyleboxOverride("panel", new StyleBoxEmpty());
			var bg = new TextureRect
			{
				Texture = frameTex,
				ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
				StretchMode = TextureRect.StretchModeEnum.Scale,
				MouseFilter = Control.MouseFilterEnum.Ignore,
			};
			bg.SetAnchorsPreset(Control.LayoutPreset.FullRect);
			_depthPanel.AddChild(bg);
		}
		else
		{
			_depthPanel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
			{
				BgColor = new Color(1f, 0.95f, 0.97f, 0.99f),
				BorderColor = new Color(0.96f, 0.72f, 0.82f, 1f),
				BorderWidthLeft = 3, BorderWidthTop = 3, BorderWidthRight = 3, BorderWidthBottom = 3,
				CornerRadiusTopLeft = 26, CornerRadiusTopRight = 26,
				CornerRadiusBottomRight = 26, CornerRadiusBottomLeft = 26,
			});
		}

		// Nút đóng trong suốt đè lên ✕ vẽ sẵn.
		var close = new Button { Flat = true, Text = "" };
		PlaceBySlot(close, SlotClose);
		close.AddThemeStyleboxOverride("normal", new StyleBoxEmpty());
		close.AddThemeStyleboxOverride("hover", new StyleBoxEmpty());
		close.AddThemeStyleboxOverride("pressed", new StyleBoxEmpty());
		close.AddThemeStyleboxOverride("focus", new StyleBoxEmpty());
		close.MouseDefaultCursorShape = Control.CursorShape.PointingHand;
		close.Pressed += () => _depthPanel.Visible = false;
		_depthPanel.AddChild(close);

		// Phụ đề động ở header (model · cờ · alive), cạnh chữ "CHIỀU SÂU" baked.
		var headerBox = NewSlot(SlotHeader);
		_depthHeaderLabel = Mk("· đang khởi tạo …", 13, DepthInkSoft);
		_depthHeaderLabel.VerticalAlignment = VerticalAlignment.Center;
		headerBox.AddChild(_depthHeaderLabel);

		// ── 8 ô nội dung ──────────────────────────────────────────────────────
		var affectBody = NewCardSlot(SlotAffect, "CẢM XÚC (affect)", "feel");
		_depthAffectLabel = Mk("—", 14, DepthBody);
		_depthAffectLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		affectBody.AddChild(_depthAffectLabel);

		var n1Body = NewCardSlot(SlotN1, "GIẰNG CO NỘI TÂM (N1)", "tought");
		_depthWantBar = DepthBarRow(n1Body, "muốn nói", DepthAccent, out _depthWantVal);
		_depthSuppressBar = DepthBarRow(n1Body, "kìm nén", DepthAmber, out _depthSuppressVal);
		_depthAllowBar = DepthBarRow(n1Body, "cho phép", DepthGreen, out _depthAllowVal);
		_depthStanceLabel = Mk("stance: —", 13, DepthDim);
		n1Body.AddChild(_depthStanceLabel);

		_depthInteriorityBody = NewCardSlot(SlotInterior, "DÒNG NỘI TÂM (interiority)", "diary_surface");

		var tomBody = NewCardSlot(SlotTom, "THẤU HIỂU NGÀI (tom_read)", "diary_analysis");
		_depthTomLabel = Mk("chưa đọc được gì", 14, DepthBody);
		_depthTomLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		tomBody.AddChild(_depthTomLabel);

		_depthN2Body = NewCardSlot(SlotN2, "LIÊN TỤC BẢN THÂN (N2)", "diary_future");

		_depthLogBody = NewCardSlot(SlotLog, "NHẬT KÝ TÍN HIỆU", "diary_now");

		var ctxBody = NewCardSlot(SlotContext, "CONTEXT", "diary_memory");
		_depthContextLabel = Mk("—", 14, DepthInkSoft);
		ctxBody.AddChild(_depthContextLabel);

		// Dải CỘNG TÁC: cờ tự bật, pill pastel read-only.
		var collabBody = NewCardSlot(SlotCollab, "CỘNG TÁC  ·  tự bật", "force");
		var chipRow = new HBoxContainer();
		chipRow.AddThemeConstantOverride("separation", 10);
		collabBody.AddChild(chipRow);
		foreach (var (key, shortLabel) in DepthFlagChips)
		{
			var pill = new PanelContainer();
			pill.AddThemeStyleboxOverride("panel", DepthPillStyle(false));
			var chip = MkBold(shortLabel, 13, DepthDim);
			pill.AddChild(chip);
			_depthFlagChips[key] = chip;
			chipRow.AddChild(pill);
		}

		RefreshDepthPanel();
	}

	private static StyleBoxFlat DepthPillStyle(bool on)
	{
		return new StyleBoxFlat
		{
			BgColor = on ? new Color(0.84f, 0.95f, 0.87f, 0.95f) : new Color(0.99f, 0.92f, 0.95f, 0.92f),
			BorderColor = on ? new Color(0.40f, 0.70f, 0.50f, 0.55f) : new Color(0.92f, 0.74f, 0.83f, 0.55f),
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 9, CornerRadiusTopRight = 9, CornerRadiusBottomLeft = 9, CornerRadiusBottomRight = 9,
			ContentMarginLeft = 10, ContentMarginRight = 10, ContentMarginTop = 2, ContentMarginBottom = 2,
		};
	}

	// ── Helper layout ─────────────────────────────────────────────────────────
	private Label Mk(string text, int fontSize, Color color)
	{
		var lbl = CreateUiLabel(text, fontSize, color);
		if (_depthFontRegular != null)
			lbl.AddThemeFontOverride("font", _depthFontRegular);
		return lbl;
	}

	private Label MkBold(string text, int fontSize, Color color)
	{
		var lbl = CreateUiLabel(text, fontSize, color);
		if (_depthFontBold != null)
			lbl.AddThemeFontOverride("font", _depthFontBold);
		return lbl;
	}

	// Nạp font Mali (OFL) đã nhúng. Thử resource đã import -> nạp thẳng bytes ->
	// null (rơi về SystemFont qua theme). Không bao giờ ném.
	private Font LoadDepthFont(string fileName)
	{
		string res = $"res://asset/Resource/{fileName}";
		try
		{
			if (ResourceLoader.Exists(res))
			{
				var f = ResourceLoader.Load<Font>(res);
				if (f != null)
					return f;
			}
		}
		catch { }
		try
		{
			if (FileAccess.FileExists(res))
			{
				byte[] bytes = FileAccess.GetFileAsBytes(res);
				if (bytes != null && bytes.Length > 0)
				{
					var ff = new FontFile();
					ff.Data = bytes;
					return ff;
				}
			}
		}
		catch { }
		return null;
	}

	// Gắn font cho toàn panel: Mali nhúng (nét tròn, hỗ trợ tiếng Việt) thay font
	// mặc định "phèn". Thiếu file -> SystemFont (Quicksand/Segoe UI). Bật antialias.
	private void ApplyDepthFontTheme()
	{
		_depthFontRegular = LoadDepthFont("Mali-Regular.ttf");
		_depthFontBold = LoadDepthFont("Mali-SemiBold.ttf") ?? _depthFontRegular;

		Font defaultFont = _depthFontRegular;
		if (defaultFont == null)
		{
			defaultFont = new SystemFont
			{
				FontNames = new[] { "Quicksand", "Comfortaa", "Nunito", "Segoe UI", "Arial" },
				Antialiasing = TextServer.FontAntialiasing.Gray,
				SubpixelPositioning = TextServer.SubpixelPositioning.Auto,
				Hinting = TextServer.Hinting.Light,
			};
			_depthFontRegular = defaultFont;
			_depthFontBold ??= defaultFont;
		}

		var theme = new Theme
		{
			DefaultFont = defaultFont,
			DefaultFontSize = 14,
		};
		_depthPanel.Theme = theme;
	}

	private void PlaceBySlot(Control ctrl, Rect2 slot)
	{
		ctrl.AnchorLeft = slot.Position.X;
		ctrl.AnchorTop = slot.Position.Y;
		ctrl.AnchorRight = slot.Position.X + slot.Size.X;
		ctrl.AnchorBottom = slot.Position.Y + slot.Size.Y;
		ctrl.OffsetLeft = 0f; ctrl.OffsetTop = 0f; ctrl.OffsetRight = 0f; ctrl.OffsetBottom = 0f;
	}

	// Ô trong suốt đặt theo tỉ lệ, có padding nhỏ + clip để chữ không tràn decor.
	private VBox NewSlot(Rect2 slot)
	{
		var box = new VBox { ClipContents = true };
		PlaceBySlot(box, slot);
		box.OffsetLeft = 6f; box.OffsetTop = 4f; box.OffsetRight = -6f; box.OffsetBottom = -4f;
		box.AddThemeConstantOverride("separation", 3);
		_depthPanel.AddChild(box);
		return box;
	}

	// Ô card: [icon + tiêu đề] + gạch nhấn + body. Trả body để nhồi nội dung.
	private VBox NewCardSlot(Rect2 slot, string heading, string icon = "")
	{
		var outer = NewSlot(slot);
		outer.AddThemeConstantOverride("separation", 4);

		var headRow = new HBoxContainer();
		headRow.AddThemeConstantOverride("separation", 7);
		if (!string.IsNullOrEmpty(icon))
		{
			var glyph = CreateDiaryGlyph(icon, DepthAccent, 19f);
			glyph.SizeFlagsVertical = Control.SizeFlags.ShrinkCenter;
			headRow.AddChild(glyph);
		}
		var headLbl = MkBold(heading, 15, DepthInk);
		headLbl.VerticalAlignment = VerticalAlignment.Center;
		headRow.AddChild(headLbl);
		outer.AddChild(headRow);

		// Gạch nhấn mảnh dưới tiêu đề cho có lớp lang.
		outer.AddChild(new ColorRect
		{
			Color = new Color(DepthAccent.R, DepthAccent.G, DepthAccent.B, 0.30f),
			CustomMinimumSize = new Vector2(0f, 1f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		});

		var body = new VBox { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, SizeFlagsVertical = Control.SizeFlags.ExpandFill };
		body.AddThemeConstantOverride("separation", 5);
		body.ClipContents = true;
		outer.AddChild(body);
		return body;
	}

	private ProgressBar DepthBarRow(VBox parent, string label, Color fill, out Label valueLabel)
	{
		var row = new HBoxContainer();
		row.AddThemeConstantOverride("separation", 8);
		var lbl = Mk(label, 14, DepthBody);
		lbl.CustomMinimumSize = new Vector2(86f, 0f);
		row.AddChild(lbl);
		var bar = new ProgressBar
		{
			MinValue = 0, MaxValue = 1, Value = 0, ShowPercentage = false,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
			CustomMinimumSize = new Vector2(0f, 13f),
		};
		bar.AddThemeStyleboxOverride("background", new StyleBoxFlat
		{
			BgColor = new Color(0.97f, 0.86f, 0.91f, 0.85f),
			CornerRadiusTopLeft = 6, CornerRadiusTopRight = 6, CornerRadiusBottomLeft = 6, CornerRadiusBottomRight = 6,
		});
		bar.AddThemeStyleboxOverride("fill", new StyleBoxFlat
		{
			BgColor = fill,
			CornerRadiusTopLeft = 6, CornerRadiusTopRight = 6, CornerRadiusBottomLeft = 6, CornerRadiusBottomRight = 6,
		});
		row.AddChild(bar);
		valueLabel = Mk("0.00", 13, fill);
		valueLabel.CustomMinimumSize = new Vector2(40f, 0f);
		valueLabel.HorizontalAlignment = HorizontalAlignment.Right;
		row.AddChild(valueLabel);
		parent.AddChild(row);
		return bar;
	}

	private Label DepthLine(string text, Color color, int fontSize = 13)
	{
		var lbl = Mk(text, fontSize, color);
		lbl.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		return lbl;
	}

	// ── Nhận block "depth" ──────────────────────────────────────────────────
	private void TryCaptureDepthBlock(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return;
		try
		{
			using var doc = JsonDocument.Parse(raw);
			var root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("depth", out var d) || d.ValueKind != JsonValueKind.Object)
				return;
			_latestDepthJson = raw;
			if (_depthPanel != null && _depthPanel.Visible)
				RefreshDepthPanel();
		}
		catch (Exception ex)
		{
			GD.Print($"[depth] parse fail: {ex.Message}");
		}
	}

	// ── Refresh ────────────────────────────────────────────────────────────
	private void RefreshDepthPanel()
	{
		if (_depthPanel == null || string.IsNullOrWhiteSpace(_latestDepthJson))
			return;
		try
		{
			using var doc = JsonDocument.Parse(_latestDepthJson);
			var root = doc.RootElement;
			if (!root.TryGetProperty("depth", out var d) || d.ValueKind != JsonValueKind.Object)
				return;

			if (_depthHeaderLabel != null && d.TryGetProperty("identity", out var id) && id.ValueKind == JsonValueKind.Object)
			{
				string model = AnStr(id, "model", "gemini");
				string channel = AnStr(id, "channel", "chat");
				int on = AnInt(id, "flags_on");
				int total = AnInt(id, "flags_total");
				bool alive = AnBool(id, "alive");
				_depthHeaderLabel.Text = $"đang [{channel}] · {model} · {on}/{(total > 0 ? total : 6)} cờ · {(alive ? "alive ✓" : "ngủ")}";
			}

			if (d.TryGetProperty("flags", out var flags) && flags.ValueKind == JsonValueKind.Object)
				foreach (var (key, chip) in _depthFlagChips)
				{
					bool ison = AnBool(flags, key);
					string baseLabel = chip.Text.Split(']')[0] + "]";
					chip.Text = ison ? $"{baseLabel} ✓" : $"{baseLabel} ·";
					chip.AddThemeColorOverride("font_color", ison ? DepthGreen : DepthDim);
				}

			if (_depthAffectLabel != null && d.TryGetProperty("affect", out var af) && af.ValueKind == JsonValueKind.Object)
			{
				if (AnBool(af, "live"))
				{
					float val = AnFloat(af, "valence");
					float aro = AnFloat(af, "arousal");
					string st = AnStr(af, "stance");
					_depthAffectLabel.Text = $"valence {val:+0.00;-0.00}   ·   arousal {aro:0.00}\nstance: {(string.IsNullOrEmpty(st) ? "—" : st)}";
					_depthAffectLabel.AddThemeColorOverride("font_color", DepthBody);
				}
				else
				{
					_depthAffectLabel.Text = "chưa có tín hiệu cảm xúc sống";
					_depthAffectLabel.AddThemeColorOverride("font_color", DepthDim);
				}
			}

			if (d.TryGetProperty("expression", out var ex) && ex.ValueKind == JsonValueKind.Object)
			{
				if (_depthWantBar != null) _depthWantBar.Value = AnFloat(ex, "want");
				if (_depthSuppressBar != null) _depthSuppressBar.Value = AnFloat(ex, "suppress");
				if (_depthAllowBar != null) _depthAllowBar.Value = AnFloat(ex, "allowed");
				if (_depthStanceLabel != null)
				{
					string st = AnStr(ex, "stance");
					_depthStanceLabel.Text = "stance: " + (string.IsNullOrEmpty(st) ? "—" : st);
				}
			}

			if (_depthN2Body != null)
			{
				AnchorClear(_depthN2Body);
				if (d.TryGetProperty("n2", out var n2) && n2.ValueKind == JsonValueKind.Object)
				{
					if (n2.TryGetProperty("axes", out var axes) && axes.ValueKind == JsonValueKind.Array)
						foreach (var ax in axes.EnumerateArray())
						{
							if (ax.ValueKind != JsonValueKind.Object)
								continue;
							string label = AnStr(ax, "label");
							float delta = AnFloat(ax, "delta");
							var c = delta > 0 ? DepthGreen : delta < 0 ? DepthAmber : DepthDim;
							_depthN2Body.AddChild(DepthLine($"{label}   {delta:+0.00;-0.00}", c, 13));
						}
					string sentence = AnStr(n2, "sentence");
					if (!string.IsNullOrWhiteSpace(sentence))
						_depthN2Body.AddChild(DepthLine($"\"{sentence}\"", DepthInkSoft, 12));
					if (n2.TryGetProperty("attachment", out var att) && att.ValueKind == JsonValueKind.Object && AnBool(att, "live"))
						_depthN2Body.AddChild(DepthLine($"attach  {AnFloat(att, "value"):+0.00;-0.00}", DepthAccent, 12));
				}
				if (_depthN2Body.GetChildren().Count == 0)
					_depthN2Body.AddChild(DepthLine("chưa lệch khỏi lúc mới gặp", DepthDim, 13));
			}

			if (_depthInteriorityBody != null)
			{
				AnchorClear(_depthInteriorityBody);
				bool any = false;
				if (d.TryGetProperty("interiority", out var inter) && inter.ValueKind == JsonValueKind.Object
					&& inter.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array)
					foreach (var it in items.EnumerateArray())
					{
						if (it.ValueKind != JsonValueKind.Object)
							continue;
						string theme = AnStr(it, "theme");
						if (string.IsNullOrWhiteSpace(theme))
							continue;
						int rec = AnInt(it, "recurrence");
						float pr = AnFloat(it, "pressure");
						string recTxt = rec > 0 ? $"  x{rec}" : "";
						_depthInteriorityBody.AddChild(DepthLine($"·  {theme}{recTxt}   ({pr:0.00})", DepthBody, 13));
						any = true;
					}
				if (!any)
					_depthInteriorityBody.AddChild(DepthLine("chưa có bận tâm nào được ghi", DepthDim, 13));
			}

			if (_depthTomLabel != null)
			{
				string tomText = "";
				float tomConf = -1f;
				if (d.TryGetProperty("tom_read_rich", out var tr) && tr.ValueKind == JsonValueKind.Object && AnBool(tr, "live"))
				{
					tomText = AnStr(tr, "text");
					tomConf = AnFloat(tr, "confidence");
				}
				if (string.IsNullOrWhiteSpace(tomText))
					tomText = AnStr(d, "tom_read");
				if (string.IsNullOrWhiteSpace(tomText))
					_depthTomLabel.Text = "chưa đọc được gì";
				else
					_depthTomLabel.Text = tomConf >= 0f ? $"\"{tomText}\"  (~{tomConf:0.00})" : tomText;
			}

			if (_depthLogBody != null)
			{
				AnchorClear(_depthLogBody);
				bool any = false;
				if (d.TryGetProperty("signal_log", out var log) && log.ValueKind == JsonValueKind.Array)
				{
					int shown = 0;
					foreach (var entry in log.EnumerateArray())
					{
						if (shown >= 5)
							break;
						string line = entry.ValueKind == JsonValueKind.String
							? entry.GetString()
							: entry.ValueKind == JsonValueKind.Object ? AnStr(entry, "text") : "";
						if (string.IsNullOrWhiteSpace(line))
							continue;
						_depthLogBody.AddChild(DepthLine($"·  {line}", DepthInkSoft, 12));
						shown++; any = true;
					}
				}
				if (!any)
					_depthLogBody.AddChild(DepthLine("im lặng — chưa có tín hiệu nổi", DepthDim, 12));
			}

			if (_depthContextLabel != null && d.TryGetProperty("context", out var ctx) && ctx.ValueKind == JsonValueKind.Array)
			{
				var tags = new List<string>();
				foreach (var t in ctx.EnumerateArray())
					if (t.ValueKind == JsonValueKind.String)
						tags.Add(t.GetString());
				_depthContextLabel.Text = tags.Count > 0 ? string.Join("   ·   ", tags) : "—";
			}
		}
		catch (Exception ex)
		{
			GD.Print($"[depth] refresh fail: {ex.Message}");
		}
	}
}
