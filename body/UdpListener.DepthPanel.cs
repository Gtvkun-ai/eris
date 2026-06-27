using Godot;
using System;
using System.Text.Json;

public partial class UdpListener : Node2D
{
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
	private static readonly Rect2 SlotEmotionJournal = RectPx(1004f, 719f, 459f, 249f);
	private static readonly Rect2 SlotClose = RectPx(1334f, 40f, 132f, 53f);

	private static Rect2 RectPx(float x, float y, float width, float height) =>
		new(
			x / DepthPanelArtworkSize.X,
			y / DepthPanelArtworkSize.Y,
			width / DepthPanelArtworkSize.X,
			height / DepthPanelArtworkSize.Y);

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

	private void BuildDepthAffectFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthAffectFramePath, SlotAffect);

	private void BuildDepthTomFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthTomFramePath, SlotTom);

	private void BuildDepthSelfContinuityFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthSelfContinuityFramePath, SlotSelfContinuity);

	private void BuildDepthCollabFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthCollabFramePath, SlotCollab);

	private void BuildDepthInteriorityFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthInteriorityFramePath, SlotInteriority);

	private void BuildDepthPrioritiesFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthPrioritiesFramePath, SlotPriorities);

	private void BuildDepthSignalLogFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthSignalLogFramePath, SlotSignalLog);

	private void BuildDepthContextFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthContextFramePath, SlotContext);

	private void BuildDepthEmotionJournalFrame(Control parent) =>
		AddDepthFrameImage(parent, DepthEmotionJournalFramePath, SlotEmotionJournal);

	private void UpdateDepthContentRootTransform()
	{
		if (_depthPanelContentRoot == null || _depthPanel == null)
			return;

		_depthPanelContentRoot.Position = Vector2.Zero;
		_depthPanelContentRoot.Rotation = 0f;
		_depthPanelContentRoot.Scale = new Vector2(DepthPanelInnerContentScale, DepthPanelInnerContentScale);
		_depthPanelContentRoot.PivotOffset = _depthPanel.Size * 0.5f;
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

		// Panel chiều sâu đang ở chế độ khung tĩnh để chờ nối UI mới.
	}
}
