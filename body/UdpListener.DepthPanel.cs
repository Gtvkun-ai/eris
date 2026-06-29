using Godot;
using System;
using System.Collections.Generic;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	private sealed class DepthInteriorityRowView
	{
		public Control Root { get; set; }
		public Panel IconFallbackBg { get; set; }
		public TextureRect IconTexture { get; set; }
		public Label IconFallbackLabel { get; set; }
		public Label TextLabel { get; set; }
		public Label MetaLabel { get; set; }
		public Label TimeLabel { get; set; }
	}

	private sealed class DepthInteriorityItem
	{
		public string Kind { get; set; } = "current";
		public string Title { get; set; } = "";
		public string Text { get; set; } = "";
		public string Meta { get; set; } = "";
		public string Time { get; set; } = "";
	}

	private sealed class DepthPriorityRowView
	{
		public Control Root { get; set; }
		public Label IconLabel { get; set; }
		public Label TitleLabel { get; set; }
		public List<Panel> Segments { get; set; } = new();
		public Label PercentLabel { get; set; }
	}

	private sealed class DepthPriorityItem
	{
		public string Key { get; set; } = "casual";
		public string Label { get; set; } = "Small Talk / Casual";
		public float Score { get; set; } = 0f;
	}

	private sealed class DepthSignalTimelineRowView
	{
		public Control Root { get; set; }
		public Panel Dot { get; set; }
		public Label TimeLabel { get; set; }
		public Label TextLabel { get; set; }
	}

	private sealed class DepthSignalTimelineItem
	{
		public string Time { get; set; } = "";
		public string Kind { get; set; } = "signal";
		public string Text { get; set; } = "";
	}

	private sealed class DepthAutoSwitchChipView
	{
		public Panel Root { get; set; }
		public Label Label { get; set; }
		public string Key { get; set; } = "";
		public string Accent { get; set; } = "pink";
	}

	private sealed class DepthContextChipView
	{
		public Control Root { get; set; }
		public Panel IconBg { get; set; }
		public Label IconLabel { get; set; }
		public Label TitleLabel { get; set; }
		public Label MetaLabel { get; set; }
		public string Key { get; set; } = "";
	}

	private sealed partial class DepthEmotionSparklineView : Control
	{
		private readonly List<float> _values = new();

		public void SetValues(IReadOnlyList<float> values)
		{
			_values.Clear();
			if (values != null)
			{
				foreach (float value in values)
					_values.Add(Mathf.Clamp(value, 0f, 1f));
			}

			QueueRedraw();
		}

		public override void _Draw()
		{
			Vector2 size = Size;
			if (size.X <= 2f || size.Y <= 2f)
				return;

			var gridColor = new Color(0.98f, 0.58f, 0.74f, 0.13f);
			var midColor = new Color(0.98f, 0.44f, 0.67f, 0.20f);
			var glowColor = new Color(1f, 0.40f, 0.66f, 0.22f);
			var lineColor = new Color(0.96f, 0.22f, 0.55f, 0.92f);
			var pointColor = new Color(1f, 0.50f, 0.70f, 0.95f);

			// Grid mảnh để giữ cảm giác "đồ thị", nhưng alpha thấp để không đè nền PNG.
			for (int i = 0; i <= 10; i++)
			{
				float x = size.X * i / 10f;
				DrawLine(new Vector2(x, 0f), new Vector2(x, size.Y), gridColor, 1f, true);
			}
			for (int i = 0; i <= 4; i++)
			{
				float y = size.Y * i / 4f;
				DrawLine(new Vector2(0f, y), new Vector2(size.X, y), i == 2 ? midColor : gridColor, 1f, true);
			}

			var points = BuildSmoothPoints(size);
			if (points.Count < 2)
				return;

			for (int i = 1; i < points.Count; i++)
			{
				DrawLine(points[i - 1], points[i], glowColor, 5f, true);
				DrawLine(points[i - 1], points[i], lineColor, 1.6f, true);
			}

			Vector2 last = points[^1];
			DrawCircle(last, 6.0f, new Color(1f, 0.48f, 0.70f, 0.18f));
			DrawCircle(last, 3.6f, pointColor);
			DrawCircle(new Vector2(Mathf.Clamp(last.X + 10f, 0f, size.X), last.Y), 5.0f, new Color(1f, 0.46f, 0.68f, 0.78f));
		}

		private List<Vector2> BuildSmoothPoints(Vector2 size)
		{
			var source = _values.Count >= 2 ? _values : DefaultPreviewValues();
			var anchors = new List<Vector2>();
			float step = source.Count <= 1 ? size.X : size.X / (source.Count - 1);
			for (int i = 0; i < source.Count; i++)
			{
				float x = step * i;
				float y = Mathf.Lerp(size.Y * 0.84f, size.Y * 0.16f, Mathf.Clamp(source[i], 0f, 1f));
				anchors.Add(new Vector2(x, y));
			}

			var smooth = new List<Vector2>();
			for (int i = 0; i < anchors.Count - 1; i++)
			{
				Vector2 p0 = anchors[Math.Max(i - 1, 0)];
				Vector2 p1 = anchors[i];
				Vector2 p2 = anchors[i + 1];
				Vector2 p3 = anchors[Math.Min(i + 2, anchors.Count - 1)];

				for (int sample = 0; sample < 6; sample++)
				{
					float t = sample / 6f;
					smooth.Add(CatmullRom(p0, p1, p2, p3, t));
				}
			}
			smooth.Add(anchors[^1]);
			return smooth;
		}

		private static Vector2 CatmullRom(Vector2 p0, Vector2 p1, Vector2 p2, Vector2 p3, float t)
		{
			float t2 = t * t;
			float t3 = t2 * t;
			return (
				(p1 * 2f)
				+ (-p0 + p2) * t
				+ (p0 * 2f - p1 * 5f + p2 * 4f - p3) * t2
				+ (-p0 + p1 * 3f - p2 * 3f + p3) * t3) * 0.5f;
		}

		private static List<float> DefaultPreviewValues() => new()
		{
			0.54f, 0.57f, 0.51f, 0.60f, 0.52f, 0.56f, 0.49f,
			0.58f, 0.61f, 0.53f, 0.59f, 0.55f, 0.62f, 0.57f,
			0.60f, 0.52f, 0.56f, 0.50f, 0.58f,
		};
	}

	private static readonly Vector2 DepthPanelMinSize = new(1497f, 988f);
	private static readonly Vector2 DepthPanelArtworkSize = new(1497f, 988f);
	private const float DepthPanelViewportMargin = 32f;
	private const float DepthPanelMaxScale = 0.70f;
	private const float DepthPanelInnerContentScale = 0.93f;
	private const string DepthFramePath = "res://asset/Resource/ChieuSauKhung.png";
	private const string DepthAffectFramePath = "res://asset/Resource/ChieuSau_CamXuc.png";
	private const string DepthTomFramePath = "res://asset/Resource/ChieuSau_ThauHieuNgai.png";
	private const string DepthSelfContinuityFramePath = "res://asset/Resource/ChieuSau_LienTucBanThan.png";
	private const string DepthCollabFramePath = "res://asset/Resource/ChieuSau_CongTac.png";
	private const string DepthInteriorityFramePath = "res://asset/Resource/ChieuSau_DongNoiTam.png";
	private const string DepthPrioritiesFramePath = "res://asset/Resource/ChieuSau_UuTienHienTai.png";
	private const string DepthSignalLogFramePath = "res://asset/Resource/ChieuSau_NhatKyTinHieu.png";
	private const string DepthContextFramePath = "res://asset/Resource/ChieuSau_BauKhongKhi.png";
	private const string DepthEmotionJournalFramePath = "res://asset/Resource/ChieuSau_NhatKyCamXuc.png";

	private Panel _depthPanel;
	private Control _depthPanelContentRoot;
	private Button _contextDepthButton;
	private Label _depthAffectHeadlineLabel;
	private Label _depthAffectSubtextLabel;
	private ProgressBar _depthAffectStabilityBar;
	private Label _depthAffectStabilityPctLabel;
	private Label _depthTomStatusLabel;
	private Label _depthTomScoreLabel;
	private Label _depthTomSummaryLabel;
	private Label _depthTomMetaLabel;
	private Label _depthTomBeliefLabel;
	private ProgressBar _depthTomThicknessBar;
	private ProgressBar _depthTomConfidenceBar;
	private ProgressBar _depthTomAttachmentBar;
	private ProgressBar _depthSelfWantBar;
	private Label _depthSelfWantValueLabel;
	private ProgressBar _depthSelfSuppressBar;
	private Label _depthSelfSuppressValueLabel;
	private ProgressBar _depthSelfAllowedBar;
	private Label _depthSelfAllowedValueLabel;
	private Label _depthSelfStanceValueLabel;
	private readonly List<DepthInteriorityRowView> _depthInteriorityRows = new();
	private readonly Dictionary<string, Texture2D> _depthIconCache = new();
	private Label _depthInteriorityFooterLabel;
	private Label _depthInteriorityPageDotLabel;
	private readonly List<DepthPriorityRowView> _depthPriorityRows = new();
	private Label _depthPriorityFocusModeLabel;
	private Label _depthPriorityFooterGlyphLabel;
	private readonly List<DepthSignalTimelineRowView> _depthSignalTimelineRows = new();
	private Label _depthSignalTimelineStatusLabel;
	private readonly List<DepthAutoSwitchChipView> _depthAutoSwitchChips = new();
	private Label _depthAutoSwitchModeLabel;
	private Label _depthAutoSwitchPolicyLabel;
	private Label _depthAutoSwitchGlyphLabel;
	private readonly Dictionary<string, DepthContextChipView> _depthContextChips = new();
	private DepthEmotionSparklineView _depthEmotionSparkline;
	private Label _depthEmotionLeftLabel;
	private Label _depthEmotionRightLabel;

	private string _latestDepthJson = "";
	private Font _depthFontRegular;
	private Font _depthFontBold;

	private static readonly Rect2 SlotAffect = RectPx(38f, 154f, 423f, 204f);
	private static readonly Rect2 SlotTom = RectPx(31f, 379f, 434f, 174f);
	private static readonly Rect2 SlotSelfContinuity = RectPx(37f, 566f, 419f, 187f);
	private static readonly Rect2 SlotCollab = RectPx(38f, 760f, 377f, 181f);
	private static readonly Rect2 SlotInteriority = RectPx(489f, 154f, 521f, 591f);
	private static readonly Rect2 SlotPriorities = RectPx(1022f, 154f, 442f, 303f);
	private static readonly Rect2 SlotSignalLog = RectPx(1022f, 479f, 442f, 235f);
	private static readonly Rect2 SlotContext = RectPx(444f, 760f, 564f, 182f);
	private static readonly Rect2 SlotEmotionJournal = RectPx(1022f, 719f, 442f, 249f);
	private static readonly Rect2 SlotClose = RectPx(1334f, 40f, 132f, 53f);

	private static Rect2 RectPx(float x, float y, float width, float height) =>
		new(
			x / DepthPanelArtworkSize.X,
			y / DepthPanelArtworkSize.Y,
			width / DepthPanelArtworkSize.X,
			height / DepthPanelArtworkSize.Y);

	private static Rect2 RectLTRB(float l, float t, float r, float b) =>
		new(l, t, r - l, b - t);

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

		Vector2 viewportSize = GetViewportRect().Size;
		float widthScale = Mathf.Max(0.10f, (viewportSize.X - DepthPanelViewportMargin) / DepthPanelArtworkSize.X);
		float heightScale = Mathf.Max(0.10f, (viewportSize.Y - DepthPanelViewportMargin) / DepthPanelArtworkSize.Y);
		float scale = Mathf.Clamp(Mathf.Min(widthScale, heightScale), 0.45f, DepthPanelMaxScale);

		_depthPanel.Size = DepthPanelArtworkSize * scale;
		_depthPanel.Position = new Vector2(
			Mathf.Max(0f, (viewportSize.X - _depthPanel.Size.X) * 0.5f),
			Mathf.Max(0f, (viewportSize.Y - _depthPanel.Size.Y) * 0.5f));
		UpdateDepthContentRootTransform();

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
				BorderWidthLeft = 3,
				BorderWidthTop = 3,
				BorderWidthRight = 3,
				BorderWidthBottom = 3,
				CornerRadiusTopLeft = 26,
				CornerRadiusTopRight = 26,
				CornerRadiusBottomRight = 26,
				CornerRadiusBottomLeft = 26,
			});
		}

		_depthPanelContentRoot = new Control
		{
			Name = "DepthPanelContentRoot",
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		_depthPanelContentRoot.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_depthPanel.AddChild(_depthPanelContentRoot);
		UpdateDepthContentRootTransform();

		BuildDepthAffectFrame(_depthPanelContentRoot);
		BuildDepthTomFrame(_depthPanelContentRoot);
		BuildDepthSelfContinuityFrame(_depthPanelContentRoot);
		BuildDepthCollabFrame(_depthPanelContentRoot);
		BuildDepthInteriorityFrame(_depthPanelContentRoot);
		BuildDepthPrioritiesFrame(_depthPanelContentRoot);
		BuildDepthSignalLogFrame(_depthPanelContentRoot);
		BuildDepthContextFrame(_depthPanelContentRoot);
		BuildDepthEmotionJournalFrame(_depthPanelContentRoot);

		var windowControls = CreateWindowControlCapsule(
			() => _depthPanel.Visible = false,
			() => _depthPanel.Visible = false);
		PlaceBySlot(windowControls, SlotClose);
		_depthPanel.AddChild(windowControls);

		RefreshDepthPanel();
	}

	private void AddDepthFrameImage(Control parent, string resourcePath, Rect2 slot)
	{
		if (parent == null || !ResourceLoader.Exists(resourcePath))
			return;

		var tex = GD.Load<Texture2D>(resourcePath);
		if (tex == null)
			return;

		var frame = new TextureRect
		{
			Texture = tex,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(frame, slot);
		parent.AddChild(frame);
	}

	private void BuildDepthAffectFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthAffectFrame", SlotAffect, DepthAffectFramePath);
		if (root == null)
			return;

		var headline = CreateDepthTextLabel("Bình tĩnh", 16, new Color(0.86f, 0.20f, 0.44f), bold: true);
		headline.AutowrapMode = TextServer.AutowrapMode.Off;
		headline.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		headline.HorizontalAlignment = HorizontalAlignment.Left;
		headline.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(headline, RectLTRB(0.48f, 0.27f, 0.90f, 0.39f));
		root.AddChild(headline);
		_depthAffectHeadlineLabel = headline;

		var subtext = CreateDepthTextLabel("Thoải mái, sẵn sàng trò chuyện.", 10, new Color(0.58f, 0.20f, 0.34f));
		subtext.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		subtext.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(subtext, RectLTRB(0.48f, 0.42f, 0.92f, 0.64f));
		root.AddChild(subtext);
		_depthAffectSubtextLabel = subtext;

		var stabilityLabel = CreateDepthTextLabel("stability", 9, new Color(0.62f, 0.42f, 0.56f));
		stabilityLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		stabilityLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		stabilityLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(stabilityLabel, RectLTRB(0.48f, 0.73f, 0.64f, 0.81f));
		root.AddChild(stabilityLabel);

		var stabilityBar = CreateDepthProgressBar(new Color(0.95f, 0.42f, 0.67f, 0.90f));
		stabilityBar.AddThemeStyleboxOverride("background", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.84f, 0.90f, 0.18f),
			CornerRadiusTopLeft = 4,
			CornerRadiusTopRight = 4,
			CornerRadiusBottomLeft = 4,
			CornerRadiusBottomRight = 4,
		});
		PlaceBySlot(stabilityBar, RectLTRB(0.66f, 0.75f, 0.84f, 0.79f));
		root.AddChild(stabilityBar);
		_depthAffectStabilityBar = stabilityBar;

		var stabilityPct = CreateDepthTextLabel("72%", 10, new Color(0.78f, 0.38f, 0.55f), bold: true);
		stabilityPct.HorizontalAlignment = HorizontalAlignment.Right;
		stabilityPct.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(stabilityPct, RectLTRB(0.85f, 0.72f, 0.93f, 0.81f));
		root.AddChild(stabilityPct);
		_depthAffectStabilityPctLabel = stabilityPct;
	}

	private void BuildDepthTomFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthTomFrame", SlotTom, DepthTomFramePath);
		if (root == null)
			return;

		_depthTomStatusLabel = CreateDepthTextLabel("đang chờ dữ liệu", 8, new Color(0.58f, 0.34f, 0.47f));
		_depthTomStatusLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthTomStatusLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_depthTomStatusLabel.HorizontalAlignment = HorizontalAlignment.Right;
		_depthTomStatusLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthTomStatusLabel, RectLTRB(0.67f, 0.09f, 0.93f, 0.18f));
		root.AddChild(_depthTomStatusLabel);

		_depthTomScoreLabel = CreateDepthTextLabel("0.00", 17, new Color(0.88f, 0.18f, 0.48f), bold: true);
		_depthTomScoreLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthTomScoreLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_depthTomScoreLabel.HorizontalAlignment = HorizontalAlignment.Center;
		_depthTomScoreLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthTomScoreLabel, RectLTRB(0.34f, 0.27f, 0.48f, 0.40f));
		root.AddChild(_depthTomScoreLabel);

		_depthTomSummaryLabel = CreateDepthTextLabel("chưa đọc được gì đủ chắc.", 10, new Color(0.52f, 0.25f, 0.40f));
		_depthTomSummaryLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_depthTomSummaryLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthTomSummaryLabel, RectLTRB(0.34f, 0.42f, 0.92f, 0.57f));
		root.AddChild(_depthTomSummaryLabel);

		_depthTomMetaLabel = null;

		_depthTomThicknessBar = CreateDepthProgressBar(new Color(0.96f, 0.38f, 0.62f, 0.92f));
		PlaceBySlot(_depthTomThicknessBar, RectLTRB(0.34f, 0.66f, 0.52f, 0.71f));
		root.AddChild(_depthTomThicknessBar);

		_depthTomConfidenceBar = CreateDepthProgressBar(new Color(0.99f, 0.62f, 0.24f, 0.94f));
		PlaceBySlot(_depthTomConfidenceBar, RectLTRB(0.55f, 0.66f, 0.73f, 0.71f));
		root.AddChild(_depthTomConfidenceBar);

		_depthTomAttachmentBar = CreateDepthProgressBar(new Color(0.68f, 0.48f, 0.92f, 0.92f));
		PlaceBySlot(_depthTomAttachmentBar, RectLTRB(0.76f, 0.66f, 0.92f, 0.71f));
		root.AddChild(_depthTomAttachmentBar);

		_depthTomBeliefLabel = CreateDepthTextLabel("belief: chưa có", 8, new Color(0.54f, 0.29f, 0.43f));
		_depthTomBeliefLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_depthTomBeliefLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthTomBeliefLabel, RectLTRB(0.34f, 0.75f, 0.92f, 0.85f));
		root.AddChild(_depthTomBeliefLabel);
	}

	private void BuildDepthSelfContinuityFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthSelfContinuityFrame", SlotSelfContinuity, DepthSelfContinuityFramePath);
		if (root == null)
			return;

		_depthSelfWantBar = CreateDepthProgressBar(new Color(0.97f, 0.46f, 0.66f, 0.96f));
		PlaceBySlot(_depthSelfWantBar, RectLTRB(0.34f, 0.31f, 0.64f, 0.38f));
		root.AddChild(_depthSelfWantBar);

		_depthSelfWantValueLabel = CreateDepthTextLabel("0.00", 11, new Color(0.77f, 0.34f, 0.54f), bold: true);
		_depthSelfWantValueLabel.HorizontalAlignment = HorizontalAlignment.Right;
		_depthSelfWantValueLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthSelfWantValueLabel, RectLTRB(0.74f, 0.27f, 0.90f, 0.41f));
		root.AddChild(_depthSelfWantValueLabel);

		_depthSelfSuppressBar = CreateDepthProgressBar(new Color(0.75f, 0.58f, 0.95f, 0.96f));
		PlaceBySlot(_depthSelfSuppressBar, RectLTRB(0.34f, 0.48f, 0.58f, 0.55f));
		root.AddChild(_depthSelfSuppressBar);

		_depthSelfSuppressValueLabel = CreateDepthTextLabel("0.00", 11, new Color(0.72f, 0.39f, 0.70f), bold: true);
		_depthSelfSuppressValueLabel.HorizontalAlignment = HorizontalAlignment.Right;
		_depthSelfSuppressValueLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthSelfSuppressValueLabel, RectLTRB(0.74f, 0.44f, 0.90f, 0.58f));
		root.AddChild(_depthSelfSuppressValueLabel);

		_depthSelfAllowedBar = CreateDepthProgressBar(new Color(0.98f, 0.67f, 0.46f, 0.98f));
		PlaceBySlot(_depthSelfAllowedBar, RectLTRB(0.34f, 0.65f, 0.69f, 0.72f));
		root.AddChild(_depthSelfAllowedBar);

		_depthSelfAllowedValueLabel = CreateDepthTextLabel("0.00", 11, new Color(0.84f, 0.48f, 0.31f), bold: true);
		_depthSelfAllowedValueLabel.HorizontalAlignment = HorizontalAlignment.Right;
		_depthSelfAllowedValueLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthSelfAllowedValueLabel, RectLTRB(0.74f, 0.61f, 0.90f, 0.75f));
		root.AddChild(_depthSelfAllowedValueLabel);

		var stanceLabel = CreateDepthTextLabel("stance:", 10, new Color(0.68f, 0.48f, 0.58f));
		stanceLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(stanceLabel, RectLTRB(0.06f, 0.85f, 0.22f, 0.97f));
		root.AddChild(stanceLabel);

		var stanceDivider = CreateDepthTextLabel("-----------", 10, new Color(0.90f, 0.70f, 0.80f, 0.95f));
		stanceDivider.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(stanceDivider, RectLTRB(0.19f, 0.85f, 0.41f, 0.97f));
		root.AddChild(stanceDivider);

		_depthSelfStanceValueLabel = CreateDepthTextLabel("cân bằng", 10, new Color(0.69f, 0.42f, 0.56f), bold: true);
		_depthSelfStanceValueLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthSelfStanceValueLabel, RectLTRB(0.43f, 0.85f, 0.72f, 0.97f));
		root.AddChild(_depthSelfStanceValueLabel);
	}

	private void BuildDepthCollabFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthCollabFrame", SlotCollab, DepthCollabFramePath);
		if (root == null)
			return;

		_depthAutoSwitchChips.Clear();
		AddDepthAutoSwitchChip(root, "n1", "N1", "pink", RectLTRB(0.045f, 0.315f, 0.245f, 0.535f));
		AddDepthAutoSwitchChip(root, "n2", "N2", "pink", RectLTRB(0.285f, 0.315f, 0.485f, 0.535f));
		AddDepthAutoSwitchChip(root, "interiority", "interiority", "pink", RectLTRB(0.530f, 0.315f, 0.775f, 0.535f));
		AddDepthAutoSwitchChip(root, "tom", "tom", "pink", RectLTRB(0.815f, 0.315f, 0.970f, 0.535f));
		AddDepthAutoSwitchChip(root, "embed", "embed", "mint", RectLTRB(0.045f, 0.610f, 0.305f, 0.830f));
		AddDepthAutoSwitchChip(root, "mind", "mind", "mint", RectLTRB(0.345f, 0.610f, 0.605f, 0.830f));

		var modeTitle = CreateDepthTextLabel("mode:", 8, new Color(0.66f, 0.36f, 0.50f), bold: true);
		modeTitle.VerticalAlignment = VerticalAlignment.Center;
		modeTitle.AutowrapMode = TextServer.AutowrapMode.Off;
		PlaceBySlot(modeTitle, RectLTRB(0.050f, 0.865f, 0.170f, 0.980f));
		root.AddChild(modeTitle);

		_depthAutoSwitchModeLabel = CreateDepthTextLabel("adaptive", 8, new Color(0.76f, 0.24f, 0.47f), bold: true);
		_depthAutoSwitchModeLabel.VerticalAlignment = VerticalAlignment.Center;
		_depthAutoSwitchModeLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthAutoSwitchModeLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthAutoSwitchModeLabel, RectLTRB(0.175f, 0.865f, 0.405f, 0.980f));
		root.AddChild(_depthAutoSwitchModeLabel);

		var dot = CreateDepthTextLabel("•", 8, new Color(0.93f, 0.35f, 0.58f, 0.82f), bold: true);
		dot.HorizontalAlignment = HorizontalAlignment.Center;
		dot.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(dot, RectLTRB(0.405f, 0.865f, 0.455f, 0.980f));
		root.AddChild(dot);

		var policyTitle = CreateDepthTextLabel("policy:", 8, new Color(0.66f, 0.36f, 0.50f), bold: true);
		policyTitle.VerticalAlignment = VerticalAlignment.Center;
		policyTitle.AutowrapMode = TextServer.AutowrapMode.Off;
		PlaceBySlot(policyTitle, RectLTRB(0.455f, 0.865f, 0.595f, 0.980f));
		root.AddChild(policyTitle);

		_depthAutoSwitchPolicyLabel = CreateDepthTextLabel("voice_guarded_plus", 8, new Color(0.76f, 0.24f, 0.47f), bold: true);
		_depthAutoSwitchPolicyLabel.VerticalAlignment = VerticalAlignment.Center;
		_depthAutoSwitchPolicyLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthAutoSwitchPolicyLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthAutoSwitchPolicyLabel, RectLTRB(0.600f, 0.865f, 0.890f, 0.980f));
		root.AddChild(_depthAutoSwitchPolicyLabel);

		_depthAutoSwitchGlyphLabel = CreateDepthTextLabel("✦  ♥", 9, new Color(0.96f, 0.46f, 0.66f, 0.72f), bold: true);
		_depthAutoSwitchGlyphLabel.HorizontalAlignment = HorizontalAlignment.Center;
		_depthAutoSwitchGlyphLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthAutoSwitchGlyphLabel, RectLTRB(0.890f, 0.865f, 0.980f, 0.980f));
		root.AddChild(_depthAutoSwitchGlyphLabel);
	}

	private void AddDepthAutoSwitchChip(Control root, string key, string labelText, string accent, Rect2 slot)
	{
		// Chip tự scale theo PNG card; không phụ thuộc pixel màn hình nên resize vẫn sạch.
		var chip = new Panel
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(chip, slot);
		root.AddChild(chip);

		var label = CreateDepthTextLabel(labelText, 9, new Color(0.82f, 0.26f, 0.50f), bold: true);
		label.HorizontalAlignment = HorizontalAlignment.Center;
		label.VerticalAlignment = VerticalAlignment.Center;
		label.AutowrapMode = TextServer.AutowrapMode.Off;
		label.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		label.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		chip.AddChild(label);

		var view = new DepthAutoSwitchChipView
		{
			Root = chip,
			Label = label,
			Key = key,
			Accent = accent,
		};
		_depthAutoSwitchChips.Add(view);
		ApplyDepthAutoSwitchChipStyle(view, active: true, accent);
	}

	private void BuildDepthInteriorityFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthInteriorityFrame", SlotInteriority, DepthInteriorityFramePath);
		if (root == null)
			return;

		_depthInteriorityRows.Clear();
		for (int i = 0; i < 4; i++)
		{
			var row = CreateDepthInteriorityRow(i);
			root.AddChild(row.Root);
			_depthInteriorityRows.Add(row);
		}
		// Chỉ đổi câu footer theo trạng thái dữ liệu, không biến nó thành log dài.
		_depthInteriorityFooterLabel = CreateDepthTextLabel("✦", 10, new Color(0.94f, 0.26f, 0.55f), bold: true);
		_depthInteriorityFooterLabel.HorizontalAlignment = HorizontalAlignment.Center;
		_depthInteriorityFooterLabel.VerticalAlignment = VerticalAlignment.Center;
		_depthInteriorityFooterLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthInteriorityFooterLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthInteriorityFooterLabel, RectLTRB(0.28f, 0.86f, 0.72f, 0.92f));
		root.AddChild(_depthInteriorityFooterLabel);

		_depthInteriorityPageDotLabel = CreateDepthTextLabel("•   ◦   ◦", 10, new Color(0.98f, 0.42f, 0.66f, 0.86f), bold: true);
		_depthInteriorityPageDotLabel.HorizontalAlignment = HorizontalAlignment.Center;
		_depthInteriorityPageDotLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthInteriorityPageDotLabel, RectLTRB(0.42f, 0.92f, 0.58f, 0.97f));
		root.AddChild(_depthInteriorityPageDotLabel);
	}

	private DepthInteriorityRowView CreateDepthInteriorityRow(int index)
	{
		// Slot dùng tỉ lệ nội bộ của card Interiority, không theo pixel màn hình.
		// Nhờ vậy khi DepthPanel scale theo viewport, row và icon vẫn bám khung PNG.
		float top = 0.145f + index * 0.165f;
		float bottom = top + 0.135f;

		var rowRoot = new Control
		{
			Name = $"DepthInteriorityRow{index + 1}",
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(rowRoot, RectLTRB(0.045f, top, 0.955f, bottom));

		var iconFallbackBg = new Panel
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		iconFallbackBg.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.96f, 0.34f, 0.62f, 0.92f),
			CornerRadiusTopLeft = 18,
			CornerRadiusTopRight = 18,
			CornerRadiusBottomLeft = 18,
			CornerRadiusBottomRight = 18,
		});
		PlaceBySlot(iconFallbackBg, RectLTRB(0.015f, 0.15f, 0.105f, 0.85f));
		rowRoot.AddChild(iconFallbackBg);

		var iconTexture = new TextureRect
		{
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(iconTexture, RectLTRB(0.010f, 0.08f, 0.112f, 0.92f));
		rowRoot.AddChild(iconTexture);

		var fallbackLabel = CreateDepthTextLabel("✦", 12, Colors.White, bold: true);
		fallbackLabel.HorizontalAlignment = HorizontalAlignment.Center;
		fallbackLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(fallbackLabel, RectLTRB(0.015f, 0.15f, 0.105f, 0.85f));
		rowRoot.AddChild(fallbackLabel);

		var textLabel = CreateDepthTextLabel("", 11, new Color(0.66f, 0.20f, 0.38f), bold: true);
		textLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		textLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(textLabel, RectLTRB(0.145f, 0.12f, 0.750f, 0.50f));
		rowRoot.AddChild(textLabel);

		var metaLabel = CreateDepthTextLabel("", 9, new Color(0.62f, 0.30f, 0.46f));
		metaLabel.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		metaLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(metaLabel, RectLTRB(0.145f, 0.55f, 0.740f, 0.88f));
		rowRoot.AddChild(metaLabel);

		var timeLabel = CreateDepthTextLabel("", 8, new Color(0.72f, 0.38f, 0.55f, 0.82f));
		timeLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		timeLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		timeLabel.HorizontalAlignment = HorizontalAlignment.Right;
		timeLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(timeLabel, RectLTRB(0.760f, 0.20f, 0.945f, 0.48f));
		rowRoot.AddChild(timeLabel);

		var divider = new Panel { MouseFilter = Control.MouseFilterEnum.Ignore };
		divider.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.94f, 0.62f, 0.74f, 0.22f),
		});
		PlaceBySlot(divider, RectLTRB(0.135f, 0.98f, 0.950f, 1.00f));
		rowRoot.AddChild(divider);

		return new DepthInteriorityRowView
		{
			Root = rowRoot,
			IconFallbackBg = iconFallbackBg,
			IconTexture = iconTexture,
			IconFallbackLabel = fallbackLabel,
			TextLabel = textLabel,
			MetaLabel = metaLabel,
			TimeLabel = timeLabel,
		};
	}

	private void BuildDepthPrioritiesFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthPrioritiesFrame", SlotPriorities, DepthPrioritiesFramePath);
		if (root == null)
			return;

		_depthPriorityRows.Clear();
		for (int i = 0; i < 5; i++)
		{
			var row = CreateDepthPriorityRow(i);
			root.AddChild(row.Root);
			_depthPriorityRows.Add(row);
		}

		var focusLabel = CreateDepthTextLabel("focus mode:", 9, new Color(0.68f, 0.38f, 0.52f));
		focusLabel.VerticalAlignment = VerticalAlignment.Center;
		focusLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		PlaceBySlot(focusLabel, RectLTRB(0.055f, 0.855f, 0.255f, 0.925f));
		root.AddChild(focusLabel);

		_depthPriorityFocusModeLabel = CreateDepthTextLabel("attentive", 9, new Color(0.78f, 0.24f, 0.48f), bold: true);
		_depthPriorityFocusModeLabel.VerticalAlignment = VerticalAlignment.Center;
		_depthPriorityFocusModeLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthPriorityFocusModeLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthPriorityFocusModeLabel, RectLTRB(0.255f, 0.855f, 0.540f, 0.925f));
		root.AddChild(_depthPriorityFocusModeLabel);

		_depthPriorityFooterGlyphLabel = CreateDepthTextLabel("✦  ♡  ✦", 12, new Color(0.96f, 0.42f, 0.66f, 0.70f), bold: true);
		_depthPriorityFooterGlyphLabel.HorizontalAlignment = HorizontalAlignment.Center;
		_depthPriorityFooterGlyphLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthPriorityFooterGlyphLabel, RectLTRB(0.48f, 0.850f, 0.72f, 0.935f));
		root.AddChild(_depthPriorityFooterGlyphLabel);
	}

	private DepthPriorityRowView CreateDepthPriorityRow(int index)
	{
		// Không dùng icon asset: glyph nằm trong Label nên project chưa có icon vẫn chạy.
		// Khi muốn thay bằng texture sau này, chỉ cần đổi hàm apply icon, không đổi contract.
		float top = 0.205f + index * 0.125f;
		float bottom = top + 0.085f;

		var rowRoot = new Control
		{
			Name = $"DepthPriorityRow{index + 1}",
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(rowRoot, RectLTRB(0.055f, top, 0.940f, bottom));

		var icon = CreateDepthTextLabel("✦", 12, new Color(0.92f, 0.34f, 0.56f), bold: true);
		icon.HorizontalAlignment = HorizontalAlignment.Center;
		icon.VerticalAlignment = VerticalAlignment.Center;
		icon.AutowrapMode = TextServer.AutowrapMode.Off;
		PlaceBySlot(icon, RectLTRB(0.000f, 0.05f, 0.075f, 0.95f));
		rowRoot.AddChild(icon);

		var title = CreateDepthTextLabel("", 9, new Color(0.63f, 0.21f, 0.38f), bold: true);
		title.VerticalAlignment = VerticalAlignment.Center;
		title.AutowrapMode = TextServer.AutowrapMode.Off;
		title.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(title, RectLTRB(0.090f, 0.00f, 0.515f, 1.00f));
		rowRoot.AddChild(title);

		var bar = new HBoxContainer
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
			Alignment = BoxContainer.AlignmentMode.Begin,
		};
		PlaceBySlot(bar, RectLTRB(0.525f, 0.30f, 0.825f, 0.70f));
		rowRoot.AddChild(bar);

		var segments = new List<Panel>();
		for (int i = 0; i < 16; i++)
		{
			var segment = new Panel
			{
				MouseFilter = Control.MouseFilterEnum.Ignore,
				CustomMinimumSize = new Vector2(4f, 12f),
			};
			segment.AddThemeStyleboxOverride("panel", new StyleBoxFlat
			{
				BgColor = new Color(1f, 0.82f, 0.90f, 0.20f),
				CornerRadiusTopLeft = 1,
				CornerRadiusTopRight = 1,
				CornerRadiusBottomLeft = 1,
				CornerRadiusBottomRight = 1,
			});
			bar.AddChild(segment);
			segments.Add(segment);
		}

		var percent = CreateDepthTextLabel("0%", 9, new Color(0.72f, 0.36f, 0.52f), bold: true);
		percent.HorizontalAlignment = HorizontalAlignment.Right;
		percent.VerticalAlignment = VerticalAlignment.Center;
		percent.AutowrapMode = TextServer.AutowrapMode.Off;
		PlaceBySlot(percent, RectLTRB(0.845f, 0.00f, 1.000f, 1.00f));
		rowRoot.AddChild(percent);

		return new DepthPriorityRowView
		{
			Root = rowRoot,
			IconLabel = icon,
			TitleLabel = title,
			Segments = segments,
			PercentLabel = percent,
		};
	}

	private void BuildDepthSignalLogFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthSignalLogFrame", SlotSignalLog, DepthSignalLogFramePath);
		if (root == null)
			return;

		_depthSignalTimelineRows.Clear();
		for (int i = 0; i < 6; i++)
		{
			var row = CreateDepthSignalTimelineRow(i);
			root.AddChild(row.Root);
			_depthSignalTimelineRows.Add(row);
		}

		_depthSignalTimelineStatusLabel = CreateDepthTextLabel("timeline chờ tín hiệu ✦", 8, new Color(0.78f, 0.34f, 0.52f, 0.82f));
		_depthSignalTimelineStatusLabel.HorizontalAlignment = HorizontalAlignment.Right;
		_depthSignalTimelineStatusLabel.VerticalAlignment = VerticalAlignment.Center;
		_depthSignalTimelineStatusLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthSignalTimelineStatusLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(_depthSignalTimelineStatusLabel, RectLTRB(0.60f, 0.085f, 0.925f, 0.155f));
		root.AddChild(_depthSignalTimelineStatusLabel);
	}

	private DepthSignalTimelineRowView CreateDepthSignalTimelineRow(int index)
	{
		// Timeline dùng slot tỉ lệ theo card signal-log. Nếu sau này đổi asset PNG,
		// chỉ cần chỉnh các số này, parser payload vẫn giữ nguyên.
		float top = 0.215f + index * 0.112f;
		float bottom = top + 0.072f;

		var rowRoot = new Control
		{
			Name = $"DepthSignalTimelineRow{index + 1}",
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(rowRoot, RectLTRB(0.060f, top, 0.925f, bottom));

		var dot = new Panel
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		dot.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.96f, 0.36f, 0.62f, 0.90f),
			CornerRadiusTopLeft = 4,
			CornerRadiusTopRight = 4,
			CornerRadiusBottomLeft = 4,
			CornerRadiusBottomRight = 4,
		});
		PlaceBySlot(dot, RectLTRB(0.000f, 0.36f, 0.020f, 0.64f));
		rowRoot.AddChild(dot);

		var connector = new Panel { MouseFilter = Control.MouseFilterEnum.Ignore };
		connector.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.96f, 0.48f, 0.68f, 0.24f),
		});
		PlaceBySlot(connector, RectLTRB(0.008f, 0.68f, 0.012f, 1.45f));
		rowRoot.AddChild(connector);

		var time = CreateDepthTextLabel("", 8, new Color(0.72f, 0.34f, 0.52f, 0.88f));
		time.AutowrapMode = TextServer.AutowrapMode.Off;
		time.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		time.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(time, RectLTRB(0.040f, 0.00f, 0.225f, 1.00f));
		rowRoot.AddChild(time);

		var text = CreateDepthTextLabel("", 9, new Color(0.62f, 0.22f, 0.40f), bold: true);
		text.AutowrapMode = TextServer.AutowrapMode.Off;
		text.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		text.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(text, RectLTRB(0.250f, 0.00f, 1.000f, 1.00f));
		rowRoot.AddChild(text);

		return new DepthSignalTimelineRowView
		{
			Root = rowRoot,
			Dot = dot,
			TimeLabel = time,
			TextLabel = text,
		};
	}

	private void BuildDepthContextFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthContextFrame", SlotContext, DepthContextFramePath);
		if (root == null)
			return;

		_depthContextChips.Clear();
		AddDepthContextChip(root, "quiet", "♪", "Yên tĩnh", "nền thấp", RectLTRB(0.050f, 0.330f, 0.175f, 0.850f));
		AddDepthContextChip(root, "alone", "●", "Chỉ có Ngài", "phiên riêng", RectLTRB(0.185f, 0.330f, 0.315f, 0.850f));
		AddDepthContextChip(root, "interrupt", "□", "Không bị", "chen ngang", RectLTRB(0.320f, 0.330f, 0.465f, 0.850f));
		AddDepthContextChip(root, "time", "☾", "Thời gian", "tối muộn", RectLTRB(0.470f, 0.330f, 0.610f, 0.850f));
	}

	private void AddDepthContextChip(Control root, string key, string icon, string title, string meta, Rect2 slot)
	{
		var item = new Control
		{
			Name = $"DepthContextChip_{key}",
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(item, slot);
		root.AddChild(item);

		var iconBg = new Panel
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(iconBg, RectLTRB(0.320f, 0.000f, 0.680f, 0.370f));
		item.AddChild(iconBg);

		var iconLabel = CreateDepthTextLabel(icon, 12, new Color(0.96f, 0.28f, 0.56f), bold: true);
		iconLabel.HorizontalAlignment = HorizontalAlignment.Center;
		iconLabel.VerticalAlignment = VerticalAlignment.Center;
		iconLabel.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		iconBg.AddChild(iconLabel);

		var titleLabel = CreateDepthTextLabel(title, 7, new Color(0.72f, 0.24f, 0.46f), bold: true);
		titleLabel.HorizontalAlignment = HorizontalAlignment.Center;
		titleLabel.VerticalAlignment = VerticalAlignment.Center;
		titleLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		titleLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(titleLabel, RectLTRB(0.000f, 0.445f, 1.000f, 0.640f));
		item.AddChild(titleLabel);

		var metaLabel = CreateDepthTextLabel(meta, 6, new Color(0.58f, 0.30f, 0.44f, 0.82f));
		metaLabel.HorizontalAlignment = HorizontalAlignment.Center;
		metaLabel.VerticalAlignment = VerticalAlignment.Center;
		metaLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		metaLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		PlaceBySlot(metaLabel, RectLTRB(0.000f, 0.640f, 1.000f, 0.875f));
		item.AddChild(metaLabel);

		var view = new DepthContextChipView
		{
			Root = item,
			IconBg = iconBg,
			IconLabel = iconLabel,
			TitleLabel = titleLabel,
			MetaLabel = metaLabel,
			Key = key,
		};
		_depthContextChips[key] = view;
		ApplyDepthContextChipStyle(view, active: true);
	}

	private void ApplyDepthContextDefaults()
	{
		ApplyDepthContextContent(new List<string> { DepthContextCurrentTimeTag(), "quiet", "just_you" }, "attentive");
	}

	private void ApplyDepthV2Context(JsonElement root)
	{
		var tags = new List<string>();
		string focusMode = DepthV2FocusMode(root);
		if (root.TryGetProperty("context", out var context) && context.ValueKind == JsonValueKind.Object)
		{
			focusMode = JsonText(context, "focus_mode", focusMode);
			if (context.TryGetProperty("tags", out var rawTags) && rawTags.ValueKind == JsonValueKind.Array)
			{
				foreach (var raw in rawTags.EnumerateArray())
				{
					if (raw.ValueKind != JsonValueKind.String)
						continue;
					string tag = NormalizeDepthKind(raw.GetString() ?? "");
					if (!string.IsNullOrWhiteSpace(tag) && !tags.Contains(tag))
						tags.Add(tag);
				}
			}
		}

		if (tags.Count == 0)
			tags.AddRange(new[] { "quiet", "just_you" });

		ApplyDepthContextContent(tags, focusMode);
	}

	private void ApplyDepthContextContent(List<string> tags, string focusMode)
	{
		bool quiet = DepthContextHasTag(tags, "quiet", "silent", "calm", "low_noise", "ambient");
		bool alone = DepthContextHasTag(tags, "just_you", "alone", "private", "one_on_one", "solo");
		bool interrupted = DepthContextHasTag(tags, "interrupt", "interrupted", "busy", "crowded", "noisy");
		string timeLabel = DepthContextTimeLabel(tags);

		ApplyDepthContextChip("quiet", "♪", quiet ? "Yên tĩnh" : "Có nhiễu", quiet ? "nền thấp" : "nền động", quiet);
		ApplyDepthContextChip("alone", "●", alone ? "Chỉ có Ngài" : "Bối cảnh mở", alone ? "phiên riêng" : "nhiều tín hiệu", alone);
		ApplyDepthContextChip("interrupt", "□", interrupted ? "Có chen" : "Không bị", interrupted ? "vừa ngắt lời" : "chen ngang", !interrupted);
		ApplyDepthContextChip("time", DepthContextTimeIcon(timeLabel), "Thời gian", timeLabel, true);

		// Focus mode chưa cần hiện thành dòng riêng; nó chỉ giúp chip yên tĩnh đổi sắc
		// khi backend báo chế độ rất nhẹ. UI nhỏ nên giữ thông tin cô đọng như ảnh mẫu.
		if (NormalizeDepthKind(focusMode) == "quiet")
			ApplyDepthContextChip("quiet", "♪", "Yên tĩnh", "nhịp thấp", true);
	}

	private void ApplyDepthContextChip(string key, string icon, string title, string meta, bool active)
	{
		if (!_depthContextChips.TryGetValue(key, out var chip) || chip == null)
			return;

		UpdateDepthLabelText(chip.IconLabel, icon);
		UpdateDepthLabelText(chip.TitleLabel, TrimDepthUiText(title, 16));
		UpdateDepthLabelText(chip.MetaLabel, TrimDepthUiText(meta, 18));
		ApplyDepthContextChipStyle(chip, active);
	}

	private void ApplyDepthContextChipStyle(DepthContextChipView chip, bool active)
	{
		if (chip?.IconBg == null)
			return;

		Color bg = active
			? new Color(1f, 0.88f, 0.94f, 0.72f)
			: new Color(0.94f, 0.86f, 0.90f, 0.46f);
		Color border = active
			? new Color(0.98f, 0.60f, 0.76f, 0.62f)
			: new Color(0.78f, 0.64f, 0.70f, 0.34f);
		Color icon = active
			? new Color(0.96f, 0.24f, 0.55f, 0.95f)
			: new Color(0.62f, 0.42f, 0.52f, 0.58f);
		Color title = active
			? new Color(0.72f, 0.24f, 0.46f, 0.95f)
			: new Color(0.58f, 0.38f, 0.48f, 0.62f);
		Color meta = active
			? new Color(0.58f, 0.30f, 0.44f, 0.82f)
			: new Color(0.52f, 0.38f, 0.46f, 0.52f);

		chip.IconBg.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = border,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 18,
			CornerRadiusTopRight = 18,
			CornerRadiusBottomLeft = 18,
			CornerRadiusBottomRight = 18,
		});
		chip.IconLabel?.AddThemeColorOverride("font_color", icon);
		chip.TitleLabel?.AddThemeColorOverride("font_color", title);
		chip.MetaLabel?.AddThemeColorOverride("font_color", meta);
	}

	private static bool DepthContextHasTag(List<string> tags, params string[] candidates)
	{
		if (tags == null || candidates == null)
			return false;
		foreach (string candidate in candidates)
		{
			string normalized = NormalizeDepthKind(candidate);
			foreach (string tag in tags)
			{
				if (NormalizeDepthKind(tag) == normalized)
					return true;
			}
		}
		return false;
	}

	private static string DepthContextTimeLabel(List<string> tags)
	{
		if (DepthContextHasTag(tags, "late_night"))
			return "tối muộn";
		if (DepthContextHasTag(tags, "evening"))
			return "buổi tối";
		if (DepthContextHasTag(tags, "afternoon"))
			return "buổi chiều";
		if (DepthContextHasTag(tags, "morning"))
			return "buổi sáng";
		return "hiện tại";
	}

	private static string DepthContextCurrentTimeTag()
	{
		int hour = DateTime.Now.Hour;
		if (hour >= 5 && hour < 12)
			return "morning";
		if (hour >= 12 && hour < 18)
			return "afternoon";
		if (hour >= 18 && hour < 24)
			return "evening";
		return "late_night";
	}

	private static string DepthContextTimeIcon(string timeLabel)
	{
		return timeLabel switch
		{
			"buổi sáng" => "☼",
			"buổi chiều" => "◐",
			"buổi tối" or "tối muộn" => "☾",
			_ => "•",
		};
	}

	private void BuildDepthEmotionJournalFrame(Control parent)
	{
		var root = CreateDepthFrameRoot(parent, "DepthEmotionJournalFrame", SlotEmotionJournal, DepthEmotionJournalFramePath);
		if (root == null)
			return;

		_depthEmotionSparkline = new DepthEmotionSparklineView
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		PlaceBySlot(_depthEmotionSparkline, RectLTRB(0.055f, 0.305f, 0.945f, 0.655f));
		root.AddChild(_depthEmotionSparkline);

		_depthEmotionLeftLabel = CreateDepthTextLabel("ổn định", 8, new Color(0.70f, 0.30f, 0.48f), bold: true);
		_depthEmotionLeftLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthEmotionLeftLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_depthEmotionLeftLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthEmotionLeftLabel, RectLTRB(0.060f, 0.725f, 0.350f, 0.850f));
		root.AddChild(_depthEmotionLeftLabel);

		_depthEmotionRightLabel = CreateDepthTextLabel("hơi tích cực", 8, new Color(0.72f, 0.20f, 0.46f), bold: true);
		_depthEmotionRightLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_depthEmotionRightLabel.TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;
		_depthEmotionRightLabel.HorizontalAlignment = HorizontalAlignment.Right;
		_depthEmotionRightLabel.VerticalAlignment = VerticalAlignment.Center;
		PlaceBySlot(_depthEmotionRightLabel, RectLTRB(0.590f, 0.725f, 0.935f, 0.850f));
		root.AddChild(_depthEmotionRightLabel);
	}

	private Control CreateDepthFrameRoot(Control parent, string name, Rect2 slot, string resourcePath)
	{
		if (parent == null)
			return null;

		var root = new Control
		{
			Name = name,
			MouseFilter = Control.MouseFilterEnum.Ignore,
			ClipContents = true,
		};
		PlaceBySlot(root, slot);
		parent.AddChild(root);

		if (ResourceLoader.Exists(resourcePath))
		{
			var tex = GD.Load<Texture2D>(resourcePath);
			if (tex != null)
			{
				var bg = new TextureRect
				{
					Texture = tex,
					ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
					StretchMode = TextureRect.StretchModeEnum.Scale,
					MouseFilter = Control.MouseFilterEnum.Ignore,
				};
				bg.SetAnchorsPreset(Control.LayoutPreset.FullRect);
				root.AddChild(bg);
			}
		}

		return root;
	}

	private void UpdateDepthContentRootTransform()
	{
		if (_depthPanelContentRoot == null || _depthPanel == null)
			return;

		_depthPanelContentRoot.Position = Vector2.Zero;
		_depthPanelContentRoot.Rotation = 0f;
		_depthPanelContentRoot.Scale = new Vector2(DepthPanelInnerContentScale, DepthPanelInnerContentScale);
		_depthPanelContentRoot.PivotOffset = _depthPanel.Size * 0.5f;
	}

	private void EnsureDepthFontsLoaded()
	{
		_depthFontRegular ??= LoadDepthFont("Mali-Regular.ttf") ?? DepthSystemFont();
		_depthFontBold ??= LoadDepthFont("Mali-SemiBold.ttf") ?? _depthFontRegular;
	}

	private Label CreateDepthTextLabel(string text, int fontSize, Color color, bool bold = false)
	{
		EnsureDepthFontsLoaded();
		var label = CreateUiLabel(text, fontSize, color);
		label.MouseFilter = Control.MouseFilterEnum.Ignore;
		label.AddThemeFontOverride("font", bold ? _depthFontBold : _depthFontRegular);
		return label;
	}

	private ProgressBar CreateDepthProgressBar(Color fillColor)
	{
		var bar = new ProgressBar
		{
			MinValue = 0,
			MaxValue = 1,
			Value = 0,
			ShowPercentage = false,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		bar.AddThemeStyleboxOverride("background", new StyleBoxFlat
		{
			BgColor = new Color(0.70f, 0.52f, 0.62f, 0.18f),
			CornerRadiusTopLeft = 4,
			CornerRadiusTopRight = 4,
			CornerRadiusBottomLeft = 4,
			CornerRadiusBottomRight = 4,
		});
		bar.AddThemeStyleboxOverride("fill", new StyleBoxFlat
		{
			BgColor = fillColor,
			CornerRadiusTopLeft = 4,
			CornerRadiusTopRight = 4,
			CornerRadiusBottomLeft = 4,
			CornerRadiusBottomRight = 4,
		});
		return bar;
	}

	private Font LoadDepthFont(string fileName)
	{
		string res = $"res://asset/Resource/{fileName}";
		try
		{
			if (ResourceLoader.Exists(res))
			{
				var font = ResourceLoader.Load<Font>(res);
				if (font != null)
					return font;
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
					var fontFile = new FontFile();
					fontFile.Data = bytes;
					return fontFile;
				}
			}
		}
		catch { }

		return null;
	}

	private static SystemFont DepthSystemFont() => new()
	{
		FontNames = new[] { "Quicksand", "Comfortaa", "Nunito", "Segoe UI", "Arial" },
		Antialiasing = TextServer.FontAntialiasing.Gray,
		SubpixelPositioning = TextServer.SubpixelPositioning.Auto,
		Hinting = TextServer.Hinting.Light,
	};

	private void PlaceBySlot(Control ctrl, Rect2 slot)
	{
		ctrl.AnchorLeft = slot.Position.X;
		ctrl.AnchorTop = slot.Position.Y;
		ctrl.AnchorRight = slot.Position.X + slot.Size.X;
		ctrl.AnchorBottom = slot.Position.Y + slot.Size.Y;
		ctrl.OffsetLeft = 0f;
		ctrl.OffsetTop = 0f;
		ctrl.OffsetRight = 0f;
		ctrl.OffsetBottom = 0f;
	}

	private void TryCaptureDepthBlock(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return;

		try
		{
			using var doc = JsonDocument.Parse(raw);
			var root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object
				|| !root.TryGetProperty("depth", out var d)
				|| d.ValueKind != JsonValueKind.Object)
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

	private void TryCaptureDepthV2Block(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return;

		try
		{
			using var doc = JsonDocument.Parse(raw);
			var root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object
				|| !root.TryGetProperty("depth_v2", out var d)
				|| d.ValueKind != JsonValueKind.Object)
				return;

			string json = d.GetRawText();
			if (!DepthV2HasContent(json))
				return;

			_latestDepthV2Json = json;
			SaveDepthV2State();
			if (_depthPanel != null && _depthPanel.Visible)
				RefreshDepthPanel();
		}
		catch (Exception ex)
		{
			GD.Print($"[depth_v2] capture fail: {ex.Message}");
		}
	}

	private static bool DepthV2HasContent(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return false;

		try
		{
			using var doc = JsonDocument.Parse(raw);
			var root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return false;
			if (root.TryGetProperty("version", out var versionEl) && versionEl.ValueKind == JsonValueKind.Number)
			{
				if (versionEl.TryGetInt32(out int version) && version == 2)
					return true;
			}
			if (root.TryGetProperty("interiority", out var interiorityEl) && interiorityEl.ValueKind == JsonValueKind.Object)
				return true;
			if (root.TryGetProperty("affect", out var affectEl) && affectEl.ValueKind == JsonValueKind.Object)
				return true;
			return root.TryGetProperty("priorities", out var prioritiesEl) && prioritiesEl.ValueKind == JsonValueKind.Array;
		}
		catch
		{
			return false;
		}
	}

	private void SaveDepthV2State()
	{
		if (string.IsNullOrWhiteSpace(_latestDepthV2Json))
			return;

		try
		{
			using var file = Godot.FileAccess.Open(DepthV2StatePath, Godot.FileAccess.ModeFlags.Write);
			if (file != null)
				file.StoreString(_latestDepthV2Json);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[depth_v2] Save state failed: {ex.Message}");
		}
	}

	private void LoadDepthV2State()
	{
		try
		{
			if (!Godot.FileAccess.FileExists(DepthV2StatePath))
				return;

			using var file = Godot.FileAccess.Open(DepthV2StatePath, Godot.FileAccess.ModeFlags.Read);
			if (file == null)
				return;

			string content = file.GetAsText();
			if (!string.IsNullOrWhiteSpace(content) && DepthV2HasContent(content))
				_latestDepthV2Json = content;
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[depth_v2] Load state failed: {ex.Message}");
		}
	}

	private void RefreshDepthPanel()
	{
		if (_depthPanel == null)
			return;

		ApplyDepthAffectContent("Bình tĩnh", "Thoải mái, sẵn sàng trò chuyện.", 0.72f);
		ApplyDepthTomContent(
			score: 0f,
			summary: "chưa đọc được gì đủ chắc.",
			confidence: 0f,
			thickness: 0f,
			attachment: 0f,
			beliefCount: 0,
			status: "đang chờ dữ liệu",
			topBelief: "belief: chưa có");

		ApplyDepthSelfContinuityContent(0f, 0f, 0f, "chưa rõ");
		ApplyDepthAutoSwitchDefaults();
		ApplyDepthInteriorityEmpty("đang sắp xếp suy nghĩ...✦");
		ApplyDepthPriorityDefaults("attentive");
		ApplyDepthSignalTimelineEmpty("timeline chờ tín hiệu ✦");
		ApplyDepthContextDefaults();
		ApplyDepthEmotionJournalDefaults();

		if (!string.IsNullOrWhiteSpace(_latestDepthV2Json))
		{
			try
			{
				using var doc = JsonDocument.Parse(_latestDepthV2Json);
				if (doc.RootElement.ValueKind == JsonValueKind.Object)
				{
					ApplyDepthV2Affect(doc.RootElement);
					ApplyDepthV2EmotionJournal(doc.RootElement);
					ApplyDepthV2Tom(doc.RootElement);
					ApplyDepthV2SelfContinuity(doc.RootElement);
					ApplyDepthV2AutoSwitch(doc.RootElement);
					ApplyDepthV2Interiority(doc.RootElement);
					ApplyDepthV2Priorities(doc.RootElement);
					ApplyDepthV2SignalTimeline(doc.RootElement);
					ApplyDepthV2Context(doc.RootElement);
					return;
				}
			}
			catch (Exception ex)
			{
				GD.Print($"[depth_v2] refresh fail: {ex.Message}");
			}
		}

		if (!string.IsNullOrWhiteSpace(_latestDepthJson))
		{
			try
			{
				using var doc = JsonDocument.Parse(_latestDepthJson);
				if (doc.RootElement.ValueKind == JsonValueKind.Object)
				{
					ApplyLegacyDepthAffect(doc.RootElement);
					ApplyLegacyDepthEmotionJournal(doc.RootElement);
					ApplyLegacyDepthTom(doc.RootElement);
					ApplyLegacyDepthAutoSwitch(doc.RootElement);
					ApplyLegacyDepthInteriority(doc.RootElement);
					ApplyLegacyDepthPriorities(doc.RootElement);
					ApplyLegacyDepthSignalTimeline(doc.RootElement);
				}
			}
			catch (Exception ex)
			{
				GD.Print($"[depth] affect refresh fail: {ex.Message}");
			}
		}
	}

	private void ApplyDepthV2Affect(JsonElement root)
	{
		if (!root.TryGetProperty("affect", out var affect) || affect.ValueKind != JsonValueKind.Object)
			return;

		string headline = LocalizeDepthAffectHeadline(JsonText(affect, "headline", "steady"));
		string subtext = LocalizeDepthAffectSubtext(JsonText(affect, "subtext", "listening quietly"));
		float stability = 0.72f;

		if (affect.TryGetProperty("metrics", out var metrics) && metrics.ValueKind == JsonValueKind.Object)
			stability = Mathf.Clamp(JsonFloat(metrics, "stability", 0.72f), 0f, 1f);

		ApplyDepthAffectContent(headline, subtext, stability);
	}

	private void ApplyDepthV2EmotionJournal(JsonElement root)
	{
		var values = new List<float>();
		float latestValue = 0.58f;
		float stability = 0.72f;

		if (root.TryGetProperty("affect_history", out var history) && history.ValueKind == JsonValueKind.Array)
		{
			foreach (var raw in history.EnumerateArray())
			{
				if (raw.ValueKind != JsonValueKind.Object)
					continue;

				float value = JsonFloat(raw, "value", JsonFloat(raw, "positive_bias", 0.5f));
				latestValue = Mathf.Clamp(value, 0f, 1f);
				stability = Mathf.Clamp(JsonFloat(raw, "stability", stability), 0f, 1f);
				values.Add(latestValue);
				if (values.Count > 28)
					values.RemoveAt(0);
			}
		}

		if (values.Count < 2
			&& root.TryGetProperty("affect", out var affect)
			&& affect.ValueKind == JsonValueKind.Object
			&& affect.TryGetProperty("metrics", out var metrics)
			&& metrics.ValueKind == JsonValueKind.Object)
		{
			latestValue = Mathf.Clamp(JsonFloat(metrics, "positive_bias", latestValue), 0f, 1f);
			stability = Mathf.Clamp(JsonFloat(metrics, "stability", stability), 0f, 1f);
			values = BuildDepthEmotionFallbackValues(latestValue, stability);
		}

		ApplyDepthEmotionJournalContent(values, stability, latestValue);
	}

	private void ApplyDepthV2Tom(JsonElement root)
	{
		JsonElement tom = default;
		JsonElement userModel = default;
		JsonElement significance = default;
		JsonElement attachmentAnchor = default;

		bool hasTom = root.TryGetProperty("tom", out tom) && tom.ValueKind == JsonValueKind.Object;
		bool hasUserModel = root.TryGetProperty("user_model", out userModel) && userModel.ValueKind == JsonValueKind.Object;
		bool hasSignificance = root.TryGetProperty("significance", out significance) && significance.ValueKind == JsonValueKind.Object;
		bool hasAttachment = root.TryGetProperty("attachment_anchor", out attachmentAnchor) && attachmentAnchor.ValueKind == JsonValueKind.Object;

		string tomText = hasTom ? JsonText(tom, "text", "") : "";
		float confidence = hasTom ? Mathf.Clamp(JsonFloat(tom, "confidence", 0f), 0f, 1f) : 0f;
		float thickness = hasUserModel ? Mathf.Clamp(JsonFloat(userModel, "model_thickness", 0f), 0f, 1f) : 0f;
		if (thickness <= 0f && hasSignificance)
			thickness = Mathf.Clamp(JsonFloat(significance, "model_thickness", 0f), 0f, 1f);
		float attachment = hasAttachment ? Mathf.Clamp(JsonFloat(attachmentAnchor, "longarc", 0f), 0f, 1f) : DepthV2AttachmentFallback(root);
		int beliefCount = hasUserModel ? JsonInt(userModel, "belief_count", 0) : 0;
		string topBelief = hasUserModel ? DepthV2TopBelief(userModel) : "";
		string summary = !string.IsNullOrWhiteSpace(tomText)
			? StripTomPrefix(tomText)
			: (!string.IsNullOrWhiteSpace(topBelief) ? topBelief : "chưa đọc được gì đủ chắc.");
		float score = Mathf.Clamp(Mathf.Max(thickness, confidence * 0.72f), 0f, 1f);
		string status = (hasTom || hasUserModel || hasSignificance) ? "depth_v2: đã nhận" : "depth_v2: thiếu mô hình";

		ApplyDepthTomContent(
			score: score,
			summary: summary,
			confidence: confidence,
			thickness: thickness,
			attachment: attachment,
			beliefCount: beliefCount,
			status: status,
			topBelief: string.IsNullOrWhiteSpace(topBelief) ? "belief: chưa có" : $"belief: {topBelief}");
	}

	private void ApplyDepthV2SelfContinuity(JsonElement root)
	{
		if (!root.TryGetProperty("expression", out var expression) || expression.ValueKind != JsonValueKind.Object)
		{
			ApplyDepthSelfContinuityContent(0f, 0f, 0f, "chưa rõ");
			return;
		}

		float want = Mathf.Clamp(JsonFloat(expression, "want", 0f), 0f, 1f);
		float suppress = Mathf.Clamp(JsonFloat(expression, "suppress", 0f), 0f, 1f);
		float allowed = Mathf.Clamp(JsonFloat(expression, "allowed", 0f), 0f, 1f);
		string stance = LocalizeDepthExpressionStance(JsonText(expression, "stance", ""), want, suppress, allowed);

		ApplyDepthSelfContinuityContent(want, suppress, allowed, stance);
	}

	private void ApplyLegacyDepthTom(JsonElement root)
	{
		if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
			return;

		string tomText = "";
		float confidence = 0f;
		if (depth.TryGetProperty("tom_read_rich", out var rich) && rich.ValueKind == JsonValueKind.Object)
		{
			tomText = JsonText(rich, "text", "");
			confidence = Mathf.Clamp(JsonFloat(rich, "confidence", 0f), 0f, 1f);
		}
		if (string.IsNullOrWhiteSpace(tomText))
			tomText = JsonText(depth, "tom_read", "");

		if (string.IsNullOrWhiteSpace(tomText))
			return;

		ApplyDepthTomContent(
			score: Mathf.Clamp(confidence * 0.72f, 0f, 1f),
			summary: StripTomPrefix(tomText),
			confidence: confidence,
			thickness: 0f,
			attachment: DepthLegacyAttachmentFallback(depth),
			beliefCount: 0,
			status: "legacy depth: đã nhận",
			topBelief: "belief: legacy chưa gửi user_model");
	}

	private void ApplyDepthTomContent(
		float score,
		string summary,
		float confidence,
		float thickness,
		float attachment,
		int beliefCount,
		string status,
		string topBelief)
	{
		float safeScore = Mathf.Clamp(score, 0f, 1f);
		float safeConfidence = Mathf.Clamp(confidence, 0f, 1f);
		float safeThickness = Mathf.Clamp(thickness, 0f, 1f);
		float safeAttachment = Mathf.Clamp(attachment, 0f, 1f);

		UpdateDepthLabelText(_depthTomScoreLabel, $"{safeScore:0.00}");
		UpdateDepthLabelText(_depthTomSummaryLabel, TrimDepthUiText(summary, 72));
		UpdateDepthLabelText(_depthTomStatusLabel, string.IsNullOrWhiteSpace(status) ? "đang chờ dữ liệu" : status);
		UpdateDepthLabelText(
			_depthTomMetaLabel,
			$"dày {safeThickness:0.00}  ·  đọc {safeConfidence:0.00}  ·  gắn {safeAttachment:0.00}  ·  {Math.Max(0, beliefCount)} belief");
		UpdateDepthLabelText(_depthTomBeliefLabel, TrimDepthUiText(topBelief, 64));

		if (_depthTomThicknessBar != null)
			_depthTomThicknessBar.Value = safeThickness;
		if (_depthTomConfidenceBar != null)
			_depthTomConfidenceBar.Value = safeConfidence;
		if (_depthTomAttachmentBar != null)
			_depthTomAttachmentBar.Value = safeAttachment;
	}

		private void ApplyDepthSelfContinuityContent(float want, float suppress, float allowed, string stance)
		{
			float safeWant = Mathf.Clamp(want, 0f, 1f);
			float safeSuppress = Mathf.Clamp(suppress, 0f, 1f);
		float safeAllowed = Mathf.Clamp(allowed, 0f, 1f);
		string safeStance = string.IsNullOrWhiteSpace(stance) ? "cân bằng" : stance.Trim();

		if (_depthSelfWantBar != null)
			_depthSelfWantBar.Value = safeWant;
		if (_depthSelfSuppressBar != null)
			_depthSelfSuppressBar.Value = safeSuppress;
		if (_depthSelfAllowedBar != null)
			_depthSelfAllowedBar.Value = safeAllowed;

		UpdateDepthLabelText(_depthSelfWantValueLabel, $"{safeWant:0.00}");
		UpdateDepthLabelText(_depthSelfSuppressValueLabel, $"{safeSuppress:0.00}");
		UpdateDepthLabelText(_depthSelfAllowedValueLabel, $"{safeAllowed:0.00}");
			UpdateDepthLabelText(_depthSelfStanceValueLabel, safeStance);
		}

	private void ApplyDepthAutoSwitchDefaults()
	{
		var activeByKey = new Dictionary<string, bool>
		{
			["n1"] = true,
			["n2"] = true,
			["interiority"] = true,
			["tom"] = true,
			["embed"] = true,
			["mind"] = true,
		};
		ApplyDepthAutoSwitchContent(activeByKey, null, null, "adaptive", "voice_guarded_plus");
	}

	private void ApplyDepthV2AutoSwitch(JsonElement root)
	{
		if (root.TryGetProperty("autoswitch", out var autoswitch) && autoswitch.ValueKind == JsonValueKind.Object)
		{
			var activeByKey = new Dictionary<string, bool>();
			var labelByKey = new Dictionary<string, string>();
			var accentByKey = new Dictionary<string, string>();
			if (autoswitch.TryGetProperty("chips", out var chips) && chips.ValueKind == JsonValueKind.Array)
			{
				foreach (var raw in chips.EnumerateArray())
				{
					if (raw.ValueKind != JsonValueKind.Object)
						continue;
					string key = NormalizeDepthKind(JsonText(raw, "key", ""));
					if (string.IsNullOrWhiteSpace(key))
						continue;
					activeByKey[key] = JsonBool(raw, "active", true);
					labelByKey[key] = JsonText(raw, "label", HumanizeDepthPhrase(key));
					accentByKey[key] = JsonText(raw, "accent", "pink");
				}
			}

			ApplyDepthAutoSwitchContent(
				activeByKey,
				labelByKey,
				accentByKey,
				JsonText(autoswitch, "mode", "adaptive"),
				JsonText(autoswitch, "policy", "voice_guarded_plus"));
			return;
		}

		if (root.TryGetProperty("flags", out var flags) && flags.ValueKind == JsonValueKind.Object)
			ApplyDepthAutoSwitchFromFlags(flags, "adaptive", DepthV2SafetyPolicy(root));
	}

	private void ApplyLegacyDepthAutoSwitch(JsonElement root)
	{
		if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
			return;
		if (depth.TryGetProperty("flags", out var flags) && flags.ValueKind == JsonValueKind.Object)
			ApplyDepthAutoSwitchFromFlags(flags, "adaptive", "voice_guarded_plus");
	}

	private void ApplyDepthAutoSwitchFromFlags(JsonElement flags, string mode, string policy)
	{
		// Mapping này bám theo cortex.depth_flags.KNOWN_FLAGS; UI chỉ đổi tên cho đẹp.
		var activeByKey = new Dictionary<string, bool>
		{
			["n1"] = JsonBool(flags, "emotional_consequence", true),
			["n2"] = JsonBool(flags, "development_growth", true),
			["interiority"] = JsonBool(flags, "interior_surface", true),
			["tom"] = JsonBool(flags, "tom_advisor", true),
			["embed"] = JsonBool(flags, "real_embeddings", true),
			["mind"] = JsonBool(flags, "private_mind", true),
		};
		ApplyDepthAutoSwitchContent(activeByKey, null, null, mode, policy);
	}

	private void ApplyDepthAutoSwitchContent(
		Dictionary<string, bool> activeByKey,
		Dictionary<string, string> labelByKey,
		Dictionary<string, string> accentByKey,
		string mode,
		string policy)
	{
		if (_depthAutoSwitchChips == null)
			return;

		foreach (var chip in _depthAutoSwitchChips)
		{
			bool active = activeByKey == null || !activeByKey.TryGetValue(chip.Key, out bool value) ? true : value;
			string accent = chip.Accent;
			if (accentByKey != null && accentByKey.TryGetValue(chip.Key, out var dynamicAccent) && !string.IsNullOrWhiteSpace(dynamicAccent))
				accent = NormalizeDepthKind(dynamicAccent);
			if (labelByKey != null && labelByKey.TryGetValue(chip.Key, out var dynamicLabel) && !string.IsNullOrWhiteSpace(dynamicLabel))
				UpdateDepthLabelText(chip.Label, TrimDepthUiText(dynamicLabel, 16));
			ApplyDepthAutoSwitchChipStyle(chip, active, accent);
		}

		UpdateDepthLabelText(_depthAutoSwitchModeLabel, string.IsNullOrWhiteSpace(mode) ? "adaptive" : TrimDepthUiText(NormalizeDepthKind(mode), 18));
		UpdateDepthLabelText(_depthAutoSwitchPolicyLabel, string.IsNullOrWhiteSpace(policy) ? "voice_guarded_plus" : TrimDepthUiText(NormalizeDepthKind(policy), 24));
		UpdateDepthLabelText(_depthAutoSwitchGlyphLabel, "✦  ♥");
	}

	private void ApplyDepthAutoSwitchChipStyle(DepthAutoSwitchChipView chip, bool active, string accent)
	{
		if (chip == null || chip.Root == null || chip.Label == null)
			return;

		bool mint = NormalizeDepthKind(accent) == "mint";
		Color bg;
		Color border;
		Color text;
		if (active && mint)
		{
			bg = new Color(0.92f, 0.97f, 0.93f, 0.82f);
			border = new Color(0.73f, 0.86f, 0.78f, 0.66f);
			text = new Color(0.40f, 0.58f, 0.55f, 0.96f);
		}
		else if (active)
		{
			bg = new Color(1.00f, 0.92f, 0.96f, 0.84f);
			border = new Color(0.97f, 0.66f, 0.79f, 0.74f);
			text = new Color(0.82f, 0.25f, 0.50f, 0.98f);
		}
		else if (mint)
		{
			bg = new Color(0.90f, 0.94f, 0.91f, 0.34f);
			border = new Color(0.72f, 0.82f, 0.76f, 0.28f);
			text = new Color(0.42f, 0.56f, 0.54f, 0.46f);
		}
		else
		{
			bg = new Color(1.00f, 0.92f, 0.96f, 0.34f);
			border = new Color(0.97f, 0.66f, 0.79f, 0.30f);
			text = new Color(0.82f, 0.25f, 0.50f, 0.48f);
		}

		chip.Root.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = bg,
			BorderColor = border,
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 18,
			CornerRadiusTopRight = 18,
			CornerRadiusBottomLeft = 18,
			CornerRadiusBottomRight = 18,
		});
		chip.Label.AddThemeColorOverride("font_color", text);
	}

	private static string DepthV2SafetyPolicy(JsonElement root)
	{
		if (!root.TryGetProperty("safety", out var safety) || safety.ValueKind != JsonValueKind.Object)
			return "voice_guarded_plus";
		bool strict = JsonBool(safety, "strict_grounding", true);
		bool safe = JsonBool(safety, "safe_mode", true);
		if (strict && safe)
			return "voice_guarded_plus";
		if (strict)
			return "strict_grounding";
		if (safe)
			return "safe_mode";
		return "expressive";
	}

		private void ApplyDepthV2Interiority(JsonElement root)
		{
			var items = new List<DepthInteriorityItem>();

			if (root.TryGetProperty("interiority", out var interiority) && interiority.ValueKind == JsonValueKind.Object)
			{
				// Contract mới: Python gửi sẵn `feed` đã gom gọn. Body chỉ render,
				// không tự diễn giải sâu để tránh lệch nghĩa giữa backend và UI.
				if (interiority.TryGetProperty("feed", out var feed) && feed.ValueKind == JsonValueKind.Array)
					CollectDepthInteriorityFeed(feed, items);

				// Fallback cho payload cũ: chưa có feed thì đọc các section gốc.
				if (items.Count == 0)
					CollectDepthInterioritySections(interiority, items);
			}

			// Fallback cuối: journal có source/text/time, đủ để panel không bị trống.
			if (items.Count == 0 && root.TryGetProperty("journal", out var journal) && journal.ValueKind == JsonValueKind.Array)
				CollectDepthInteriorityJournal(journal, items);

			if (items.Count == 0)
			{
				ApplyDepthInteriorityEmpty("✦");
				return;
			}

			ApplyDepthInteriorityItems(items, $"đã nhận {Math.Min(items.Count, _depthInteriorityRows.Count)} luồng nghĩ ✦");
		}

		private void ApplyLegacyDepthInteriority(JsonElement root)
		{
			if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
				return;

			var items = new List<DepthInteriorityItem>();
			if (depth.TryGetProperty("interiority", out var interiority) && interiority.ValueKind == JsonValueKind.Object)
			{
				if (interiority.TryGetProperty("items", out var legacyItems) && legacyItems.ValueKind == JsonValueKind.Array)
				{
					foreach (var raw in legacyItems.EnumerateArray())
					{
						if (raw.ValueKind != JsonValueKind.Object)
							continue;
						AddDepthInteriorityItem(
							items,
							kind: JsonText(raw, "kind", "current"),
							title: JsonText(raw, "status", ""),
							text: JsonText(raw, "theme", ""),
							meta: $"pressure {JsonFloat(raw, "pressure", 0f):0.00}",
							time: "");
					}
				}
			}

			if (items.Count > 0)
				ApplyDepthInteriorityItems(items, "legacy interiority ✦");
		}

		private void CollectDepthInteriorityFeed(JsonElement feed, List<DepthInteriorityItem> items)
		{
			foreach (var raw in feed.EnumerateArray())
			{
				if (raw.ValueKind != JsonValueKind.Object)
					continue;
				AddDepthInteriorityItem(
					items,
					kind: JsonText(raw, "kind", JsonText(raw, "source", "current")),
					title: JsonText(raw, "title", ""),
					text: JsonText(raw, "text", ""),
					meta: JsonText(raw, "meta", ""),
					time: JsonText(raw, "time", ""));
			}
		}

		private void CollectDepthInterioritySections(JsonElement interiority, List<DepthInteriorityItem> items)
		{
			foreach (string kind in new[] { "current", "concern", "analysis", "future", "surface", "settled" })
			{
				if (!interiority.TryGetProperty(kind, out var section) || section.ValueKind != JsonValueKind.Object)
					continue;
				string title = JsonText(section, "title", DepthInteriorityDefaultTitle(kind));
				if (!section.TryGetProperty("items", out var sectionItems) || sectionItems.ValueKind != JsonValueKind.Array)
					continue;

				foreach (var rawItem in sectionItems.EnumerateArray())
				{
					if (rawItem.ValueKind != JsonValueKind.Object)
						continue;
					AddDepthInteriorityItem(
						items,
						kind: kind,
						title: title,
						text: JsonText(rawItem, "text", ""),
						meta: JsonText(rawItem, "badge", ""),
						time: "");
					break;
				}
			}
		}

		private void CollectDepthInteriorityJournal(JsonElement journal, List<DepthInteriorityItem> items)
		{
			foreach (var raw in journal.EnumerateArray())
			{
				if (raw.ValueKind != JsonValueKind.Object)
					continue;
				AddDepthInteriorityItem(
					items,
					kind: JsonText(raw, "source", "observe"),
					title: DepthInteriorityDefaultTitle(JsonText(raw, "source", "observe")),
					text: JsonText(raw, "text", ""),
					meta: "journal",
					time: JsonText(raw, "time", ""));
			}
		}

		private static void AddDepthInteriorityItem(
			List<DepthInteriorityItem> items,
			string kind,
			string title,
			string text,
			string meta,
			string time)
		{
			string safeText = TrimDepthUiText(text, 120);
			if (string.IsNullOrWhiteSpace(safeText))
				return;

			string safeKind = NormalizeDepthKind(kind);
			foreach (var item in items)
			{
				if (string.Equals(item.Text, safeText, StringComparison.OrdinalIgnoreCase))
					return;
			}

			items.Add(new DepthInteriorityItem
			{
				Kind = string.IsNullOrWhiteSpace(safeKind) ? "current" : safeKind,
				Title = TrimDepthUiText(title, 36),
				Text = safeText,
				Meta = TrimDepthUiText(meta, 72),
				Time = TrimDepthUiText(time, 16),
			});
		}

		private void ApplyDepthInteriorityItems(List<DepthInteriorityItem> items, string footer)
		{
			int visibleCount = Math.Min(items.Count, _depthInteriorityRows.Count);
			for (int i = 0; i < _depthInteriorityRows.Count; i++)
			{
				var row = _depthInteriorityRows[i];
				bool visible = i < visibleCount;
				row.Root.Visible = visible;
				if (!visible)
					continue;

				var item = items[i];
				ApplyDepthInteriorityIcon(row, item.Kind);
				UpdateDepthLabelText(row.TextLabel, TrimDepthUiText(item.Text, 74));
				UpdateDepthLabelText(row.MetaLabel, DepthInteriorityMetaText(item));
				UpdateDepthLabelText(row.TimeLabel, item.Time);
			}

			UpdateDepthLabelText(_depthInteriorityFooterLabel, string.IsNullOrWhiteSpace(footer) ? "✦" : footer);
			UpdateDepthLabelText(_depthInteriorityPageDotLabel, visibleCount > 0 ? "•   ◦   ◦" : "◦   ◦   ◦");
		}

		private void ApplyDepthInteriorityEmpty(string footer)
		{
			foreach (var row in _depthInteriorityRows)
				row.Root.Visible = false;
			UpdateDepthLabelText(_depthInteriorityFooterLabel, footer);
			UpdateDepthLabelText(_depthInteriorityPageDotLabel, "◦   ◦   ◦");
		}

		private void ApplyDepthInteriorityIcon(DepthInteriorityRowView row, string kind)
		{
			string normalized = NormalizeDepthKind(kind);
			Texture2D texture = LoadDepthInteriorityIcon(normalized);
			if (texture != null)
			{
				row.IconTexture.Texture = texture;
				row.IconTexture.Visible = true;
				row.IconFallbackBg.Visible = false;
				row.IconFallbackLabel.Visible = false;
				return;
			}

			// Nếu asset icon chưa nằm trong project, vẫn hiện một vòng tròn chữ tắt
			// để UI không chết trắng. Đây chỉ là fallback phát triển.
			row.IconTexture.Visible = false;
			row.IconFallbackBg.Visible = true;
			row.IconFallbackLabel.Visible = true;
			row.IconFallbackBg.AddThemeStyleboxOverride("panel", new StyleBoxFlat
			{
				BgColor = DepthInteriorityFallbackColor(normalized),
				CornerRadiusTopLeft = 18,
				CornerRadiusTopRight = 18,
				CornerRadiusBottomLeft = 18,
				CornerRadiusBottomRight = 18,
			});
			UpdateDepthLabelText(row.IconFallbackLabel, DepthInteriorityFallbackGlyph(normalized));
		}

		private Texture2D LoadDepthInteriorityIcon(string kind)
		{
			string path = DepthInteriorityIconPath(kind);
			if (string.IsNullOrWhiteSpace(path))
				return null;
			if (_depthIconCache.TryGetValue(path, out var cached))
				return cached;

			Texture2D texture = null;
			try
			{
				if (ResourceLoader.Exists(path))
					texture = ResourceLoader.Load<Texture2D>(path);
			}
			catch
			{
				texture = null;
			}

			_depthIconCache[path] = texture;
			return texture;
		}

		private static string DepthInteriorityIconPath(string kind)
		{
			return NormalizeDepthKind(kind) switch
			{
				"analysis" => "res://asset/icon/icon-analysis.png",
				"concern" or "tom" => "res://asset/icon/icon-concern.png",
				"current" or "section" => "res://asset/icon/icon-current.png",
				"emotion" or "emotional" => "res://asset/icon/icon-emotion.png",
				"future" or "plan" => "res://asset/icon/icon-future.png",
				"guard" or "restraint" => "res://asset/icon/icon-guard.png",
				"memory" or "memory_echo" => "res://asset/icon/icon-memory-echo.png",
				"observe" or "signal" or "vision" => "res://asset/icon/icon-observe.png",
				"pending" or "waiting" => "res://asset/icon/icon-pending.png",
				"settled" => "res://asset/icon/icon-settled.png",
				"technical" or "tech" or "architecture" or "repair" => "res://asset/icon/icon-tech.png",
				"uncertain" or "unknown" => "res://asset/icon/icon-uncertain.png",
				"surface" or "speech" => "res://asset/icon/icon-concern.png",
				_ => "res://asset/icon/icon-current.png",
			};
		}

		private static string DepthInteriorityMetaText(DepthInteriorityItem item)
		{
			string title = TrimDepthUiText(item.Title, 30);
			string meta = TrimDepthUiText(item.Meta, 54);
			if (string.IsNullOrWhiteSpace(title))
				return string.IsNullOrWhiteSpace(meta) ? DepthInteriorityDefaultTitle(item.Kind) : $"({meta})";
			if (string.IsNullOrWhiteSpace(meta))
				return $"({title})";
			return $"({title} · {meta})";
		}

		private static string DepthInteriorityDefaultTitle(string kind)
		{
			return NormalizeDepthKind(kind) switch
			{
				"analysis" => "đang phân tích",
				"concern" or "tom" => "đang bận tâm",
				"current" => "ý nghĩ đang nổi",
				"emotion" or "emotional" => "cảm xúc nền",
				"future" or "plan" => "hướng tiếp theo",
				"guard" or "restraint" => "tự kìm lại",
				"memory" or "memory_echo" => "ký ức vọng lại",
				"observe" or "signal" or "vision" => "tín hiệu runtime",
				"pending" or "waiting" => "đang chờ",
				"settled" => "đã nguội",
				"technical" or "tech" or "architecture" or "repair" => "kỹ thuật",
				"surface" or "speech" => "muốn nói ra",
				"uncertain" or "unknown" => "chưa chắc",
				_ => "dòng nội tâm",
			};
		}

		private static string DepthInteriorityFallbackGlyph(string kind)
		{
			return NormalizeDepthKind(kind) switch
			{
				"analysis" => "A",
				"concern" or "tom" => "C",
				"emotion" or "emotional" => "H",
				"future" or "plan" => "F",
				"guard" or "restraint" => "G",
				"memory" or "memory_echo" => "M",
				"observe" or "signal" or "vision" => "O",
				"pending" or "waiting" => "...",
				"settled" => "S",
				"technical" or "tech" or "architecture" or "repair" => "T",
				"uncertain" or "unknown" => "?",
				_ => "*",
			};
		}

		private static Color DepthInteriorityFallbackColor(string kind)
		{
			return NormalizeDepthKind(kind) switch
			{
				"analysis" => new Color(0.56f, 0.42f, 0.96f, 0.92f),
				"concern" or "tom" => new Color(0.72f, 0.42f, 0.96f, 0.92f),
				"emotion" or "emotional" => new Color(0.98f, 0.36f, 0.58f, 0.94f),
				"future" or "plan" => new Color(0.98f, 0.60f, 0.28f, 0.92f),
				"guard" or "restraint" => new Color(0.34f, 0.76f, 0.58f, 0.92f),
				"memory" or "memory_echo" => new Color(0.28f, 0.70f, 0.88f, 0.92f),
				"technical" or "tech" or "architecture" or "repair" => new Color(0.64f, 0.50f, 0.96f, 0.92f),
				_ => new Color(0.96f, 0.34f, 0.62f, 0.92f),
			};
		}

		private void ApplyDepthV2Priorities(JsonElement root)
		{
			var items = DefaultDepthPriorityItems();
			if (root.TryGetProperty("priorities", out var priorities) && priorities.ValueKind == JsonValueKind.Array)
			{
				var live = new List<DepthPriorityItem>();
				foreach (var raw in priorities.EnumerateArray())
				{
					if (raw.ValueKind != JsonValueKind.Object)
						continue;
					string key = NormalizeDepthKind(JsonText(raw, "key", ""));
					string label = JsonText(raw, "label", DepthPriorityDefaultLabel(key));
					float score = NormalizeDepthPriorityScore(JsonFloat(raw, "score", 0f));
					AddDepthPriorityItem(live, key, label, score);
				}

				// Payload thường đã sort theo score. Giữ thứ tự đó để panel phản ánh
				// "ưu tiên hiện tại" thật, rồi bù các loại còn thiếu để layout đủ 5 dòng.
				if (live.Count > 0)
				{
					foreach (var fallback in DefaultDepthPriorityItems())
						AddDepthPriorityItem(live, fallback.Key, fallback.Label, fallback.Score);
					items = live;
				}
			}

			string focusMode = DepthV2FocusMode(root);
			ApplyDepthPriorityRows(items, focusMode);
		}

		private void ApplyLegacyDepthPriorities(JsonElement root)
		{
			if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
				return;
			if (!depth.TryGetProperty("priorities", out var priorities) || priorities.ValueKind != JsonValueKind.Array)
				return;

			var items = new List<DepthPriorityItem>();
			foreach (var raw in priorities.EnumerateArray())
			{
				if (raw.ValueKind != JsonValueKind.Object)
					continue;
				string key = NormalizeDepthKind(JsonText(raw, "key", JsonText(raw, "label", "casual")));
				AddDepthPriorityItem(
					items,
					key,
					JsonText(raw, "label", DepthPriorityDefaultLabel(key)),
					NormalizeDepthPriorityScore(JsonFloat(raw, "score", 0f)));
			}
			foreach (var fallback in DefaultDepthPriorityItems())
				AddDepthPriorityItem(items, fallback.Key, fallback.Label, fallback.Score);
			ApplyDepthPriorityRows(items, "legacy");
		}

		private void ApplyDepthPriorityDefaults(string focusMode)
		{
			ApplyDepthPriorityRows(DefaultDepthPriorityItems(), focusMode);
		}

		private void ApplyDepthPriorityRows(List<DepthPriorityItem> items, string focusMode)
		{
			for (int i = 0; i < _depthPriorityRows.Count; i++)
			{
				var row = _depthPriorityRows[i];
				var item = i < items.Count ? items[i] : null;
				bool visible = item != null;
				row.Root.Visible = visible;
				if (!visible)
					continue;

				string key = NormalizeDepthKind(item.Key);
				Color color = DepthPriorityColor(key);
				UpdateDepthLabelText(row.IconLabel, DepthPriorityGlyph(key));
				row.IconLabel.AddThemeColorOverride("font_color", color);
				UpdateDepthLabelText(row.TitleLabel, DepthPriorityDisplayLabel(key, item.Label));
				ApplyDepthPrioritySegments(row, NormalizeDepthPriorityScore(item.Score), color);
				UpdateDepthLabelText(row.PercentLabel, $"{Mathf.RoundToInt(NormalizeDepthPriorityScore(item.Score) * 100f)}%");
			}

			UpdateDepthLabelText(_depthPriorityFocusModeLabel, string.IsNullOrWhiteSpace(focusMode) ? "attentive" : NormalizeDepthKind(focusMode));
			UpdateDepthLabelText(_depthPriorityFooterGlyphLabel, "✦   ♡   ✦");
		}

		private void ApplyDepthPrioritySegments(DepthPriorityRowView row, float score, Color color)
		{
			float safeScore = NormalizeDepthPriorityScore(score);
			int active = safeScore <= 0f ? 0 : Mathf.Clamp(Mathf.CeilToInt(safeScore * row.Segments.Count), 1, row.Segments.Count);
			for (int i = 0; i < row.Segments.Count; i++)
			{
				bool filled = i < active;
				row.Segments[i].AddThemeStyleboxOverride("panel", new StyleBoxFlat
				{
					BgColor = filled ? color : new Color(1f, 0.82f, 0.90f, 0.22f),
					CornerRadiusTopLeft = 1,
					CornerRadiusTopRight = 1,
					CornerRadiusBottomLeft = 1,
					CornerRadiusBottomRight = 1,
				});
			}
		}

		private static List<DepthPriorityItem> DefaultDepthPriorityItems() => new()
		{
			new DepthPriorityItem { Key = "technical", Label = "Architecture / Technical", Score = 0f },
			new DepthPriorityItem { Key = "humor", Label = "Humor / Playfulness", Score = 0f },
			new DepthPriorityItem { Key = "repair", Label = "Repair / Help", Score = 0f },
			new DepthPriorityItem { Key = "emotional", Label = "Emotional Reading", Score = 0f },
			new DepthPriorityItem { Key = "casual", Label = "Small Talk / Casual", Score = 0f },
		};

		private static void AddDepthPriorityItem(List<DepthPriorityItem> items, string key, string label, float score)
		{
			string safeKey = NormalizeDepthPriorityKey(key);
			foreach (var existing in items)
			{
				if (NormalizeDepthPriorityKey(existing.Key) == safeKey)
					return;
			}

			items.Add(new DepthPriorityItem
			{
				Key = safeKey,
				Label = string.IsNullOrWhiteSpace(label) ? DepthPriorityDefaultLabel(safeKey) : TrimDepthUiText(label, 40),
				Score = NormalizeDepthPriorityScore(score),
			});
		}

		private static string DepthV2FocusMode(JsonElement root)
		{
			if (root.TryGetProperty("status", out var status)
				&& status.ValueKind == JsonValueKind.Object)
			{
				string value = JsonText(status, "focus_mode", "");
				if (!string.IsNullOrWhiteSpace(value))
					return value;
			}

			if (root.TryGetProperty("context", out var context)
				&& context.ValueKind == JsonValueKind.Object)
				return JsonText(context, "focus_mode", "attentive");

			return "attentive";
		}

		private static float NormalizeDepthPriorityScore(float score)
		{
			if (score > 1f)
				score /= 100f;
			return Mathf.Clamp(score, 0f, 1f);
		}

		private static string NormalizeDepthPriorityKey(string raw)
		{
			string key = NormalizeDepthKind(raw);
			if (key.Contains("architecture") || key.Contains("technical") || key.Contains("code") || key.Contains("debug"))
				return "technical";
			if (key.Contains("humor") || key.Contains("play"))
				return "humor";
			if (key.Contains("repair") || key.Contains("help") || key.Contains("fix"))
				return "repair";
			if (key.Contains("emotion") || key.Contains("feeling"))
				return "emotional";
			if (key.Contains("casual") || key.Contains("small"))
				return "casual";
			return string.IsNullOrWhiteSpace(key) ? "casual" : key;
		}

		private static string DepthPriorityDisplayLabel(string key, string rawLabel)
		{
			string label = TrimDepthUiText(rawLabel, 38);
			return string.IsNullOrWhiteSpace(label) ? DepthPriorityDefaultLabel(key) : label;
		}

		private static string DepthPriorityDefaultLabel(string key)
		{
			return NormalizeDepthPriorityKey(key) switch
			{
				"technical" => "Architecture / Technical",
				"humor" => "Humor / Playfulness",
				"repair" => "Repair / Help",
				"emotional" => "Emotional Reading",
				"casual" => "Small Talk / Casual",
				_ => HumanizeDepthPhrase(key),
			};
		}

		private static string DepthPriorityGlyph(string key)
		{
			return NormalizeDepthPriorityKey(key) switch
			{
				"technical" => "♜",
				"humor" => "☺",
				"repair" => "⚒",
				"emotional" => "♥",
				"casual" => "▱",
				_ => "✦",
			};
		}

		private static Color DepthPriorityColor(string key)
		{
			return NormalizeDepthPriorityKey(key) switch
			{
				"technical" => new Color(0.98f, 0.34f, 0.62f, 0.96f),
				"humor" => new Color(1.00f, 0.58f, 0.42f, 0.96f),
				"repair" => new Color(0.73f, 0.42f, 0.96f, 0.94f),
				"emotional" => new Color(1.00f, 0.62f, 0.42f, 0.94f),
				"casual" => new Color(0.42f, 0.76f, 0.68f, 0.94f),
				_ => new Color(0.92f, 0.34f, 0.56f, 0.94f),
			};
		}

		private void ApplyDepthV2SignalTimeline(JsonElement root)
		{
			var items = new List<DepthSignalTimelineItem>();
			if (root.TryGetProperty("signal_timeline", out var timeline) && timeline.ValueKind == JsonValueKind.Array)
				CollectDepthSignalTimeline(timeline, items);

			if (items.Count == 0 && root.TryGetProperty("signal_log", out var signalLog) && signalLog.ValueKind == JsonValueKind.Array)
				CollectDepthSignalTimeline(signalLog, items);

			if (items.Count == 0 && root.TryGetProperty("journal", out var journal) && journal.ValueKind == JsonValueKind.Array)
				CollectDepthSignalTimeline(journal, items);

			if (items.Count == 0)
			{
				ApplyDepthSignalTimelineEmpty("timeline chờ tín hiệu ✦");
				return;
			}

			ApplyDepthSignalTimelineItems(items, $"timeline: {Math.Min(items.Count, _depthSignalTimelineRows.Count)} mốc ✦");
		}

		private void ApplyLegacyDepthSignalTimeline(JsonElement root)
		{
			if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
				return;

			var items = new List<DepthSignalTimelineItem>();
			if (depth.TryGetProperty("signal_log", out var signalLog) && signalLog.ValueKind == JsonValueKind.Array)
				CollectDepthSignalTimeline(signalLog, items);
			if (items.Count == 0 && depth.TryGetProperty("journal", out var journal) && journal.ValueKind == JsonValueKind.Array)
				CollectDepthSignalTimeline(journal, items);

			if (items.Count > 0)
				ApplyDepthSignalTimelineItems(items, "legacy timeline ✦");
		}

		private void CollectDepthSignalTimeline(JsonElement source, List<DepthSignalTimelineItem> items)
		{
			foreach (var raw in source.EnumerateArray())
			{
				if (raw.ValueKind != JsonValueKind.Object)
					continue;

				string text = JsonText(raw, "text", "");
				if (string.IsNullOrWhiteSpace(text))
					text = JsonText(raw, "message", "");
				if (string.IsNullOrWhiteSpace(text))
					text = JsonText(raw, "kind", "");

				AddDepthSignalTimelineItem(
					items,
					time: JsonText(raw, "time", ""),
					kind: JsonText(raw, "kind", JsonText(raw, "source", "signal")),
					text: text);
			}
		}

		private static void AddDepthSignalTimelineItem(List<DepthSignalTimelineItem> items, string time, string kind, string text)
		{
			string safeText = TrimDepthUiText(text, 82);
			if (string.IsNullOrWhiteSpace(safeText))
				return;
			foreach (var item in items)
			{
				if (string.Equals(item.Text, safeText, StringComparison.OrdinalIgnoreCase))
					return;
			}

			items.Add(new DepthSignalTimelineItem
			{
				Time = TrimDepthUiText(time, 16),
				Kind = NormalizeDepthKind(kind),
				Text = safeText,
			});
		}

		private void ApplyDepthSignalTimelineItems(List<DepthSignalTimelineItem> items, string status)
		{
			int visibleCount = Math.Min(items.Count, _depthSignalTimelineRows.Count);
			for (int i = 0; i < _depthSignalTimelineRows.Count; i++)
			{
				var row = _depthSignalTimelineRows[i];
				bool visible = i < visibleCount;
				row.Root.Visible = visible;
				if (!visible)
					continue;

				var item = items[i];
				Color color = DepthSignalTimelineColor(item.Kind);
				row.Dot.AddThemeStyleboxOverride("panel", new StyleBoxFlat
				{
					BgColor = color,
					CornerRadiusTopLeft = 4,
					CornerRadiusTopRight = 4,
					CornerRadiusBottomLeft = 4,
					CornerRadiusBottomRight = 4,
				});
				UpdateDepthLabelText(row.TimeLabel, string.IsNullOrWhiteSpace(item.Time) ? "--:--:--" : item.Time);
				UpdateDepthLabelText(row.TextLabel, TrimDepthUiText(item.Text, 62));
			}

			UpdateDepthLabelText(_depthSignalTimelineStatusLabel, string.IsNullOrWhiteSpace(status) ? "timeline đã nhận ✦" : status);
		}

		private void ApplyDepthSignalTimelineEmpty(string status)
		{
			foreach (var row in _depthSignalTimelineRows)
				row.Root.Visible = false;
			UpdateDepthLabelText(_depthSignalTimelineStatusLabel, status);
		}

		private static Color DepthSignalTimelineColor(string kind)
		{
			return NormalizeDepthKind(kind) switch
			{
				"context" or "tom" or "tom_read" => new Color(0.98f, 0.34f, 0.62f, 0.94f),
				"topic" or "priority" or "technical" => new Color(0.96f, 0.48f, 0.70f, 0.94f),
				"recurrence" or "concern" => new Color(0.74f, 0.42f, 0.96f, 0.94f),
				"affect" or "emotion" => new Color(1.00f, 0.58f, 0.42f, 0.94f),
				"surface" or "signal" => new Color(0.42f, 0.76f, 0.68f, 0.94f),
				_ => new Color(0.92f, 0.34f, 0.56f, 0.92f),
			};
		}

	private void ApplyLegacyDepthAffect(JsonElement root)
	{
		if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
			return;
		if (!depth.TryGetProperty("affect", out var affect) || affect.ValueKind != JsonValueKind.Object)
			return;

		bool live = JsonBool(affect, "live", false);
		float valence = JsonFloat(affect, "valence", 0f);
		float arousal = JsonFloat(affect, "arousal", 0.3f);
		string stance = JsonText(affect, "stance", "");

		string headline = live ? LocalizeDepthAffectHeadline(LegacyAffectHeadline(valence, arousal)) : "Ổn định";
		string subtext = live ? LocalizeDepthAffectSubtext(LegacyAffectSubtext(valence, arousal, stance)) : "Đang lắng nghe yên tĩnh.";
		float stability = Mathf.Clamp((1f - arousal) * 0.78f, 0f, 1f);

		ApplyDepthAffectContent(headline, subtext, stability);
	}

	private void ApplyLegacyDepthEmotionJournal(JsonElement root)
	{
		if (!root.TryGetProperty("depth", out var depth) || depth.ValueKind != JsonValueKind.Object)
			return;
		if (!depth.TryGetProperty("affect", out var affect) || affect.ValueKind != JsonValueKind.Object)
			return;

		float valence = Mathf.Clamp(JsonFloat(affect, "valence", 0f), -1f, 1f);
		float arousal = Mathf.Clamp(JsonFloat(affect, "arousal", 0.3f), 0f, 1f);
		float latestValue = Mathf.Clamp((valence + 1f) * 0.5f, 0f, 1f);
		float stability = Mathf.Clamp((1f - arousal) * 0.78f, 0f, 1f);

		ApplyDepthEmotionJournalContent(BuildDepthEmotionFallbackValues(latestValue, stability), stability, latestValue);
	}

	private void ApplyDepthAffectContent(string headline, string subtext, float stability)
	{
		string safeHeadline = string.IsNullOrWhiteSpace(headline) ? "Bình tĩnh" : headline.Trim();
		string safeSubtext = string.IsNullOrWhiteSpace(subtext) ? "Thoải mái, sẵn sàng trò chuyện." : subtext.Trim();
		float clampedStability = Mathf.Clamp(stability, 0f, 1f);

		UpdateDepthLabelText(_depthAffectHeadlineLabel, safeHeadline);
		UpdateDepthLabelText(_depthAffectSubtextLabel, safeSubtext);

		if (_depthAffectStabilityBar != null)
			_depthAffectStabilityBar.Value = clampedStability;
		UpdateDepthLabelText(_depthAffectStabilityPctLabel, $"{Mathf.RoundToInt(clampedStability * 100f)}%");
	}

	private void ApplyDepthEmotionJournalDefaults()
	{
		ApplyDepthEmotionJournalContent(BuildDepthEmotionFallbackValues(0.58f, 0.72f), 0.72f, 0.58f);
	}

	private void ApplyDepthEmotionJournalContent(List<float> values, float stability, float latestValue)
	{
		var safeValues = values == null || values.Count < 2
			? BuildDepthEmotionFallbackValues(latestValue, stability)
			: values;

		_depthEmotionSparkline?.SetValues(safeValues);
		UpdateDepthLabelText(_depthEmotionLeftLabel, DepthEmotionStabilityLabel(stability));
		UpdateDepthLabelText(_depthEmotionRightLabel, DepthEmotionMoodLabel(latestValue));
	}

	private static List<float> BuildDepthEmotionFallbackValues(float center, float stability)
	{
		float safeCenter = Mathf.Clamp(center, 0.18f, 0.82f);
		float wave = Mathf.Lerp(0.105f, 0.030f, Mathf.Clamp(stability, 0f, 1f));
		var values = new List<float>();
		for (int i = 0; i < 19; i++)
		{
			float slow = Mathf.Sin(i * 1.18f) * wave;
			float quick = Mathf.Sin(i * 2.75f + 0.45f) * wave * 0.42f;
			values.Add(Mathf.Clamp(safeCenter + slow + quick, 0.06f, 0.94f));
		}
		return values;
	}

	private static string DepthEmotionStabilityLabel(float stability)
	{
		float safe = Mathf.Clamp(stability, 0f, 1f);
		if (safe >= 0.70f)
			return "ổn định";
		if (safe >= 0.45f)
			return "dao động nhẹ";
		return "nhiễu cảm xúc";
	}

	private static string DepthEmotionMoodLabel(float latestValue)
	{
		float safe = Mathf.Clamp(latestValue, 0f, 1f);
		if (safe >= 0.62f)
			return "tích cực";
		if (safe >= 0.54f)
			return "hơi tích cực";
		if (safe <= 0.38f)
			return "hơi nặng";
		return "trung tính";
	}

	private void UpdateDepthLabelText(Label label, string text)
	{
		if (label == null || label.Text == text)
			return;

		label.Text = text;
		label.Modulate = new Color(1f, 1f, 1f, 0.72f);
		var tween = CreateTween();
		tween.TweenProperty(label, "modulate", Colors.White, 0.22f);
	}

	private static string JsonText(JsonElement obj, string key, string fallback = "")
	{
		if (obj.ValueKind == JsonValueKind.Object
			&& obj.TryGetProperty(key, out var el)
			&& el.ValueKind == JsonValueKind.String)
		{
			return el.GetString() ?? fallback;
		}

		return fallback;
	}

	private static float JsonFloat(JsonElement obj, string key, float fallback = 0f)
	{
		if (obj.ValueKind == JsonValueKind.Object
			&& obj.TryGetProperty(key, out var el))
		{
			if (el.ValueKind == JsonValueKind.Number && el.TryGetSingle(out float direct))
				return direct;
			if (el.ValueKind == JsonValueKind.String && float.TryParse(el.GetString(), out float parsed))
				return parsed;
		}

		return fallback;
	}

	private static bool JsonBool(JsonElement obj, string key, bool fallback = false)
	{
		if (obj.ValueKind == JsonValueKind.Object
			&& obj.TryGetProperty(key, out var el))
		{
			if (el.ValueKind == JsonValueKind.True)
				return true;
			if (el.ValueKind == JsonValueKind.False)
				return false;
		}

		return fallback;
	}

	private static int JsonInt(JsonElement obj, string key, int fallback = 0)
	{
		if (obj.ValueKind == JsonValueKind.Object
			&& obj.TryGetProperty(key, out var el))
		{
			if (el.ValueKind == JsonValueKind.Number && el.TryGetInt32(out int direct))
				return direct;
			if (el.ValueKind == JsonValueKind.String && int.TryParse(el.GetString(), out int parsed))
				return parsed;
		}

		return fallback;
	}

	private static string DepthV2TopBelief(JsonElement userModel)
	{
		if (userModel.ValueKind != JsonValueKind.Object
			|| !userModel.TryGetProperty("beliefs", out var beliefs)
			|| beliefs.ValueKind != JsonValueKind.Array)
			return "";

		string bestClaim = "";
		float bestScore = -1f;
		foreach (var raw in beliefs.EnumerateArray())
		{
			if (raw.ValueKind != JsonValueKind.Object)
				continue;
			string claim = JsonText(raw, "claim", "");
			if (string.IsNullOrWhiteSpace(claim))
				continue;
			float confidence = Mathf.Clamp(JsonFloat(raw, "confidence", 0f), 0f, 1f);
			float recurrence = Mathf.Clamp(JsonFloat(raw, "recurrence", 1f) / 6f, 0f, 1f);
			float score = confidence * 0.70f + recurrence * 0.30f;
			if (score <= bestScore)
				continue;
			bestScore = score;
			bestClaim = claim;
		}
		return bestClaim;
	}

	private static float DepthV2AttachmentFallback(JsonElement root)
	{
		if (root.TryGetProperty("n2", out var n2)
			&& n2.ValueKind == JsonValueKind.Object
			&& n2.TryGetProperty("attachment", out var attachment)
			&& attachment.ValueKind == JsonValueKind.Object)
			return Mathf.Clamp(JsonFloat(attachment, "value", 0f), 0f, 1f);

		return 0f;
	}

	private static float DepthLegacyAttachmentFallback(JsonElement depth)
	{
		if (depth.TryGetProperty("n2", out var n2)
			&& n2.ValueKind == JsonValueKind.Object
			&& n2.TryGetProperty("attachment", out var attachment)
			&& attachment.ValueKind == JsonValueKind.Object)
			return Mathf.Clamp(JsonFloat(attachment, "value", 0f), 0f, 1f);

		return 0f;
	}

	private static string StripTomPrefix(string raw)
	{
		string text = TrimDepthUiText(raw, 180);
		if (text.StartsWith("tom_read:", StringComparison.OrdinalIgnoreCase))
			text = text["tom_read:".Length..].Trim();
		return text;
	}

	private static string TrimDepthUiText(string raw, int maxChars)
	{
		string text = string.Join(" ", (raw ?? "").Split(' ', '\t', '\r', '\n')).Trim();
		if (maxChars <= 0 || text.Length <= maxChars)
			return text;
		return text[..Math.Max(0, maxChars - 1)].TrimEnd() + "…";
	}

	private static string LocalizeDepthExpressionStance(string raw, float want, float suppress, float allowed)
	{
		switch (NormalizeDepthPhrase(raw))
		{
			case "precise direct":
				return "rõ và thẳng";
			case "guarded tender":
				return "dịu mà giữ";
			case "reserved direct":
				return "cân bằng";
			case "held back":
				return "giữ lại";
			case "open":
				return "mở";
		}

		if (allowed >= 0.72f && suppress <= 0.22f)
			return "mở";
		if (suppress >= 0.52f && allowed <= 0.40f)
			return "giữ lại";
		if (want >= 0.58f && allowed >= 0.52f)
			return "muốn nói";
		return "cân bằng";
	}

	private static string LegacyAffectHeadline(float valence, float arousal)
	{
		if (arousal >= 0.68f)
			return valence >= 0.10f ? "energized" : "tense";
		if (valence >= 0.22f)
			return "calm";
		if (valence <= -0.18f)
			return "tense";
		return "steady";
	}

	private static string LegacyAffectSubtext(float valence, float arousal, string stance)
	{
		if (!string.IsNullOrWhiteSpace(stance) && stance.Contains("tender", StringComparison.OrdinalIgnoreCase))
			return "warm and open to gentle conversation";
		if (arousal >= 0.68f)
			return "thinking quickly, with more inner movement";
		if (valence <= -0.18f)
			return "holding a little tension while listening";
		return "listening quietly";
	}

	private static string LocalizeDepthAffectHeadline(string raw)
	{
		return NormalizeDepthPhrase(raw) switch
		{
			"calm" => "Bình tĩnh",
			"steady" => "Ổn định",
			"light" => "Nhẹ lòng",
			"energized" => "Tỉnh và nhanh",
			"tense" => "Hơi căng",
			_ => HumanizeDepthPhrase(raw),
		};
	}

		private static string LocalizeDepthAffectSubtext(string raw)
		{
			return NormalizeDepthPhrase(raw) switch
		{
			"listening closely" => "Thoải mái, sẵn sàng trò chuyện.",
			"listening quietly" => "Đang lắng nghe và suy nghĩ cùng Ngài.",
			"live affect fallback" => "Cảm xúc đang được đọc trực tiếp.",
			"warm and open to gentle conversation" => "Ấm áp và sẵn sàng trò chuyện nhẹ nhàng.",
			"thinking quickly, with more inner movement" => "Đầu óc đang chạy nhanh hơn một chút.",
			"holding a little tension while listening" => "Vẫn đang lắng nghe, nhưng có chút căng nhẹ.",
			"fallback" => "Đang cập nhật cảm xúc.",
			_ => HumanizeDepthPhrase(raw),
			};
		}

		private static string NormalizeDepthKind(string raw) =>
			// Kind là contract kỹ thuật (`memory_echo`, `technical`, ...), nên giữ
			// dạng snake_case để map icon ổn định. Khác với phrase UI, chỗ này không
			// humanize chữ mà chỉ dọn khoảng trắng/dấu gạch.
			NormalizeDepthPhrase(raw).Replace(" ", "_").Replace("-", "_");

		private static string NormalizeDepthPhrase(string raw) =>
			string.IsNullOrWhiteSpace(raw) ? "" : raw.Trim().Replace("_", " ").ToLowerInvariant();

	private static string HumanizeDepthPhrase(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return "";

		string text = raw.Trim().Replace("_", " ");
		if (text.Length == 0)
			return "";
		if (text.Length == 1)
			return text.ToUpperInvariant();
		return char.ToUpperInvariant(text[0]) + text[1..];
	}
}
