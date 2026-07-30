using Godot;
using System;
using System.IO;
using System.Text;
using System.Text.Json;

public partial class UdpListener
{
	private const string BodyRendererStatePath = "user://body_renderer_mode.txt";
	private Button _contextBodyModeButton;
	private Live2DBodyManager _live2DManager;
	private PacketPeerUdp _live2DForward = new();
	private bool _isLive2DMode;
	private bool _live2DInitialized;
	private Rect2I _live2DWindowRectScreen;
	private bool _hasLive2DWindowRect;
	private Color _spriteSelfModulateBeforeLive2D = Colors.White;
	private bool _capturedSpriteVisual;
	private Vector2 _bodyPositionBeforeLive2D;

	[ExportGroup("Live2D Body")]
	[Export] public bool EnableLive2DSwitch = true;
	[Export] public string Live2DModelPath = "src/assets/live2d/infj/infj.model3.json";
	[Export(PropertyHint.Range, "1,65535,1")] public int Live2DStagePort = 4252;
	[Export] public bool RememberBodyRendererMode = true;
	[Export(PropertyHint.Range, "320,1600,1")] public int Live2DWindowWidth = 520;
	[Export(PropertyHint.Range, "480,1800,1")] public int Live2DWindowHeight = 900;
	[Export(PropertyHint.Range, "0.20,0.50,0.01")] public float Live2DBubbleAnchorY = 0.34f;
	[Export(PropertyHint.Range, "0.05,0.75,0.01")] public float Live2DBubbleSideAnchorY = 0.18f;
	[Export(PropertyHint.Range, "8,96,1")] public float Live2DBubbleGap = 24f;

	private void EnsureLive2DContextButton(VBoxContainer container)
	{
		if (!EnableLive2DSwitch || container == null)
			return;
		if (_contextBodyModeButton == null)
		{
			_contextBodyModeButton = new Button { Name = "BodyModeButton" };
			container.AddChild(_contextBodyModeButton);
			int insertIndex = _contextExitButton != null
				? _contextExitButton.GetIndex()
				: (_contextCloseButton != null ? _contextCloseButton.GetIndex() : container.GetChildCount() - 1);
			container.MoveChild(_contextBodyModeButton, Mathf.Max(0, insertIndex));
		}
		ConfigureContextMenuButton(
			_contextBodyModeButton,
			_isLive2DMode ? "Chuyển về 2D" : "Chuyển sang Live2D",
			"res://asset/Resource/emotion.png");
	}

	private void InitializeLive2DMode()
	{
		if (_live2DInitialized)
			return;
		_live2DInitialized = true;
		_live2DForward.ConnectToHost("127.0.0.1", Math.Clamp(Live2DStagePort, 1, 65535));
		_live2DManager = new Live2DBodyManager(OnLive2DProcessExited);
		if (_contextBodyModeButton != null)
			_contextBodyModeButton.Pressed += OnContextBodyModePressed;
		UpdateBodyModeButton();

		if (RememberBodyRendererMode && ReadSavedBodyRendererMode() == "live2d")
			CallDeferred(nameof(RestoreSavedLive2DMode));
	}

	private void RestoreSavedLive2DMode()
	{
		SetBodyRendererMode(true, persist: false);
	}

	private void OnContextBodyModePressed()
	{
		SetBodyRendererMode(!_isLive2DMode, persist: true);
	}

