using Godot;
using System;
using System.Text.Json;

// ─────────────────────────────────────────────────────────────────────────────
//  TAB GIA SƯ — Eris đi hỏi trợ lý Gemini.
//  Một thẻ nhỏ nổi góc màn hình: tiêu đề + trạng thái động (đang gõ/đọc/ghi nhớ),
//  câu hỏi gõ ra từng chữ (typewriter), rồi câu trả lời gõ ra khi xong. Tự ẩn.
//  Data đến qua UDP 4242 với parse_mode="tutor_event" (xem TutorStageEmitter).
//  Thuần trang trí: không bắt chuột (click xuyên qua).
// ─────────────────────────────────────────────────────────────────────────────
public partial class UdpListener : Node2D
{
	private static readonly Vector2 TutorPanelMinSize = new(560f, 170f);

	private Panel _tutorPanel;
	private VBoxContainer _tutorRoot;
	private Label _tutorTitleLabel;
	private Label _tutorStatusLabel;
	private Button _tutorHideButton;
	private RichTextLabel _tutorQuestionLabel;
	private RichTextLabel _tutorAnswerLabel;
	private Tween _tutorTypeTween;
	private Tween _tutorDotsTween;
	private Tween _tutorPulseTween;
	private ulong _tutorHideAtMs = 0;
	private string _tutorEpisodeId = "";

	private static readonly Color TutorInk = new(0.50f, 0.12f, 0.34f);
	private static readonly Color TutorInkSoft = new(0.66f, 0.40f, 0.56f);
	private static readonly Color TutorPink = new(0.97f, 0.46f, 0.66f);
	private static readonly Color TutorGold = new(0.90f, 0.62f, 0.26f);

	[Export] public float TutorPanelAutoHideSeconds = 14f;

