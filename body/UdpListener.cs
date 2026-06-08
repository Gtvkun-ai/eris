using Godot;
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	private sealed class EmotionRowView
	{
		public HBoxContainer Row { get; init; }
		public Label Title { get; init; }
		public Label Note { get; init; }
		public Control FillClip { get; init; }
		public TextureRect Fill { get; init; }
		public Label Percent { get; init; }
	}

	private PacketPeerUdp _udp = new PacketPeerUdp();
	private int _port = 4242;
	private AnimatedSprite2D _monika;
	private CharacterBody2D _body;
	private RichTextLabel _label;
	private MotionController _motion;
	private LocalBodyAutonomy _bodyAutonomy;
	private BodyAudioController _audio;
	private ErisProcessManager _processes;
	private UdpDecisionParser _decisionParser = new();

	[Export] public string PythonExecutable = "python";
	[Export] public string VisionScriptPath = "src/vision.py";
	[Export] public string LlamaServerPath = "lib/llama-b8466-bin-win-cuda-12.4-x64/llama-server.exe";
	[Export] public string ModelPath = "src/model.gguf";
	[Export] public bool EnableLocalVisionInput = true;
	[Export] public string MmprojPath = "src/mmproj-F16.gguf";
	[Export] public bool AutoStartVision = true;
	[Export] public bool AutoPreloadLlamaServer = false;
	[Export] public int LlamaServerPort = 8080;
	[Export] public string LlamaServerNgl = "all";
	[Export] public int LlamaServerCtx = 8192;
	[Export] public bool LlamaServerFlashAttn = true;
	[Export(PropertyHint.MultilineText)] public string LlamaServerExtraArgs = "";
	[Export] public bool EnableRemoteCognitionApi = true;
	[Export] public bool EnableLocalStyleRewrite = false;
	[Export(PropertyHint.Password)] public string DefaultRemoteApiKey = "";
	[Export] public string RemoteApiProvider = "gemini";
	[Export] public string RemoteApiBaseUrl = "https://generativelanguage.googleapis.com/v1beta";
	[Export] public string RemoteApiModelName = "gemma-4-26b-a4b-it";
	[ExportGroup("Desktop Overlay")]
	[Export] public bool EnableDesktopOverlayWindow = true;
	[Export] public bool KeepWindowAlwaysOnTop = true;
	[Export] public bool UseBorderlessWindow = true;
	[Export] public bool UseTransparentWindow = true;

	private float _moveSpeed = 60f;   
	private float _moveDir = 1f;      
	private int _facingDir = -1;      
	private bool _isWalking = false;
	private string _currentAction = "stand";
	private float _gravity = 980f; // Gia tốc trọng trường tiêu chuẩn
	private float _velocityY = 0f;
	private bool _isFalling = false;
	private Vector2 _spriteHalfSize; // Láº¥y tá»« CollisionShape2D trong _Ready()
	// Climb
	private enum ClimbPhase { None, GoingToWall, Up, Top, TopHold, Down }
	private ClimbPhase _climbPhase = ClimbPhase.None;
	private float _climbUpWallX;    // X của tường leo lên
	private float _climbDownWallX;  // X của tường leo xuống
	private float _climbTopTargetX = float.NaN; // Điểm đích trên mép đỉnh; NaN = đi hết mép như cũ
	private const float ClimbSpeed = 50f;

	private Panel _chatPanel;
	private Panel _characterContextMenu;
	private Button _chatSendButton;
	private Button _chatCloseButton;
	private Button _contextChatButton;
	private Button _contextTouchButton;
	private Button _contextForceSpeakButton;
	private Button _contextEmotionButton;
	private Button _contextPrivateMindButton;
	private Button _contextCloseButton;
	private Panel _emotionPanel;
	private RichTextLabel _emotionText;
	private Panel _privateMindPanel;
	private RichTextLabel _privateMindText;
	private Label _emotionSummaryLabel;
	private Label _emotionHintLabel;
	private readonly List<EmotionRowView> _emotionRows = new();
	private Texture2D _emotionFillTexture;
	private Texture2D _emotionTrackTexture;
	private Texture2D _switchOnTexture;
	private Texture2D _switchOffTexture;
	private Texture2D _chatFrameTexture;
	private Texture2D _chatSubmitTexture;
	private Texture2D _chatCloseTexture;
	private TextureRect _switchTexture;
	private OptionButton _modeDropdown;
	private bool _emotionSwitchEnabled = true;
	private LineEdit _chatInput;
	private PacketPeerUdp _chatSend = new PacketPeerUdp();
	private Tween _textTween;
	private static readonly Vector2 CharacterContextMenuMinSize = new(212f, 262f);
	private static readonly Vector2 EmotionPanelMinSize = new(760f, 506f);
	private static readonly Vector2 PrivateMindPanelMinSize = new(820f, 560f);
	private const float EmotionBarWidth = 160f;
	private const float EmotionBarHeight = 26f;
	private readonly Random _rng = new Random();
	private EmotionDebug _latestEmotionDebug;
	private string _latestPrivateMindDebugJson = "";
	private Control _bubble;
	private bool _grabModeArmed = false;
	private bool _isDraggingCharacter = false;
	private Vector2 _dragOffset = Vector2.Zero;
	private Vector2 _lastDragMousePos = Vector2.Zero;
	private Vector2 _previousDragMousePos = Vector2.Zero;
	private double _previousDragSampleAt = 0.0;
	private double _lastDragSampleAt = 0.0;
	private string _nextAction = ""; // Lưu trữ hành động chờ thực thi
	private string _bounceAction = ""; // animation phát tại tường trước khi đổi chiều (loop mãi)
	private float _targetX = float.NaN; // target_x tuyệt đối trên màn hình (NaN = không có mục tiêu)
	private Vector2 _bubbleBasePos; // vị trí gốc của bubble trong không gian local của sprite
	private float _autonomousMoveCooldown = 0f;
	private double _lastRemoteMotionAt = 0.0;

	[Export] public bool EnableAutonomousIdleMovement = true;
	[Export] public float AutonomousIdleMoveMinSeconds = 5.0f;
	[Export] public float AutonomousIdleMoveMaxSeconds = 10.0f;
	[Export(PropertyHint.Range, "0,1,0.01")] public float AutonomousIdleWalkChance = 0.72f;
	[Export(PropertyHint.Range, "0,1,0.01")] public float AutonomousIdleFaceChance = 0.20f;
	[Export] public float AutonomousIdleRemoteCooldownSeconds = 2.5f;
	[Export] public bool EnableBodyAutonomyDebugLog = false;
	[Export] public float ThrowVelocityScale = 7.5f;
	[Export] public float ThrowVerticalBoostScale = 3.5f;
	[Export(PropertyHint.Range, "0,1,0.01")] public float ThrowClingChance = 0.45f;

	// Alias: ánh xạ tên AI hay hallucinate về tên animation thực
	private static readonly Dictionary<string, string> _animAliases = new()
	{
		{ "walk",       "stand_walk" },
		{ "walking",    "stand_walk" },
		{ "run",        "stand_walk" },
		{ "running",    "stand_walk" },
		{ "divide",     "divine" },
		{ "wave",       "stand" },
		{ "idle",       "stand" },
	};

	// Toàn bộ animation hợp lệ trong SpriteFrames
	private static readonly HashSet<string> _validAnimations = new()
	{
		"stand", "sit_down", "sit", "sit_up", "read", "stand_walk",
		"piano", "clone", "divine", "hop", "jump", "sleep", "sad",
		"food", "affection", "climb", "climb_top", "air_swing_l", "air_swing_r",
		"air", "shime", "idle",
	};

	// Các animation có âm thanh lặp lại liên tục
	private static readonly HashSet<string> _loopingSoundAnims = new()
	{
		"stand_walk", "sleep", "hop", "climb",
	};

	// Animation -> danh sách sound (tên ngẫu nhiên, sẽ rename sau)
	private static readonly Dictionary<string, string[]> _soundMap = new()
	{
		{ "affection",   new[] { "res://asset/Monika/sound/Cuddling.wav", "res://asset/Monika/sound/Giggle.wav", "res://asset/Monika/sound/Happy_Squeals.wav", "res://asset/Monika/sound/Squeal_Happy.wav" } },
		{ "air",         new[] { "res://asset/Monika/sound/Cartoon_Aah.wav", "res://asset/Monika/sound/Cartoon_Jump2.wav" } },
		{ "stand_walk",  new[] { "res://asset/Monika/sound/Cute_Run.wav", "res://asset/Monika/sound/Cartoon_Hop.wav" } },
		{ "sad",         new[] { "res://asset/Monika/sound/Hurt_Aah.wav", "res://asset/Monika/sound/Hurt_Unh.wav", "res://asset/Monika/sound/Sigh_Sleepy.wav" } },
		{ "read",        new[] { "res://asset/Monika/sound/Nyaa_Soft.wav" } },
		{ "piano",       new[] { "res://asset/Monika/sound/Giggle_Short.wav", "res://asset/Monika/sound/Giggle.wav" } },
		{ "food",        new[] { "res://asset/Monika/sound/Cartoon_Plop.wav", "res://asset/Monika/sound/Cartoon_Pop.wav" } },
		{ "clone",       new[] { "res://asset/Monika/sound/Cartoon_Pop.wav", "res://asset/Monika/sound/Happy_Squeals.wav" } },
		{ "divine",      new[] { "res://asset/Monika/sound/Cartoon_Pop.wav", "res://asset/Monika/sound/Happy_Squeals.wav" } },
		{ "stand",       new[] { "res://asset/Monika/sound/Nyaa_Quick.wav", "res://asset/Monika/sound/Nyaa_Soft.wav" } },
		{ "sit_down",    new[] { "res://asset/Monika/sound/Cartoon_Plop.wav" } },
		{ "sit_up",      new[] { "res://asset/Monika/sound/Cartoon_Plop.wav", "res://asset/Monika/sound/Nyaa_Quick.wav" } },
		{ "sit",         new[] { "res://asset/Monika/sound/Cartoon_Plop.wav", "res://asset/Monika/sound/Nyaa_Soft.wav" } },
		{ "climb",       new[] { "res://asset/Monika/sound/Cute_Run.wav" } },
		{ "climb_top",   new[] { "res://asset/Monika/sound/Cute_Run.wav", "res://asset/Monika/sound/Cartoon_Impact_F.wav" } },
		{ "hop",         new[] { "res://asset/Monika/sound/Cartoon_Hop.wav", "res://asset/Monika/sound/Cartoon_Jump2.wav" } },
		{ "jump",        new[] { "res://asset/Monika/sound/Cartoon_Jump2.wav", "res://asset/Monika/sound/Cartoon_Aah.wav" } },
		{ "sleep",       new[] { "res://asset/Monika/sound/Sigh_Sleepy.wav", "res://asset/Monika/sound/Cuddling.wav" } },
		{ "air_swing_l", new[] { "res://asset/Monika/sound/Cartoon_Aah.wav", "res://asset/Monika/sound/Squeal_Happy.wav" } },
		{ "air_swing_r", new[] { "res://asset/Monika/sound/Cartoon_Aah.wav", "res://asset/Monika/sound/Squeal_Happy.wav" } },
	};

	public override void _Ready()
	{
		ConfigureDesktopOverlayWindow();
		_udp.Bind(_port);
		_body   = GetNode<CharacterBody2D>("Monika2");
		_monika = GetNode<AnimatedSprite2D>("Monika2/Monika");
		_label  = GetNode<RichTextLabel>("Monika2/Monika/BubbleContainer/TextureRect/MessageLabel");
		_bubble   = GetNode<Control>("Monika2/Monika/BubbleContainer");
	_chatPanel = GetNode<Panel>("CanvasLayer/Control/ChatPanel");
	_chatSendButton = GetNode<Button>("CanvasLayer/Control/ChatPanel/HBoxContainer/SendButton");
	_chatCloseButton = GetNode<Button>("CanvasLayer/Control/ChatPanel/HBoxContainer/CloseButton");
	_characterContextMenu = GetNode<Panel>("CanvasLayer/Control/CharacterContextMenu");
	_contextChatButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/ChatButton");
		_contextTouchButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/TouchButton");
		_contextForceSpeakButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/ForceSpeakButton");
		_contextEmotionButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/EmotionButton");
		_contextCloseButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/CloseButton");
		_characterContextMenu.CustomMinimumSize = CharacterContextMenuMinSize;
		_characterContextMenu.Size = CharacterContextMenuMinSize;
		_characterContextMenu.ZIndex = 100;
		BuildCharacterContextMenuUi();
		_emotionPanel = GetNode<Panel>("CanvasLayer/Control/EmotionPanel");
		_emotionPanel.CustomMinimumSize = EmotionPanelMinSize;
		_emotionPanel.Size = EmotionPanelMinSize;
		_emotionPanel.ZIndex = 99;
		_emotionText = GetNodeOrNull<RichTextLabel>("CanvasLayer/Control/EmotionPanel/VBoxContainer/ScrollContainer/EmotionText");
		_privateMindPanel = new Panel
		{
			Name = "PrivateMindPanel",
			Visible = false,
			CustomMinimumSize = PrivateMindPanelMinSize,
			Size = PrivateMindPanelMinSize,
			ZIndex = 98,
		};
		GetNode<Control>("CanvasLayer/Control").AddChild(_privateMindPanel);
		BuildPrivateMindPanelUi();
		_chatInput = GetNode<LineEdit>("CanvasLayer/Control/ChatPanel/HBoxContainer/LineEdit");
		BuildChatPanelUi();
	_chatSendButton.Pressed += OnSendPressed;
	_chatCloseButton.Pressed += CloseChatPanel;
	_contextChatButton.Pressed += OnContextChatPressed;
	_contextTouchButton.Pressed += OnContextTouchPressed;
	_contextForceSpeakButton.Pressed += OnContextForceSpeakPressed;
	_contextEmotionButton.Pressed += OnContextEmotionPressed;
	if (_contextPrivateMindButton != null)
		_contextPrivateMindButton.Pressed += OnContextPrivateMindPressed;
	_contextCloseButton.Pressed += CloseCharacterContextMenu;
		_chatInput.TextSubmitted += _ => OnSendPressed();
		_chatSend.ConnectToHost("127.0.0.1", 4243);
		BuildEmotionPanelUi();

		var cs  = GetNode<CollisionShape2D>("Monika2/CollisionShape2D");

		// Hoist offset của children vào body, rồi reset children về gốc
		Vector2 startPos   = _monika.GlobalPosition; // (646, 360) theo tscn
		_monika.Position   = Vector2.Zero;
		cs.Position        = Vector2.Zero;
		_body.GlobalPosition = startPos;

		_spriteHalfSize = ((RectangleShape2D)cs.Shape).Size / 2;

		// Đặt nhân vật sát đáy màn hình ngay từ đầu, không cần rơi
		Vector2 screenSize = GetViewportRect().Size;
		Vector2 groundedPos = _body.GlobalPosition;
		_bubbleBasePos = _bubble.Position;
		_audio = new BodyAudioController();
		_audio.Attach(this, () => _motion?.CurrentAction ?? "stand");
		_motion = new MotionController(PlaySoundForAnimation);
		_motion.Configure(_spriteHalfSize, _bubbleBasePos);
		_bodyAutonomy = new LocalBodyAutonomy
		{
			TickMinSeconds = AutonomousIdleMoveMinSeconds,
			TickMaxSeconds = AutonomousIdleMoveMaxSeconds,
			EnableDebugLog = EnableBodyAutonomyDebugLog,
		};
		_motion.PlaceOnFloor(ref groundedPos, screenSize);
		_body.GlobalPosition = groundedPos;
		ResetAutonomousIdleMovementCooldown();
		_velocityY = 0f;
		_isFalling = false;

		// Khởi tạo AudioStreamPlayer
		_processes = new ErisProcessManager(UpdateServiceButtons);

		// Trạng thái mặc định khi khởi động
		_monika.Play("stand");
		_label.Text = "Chờ lệnh từ AI...";

		_monika.AnimationFinished += OnBounceAnimationFinished;
		GD.Print($"[Ready] Đang lắng nghe UDP cổng 4242. HalfSize={_spriteHalfSize}");
		if (AutoPreloadLlamaServer)
			StartLlamaServerProcess();
		if (AutoStartVision)
			StartVisionProcess();
	}

	private void ConfigureDesktopOverlayWindow()
	{
		if (!EnableDesktopOverlayWindow)
			return;

		DisplayServer.WindowSetFlag(DisplayServer.WindowFlags.AlwaysOnTop, KeepWindowAlwaysOnTop);
		DisplayServer.WindowSetFlag(DisplayServer.WindowFlags.Borderless, UseBorderlessWindow);

		if (UseTransparentWindow)
		{
			DisplayServer.WindowSetFlag(DisplayServer.WindowFlags.Transparent, true);
			GetViewport().TransparentBg = true;
		}
	}

	public override void _ExitTree()
	{
		StopVisionProcess();
		StopLlamaServerProcess();
		_udp.Close();
		_chatSend.Close();
	}


	public override void _Process(double delta)
	{
		//Nếu đang kéo nhân vật bằng chuột, nhân vật theo chuột.
		float d = (float)delta;
		Vector2 pos = _body.Position;
		Vector2 screenSize = GetViewportRect().Size;
		if (_isDraggingCharacter)
		{
			pos = ClampDraggedPosition(pos, screenSize);
			_body.Position = pos;
		}
		else
		{
			_motion.Step(ref pos, screenSize, d);
			_body.Position = pos;
			UpdateLocalBodyAutonomy(d);
		}
		_motion.ApplyVisualState(_monika, _bubble, _body.Position, screenSize);
		ClampBubbleToScreen();

		if (_udp.GetAvailablePacketCount() > 0)
		{
			string raw = Encoding.UTF8.GetString(_udp.GetPacket());
			ParseAndApply(raw);
		}
	}

	public override void _Input(InputEvent @event)
	{
		if (@event is InputEventMouseMotion mouseMotion && _isDraggingCharacter)
		{
			UpdateDrag(mouseMotion.Position);
			GetViewport().SetInputAsHandled();
			return;
		}

		if (@event is not InputEventMouseButton mouseEvent)
			return;

		if (_grabModeArmed && mouseEvent.ButtonIndex == MouseButton.Left)
		{
			if (mouseEvent.Pressed && IsMouseOverCharacter(mouseEvent.Position))
			{
				BeginDrag(mouseEvent.Position);
				GetViewport().SetInputAsHandled();
				return;
			}

			if (!mouseEvent.Pressed && _isDraggingCharacter)
			{
				EndDrag(mouseEvent.Position);
				GetViewport().SetInputAsHandled();
				return;
			}
		}

		if (!mouseEvent.Pressed)
			return;

		if (mouseEvent.ButtonIndex == MouseButton.Right)
		{
			if (_grabModeArmed || _isDraggingCharacter)
			{
				CancelGrabMode();
				GetViewport().SetInputAsHandled();
				return;
			}

			if (_characterContextMenu.Visible && IsMouseOverControl(_characterContextMenu, mouseEvent.Position))
			{
				GetViewport().SetInputAsHandled();
				return;
			}
			if (_emotionPanel.Visible && IsMouseOverControl(_emotionPanel, mouseEvent.Position))
			{
				GetViewport().SetInputAsHandled();
				return;
			}
			if (_privateMindPanel != null && _privateMindPanel.Visible && IsMouseOverControl(_privateMindPanel, mouseEvent.Position))
			{
				GetViewport().SetInputAsHandled();
				return;
			}

			if (IsMouseOverCharacter(mouseEvent.Position))
			{
				_bodyAutonomy?.RecordUserInteraction();
				ShowCharacterContextMenu(mouseEvent.Position);
				GetViewport().SetInputAsHandled();
				return;
			}

			if (_characterContextMenu.Visible)
			{
				CloseCharacterContextMenu();
				GetViewport().SetInputAsHandled();
			}
			if (_emotionPanel.Visible)
			{
				CloseEmotionPanel();
				GetViewport().SetInputAsHandled();
			}
			if (_privateMindPanel != null && _privateMindPanel.Visible)
			{
				ClosePrivateMindPanel();
				GetViewport().SetInputAsHandled();
			}

			return;
		}

		if (
			mouseEvent.ButtonIndex == MouseButton.Left
			&& _characterContextMenu.Visible
			&& !IsMouseOverControl(_characterContextMenu, mouseEvent.Position)
		)
		{
			CloseCharacterContextMenu();
		}

		if (
			mouseEvent.ButtonIndex == MouseButton.Left
			&& _emotionPanel.Visible
			&& !IsMouseOverControl(_emotionPanel, mouseEvent.Position)
		)
		{
			CloseEmotionPanel();
		}
		if (
			mouseEvent.ButtonIndex == MouseButton.Left
			&& _privateMindPanel != null
			&& _privateMindPanel.Visible
			&& !IsMouseOverControl(_privateMindPanel, mouseEvent.Position)
		)
		{
			ClosePrivateMindPanel();
		}
	}

	public override void _UnhandledInput(InputEvent @event)
	{
		if (@event is InputEventMouseButton releaseEvent && releaseEvent.ButtonIndex == MouseButton.Left && !releaseEvent.Pressed && _isDraggingCharacter)
		{
			EndDrag(releaseEvent.Position);
			return;
		}

		if (@event is not InputEventMouseButton mouseEvent || !mouseEvent.Pressed)
			return;

		if (mouseEvent.ButtonIndex == MouseButton.Left && _characterContextMenu.Visible)
		{
			CloseCharacterContextMenu();
		}
	}

	private void ToggleChatPanel()
	{
		CloseCharacterContextMenu();
		if (_chatPanel.Visible)
			CloseChatPanel();
		else
		{
			_bodyAutonomy?.RecordUserInteraction();
			UpdateChatPanelLayout();
			_chatPanel.Visible = true;
			_chatInput.GrabFocus();
			SendChatSignal("chat_start");
		}
	}

	private void CloseChatPanel()
	{
		_bodyAutonomy?.RecordUserInteraction();
		_chatPanel.Visible = false;
		_chatInput.Text = "";
		SendChatSignal("chat_end");
	}

	private void OnContextChatPressed()
	{
		CloseCharacterContextMenu();
		if (!_chatPanel.Visible)
			ToggleChatPanel();
		else
			_chatInput.GrabFocus();
	}

	private void OnContextTouchPressed()
	{
		CloseCharacterContextMenu();
		_bodyAutonomy?.RecordUserInteraction();
		_grabModeArmed = true;
	}

	private void OnContextForceSpeakPressed()
	{
		CloseCharacterContextMenu();
		_bodyAutonomy?.RecordUserInteraction();
		SendChatSignal("force_speak");
	}

	private void OnContextEmotionPressed()
	{
		_bodyAutonomy?.RecordUserInteraction();
		ToggleEmotionPanel();
	}

	private void OnContextPrivateMindPressed()
	{
		_bodyAutonomy?.RecordUserInteraction();
		TogglePrivateMindPanel();
	}

	private void ToggleEmotionPanel()
	{
		if (_emotionPanel.Visible)
			CloseEmotionPanel();
		else
			ShowEmotionPanel();
	}

	private void ShowEmotionPanel()
	{
		CloseCharacterContextMenu();
		_emotionPanel.Visible = true;
		_emotionPanel.Size = EmotionPanelMinSize;
		Vector2 screenSize = GetViewportRect().Size;
		_emotionPanel.Position = new Vector2(
			Mathf.Max(0f, (screenSize.X - EmotionPanelMinSize.X) * 0.5f),
			Mathf.Max(0f, (screenSize.Y - EmotionPanelMinSize.Y) * 0.5f));
		RefreshEmotionPanel();
	}

	private void CloseEmotionPanel()
	{
		_emotionPanel.Visible = false;
	}

	private void TogglePrivateMindPanel()
	{
		if (_privateMindPanel == null)
			return;
		if (_privateMindPanel.Visible)
			ClosePrivateMindPanel();
		else
			ShowPrivateMindPanel();
	}

	private void ShowPrivateMindPanel()
	{
		if (_privateMindPanel == null)
			return;
		CloseCharacterContextMenu();
		_privateMindPanel.Visible = true;
		_privateMindPanel.Size = PrivateMindPanelMinSize;
		Vector2 screenSize = GetViewportRect().Size;
		_privateMindPanel.Position = new Vector2(
			Mathf.Max(0f, screenSize.X - PrivateMindPanelMinSize.X - 28f),
			Mathf.Max(0f, (screenSize.Y - PrivateMindPanelMinSize.Y) * 0.5f));
		RefreshPrivateMindPanel();
	}

	private void ClosePrivateMindPanel()
	{
		if (_privateMindPanel != null)
			_privateMindPanel.Visible = false;
	}

	private void BuildChatPanelUi()
	{
		if (_chatPanel == null || _chatInput == null || _chatSendButton == null || _chatCloseButton == null)
			return;

		_chatFrameTexture = GD.Load<Texture2D>("res://asset/Resource/chatframe.png");
		_chatSubmitTexture = GD.Load<Texture2D>("res://asset/Resource/submitchatframe.png");
		_chatCloseTexture = GD.Load<Texture2D>("res://asset/Resource/exitschatframe.png");

		_chatPanel.AddThemeStyleboxOverride("panel", new StyleBoxTexture
		{
			Texture = _chatFrameTexture,
			TextureMarginLeft = 26f,
			TextureMarginTop = 26f,
			TextureMarginRight = 26f,
			TextureMarginBottom = 26f,
			AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
			AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
			ContentMarginLeft = 14f,
			ContentMarginTop = 14f,
			ContentMarginRight = 14f,
			ContentMarginBottom = 14f,
		});

		if (GetNodeOrNull<HBoxContainer>("CanvasLayer/Control/ChatPanel/HBoxContainer") is { } row)
		{
			row.Alignment = BoxContainer.AlignmentMode.Center;
			row.AddThemeConstantOverride("separation", 12);
			row.OffsetLeft = 12f;
			row.OffsetTop = 12f;
			row.OffsetRight = -12f;
			row.OffsetBottom = -12f;
		}

		_chatInput.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_chatInput.Alignment = HorizontalAlignment.Left;
		_chatInput.PlaceholderText = "Nhan tin voi ERIS...";
		_chatInput.AddThemeColorOverride("font_color", new Color(0.43f, 0.39f, 0.42f));
		_chatInput.AddThemeColorOverride("font_placeholder_color", new Color(0.64f, 0.60f, 0.63f));

		ConfigureChatActionButton(_chatSendButton, "Gui", _chatSubmitTexture, 22);
		ConfigureChatActionButton(_chatCloseButton, "X", _chatCloseTexture, 20);
		UpdateChatPanelLayout();
	}

	private void UpdateChatPanelLayout()
	{
		if (_chatPanel == null || _chatInput == null || _chatSendButton == null || _chatCloseButton == null || _chatFrameTexture == null)
			return;

		Vector2 viewport = GetViewportRect().Size;
		float targetWidth = Mathf.Clamp(viewport.X - 28f, 460f, 880f);
		float scale = Mathf.Clamp(targetWidth / 880f, 0.7f, 1f);
		// Keep height stable to avoid squishing the baked-in circular icon in chatframe.png.
		float targetHeight = 68f;
		float outerPadding = Mathf.Clamp(8f * scale, 6f, 8f);
		// Leave room for the decorative "chat" button area baked into the frame texture.
		float leftInset = Mathf.Clamp(72f * scale, 44f, 72f);
		float gap = Mathf.Clamp(10f * scale, 8f, 10f);
		float buttonHeight = Mathf.Clamp(44f * scale, 34f, 44f);
		// Icon removed from ChatPanel; keep layout compact.
		float submitWidth = Mathf.Clamp(96f * scale, 72f, 96f);
		float closeWidth = Mathf.Clamp(46f * scale, 36f, 46f);
		float fontSize = Mathf.Clamp(Mathf.RoundToInt(17f * scale), 13, 17);
		float buttonFontSize = Mathf.Clamp(Mathf.RoundToInt(20f * scale), 13, 20);
		float closeFontSize = Mathf.Clamp(Mathf.RoundToInt(18f * scale), 13, 18);
		float radius = Mathf.Clamp(Mathf.RoundToInt(13f * scale), 10, 13);
		float inputPadding = Mathf.Clamp(14f * scale, 10f, 14f);
		float borderPadding = Mathf.Clamp(2f * scale, 1f, 2f);

		_chatPanel.CustomMinimumSize = new Vector2(targetWidth, targetHeight);
		_chatPanel.Size = new Vector2(targetWidth, targetHeight);
		_chatPanel.Position = new Vector2(
			Mathf.Max(0f, (viewport.X - targetWidth) * 0.5f),
			Mathf.Max(0f, viewport.Y - targetHeight - 8f));

		if (GetNodeOrNull<HBoxContainer>("CanvasLayer/Control/ChatPanel/HBoxContainer") is { } row)
		{
			row.AddThemeConstantOverride("separation", (int)gap);
			row.OffsetLeft = outerPadding + leftInset;
			row.OffsetTop = outerPadding;
			row.OffsetRight = -outerPadding;
			row.OffsetBottom = -outerPadding;
		}

		_chatInput.CustomMinimumSize = new Vector2(140f, buttonHeight);
		_chatInput.AddThemeFontSizeOverride("font_size", (int)fontSize);
		_chatInput.AddThemeStyleboxOverride("normal", new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0.98f),
			CornerRadiusTopLeft = (int)radius,
			CornerRadiusTopRight = (int)radius,
			CornerRadiusBottomRight = (int)radius,
			CornerRadiusBottomLeft = (int)radius,
			ContentMarginLeft = inputPadding,
			ContentMarginTop = Mathf.Clamp(9f * scale, 7f, 9f),
			ContentMarginRight = inputPadding,
			ContentMarginBottom = Mathf.Clamp(9f * scale, 7f, 9f),
		});
		_chatInput.AddThemeStyleboxOverride("focus", new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0.98f),
			BorderColor = new Color(1f, 0.63f, 0.79f, 0.9f),
			BorderWidthLeft = (int)borderPadding,
			BorderWidthTop = (int)borderPadding,
			BorderWidthRight = (int)borderPadding,
			BorderWidthBottom = (int)borderPadding,
			CornerRadiusTopLeft = (int)radius,
			CornerRadiusTopRight = (int)radius,
			CornerRadiusBottomRight = (int)radius,
			CornerRadiusBottomLeft = (int)radius,
			ContentMarginLeft = Mathf.Max(8f, inputPadding - borderPadding),
			ContentMarginTop = Mathf.Max(6f, Mathf.Clamp(9f * scale, 7f, 9f) - borderPadding),
			ContentMarginRight = Mathf.Max(8f, inputPadding - borderPadding),
			ContentMarginBottom = Mathf.Max(6f, Mathf.Clamp(9f * scale, 7f, 9f) - borderPadding),
		});

		ApplyChatButtonLayout(_chatSendButton, "", _chatSubmitTexture, new Vector2(submitWidth, buttonHeight), buttonFontSize, scale);
		ApplyChatButtonLayout(_chatCloseButton, "X", _chatCloseTexture, new Vector2(closeWidth, buttonHeight), closeFontSize, scale);
	}

	private void ConfigureChatActionButton(Button button, string text, Texture2D texture, int fontSize)
	{
		if (button == null || texture == null)
			return;

		var style = new StyleBoxTexture
		{
			Texture = texture,
			TextureMarginLeft = 20f,
			TextureMarginTop = 20f,
			TextureMarginRight = 20f,
			TextureMarginBottom = 20f,
			AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
			AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
			ContentMarginLeft = 12f,
			ContentMarginTop = 8f,
			ContentMarginRight = 12f,
			ContentMarginBottom = 8f,
		};

		button.Text = text;
		button.AddThemeStyleboxOverride("normal", style);
		button.AddThemeStyleboxOverride("hover", style);
		button.AddThemeStyleboxOverride("pressed", style);
		button.AddThemeStyleboxOverride("focus", style);
		button.AddThemeColorOverride("font_color", Colors.White);
		button.AddThemeColorOverride("font_hover_color", Colors.White);
		button.AddThemeColorOverride("font_pressed_color", Colors.White);
		button.AddThemeFontSizeOverride("font_size", fontSize);
		button.MouseDefaultCursorShape = Control.CursorShape.PointingHand;
	}

	private void ApplyChatButtonLayout(Button button, string text, Texture2D texture, Vector2 size, float fontSize, float scale)
	{
		if (button == null || texture == null)
			return;

		button.Text = text;
		button.CustomMinimumSize = size;
		button.SizeFlagsHorizontal = Control.SizeFlags.ShrinkCenter;
		button.AddThemeFontSizeOverride("font_size", Mathf.RoundToInt(fontSize));

		// The button textures use 9-slice margins. When the UI scales down, fixed margins can exceed the
		// button height (e.g. 20+20 > 34), which causes the submit button to look "broken".
		float slice = Mathf.Clamp(20f * scale, 12f, 20f);
		slice = Mathf.Min(slice, Mathf.Max(1f, size.X * 0.5f - 1f));
		slice = Mathf.Min(slice, Mathf.Max(1f, size.Y * 0.5f - 1f));

		float contentX = Mathf.Clamp(12f * scale, 8f, 12f);
		float contentY = Mathf.Clamp(8f * scale, 6f, 8f);
		contentX = Mathf.Min(contentX, Mathf.Max(0f, size.X * 0.5f - slice - 1f));
		contentY = Mathf.Min(contentY, Mathf.Max(0f, size.Y * 0.5f - slice - 1f));

		var style = new StyleBoxTexture
		{
			Texture = texture,
			TextureMarginLeft = slice,
			TextureMarginTop = slice,
			TextureMarginRight = slice,
			TextureMarginBottom = slice,
			AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
			AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
			ContentMarginLeft = contentX,
			ContentMarginTop = contentY,
			ContentMarginRight = contentX,
			ContentMarginBottom = contentY,
		};

		button.AddThemeStyleboxOverride("normal", style);
		button.AddThemeStyleboxOverride("hover", style);
		button.AddThemeStyleboxOverride("pressed", style);
		button.AddThemeStyleboxOverride("focus", style);
	}

	private static float GetScaledWidth(Texture2D texture, float targetHeight)
	{
		if (texture == null)
			return targetHeight;

		Vector2 sourceSize = texture.GetSize();
		if (sourceSize.Y <= 0f)
			return targetHeight;

		return sourceSize.X / sourceSize.Y * targetHeight;
	}

	private void BuildCharacterContextMenuUi()
	{
		if (_characterContextMenu == null)
			return;

		var panelStyle = new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0.9f),
			BorderColor = new Color(1f, 0.76f, 0.86f, 0.95f),
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 14,
			CornerRadiusTopRight = 14,
			CornerRadiusBottomRight = 14,
			CornerRadiusBottomLeft = 14,
			ShadowColor = new Color(1f, 0.67f, 0.80f, 0.18f),
			ShadowSize = 7,
			ContentMarginLeft = 0,
			ContentMarginTop = 0,
			ContentMarginRight = 0,
			ContentMarginBottom = 0,
		};
		_characterContextMenu.AddThemeStyleboxOverride("panel", panelStyle);

		if (GetNodeOrNull<VBoxContainer>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer") is { } container)
		{
			container.AddThemeConstantOverride("separation", 6);
			container.OffsetLeft = 6f;
			container.OffsetTop = 8f;
			container.OffsetRight = -6f;
			container.OffsetBottom = -8f;
			if (_contextPrivateMindButton == null)
			{
				_contextPrivateMindButton = new Button { Name = "PrivateMindButton" };
				container.AddChild(_contextPrivateMindButton);
				int closeIndex = _contextCloseButton != null ? _contextCloseButton.GetIndex() : container.GetChildCount() - 1;
				container.MoveChild(_contextPrivateMindButton, Mathf.Max(0, closeIndex));
			}
		}

		ConfigureContextMenuButton(_contextChatButton, "Chat", "res://asset/Resource/chat.png");
		ConfigureContextMenuButton(_contextTouchButton, "Cham / Nem", "res://asset/Resource/tought.png");
		ConfigureContextMenuButton(_contextForceSpeakButton, "Noi ngay", "res://asset/Resource/force.png");
		ConfigureContextMenuButton(_contextEmotionButton, "Cam xuc", "res://asset/Resource/emotion.png");
		ConfigureContextMenuButton(_contextPrivateMindButton, "Private Mind", "res://asset/Resource/emotion.png");
		ConfigureContextMenuButton(_contextCloseButton, "Dong", "res://asset/Resource/exit.png");
	}

	private void ConfigureContextMenuButton(Button button, string text, string iconPath)
	{
		if (button == null)
			return;

		var texture = GD.Load<Texture2D>("res://asset/Resource/button.png");
		var style = new StyleBoxTexture
		{
			Texture = texture,
			TextureMarginLeft = 16f,
			TextureMarginTop = 16f,
			TextureMarginRight = 16f,
			TextureMarginBottom = 16f,
			AxisStretchHorizontal = StyleBoxTexture.AxisStretchMode.Stretch,
			AxisStretchVertical = StyleBoxTexture.AxisStretchMode.Stretch,
			ContentMarginLeft = 40f,
			ContentMarginTop = 6f,
			ContentMarginRight = 10f,
			ContentMarginBottom = 6f,
		};

		button.Text = text;
		button.CustomMinimumSize = new Vector2(0f, 36f);
		button.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		button.Alignment = HorizontalAlignment.Left;
		button.Icon = GD.Load<Texture2D>(iconPath);
		button.IconAlignment = HorizontalAlignment.Left;
		button.ExpandIcon = false;
		button.AddThemeStyleboxOverride("normal", style);
		button.AddThemeStyleboxOverride("hover", style);
		button.AddThemeStyleboxOverride("pressed", style);
		button.AddThemeStyleboxOverride("focus", style);
		button.AddThemeColorOverride("font_color", new Color(0.34f, 0.20f, 0.28f));
		button.AddThemeColorOverride("font_hover_color", new Color(0.34f, 0.20f, 0.28f));
		button.AddThemeColorOverride("font_pressed_color", new Color(0.34f, 0.20f, 0.28f));
		button.AddThemeConstantOverride("h_separation", 8);
		button.AddThemeFontSizeOverride("font_size", 15);
		button.MouseDefaultCursorShape = Control.CursorShape.PointingHand;
	}

	private void BuildEmotionPanelUi()
	{
		if (_emotionPanel == null)
			return;

		_emotionPanel.AddThemeStyleboxOverride("panel", new StyleBoxEmpty());
		foreach (Node child in _emotionPanel.GetChildren())
		{
			_emotionPanel.RemoveChild(child);
			child.QueueFree();
		}

		_emotionTrackTexture = GD.Load<Texture2D>("res://asset/Resource/feel 100.png");
		_emotionFillTexture = GD.Load<Texture2D>("res://asset/Resource/feel.png");
		_switchOnTexture = GD.Load<Texture2D>("res://asset/Resource/on.png");
		_switchOffTexture = GD.Load<Texture2D>("res://asset/Resource/off.png");

		var background = new TextureRect
		{
			Texture = GD.Load<Texture2D>("res://asset/Resource/ui clear.png"),
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		background.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_emotionPanel.AddChild(background);

		var left = new VBoxContainer
		{
			Position = new Vector2(50f, 148f),
			Size = new Vector2(470f, 286f),
			CustomMinimumSize = new Vector2(470f, 286f),
		};
		left.AddThemeConstantOverride("separation", 2);
		_emotionPanel.AddChild(left);

		_emotionRows.Clear();
		AddEmotionRow(left, "Binh tinh", "Trang thai thu gian, on dinh.", 0.72f, "res://asset/Monika/affection1.png");
		AddEmotionRow(left, "Kich thich", "Trang thai hung phan, phan khich.", 0.45f, "res://asset/Monika/affection2.png");
		AddEmotionRow(left, "Mood", "Tam trang hien tai.", 0.68f, "res://asset/Monika/affection3.png");
		AddEmotionRow(left, "Cam xuc tich cuc", "Nhung cam xuc tich cuc trong ban.", 0.85f, "res://asset/Monika/affection4.png");

		_emotionSummaryLabel = CreateUiLabel("", 1, Colors.Transparent);
		_emotionSummaryLabel.Visible = false;
		_emotionPanel.AddChild(_emotionSummaryLabel);
		_emotionHintLabel = CreateUiLabel("Nhung con so chi mang tinh tham khao.", 12, new Color(0.48f, 0.25f, 0.34f));
		_emotionHintLabel.Position = new Vector2(62f, 445f);
		_emotionHintLabel.Size = new Vector2(250f, 24f);
		_emotionPanel.AddChild(_emotionHintLabel);

		var windowControls = CreateWindowControlCapsule();
		windowControls.Position = new Vector2(635f, 20f);
		_emotionPanel.AddChild(windowControls);

		var modeLabel = CreateUiLabel("Chế độ", 16, new Color(0.69f, 0.30f, 0.47f));
		modeLabel.Position = new Vector2(536f, 98f);
		modeLabel.Size = new Vector2(160f, 24f);
		modeLabel.Visible = false;
		_emotionPanel.AddChild(modeLabel);

		_modeDropdown = CreateModeDropdown();
		_modeDropdown.Position = new Vector2(580f, 118f);
		_emotionPanel.AddChild(_modeDropdown);

		_switchTexture = new TextureRect
		{
			Texture = _switchOnTexture,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			Position = new Vector2(666f, 160f),
			Size = new Vector2(58f, 34f),
			CustomMinimumSize = new Vector2(58f, 34f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		_switchTexture.GuiInput += OnEmotionSwitchGuiInput;
		_emotionPanel.AddChild(_switchTexture);

	}

	private void BuildPrivateMindPanelUi()
	{
		if (_privateMindPanel == null)
			return;

		// Màu nền tối để chữ sáng dễ đọc hơn so với nền trắng cũ.
		var panelStyle = new StyleBoxFlat
		{
			BgColor = new Color(0.102f, 0.086f, 0.141f, 0.97f),       // #1a1624
			BorderColor = new Color(0.44f, 0.33f, 0.64f, 0.80f),      // tím vừa
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 10,
			CornerRadiusTopRight = 10,
			CornerRadiusBottomRight = 10,
			CornerRadiusBottomLeft = 10,
			ContentMarginLeft = 14,
			ContentMarginTop = 12,
			ContentMarginRight = 14,
			ContentMarginBottom = 12,
		};
		_privateMindPanel.AddThemeStyleboxOverride("panel", panelStyle);

		var root = new VBoxContainer();
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.OffsetLeft = 18f;
		root.OffsetTop = 16f;
		root.OffsetRight = -18f;
		root.OffsetBottom = -16f;
		root.AddThemeConstantOverride("separation", 10);
		_privateMindPanel.AddChild(root);

		var header = new HBoxContainer { CustomMinimumSize = new Vector2(0f, 34f) };
		root.AddChild(header);

		// Tiêu đề sáng trên nền tối.
		var title = CreateUiLabel("✦ Inner Diary", 20, new Color(0.769f, 0.659f, 0.941f)); // #c4a8f0
		title.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		header.AddChild(title);

		var close = new Button
		{
			Text = "×",
			CustomMinimumSize = new Vector2(34f, 30f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		close.Pressed += ClosePrivateMindPanel;
		header.AddChild(close);

		var scroll = new ScrollContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		root.AddChild(scroll);

		_privateMindText = new RichTextLabel
		{
			BbcodeEnabled = true,
			FitContent = true,
			ScrollActive = false,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		_privateMindText.AddThemeFontSizeOverride("normal_font_size", 14);
		// Màu chữ mặc định sáng cho nền tối.
		_privateMindText.AddThemeColorOverride("default_color", new Color(0.910f, 0.878f, 0.941f)); // #e8e0f0
		scroll.AddChild(_privateMindText);
		RefreshPrivateMindPanel();
	}

	private Label CreateUiLabel(string text, int fontSize, Color color)
	{
		var label = new Label { Text = text };
		label.AddThemeFontSizeOverride("font_size", fontSize);
		label.AddThemeColorOverride("font_color", color);
		return label;
	}

	private TextureButton CreateTextureButton(string path, Action onPressed, Vector2 size)
	{
		var button = new TextureButton
		{
			TextureNormal = GD.Load<Texture2D>(path),
			StretchMode = TextureButton.StretchModeEnum.Scale,
			CustomMinimumSize = size,
			IgnoreTextureSize = true,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		button.Pressed += onPressed;
		return button;
	}

	private Control CreateWindowControlCapsule()
	{
		var capsule = new PanelContainer
		{
			CustomMinimumSize = new Vector2(94f, 34f),
			Size = new Vector2(94f, 34f),
		};

		var capsuleStyle = new StyleBoxFlat
		{
			BgColor = new Color(1.00f, 0.94f, 0.97f, 0.88f),
			BorderColor = new Color(0.95f, 0.78f, 0.86f, 0.95f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 17,
			CornerRadiusTopRight = 17,
			CornerRadiusBottomRight = 17,
			CornerRadiusBottomLeft = 17,
			ContentMarginLeft = 6f,
			ContentMarginTop = 3f,
			ContentMarginRight = 6f,
			ContentMarginBottom = 3f,
			ShadowColor = new Color(0.94f, 0.76f, 0.84f, 0.20f),
			ShadowSize = 1,
		};
		capsule.AddThemeStyleboxOverride("panel", capsuleStyle);

		var row = new HBoxContainer();
		row.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		row.AddThemeConstantOverride("separation", 6);
		capsule.AddChild(row);

		var minimizeButton = CreateWindowControlButton("─", () => _emotionPanel.Visible = false, 34f, 16);
		var closeButton = CreateWindowControlButton("✕", CloseEmotionPanel, 34f, 14);
		row.AddChild(minimizeButton);
		row.AddChild(closeButton);
		return capsule;
	}

	private Button CreateWindowControlButton(string symbol, Action onPressed, float diameter, int fontSize)
	{
		var button = new Button
		{
			Text = symbol,
			CustomMinimumSize = new Vector2(diameter, diameter),
			Size = new Vector2(diameter, diameter),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			Flat = false,
		};

		var normalStyle = new StyleBoxFlat
		{
			BgColor = new Color(1.00f, 1.00f, 1.00f, 0.36f),
			BorderColor = new Color(0.95f, 0.78f, 0.86f, 0.00f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14,
			CornerRadiusTopRight = 14,
			CornerRadiusBottomRight = 14,
			CornerRadiusBottomLeft = 14,
			ContentMarginLeft = 0f,
			ContentMarginTop = 0f,
			ContentMarginRight = 0f,
			ContentMarginBottom = 0f,
		};
		var hoverStyle = (StyleBoxFlat)normalStyle.Duplicate();
		hoverStyle.BgColor = new Color(1.00f, 0.98f, 0.99f, 0.92f);
		hoverStyle.BorderColor = new Color(0.96f, 0.66f, 0.79f, 0.55f);
		var pressedStyle = (StyleBoxFlat)hoverStyle.Duplicate();
		pressedStyle.BgColor = new Color(0.99f, 0.93f, 0.96f, 0.98f);
		var focusStyle = (StyleBoxFlat)hoverStyle.Duplicate();
		focusStyle.BorderWidthLeft = 2;
		focusStyle.BorderWidthTop = 2;
		focusStyle.BorderWidthRight = 2;
		focusStyle.BorderWidthBottom = 2;

		button.AddThemeStyleboxOverride("normal", normalStyle);
		button.AddThemeStyleboxOverride("hover", hoverStyle);
		button.AddThemeStyleboxOverride("pressed", pressedStyle);
		button.AddThemeStyleboxOverride("focus", focusStyle);
		button.AddThemeColorOverride("font_color", new Color(0.86f, 0.45f, 0.63f));
		button.AddThemeColorOverride("font_hover_color", new Color(0.90f, 0.40f, 0.62f));
		button.AddThemeColorOverride("font_pressed_color", new Color(0.84f, 0.36f, 0.57f));
		button.AddThemeFontSizeOverride("font_size", fontSize);
		button.Alignment = HorizontalAlignment.Center;
		button.PivotOffset = new Vector2(diameter * 0.5f, diameter * 0.5f);
		button.MouseEntered += () => button.Scale = new Vector2(1.05f, 1.05f);
		button.MouseExited += () => button.Scale = Vector2.One;
		button.Pressed += onPressed;
		return button;
	}

	private OptionButton CreateModeDropdown()
	{
		var dropdown = new OptionButton
		{
			CustomMinimumSize = new Vector2(112f, 25f),
			Size = new Vector2(112f, 25f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			Text = "Dev",
			Alignment = HorizontalAlignment.Left,
		};
		dropdown.AddItem("Dev Mode");
		dropdown.AddItem("Casual Mode");
		dropdown.Select(0);

		var normalStyle = new StyleBoxFlat
		{
			BgColor = new Color(1.00f, 0.97f, 0.98f),
			BorderColor = new Color(0.95f, 0.82f, 0.88f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14,
			CornerRadiusTopRight = 14,
			CornerRadiusBottomRight = 14,
			CornerRadiusBottomLeft = 14,
			ContentMarginLeft = 16f,
			ContentMarginTop = 10f,
			ContentMarginRight = 34f,
			ContentMarginBottom = 10f,
			ShadowColor = new Color(0.90f, 0.70f, 0.79f, 0.20f),
			ShadowSize = 1,
		};
		var hoverStyle = (StyleBoxFlat)normalStyle.Duplicate();
		hoverStyle.BorderColor = new Color(0.93f, 0.70f, 0.81f);
		var focusStyle = (StyleBoxFlat)hoverStyle.Duplicate();
		focusStyle.BorderWidthLeft = 2;
		focusStyle.BorderWidthTop = 2;
		focusStyle.BorderWidthRight = 2;
		focusStyle.BorderWidthBottom = 2;

		dropdown.AddThemeStyleboxOverride("normal", normalStyle);
		dropdown.AddThemeStyleboxOverride("hover", hoverStyle);
		dropdown.AddThemeStyleboxOverride("pressed", hoverStyle);
		dropdown.AddThemeStyleboxOverride("focus", focusStyle);
		dropdown.AddThemeColorOverride("font_color", new Color(0.35f, 0.24f, 0.31f));
		dropdown.AddThemeColorOverride("font_hover_color", new Color(0.35f, 0.24f, 0.31f));
		dropdown.AddThemeColorOverride("font_focus_color", new Color(0.35f, 0.24f, 0.31f));
		dropdown.AddThemeColorOverride("font_disabled_color", new Color(0.58f, 0.49f, 0.54f));
		dropdown.AddThemeColorOverride("modulate_arrow", new Color(0.90f, 0.56f, 0.72f));
		dropdown.AddThemeFontSizeOverride("font_size", 13);

		var popup = dropdown.GetPopup();
		var popupStyle = new StyleBoxFlat
		{
			BgColor = new Color(1.00f, 0.97f, 0.98f),
			BorderColor = new Color(0.95f, 0.82f, 0.88f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14,
			CornerRadiusTopRight = 14,
			CornerRadiusBottomRight = 14,
			CornerRadiusBottomLeft = 14,
			ContentMarginLeft = 8f,
			ContentMarginTop = 8f,
			ContentMarginRight = 8f,
			ContentMarginBottom = 8f,
		};
		var popupHoverStyle = new StyleBoxFlat
		{
			BgColor = new Color(0.98f, 0.90f, 0.94f),
			CornerRadiusTopLeft = 10,
			CornerRadiusTopRight = 10,
			CornerRadiusBottomRight = 10,
			CornerRadiusBottomLeft = 10,
		};
		popup.AddThemeStyleboxOverride("panel", popupStyle);
		popup.AddThemeStyleboxOverride("hover", popupHoverStyle);
		popup.AddThemeStyleboxOverride("hover_mirrored", popupHoverStyle);
		popup.AddThemeColorOverride("font_color", new Color(0.35f, 0.24f, 0.31f));
		popup.AddThemeColorOverride("font_hover_color", new Color(0.35f, 0.24f, 0.31f));
		popup.AddThemeColorOverride("font_accelerator_color", new Color(0.58f, 0.49f, 0.54f));
		popup.AddThemeConstantOverride("v_separation", 4);

		dropdown.ItemSelected += OnModeDropdownSelected;
		return dropdown;
	}

	private void AddEmotionRow(VBoxContainer parent, string title, string note, float value, string portraitPath)
	{
		var row = new HBoxContainer
		{
			CustomMinimumSize = new Vector2(0f, 68f),
		};
		row.AddThemeConstantOverride("separation", 14);
		parent.AddChild(row);

		var portrait = new TextureRect
		{
			Texture = GD.Load<Texture2D>(portraitPath),
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
			CustomMinimumSize = new Vector2(58f, 58f),
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
		};
		row.AddChild(portrait);

		var textBox = new VBoxContainer
		{
			CustomMinimumSize = new Vector2(170f, 0f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
		};
		row.AddChild(textBox);
		var titleLabel = CreateUiLabel(title, 15, new Color(0.34f, 0.08f, 0.20f));
		var noteLabel = CreateUiLabel(note, 11, new Color(0.45f, 0.20f, 0.30f));
		textBox.AddChild(titleLabel);
		textBox.AddChild(noteLabel);

		var barStack = new Control
		{
			CustomMinimumSize = new Vector2(EmotionBarWidth, EmotionBarHeight),
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
		};
		row.AddChild(barStack);
		var track = new TextureRect
		{
			Texture = _emotionTrackTexture,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			Size = new Vector2(EmotionBarWidth, EmotionBarHeight),
		};
		barStack.AddChild(track);
		var fillClip = new Control
		{
			ClipContents = true,
			Position = new Vector2(0f, (EmotionBarHeight - GetEmotionFillHeight()) * 0.5f),
			Size = new Vector2(EmotionBarWidth, GetEmotionFillHeight()),
		};
		barStack.AddChild(fillClip);
		var fill = new TextureRect
		{
			Texture = _emotionFillTexture,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			Size = new Vector2(EmotionBarWidth, GetEmotionFillHeight()),
		};
		fillClip.AddChild(fill);

		var percent = CreateUiLabel("0%", 13, new Color(0.34f, 0.08f, 0.20f));
		percent.CustomMinimumSize = new Vector2(42f, 0f);
		percent.SizeFlagsVertical = Control.SizeFlags.ShrinkCenter;
		row.AddChild(percent);

		var view = new EmotionRowView
		{
			Row = row,
			Title = titleLabel,
			Note = noteLabel,
			FillClip = fillClip,
			Fill = fill,
			Percent = percent,
		};
		_emotionRows.Add(view);
		UpdateEmotionRow(view, title, note, value);
	}

	private void UpdateEmotionRow(EmotionRowView row, string title, string note, float value)
	{
		float clamped = Mathf.Clamp(value, 0f, 1f);
		float fillHeight = GetEmotionFillHeight();
		row.Title.Text = title;
		row.Note.Text = note;
		row.FillClip.CustomMinimumSize = new Vector2(EmotionBarWidth * clamped, fillHeight);
		row.FillClip.Position = new Vector2(0f, (EmotionBarHeight - fillHeight) * 0.5f);
		row.FillClip.Size = new Vector2(EmotionBarWidth * clamped, fillHeight);
		row.Fill.Size = new Vector2(EmotionBarWidth, fillHeight);
		row.Percent.Text = $"{Mathf.RoundToInt(clamped * 100f)}%";
	}

	private static float GetEmotionFillHeight()
	{
		return EmotionBarHeight * 0.80f;
	}

	private void OnEmotionSwitchGuiInput(InputEvent inputEvent)
	{
		if (inputEvent is not InputEventMouseButton mouse || mouse.ButtonIndex != MouseButton.Left || !mouse.Pressed)
			return;

		_emotionSwitchEnabled = !_emotionSwitchEnabled;
		if (_switchTexture != null)
			_switchTexture.Texture = _emotionSwitchEnabled ? _switchOnTexture : _switchOffTexture;
		SendChatSignal(_emotionSwitchEnabled ? "switch_case_on" : "switch_case_off");
	}

	private void OnModeDropdownSelected(long index)
	{
		if (_modeDropdown == null)
			return;

		_modeDropdown.Text = index == 0 ? "Dev" : "Casual";
	}

	private void BeginDrag(Vector2 mousePosition)
	{
		CloseCharacterContextMenu();
		_bodyAutonomy?.RecordUserInteraction();
		_grabModeArmed = false;
		_isDraggingCharacter = true;
		_dragOffset = _body.GlobalPosition - mousePosition; //Lưu khoảng cách giữa chuột và body để kéo không bị giật.
		_previousDragMousePos = mousePosition;
		_lastDragMousePos = mousePosition;
		_previousDragSampleAt = GetRuntimeSeconds();
		_lastDragSampleAt = GetRuntimeSeconds();
		int facing = mousePosition.X >= _body.GlobalPosition.X ? 1 : -1;
		string touchPose = facing >= 0 ? "air_swing_r" : "air_swing_l";
		_motion.ApplyCommand(
			new MotionCommand(
				intent: "pose",
				poseAnimation: touchPose,
				nextAnimation: "",
				bounceAction: "",
				facingDir: facing,
				targetX: -1f),
			_body.Position,
			GetViewportRect().Size);
		SendChatSignal("force_speak");
	}

	private void UpdateDrag(Vector2 mousePosition)
	{
		_previousDragSampleAt = _lastDragSampleAt;
		_previousDragMousePos = _lastDragMousePos;
		_lastDragMousePos = mousePosition;
		_lastDragSampleAt = GetRuntimeSeconds();
		_body.GlobalPosition = ClampDraggedPosition(mousePosition + _dragOffset, GetViewportRect().Size);
	}

	private void EndDrag(Vector2 mousePosition)
	{
		if (!_isDraggingCharacter)
			return;

		UpdateDrag(mousePosition);
		_isDraggingCharacter = false;
		_bodyAutonomy?.RecordRoughHandling();

		double dt = Math.Max(0.016, _lastDragSampleAt - _previousDragSampleAt);
		Vector2 delta = _lastDragMousePos - _previousDragMousePos;
		float impulseX = Mathf.Clamp((float)(delta.X / dt) * ThrowVelocityScale * 0.06f, -760f, 760f);
		float impulseY = Mathf.Clamp((float)(delta.Y / dt) * ThrowVerticalBoostScale * 0.04f, -560f, 320f);
		int facing = impulseX >= 0f ? 1 : -1;
		string airPose = facing >= 0 ? "air_swing_r" : "air_swing_l";
		float clingChance = Mathf.Clamp(ThrowClingChance + (Math.Abs(impulseX) >= 420f ? 0.18f : 0f), 0f, 0.9f);

		_motion.ApplyCommand(
			new MotionCommand(
				intent: "throw",
				poseAnimation: airPose,
				nextAnimation: "",
				bounceAction: "",
				facingDir: facing,
				targetX: -1f,
				impulseX: impulseX,
				impulseY: impulseY,
				clingChance: clingChance),
			_body.Position,
			GetViewportRect().Size);
	}

	private void CancelGrabMode()
	{
		_grabModeArmed = false;
		if (_isDraggingCharacter)
			EndDrag(_lastDragMousePos);
	}

	private void ShowCharacterContextMenu(Vector2 mousePosition)
	{
		_characterContextMenu.Visible = true;
		_characterContextMenu.Size = CharacterContextMenuMinSize;
		_characterContextMenu.ZIndex = 100;

		Vector2 screenSize = GetViewportRect().Size;
		Vector2 menuSize = _characterContextMenu.Size;
		Vector2 clamped = new(
			Mathf.Clamp(mousePosition.X, 0f, Mathf.Max(0f, screenSize.X - menuSize.X)),
			Mathf.Clamp(mousePosition.Y, 0f, Mathf.Max(0f, screenSize.Y - menuSize.Y)));

		_characterContextMenu.Position = clamped;
	}

	private void CloseCharacterContextMenu()
	{
		_characterContextMenu.Visible = false;
	}

	private bool IsMouseOverCharacter(Vector2 mousePosition)
	{
		Vector2 halfSize = _spriteHalfSize;
		Rect2 hitRect = new(_body.GlobalPosition - halfSize, halfSize * 2f);
		return hitRect.HasPoint(mousePosition);
	}

	private static bool IsMouseOverControl(Control control, Vector2 mousePosition)
	{
		Rect2 rect = new(control.GlobalPosition, control.Size);
		return rect.HasPoint(mousePosition);
	}

	private Vector2 ClampDraggedPosition(Vector2 desiredGlobalPosition, Vector2 screenSize)
	{
		return new Vector2(
			Mathf.Clamp(desiredGlobalPosition.X, _spriteHalfSize.X, screenSize.X - _spriteHalfSize.X),
			Mathf.Clamp(desiredGlobalPosition.Y, _spriteHalfSize.Y, screenSize.Y - _spriteHalfSize.Y));
	}

	private void OnSendPressed()
	{
		string msg = _chatInput.Text.Trim();
		if (string.IsNullOrEmpty(msg)) return;
		_bodyAutonomy?.RecordUserInteraction();
		_chatInput.Text = "";
		_chatInput.GrabFocus();
		//JsonSerializer.Serialize(msg) để escape chuỗi. Không tự nối raw string ngu ngốc
		string payload = $"{{\"type\":\"chat\",\"message\":{JsonSerializer.Serialize(msg)}}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
		ApplyTypewriterEffect($"[Chủ nhân]: {msg}");
	}

	private void SendChatSignal(string type)
	{
		string payload = $"{{\"type\":\"{type}\"}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
	}

	private void ApplyTypewriterEffect(string text){
		_label.Text = text;
		_label.VisibleCharacters = 0;

		if (_textTween != null && _textTween.IsValid())
		{
			_textTween.Kill();
		}

		_textTween = CreateTween();

		float speedPerChar = 0.05f;
		float totalDuration = text.Length * speedPerChar;

		// thực thi hiệu ứng gõ chữ
		_textTween.TweenProperty(_label, "visible_characters", text.Length, totalDuration);
	}
	private void UpdateAnimation()
	{
		// Climb phases
		if (_climbPhase == ClimbPhase.GoingToWall)
		{
			if (_monika.Animation != "stand_walk") _monika.Play("stand_walk");
			float scaleX = _climbUpWallX > _body.Position.X ? -1f : 1f;
			_monika.Scale = new Vector2(scaleX, 1f);
			_bubble.Scale = new Vector2(scaleX, 1f);
			_bubble.Position = new Vector2(_bubbleBasePos.X * scaleX, _bubbleBasePos.Y);
			return;
		}
		if (_climbPhase == ClimbPhase.Up || _climbPhase == ClimbPhase.Down)
		{
			if (_monika.Animation != "climb") _monika.Play("climb");
			float wallX = _climbPhase == ClimbPhase.Up ? _climbUpWallX : _climbDownWallX;
			float scaleX = wallX < GetViewportRect().Size.X / 2f ? 1f : -1f;
			_monika.Scale = new Vector2(scaleX, 1f);
			_bubble.Scale = new Vector2(scaleX, 1f);
			_bubble.Position = new Vector2(_bubbleBasePos.X * scaleX, _bubbleBasePos.Y);
			return;
		}
		if (_climbPhase == ClimbPhase.Top || _climbPhase == ClimbPhase.TopHold)
		{
			if (_monika.Animation != "climb_top") _monika.Play("climb_top");
			ApplyFacingForTopClimb();
			return;
		}

		// Normal
		if (_isFalling)
		{
			if (_monika.Animation != "air")
			{
				_monika.Play("air");
				GD.Print("[Anim] Chuyển sang animation: air (rơi tự do)");
			}
		}
		else
		{
			if (_monika.Animation != _currentAction)
				_monika.Play(_currentAction);
			if (_isWalking)
			{
				ApplyHorizontalFacing(_moveDir >= 0f ? 1 : -1);
			}
			else
			{
				ApplyFacingForCurrentAction();
			}
		}
	}

	private void ApplyHorizontalFacing(int facingDir)
	{
		_facingDir = facingDir >= 0 ? 1 : -1;
		float flipX = _facingDir == 1 ? -1f : 1f;
		_monika.Scale = new Vector2(flipX, 1f);
		_bubble.Scale = new Vector2(flipX, 1f);
		_bubble.Position = new Vector2(_bubbleBasePos.X * flipX, _bubbleBasePos.Y);
	}

	private void ApplyFacingForCurrentAction()
	{
		if (_currentAction == "air_swing_l")
		{
			ApplyHorizontalFacing(-1);
			return;
		}

		if (_currentAction == "air_swing_r")
		{
			ApplyHorizontalFacing(1);
			return;
		}

		ApplyHorizontalFacing(_facingDir);
	}

	private void ApplyFacingForTopClimb()
	{
		int topFacing = _facingDir;
		if (_climbPhase == ClimbPhase.Top)
		{
			float topTargetX = float.IsNaN(_climbTopTargetX) ? _climbDownWallX : _climbTopTargetX;
			topFacing = topTargetX >= _body.Position.X ? 1 : -1;
		}
		else if (_climbPhase == ClimbPhase.TopHold)
		{
			if (Mathf.IsEqualApprox(_body.Position.X, _spriteHalfSize.X))
				topFacing = 1;
			else if (Mathf.IsEqualApprox(_body.Position.X, GetViewportRect().Size.X - _spriteHalfSize.X))
				topFacing = -1;
		}

		ApplyHorizontalFacing(topFacing);
	}

	private void ClampBubbleToScreen()
	{
		Vector2 screenSize = GetViewportRect().Size;
		Vector2 bubbleGlobal = _bubble.GlobalPosition;
		float bubbleW = _bubble.Size.X;
		if (bubbleW <= 0f) return;

		float clampedX = Mathf.Clamp(bubbleGlobal.X, 0f, screenSize.X - bubbleW);
		if (!Mathf.IsEqualApprox(clampedX, bubbleGlobal.X))
			_bubble.GlobalPosition = new Vector2(clampedX, bubbleGlobal.Y);
	}

	private void UpdateLocalBodyAutonomy(float delta)
	{
		if (!EnableAutonomousIdleMovement || _bodyAutonomy == null || _motion == null)
			return;

		_bodyAutonomy.TickMinSeconds = AutonomousIdleMoveMinSeconds;
		_bodyAutonomy.TickMaxSeconds = AutonomousIdleMoveMaxSeconds;
		_bodyAutonomy.EnableDebugLog = EnableBodyAutonomyDebugLog;

		var context = new BodyAutonomyContext(
			bodyPosition: _body.Position,
			screenSize: GetViewportRect().Size,
			currentAction: _motion.CurrentAction,
			motionBusy: _motion.IsBusy,
			chatVisible: _chatPanel != null && _chatPanel.Visible,
			isTopPerched: _motion.IsTopPerched);

		if (!_bodyAutonomy.TryUpdate(delta, context, out var decision))
			return;

		_motion.ApplyCommand(decision.Command, _body.Position, GetViewportRect().Size);
		if (!string.IsNullOrWhiteSpace(decision.OptionalSpeech))
			ApplyTypewriterEffect(decision.OptionalSpeech);
	}

	private void UpdateAutonomousIdleMovement(float delta)
	{
		if (!EnableAutonomousIdleMovement || _motion == null)
			return;
		if (_motion.IsBusy || _motion.CurrentAction != "stand")
			return;
		if (_chatPanel != null && _chatPanel.Visible)
			return;
		if (GetRuntimeSeconds() - _lastRemoteMotionAt < Math.Max(0.5f, AutonomousIdleRemoteCooldownSeconds))
			return;

		_autonomousMoveCooldown -= delta;
		if (_autonomousMoveCooldown > 0f)
			return;

		float roll = (float)_rng.NextDouble();
		if (roll <= Mathf.Clamp(AutonomousIdleWalkChance, 0f, 1f))
		{
			float target = 0.12f + (float)_rng.NextDouble() * 0.76f;
			int facing = target >= (_body.Position.X / Math.Max(1f, GetViewportRect().Size.X)) ? 1 : -1;
			_motion.ApplyCommand(
				new MotionCommand(
					intent: "walk_to",
					poseAnimation: "stand_walk",
					nextAnimation: "stand",
					bounceAction: "",
					facingDir: facing,
					targetX: target),
				_body.Position,
				GetViewportRect().Size);
		}
		else if (roll <= Mathf.Clamp(AutonomousIdleWalkChance + AutonomousIdleFaceChance, 0f, 1f))
		{
			int facing = _rng.NextDouble() >= 0.5 ? 1 : -1;
			_motion.ApplyCommand(
				new MotionCommand(
					intent: "face",
					poseAnimation: "stand",
					nextAnimation: "",
					bounceAction: "",
					facingDir: facing,
					targetX: -1f),
				_body.Position,
				GetViewportRect().Size);
		}

		ResetAutonomousIdleMovementCooldown();
	}

	private void ResetAutonomousIdleMovementCooldown()
	{
		float min = Math.Max(1f, AutonomousIdleMoveMinSeconds);
		float max = Math.Max(min, AutonomousIdleMoveMaxSeconds);
		_autonomousMoveCooldown = (float)(min + _rng.NextDouble() * (max - min));
	}

	private static bool HasRemoteMotionCommand(string motionIntent, string animation, string nextAnimation, int motionFacing, float motionTargetX)
	{
		if (!string.IsNullOrWhiteSpace(motionIntent))
			return true;
		if (motionFacing != 0)
			return true;
		if (motionTargetX >= 0f)
			return true;
		if (!string.IsNullOrWhiteSpace(nextAnimation))
			return true;
		return !string.Equals(animation, "stand", StringComparison.Ordinal);
	}

	private static double GetRuntimeSeconds()
	{
		return Time.GetTicksMsec() / 1000.0;
	}

	private string NormalizeAnimationName(string animation, int facingDir, bool allowEmpty = false)
	{
		string value = (animation ?? "").Trim();
		if (string.IsNullOrEmpty(value))
			return allowEmpty ? "" : "stand";

		if (_animAliases.TryGetValue(value, out var mapped))
		{
			GD.Print($"[Anim] Alias '{value}' -> '{mapped}'");
			value = mapped;
		}

		if (_validAnimations.Contains(value))
			return value;

		string fallback = (facingDir == 1 || facingDir == -1) ? "stand_walk" : "stand";
		GD.PrintErr($"[Anim] Animation không hợp lệ: '{value}', fallback về '{fallback}'.");
		return allowEmpty ? "" : fallback;
	}

	private static string InferMotionIntent(string animation, string nextAnimation, int facingDir, float targetX)
	{
		if (animation == "climb" && nextAnimation == "climb_top")
			return "climb_to_top";
		if (animation == "climb_top")
			return "climb_to_top";
		if (animation == "climb")
			return "climb_loop";
		if (animation == "air_swing_l" || animation == "air_swing_r")
			return "drop";
		if (targetX >= 0f)
			return "walk_to";
		if (animation == "stand_walk")
			return "walk";
		if (facingDir == 1 || facingDir == -1)
			return "face";
		return "";
	}

	private void ParseAndApply(string raw)
	{
		var payload = _decisionParser.Parse(raw);
		if (payload.HasEmotionDebug)
		{
			_latestEmotionDebug = payload.EmotionDebug;
			if (_emotionPanel != null && _emotionPanel.Visible)
				RefreshEmotionPanel();
		}
		if (payload.HasPrivateMindDebug)
		{
			_latestPrivateMindDebugJson = payload.PrivateMindDebugJson;
			if (_privateMindPanel != null && _privateMindPanel.Visible)
				RefreshPrivateMindPanel();
		}
		if (payload.HasBodyBias)
			_bodyAutonomy?.ApplyCognitionBias(payload.BodyBias);

		if (!string.IsNullOrEmpty(payload.ParseMode) || !string.IsNullOrEmpty(payload.DebugTrace) || !string.IsNullOrEmpty(payload.ParserTrace))
		{
			GD.Print($"[AI Debug] parse_mode={payload.ParseMode}");
			if (!string.IsNullOrEmpty(payload.DebugTrace))
				GD.Print($"[AI Debug] trace={payload.DebugTrace}");
			if (!string.IsNullOrEmpty(payload.ParserTrace))
				GD.Print($"[AI Debug] parser={payload.ParserTrace}");
		}

		if (payload.HasRemoteMotion)
			_lastRemoteMotionAt = GetRuntimeSeconds();

		if (payload.ShouldSpeak && (payload.HasTextField || !payload.ParsedJson) && !string.IsNullOrWhiteSpace(payload.Text))
			ApplyTypewriterEffect(payload.Text);

		if (payload.HasExplicitMotion)
			_motion.ApplyCommand(payload.MotionCommand, _body.Position, GetViewportRect().Size);
	}

	private void RefreshEmotionPanel()
	{
		if (_emotionRows.Count > 0)
		{
			RefreshEmotionPanelRows();
			return;
		}

		if (_emotionText == null)
			return;

		if (_latestEmotionDebug == null || _latestEmotionDebug.Items == null || _latestEmotionDebug.Items.Count == 0)
		{
			_emotionText.Text = "[i]Chua co frame cam xuc.[/i]";
			return;
		}

		var sb = new StringBuilder();
		sb.Append("[b]Trang thai[/b]\n");
		string summary = string.IsNullOrWhiteSpace(_latestEmotionDebug.SummaryValue) ? "unknown" : _latestEmotionDebug.SummaryValue;
		sb.Append(EscapeBbcode(_latestEmotionDebug.SummaryLabel));
		sb.Append(": [b]");
		sb.Append(EscapeBbcode(summary));
		sb.Append("[/b]");
		if (_latestEmotionDebug.HasSummaryValence)
			sb.Append($"  valence={_latestEmotionDebug.SummaryValence:0.00}");
		if (!string.IsNullOrWhiteSpace(_latestEmotionDebug.SummaryState))
			sb.Append($"  state={EscapeBbcode(_latestEmotionDebug.SummaryState)}");
		sb.Append("\n\n");

		string currentGroup = "";
		foreach (var item in _latestEmotionDebug.Items)
		{
			string group = string.IsNullOrWhiteSpace(item.Group) ? "other" : item.Group;
			if (!string.Equals(group, currentGroup, StringComparison.Ordinal))
			{
				currentGroup = group;
				sb.Append("[color=#8fb7ff][b]");
				sb.Append(EscapeBbcode(GroupTitle(group)));
				sb.Append("[/b][/color]\n");
			}

			sb.Append("  ");
			sb.Append(EscapeBbcode(item.Label));
			sb.Append(": ");
			if (item.HasNumericValue)
			{
				sb.Append(BuildMeter(item.NumericValue));
				sb.Append($" {item.NumericValue:0.00}");
			}
			else
			{
				sb.Append(EscapeBbcode(string.IsNullOrWhiteSpace(item.ValueText) ? "-" : item.ValueText));
			}
			if (!string.IsNullOrWhiteSpace(item.Note))
			{
				sb.Append("  ");
				sb.Append(EscapeBbcode(item.Note));
			}
			sb.Append("\n");
		}

		_emotionText.Text = sb.ToString();
	}

	private void RefreshPrivateMindPanel()
	{
		if (_privateMindText == null)
			return;
		if (string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson))
		{
			_privateMindText.Text = "[color=#a090b8][i]Chưa có dữ liệu.[/i][/color]";
			return;
		}

		try
		{
			using var doc = JsonDocument.Parse(_latestPrivateMindDebugJson);
			_privateMindText.Text = RenderDiary(doc.RootElement);
		}
		catch (Exception ex)
		{
			_privateMindText.Text =
				$"[color=#ff6666]Lỗi đọc dữ liệu:[/color] {EscapeBbcode(ex.Message)}";
		}
	}

	/// <summary>
	/// Render private mind digest thành diary tiếng Việt dễ đọc.
	/// Ưu tiên inner_diary.sections nếu có; nếu không, tự dựng từ current/concerns/fragments.
	/// </summary>
	private static string RenderDiary(JsonElement root)
	{
		if (root.ValueKind != JsonValueKind.Object)
			return "[color=#a090b8][i]Không có dữ liệu.[/i][/color]";

		var sb = new StringBuilder();

		// Thử dùng inner_diary.sections trước (đường ưu tiên)
		JsonElement diaryEl = default;
		bool hasDiary = false;
		if (root.TryGetProperty("inner_diary", out diaryEl) && diaryEl.ValueKind == JsonValueKind.Object)
			hasDiary = true;
		else if (root.TryGetProperty("menu", out var menuEl) && menuEl.ValueKind == JsonValueKind.Object
		         && menuEl.TryGetProperty("inner_diary", out diaryEl) && diaryEl.ValueKind == JsonValueKind.Object)
			hasDiary = true;

		if (hasDiary && diaryEl.TryGetProperty("sections", out var sectionsEl) && sectionsEl.ValueKind == JsonValueKind.Array)
		{
			int rendered = 0;
			foreach (var sec in sectionsEl.EnumerateArray())
			{
				if (sec.ValueKind != JsonValueKind.Object) continue;
				string title = sec.TryGetProperty("title", out var tEl) ? tEl.GetString() ?? "" : "";
				if (!sec.TryGetProperty("lines", out var linesEl) || linesEl.ValueKind != JsonValueKind.Array)
					continue;
				var lines = new List<string>();
				foreach (var l in linesEl.EnumerateArray())
				{
					string s = l.GetString() ?? "";
					if (!string.IsNullOrWhiteSpace(s)) lines.Add(s);
				}
				if (lines.Count == 0) continue;
				if (rendered > 0) sb.Append('\n');
				sb.Append("[color=#88aaff][b]").Append(EscapeBbcode(title)).Append("[/b][/color]\n");
				foreach (string line in lines)
				{
					if (line.StartsWith("- ", StringComparison.Ordinal))
						sb.Append("[color=#a090b8]·[/color] ").Append(EscapeBbcode(line[2..])).Append('\n');
					else
						sb.Append(EscapeBbcode(line)).Append('\n');
				}
				rendered++;
			}
			if (rendered > 0)
				return sb.ToString();
		}

		// Fallback: tự dựng diary từ dữ liệu thô — tiếng Việt, không dump JSON
		return RenderDiaryFromRaw(root);
	}

	private static string RenderDiaryFromRaw(JsonElement root)
	{
		var sb = new StringBuilder();

		// Tìm menu (hoặc dùng root trực tiếp)
		JsonElement menu = root;
		if (root.TryGetProperty("menu", out var menuEl) && menuEl.ValueKind == JsonValueKind.Object)
			menu = menuEl;

		// --- Suy nghĩ hiện tại ---
		JsonElement current = default;
		bool hasCurrent = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("current_thought", out current) && current.ValueKind == JsonValueKind.Object)
			hasCurrent = true;
		else if (root.TryGetProperty("current", out current) && current.ValueKind == JsonValueKind.Object)
			hasCurrent = true;

		if (hasCurrent)
		{
			string judgment = DiaryStr(current, "dominant_judgment", 300);
			string confidence = DiaryNum(current, "confidence");
			string pressure = DiaryNum(current, "pressure");
			if (!string.IsNullOrWhiteSpace(judgment))
			{
				sb.Append("[color=#88aaff][b]Suy nghĩ hiện tại[/b][/color]\n");
				sb.Append(EscapeBbcode(judgment)).Append('\n');
				sb.Append("[color=#6a5a80]Độ chắc: ").Append(confidence)
				  .Append("  |  Áp lực: ").Append(pressure).Append("[/color]\n");
			}
		}

		// --- Điều đang bận tâm ---
		JsonElement concerns = default;
		bool hasConcerns = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("open_concerns", out concerns) && concerns.ValueKind == JsonValueKind.Array)
			hasConcerns = true;
		else if (root.TryGetProperty("retained", out var retained) && retained.ValueKind == JsonValueKind.Object
		         && retained.TryGetProperty("concerns", out concerns) && concerns.ValueKind == JsonValueKind.Array)
			hasConcerns = true;

		if (hasConcerns)
		{
			int count = 0;
			var concernLines = new List<string>();
			foreach (var c in concerns.EnumerateArray())
			{
				if (c.ValueKind != JsonValueKind.Object) continue;
				string theme = DiaryStr(c, "theme", 160);
				if (string.IsNullOrWhiteSpace(theme)) continue;
				string pressure = DiaryNum(c, "pressure");
				string status = DiaryStr(c, "status", 30);
				concernLines.Add($"{theme}  [color=#6a5a80](áp lực {pressure})[/color]");
				if (++count >= 4) break;
			}
			if (concernLines.Count > 0)
			{
				if (sb.Length > 0) sb.Append('\n');
				sb.Append("[color=#88aaff][b]Đang bận tâm[/b][/color]\n");
				foreach (var l in concernLines)
					sb.Append("[color=#a090b8]·[/color] ").Append(l).Append('\n');
			}
		}

		// --- Mảnh suy nghĩ từ evaluators ---
		JsonElement fragments = default;
		bool hasFragments = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("temporary_thoughts", out var tmp)
		    && tmp.ValueKind == JsonValueKind.Object && tmp.TryGetProperty("fragments", out fragments)
		    && fragments.ValueKind == JsonValueKind.Array)
			hasFragments = true;
		else if (root.TryGetProperty("temporary", out var tmpR) && tmpR.ValueKind == JsonValueKind.Object
		         && tmpR.TryGetProperty("fragments", out fragments) && fragments.ValueKind == JsonValueKind.Array)
			hasFragments = true;

		if (hasFragments)
		{
			int count = 0;
			var fragLines = new List<string>();
			foreach (var f in fragments.EnumerateArray())
			{
				if (f.ValueKind != JsonValueKind.Object) continue;
				string claim = DiaryStr(f, "claim", 200);
				if (string.IsNullOrWhiteSpace(claim)) continue;
				string score = DiaryNum(f, "score");
				fragLines.Add($"{claim}  [color=#6a5a80](score {score})[/color]");
				if (++count >= 4) break;
			}
			if (fragLines.Count > 0)
			{
				if (sb.Length > 0) sb.Append('\n');
				sb.Append("[color=#88aaff][b]Phân tích gần đây[/b][/color]\n");
				foreach (var l in fragLines)
					sb.Append("[color=#a090b8]·[/color] ").Append(l).Append('\n');
			}
		}

		// --- API status nếu có lỗi ---
		JsonElement debugApi = default;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("debug_api", out debugApi)
		    && debugApi.ValueKind == JsonValueKind.Object)
		{
			string lastError = DiaryStr(debugApi, "last_error", 120);
			if (!string.IsNullOrWhiteSpace(lastError) && lastError != "none" && lastError != "null")
			{
				if (sb.Length > 0) sb.Append('\n');
				sb.Append("[color=#ff8866][b]API:[/b] ").Append(EscapeBbcode(lastError)).Append("[/color]\n");
			}
		}

		return sb.Length > 0
			? sb.ToString()
			: "[color=#a090b8][i]Chưa có đủ dữ liệu.[/i][/color]";
	}

	private static string DiaryStr(JsonElement el, string key, int limit)
	{
		if (el.ValueKind != JsonValueKind.Object) return "";
		if (!el.TryGetProperty(key, out var v)) return "";
		string raw = v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : v.GetRawText();
		return CompactText(raw, limit);
	}

	private static string DiaryNum(JsonElement el, string key)
	{
		if (el.ValueKind != JsonValueKind.Object) return "—";
		if (!el.TryGetProperty(key, out var v)) return "—";
		if (v.ValueKind == JsonValueKind.Number)
		{
			if (v.TryGetDouble(out double d)) return d.ToString("0.##");
		}
		return v.GetRawText();
	}

	/// <summary>
	/// Đọc inner_diary.sections từ digest (do InnerDiaryRenderer tạo ra)
	/// và render thành BBCode dễ đọc. Trả false nếu không có.
	/// </summary>
	private static bool TryRenderInnerDiary(JsonElement root, out string bbcode)
	{
		bbcode = "";

		// inner_diary có thể nằm ở root hoặc trong root.menu
		JsonElement diaryEl = default;
		bool found = false;
		if (root.ValueKind == JsonValueKind.Object)
		{
			if (root.TryGetProperty("inner_diary", out diaryEl) && diaryEl.ValueKind == JsonValueKind.Object)
				found = true;
			else if (root.TryGetProperty("menu", out var menuEl) && menuEl.ValueKind == JsonValueKind.Object
			         && menuEl.TryGetProperty("inner_diary", out diaryEl) && diaryEl.ValueKind == JsonValueKind.Object)
				found = true;
		}
		if (!found)
			return false;

		// Nếu có mảng sections thì render từng section.
		if (diaryEl.TryGetProperty("sections", out var sectionsEl) && sectionsEl.ValueKind == JsonValueKind.Array)
		{
			var sb = new StringBuilder();
			int totalLines = 0;

			foreach (var sectionEl in sectionsEl.EnumerateArray())
			{
				if (sectionEl.ValueKind != JsonValueKind.Object) continue;
				string sectionTitle = sectionEl.TryGetProperty("title", out var tEl) ? tEl.GetString() ?? "" : "";

				// Đếm lines thực có trong section này trước khi render tiêu đề,
				// tránh render tiêu đề rỗng lơ lửng khi data chưa về.
				var sectionLines = new List<string>();
				if (sectionEl.TryGetProperty("lines", out var linesEl) && linesEl.ValueKind == JsonValueKind.Array)
				{
					foreach (var lineEl in linesEl.EnumerateArray())
					{
						string line = lineEl.GetString() ?? "";
						if (!string.IsNullOrWhiteSpace(line))
							sectionLines.Add(line);
					}
				}

				if (sectionLines.Count == 0) continue; // bỏ qua section rỗng

				sb.Append("\n[color=#88aaff][b]");
				sb.Append(EscapeBbcode(sectionTitle));
				sb.Append("[/b][/color]\n");

				foreach (string line in sectionLines)
				{
					if (line.StartsWith("- ", StringComparison.Ordinal))
						sb.Append("[color=#a090b8]•[/color] ").Append(EscapeBbcode(line[2..])).Append('\n');
					else
						sb.Append(EscapeBbcode(line)).Append('\n');
					totalLines++;
				}
			}

			// Nếu không có line nào thực sự — digest chưa đủ data (synthesis đang fail).
			// Trả false để fallback raw JSON thay vì hiện panel trống chỉ có tiêu đề.
			if (totalLines == 0)
				return false;

			bbcode = sb.ToString().TrimStart('\n');
			return true;
		}

		// Có inner_diary nhưng chỉ có text thuần — render text đó.
		if (diaryEl.TryGetProperty("text", out var textEl) && textEl.ValueKind == JsonValueKind.String)
		{
			string raw = textEl.GetString() ?? "";
			if (!string.IsNullOrWhiteSpace(raw))
			{
				var sb = new StringBuilder();
				foreach (var line in raw.Split('\n'))
				{
					if (line.EndsWith(":", StringComparison.Ordinal))
						sb.Append("[color=#88aaff][b]").Append(EscapeBbcode(line)).Append("[/b][/color]\n");
					else if (line.StartsWith("- ", StringComparison.Ordinal))
						sb.Append("[color=#a090b8]•[/color] ").Append(EscapeBbcode(line[2..])).Append('\n');
					else
						sb.Append(EscapeBbcode(line)).Append('\n');
				}
				bbcode = sb.ToString();
				return true;
			}
		}

		return false;
	}

	private static void AppendPrivateMindSection(StringBuilder sb, JsonElement menu, string key, string title)
	{
		sb.Append("\n[color=#88aaff][b]");
		sb.Append(EscapeBbcode(title));
		sb.Append("[/b][/color]\n");
		if (menu.ValueKind != JsonValueKind.Object || !menu.TryGetProperty(key, out var value))
		{
			sb.Append("  [color=#6a5a80][i]chua co du lieu[/i][/color]\n");
			return;
		}
		AppendJsonPreview(sb, value, 1);
	}

	private static void AppendJsonPreview(StringBuilder sb, JsonElement value, int indent)
	{
		string pad = new(' ', Math.Max(0, indent * 2));
		switch (value.ValueKind)
		{
			case JsonValueKind.Object:
			{
				int count = 0;
				foreach (var property in value.EnumerateObject())
				{
					if (count++ >= 10)
					{
						sb.Append(pad).Append("- ...\n");
						break;
					}
					sb.Append(pad).Append("- ").Append(EscapeBbcode(property.Name)).Append(": ");
					if (IsScalarJson(property.Value))
					{
						sb.Append(EscapeBbcode(ScalarJsonText(property.Value))).Append('\n');
					}
					else
					{
						sb.Append('\n');
						AppendJsonPreview(sb, property.Value, indent + 1);
					}
				}
				break;
			}
			case JsonValueKind.Array:
			{
				int count = 0;
				foreach (var item in value.EnumerateArray())
				{
					if (count++ >= 8)
					{
						sb.Append(pad).Append("- ...\n");
						break;
					}
					sb.Append(pad).Append("- ");
					if (IsScalarJson(item))
					{
						sb.Append(EscapeBbcode(ScalarJsonText(item))).Append('\n');
					}
					else
					{
						sb.Append('\n');
						AppendJsonPreview(sb, item, indent + 1);
					}
				}
				break;
			}
			default:
				sb.Append(pad).Append(EscapeBbcode(ScalarJsonText(value))).Append('\n');
				break;
		}
	}

	private static bool IsScalarJson(JsonElement value)
	{
		return value.ValueKind is JsonValueKind.String or JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False or JsonValueKind.Null;
	}

	private static string ScalarJsonText(JsonElement value)
	{
		return value.ValueKind switch
		{
			JsonValueKind.String => CompactText(value.GetString() ?? "", 260),
			JsonValueKind.Number => value.GetRawText(),
			JsonValueKind.True => "true",
			JsonValueKind.False => "false",
			JsonValueKind.Null => "null",
			_ => CompactText(value.GetRawText(), 360),
		};
	}

	private static string CompactText(string text, int limit)
	{
		string clean = (text ?? "").Replace("\r", " ").Replace("\n", " ").Trim();
		while (clean.Contains("  ", StringComparison.Ordinal))
			clean = clean.Replace("  ", " ", StringComparison.Ordinal);
		if (clean.Length <= limit)
			return clean;
		return clean.Substring(0, Math.Max(0, limit - 3)).TrimEnd() + "...";
	}

	private void RefreshEmotionPanelRows()
	{
		if (_emotionSummaryLabel == null)
			return;

		if (_latestEmotionDebug == null || _latestEmotionDebug.Items == null || _latestEmotionDebug.Items.Count == 0)
		{
			_emotionSummaryLabel.Text = "Cam xuc";
			if (_emotionHintLabel != null)
				_emotionHintLabel.Text = "Chua co frame cam xuc.";
			return;
		}

		string summary = string.IsNullOrWhiteSpace(_latestEmotionDebug.SummaryValue) ? "unknown" : _latestEmotionDebug.SummaryValue;
		_emotionSummaryLabel.Text = string.IsNullOrWhiteSpace(summary) || summary == "unknown"
			? "Cam xuc"
			: $"Cam xuc - {summary}";
		if (_emotionHintLabel != null)
			_emotionHintLabel.Text = _latestEmotionDebug.HasSummaryValence
				? $"Valence tong: {_latestEmotionDebug.SummaryValence:0.00}"
				: "Nhung con so chi mang tinh tham khao.";

		var numericItems = new List<EmotionDebugItem>();
		foreach (var item in _latestEmotionDebug.Items)
		{
			if (item.HasNumericValue)
				numericItems.Add(item);
		}

		for (int i = 0; i < _emotionRows.Count; i++)
		{
			if (i >= numericItems.Count)
			{
				_emotionRows[i].Row.Visible = false;
				continue;
			}

			var item = numericItems[i];
			_emotionRows[i].Row.Visible = true;
			string title = string.IsNullOrWhiteSpace(item.Label) ? item.Key : item.Label;
			string note = string.IsNullOrWhiteSpace(item.Note) ? GroupTitle(item.Group) : item.Note;
			UpdateEmotionRow(_emotionRows[i], title, note, item.NumericValue);
		}
	}

	private static string BuildMeter(float value)
	{
		float clamped = Mathf.Clamp(value, 0f, 1f);
		int filled = Mathf.RoundToInt(clamped * 10f);
		filled = Mathf.Clamp(filled, 0, 10);
		return "[" + new string('#', filled) + new string('-', 10 - filled) + "]";
	}

	private static string GroupTitle(string group)
	{
		return group switch
		{
			"core" => "loi cam xuc",
			"bond" => "gan bo",
			"friction" => "ma sat",
			"attention" => "chu y / suy nghi",
			"speech" => "ap luc noi",
			"tone" => "tone xa hoi",
			"control" => "kiem che / tiem thuc",
			"load" => "tai nhan thuc",
			"surface" => "be mat loi noi",
			_ => group,
		};
	}

	private static string EscapeBbcode(string text)
	{
		return (text ?? "").Replace("[", "\\[").Replace("]", "\\]");
	}

	private void ApplyAnimationCommand(string animation, int direction, string nextAnimation)
	{
		_nextAction = nextAnimation;
		// Chuẩn hoá alias trước (walk -> stand_walk, v.v.)
		if (_animAliases.TryGetValue(animation, out var mapped))
		{
			GD.Print($"[Anim] Alias '{animation}' -> '{mapped}'");
			animation = mapped;
		}

		// Kiểm tra animation có hợp lệ không
		if (!_validAnimations.Contains(animation))
		{
			// Nếu có direction → người dùng muốn đi → fallback về stand_walk
			string fallback = (direction == 1 || direction == -1) ? "stand_walk" : "stand";
			GD.PrintErr($"[Anim] Animation không hợp lệ: '{animation}', fallback về '{fallback}'.");
			animation = fallback;
		}
		if (direction == 1 || direction == -1)
		{
			_moveDir = direction;
			_facingDir = direction;
			GD.Print($"[Physics] Đổi hướng di chuyển thành: {direction}");
		}

		// Ngắt climb đang chạy nếu có
		if (_climbPhase != ClimbPhase.None)
		{
			_climbPhase = ClimbPhase.None;
			_climbTopTargetX = float.NaN;
			_monika.Scale = Vector2.One;
			_bubble.Scale = Vector2.One;
			_velocityY = 0f;
			_isFalling = false;
		}

		_currentAction = animation;
		_isWalking = (animation == "stand_walk");

		if (!_isWalking)
		{
			ApplyFacingForCurrentAction();
		}

		if (animation == "climb")
		{
			StartClimb();
			return;
		}

		PlaySoundForAnimation(animation);
	}

	private void StartClimb()
	{
		Vector2 screenSize = GetViewportRect().Size;
		float wallXRight = screenSize.X - _spriteHalfSize.X;
		float wallXLeft  = _spriteHalfSize.X;
		float posX = _body.Position.X;

		// Leo tường gần nhất trước
		if (wallXRight - posX <= posX - wallXLeft)
		{
			_climbUpWallX   = wallXRight;
			_climbDownWallX = wallXLeft;
		}
		else
		{
			_climbUpWallX   = wallXLeft;
			_climbDownWallX = wallXRight;
		}

		_climbTopTargetX = _nextAction == "climb_top"
			? (!float.IsNaN(_targetX) ? _targetX : _climbUpWallX)
			: float.NaN;

		_climbPhase = ClimbPhase.GoingToWall;
		PlaySoundForAnimation("climb");
	}

	private void UpdateClimbMovement(ref Vector2 pos, Vector2 screenSize, float d)
	{
		float ceilingY = _spriteHalfSize.Y;
		float floorY   = screenSize.Y - _spriteHalfSize.Y;

		switch (_climbPhase)
		{
			case ClimbPhase.GoingToWall:
				float dx = _climbUpWallX - pos.X;
				pos.X += Mathf.Sign(dx) * _moveSpeed * d;
				if (Mathf.Abs(dx) < _moveSpeed * d + 2f)
				{
					pos.X = _climbUpWallX;
					_climbPhase = ClimbPhase.Up;
				}
				break;

			case ClimbPhase.Up:
				pos.X  = _climbUpWallX;
				pos.Y -= ClimbSpeed * d;
				if (pos.Y <= ceilingY)
				{
					pos.Y = ceilingY;
					_climbPhase = ClimbPhase.Top;
				}
				break;

			case ClimbPhase.Top:
				pos.Y = ceilingY;
				float topTargetX = float.IsNaN(_climbTopTargetX) ? _climbDownWallX : _climbTopTargetX;
				float dx2 = topTargetX - pos.X;
				pos.X += Mathf.Sign(dx2) * _moveSpeed * d;
				if (Mathf.Abs(dx2) < _moveSpeed * d + 2f)
				{
					pos.X = topTargetX;
					if (float.IsNaN(_climbTopTargetX))
					{
						_climbPhase = ClimbPhase.Down;
					}
					else
					{
						_climbPhase = ClimbPhase.TopHold;
						_currentAction = "climb_top";
						_nextAction = "";
						_targetX = float.NaN;
					}
				}
				break;

			case ClimbPhase.TopHold:
				pos.Y = ceilingY;
				if (!float.IsNaN(_climbTopTargetX))
					pos.X = _climbTopTargetX;
				_velocityY = 0f;
				_isFalling = false;
				break;

			case ClimbPhase.Down:
				pos.X  = _climbDownWallX;
				pos.Y += ClimbSpeed * d;
				if (pos.Y >= floorY)
				{
					pos.Y          = floorY;
					_climbPhase    = ClimbPhase.None;
					_velocityY     = 0f;
					_isFalling     = false;
					_currentAction = "stand";
					_isWalking     = false;
					_climbTopTargetX = float.NaN;
					_monika.Scale  = Vector2.One;
					_bubble.Scale  = Vector2.One;
				}
				break;
		}
	}

	private void OnBounceAnimationFinished()
	{
		_motion.NotifyAnimationFinished();
	}

	private void OnAudioFinished()
	{
	}

	private void PlaySoundForAnimation(string animation)
	{
		_audio?.PlayForAnimation(animation);
	}

	private void ApplyAnimation(string animation)
	{
		GD.Print($"[Anim] Áp dụng animation: \"{animation}\"");
		if (animation == "stand_walk")
		{
			_isWalking = true;
			_monika.Play("stand_walk");
			GD.Print("[Anim] Chế độ đi bộ BẬT.");
		}
		else
		{
			_isWalking = false;
			_monika.Scale = new Vector2(1f, 1f);
			_monika.Play(animation);
			GD.Print($"[Anim] Chế độ đi bộ TẮT. Đang phát: {animation}");
		}
	}

	private void StartVisionProcess()
	{
		_processes?.StartVision(BuildServiceConfig());
	}

	private void StopVisionProcess()
	{
		_processes?.StopVision();
	}

	private void ToggleVisionProcess()
	{
		_processes?.ToggleVision(BuildServiceConfig());
	}

	private string GetProjectRoot()
	{
		return ProjectSettings.GlobalizePath("res://");
	}

	private string GetLlamaServerFullPath()
	{
		return Path.Combine(GetProjectRoot(), LlamaServerPath.Replace('/', Path.DirectorySeparatorChar));
	}

	private string GetModelFullPath()
	{
		return Path.Combine(GetProjectRoot(), ModelPath.Replace('/', Path.DirectorySeparatorChar));
	}

	private string GetMmprojFullPath()
	{
		return Path.Combine(GetProjectRoot(), MmprojPath.Replace('/', Path.DirectorySeparatorChar));
	}

	private bool IsLlamaServerReachable()
	{
		try
		{
			using var client = new TcpClient();
			var result = client.BeginConnect("127.0.0.1", LlamaServerPort, null, null);
			bool connected = result.AsyncWaitHandle.WaitOne(TimeSpan.FromMilliseconds(200));
			if (!connected)
				return false;
			client.EndConnect(result);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private bool ShouldLogVisionOutput(string line)
	{
		if (string.IsNullOrWhiteSpace(line))
			return false;

		string trimmed = line.Trim();

		return
			trimmed.Contains("[Init]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Shutdown]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Loop]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Parse]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[LLM]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Vision]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Chat]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[AI Decision]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[AI Tư duy]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[AI Chain of Thought]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[chat raw]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[directive raw]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[raw]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Lỗi", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Error]", StringComparison.OrdinalIgnoreCase);
	}

	private bool ShouldLogVisionStderr(string line)
	{
		if (string.IsNullOrWhiteSpace(line))
			return false;

		return
			line.Contains("Traceback", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("Exception", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("error loading model", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("failed to load model", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("No connection could be made", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("JSON không hợp lệ", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("main: model loaded", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("server is listening", StringComparison.OrdinalIgnoreCase);
	}

	private bool ShouldLogLlamaOutput(string line)
	{
		if (string.IsNullOrWhiteSpace(line))
			return false;

		return
			line.Contains("main: model loaded", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("server is listening", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("failed to load model", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("error loading model", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("Traceback", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("Exception", StringComparison.OrdinalIgnoreCase);
	}

	private bool StartLlamaServerProcess()
	{
		return _processes?.StartLlamaServer(BuildServiceConfig()) ?? false;
	}

	private void StopLlamaServerProcess()
	{
		_processes?.StopLlamaServer();
	}

	private void ToggleLlamaServerProcess()
	{
		_processes?.ToggleLlamaServer(BuildServiceConfig());
	}

	private ErisServiceConfig BuildServiceConfig()
	{
		return new ErisServiceConfig
		{
			PythonExecutable = PythonExecutable,
			VisionScriptPath = VisionScriptPath,
			LlamaServerPath = LlamaServerPath,
			ModelPath = ModelPath,
			MmprojPath = MmprojPath,
			EnableLocalVisionInput = EnableLocalVisionInput,
			LlamaServerPort = LlamaServerPort,
			LlamaServerNgl = LlamaServerNgl,
			LlamaServerCtx = LlamaServerCtx,
			LlamaServerFlashAttn = LlamaServerFlashAttn,
			LlamaServerExtraArgs = LlamaServerExtraArgs,
			EnableRemoteCognitionApi = EnableRemoteCognitionApi,
			EnableLocalStyleRewrite = EnableLocalStyleRewrite,
			DefaultRemoteApiKey = DefaultRemoteApiKey,
			RemoteApiProvider = RemoteApiProvider,
			RemoteApiBaseUrl = RemoteApiBaseUrl,
			RemoteApiModelName = RemoteApiModelName,
		};
	}

	private void UpdateServiceButtons()
	{
		// Không còn nút điều khiển service trên UI.
	}
}