	private void SetBodyRendererMode(bool useLive2D, bool persist)
	{
		if (!EnableLive2DSwitch)
			useLive2D = false;

		if (useLive2D)
		{
			if (_isLive2DMode && (_live2DManager?.IsRunning ?? false))
			{
				CloseCharacterContextMenu();
				return;
			}

			_bodyPositionBeforeLive2D = _body?.GlobalPosition ?? Vector2.Zero;
			if (!_hasLive2DWindowRect)
			{
				_live2DWindowRectScreen = ResolveInitialLive2DWindowRect();
				_hasLive2DWindowRect = true;
			}

			bool resident = _live2DManager?.IsRunning ?? false;
			if (!resident && !(_live2DManager?.Start(
				PythonExecutable,
				Live2DModelPath,
				Live2DStagePort,
				_live2DWindowRectScreen.Position.X,
				_live2DWindowRectScreen.Position.Y,
				_live2DWindowRectScreen.Size.X,
				_live2DWindowRectScreen.Size.Y) ?? false))
			{
				_isLive2DMode = false;
				Restore2DSpriteVisual();
				UpdateBodyModeButton();
				_label.Text = "Không mở được Live2D. Chạy src/install_live2d_body.bat rồi thử lại.";
				CloseCharacterContextMenu();
				return;
			}

			_isLive2DMode = true;
			SyncSpeechBubbleMode();
			ConfigureLive2DSpeechBubbleVisual();
			ConfigureLegacySpeechBubbleVisual();
			HideOnly2DSpriteVisual();
			if (resident)
				SendLive2DControl("set_visibility", visible: true);
			SyncLive2DBodyAnchor();
			RunLogger.Log($"[BodyMode] 2D -> Live2D | resident={resident} | bubble giữ ở Godot overlay");
		}
		else
		{
			bool wasLive2D = _isLive2DMode;
			_isLive2DMode = false;
			SyncSpeechBubbleMode();
			ConfigureLive2DSpeechBubbleVisual();
			ConfigureLegacySpeechBubbleVisual();
			if (_live2DManager?.IsRunning ?? false)
				SendLive2DControl("set_visibility", visible: false);
			Restore2DSpriteVisual();
			if (_body != null)
				_body.GlobalPosition = _bodyPositionBeforeLive2D;
			if (wasLive2D)
				RunLogger.Log("[BodyMode] Live2D -> 2D | renderer hidden, process giữ thường trú");
		}

		if (persist && RememberBodyRendererMode)
			SaveBodyRendererMode(_isLive2DMode ? "live2d" : "2d");
		UpdateBodyModeButton();
		CloseCharacterContextMenu();
	}

	private Rect2I ResolveInitialLive2DWindowRect()
	{
		int width = Math.Clamp(Live2DWindowWidth, 320, 1600);
		int height = Math.Clamp(Live2DWindowHeight, 480, 1800);
		Vector2I overlayScreenPosition = DisplayServer.WindowGetPosition();
		Vector2 bodyPosition = _body?.GlobalPosition ?? GetViewportRect().Size * 0.5f;
		int x = overlayScreenPosition.X + Mathf.RoundToInt(bodyPosition.X - width * 0.5f);
		int y = overlayScreenPosition.Y + Mathf.RoundToInt(bodyPosition.Y + _spriteHalfSize.Y - height);

		int screen = DisplayServer.WindowGetCurrentScreen();
		Vector2I screenPosition = DisplayServer.ScreenGetPosition(screen);
		Vector2I screenSize = DisplayServer.ScreenGetSize(screen);
		x = Math.Clamp(x, screenPosition.X, Math.Max(screenPosition.X, screenPosition.X + screenSize.X - width));
		y = Math.Clamp(y, screenPosition.Y, Math.Max(screenPosition.Y, screenPosition.Y + screenSize.Y - height));
		return new Rect2I(x, y, width, height);
	}

	private void HideOnly2DSpriteVisual()
	{
		if (_body != null)
			_body.Visible = true;
		if (_monika == null)
			return;
		if (!_capturedSpriteVisual)
		{
			_spriteSelfModulateBeforeLive2D = _monika.SelfModulate;
			_capturedSpriteVisual = true;
		}
		Color original = _spriteSelfModulateBeforeLive2D;
		_monika.SelfModulate = new Color(original.R, original.G, original.B, 0f);
	}

	private void Restore2DSpriteVisual()
	{
		if (_body != null)
			_body.Visible = true;
		if (_monika != null && _capturedSpriteVisual)
			_monika.SelfModulate = _spriteSelfModulateBeforeLive2D;
		_capturedSpriteVisual = false;
	}

	private void UpdateBodyModeButton()
	{
		if (_contextBodyModeButton == null)
			return;
		_contextBodyModeButton.Text = _isLive2DMode ? "Chuyển về 2D" : "Chuyển sang Live2D";
		_contextBodyModeButton.TooltipText = _isLive2DMode
			? "Ẩn Live2D và hiện lại sprite 2D; renderer không bị khởi động lại."
			: "Hiện renderer Live2D thường trú; chỉ lần mở đầu tiên mới phải nạp model.";
	}