	private void BuildTutorPanelUi()
	{
		_tutorPanel = new Panel
		{
			Name = "TutorPanel",
			Visible = false,
			CustomMinimumSize = TutorPanelMinSize,
			Size = TutorPanelMinSize,
			ZIndex = 97,
			MouseFilter = Control.MouseFilterEnum.Ignore, // trang trí: không chặn chuột
		};
		_tutorPanel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.965f, 0.982f, 0.97f),
			BorderColor = new Color(0.96f, 0.72f, 0.82f, 1f),
			BorderWidthLeft = 2, BorderWidthTop = 2, BorderWidthRight = 2, BorderWidthBottom = 2,
			CornerRadiusTopLeft = 22, CornerRadiusTopRight = 22,
			CornerRadiusBottomRight = 22, CornerRadiusBottomLeft = 22,
			ShadowColor = new Color(0.85f, 0.45f, 0.62f, 0.22f),
			ShadowSize = 8,
		});
		GetNode<Control>("CanvasLayer/Control").AddChild(_tutorPanel);

		var root = new VBoxContainer();
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.OffsetLeft = 16f; root.OffsetTop = 12f; root.OffsetRight = -16f; root.OffsetBottom = -12f;
		root.AddThemeConstantOverride("separation", 6);
		root.MouseFilter = Control.MouseFilterEnum.Ignore;
		_tutorPanel.AddChild(root);
		_tutorRoot = root;

		// Header: tiêu đề + trạng thái động
		var header = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		header.AddThemeConstantOverride("separation", 8);
		header.MouseFilter = Control.MouseFilterEnum.Ignore;
		root.AddChild(header);

		_tutorTitleLabel = MakeTutorLabel("✦ Eris hỏi trợ lý Gemini", 15, TutorInk);
		_tutorTitleLabel.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		header.AddChild(_tutorTitleLabel);

		_tutorStatusLabel = MakeTutorLabel("", 12, TutorGold);
		_tutorStatusLabel.HorizontalAlignment = HorizontalAlignment.Right;
		header.AddChild(_tutorStatusLabel);

		// Nút Ẩn — phần DUY NHẤT bấm được. Mọi chỗ khác click xuyên qua, user không
		// thể chạm vào phần Eris đang hỏi Gemini (tránh bấm bậy làm AI lỗi).
		_tutorHideButton = new Button
		{
			Text = "✕",
			CustomMinimumSize = new Vector2(26f, 24f),
			MouseFilter = Control.MouseFilterEnum.Stop,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			TooltipText = "Ẩn",
		};
		var hideStyle = new StyleBoxFlat
		{
			BgColor = new Color(0.97f, 0.86f, 0.91f, 0.95f),
			CornerRadiusTopLeft = 10, CornerRadiusTopRight = 10,
			CornerRadiusBottomRight = 10, CornerRadiusBottomLeft = 10,
			ContentMarginLeft = 6, ContentMarginRight = 6, ContentMarginTop = 2, ContentMarginBottom = 2,
		};
		var hideHover = (StyleBoxFlat)hideStyle.Duplicate();
		hideHover.BgColor = TutorPink;
		_tutorHideButton.AddThemeStyleboxOverride("normal", hideStyle);
		_tutorHideButton.AddThemeStyleboxOverride("hover", hideHover);
		_tutorHideButton.AddThemeStyleboxOverride("pressed", hideStyle);
		_tutorHideButton.AddThemeStyleboxOverride("focus", hideStyle);
		_tutorHideButton.AddThemeColorOverride("font_color", TutorInk);
		_tutorHideButton.AddThemeColorOverride("font_hover_color", Colors.White);
		_tutorHideButton.AddThemeFontSizeOverride("font_size", 13);
		_tutorHideButton.Pressed += HideTutorPanel;
		header.AddChild(_tutorHideButton);

		root.AddChild(new ColorRect
		{
			Color = new Color(0.96f, 0.80f, 0.88f, 0.5f),
			CustomMinimumSize = new Vector2(0f, 1f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		});

		_tutorQuestionLabel = MakeTutorRich(TutorInk);
		root.AddChild(_tutorQuestionLabel);

		_tutorAnswerLabel = MakeTutorRich(new Color(0.30f, 0.40f, 0.34f));
		_tutorAnswerLabel.Visible = false;
		root.AddChild(_tutorAnswerLabel);
	}

	private Label MakeTutorLabel(string text, int size, Color color)
	{
		var lbl = new Label { Text = text };
		lbl.AddThemeFontSizeOverride("font_size", size);
		lbl.AddThemeColorOverride("font_color", color);
		lbl.MouseFilter = Control.MouseFilterEnum.Ignore;
		return lbl;
	}

	private RichTextLabel MakeTutorRich(Color color)
	{
		var rt = new RichTextLabel
		{
			FitContent = true,
			ScrollActive = false,
			AutowrapMode = TextServer.AutowrapMode.WordSmart,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		rt.AddThemeFontSizeOverride("normal_font_size", 13);
		rt.AddThemeColorOverride("default_color", color);
		return rt;
	}

	// Trả true nếu raw là một tutor_event (đã xử lý xong, caller nên return).
	private bool TryHandleTutorEvent(string raw)
	{
		if (string.IsNullOrEmpty(raw) || raw.IndexOf("tutor_event", StringComparison.Ordinal) < 0)
			return false;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return false;
			if (!root.TryGetProperty("parse_mode", out var pm) || pm.GetString() != "tutor_event")
				return false;
			if (!root.TryGetProperty("tutor", out var t) || t.ValueKind != JsonValueKind.Object)
				return true;

			string stage = TutorStr(t, "stage");
			string question = TutorStr(t, "question");
			if (string.IsNullOrEmpty(question)) question = TutorStr(t, "question_preview");
			string answer = TutorStr(t, "answer");
			int claims = TutorInt(t, "claims");
			string failReason = TutorStr(t, "fail_reason");
			DriveTutorPanel(stage, question, answer, claims, failReason);
			return true;
		}
		catch (Exception)
		{
			return false;
		}
	}

	private void DriveTutorPanel(string stage, string question, string answer, int claims, string failReason)
	{
		if (_tutorPanel == null)
			return;

		if (!_tutorPanel.Visible)
			ShowTutorPanel();
		_tutorHideAtMs = 0; // còn diễn tiến thì không tự ẩn
		StartTutorPulse();  // "thở" nhẹ để Ngài biết Eris đang đi hỏi Gemini

		switch (stage)
		{
			case "forming":
				_tutorAnswerLabel.Visible = false;
				_tutorAnswerLabel.Text = "";
				SetTutorQuestion(question);
				StartTutorDots("đang nghĩ câu hỏi");
				break;
			case "opening":
				StartTutorDots("đang mở Gemini");
				break;
			case "asking":
				StopTutorDots("đang gõ…");
				TypeTutorText(_tutorQuestionLabel, question);
				break;
			case "reading":
				StartTutorDots("đang đọc trả lời");
				break;
			case "digesting":
				StartTutorDots("đang ghi nhớ");
				break;
			case "done":
				StopTutorPulse();
				StopTutorDots(claims > 0 ? $"đã học ✓ ({claims})" : "xong ✓");
				if (!string.IsNullOrWhiteSpace(answer))
				{
					_tutorAnswerLabel.Visible = true;
					TypeTutorText(_tutorAnswerLabel, answer);
				}
				ScheduleTutorHide();
				break;
			case "failed":
				StopTutorPulse();
				StopTutorDots(TutorFailText(failReason));
				ScheduleTutorHide();
				break;
			default:
				break;
		}
	}

	private static string TutorFailText(string reason)
	{
		switch (reason)
		{
			case "captcha_or_expired": return "cần đăng nhập lại…";
			case "timeout": return "Gemini lâu quá, thôi vậy";
			case "empty_answer": return "không rõ câu trả lời";
			case "formulation_failed": return "chưa nghĩ ra câu hỏi";
			case "gate_rejected_known": return "cái này biết rồi";
			case "gate_rejected_trivial": return "thôi, chuyện vặt";
			case "gate_rejected": return "thôi, cái này biết rồi";
			case "selector_miss": return "không mở được ô hỏi";
			case "network_error": return "mạng trục trặc";
			default: return "hỏi hụt rồi";
		}
	}

	private void SetTutorQuestion(string question)
	{
		if (_tutorQuestionLabel == null)
			return;
		KillTutorTypeTween();
		_tutorQuestionLabel.Text = string.IsNullOrWhiteSpace(question) ? "" : question;
		_tutorQuestionLabel.VisibleCharacters = -1;
		CallDeferred(nameof(FitTutorPanelHeight));
	}

	private void TypeTutorText(RichTextLabel label, string text)
	{
		if (label == null)
			return;
		KillTutorTypeTween();
		text ??= "";
		// Đặt FULL text ngay để panel tự dãn đúng chiều cao một lần (ổn định, không
		// giật), rồi chỉ animate số ký tự hiện ra bằng VisibleCharacters.
		label.Text = text;
		label.VisibleCharacters = 0;
		CallDeferred(nameof(FitTutorPanelHeight));
		if (text.Length == 0)
		{
			label.VisibleCharacters = -1;
			return;
		}
		float dur = Mathf.Max(0.2f, text.Length * 0.035f);
		_tutorTypeTween = CreateTween();
		_tutorTypeTween.TweenProperty(label, "visible_characters", text.Length, dur).From(0);
		_tutorTypeTween.TweenCallback(Callable.From(() =>
		{
			if (label != null) label.VisibleCharacters = -1;
		}));
	}

	// Tự dãn chiều cao panel theo nội dung (câu hỏi/trả lời dài ngắn khác nhau).
	// Rộng cố định -> RichTextLabel wrap -> GetCombinedMinimumSize cho chiều cao thật.
	private void FitTutorPanelHeight()
	{
		if (_tutorPanel == null || _tutorRoot == null || !_tutorPanel.Visible)
			return;
		float content = _tutorRoot.GetCombinedMinimumSize().Y;
		float wanted = Mathf.Max(TutorPanelMinSize.Y, content + 24f); // 12 trên + 12 dưới
		float screenY = GetViewportRect().Size.Y;
		float maxH = Mathf.Max(TutorPanelMinSize.Y, screenY - _tutorPanel.Position.Y - 16f);
		float h = Mathf.Min(wanted, maxH);
		_tutorPanel.Size = new Vector2(TutorPanelMinSize.X, h);
	}

	private void KillTutorTypeTween()
	{
		if (_tutorTypeTween != null && _tutorTypeTween.IsValid())
			_tutorTypeTween.Kill();
		_tutorTypeTween = null;
	}

	private void StartTutorDots(string baseText)
	{
		if (_tutorStatusLabel == null)
			return;
		if (_tutorDotsTween != null && _tutorDotsTween.IsValid())
			_tutorDotsTween.Kill();
		_tutorDotsTween = CreateTween().SetLoops();
		_tutorDotsTween.TweenMethod(
			Callable.From<int>(n => { if (_tutorStatusLabel != null) _tutorStatusLabel.Text = baseText + new string('.', n % 4); }),
			0, 3, 1.2f);
	}

	private void StopTutorDots(string finalText)
	{
		if (_tutorDotsTween != null && _tutorDotsTween.IsValid())
			_tutorDotsTween.Kill();
		_tutorDotsTween = null;
		if (_tutorStatusLabel != null)
			_tutorStatusLabel.Text = finalText ?? "";
	}

	// "Thở" nhẹ toàn panel khi Eris đang đi hỏi Gemini — tín hiệu để Ngài biết.
	private void StartTutorPulse()
	{
		if (_tutorPanel == null)
			return;
		if (_tutorPulseTween != null && _tutorPulseTween.IsValid())
			return; // đang thở rồi, đừng chồng tween
		_tutorPulseTween = CreateTween().SetLoops();
		_tutorPulseTween.TweenProperty(_tutorPanel, "modulate:a", 0.70f, 0.7f)
			.SetTrans(Tween.TransitionType.Sine).SetEase(Tween.EaseType.InOut);
		_tutorPulseTween.TweenProperty(_tutorPanel, "modulate:a", 1.0f, 0.7f)
			.SetTrans(Tween.TransitionType.Sine).SetEase(Tween.EaseType.InOut);
	}

	private void StopTutorPulse()
	{
		if (_tutorPulseTween != null && _tutorPulseTween.IsValid())
			_tutorPulseTween.Kill();
		_tutorPulseTween = null;
		if (_tutorPanel != null)
			_tutorPanel.Modulate = new Color(1f, 1f, 1f, 1f);
	}

	private void HideTutorPanel()
	{
		if (_tutorPanel == null)
			return;
		_tutorPanel.Visible = false;
		_tutorHideAtMs = 0;
		StopTutorDots("");
		StopTutorPulse();
		KillTutorTypeTween();
	}

	private void ShowTutorPanel()
	{
		if (_tutorPanel == null)
			return;
		_tutorPanel.Visible = true;
		_tutorPanel.ClipContents = true;
		_tutorPanel.Size = TutorPanelMinSize;
		Vector2 screen = GetViewportRect().Size;
		_tutorPanel.Position = new Vector2(
			Mathf.Max(12f, screen.X - TutorPanelMinSize.X - 30f),
			48f);
		CallDeferred(nameof(FitTutorPanelHeight));
	}

	private void ScheduleTutorHide()
	{
		if (TutorPanelAutoHideSeconds <= 0f)
		{
			_tutorHideAtMs = 0;
			return;
		}
		_tutorHideAtMs = Time.GetTicksMsec() + (ulong)(TutorPanelAutoHideSeconds * 1000f);
	}

	private void UpdateTutorPanelAutoHide()
	{
		if (_tutorPanel == null || !_tutorPanel.Visible || _tutorHideAtMs == 0)
			return;
		if (Time.GetTicksMsec() < _tutorHideAtMs)
			return;
		_tutorPanel.Visible = false;
		_tutorHideAtMs = 0;
		StopTutorDots("");
		StopTutorPulse();
		KillTutorTypeTween();
	}

	private static string TutorStr(JsonElement obj, string key)
	{
		if (obj.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String)
			return v.GetString() ?? "";
		return "";
	}

	private static int TutorInt(JsonElement obj, string key)
	{
		if (obj.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out int n))
			return n;
		return 0;
	}
}
