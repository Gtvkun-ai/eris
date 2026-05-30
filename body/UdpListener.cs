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
	private Button _contextChatButton;
	private Button _contextTouchButton;
	private Button _contextForceSpeakButton;
	private Button _contextEmotionButton;
	private Button _contextCloseButton;
	private Panel _emotionPanel;
	private RichTextLabel _emotionText;
	private Label _emotionSummaryLabel;
	private Label _emotionHintLabel;
	private readonly List<EmotionRowView> _emotionRows = new();
	private Texture2D _emotionFillTexture;
	private Texture2D _emotionTrackTexture;
	private Texture2D _switchOnTexture;
	private Texture2D _switchOffTexture;
	private TextureRect _switchTexture;
	private bool _emotionSwitchEnabled = true;
	private LineEdit _chatInput;
	private PacketPeerUdp _chatSend = new PacketPeerUdp();
	private Tween _textTween;
	private static readonly Vector2 CharacterContextMenuMinSize = new(170f, 188f);
	private static readonly Vector2 EmotionPanelMinSize = new(760f, 506f);
	private const float EmotionBarWidth = 160f;
	private const float EmotionBarHeight = 26f;
	private readonly Random _rng = new Random();
	private EmotionDebug _latestEmotionDebug;
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
	_characterContextMenu = GetNode<Panel>("CanvasLayer/Control/CharacterContextMenu");
	_contextChatButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/ChatButton");
	_contextTouchButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/TouchButton");
	_contextForceSpeakButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/ForceSpeakButton");
	_contextEmotionButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/EmotionButton");
	_contextCloseButton = GetNode<Button>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer/CloseButton");
		_characterContextMenu.CustomMinimumSize = CharacterContextMenuMinSize;
		_characterContextMenu.Size = CharacterContextMenuMinSize;
		_characterContextMenu.ZIndex = 100;
		_emotionPanel = GetNode<Panel>("CanvasLayer/Control/EmotionPanel");
		_emotionPanel.CustomMinimumSize = EmotionPanelMinSize;
		_emotionPanel.Size = EmotionPanelMinSize;
		_emotionPanel.ZIndex = 99;
		_emotionText = GetNodeOrNull<RichTextLabel>("CanvasLayer/Control/EmotionPanel/VBoxContainer/ScrollContainer/EmotionText");
		_chatInput = GetNode<LineEdit>("CanvasLayer/Control/ChatPanel/HBoxContainer/LineEdit");
	GetNode<Button>("CanvasLayer/Control/ChatPanel/HBoxContainer/SendButton").Pressed += OnSendPressed;
	GetNode<Button>("CanvasLayer/Control/ChatPanel/HBoxContainer/CloseButton").Pressed += CloseChatPanel;
	_contextChatButton.Pressed += OnContextChatPressed;
	_contextTouchButton.Pressed += OnContextTouchPressed;
	_contextForceSpeakButton.Pressed += OnContextForceSpeakPressed;
	_contextEmotionButton.Pressed += OnContextEmotionPressed;
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

		var closeButton = CreateTextureButton("res://asset/Resource/x.png", CloseEmotionPanel, new Vector2(44f, 44f));
		closeButton.Position = new Vector2(684f, 24f);
		_emotionPanel.AddChild(closeButton);
		var minimizeButton = CreateTextureButton("res://asset/Resource/_.png", () => _emotionPanel.Visible = false, new Vector2(34f, 34f));
		minimizeButton.Position = new Vector2(642f, 29f);
		_emotionPanel.AddChild(minimizeButton);

		var modeButton = CreateTextureButton("res://asset/Resource/dev mode.png", () => { }, new Vector2(176f, 48f));
		modeButton.Position = new Vector2(536f, 124f);
		_emotionPanel.AddChild(modeButton);
		var moreButton = CreateTextureButton("res://asset/Resource/more.png", () => { }, new Vector2(36f, 36f));
		moreButton.Position = new Vector2(668f, 130f);
		_emotionPanel.AddChild(moreButton);

		_switchTexture = new TextureRect
		{
			Texture = _switchOnTexture,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			Position = new Vector2(666f, 194f),
			Size = new Vector2(58f, 34f),
			CustomMinimumSize = new Vector2(58f, 34f),
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
		};
		_switchTexture.GuiInput += OnEmotionSwitchGuiInput;
		_emotionPanel.AddChild(_switchTexture);

		var resetButton = CreateTextureButton("res://asset/Resource/reset all mode.png", () => SendChatSignal("reset_all_mood"), new Vector2(190f, 40f));
		resetButton.Position = new Vector2(535f, 286f);
		_emotionPanel.AddChild(resetButton);
		var randomButton = CreateTextureButton("res://asset/Resource/randomize mode.png", () => SendChatSignal("randomize_mood"), new Vector2(190f, 40f));
		randomButton.Position = new Vector2(535f, 330f);
		_emotionPanel.AddChild(randomButton);
		var console = new TextureRect
		{
			Texture = GD.Load<Texture2D>("res://asset/Resource/console output.png"),
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			Position = new Vector2(535f, 374f),
			Size = new Vector2(190f, 112f),
			CustomMinimumSize = new Vector2(190f, 112f),
		};
		_emotionPanel.AddChild(console);
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