	private void OnLive2DProcessExited(int exitCode)
	{
		// Process.Exited chạy ở thread hệ thống; mọi thao tác Godot phải quay về main thread.
		CallDeferred(nameof(HandleLive2DProcessExited), exitCode);
	}

	private void HandleLive2DProcessExited(int exitCode)
	{
		if (!_isLive2DMode)
			return;
		_isLive2DMode = false;
		SyncSpeechBubbleMode();
		Restore2DSpriteVisual();
		_hasLive2DWindowRect = false;
		if (_body != null)
			_body.GlobalPosition = _bodyPositionBeforeLive2D;
		UpdateBodyModeButton();
		if (RememberBodyRendererMode)
			SaveBodyRendererMode("2d");
		if (exitCode != 0)
			_label.Text = "Live2D đã dừng; Eris tự quay về body 2D. Xem log để biết lỗi renderer.";
		RunLogger.Log($"[BodyMode] Renderer Live2D thoát, fallback 2D (code={exitCode}).");
	}

	private bool HandleLive2DControlPacket(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw) || !raw.Contains("eris.body.control", StringComparison.Ordinal))
			return false;
		try
		{
			using JsonDocument document = JsonDocument.Parse(raw);
			JsonElement root = document.RootElement;
			if (root.ValueKind != JsonValueKind.Object
				|| !root.TryGetProperty("protocol", out var protocol)
				|| !string.Equals(protocol.GetString(), "eris.body.control", StringComparison.Ordinal)
				|| !root.TryGetProperty("type", out var typeElement))
				return false;

			string type = typeElement.GetString() ?? "";
			if (string.Equals(type, "open_context_menu", StringComparison.Ordinal))
			{
				float screenX = ReadJsonFloat(root, "screen_x");
				float screenY = ReadJsonFloat(root, "screen_y");
				OpenContextMenuFromLive2D(screenX, screenY);
				return true;
			}
			if (string.Equals(type, "window_geometry", StringComparison.Ordinal))
			{
				int x = Mathf.RoundToInt(ReadJsonFloat(root, "screen_x"));
				int y = Mathf.RoundToInt(ReadJsonFloat(root, "screen_y"));
				int width = Math.Max(1, Mathf.RoundToInt(ReadJsonFloat(root, "width")));
				int height = Math.Max(1, Mathf.RoundToInt(ReadJsonFloat(root, "height")));
				_live2DWindowRectScreen = new Rect2I(x, y, width, height);
				_hasLive2DWindowRect = true;
				SyncLive2DBodyAnchor();
				return true;
			}
			return true;
		}
		catch (JsonException ex)
		{
			RunLogger.LogErr($"[Live2D] Control packet JSON lỗi: {ex.Message}");
			return true;
		}
	}


	private void OpenContextMenuFromLive2D(float screenX, float screenY)
	{
		if (!_isLive2DMode)
			return;
		DisplayServer.WindowMoveToForeground();
		Vector2I windowPosition = DisplayServer.WindowGetPosition();
		Vector2 localPosition = new(screenX - windowPosition.X, screenY - windowPosition.Y);
		ShowCharacterContextMenu(localPosition);
	}

	private void SyncLive2DBodyAnchor()
	{
		if (!_isLive2DMode || !_hasLive2DWindowRect || _body == null)
			return;
		Vector2I overlayScreenPosition = DisplayServer.WindowGetPosition();
		float anchorScreenX = _live2DWindowRectScreen.Position.X + _live2DWindowRectScreen.Size.X * 0.5f;
		float anchorScreenY = _live2DWindowRectScreen.Position.Y
			+ _live2DWindowRectScreen.Size.Y * Mathf.Clamp(Live2DBubbleAnchorY, 0.20f, 0.50f);
		_body.GlobalPosition = new Vector2(
			anchorScreenX - overlayScreenPosition.X,
			anchorScreenY - overlayScreenPosition.Y);
	}

	private void MoveLive2DWindowForBodyPosition(Vector2 bodyPosition)
	{
		if (_body == null)
			return;
		if (!_isLive2DMode)
		{
			_body.GlobalPosition = bodyPosition;
			return;
		}

		int width = Math.Max(1, _live2DWindowRectScreen.Size.X);
		int height = Math.Max(1, _live2DWindowRectScreen.Size.Y);
		Vector2I overlayScreenPosition = DisplayServer.WindowGetPosition();
		float anchorY = Mathf.Clamp(Live2DBubbleAnchorY, 0.20f, 0.50f);
		int x = overlayScreenPosition.X + Mathf.RoundToInt(bodyPosition.X - width * 0.5f);
		int y = overlayScreenPosition.Y + Mathf.RoundToInt(bodyPosition.Y - height * anchorY);

		_live2DWindowRectScreen = new Rect2I(x, y, width, height);
		_hasLive2DWindowRect = true;
		_body.GlobalPosition = bodyPosition;
		SendLive2DWindowGeometry(_live2DWindowRectScreen);
	}

	private void ApplyLive2DBubbleVisualState()
	{
		Control liveBubble = Live2DSpeechBubbleControl();
		if (!_isLive2DMode || liveBubble == null)
			return;
		EnsureControlOnCanvasLayer(liveBubble, 999);
		// Live2D không lật cả sprite như body pixel. Giữ bubble và chữ không bị
		// mirror theo trạng thái facing còn sót lại của MotionController.
		if (_monika != null)
			_monika.Scale = Vector2.One;
		liveBubble.Scale = Vector2.One;
		if (_hasLive2DWindowRect)
			PositionLive2DBubbleBesideModel(liveBubble);
		else
			liveBubble.Position = _bubbleBasePos;
	}

	private void PositionLive2DBubbleBesideModel(Control liveBubble)
	{
		if (liveBubble == null)
			return;
		Vector2 viewportSize = GetViewportRect().Size;
		if (viewportSize.X <= 0f || viewportSize.Y <= 0f)
			return;

		Vector2I overlayScreenPosition = DisplayServer.WindowGetPosition();
		Rect2 liveRect = new(
			new Vector2(
				_live2DWindowRectScreen.Position.X - overlayScreenPosition.X,
				_live2DWindowRectScreen.Position.Y - overlayScreenPosition.Y),
			new Vector2(_live2DWindowRectScreen.Size.X, _live2DWindowRectScreen.Size.Y));
		Vector2 bubbleSize = liveBubble.Size;
		if (bubbleSize.X <= 0f || bubbleSize.Y <= 0f)
			bubbleSize = new Vector2(560f, 230f);

		float margin = 8f;
		float gap = Mathf.Clamp(Live2DBubbleGap, 8f, 96f);
		float rightSpace = viewportSize.X - liveRect.End.X;
		float leftSpace = liveRect.Position.X;
		bool canPlaceRight = rightSpace >= bubbleSize.X + gap + margin;
		bool canPlaceLeft = leftSpace >= bubbleSize.X + gap + margin;

		float x;
		if (canPlaceRight || (!canPlaceLeft && rightSpace >= leftSpace))
			x = liveRect.End.X + gap;
		else if (canPlaceLeft)
			x = liveRect.Position.X - bubbleSize.X - gap;
		else
			x = liveRect.Position.X + (liveRect.Size.X - bubbleSize.X) * 0.5f;

		float y = liveRect.Position.Y
			+ liveRect.Size.Y * Mathf.Clamp(Live2DBubbleSideAnchorY, 0.05f, 0.75f);
		x = Mathf.Clamp(x, margin, Math.Max(margin, viewportSize.X - bubbleSize.X - margin));
		y = Mathf.Clamp(y, margin, Math.Max(margin, viewportSize.Y - bubbleSize.Y - margin));
		liveBubble.GlobalPosition = new Vector2(x, y);
	}

	private void SendLive2DControl(string type, bool visible = true)
	{
		if (!(_live2DManager?.IsRunning ?? false))
			return;
		try
		{
			var payload = new
			{
				protocol = "eris.live2d.control",
				version = 1,
				type = type ?? "",
				visible,
				timestamp = Time.GetUnixTimeFromSystem(),
			};
			string raw = JsonSerializer.Serialize(payload);
			_live2DForward.PutPacket(Encoding.UTF8.GetBytes(raw));
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Live2D] Control UDP lỗi: {ex.Message}");
		}
	}

	private void SendLive2DWindowGeometry(Rect2I windowRect)
	{
		if (!(_live2DManager?.IsRunning ?? false))
			return;
		try
		{
			var payload = new
			{
				protocol = "eris.live2d.control",
				version = 1,
				type = "set_window_geometry",
				timestamp = Time.GetUnixTimeFromSystem(),
				screen_x = windowRect.Position.X,
				screen_y = windowRect.Position.Y,
				width = windowRect.Size.X,
				height = windowRect.Size.Y,
			};
			string raw = JsonSerializer.Serialize(payload);
			_live2DForward.PutPacket(Encoding.UTF8.GetBytes(raw));
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Live2D] Window geometry UDP lỗi: {ex.Message}");
		}
	}

	private void ForwardPacketToLive2D(string raw)
	{
		// Giữ stage state nóng cả khi cửa sổ đang ẩn. Lúc bật lại, cảm xúc/TTS hiện
		// tại được tiếp tục ngay thay vì reset về neutral.
		if (!(_live2DManager?.IsRunning ?? false) || string.IsNullOrWhiteSpace(raw))
			return;
		try
		{
			_live2DForward.PutPacket(Encoding.UTF8.GetBytes(raw));
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[Live2D] Forward UDP lỗi: {ex.Message}");
		}
	}

	private bool ApplyLive2DMousePassthrough(bool uiActive)
	{
		if (!_isLive2DMode || uiActive)
			return false;

		Rect2 interactiveRect = new(new Vector2(-8f, -8f), Vector2.One);
		bool hasInteractiveRect = false;
		MergeVisibleControlRect(ref interactiveRect, ref hasInteractiveRect, Live2DSpeechBubbleControl(), 2f);
		MergeVisibleControlRect(ref interactiveRect, ref hasInteractiveRect, _runtimePresenceIndicator, 2f);
		MergeVisibleControlRect(ref interactiveRect, ref hasInteractiveRect, _tutorPanel, 2f);

		if (!hasInteractiveRect)
			interactiveRect = new Rect2(new Vector2(-8f, -8f), Vector2.One);

		bool unchanged =
			!_passthroughFullCapture
			&& _passthroughLastRect.Position.DistanceTo(interactiveRect.Position) < 2f
			&& _passthroughLastRect.Size.DistanceTo(interactiveRect.Size) < 2f;
		if (unchanged)
			return true;

		var region = new[]
		{
			interactiveRect.Position,
			interactiveRect.Position + new Vector2(interactiveRect.Size.X, 0f),
			interactiveRect.Position + interactiveRect.Size,
			interactiveRect.Position + new Vector2(0f, interactiveRect.Size.Y),
		};
		DisplayServer.WindowSetMousePassthrough(region);
		_passthroughFullCapture = false;
		_passthroughLastRect = interactiveRect;
		return true;
	}

	private void ShutdownLive2DMode()
	{
		_isLive2DMode = false;
		Restore2DSpriteVisual();
		SendLive2DControl("shutdown");
		_live2DManager?.Stop();
		_live2DForward.Close();
	}

	private static string ReadSavedBodyRendererMode()
	{
		try
		{
			string path = ProjectSettings.GlobalizePath(BodyRendererStatePath);
			return File.Exists(path) ? File.ReadAllText(path, Encoding.UTF8).Trim().ToLowerInvariant() : "2d";
		}
		catch
		{
			return "2d";
		}
	}

	private static void SaveBodyRendererMode(string mode)
	{
		try
		{
			string path = ProjectSettings.GlobalizePath(BodyRendererStatePath);
			Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
			File.WriteAllText(path, mode, Encoding.UTF8);
		}
		catch (Exception ex)
		{
			RunLogger.LogErr($"[BodyMode] Không lưu được renderer mode: {ex.Message}");
		}
	}
}
