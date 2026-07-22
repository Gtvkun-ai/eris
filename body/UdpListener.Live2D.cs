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

	[ExportGroup("Live2D Body")]
	[Export] public bool EnableLive2DSwitch = true;
	[Export] public string Live2DModelPath = "src/assets/live2d/infj/infj.model3.json";
	[Export(PropertyHint.Range, "1,65535,1")] public int Live2DStagePort = 4252;
	[Export] public bool RememberBodyRendererMode = true;

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
			if (!(_live2DManager?.Start(PythonExecutable, Live2DModelPath, Live2DStagePort) ?? false))
			{
				_isLive2DMode = false;
				if (_body != null)
					_body.Visible = true;
				UpdateBodyModeButton();
				_label.Text = "Không mở được Live2D. Chạy src/install_live2d_body.bat rồi thử lại.";
				CloseCharacterContextMenu();
				return;
			}
			_isLive2DMode = true;
			if (_body != null)
				_body.Visible = false;
			if (_bubble != null)
				_bubble.Visible = false;
			RunLogger.Log("[BodyMode] 2D -> Live2D");
		}
		else
		{
			bool wasLive2D = _isLive2DMode;
			_isLive2DMode = false;
			_live2DManager?.Stop();
			if (_body != null)
				_body.Visible = true;
			if (wasLive2D)
				RunLogger.Log("[BodyMode] Live2D -> 2D");
		}

		if (persist && RememberBodyRendererMode)
			SaveBodyRendererMode(_isLive2DMode ? "live2d" : "2d");
		UpdateBodyModeButton();
		CloseCharacterContextMenu();
	}

	private void UpdateBodyModeButton()
	{
		if (_contextBodyModeButton == null)
			return;
		_contextBodyModeButton.Text = _isLive2DMode ? "Chuyển về 2D" : "Chuyển sang Live2D";
		_contextBodyModeButton.TooltipText = _isLive2DMode
			? "Tắt cửa sổ Live2D và hiện lại body sprite 2D."
			: "Ẩn body sprite 2D và mở model infj.model3.json.";
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
		if (_body != null)
			_body.Visible = true;
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
				|| !root.TryGetProperty("type", out var type)
				|| !string.Equals(type.GetString(), "open_context_menu", StringComparison.Ordinal))
				return false;

			float screenX = root.TryGetProperty("screen_x", out var x) && x.TryGetSingle(out float parsedX) ? parsedX : 0f;
			float screenY = root.TryGetProperty("screen_y", out var y) && y.TryGetSingle(out float parsedY) ? parsedY : 0f;
			OpenContextMenuFromLive2D(screenX, screenY);
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

	private void ForwardPacketToLive2D(string raw)
	{
		if (!_isLive2DMode || !(_live2DManager?.IsRunning ?? false) || string.IsNullOrWhiteSpace(raw))
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

		// Renderer GLFW tự sở hữu vùng chuột của model. Godot chỉ giữ lại vùng
		// tương tác của TutorPanel nếu nó đang hiện; nếu không thì toàn bộ overlay
		// Godot được click xuyên để không dựng một hình chữ nhật vô hình trên desktop.
		Rect2 interactiveRect = new(new Vector2(-8f, -8f), Vector2.One);
		if (_tutorPanel != null && _tutorPanel.Visible && _tutorPanel.Size.X > 0f)
			interactiveRect = new Rect2(_tutorPanel.GlobalPosition, _tutorPanel.Size);

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
