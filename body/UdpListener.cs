using Godot;
using System;
using System.Collections.Generic;
using System.IO;
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

	private sealed class PrivateMindDiaryItem
	{
		public string Text { get; init; } = "";
		public string Badge { get; init; } = "";
	}

	private sealed class PrivateMindDiarySection
	{
		public string Title { get; init; } = "";
		public List<PrivateMindDiaryItem> Items { get; init; } = new();
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
	[Export] public bool AutoStartVision = true;
	[Export] public bool EnableRemoteCognitionApi = true;
	[Export(PropertyHint.Password)] public string DefaultRemoteApiKey = "";
	[Export] public string RemoteApiProvider = "gemini";
	[Export] public string RemoteApiBaseUrl = "https://generativelanguage.googleapis.com/v1beta";
	[Export] public string RemoteApiModelName = "gemma-4-26b-a4b-it";
	[ExportGroup("Desktop Overlay")]
	[Export] public bool EnableDesktopOverlayWindow = true;
	[Export] public bool KeepWindowAlwaysOnTop = true;
	[Export] public bool UseBorderlessWindow = true;
	[Export] public bool UseTransparentWindow = true;
	[Export] public bool FillScreenOverlay = true;
	[Export] public bool EnableMousePassthrough = true;

	private float _moveSpeed = 60f;   
	private float _moveDir = 1f;      
	private int _facingDir = -1;      
	private bool _isWalking = false;
	private string _currentAction = "stand";
	private float _gravity = 980f; // Gia tốc trọng trường tiêu chuẩn
	private float _velocityY = 0f;
	private bool _isFalling = false;
	private Vector2 _spriteHalfSize; // Lấy từ CollisionShape2D trong _Ready()
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
	private Button _contextExitButton;
	private Button _contextCloseButton;
	private Panel _emotionPanel;
	private RichTextLabel _emotionText;
	private Panel _privateMindPanel;
	private RichTextLabel _privateMindText;
	private VBoxContainer _privateMindSectionList;
	private Label _emotionSummaryLabel;
	private Label _emotionHintLabel;
	private readonly List<EmotionRowView> _emotionRows = new();
	private Texture2D _emotionFillTexture;
	private Texture2D _emotionTrackTexture;

	// Casual mode UI
	private bool _isCasualMode = false;
	private Label _casualNarrativeLabel;
	private Control _moodDotCanvas;
	private Control _casualContentRoot;  // container cho toàn bộ casual nodes — xoá 1 node là xong
	internal float _moodDotValence;
	internal float _moodDotArousal;
	internal string _moodStateName = "";   // do AI đặt, ví dụ "calm", "excited"
	internal string _moodStateDesc = "";   // mô tả phụ từ AI, ví dụ "ít căng thẳng"
	private readonly List<(Control FillClip, Control Fill, Label WordLabel)> _casualBars = new();

	// Dev mode UI
	private Control _devContentRoot;
	private Label _devHeaderLabel;          // valence / arousal / state
	private VBoxContainer _devItemList;     // container chứa tất cả raw item rows
	private Texture2D _switchOnTexture;
	private Texture2D _switchOffTexture;
	private Texture2D _chatFrameTexture;
	private Texture2D _chatSubmitTexture;
	private Texture2D _chatCloseTexture;
	private Texture2D _privateMindFrameTexture;
	private Texture2D _privateMindScrollCapTexture;
	private Texture2D _privateMindScrollTrackTexture;
	private Texture2D _privateMindScrollFillTexture;
	private TextureRect _switchTexture;
	private ScrollContainer _privateMindScrollContainer;
	private TextureRect _privateMindFrameRect;
	private TextureRect _privateMindScrollCapRect;
	private TextureRect _privateMindScrollTrackRect;
	private TextureRect _privateMindScrollFillRect;
	private OptionButton _modeDropdown;
	private bool _emotionSwitchEnabled = true;
	private LineEdit _debugCommandInput;   // ô nhập lệnh debug
	private Label _debugCommandStatus;     // báo lệnh debug vừa gửi
	private LineEdit _chatInput;
	private PacketPeerUdp _chatSend = new PacketPeerUdp();
	// Tự ẩn khung chat sau khi Ngài ngừng tương tác, để màn hình không bị panel
	// nằm lì. Khớp với mô hình "recency" ở backend (autonomous tự sống lại).
	private ulong _chatLastActivityMs = 0;
	[Export] public float ChatAutoHideSeconds = 20f;
	// Bong bóng thoại chỉ hiện khi Eris đang nói; tự ẩn sau khi gõ xong + chừa thời
	// gian đọc. 0 = không tự ẩn (hiện mãi cho tới câu kế tiếp).
	[Export] public float BubbleReadSeconds = 20f;
	private ulong _bubbleHideAtMs = 0;
	private Tween _textTween;
	private static readonly Vector2 CharacterContextMenuMinSize = new(212f, 348f);
	private static readonly Vector2 EmotionPanelMinSize = new(760f, 506f);
	private static readonly Vector2 PrivateMindPanelMinSize = new(1040f, 624f);

	// Tỉ lệ phần khung banner header nằm TRÊN viền card (nhô ra ngoài). 0.5 = 50/50; >0.5 = nổi hẳn lên.
	private const float DiaryBannerAboveRatio = 0.6f;

	// Inner Diary — sidebar (Mood / Concern Stack / Memory Echo)
	private ProgressBar _diaryValenceBar;
	private ProgressBar _diaryArousalBar;
	private Label _diaryValenceLabel;
	private Label _diaryArousalLabel;
	private Label _diaryMoodQuoteLabel;
	private TextureRect _diaryMoodFace;     // ảnh mặt động (9 face), null texture = fallback chấm hồng
	private string _diaryMoodFaceAsset = ""; // asset đang hiển thị, tránh load lại mỗi frame
	private PanelContainer _diaryMoodFaceBg; // nền chấm hồng, chỉ hiện khi chưa có ảnh face
	private VBoxContainer _diaryConcernList;
	private bool _diaryConcernExpanded;
	private readonly List<(string Theme, float Pct)> _diaryConcernData = new();
	private const int DiaryConcernCollapsedCount = 2;
	private Control _diaryConcernToggle; // nút "+ N mục khác" / "Thu gọn"
	private Label _diaryMemoryEchoLabel;
	private Label _diaryMemoryEchoMetaLabel;
	private const float EmotionBarWidth = 160f;
	private const float EmotionBarHeight = 26f;
	private readonly Random _rng = new Random();
	private EmotionDebug _latestEmotionDebug;
	private string _latestPrivateMindDebugJson = "";
	private const string PrivateMindStatePath = "user://inner_diary_state.json";	private Control _bubble;
	private string _latestDepthV2Json = "";
	private const string DepthV2StatePath = "user://depth_v2_state.json";
	private bool _grabModeArmed = false;
	private bool _isDraggingCharacter = false;
	private Control _draggingPanel = null;
	private Vector2 _panelDragOffset = Vector2.Zero;
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

	// Đổi font cho TOÀN BỘ UI context-menu (chat, mô hình ngài, private mind, emotion,
	// menu chuột phải, chiều sâu …) bằng cách gắn Theme lên node Control gốc — mọi
	// panel con kế thừa. CHỈ đổi typeface (DefaultFont), KHÔNG đặt DefaultFontSize để
	// giữ nguyên cỡ chữ mỗi panel đã canh, tránh vỡ layout. Không bao giờ ném.
	private void ApplyGlobalUiFontTheme()
	{
		try
		{
			_depthFontRegular ??= LoadDepthFont("Mali-Regular.ttf");
			_depthFontBold ??= LoadDepthFont("Mali-SemiBold.ttf") ?? _depthFontRegular;
			Font def = _depthFontRegular ?? DepthSystemFont();

			var root = GetNodeOrNull<Control>("CanvasLayer/Control");
			if (root == null)
				return;
			var theme = root.Theme ?? new Theme();
			theme.DefaultFont = def;        // chỉ đổi mặt chữ
			root.Theme = theme;             // mọi Control con kế thừa
		}
		catch (Exception ex)
		{
			GD.Print($"[ui font] apply global theme fail: {ex.Message}");
		}
	}

	public override void _Ready()
	{
		RunLogger.Initialize();
		ApplyGlobalUiFontTheme();
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
		_anchorPanel = new Panel
		{
			Name = "AnchorPanel",
			Visible = false,
			CustomMinimumSize = AnchorPanelMinSize,
			Size = AnchorPanelMinSize,
			ZIndex = 98,
		};
		GetNode<Control>("CanvasLayer/Control").AddChild(_anchorPanel);
		BuildAnchorPanelUi();
		_depthPanel = new Panel
		{
			Name = "DepthPanel",
			Visible = false,
			CustomMinimumSize = DepthPanelMinSize,
			Size = DepthPanelMinSize,
			ZIndex = 98,
		};
		GetNode<Control>("CanvasLayer/Control").AddChild(_depthPanel);
		BuildDepthPanelUi();
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
	if (_contextAnchorButton != null)
		_contextAnchorButton.Pressed += OnContextAnchorPressed;
	if (_contextDepthButton != null)
		_contextDepthButton.Pressed += OnContextDepthPressed;
	if (_contextExitButton != null)
		_contextExitButton.Pressed += OnContextExitPressed;
	_contextCloseButton.Pressed += CloseCharacterContextMenu;
		_chatInput.TextSubmitted += _ => OnSendPressed();
		_chatInput.TextChanged += _ => MarkChatActivity();
		_chatSend.ConnectToHost("127.0.0.1", 4243);
		BuildEmotionPanelUi();
		BuildTutorPanelUi();

		// Cho phép kéo-di-chuyển các panel nổi (kéo từ vùng nền, không đụng nút con).
		MakePanelDraggable(_emotionPanel);
		MakePanelDraggable(_privateMindPanel);
		MakePanelDraggable(_anchorPanel);
		MakePanelDraggable(_chatPanel);
		MakePanelDraggable(_tutorPanel);
		MakePanelDraggable(_depthPanel);

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
		// Khởi động ẩn bong bóng; chỉ hiện khi Eris thực sự nói (xem ApplyTypewriterEffect).
		_bubble.Visible = false;

		_monika.AnimationFinished += OnBounceAnimationFinished;
		GD.Print($"[Ready] Đang lắng nghe UDP cổng 4242. HalfSize={_spriteHalfSize}");
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

		if (FillScreenOverlay)
		{
			// Phủ trọn màn hình vật lý (gồm cả vùng taskbar) để Eris bò khắp nơi,
			// kết hợp Borderless + AlwaysOnTop nên vẽ đè cả lên taskbar.
			int screen = DisplayServer.WindowGetCurrentScreen();
			Vector2I screenPos = DisplayServer.ScreenGetPosition(screen);
			Vector2I screenSize = DisplayServer.ScreenGetSize(screen);
			DisplayServer.WindowSetSize(screenSize);
			DisplayServer.WindowSetPosition(screenPos);
		}

		// Mặc định cho chuột xuyên qua toàn bộ cửa sổ; mỗi frame sẽ chỉ "mở khoá"
		// vùng quanh Eris (xem UpdateMousePassthrough) để desktop phía sau vẫn bấm được.
		if (EnableMousePassthrough)
			UpdateMousePassthrough();
	}

	private bool _passthroughFullCapture = true;
	private Rect2 _passthroughLastRect = new(Vector2.Zero, Vector2.Zero);

	private void UpdateMousePassthrough()
	{
		if (!EnableDesktopOverlayWindow || !EnableMousePassthrough)
			return;

		// Đang mở panel/menu/chat hoặc đang kéo nhân vật → để cả cửa sổ nhận chuột,
		// nếu không các nút trên panel sẽ bị click xuyên mất.
		bool uiActive =
			(_chatPanel?.Visible ?? false)
			|| (_characterContextMenu?.Visible ?? false)
			|| (_emotionPanel?.Visible ?? false)
			|| (_privateMindPanel?.Visible ?? false)
			|| (_anchorPanel?.Visible ?? false)
			|| (_depthPanel?.Visible ?? false)
			|| _grabModeArmed
			|| _isDraggingCharacter;

		if (uiActive)
		{
			if (!_passthroughFullCapture)
			{
				// Mảng rỗng = tắt passthrough = cả cửa sổ chặn chuột (UI bấm được).
				DisplayServer.WindowSetMousePassthrough(Array.Empty<Vector2>());
				_passthroughFullCapture = true;
			}
			return;
		}

		if (_body == null)
			return;

		// Vùng quanh nhân vật (nới thêm cho dễ click).
		float pad = 12f;
		Vector2 tl = _body.GlobalPosition - _spriteHalfSize - new Vector2(pad, pad);
		Vector2 size = _spriteHalfSize * 2f + new Vector2(pad * 2f, pad * 2f);
		var rect = new Rect2(tl, size);

		// Khi bong bóng thoại đang hiện, gộp luôn vùng của nó vào passthrough.
		// Vừa cho phép click trúng bong bóng, vừa buộc cửa sổ overlay trong suốt
		// vẽ lại vùng đó ngay (nếu không bong bóng hay bị "kẹt" không hiện cho tới
		// khi có sự kiện cửa sổ khác như mở context menu).
		bool bubbleVisible = _bubble != null && _bubble.Visible && _bubble.Size.X > 0f;
		if (bubbleVisible)
		{
			var bubbleRect = new Rect2(_bubble.GlobalPosition, _bubble.Size);
			rect = rect.Merge(bubbleRect);
		}

		// Tránh gọi mỗi frame khi nhân vật đứng yên và bong bóng không đổi.
		bool unchanged =
			!_passthroughFullCapture
			&& _passthroughLastRect.Position.DistanceTo(rect.Position) < 2f
			&& _passthroughLastRect.Size.DistanceTo(rect.Size) < 2f;
		if (unchanged)
			return;

		var region = new[]
		{
			rect.Position,
			rect.Position + new Vector2(rect.Size.X, 0f),
			rect.Position + rect.Size,
			rect.Position + new Vector2(0f, rect.Size.Y),
		};
		DisplayServer.WindowSetMousePassthrough(region);
		_passthroughFullCapture = false;
		_passthroughLastRect = rect;
	}

	public override void _ExitTree()
	{
		StopVisionProcess();
		_udp.Close();
		_chatSend.Close();
		RunLogger.Shutdown();
	}


	public override void _Process(double delta)
	{
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
		UpdateMousePassthrough();
		if (_privateMindPanel != null && _privateMindPanel.Visible)
		{
			UpdatePrivateMindDecorLayout();
			UpdatePrivateMindScrollDecor();
		}

		UpdateChatPanelAutoHide();
		UpdateBubbleAutoHide();
		UpdateTutorPanelAutoHide();

		if (_udp.GetAvailablePacketCount() > 0)
		{
			string raw = Encoding.UTF8.GetString(_udp.GetPacket());
			ParseAndApply(raw);
		}
	}

	public override void _Input(InputEvent @event)
	{
		// Đang kéo một panel: xử lý di chuyển + thả tại đây để kéo mượt kể cả khi
		// con trỏ rời khỏi vùng panel (GuiInput không nhận motion khi ra ngoài).
		if (_draggingPanel != null)
		{
			if (@event is InputEventMouseMotion)
			{
				UpdatePanelDrag();
				GetViewport().SetInputAsHandled();
				return;
			}
			if (@event is InputEventMouseButton panelRelease
				&& panelRelease.ButtonIndex == MouseButton.Left
				&& !panelRelease.Pressed)
			{
				_draggingPanel = null;
				GetViewport().SetInputAsHandled();
				return;
			}
		}

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
				// Click nút "+ mục khác"/"Thu gọn" → đảo trạng thái.
				if (_diaryConcernToggle != null && IsMouseOverControl(_diaryConcernToggle, mouseEvent.Position))
				{
					_diaryConcernExpanded = !_diaryConcernExpanded;
					RenderDiaryConcernList();
				}
				// Bấm ra ngoài danh sách Concern (mà vẫn trong panel) thì thu gọn lại.
				else if (_diaryConcernExpanded && _diaryConcernList != null
					&& !IsMouseOverControl(_diaryConcernList, mouseEvent.Position))
				{
					_diaryConcernExpanded = false;
					RenderDiaryConcernList();
				}
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

	private void MarkChatActivity()
	{
		_chatLastActivityMs = Time.GetTicksMsec();
	}

	private void UpdateChatPanelAutoHide()
	{
		if (_chatPanel == null || !_chatPanel.Visible)
			return;
		if (ChatAutoHideSeconds <= 0f)
			return;
		// Đang soạn dở (còn chữ trong ô) thì giữ panel, đừng nuốt mất câu của Ngài.
		if (!string.IsNullOrWhiteSpace(_chatInput?.Text))
			return;
		ulong idleMs = Time.GetTicksMsec() - _chatLastActivityMs;
		if (idleMs < (ulong)(ChatAutoHideSeconds * 1000f))
			return;
		CloseChatPanel();
	}

	// Ẩn bong bóng thoại sau khi đã nói xong + chừa thời gian đọc, để màn hình
	// không bị khung thoại nằm lì khi Eris im lặng.
	private void UpdateBubbleAutoHide()
	{
		if (_bubble == null || !_bubble.Visible)
			return;
		if (_bubbleHideAtMs == 0)
			return;
		if (Time.GetTicksMsec() < _bubbleHideAtMs)
			return;
		_bubble.Visible = false;
		_bubbleHideAtMs = 0;
	}

	private void ToggleChatPanel()
	{
		CloseCharacterContextMenu();
		if (_chatPanel.Visible)
			CloseChatPanel();
		else
		{
			_bodyAutonomy?.RecordUserInteraction();
			MarkChatActivity();
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
		{
			MarkChatActivity();
			_chatInput.GrabFocus();
		}
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

	private void OnContextExitPressed()
	{
		// Thoát hẳn ERIS: đóng menu, dừng tiến trình con (vision...) rồi tắt app.
		CloseCharacterContextMenu();
		GD.Print("[Exit] Người dùng yêu cầu thoát ERIS qua context menu.");
		StopVisionProcess();
		GetTree().Quit();
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
			Mathf.Max(0f, (screenSize.X - PrivateMindPanelMinSize.X) * 0.5f),
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
		float targetHeight = 64f;
		float outerPadding = Mathf.Clamp(7f * scale, 5f, 7f);
		// Leave room for the decorative "chat" button area baked into the frame texture.
		float leftInset = Mathf.Clamp(72f * scale, 44f, 72f);
		float gap = Mathf.Clamp(8f * scale, 6f, 8f);
		float buttonHeight = Mathf.Clamp(40f * scale, 32f, 40f);
		// Icon removed from ChatPanel; keep layout compact.
		float submitWidth = Mathf.Clamp(88f * scale, 70f, 88f);
		float closeWidth = Mathf.Clamp(40f * scale, 32f, 40f);
		float fontSize = Mathf.Clamp(Mathf.RoundToInt(16f * scale), 12, 16);
		float buttonFontSize = Mathf.Clamp(Mathf.RoundToInt(16f * scale), 12, 16);
		float closeFontSize = Mathf.Clamp(Mathf.RoundToInt(14f * scale), 12, 14);
		float radius = Mathf.Clamp(Mathf.RoundToInt(12f * scale), 9, 12);
		float inputPadding = Mathf.Clamp(12f * scale, 9f, 12f);
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
		float slice = Mathf.Clamp(12f * scale, 8f, 12f);
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
			if (_contextAnchorButton == null)
			{
				_contextAnchorButton = new Button { Name = "AnchorButton" };
				container.AddChild(_contextAnchorButton);
				int closeIndex = _contextCloseButton != null ? _contextCloseButton.GetIndex() : container.GetChildCount() - 1;
				container.MoveChild(_contextAnchorButton, Mathf.Max(0, closeIndex));
			}
			if (_contextDepthButton == null)
			{
				_contextDepthButton = new Button { Name = "DepthButton" };
				container.AddChild(_contextDepthButton);
				int closeIndex = _contextCloseButton != null ? _contextCloseButton.GetIndex() : container.GetChildCount() - 1;
				container.MoveChild(_contextDepthButton, Mathf.Max(0, closeIndex));
			}
			if (_contextExitButton == null)
			{
				_contextExitButton = new Button { Name = "ExitButton" };
				container.AddChild(_contextExitButton);
				int closeIndex = _contextCloseButton != null ? _contextCloseButton.GetIndex() : container.GetChildCount() - 1;
				container.MoveChild(_contextExitButton, Mathf.Max(0, closeIndex));
			}
		}

		ConfigureContextMenuButton(_contextChatButton, "Chat", "res://asset/Resource/chat.png");
		ConfigureContextMenuButton(_contextTouchButton, "Cham / Nem", "res://asset/Resource/tought.png");
		ConfigureContextMenuButton(_contextForceSpeakButton, "Noi ngay", "res://asset/Resource/force.png");
		ConfigureContextMenuButton(_contextEmotionButton, "Cam xuc", "res://asset/Resource/emotion.png");
		ConfigureContextMenuButton(_contextPrivateMindButton, "Private Mind", "res://asset/Resource/emotion.png");
		ConfigureContextMenuButton(_contextAnchorButton, "Mo Hinh Ngai", "res://asset/Resource/emotion.png");
		ConfigureContextMenuButton(_contextDepthButton, "Chieu Sau", "res://asset/Resource/emotion.png");
		ConfigureContextMenuButton(_contextExitButton, "Thoat ERIS", "res://asset/Resource/exit.png");
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
		_emotionPanel.ClipContents = true;
		foreach (Node child in _emotionPanel.GetChildren())
		{
			_emotionPanel.RemoveChild(child);
			child.QueueFree();
		}

		_emotionTrackTexture = GD.Load<Texture2D>("res://asset/Resource/feel 100.png");
		_emotionFillTexture = GD.Load<Texture2D>("res://asset/Resource/feel.png");
		_switchOnTexture = GD.Load<Texture2D>("res://asset/Resource/on.png");
		_switchOffTexture = GD.Load<Texture2D>("res://asset/Resource/off.png");

		_emotionRows.Clear();
		_casualBars.Clear();
		_casualNarrativeLabel = null;
		_moodDotCanvas = null;
		_emotionSummaryLabel = null;
		_emotionHintLabel = null;

		var background = new TextureRect
		{
			Texture = GD.Load<Texture2D>("res://asset/Resource/ui clear.png"),
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		background.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_emotionPanel.AddChild(background);

		// Shared: window controls + right-side DEBUG panel
		var windowControls = CreateWindowControlCapsule(() => _emotionPanel.Visible = false, CloseEmotionPanel);
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

		// Khung DEBUG: ô nhập lệnh tay (góc dưới phải) — gõ lệnh rồi Enter/Chạy.
		BuildDebugCommandPanel();

		// Build left-side content theo mode hiện tại
		if (_isCasualMode)
			BuildCasualContent();
		else
			BuildDevContent();
	}

	// ── Dev mode content ──────────────────────────────────────────────────────

	// Màu sắc dev mode — monochrome hơn, hồng nhạt tông lạnh
	private static readonly Color DevBg        = new(0.98f, 0.96f, 0.975f, 0.96f);
	private static readonly Color DevBorder     = new(0.90f, 0.76f, 0.84f, 0.80f);
	private static readonly Color DevGroupFg    = new(0.72f, 0.30f, 0.52f, 1.00f);  // group header
	private static readonly Color DevKeyFg      = new(0.22f, 0.10f, 0.18f, 0.90f);  // key name
	private static readonly Color DevValFg      = new(0.55f, 0.15f, 0.35f, 1.00f);  // numeric value
	private static readonly Color DevNoteFg     = new(0.58f, 0.38f, 0.50f, 0.75f);  // note
	private static readonly Color DevBarTrack   = new(0.93f, 0.84f, 0.90f, 0.70f);
	private static readonly Color DevBarFill    = new(0.95f, 0.45f, 0.68f, 0.85f);
	private static readonly Color DevHeaderFg   = new(0.30f, 0.06f, 0.22f, 0.95f);
	private static readonly Color DevHintFg     = new(0.50f, 0.24f, 0.38f, 0.75f);

	private const float DevBarW  = 72f;
	private const float DevBarH  = 7f;
	private const float DevRowH  = 18f;

	private void BuildDevContent()
	{
		// ── Root container ────────────────────────────────────────────────
		var root = new Control { MouseFilter = Control.MouseFilterEnum.Ignore };
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_emotionPanel.AddChild(root);
		_devContentRoot = root;

		const float SafeX  = 46f;
		const float SafeW  = 440f;
		const float StartY = 108f;

		// ── Header chip: valence | arousal | state ────────────────────────
		var headerChip = new Panel
		{
			Position    = new Vector2(SafeX, StartY),
			Size        = new Vector2(SafeW, 28f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		headerChip.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor     = new Color(1f, 0.94f, 0.97f, 0.88f),
			BorderColor = DevBorder,
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10, CornerRadiusTopRight = 10,
			CornerRadiusBottomLeft = 10, CornerRadiusBottomRight = 10,
		});
		root.AddChild(headerChip);

		_devHeaderLabel             = CreateUiLabel("valence —  |  arousal —  |  state —", 11, DevHeaderFg);
		_devHeaderLabel.Position    = new Vector2(SafeX + 10f, StartY + 6f);
		_devHeaderLabel.Size        = new Vector2(SafeW - 12f, 20f);
		_devHeaderLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_devHeaderLabel.ClipText    = true;
		root.AddChild(_devHeaderLabel);

		// ── Scroll container cho raw items ────────────────────────────────
		const float ScrollY = StartY + 34f;
		const float ScrollH = 302f;   // 474 (safe bottom) - 142 (ScrollY) - 22 (hint) - 8 (padding)

		var scrollBg = new Panel
		{
			Position    = new Vector2(SafeX, ScrollY),
			Size        = new Vector2(SafeW, ScrollH),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		scrollBg.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor     = DevBg,
			BorderColor = DevBorder,
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14, CornerRadiusTopRight = 14,
			CornerRadiusBottomLeft = 14, CornerRadiusBottomRight = 14,
		});
		root.AddChild(scrollBg);

		var scroll = new ScrollContainer
		{
			Position = new Vector2(SafeX + 6f, ScrollY + 6f),
			Size     = new Vector2(SafeW - 12f, ScrollH - 12f),
		};
		scroll.AddThemeConstantOverride("v_scrollbar_separation", 0);
		root.AddChild(scroll);

		_devItemList = new VBoxContainer();
		_devItemList.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		_devItemList.AddThemeConstantOverride("separation", 1);
		scroll.AddChild(_devItemList);

		// ── Hint ở dưới ───────────────────────────────────────────────────
		_emotionHintLabel             = CreateUiLabel("", 11, DevHintFg);
		_emotionHintLabel.Position    = new Vector2(SafeX, ScrollY + ScrollH + 4f);
		_emotionHintLabel.Size        = new Vector2(SafeW, 18f);
		_emotionHintLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		root.AddChild(_emotionHintLabel);

		// Placeholder khi chưa có data
		_devItemList.AddChild(DevPlaceholderLabel("Chưa có dữ liệu emotion_debug."));
	}

	private Label DevPlaceholderLabel(string text)
	{
		var lbl = CreateUiLabel(text, 11, DevNoteFg);
		lbl.AutowrapMode = TextServer.AutowrapMode.Off;
		return lbl;
	}

	// ── DEBUG: ô nhập lệnh tay (góc dưới phải) ─────────────────────────────────
	// Gõ lệnh DebugConsole rồi Enter hoặc bấm "Chạy". Cú pháp:
	//   set <f>=<v> ...  |  buff <f>=<d> ...  |  rel <f>=<v> ...  |  trust <v>
	//   yan on|off  |  stage <name>  |  mem [ep] <text>  |  show  |  reset [affect|rel|all]
	//   nối nhiều lệnh bằng ';'  vd: reset all; stage rooted; set tenderness=0.9

	private static readonly Color DbgInk    = new(0.69f, 0.30f, 0.47f);
	private static readonly Color DbgBtnBg   = new(1.00f, 0.95f, 0.97f);
	private static readonly Color DbgBtnEdge = new(0.95f, 0.78f, 0.86f);
	private static readonly Color DbgBtnInk  = new(0.50f, 0.20f, 0.35f);

	private void BuildDebugCommandPanel()
	{
		// Cột DEBUG bên phải divider, nằm DƯỚI cụm baked "Switch Case / Hiển thị
		// gợi ý theo ngữ cảnh" (in trong ảnh nền). Ảnh nền có viền trang trí dày nên
		// vùng pink dùng được hẹp hơn 760 — phải canh mép phải khung ~x=708 cho khớp
		// cột dropdown/switch, nếu không khung sẽ lồi ra ngoài viền.
		const float PanelX = 514f;
		const float PanelW = 194f;   // ends 708, nằm gọn trong vùng pink
		const float PanelY = 256f;
		const float PanelH = 220f;   // ends 476

		// Đường kẻ dọc ngăn cách phần cảm xúc (trái) và DEBUG (phải).
		var divider = new ColorRect
		{
			Color       = new Color(0.93f, 0.80f, 0.87f, 0.55f),
			Position    = new Vector2(502f, 96f),
			Size        = new Vector2(1.5f, 392f),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		_emotionPanel.AddChild(divider);

		var header = CreateUiLabel("LỆNH DEBUG", 14, DbgInk);
		header.Position = new Vector2(PanelX + 2f, PanelY - 24f);
		header.Size     = new Vector2(PanelW, 20f);
		_emotionPanel.AddChild(header);

		// Khung nền.
		var card = new Panel
		{
			Position    = new Vector2(PanelX, PanelY),
			Size        = new Vector2(PanelW, PanelH),
			MouseFilter = Control.MouseFilterEnum.Stop,
		};
		card.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor     = new Color(1f, 0.97f, 0.98f, 0.92f),
			BorderColor = DbgBtnEdge,
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 14, CornerRadiusTopRight = 14,
			CornerRadiusBottomLeft = 14, CornerRadiusBottomRight = 14,
		});
		_emotionPanel.AddChild(card);

		const float Pad = 10f;
		float innerX = PanelX + Pad;
		float innerW = PanelW - Pad * 2f;

		// Ô nhập lệnh.
		_debugCommandInput = new LineEdit
		{
			Position           = new Vector2(innerX, PanelY + Pad),
			Size               = new Vector2(innerW, 30f),
			PlaceholderText    = "vd: set valence=0.5; rel trust=0.8",
			ClearButtonEnabled = true,
		};
		StyleDebugLineEdit(_debugCommandInput);
		_debugCommandInput.TextSubmitted += OnDebugCommandSubmitted;
		_emotionPanel.AddChild(_debugCommandInput);

		// Hàng nút: Chạy + Xem.
		float btnY = PanelY + Pad + 38f;
		var runBtn = CreateDebugButton("Chạy", () => RunDebugCommandFromInput());
		runBtn.Position = new Vector2(innerX, btnY);
		runBtn.Size     = new Vector2(innerW * 0.62f - 4f, 30f);
		_emotionPanel.AddChild(runBtn);

		var showBtn = CreateDebugButton("Xem", () => SendDebugCommand("show"));
		showBtn.Position = new Vector2(innerX + innerW * 0.62f + 4f, btnY);
		showBtn.Size     = new Vector2(innerW * 0.38f - 4f, 30f);
		_emotionPanel.AddChild(showBtn);

		// Gợi ý cú pháp (nhiều dòng).
		var hint = CreateUiLabel(
			"set/buff/rel <f>=<v> · trust <v>\nyan on|off · stage <name> · reset\nmem [ep] <text> · nối lệnh bằng ';'",
			9, new Color(0.58f, 0.36f, 0.48f));
		hint.Position     = new Vector2(innerX, btnY + 38f);
		hint.Size         = new Vector2(innerW, 50f);
		hint.AutowrapMode = TextServer.AutowrapMode.WordSmart;
		_emotionPanel.AddChild(hint);

		// Dòng trạng thái: lệnh vừa gửi.
		_debugCommandStatus = CreateUiLabel("— gõ lệnh rồi Enter hoặc bấm Chạy —", 9, DbgBtnInk);
		_debugCommandStatus.Position     = new Vector2(innerX, PanelY + PanelH - 18f);
		_debugCommandStatus.Size         = new Vector2(innerW, 16f);
		_debugCommandStatus.AutowrapMode = TextServer.AutowrapMode.Off;
		_debugCommandStatus.ClipText     = true;
		_emotionPanel.AddChild(_debugCommandStatus);
	}

	private void OnDebugCommandSubmitted(string text) => RunDebugCommandFromInput();

	// Đọc debug_command_ack từ gói tin để hiện KẾT QUẢ lệnh debug lên label trạng
	// thái (không chỉ "đã gửi"). Đây là xác nhận engine đã nhận + parse lệnh.
	private void TryApplyDebugCommandAck(string raw)
	{
		if (_debugCommandStatus == null || string.IsNullOrWhiteSpace(raw) || !raw.Contains("debug_command_ack"))
			return;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			if (!doc.RootElement.TryGetProperty("debug_command_ack", out var ack) || ack.ValueKind != JsonValueKind.Object)
				return;
			string result = ack.TryGetProperty("result", out var r) ? r.GetString() ?? "" : "";
			if (string.IsNullOrEmpty(result))
				return;
			string head = result.Length > 64 ? result.Substring(0, 64) + "…" : result;
			_debugCommandStatus.Text = "↳ " + head;
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Debug] ack parse error: {ex.Message}");
		}
	}

	private void RunDebugCommandFromInput()
	{
		if (_debugCommandInput == null)
			return;
		string cmd = _debugCommandInput.Text.Trim();
		if (string.IsNullOrEmpty(cmd))
			return;
		SendDebugCommand(cmd);
		_debugCommandInput.Text = "";
	}

	private void StyleDebugLineEdit(LineEdit edit)
	{
		var normal = new StyleBoxFlat
		{
			BgColor     = new Color(1f, 0.99f, 0.99f),
			BorderColor = DbgBtnEdge,
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10, CornerRadiusTopRight = 10,
			CornerRadiusBottomLeft = 10, CornerRadiusBottomRight = 10,
			ContentMarginLeft = 10f, ContentMarginRight = 10f,
			ContentMarginTop = 4f, ContentMarginBottom = 4f,
		};
		var focus = (StyleBoxFlat)normal.Duplicate();
		focus.BorderColor = new Color(0.92f, 0.62f, 0.76f);
		focus.BorderWidthLeft = 2; focus.BorderWidthTop = 2; focus.BorderWidthRight = 2; focus.BorderWidthBottom = 2;
		edit.AddThemeStyleboxOverride("normal", normal);
		edit.AddThemeStyleboxOverride("focus", focus);
		edit.AddThemeColorOverride("font_color", new Color(0.30f, 0.12f, 0.22f));
		edit.AddThemeColorOverride("font_placeholder_color", new Color(0.62f, 0.45f, 0.54f));
		edit.AddThemeColorOverride("caret_color", DbgInk);
		edit.AddThemeFontSizeOverride("font_size", 11);
	}

	private Button CreateDebugButton(string text, Action onPressed)
	{
		var btn = new Button
		{
			Text                     = text,
			CustomMinimumSize        = new Vector2(0f, 30f),
			MouseDefaultCursorShape  = Control.CursorShape.PointingHand,
			Alignment                = HorizontalAlignment.Center,
			ClipText                 = true,
		};

		var normal = new StyleBoxFlat
		{
			BgColor     = DbgBtnBg,
			BorderColor = DbgBtnEdge,
			BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
			CornerRadiusTopLeft = 10, CornerRadiusTopRight = 10,
			CornerRadiusBottomLeft = 10, CornerRadiusBottomRight = 10,
			ContentMarginLeft = 6f, ContentMarginRight = 6f,
			ContentMarginTop = 4f, ContentMarginBottom = 4f,
		};
		var hover = (StyleBoxFlat)normal.Duplicate();
		hover.BgColor     = new Color(0.99f, 0.90f, 0.94f);
		hover.BorderColor = new Color(0.92f, 0.62f, 0.76f);
		var pressed = (StyleBoxFlat)hover.Duplicate();
		pressed.BgColor = new Color(0.97f, 0.83f, 0.90f);

		btn.AddThemeStyleboxOverride("normal", normal);
		btn.AddThemeStyleboxOverride("hover", hover);
		btn.AddThemeStyleboxOverride("pressed", pressed);
		btn.AddThemeStyleboxOverride("focus", hover);
		btn.AddThemeColorOverride("font_color", DbgBtnInk);
		btn.AddThemeColorOverride("font_hover_color", new Color(0.74f, 0.20f, 0.42f));
		btn.AddThemeColorOverride("font_pressed_color", new Color(0.66f, 0.16f, 0.36f));
		btn.AddThemeFontSizeOverride("font_size", 12);

		btn.Pressed += onPressed;
		return btn;
	}

	/// <summary>Dựng lại toàn bộ raw item list trong dev mode từ _latestEmotionDebug.</summary>
	private void RefreshDevMode()
	{
		if (_devItemList == null || _devHeaderLabel == null)
			return;

		// Xoá cũ
		foreach (Node child in _devItemList.GetChildren())
		{
			_devItemList.RemoveChild(child);
			child.QueueFree();
		}

		if (_latestEmotionDebug == null || _latestEmotionDebug.Items == null || _latestEmotionDebug.Items.Count == 0)
		{
			_devHeaderLabel.Text = "valence —  |  arousal —  |  state: chưa có";
			_devItemList.AddChild(DevPlaceholderLabel("Chưa có dữ liệu emotion_debug."));
			if (_emotionHintLabel != null) _emotionHintLabel.Text = "";
			return;
		}

		var debug = _latestEmotionDebug;

		// Header: valence + arousal raw + state từ AI
		float rawValence = debug.HasSummaryValence ? debug.SummaryValence : float.NaN;
		float rawArousal = 0f;
		foreach (var it in debug.Items)
			if (it.Key == "calm_aroused" && it.HasNumericValue) { rawArousal = it.NumericValue; break; }

		string valStr   = float.IsNaN(rawValence) ? "—" : $"{rawValence:+0.00;-0.00}";
		string aroStr   = $"{rawArousal:0.00}";
		string stateStr = string.IsNullOrWhiteSpace(debug.SummaryState) ? FormatSummaryValue(debug.SummaryValue) : debug.SummaryState;
		_devHeaderLabel.Text = $"valence {valStr}  |  arousal {aroStr}  |  {stateStr}";

		// Build theo group
		string currentGroup = null;
		foreach (var item in debug.Items)
		{
			string group = string.IsNullOrWhiteSpace(item.Group) ? "other" : item.Group;

			if (group != currentGroup)
			{
				currentGroup = group;
				// Group header
				var groupLbl = CreateUiLabel($"── {GroupTitle(group)} ──", 10, DevGroupFg);
				groupLbl.CustomMinimumSize = new Vector2(0f, 16f);
				_devItemList.AddChild(groupLbl);
			}

			// Row: key  [████░]  0.72  note
			_devItemList.AddChild(BuildDevItemRow(item));
		}

		// Hint: romcom summary
		if (_emotionHintLabel != null)
		{
			var byKey = new Dictionary<string, EmotionDebugItem>(debug.Items.Count, StringComparer.Ordinal);
			foreach (var it in debug.Items) byKey[it.Key] = it;
			_emotionHintLabel.Text = BuildRomcomHint(byKey, debug);
		}
	}

	/// <summary>Tạo 1 dòng raw item: label-key  mini-bar  value  note</summary>
	private Control BuildDevItemRow(EmotionDebugItem item)
	{
		var row = new HBoxContainer { CustomMinimumSize = new Vector2(0f, DevRowH) };
		row.AddThemeConstantOverride("separation", 6);

		// Key/label — 130px cố định, clip
		string displayKey = string.IsNullOrWhiteSpace(item.Label) ? item.Key : item.Label;
		var keyLbl = CreateUiLabel(displayKey, 11, DevKeyFg);
		keyLbl.CustomMinimumSize = new Vector2(130f, DevRowH);
		keyLbl.SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin;
		keyLbl.AutowrapMode = TextServer.AutowrapMode.Off;
		keyLbl.ClipText     = true;
		row.AddChild(keyLbl);

		if (item.HasNumericValue)
		{
			// Mini bar container
			var barOuter = new Control
			{
				CustomMinimumSize = new Vector2(DevBarW, DevRowH),
				SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
			};
			row.AddChild(barOuter);

			var track = new Panel
			{
				Position = new Vector2(0f, (DevRowH - DevBarH) * 0.5f),
				Size     = new Vector2(DevBarW, DevBarH),
				MouseFilter = Control.MouseFilterEnum.Ignore,
			};
			track.AddThemeStyleboxOverride("panel", new StyleBoxFlat
			{
				BgColor = DevBarTrack,
				CornerRadiusTopLeft = 4, CornerRadiusTopRight = 4,
				CornerRadiusBottomLeft = 4, CornerRadiusBottomRight = 4,
			});
			barOuter.AddChild(track);

			float fillW = Mathf.Clamp(item.NumericValue, 0f, 1f) * DevBarW;
			var fill = new Panel
			{
				Position = new Vector2(0f, (DevRowH - DevBarH) * 0.5f),
				Size     = new Vector2(fillW, DevBarH),
				MouseFilter = Control.MouseFilterEnum.Ignore,
			};
			fill.AddThemeStyleboxOverride("panel", new StyleBoxFlat
			{
				BgColor = DevBarFill,
				CornerRadiusTopLeft = 4, CornerRadiusTopRight = 4,
				CornerRadiusBottomLeft = 4, CornerRadiusBottomRight = 4,
			});
			barOuter.AddChild(fill);

			// Numeric value
			var valLbl = CreateUiLabel($"{item.NumericValue:0.00}", 11, DevValFg);
			valLbl.CustomMinimumSize = new Vector2(34f, DevRowH);
			valLbl.SizeFlagsHorizontal = Control.SizeFlags.ShrinkBegin;
			row.AddChild(valLbl);
		}
		else
		{
			// Non-numeric: hiện raw text
			var valLbl = CreateUiLabel(string.IsNullOrWhiteSpace(item.ValueText) ? "—" : item.ValueText, 11, DevValFg);
			valLbl.CustomMinimumSize = new Vector2(110f, DevRowH);
			valLbl.AutowrapMode = TextServer.AutowrapMode.Off;
			valLbl.ClipText     = true;
			row.AddChild(valLbl);
		}

		// Note (mờ, clip)
		if (!string.IsNullOrWhiteSpace(item.Note))
		{
			var noteLbl = CreateUiLabel(item.Note, 10, DevNoteFg);
			noteLbl.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
			noteLbl.AutowrapMode = TextServer.AutowrapMode.Off;
			noteLbl.ClipText     = true;
			row.AddChild(noteLbl);
		}

		return row;
	}

	// ── Casual mode content ───────────────────────────────────────────────────

	// Casual mode constants
	private static readonly Color CasualBarFill  = new(0.97f, 0.55f, 0.72f);
	private static readonly Color CasualBarTrack = new(1.00f, 0.88f, 0.93f);
	private static readonly Color CasualBarWord  = new(0.80f, 0.18f, 0.45f);

	private static readonly (string Icon, string Name, string Key1, string Key2, string Key3, string[] Levels)[] CasualBarDefs =
	{
		("♡", "Gắn bó",    "attachment", "tenderness",  "warmth",
			new[] { "xa lắm", "hơi xa", "vừa đủ", "gần", "rất gần" }),
		("~", "Nhịp điệu", "emotional_stability", "", "",
			new[] { "dao động", "hơi bất ổn", "ổn", "khá vững", "rất vững" }),
		("✦", "Muốn nói",  "speech_pressure", "social_pressure", "",
			new[] { "im lặng", "ít muốn nói", "muốn nói", "đang hứng", "rất hứng" }),
	};

	private void BuildCasualContent()
	{
		// Root container
		var root = new Control { MouseFilter = Control.MouseFilterEnum.Ignore };
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_emotionPanel.AddChild(root);
		_casualContentRoot = root;

		// ── Layout (panel 760×506, header ~108px, bottom decoration ~32px) ───
		// Safe zone: x=46..610, y=108..474
		// Dọc: narrative(42px) → grid(240px) → bars(3×44px=132px) → hint(18px)
		// Total: 42+8+240+8+132+8+18 = 456px → fit trong 366px safe
		// Điều chỉnh: narrative(40), grid(220), bars(120), hint(18) = 398px → ok

		const float SafeX  = 46f;
		const float SafeW  = 440f;  // grid width — chừa khoảng trước divider DEBUG (~x=520)
		const float StartY = 108f;

		// ── Narrative ─────────────────────────────────────────────────────────
		var narrativeHeader = CreateUiLabel("♡  Hôm nay mình...", 13, new Color(0.62f, 0.14f, 0.38f));
		narrativeHeader.Position     = new Vector2(SafeX, StartY);
		narrativeHeader.Size         = new Vector2(SafeW, 18f);
		narrativeHeader.AutowrapMode = TextServer.AutowrapMode.Off;
		narrativeHeader.ClipText     = true;
		root.AddChild(narrativeHeader);

		_casualNarrativeLabel             = CreateUiLabel("\"...\"", 17, new Color(0.88f, 0.24f, 0.52f));
		_casualNarrativeLabel.Position    = new Vector2(SafeX, StartY + 20f);
		_casualNarrativeLabel.Size        = new Vector2(SafeW, 22f);
		_casualNarrativeLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		_casualNarrativeLabel.ClipText    = true;
		root.AddChild(_casualNarrativeLabel);

		// ── Grid card ─────────────────────────────────────────────────────────
		const float GridY    = StartY + 46f;  // 154
		const float GridW    = SafeW;          // 440
		const float GridH    = 230f;           // circular wheel card
		const float CardPad  = 18f;
		const float CanvasW  = GridW - CardPad * 2f;  // 404
		const float CanvasH  = GridH - CardPad * 2f;  // 194

		// Card background
		var cardBg = new Panel
		{
			Position    = new Vector2(SafeX, GridY),
			Size        = new Vector2(GridW, GridH),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		cardBg.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor     = new Color(1f, 0.970f, 0.985f, 0.92f),
			BorderColor = new Color(0.96f, 0.78f, 0.87f, 0.85f),
			BorderWidthLeft = 2, BorderWidthTop = 2, BorderWidthRight = 2, BorderWidthBottom = 2,
			CornerRadiusTopLeft = 20, CornerRadiusTopRight = 20,
			CornerRadiusBottomLeft = 20, CornerRadiusBottomRight = 20,
		});
		root.AddChild(cardBg);

		// ♡ decorations ở 4 góc trong card
		float[] cornerXs = { SafeX + 6f,  SafeX + GridW - 20f };
		float[] cornerYs = { GridY + 4f,  GridY + GridH - 22f  };
		foreach (float cx in cornerXs)
			foreach (float cy in cornerYs)
			{
				var heart = CreateUiLabel("♡", 13, new Color(0.97f, 0.72f, 0.82f));
				heart.Position    = new Vector2(cx, cy);
				heart.MouseFilter = Control.MouseFilterEnum.Ignore;
				root.AddChild(heart);
			}

		// Canvas mood dot
		var canvas = new _MoodDotCanvas
		{
			Position = new Vector2(SafeX + CardPad, GridY + CardPad),
			Size     = new Vector2(CanvasW, CanvasH),
		};
		canvas.SetOwnerListener(this, CanvasW, CanvasH);
		root.AddChild(canvas);
		_moodDotCanvas = canvas;

		// Axis labels đặt ngoài vòng tròn — canvas tự vẽ từ _Draw()

		// ── 3 bars dưới grid ─────────────────────────────────────────────────
		const float BarsY0  = GridY + GridH + 8f;
		const float BarsGap = 34f;
		const float BarIconX = SafeX;
		const float BarNameX = SafeX + 26f;
		const float BarTrackX = SafeX + 108f;
		const float BarTrackW = 200f;
		const float BarWordX  = BarTrackX + BarTrackW + 10f;

		_casualBars.Clear();
		for (int i = 0; i < CasualBarDefs.Length; i++)
		{
			var (icon, name, k1, k2, k3, levels) = CasualBarDefs[i];
			CasualBar(root, icon, name, levels,
				BarIconX, BarNameX, BarTrackX, BarTrackW, BarWordX,
				BarsY0 + i * BarsGap,
				out var fillClip, out var fill, out var wordLabel);
			_casualBars.Add((fillClip, fill, wordLabel));
		}

		// ── Hint ──────────────────────────────────────────────────────────────
		_emotionHintLabel             = CreateUiLabel("", 11, new Color(0.62f, 0.32f, 0.44f));
		_emotionHintLabel.Position    = new Vector2(SafeX, BarsY0 + CasualBarDefs.Length * BarsGap + 4f);
		_emotionHintLabel.Size        = new Vector2(SafeW, 18f);
		_emotionHintLabel.AutowrapMode = TextServer.AutowrapMode.Off;
		root.AddChild(_emotionHintLabel);
	}

	private void AxisLabel(Control parent, string text, float x, float y, int fontSize)
	{
		var lbl = CreateUiLabel(text, fontSize, new Color(0.68f, 0.36f, 0.52f));
		lbl.Position    = new Vector2(x, y);
		lbl.MouseFilter = Control.MouseFilterEnum.Ignore;
		parent.AddChild(lbl);
	}

	// Bar: icon  name  [ ████░░░ ]  "word"
	// Track dùng dashes, fill dùng blocks — như design target
	private void CasualBar(Control parent,
		string icon, string name, string[] levels,
		float iconX, float nameX, float trackX, float trackW, float wordX,
		float y,
		out Control fillClip, out Control fill, out Label wordLabel)
	{
		const float BarH   = 14f;
		const float LabelH = 20f;
		float midY = y + (LabelH - BarH) * 0.5f;

		// Icon
		var iconLbl = CreateUiLabel(icon, 15, new Color(0.93f, 0.36f, 0.62f));
		iconLbl.Position    = new Vector2(iconX, y);
		iconLbl.Size        = new Vector2(22f, LabelH);
		iconLbl.MouseFilter = Control.MouseFilterEnum.Ignore;
		parent.AddChild(iconLbl);

		// Name
		var nameLbl = CreateUiLabel(name, 14, new Color(0.38f, 0.08f, 0.24f));
		nameLbl.Position     = new Vector2(nameX, y);
		nameLbl.Size         = new Vector2(trackX - nameX - 4f, LabelH);
		nameLbl.AutowrapMode = TextServer.AutowrapMode.Off;
		parent.AddChild(nameLbl);

		// "[" bracket
		var bracketL = CreateUiLabel("[", 13, new Color(0.80f, 0.48f, 0.62f));
		bracketL.Position    = new Vector2(trackX - 12f, midY - 1f);
		bracketL.Size        = new Vector2(12f, LabelH);
		bracketL.MouseFilter = Control.MouseFilterEnum.Ignore;
		parent.AddChild(bracketL);

		// Track background (dashed feel — dùng StyleBoxFlat với thưa)
		var track = new Panel
		{
			Position    = new Vector2(trackX, midY),
			Size        = new Vector2(trackW, BarH),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		track.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = CasualBarTrack,
			CornerRadiusTopLeft = 6, CornerRadiusTopRight = 6,
			CornerRadiusBottomLeft = 6, CornerRadiusBottomRight = 6,
		});
		parent.AddChild(track);

		// Fill
		var fClip = new Panel
		{
			Position    = new Vector2(trackX, midY),
			Size        = new Vector2(0f, BarH),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		fClip.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = CasualBarFill,
			CornerRadiusTopLeft = 6, CornerRadiusTopRight = 6,
			CornerRadiusBottomLeft = 6, CornerRadiusBottomRight = 6,
		});
		parent.AddChild(fClip);

		// "]" bracket
		var bracketR = CreateUiLabel("]", 13, new Color(0.80f, 0.48f, 0.62f));
		bracketR.Position    = new Vector2(trackX + trackW, midY - 1f);
		bracketR.Size        = new Vector2(12f, LabelH);
		bracketR.MouseFilter = Control.MouseFilterEnum.Ignore;
		parent.AddChild(bracketR);

		// Word label
		wordLabel          = CreateUiLabel("―", 14, CasualBarWord);
		wordLabel.Position = new Vector2(wordX + 4f, y);
		wordLabel.Size     = new Vector2(100f, LabelH);
		parent.AddChild(wordLabel);

		fillClip = fClip;
		fill     = fClip;
	}

	/// <summary>
	/// Format raw snake_case value từ AI thành readable text.
	/// Ví dụ: "trung_tinh" → "trung tính", "kho_chiu" → "khó chịu".
	/// </summary>
	private static string FormatSummaryValue(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw)) return "";
		return raw switch
		{
			"vui"        => "vui",
			"kho_chiu"   => "khó chịu",
			"trung_tinh" => "trung tính",
			_            => raw.Replace('_', ' '),   // fallback: underscore → space
		};
	}

	/// <summary>Chuyển 0..1 thành từ trạng thái (5 cấp).</summary>
	private static string ValueToWord(float v, string[] levels)
	{
		int idx = Mathf.Clamp(Mathf.RoundToInt(v * (levels.Length - 1)), 0, levels.Length - 1);
		return $"\"{levels[idx]}\"";
	}

	private void BuildPrivateMindPanelUi()
	{
		if (_privateMindPanel == null)
			return;

		_privateMindScrollCapTexture ??= GD.Load<Texture2D>("res://asset/Resource/topcap.png");
		_privateMindScrollTrackTexture ??= GD.Load<Texture2D>("res://asset/Resource/scrolltrack.png");
		_privateMindScrollFillTexture ??= GD.Load<Texture2D>("res://asset/Resource/scrollfill.png");

		// Khung vẽ bằng StyleBox để co giãn sắc nét ở kích thước lớn (thay cho việc kéo dãn PNG cũ).
		var panelStyle = new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.965f, 0.982f, 0.99f),
			BorderColor = new Color(0.96f, 0.72f, 0.82f, 1f),
			BorderWidthLeft = 3,
			BorderWidthTop = 3,
			BorderWidthRight = 3,
			BorderWidthBottom = 3,
			CornerRadiusTopLeft = 34,
			CornerRadiusTopRight = 34,
			CornerRadiusBottomRight = 34,
			CornerRadiusBottomLeft = 34,
			ShadowColor = new Color(0.85f, 0.45f, 0.62f, 0.25f),
			ShadowSize = 10,
			ContentMarginLeft = 0,
			ContentMarginTop = 0,
			ContentMarginRight = 0,
			ContentMarginBottom = 0,
		};
		_privateMindPanel.AddThemeStyleboxOverride("panel", panelStyle);
		_privateMindFrameRect = null; // không dùng layer ảnh nữa; khung do StyleBox vẽ

		// ── Root layout: header / body (sidebar + cột phải) / footer ──────────
		var root = new VBoxContainer();
		root.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		root.OffsetLeft = 30f;
		root.OffsetTop = 24f;
		root.OffsetRight = -30f;
		root.OffsetBottom = -18f;
		root.AddThemeConstantOverride("separation", 14);
		_privateMindPanel.AddChild(root);

		// ── Header: tiêu đề + phụ đề ──────────────────────────────────────────
		var headerRow = new HBoxContainer();
		headerRow.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		headerRow.AddThemeConstantOverride("separation", 10);
		root.AddChild(headerRow);

		var titleCol = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		titleCol.AddThemeConstantOverride("separation", 2);
		headerRow.AddChild(titleCol);

		var titleLabel = CreateUiLabel("Inner Diary", 30, new Color(0.62f, 0.10f, 0.36f));
		titleCol.AddChild(titleLabel);

		var subtitleLabel = CreateUiLabel("Chỉ Ngài mới được phép xem.", 13, new Color(0.74f, 0.46f, 0.60f));
		titleCol.AddChild(subtitleLabel);

		// Khoảng trống đẩy capsule điều khiển về góc phải
		var headerSpacer = new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		headerRow.AddChild(headerSpacer);

		var windowControls = CreateWindowControlCapsule(
			() => _privateMindPanel.Visible = false,
			ClosePrivateMindPanel);
		windowControls.SizeFlagsVertical = Control.SizeFlags.ShrinkBegin;
		headerRow.AddChild(windowControls);

		// Đường kẻ mảnh ngăn header
		var divider = new ColorRect
		{
			Color = new Color(0.96f, 0.80f, 0.88f, 0.55f),
			CustomMinimumSize = new Vector2(0f, 1f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		root.AddChild(divider);

		// ── Body: sidebar trái + cột phải ────────────────────────────────────
		var body = new HBoxContainer();
		body.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		body.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		body.AddThemeConstantOverride("separation", 18);
		root.AddChild(body);

		var sidebar = new VBoxContainer
		{
			CustomMinimumSize = new Vector2(286f, 0f),
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		sidebar.AddThemeConstantOverride("separation", 32);
		body.AddChild(sidebar);

		BuildDiaryMoodCard(sidebar);
		BuildDiaryConcernCard(sidebar);
		BuildDiaryMemoryEchoCard(sidebar);

		// Cột phải: scroll chứa các thẻ suy nghĩ
		var rightCol = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
		};
		body.AddChild(rightCol);

		var scroll = new ScrollContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ExpandFill,
			ClipContents = true,
		};
		scroll.AddThemeConstantOverride("v_scrollbar_separation", 0);
		rightCol.AddChild(scroll);
		_privateMindScrollContainer = scroll;

		// MarginContainer chừa chỗ bên phải cho thanh cuộn tim + lề trên để banner card đầu không bị cắt
		var scrollPad = new MarginContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		scrollPad.AddThemeConstantOverride("margin_right", 26);
		scrollPad.AddThemeConstantOverride("margin_top", 42);
		scroll.AddChild(scrollPad);

		_privateMindSectionList = new VBoxContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		_privateMindSectionList.AddThemeConstantOverride("separation", 44);
		scrollPad.AddChild(_privateMindSectionList);

		// RichTextLabel ẩn — vẫn giữ để tương thích state cũ
		_privateMindText = new RichTextLabel
		{
			BbcodeEnabled = true,
			FitContent = true,
			ScrollActive = false,
			Visible = false,
			CustomMinimumSize = new Vector2(0f, 0f),
		};
		_privateMindText.AddThemeFontSizeOverride("normal_font_size", 14);


		// ── Decoration overlay (thanh cuộn tim) — nằm trên cùng ──────────────
		var decorationLayer = new Control
		{
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		decorationLayer.SetAnchorsPreset(Control.LayoutPreset.FullRect);
		_privateMindPanel.AddChild(decorationLayer);

		_privateMindScrollTrackRect = CreateDecorTextureRect(_privateMindScrollTrackTexture, new Vector2(14f, 200f));
		decorationLayer.AddChild(_privateMindScrollTrackRect);

		_privateMindScrollFillRect = CreateDecorTextureRect(_privateMindScrollFillTexture, new Vector2(14f, 60f));
		decorationLayer.AddChild(_privateMindScrollFillRect);

		_privateMindScrollCapRect = CreateDecorTextureRect(_privateMindScrollCapTexture, new Vector2(26f, 24f));
		decorationLayer.AddChild(_privateMindScrollCapRect);

		ApplyHiddenScrollBarTheme(scroll.GetVScrollBar());
		scroll.GetVScrollBar().ValueChanged += _ => UpdatePrivateMindScrollDecor();

		if (string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson))
			LoadPrivateMindState();

		UpdatePrivateMindDecorLayout();
		UpdatePrivateMindScrollDecor();
		RefreshPrivateMindPanel();
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  Sidebar cards
	// ─────────────────────────────────────────────────────────────────────────

	private PanelContainer CreateDiarySidebarCard(out VBoxContainer content, int topMargin = 14)

	{
		var card = new PanelContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		card.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.974f, 0.987f, 0.97f),
			BorderColor = new Color(0.97f, 0.82f, 0.89f, 0.95f),
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 20,
			CornerRadiusTopRight = 20,
			CornerRadiusBottomRight = 20,
			CornerRadiusBottomLeft = 20,
			ContentMarginLeft = 16,
			ContentMarginTop = topMargin,
			ContentMarginRight = 16,
			ContentMarginBottom = 14,
		});

		content = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		content.AddThemeConstantOverride("separation", 10);
		card.AddChild(content);
		return card;
	}

	private void AddDiaryCardHeader(VBoxContainer content, string iconAsset, string title, Color accent)
	{
		Control header = BuildDiaryHeader(iconAsset, title, new Color(0.60f, 0.12f, 0.40f), null, accent, 56f, 12);
		header.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		content.AddChild(header);
	}

	// Header diary: nếu asset là khung banner ngang (icon trái + vùng chữ phải) thì vẽ khung
	// theo đúng tỉ lệ gốc (canh trái, không méo icon) rồi chèn tiêu đề đè lên vùng trống bên phải.
	// Asset không phải banner (thiếu ảnh / ảnh vuông) thì fallback về glyph nhỏ + label như cũ.
	private Control BuildDiaryHeader(
		string asset, string title, Color titleColor, string badge, Color badgeColor,
		float bannerHeight, int titleFontSize)
	{
		Texture2D tex = LoadResourceTexture($"res://asset/Resource/{asset}.png");
		bool isBanner = tex != null && tex.GetHeight() > 0 && tex.GetWidth() >= tex.GetHeight() * 2;

		if (isBanner)
		{
			float aspect = (float)tex.GetWidth() / tex.GetHeight();
			float bannerWidth = bannerHeight * aspect;
			// Tỉ lệ phần khung nằm TRÊN viền card (nhô ra ngoài). >0.5 = nổi hẳn lên trên.
			float above = bannerHeight * DiaryBannerAboveRatio;
			float below = bannerHeight - above;

			// Control bao ngoài chỉ chiếm phần DƯỚI viền trong layout (= below). Banner vắt lên trên.
			// Không clip để phần trên banner tràn ra ngoài viền card.
			var wrap = new Control
			{
				CustomMinimumSize = new Vector2(bannerWidth, below),
				MouseFilter = Control.MouseFilterEnum.Ignore,
			};

			// Khung: phần trên (above) tràn ra ngoài viền, phần dưới (below) nằm trong card.
			var banner = new TextureRect
			{
				Texture = tex,
				ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
				StretchMode = TextureRect.StretchModeEnum.Scale,
				MouseFilter = Control.MouseFilterEnum.Ignore,
			};
			banner.SetAnchorsPreset(Control.LayoutPreset.TopLeft);
			banner.OffsetLeft = 0;
			banner.OffsetRight = bannerWidth;
			banner.OffsetTop = -above;
			banner.OffsetBottom = below;
			wrap.AddChild(banner);

			// Tiêu đề: căn giữa theo chiều dọc của banner, bắt đầu ~50% bề ngang, tràn ra phải.
			var label = new Label
			{
				Text = title,
				ClipText = false,
				VerticalAlignment = VerticalAlignment.Center,
				HorizontalAlignment = HorizontalAlignment.Left,
				MouseFilter = Control.MouseFilterEnum.Ignore,
			};
			label.AddThemeFontSizeOverride("font_size", titleFontSize);
			label.AddThemeColorOverride("font_color", titleColor);
			label.SetAnchorsPreset(Control.LayoutPreset.TopLeft);
			label.OffsetLeft = bannerWidth * 0.50f;   // dính ~50% trên khung, nhích sang phải
			label.OffsetRight = bannerWidth * 2.0f;    // cho tràn ra ngoài về phải, không clip
			label.OffsetTop = -above;
			label.OffsetBottom = below;
			wrap.AddChild(label);

			if (string.IsNullOrWhiteSpace(badge))
				return wrap;

			// Có badge → khung+chữ bên trái, badge dồn về mép phải (căn theo phần trong card).
			var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
			row.AddThemeConstantOverride("separation", 8);
			row.AddChild(wrap);
			row.AddChild(new Control { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill });
			var badgeLabel = CreateUiLabel(badge, 12, badgeColor);
			badgeLabel.VerticalAlignment = VerticalAlignment.Center;
			row.AddChild(badgeLabel);
			return row;
		}

		// Fallback kiểu cũ: glyph nhỏ + tiêu đề (+ badge nếu có).
		var fallback = new HBoxContainer();
		fallback.AddThemeConstantOverride("separation", 8);
		var glyph = CreateDiaryGlyph(asset, badgeColor, 18f);
		glyph.SizeFlagsVertical = Control.SizeFlags.ShrinkCenter;
		fallback.AddChild(glyph);
		var lbl = CreateUiLabel(title, 16, titleColor);
		lbl.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		lbl.VerticalAlignment = VerticalAlignment.Center;
		fallback.AddChild(lbl);
		if (!string.IsNullOrWhiteSpace(badge))
		{
			var b = CreateUiLabel(badge, 12, badgeColor);
			b.VerticalAlignment = VerticalAlignment.Center;
			fallback.AddChild(b);
		}
		return fallback;
	}

	private ProgressBar CreateDiaryBar(Color fillColor)
	{
		var pb = new ProgressBar
		{
			MinValue = 0,
			MaxValue = 100,
			Value = 0,
			ShowPercentage = false,
			CustomMinimumSize = new Vector2(0f, 9f),
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
		};
		pb.AddThemeStyleboxOverride("background", new StyleBoxFlat
		{
			BgColor = new Color(0.99f, 0.90f, 0.94f, 1f),
			CornerRadiusTopLeft = 6,
			CornerRadiusTopRight = 6,
			CornerRadiusBottomRight = 6,
			CornerRadiusBottomLeft = 6,
		});
		pb.AddThemeStyleboxOverride("fill", new StyleBoxFlat
		{
			BgColor = fillColor,
			CornerRadiusTopLeft = 6,
			CornerRadiusTopRight = 6,
			CornerRadiusBottomRight = 6,
			CornerRadiusBottomLeft = 6,
		});
		return pb;
	}

	private void BuildDiaryMoodCard(VBoxContainer sidebar)
	{
		PanelContainer card = CreateDiarySidebarCard(out VBoxContainer content);
		AddDiaryCardHeader(content, "diary_mood", "Mood", new Color(0.95f, 0.42f, 0.66f));

		var row = new HBoxContainer();
		row.AddThemeConstantOverride("separation", 12);
		content.AddChild(row);

		// Avatar tròn — 9 face theo valence/arousal. Nếu chưa có ảnh thì rơi về chấm tròn hồng.
		Control face = BuildDiaryMoodFace(72f);
		row.AddChild(face);

		var bars = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		bars.AddThemeConstantOverride("separation", 8);
		row.AddChild(bars);

		bars.AddChild(BuildMoodMetric("Valence", new Color(0.95f, 0.40f, 0.62f), out _diaryValenceBar, out _diaryValenceLabel));
		bars.AddChild(BuildMoodMetric("Arousal", new Color(0.98f, 0.62f, 0.42f), out _diaryArousalBar, out _diaryArousalLabel));

		// Hộp trích dẫn tâm trạng
		var quoteBox = new PanelContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		quoteBox.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.945f, 0.965f, 0.95f),
			CornerRadiusTopLeft = 12,
			CornerRadiusTopRight = 12,
			CornerRadiusBottomRight = 12,
			CornerRadiusBottomLeft = 12,
			ContentMarginLeft = 12,
			ContentMarginTop = 8,
			ContentMarginRight = 12,
			ContentMarginBottom = 8,
		});
		content.AddChild(quoteBox);

		_diaryMoodQuoteLabel = new Label
		{
			Text = "\u201c…\u201d",
			AutowrapMode = TextServer.AutowrapMode.WordSmart,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		_diaryMoodQuoteLabel.AddThemeFontSizeOverride("font_size", 13);
		_diaryMoodQuoteLabel.AddThemeColorOverride("font_color", new Color(0.62f, 0.34f, 0.48f));
		quoteBox.AddChild(_diaryMoodQuoteLabel);

		sidebar.AddChild(card);
	}

	private Control BuildMoodMetric(string name, Color fillColor, out ProgressBar bar, out Label valueLabel)
	{
		var col = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		col.AddThemeConstantOverride("separation", 3);

		var labelRow = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		var name1 = CreateUiLabel(name, 12, new Color(0.58f, 0.22f, 0.40f));
		name1.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		labelRow.AddChild(name1);
		valueLabel = CreateUiLabel("—", 12, new Color(0.84f, 0.30f, 0.52f));
		labelRow.AddChild(valueLabel);
		col.AddChild(labelRow);

		bar = CreateDiaryBar(fillColor);
		col.AddChild(bar);
		return col;
	}

	private void BuildDiaryConcernCard(VBoxContainer sidebar)
	{
		PanelContainer card = CreateDiarySidebarCard(out VBoxContainer content, 0);
		AddDiaryCardHeader(content, "diary_concern", "Concern Stack", new Color(0.97f, 0.46f, 0.66f));

		_diaryConcernList = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		_diaryConcernList.AddThemeConstantOverride("separation", 10);
		content.AddChild(_diaryConcernList);

		sidebar.AddChild(card);
	}

	private void BuildDiaryMemoryEchoCard(VBoxContainer sidebar)
	{
		PanelContainer card = CreateDiarySidebarCard(out VBoxContainer content, 0);
		card.SizeFlagsVertical = Control.SizeFlags.ExpandFill;
		AddDiaryCardHeader(content, "diary_memory", "Memory Echo", new Color(0.72f, 0.52f, 0.88f));

		_diaryMemoryEchoLabel = new Label
		{
			Text = "\u201cchưa có ký ức nào vọng lại.\u201d",
			AutowrapMode = TextServer.AutowrapMode.WordSmart,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		_diaryMemoryEchoLabel.AddThemeFontSizeOverride("font_size", 13);
		_diaryMemoryEchoLabel.AddThemeColorOverride("font_color", new Color(0.55f, 0.30f, 0.45f));
		content.AddChild(_diaryMemoryEchoLabel);

		_diaryMemoryEchoMetaLabel = CreateUiLabel("", 11, new Color(0.74f, 0.50f, 0.62f));
		content.AddChild(_diaryMemoryEchoMetaLabel);

		sidebar.AddChild(card);
	}

	private Label CreateUiLabel(string text, int fontSize, Color color)
	{
		var label = new Label { Text = text };
		label.AddThemeFontSizeOverride("font_size", fontSize);
		label.AddThemeColorOverride("font_color", color);
		return label;
	}

	// Icon nhỏ cho diary: ưu tiên ảnh PNG nếu có (do người dùng cung cấp), nếu chưa
	// có thì rơi về một chấm tròn màu nhấn — KHÔNG dùng ký tự unicode/emoji vì font
	// mặc định của Godot không vẽ được (sẽ ra ô vuông tofu).
	private Control CreateDiaryGlyph(string assetName, Color accent, float boxSize)
	{
		string path = $"res://asset/Resource/{assetName}.png";
		if (ResourceLoader.Exists(path))
		{
			var tex = GD.Load<Texture2D>(path);
			if (tex != null)
			{
				return new TextureRect
				{
					Texture = tex,
					ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
					StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
					CustomMinimumSize = new Vector2(boxSize, boxSize),
					MouseFilter = Control.MouseFilterEnum.Ignore,
				};
			}
		}

		var dot = new PanelContainer { CustomMinimumSize = new Vector2(boxSize, boxSize) };
		int r = Mathf.RoundToInt(boxSize * 0.32f);
		dot.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(accent.R, accent.G, accent.B, 0.85f),
			CornerRadiusTopLeft = r,
			CornerRadiusTopRight = r,
			CornerRadiusBottomRight = r,
			CornerRadiusBottomLeft = r,
			ContentMarginLeft = 0,
			ContentMarginTop = 0,
			ContentMarginRight = 0,
			ContentMarginBottom = 0,
		});
		return dot;
	}

	// Khung face động cho Mood: nền chấm hồng bo tròn (fallback) + TextureRect đè lên.
	// Khi có PNG hợp lệ thì set texture, không có thì để null → chỉ thấy chấm hồng.
	private Control BuildDiaryMoodFace(float boxSize)
	{
		int r = Mathf.RoundToInt(boxSize * 0.5f);
		var bg = new PanelContainer { CustomMinimumSize = new Vector2(boxSize, boxSize) };
		bg.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.96f, 0.66f, 0.78f, 0.85f),
			CornerRadiusTopLeft = r,
			CornerRadiusTopRight = r,
			CornerRadiusBottomRight = r,
			CornerRadiusBottomLeft = r,
		});

		_diaryMoodFace = new TextureRect
		{
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
			CustomMinimumSize = new Vector2(boxSize, boxSize),
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		bg.AddChild(_diaryMoodFace);
		_diaryMoodFaceBg = bg;
		_diaryMoodFaceAsset = "";
		return bg;
	}

	// Chọn 1 trong 9 face theo lưới 3x3 (arousal x valence).
	//   valence  > +0.2 = pos | < -0.2 = neg | còn lại = neu
	//   arousal  > 0.66 = hyper | < 0.33 = calm | còn lại = mid
	// Chưa có dữ liệu mood → dùng "diary_mood_face" (mặt trung tính mặc định).
	private static string MoodFaceAsset(float valence, float arousal, bool hasMood)
	{
		if (!hasMood)
			return "diary_mood_face";
		string v = valence > 0.2f ? "pos" : valence < -0.2f ? "neg" : "neu";
		string a = arousal > 0.66f ? "hyper" : arousal < 0.33f ? "calm" : "mid";
		return $"diary_face_{a}_{v}";
	}

	// Đổi texture của face theo cảm xúc. Có fallback chuỗi: face 3x3 → diary_mood_face → chấm hồng.
	private void UpdateDiaryMoodFace(float valence, float arousal, bool hasMood)
	{
		if (_diaryMoodFace == null)
			return;

		string asset = MoodFaceAsset(valence, arousal, hasMood);
		if (asset == _diaryMoodFaceAsset)
			return;

		Texture2D tex = LoadResourceTexture($"res://asset/Resource/{asset}.png");
		if (tex == null && asset != "diary_mood_face")
			tex = LoadResourceTexture("res://asset/Resource/diary_mood_face.png");

		_diaryMoodFace.Texture = tex;       // null → chỉ còn chấm hồng nền
		_diaryMoodFaceAsset = asset;
		if (_diaryMoodFaceBg != null)
		{
			// Có ảnh face → ẩn nền hồng để không tạo viền cứng; thiếu ảnh → giữ chấm hồng.
			var sb = _diaryMoodFaceBg.GetThemeStylebox("panel") as StyleBoxFlat;
			if (sb != null)
				sb.BgColor = new Color(0.96f, 0.66f, 0.78f, tex != null ? 0f : 0.85f);
		}
	}

	private static Texture2D LoadResourceTexture(string path)
	{
		return ResourceLoader.Exists(path) ? GD.Load<Texture2D>(path) : null;
	}

	private TextureRect CreateDecorTextureRect(Texture2D texture, Vector2 size)
	{
		return new TextureRect
		{
			Texture = texture,
			ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
			StretchMode = TextureRect.StretchModeEnum.Scale,
			CustomMinimumSize = size,
			Size = size,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
	}

	private Button CreateTransparentHotspotButton(Rect2 rect, Action onPressed)
	{
		var button = new Button
		{
			Flat = true,
			Text = "",
			FocusMode = Control.FocusModeEnum.None,
			MouseDefaultCursorShape = Control.CursorShape.PointingHand,
			MouseFilter = Control.MouseFilterEnum.Stop,
			Position = rect.Position,
			Size = rect.Size,
			CustomMinimumSize = rect.Size,
			Modulate = new Color(1f, 1f, 1f, 0.01f),
		};
		var hidden = new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0f),
			BorderColor = new Color(1f, 1f, 1f, 0f),
		};
		button.AddThemeStyleboxOverride("normal", hidden);
		button.AddThemeStyleboxOverride("hover", hidden);
		button.AddThemeStyleboxOverride("pressed", hidden);
		button.AddThemeStyleboxOverride("focus", hidden);
		button.Pressed += onPressed;
		return button;
	}

	private void ApplyHiddenScrollBarTheme(VScrollBar scrollBar)
	{
		if (scrollBar == null)
			return;

		scrollBar.CustomMinimumSize = new Vector2(0f, 0f);
		scrollBar.Modulate = new Color(1f, 1f, 1f, 0.01f);

		var hidden = new StyleBoxFlat
		{
			BgColor = new Color(1f, 1f, 1f, 0f),
			BorderColor = new Color(1f, 1f, 1f, 0f),
		};
		scrollBar.AddThemeStyleboxOverride("scroll", hidden);
		scrollBar.AddThemeStyleboxOverride("scroll_focus", hidden);
		scrollBar.AddThemeStyleboxOverride("grabber", hidden);
		scrollBar.AddThemeStyleboxOverride("grabber_highlight", hidden);
		scrollBar.AddThemeStyleboxOverride("grabber_pressed", hidden);
	}

	private void UpdatePrivateMindDecorLayout()
	{
		if (_privateMindPanel == null)
			return;

		Vector2 size = _privateMindPanel.Size;

		if (_privateMindFrameRect != null)
			_privateMindFrameRect.Size = size;
	}

	private void UpdatePrivateMindScrollDecor()
	{
		if (_privateMindScrollContainer == null || _privateMindPanel == null)
			return;

		VScrollBar scrollBar = _privateMindScrollContainer.GetVScrollBar();
		if (scrollBar == null)
			return;

		// Rail bám đúng mép phải của vùng cuộn (cột phải), không tính theo cả panel
		// nữa — nhờ vậy nó luôn nằm trong khung dù layout đổi.
		Vector2 panelOrigin = _privateMindPanel.GlobalPosition;
		Vector2 scPos = _privateMindScrollContainer.GlobalPosition - panelOrigin;
		Vector2 scSize = _privateMindScrollContainer.Size;

		float railWidth = 12f;
		float trackX = scPos.X + scSize.X - railWidth - 6f;
		float trackTop = scPos.Y + 4f;
		float trackHeight = Mathf.Max(48f, scSize.Y - 8f);

		bool canScroll = scrollBar.MaxValue > scrollBar.Page + 0.5;

		// Vẽ track (background rail)
		if (_privateMindScrollTrackRect != null)
		{
			_privateMindScrollTrackRect.Position = new Vector2(trackX, trackTop);
			_privateMindScrollTrackRect.Size = new Vector2(railWidth, trackHeight);
			_privateMindScrollTrackRect.Visible = canScroll;
		}

		// Thumb fill — chiều cao tỉ lệ theo page/max
		float thumbMinHeight = 52f;
		float thumbMaxHeight = Mathf.Min(trackHeight, 150f);
		float thumbHeight = thumbMinHeight;
		double maxVal = scrollBar.MaxValue;
		if (maxVal > 0.001 && scrollBar.Page > 0)
		{
			float ratio = Mathf.Clamp((float)(scrollBar.Page / maxVal), 0.12f, 1f);
			thumbHeight = Mathf.Clamp(trackHeight * ratio, thumbMinHeight, thumbMaxHeight);
		}

		// Vị trí thumb theo tỉ lệ cuộn
		float scrollRange = Mathf.Max(0f, (float)(scrollBar.MaxValue - scrollBar.Page));
		float ratio2 = scrollRange > 0.001f ? Mathf.Clamp((float)(scrollBar.Value / scrollRange), 0f, 1f) : 0f;
		float thumbY = trackTop + ratio2 * Mathf.Max(0f, trackHeight - thumbHeight);

		float thumbWidth = railWidth;
		float thumbX = trackX + (railWidth - thumbWidth) * 0.5f;

		if (_privateMindScrollFillRect != null)
		{
			_privateMindScrollFillRect.Position = new Vector2(thumbX, thumbY);
			_privateMindScrollFillRect.Size = new Vector2(thumbWidth, thumbHeight);
			_privateMindScrollFillRect.Visible = canScroll;
		}

		// Heart cap (mũ đầu thumb) — giữ đúng tỉ lệ thật của ảnh trái tim để không bị
		// bóp méo, canh giữa theo thân thumb và ngồi ngay đỉnh thumb như một nắp tròn.
		if (_privateMindScrollCapRect != null)
		{
			float capWidth = thumbWidth + 12f;
			float capHeight = capWidth;
			if (_privateMindScrollCapTexture != null)
			{
				Vector2 texSize = _privateMindScrollCapTexture.GetSize();
				if (texSize.X > 0f && texSize.Y > 0f)
					capHeight = capWidth * (texSize.Y / texSize.X);
			}

			float capX = thumbX + (thumbWidth - capWidth) * 0.5f;
			float capY = thumbY - capHeight * 0.4f;
			_privateMindScrollCapRect.Position = new Vector2(capX, capY);
			_privateMindScrollCapRect.Size = new Vector2(capWidth, capHeight);
			_privateMindScrollCapRect.Visible = canScroll;
		}
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

	private Control CreateWindowControlCapsule(Action onMinimize, Action onClose)
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

		var minimizeButton = CreateWindowControlButton("-", onMinimize, 34f, 16);
		var closeButton = CreateWindowControlButton("x", onClose, 34f, 14);
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

		bool wantCasual = index == 1;
		_modeDropdown.Text = wantCasual ? "Casual" : "Dev";
		if (_isCasualMode != wantCasual)
		{
			_isCasualMode = wantCasual;
			RebuildEmotionPanelContent();
			if (_latestEmotionDebug != null)
				RefreshEmotionPanel();
		}
	}

	/// <summary>Xoá và dựng lại phần content bên trái panel theo mode hiện tại.</summary>
	private void RebuildEmotionPanelContent()
	{
		if (_emotionPanel == null)
			return;

		void RemoveAndFree(Node n)
		{
			if (n != null && IsInstanceValid(n))
			{
				n.GetParent()?.RemoveChild(n);
				n.QueueFree();
			}
		}

		// Dev content: rows trong VBoxContainer
		foreach (var row in _emotionRows) RemoveAndFree(row.Row);
		_emotionRows.Clear();
		RemoveAndFree(_emotionSummaryLabel); _emotionSummaryLabel = null;
		RemoveAndFree(_emotionHintLabel);    _emotionHintLabel = null;
		// Dev mode mới: xoá qua _devContentRoot
		RemoveAndFree(_devContentRoot);
		_devContentRoot = null;
		_devHeaderLabel = null;
		_devItemList    = null;
		// Legacy: tìm VBoxContainer cũ nếu vẫn còn
		foreach (Node child in _emotionPanel.GetChildren())
		{
			if (child is VBoxContainer vbox && vbox.Position.Y > 100f && vbox.Position.Y < 200f)
			{
				RemoveAndFree(vbox);
				break;
			}
		}

		// Casual content: toàn bộ nằm trong _casualContentRoot
		RemoveAndFree(_casualContentRoot);
		_casualContentRoot       = null;
		_casualNarrativeLabel    = null;
		_moodDotCanvas           = null;
		_casualBars.Clear();

		if (_isCasualMode)
			BuildCasualContent();
		else
			BuildDevContent();
	}

	private void BeginDrag(Vector2 mousePosition)
	{
		CloseCharacterContextMenu();
		_bodyAutonomy?.RecordUserInteraction();
		_grabModeArmed = false;
		_isDraggingCharacter = true;
		_dragOffset = _body.GlobalPosition - mousePosition; // Lưu khoảng cách giữa chuột và body để kéo không bị giật.
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
		_characterContextMenu.ZIndex = 100;

		// Tự co chiều cao theo số nút thực tế — tránh tràn khi thêm tab mới
		// (vd "Chieu Sau") làm menu cao hơn CharacterContextMenuMinSize cố định.
		float height = CharacterContextMenuMinSize.Y;
		if (GetNodeOrNull<VBoxContainer>("CanvasLayer/Control/CharacterContextMenu/VBoxContainer") is { } menuBox)
		{
			float needed = menuBox.GetCombinedMinimumSize().Y + 16f; // offset top(8)+bottom(8)
			height = Mathf.Max(CharacterContextMenuMinSize.Y, needed);
		}
		_characterContextMenu.Size = new Vector2(CharacterContextMenuMinSize.X, height);

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
		// Tính theo Scale để hit-test khớp với vùng vẽ thực (tránh đóng panel nhầm
		// khi panel được phóng to bằng Scale).
		Rect2 rect = new(control.GlobalPosition, control.Size * control.Scale);
		return rect.HasPoint(mousePosition);
	}

	// Cho phép kéo-di-chuyển một panel: nhấn vào vùng nền (không phải nút con) để bắt đầu kéo.
	private void MakePanelDraggable(Control panel)
	{
		if (panel == null)
			return;
		panel.MouseFilter = Control.MouseFilterEnum.Stop;
		panel.GuiInput += @event => OnPanelGuiInput(panel, @event);
	}

	private void OnPanelGuiInput(Control panel, InputEvent @event)
	{
		if (@event is InputEventMouseButton mb && mb.ButtonIndex == MouseButton.Left && mb.Pressed)
		{
			_draggingPanel = panel;
			_panelDragOffset = panel.GetGlobalMousePosition() - panel.GlobalPosition;
			panel.AcceptEvent();
		}
	}

	private void UpdatePanelDrag()
	{
		if (_draggingPanel == null)
			return;
		Vector2 target = _draggingPanel.GetGlobalMousePosition() - _panelDragOffset;
		Vector2 screen = GetViewportRect().Size;
		target.X = Mathf.Clamp(target.X, 0f, Mathf.Max(0f, screen.X - _draggingPanel.Size.X));
		target.Y = Mathf.Clamp(target.Y, 0f, Mathf.Max(0f, screen.Y - _draggingPanel.Size.Y));
		_draggingPanel.GlobalPosition = target;
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
		MarkChatActivity();
		_chatInput.Text = "";
		// JsonSerializer.Serialize(msg) để escape chuỗi. Không tự nối raw string ngu ngốc
		string payload = $"{{\"type\":\"chat\",\"message\":{JsonSerializer.Serialize(msg)}}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
		ApplyTypewriterEffect($"[Chủ nhân]: {msg}");
		// Gửi xong là ẩn khung chat + báo chat_end để backend nối lại nhịp autonomous.
		CloseChatPanel();
	}

	private void SendChatSignal(string type)
	{
		string payload = $"{{\"type\":\"{type}\"}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
	}

	// Gửi 1 lệnh debug (scenario preset) xuống cortex (UDP 4243).
	// DebugConsole bên Python sẽ parse "reset all; stage rooted; set ...; rel ...; mem ...".
	private void SendDebugCommand(string command)
	{
		if (string.IsNullOrWhiteSpace(command))
			return;
		// JsonSerializer.Serialize để escape an toàn (lệnh mem có dấu tiếng Việt + khoảng trắng).
		string payload = $"{{\"type\":\"debug_command\",\"command\":{JsonSerializer.Serialize(command)}}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
		if (_debugCommandStatus != null)
		{
			string head = command.Length > 38 ? command.Substring(0, 38) + "…" : command;
			_debugCommandStatus.Text = "đã gửi: " + head;
		}
	}

	private void ApplyTypewriterEffect(string text){
		if (_textTween != null && _textTween.IsValid())
		{
			_textTween.Kill();
		}

		text ??= "";

		// Câu rỗng = không có gì để đọc → ẩn bong bóng luôn.
		if (string.IsNullOrWhiteSpace(text))
		{
			if (_bubble != null)
				_bubble.Visible = false;
			_bubbleHideAtMs = 0;
			_label.Text = "";
			return;
		}

		// Bật cuộn + tự bám đáy để tin nhắn dài không bị tràn khỏi khung bong bóng.
		// Chữ được nối dần (progressive) thay vì set hết rồi mới hé lộ, nhờ vậy
		// ScrollFollowing luôn kéo xuống dòng mới nhất đang gõ.
		_label.ClipContents = true;
		_label.ScrollActive = true;
		_label.ScrollFollowing = true;
		_label.VisibleCharacters = -1;
		_label.Text = "";

		// Hiện bong bóng đúng lúc Eris bắt đầu nói. Việc bật Visible cũng buộc
		// cửa sổ overlay trong suốt vẽ lại vùng này (nếu không nó hay "kẹt" ẩn).
		if (_bubble != null)
			_bubble.Visible = true;

		_textTween = CreateTween();

		float speedPerChar = 0.05f;
		float totalDuration = Mathf.Max(0.01f, text.Length * speedPerChar);

		// Lên lịch tự ẩn: gõ xong + chừa thời gian đọc (tỉ lệ theo độ dài câu).
		if (BubbleReadSeconds > 0f)
		{
			float readSeconds = Mathf.Max(BubbleReadSeconds, text.Length * 0.06f);
			_bubbleHideAtMs = Time.GetTicksMsec() + (ulong)((totalDuration + readSeconds) * 1000f);
		}
		else
		{
			_bubbleHideAtMs = 0; // không tự ẩn
		}

		// thực thi hiệu ứng gõ chữ
		_textTween.TweenMethod(Callable.From<int>(count => RevealTypewriterText(text, count)), 0, text.Length, totalDuration);
	}

	private void RevealTypewriterText(string fullText, int count)
	{
		if (_label == null)
			return;

		count = Mathf.Clamp(count, 0, fullText.Length);
		_label.Text = fullText.Substring(0, count);

		// Ép thanh cuộn bám đáy để dòng vừa gõ luôn nằm trong khung.
		VScrollBar scrollBar = _label.GetVScrollBar();
		if (scrollBar != null)
			scrollBar.Value = scrollBar.MaxValue;
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
		if (TryHandleTutorEvent(raw))
			return;
		var payload = _decisionParser.Parse(raw);
		if (payload.HasEmotionDebug)
		{
			_latestEmotionDebug = payload.EmotionDebug;
			if (_emotionPanel != null && _emotionPanel.Visible)
				RefreshEmotionPanel();
		}
		TryApplyDebugCommandAck(raw);
		if (payload.HasPrivateMindDebug)
		{
			// Chỉ nhận digest có nội dung thật; digest rỗng bị bỏ qua để giữ liên tục
			if (PrivateMindDigestHasContent(payload.PrivateMindDebugJson))
			{
				_latestPrivateMindDebugJson = payload.PrivateMindDebugJson;
				SavePrivateMindState();
				if (_privateMindPanel != null && _privateMindPanel.Visible)
					RefreshPrivateMindPanel();
				if (_anchorPanel != null && _anchorPanel.Visible)
					RefreshAnchorPanel();
			}
		}
		if (payload.HasBodyBias)
			_bodyAutonomy?.ApplyCognitionBias(payload.BodyBias);

		TryCaptureDepthBlock(raw);
		TryCaptureDepthV2Block(raw);

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
		// Casual mode: dùng riêng
		if (_isCasualMode)
		{
			if (_latestEmotionDebug == null || _latestEmotionDebug.Items == null || _latestEmotionDebug.Items.Count == 0)
				return;
			var byKeyCasual = new Dictionary<string, EmotionDebugItem>(_latestEmotionDebug.Items.Count, StringComparer.Ordinal);
			foreach (var item in _latestEmotionDebug.Items)
				byKeyCasual[item.Key] = item;
			RefreshCasualMode(byKeyCasual, _latestEmotionDebug);
			return;
		}

		// Dev mode — dùng raw item list mới
		if (_devItemList != null)
		{
			RefreshDevMode();
			return;
		}

		// Fallback: dev mode cũ với EmotionRows (portrait + aggregated bars)
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

	private static bool PrivateMindDigestHasContent(string json)
	{
		if (string.IsNullOrWhiteSpace(json))
			return false;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(json);
			JsonElement root = doc.RootElement;
			JsonElement menu = root;
			if (root.ValueKind == JsonValueKind.Object
				&& root.TryGetProperty("menu", out var m) && m.ValueKind == JsonValueKind.Object)
				menu = m;
			return ExtractCurrentThought(menu, root).Count > 0
				|| ExtractFutureThought(menu, root).Count > 0
				|| ExtractConcerns(menu).Count > 0
				|| ExtractFragments(menu, root).Count > 0
				|| ExtractSurface(menu, root).Count > 0;
		}
		catch
		{
			return false;
		}
	}

	private void SavePrivateMindState()
	{
		if (string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson))
			return;
		try
		{
			using var file = Godot.FileAccess.Open(PrivateMindStatePath, Godot.FileAccess.ModeFlags.Write);
			if (file != null)
				file.StoreString(_latestPrivateMindDebugJson);
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[PrivateMind] Save state failed: {ex.Message}");
		}
	}

	private void LoadPrivateMindState()
	{
		try
		{
			if (!Godot.FileAccess.FileExists(PrivateMindStatePath))
				return;
			using var file = Godot.FileAccess.Open(PrivateMindStatePath, Godot.FileAccess.ModeFlags.Read);
			if (file == null)
				return;
			string content = file.GetAsText();
			if (!string.IsNullOrWhiteSpace(content) && PrivateMindDigestHasContent(content))
				_latestPrivateMindDebugJson = content;
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[PrivateMind] Load state failed: {ex.Message}");
		}
	}

	private void RefreshPrivateMindPanel()
	{
		if (_privateMindSectionList == null || _privateMindText == null)
			return;
		foreach (Node child in _privateMindSectionList.GetChildren())
		{
			_privateMindSectionList.RemoveChild(child);
			child.QueueFree();
		}

		JsonElement root = default;
		JsonElement menu = default;
		bool hasData = false;
		JsonDocument doc = null;
		if (!string.IsNullOrWhiteSpace(_latestPrivateMindDebugJson))
		{
			try
			{
				doc = JsonDocument.Parse(_latestPrivateMindDebugJson);
				root = doc.RootElement;
				menu = root;
				if (root.ValueKind == JsonValueKind.Object
					&& root.TryGetProperty("menu", out var menuEl) && menuEl.ValueKind == JsonValueKind.Object)
					menu = menuEl;
				hasData = true;
			}
			catch (Exception ex)
			{
				GD.PrintErr($"[PrivateMind] Parse error: {ex.Message}");
			}
		}

		// Ưu tiên giọng Eris từ inner_diary.sections (nếu có); thiếu thì fallback extractor thô.
		var diaryByTitle = new Dictionary<string, List<PrivateMindDiaryItem>>();
		if (hasData)
		{
			foreach (var sec in TryReadDiarySections(root))
			{
				if (!string.IsNullOrWhiteSpace(sec.Title))
					diaryByTitle[sec.Title.Trim()] = sec.Items;
			}
		}

		// Luôn dựng đủ 5 khung cố định, mỗi khung tự điền dữ liệu nếu có
		var slots = new List<PrivateMindDiarySection>
		{
			BuildDiarySlot("Suy nghĩ hiện tại", PreferDiarySection(diaryByTitle, "Suy nghĩ hiện tại", hasData ? ExtractCurrentThought(menu, root) : null)),
			BuildDiarySlot("Suy nghĩ tương lai", PreferDiarySection(diaryByTitle, "Suy nghĩ tương lai", hasData ? ExtractFutureThought(menu, root) : null)),
			BuildDiarySlot("Đang bận tâm", PreferDiarySection(diaryByTitle, "Đang bận tâm", hasData ? ExtractConcerns(menu) : null)),
			BuildDiarySlot("Phân tích gần đây", PreferDiarySection(diaryByTitle, "Phân tích gần đây", hasData ? ExtractFragments(menu, root) : null)),
			BuildDiarySlot("Muốn nói", PreferDiarySection(diaryByTitle, "Muốn nói", hasData ? ExtractSurface(menu, root) : null)),
		};

		foreach (PrivateMindDiarySection slot in slots)
			_privateMindSectionList.AddChild(BuildPrivateMindSectionCard(slot));

		RefreshDiaryMood();
		RefreshDiaryConcernStack(menu, hasData);
		RefreshDiaryMemoryEcho(menu, hasData);

		_privateMindText.Text = hasData ? RenderDiary(root) : "[i]Chưa có dữ liệu.[/i]";
		doc?.Dispose();
	}

	// ─────────────────────────────────────────────────────────────────────────
	//  Sidebar refresh
	// ─────────────────────────────────────────────────────────────────────────

	private void RefreshDiaryMood()
	{
		if (_diaryValenceBar == null || _diaryArousalBar == null)
			return;

		var debug = _latestEmotionDebug;
		bool hasMood = debug != null && debug.Items != null && debug.Items.Count > 0;

		float valence = hasMood && debug.HasSummaryValence ? Mathf.Clamp(debug.SummaryValence, -1f, 1f) : 0f;
		float arousal = 0f;
		if (hasMood)
		{
			foreach (var it in debug.Items)
			{
				if (it.Key == "calm_aroused" && it.HasNumericValue) { arousal = Mathf.Clamp(it.NumericValue, 0f, 1f); break; }
			}
		}

		float valPct = (valence + 1f) * 50f;   // -1..1 → 0..100
		float aroPct = arousal * 100f;          // 0..1 → 0..100

		_diaryValenceBar.Value = valPct;
		_diaryArousalBar.Value = aroPct;
		if (_diaryValenceLabel != null) _diaryValenceLabel.Text = hasMood ? $"{valPct:0}%" : "—";
		if (_diaryArousalLabel != null) _diaryArousalLabel.Text = hasMood ? $"{aroPct:0}%" : "—";

		UpdateDiaryMoodFace(valence, arousal, hasMood);

		if (_diaryMoodQuoteLabel != null)
		{
			string state = hasMood ? FormatSummaryValue(debug.SummaryState) : "";
			if (string.IsNullOrWhiteSpace(state))
				state = hasMood ? FormatSummaryValue(debug.SummaryValue) : "";
			_diaryMoodQuoteLabel.Text = string.IsNullOrWhiteSpace(state) || state == "unknown"
				? "\u201cđang lặng yên bên Ngài.\u201d"
				: $"\u201c{state}\u201d";
		}
	}

	private void RefreshDiaryConcernStack(JsonElement menu, bool hasData)
	{
		if (_diaryConcernList == null)
			return;

		_diaryConcernData.Clear();
		_diaryConcernData.AddRange(hasData ? ExtractConcernBars(menu) : new List<(string, float)>());
		_diaryConcernExpanded = false; // mỗi lần có dữ liệu mới thì thu gọn lại
		RenderDiaryConcernList();
	}

	private void RenderDiaryConcernList()
	{
		if (_diaryConcernList == null)
			return;

		foreach (Node child in _diaryConcernList.GetChildren())
		{
			_diaryConcernList.RemoveChild(child);
			child.QueueFree();
		}

		if (_diaryConcernData.Count == 0)
		{
			var empty = new Label
			{
				Text = "(chưa có bận tâm nào)",
				AutowrapMode = TextServer.AutowrapMode.WordSmart,
				SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			};
			empty.AddThemeFontSizeOverride("font_size", 12);
			empty.AddThemeColorOverride("font_color", new Color(0.72f, 0.48f, 0.60f));
			_diaryConcernList.AddChild(empty);
			return;
		}

		int total = _diaryConcernData.Count;
		int shown = _diaryConcernExpanded ? total : Mathf.Min(DiaryConcernCollapsedCount, total);
		for (int i = 0; i < shown; i++)
		{
			(string theme, float pct) = _diaryConcernData[i];
			var col = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
			col.AddThemeConstantOverride("separation", 3);

			var labelRow = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
			var themeLabel = new Label
			{
				Text = theme,
				AutowrapMode = TextServer.AutowrapMode.Off,
				ClipText = true,
				SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			};
			themeLabel.AddThemeFontSizeOverride("font_size", 12);
			themeLabel.AddThemeColorOverride("font_color", new Color(0.50f, 0.20f, 0.38f));
			labelRow.AddChild(themeLabel);

			var pctLabel = CreateUiLabel($"{pct:0}%", 12, new Color(0.84f, 0.30f, 0.52f));
			labelRow.AddChild(pctLabel);
			col.AddChild(labelRow);

			ProgressBar bar = CreateDiaryBar(new Color(0.97f, 0.46f, 0.66f));
			bar.Value = pct;
			col.AddChild(bar);

			_diaryConcernList.AddChild(col);
		}

		// Nút thu/xổ: chỉ hiện khi có nhiều hơn số mục thu gọn. Click xử lý trong _Input.
		_diaryConcernToggle = null;
		if (total > DiaryConcernCollapsedCount)
		{
			var toggle = CreateUiLabel(
				_diaryConcernExpanded ? "Thu gọn" : $"+ {total - DiaryConcernCollapsedCount} mục khác",
				12, new Color(0.70f, 0.46f, 0.60f));
			toggle.MouseDefaultCursorShape = Control.CursorShape.PointingHand;
			toggle.MouseFilter = Control.MouseFilterEnum.Stop;
			_diaryConcernList.AddChild(toggle);
			_diaryConcernToggle = toggle;
		}
	}

	private static List<(string Theme, float Pct)> ExtractConcernBars(JsonElement menu)
	{
		var result = new List<(string, float)>();
		if (menu.ValueKind == JsonValueKind.Object
			&& menu.TryGetProperty("open_concerns", out var concerns) && concerns.ValueKind == JsonValueKind.Array)
		{
			foreach (var c in concerns.EnumerateArray())
			{
				if (c.ValueKind != JsonValueKind.Object)
					continue;
				string theme = DiaryStr(c, "theme", 60);
				if (string.IsNullOrWhiteSpace(theme))
					continue;
				float pct = 0f;
				if (c.TryGetProperty("pressure", out var p) && p.ValueKind == JsonValueKind.Number && p.TryGetDouble(out double pressure))
					pct = Mathf.Clamp((float)pressure, 0f, 1f) * 100f;
				result.Add((theme, pct));
			}
		}
		return result;
	}

	private void RefreshDiaryMemoryEcho(JsonElement menu, bool hasData)
	{
		if (_diaryMemoryEchoLabel == null)
			return;

		string quote = "";
		if (hasData)
		{
			JsonElement retained = default;
			bool has = false;
			if (menu.ValueKind == JsonValueKind.Object
				&& menu.TryGetProperty("retained_thoughts", out var rt) && rt.ValueKind == JsonValueKind.Object
				&& rt.TryGetProperty("items", out retained) && retained.ValueKind == JsonValueKind.Array)
				has = true;
			else if (menu.ValueKind == JsonValueKind.Object
				&& menu.TryGetProperty("retained_thoughts", out retained) && retained.ValueKind == JsonValueKind.Array)
				has = true;

			if (has)
			{
				foreach (var r in retained.EnumerateArray())
				{
					if (r.ValueKind == JsonValueKind.String)
						quote = r.GetString() ?? "";
					else if (r.ValueKind == JsonValueKind.Object)
						quote = FirstStr(r, "claim", "text", "thought", "summary");
					quote = CompactText(quote, 160);
					if (!string.IsNullOrWhiteSpace(quote))
						break;
				}
			}
		}

		if (string.IsNullOrWhiteSpace(quote))
		{
			_diaryMemoryEchoLabel.Text = "\u201cchưa có ký ức nào vọng lại.\u201d";
			if (_diaryMemoryEchoMetaLabel != null) _diaryMemoryEchoMetaLabel.Text = "";
		}
		else
		{
			_diaryMemoryEchoLabel.Text = $"\u201c{quote}\u201d";
			if (_diaryMemoryEchoMetaLabel != null) _diaryMemoryEchoMetaLabel.Text = "\u2014 vừa nhớ lại";
		}
	}

	private static PrivateMindDiarySection BuildDiarySlot(string title, List<PrivateMindDiaryItem> items)
	{
		if (items == null || items.Count == 0)
			items = new List<PrivateMindDiaryItem> { new() { Text = "(chưa có)", Badge = "" } };
		return new PrivateMindDiarySection { Title = title, Items = items };
	}

	private static List<PrivateMindDiaryItem> PreferDiarySection(
		Dictionary<string, List<PrivateMindDiaryItem>> diaryByTitle, string title, List<PrivateMindDiaryItem> fallback)
	{
		// Có section giọng Eris cho đúng tiêu đề thì dùng nó; không thì về extractor thô.
		if (diaryByTitle != null && diaryByTitle.TryGetValue(title, out var items) && items != null && items.Count > 0)
			return items;
		return fallback;
	}

	private static List<PrivateMindDiaryItem> ExtractCurrentThought(JsonElement menu, JsonElement root)
	{
		var items = new List<PrivateMindDiaryItem>();
		JsonElement current = default;
		bool has = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("current_thought", out current) && current.ValueKind == JsonValueKind.Object)
			has = true;
		else if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("current", out current) && current.ValueKind == JsonValueKind.Object)
			has = true;
		if (has)
		{
			string dominant = DiaryStr(current, "dominant_judgment", 220);
			if (!string.IsNullOrWhiteSpace(dominant))
				items.Add(new PrivateMindDiaryItem { Text = dominant, Badge = "" });
		}
		return items;
	}

	private static List<PrivateMindDiaryItem> ExtractFutureThought(JsonElement menu, JsonElement root)
	{
		var items = new List<PrivateMindDiaryItem>();
		JsonElement fb = default;
		bool has = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("future_bias", out fb) && fb.ValueKind == JsonValueKind.Object)
			has = true;
		else if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("future_bias", out fb) && fb.ValueKind == JsonValueKind.Object)
			has = true;
		if (!has)
			return items;

		if (fb.TryGetProperty("inquiry_plan", out var plan) && plan.ValueKind == JsonValueKind.Array)
		{
			foreach (var it in plan.EnumerateArray())
			{
				string text = "";
				if (it.ValueKind == JsonValueKind.String)
					text = it.GetString() ?? "";
				else if (it.ValueKind == JsonValueKind.Object)
					text = FirstStr(it, "question", "text", "topic", "theme");
				text = CompactText(text, 160);
				if (!string.IsNullOrWhiteSpace(text))
					items.Add(new PrivateMindDiaryItem { Text = text, Badge = "" });
				if (items.Count >= 3)
					break;
			}
		}

		if (items.Count == 0 && fb.TryGetProperty("speech_bias", out var sb) && sb.ValueKind == JsonValueKind.Object)
		{
			string val = FirstStr(sb, "intent", "next_move", "stance", "tone");
			val = CompactText(val, 160);
			if (!string.IsNullOrWhiteSpace(val))
				items.Add(new PrivateMindDiaryItem { Text = val, Badge = "" });
		}
		return items;
	}

	private static List<PrivateMindDiaryItem> ExtractConcerns(JsonElement menu)
	{
		var items = new List<PrivateMindDiaryItem>();
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("open_concerns", out var concerns) && concerns.ValueKind == JsonValueKind.Array)
		{
			foreach (var c in concerns.EnumerateArray())
			{
				if (c.ValueKind != JsonValueKind.Object)
					continue;
				string theme = DiaryStr(c, "theme", 180);
				if (string.IsNullOrWhiteSpace(theme))
					continue;
				string badge = "";
				if (c.TryGetProperty("pressure", out var p) && p.ValueKind == JsonValueKind.Number && p.TryGetDouble(out double pressure))
					badge = $"ap luc {pressure:0.##}";
				items.Add(new PrivateMindDiaryItem { Text = theme, Badge = badge });
				if (items.Count >= 4)
					break;
			}
		}
		return items;
	}

	private static List<PrivateMindDiaryItem> ExtractFragments(JsonElement menu, JsonElement root)
	{
		var items = new List<PrivateMindDiaryItem>();
		JsonElement fragments = default;
		bool has = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("temporary_thoughts", out var tmp)
			&& tmp.ValueKind == JsonValueKind.Object && tmp.TryGetProperty("fragments", out fragments) && fragments.ValueKind == JsonValueKind.Array)
			has = true;
		else if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("temporary", out var tmpRoot) && tmpRoot.ValueKind == JsonValueKind.Object
			&& tmpRoot.TryGetProperty("fragments", out fragments) && fragments.ValueKind == JsonValueKind.Array)
			has = true;
		if (!has)
			return items;

		foreach (var f in fragments.EnumerateArray())
		{
			if (f.ValueKind != JsonValueKind.Object)
				continue;
			string claim = DiaryStr(f, "claim", 220);
			if (string.IsNullOrWhiteSpace(claim))
				continue;
			string badge = "";
			if (f.TryGetProperty("score", out var s) && s.ValueKind == JsonValueKind.Number && s.TryGetDouble(out double score))
				badge = $"score {score:0.##}";
			items.Add(new PrivateMindDiaryItem { Text = claim, Badge = badge });
			if (items.Count >= 4)
				break;
		}
		return items;
	}

	private static List<PrivateMindDiaryItem> ExtractSurface(JsonElement menu, JsonElement root)
	{
		var items = new List<PrivateMindDiaryItem>();
		JsonElement queue = default;
		bool has = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("surface_queue", out queue) && queue.ValueKind == JsonValueKind.Array)
			has = true;
		else if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("surface_queue", out queue) && queue.ValueKind == JsonValueKind.Array)
			has = true;
		if (!has)
			return items;

		foreach (var q in queue.EnumerateArray())
		{
			string text = "";
			if (q.ValueKind == JsonValueKind.String)
				text = q.GetString() ?? "";
			else if (q.ValueKind == JsonValueKind.Object)
				text = FirstStr(q, "topic_seed", "text", "claim");
			text = CompactText(text, 160);
			if (!string.IsNullOrWhiteSpace(text))
				items.Add(new PrivateMindDiaryItem { Text = text, Badge = "" });
			if (items.Count >= 3)
				break;
		}
		return items;
	}

	private static string FirstStr(JsonElement obj, params string[] keys)
	{
		if (obj.ValueKind != JsonValueKind.Object)
			return "";
		foreach (string key in keys)
		{
			if (obj.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String)
			{
				string s = v.GetString() ?? "";
				if (!string.IsNullOrWhiteSpace(s))
					return s;
			}
		}
		return "";
	}

	private static IEnumerable<string> GetJsonKeys(JsonElement el)
	{
		if (el.ValueKind != JsonValueKind.Object)
			return Array.Empty<string>();
		var keys = new List<string>();
		foreach (var prop in el.EnumerateObject())
			keys.Add(prop.Name);
		return keys;
	}

	private static string ExtractAnyMeaningfulText(JsonElement root)
	{
		// Thử lấy dominant_judgment từ current
		if (root.TryGetProperty("current", out var cur) && cur.ValueKind == JsonValueKind.Object
			&& cur.TryGetProperty("dominant_judgment", out var dj) && dj.ValueKind == JsonValueKind.String)
		{
			string t = dj.GetString() ?? "";
			if (!string.IsNullOrWhiteSpace(t)) return t;
		}
		// Thử inner_diary.text
		if (root.TryGetProperty("inner_diary", out var diary) && diary.ValueKind == JsonValueKind.Object
			&& diary.TryGetProperty("text", out var txt) && txt.ValueKind == JsonValueKind.String)
		{
			string t = txt.GetString() ?? "";
			if (!string.IsNullOrWhiteSpace(t)) return t.Length > 300 ? t[..300] + "..." : t;
		}
		return "";
	}

	/// <summary>
	/// Render private mind digest thành diary tiếng Việt dễ đọc.
	/// Ưu tiên inner_diary.sections nếu có; nếu không, tự dựng từ current/concerns/fragments.
	/// </summary>
	private PanelContainer BuildPrivateMindPlaceholderCard(string message)
	{
		var card = new PanelContainer();
		card.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.965f, 0.985f, 0.95f),
			BorderColor = new Color(0.98f, 0.80f, 0.88f, 0.95f),
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 22,
			CornerRadiusTopRight = 22,
			CornerRadiusBottomRight = 22,
			CornerRadiusBottomLeft = 22,
			ContentMarginLeft = 24,
			ContentMarginTop = 20,
			ContentMarginRight = 24,
			ContentMarginBottom = 20,
		});

		var text = new Label
		{
			Text = message,
			AutowrapMode = TextServer.AutowrapMode.WordSmart,
			SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
		};
		text.AddThemeFontSizeOverride("font_size", 17);
		text.AddThemeColorOverride("font_color", new Color(0.58f, 0.20f, 0.38f));
		card.AddChild(text);
		return card;
	}

	private PanelContainer BuildPrivateMindSectionCard(PrivateMindDiarySection section)
	{
		(string iconAsset, string badgeText, Color accent) = DiarySectionStyle(section.Title);

		var card = new PanelContainer();
		card.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		card.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.978f, 0.989f, 0.97f),
			BorderColor = new Color(0.97f, 0.82f, 0.89f, 0.95f),
			BorderWidthLeft = 2,
			BorderWidthTop = 2,
			BorderWidthRight = 2,
			BorderWidthBottom = 2,
			CornerRadiusTopLeft = 20,
			CornerRadiusTopRight = 20,
			CornerRadiusBottomRight = 20,
			CornerRadiusBottomLeft = 20,
			ContentMarginLeft = 18,
			ContentMarginTop = 0,
			ContentMarginRight = 18,
			ContentMarginBottom = 16,
		});

		var content = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		content.AddThemeConstantOverride("separation", 10);
		card.AddChild(content);

		// Header: khung banner với tiêu đề chèn lên vùng trống + badge phân loại bên phải.
		Control header = BuildDiaryHeader(iconAsset, section.Title,
			new Color(0.55f, 0.16f, 0.36f), badgeText, accent, 64f, 12);
		header.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
		content.AddChild(header);

		// Body: từng dòng item với bullet
		var rows = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
		rows.AddThemeConstantOverride("separation", 8);
		content.AddChild(rows);

		foreach (PrivateMindDiaryItem item in section.Items)
		{
			var row = new HBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
			row.AddThemeConstantOverride("separation", 10);
			rows.AddChild(row);

			var bullet = CreateUiLabel("*", 16, new Color(0.98f, 0.58f, 0.76f));
			bullet.CustomMinimumSize = new Vector2(14f, 0f);
			row.AddChild(bullet);

			var line = new Label
			{
				Text = item.Text,
				AutowrapMode = TextServer.AutowrapMode.WordSmart,
				SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
			};
			line.AddThemeFontSizeOverride("font_size", 15);
			line.AddThemeColorOverride("font_color", new Color(0.44f, 0.20f, 0.34f));
			row.AddChild(line);
		}

		return card;
	}

	// Icon asset + badge + màu nhấn cho từng loại section, khớp với mockup.
	private static (string IconAsset, string Badge, Color Accent) DiarySectionStyle(string title)
	{
		switch (title)
		{
			case "Suy nghĩ hiện tại": return ("diary_now", "Hiện tại", new Color(0.95f, 0.42f, 0.66f));
			case "Suy nghĩ tương lai": return ("diary_future", "Dự đoán", new Color(0.66f, 0.50f, 0.92f));
			case "Đang bận tâm": return ("diary_concern_card", "Ưu tiên cao", new Color(0.95f, 0.46f, 0.42f));
			case "Phân tích gần đây": return ("diary_analysis", "Phân tích", new Color(0.40f, 0.66f, 0.86f));
			case "Muốn nói": return ("diary_surface", "Bề mặt", new Color(0.94f, 0.40f, 0.60f));
			default: return ("diary_now", "", new Color(0.95f, 0.42f, 0.66f));
		}
	}

	private Control BuildPrivateMindBadge(string text)
	{
		var pill = new PanelContainer
		{
			SizeFlagsHorizontal = Control.SizeFlags.ShrinkEnd,
			CustomMinimumSize = new Vector2(0f, 38f),
		};
		pill.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(1f, 0.90f, 0.95f, 0.92f),
			CornerRadiusTopLeft = 18,
			CornerRadiusTopRight = 18,
			CornerRadiusBottomRight = 18,
			CornerRadiusBottomLeft = 18,
			ContentMarginLeft = 16,
			ContentMarginTop = 8,
			ContentMarginRight = 16,
			ContentMarginBottom = 8,
		});

		var label = CreateUiLabel($"({text})", 15, new Color(0.97f, 0.32f, 0.67f));
		pill.AddChild(label);
		return pill;
	}

	private static List<PrivateMindDiarySection> BuildPrivateMindDiarySections(JsonElement root)
	{
		List<PrivateMindDiarySection> sections = TryReadDiarySections(root);
		if (sections.Count > 0)
			return sections;
		return BuildPrivateMindDiarySectionsFromRaw(root);
	}

	private static List<PrivateMindDiarySection> TryReadDiarySections(JsonElement root)
	{
		var sections = new List<PrivateMindDiarySection>();
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
		if (!found || !diaryEl.TryGetProperty("sections", out var sectionsEl) || sectionsEl.ValueKind != JsonValueKind.Array)
			return sections;

		foreach (var sectionEl in sectionsEl.EnumerateArray())
		{
			if (sectionEl.ValueKind != JsonValueKind.Object)
				continue;

			string title = sectionEl.TryGetProperty("title", out var titleEl) ? titleEl.GetString() ?? "" : "";
			if (string.IsNullOrWhiteSpace(title))
				continue;

			var items = new List<PrivateMindDiaryItem>();
			if (sectionEl.TryGetProperty("items", out var itemsEl) && itemsEl.ValueKind == JsonValueKind.Array)
			{
				foreach (var itemEl in itemsEl.EnumerateArray())
				{
					if (itemEl.ValueKind != JsonValueKind.Object)
						continue;
					string text = itemEl.TryGetProperty("text", out var itemTextEl) ? itemTextEl.GetString() ?? "" : "";
					string badge = itemEl.TryGetProperty("badge", out var badgeEl) ? badgeEl.GetString() ?? "" : "";
					if (!string.IsNullOrWhiteSpace(text))
						items.Add(new PrivateMindDiaryItem { Text = text, Badge = badge });
				}
			}

			if (items.Count == 0 && sectionEl.TryGetProperty("lines", out var linesEl) && linesEl.ValueKind == JsonValueKind.Array)
			{
				foreach (var lineEl in linesEl.EnumerateArray())
				{
					string line = lineEl.GetString() ?? "";
					if (string.IsNullOrWhiteSpace(line))
						continue;
					string text = line.StartsWith("- ", StringComparison.Ordinal) ? line[2..] : line;
					items.Add(new PrivateMindDiaryItem { Text = text, Badge = "" });
				}
			}

			if (items.Count > 0)
				sections.Add(new PrivateMindDiarySection { Title = title, Items = items });
		}

		if (sections.Count == 0 && diaryEl.TryGetProperty("text", out var textEl) && textEl.ValueKind == JsonValueKind.String)
			sections = ParseDiarySectionsFromText(textEl.GetString() ?? "");

		return sections;
	}

	private static List<PrivateMindDiarySection> BuildPrivateMindDiarySectionsFromRaw(JsonElement root)
	{
		var sections = new List<PrivateMindDiarySection>();
		if (root.ValueKind != JsonValueKind.Object)
			return sections;

		JsonElement menu = root;
		if (root.TryGetProperty("menu", out var menuEl) && menuEl.ValueKind == JsonValueKind.Object)
			menu = menuEl;

		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("open_concerns", out var concerns) && concerns.ValueKind == JsonValueKind.Array)
		{
			var items = new List<PrivateMindDiaryItem>();
			foreach (var c in concerns.EnumerateArray())
			{
				if (c.ValueKind != JsonValueKind.Object)
					continue;
				string theme = DiaryStr(c, "theme", 180);
				if (string.IsNullOrWhiteSpace(theme))
					continue;
				string badge = "";
				if (c.TryGetProperty("pressure", out var pressureEl) && pressureEl.ValueKind == JsonValueKind.Number && pressureEl.TryGetDouble(out double pressure))
					badge = $"ap luc {pressure:0.##}";
				items.Add(new PrivateMindDiaryItem { Text = theme, Badge = badge });
				if (items.Count >= 4)
					break;
			}
			if (items.Count > 0)
				sections.Add(new PrivateMindDiarySection { Title = "Dang ban tam", Items = items });
		}

		JsonElement fragments = default;
		bool hasFragments = false;
		if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("temporary_thoughts", out var tmp)
		    && tmp.ValueKind == JsonValueKind.Object && tmp.TryGetProperty("fragments", out fragments)
		    && fragments.ValueKind == JsonValueKind.Array)
			hasFragments = true;
		else if (root.TryGetProperty("temporary", out var tmpRoot) && tmpRoot.ValueKind == JsonValueKind.Object
		         && tmpRoot.TryGetProperty("fragments", out fragments) && fragments.ValueKind == JsonValueKind.Array)
			hasFragments = true;

		if (hasFragments)
		{
			var items = new List<PrivateMindDiaryItem>();
			foreach (var f in fragments.EnumerateArray())
			{
				if (f.ValueKind != JsonValueKind.Object)
					continue;
				string claim = DiaryStr(f, "claim", 220);
				if (string.IsNullOrWhiteSpace(claim))
					continue;
				string badge = "";
				if (f.TryGetProperty("score", out var scoreEl) && scoreEl.ValueKind == JsonValueKind.Number && scoreEl.TryGetDouble(out double score))
					badge = $"score {score:0.##}";
				items.Add(new PrivateMindDiaryItem { Text = claim, Badge = badge });
				if (items.Count >= 4)
					break;
			}
			if (items.Count > 0)
				sections.Add(new PrivateMindDiarySection { Title = "Phan tich gan day", Items = items });
		}

		if (sections.Count == 0)
		{
			JsonElement current = default;
			bool hasCurrent = false;
			if (menu.ValueKind == JsonValueKind.Object && menu.TryGetProperty("current_thought", out current) && current.ValueKind == JsonValueKind.Object)
				hasCurrent = true;
			else if (root.TryGetProperty("current", out current) && current.ValueKind == JsonValueKind.Object)
				hasCurrent = true;

			if (hasCurrent)
			{
				string dominant = DiaryStr(current, "dominant_judgment", 220);
				if (!string.IsNullOrWhiteSpace(dominant))
				{
					sections.Add(new PrivateMindDiarySection
					{
						Title = "Dang nghi",
						Items = new List<PrivateMindDiaryItem> { new() { Text = dominant, Badge = "" } },
					});
				}
			}
		}

		return sections;
	}

	private static List<PrivateMindDiarySection> ParseDiarySectionsFromText(string raw)
	{
		var sections = new List<PrivateMindDiarySection>();
		if (string.IsNullOrWhiteSpace(raw))
			return sections;

		string currentTitle = "";
		var currentItems = new List<PrivateMindDiaryItem>();
		foreach (string piece in raw.Split('\n'))
		{
			string line = (piece ?? "").Trim();
			if (string.IsNullOrWhiteSpace(line))
				continue;

			if (line.EndsWith(":", StringComparison.Ordinal))
			{
				if (!string.IsNullOrWhiteSpace(currentTitle) && currentItems.Count > 0)
					sections.Add(new PrivateMindDiarySection { Title = currentTitle, Items = new List<PrivateMindDiaryItem>(currentItems) });

				currentTitle = line[..^1].Trim();
				currentItems.Clear();
				continue;
			}

			string text = line.StartsWith("- ", StringComparison.Ordinal) ? line[2..].Trim() : line;
			if (string.IsNullOrWhiteSpace(text))
				continue;

			currentItems.Add(new PrivateMindDiaryItem { Text = text, Badge = "" });
		}

		if (!string.IsNullOrWhiteSpace(currentTitle) && currentItems.Count > 0)
			sections.Add(new PrivateMindDiarySection { Title = currentTitle, Items = currentItems });

		return sections;
	}

	private static List<PrivateMindDiarySection> ParseDiarySectionsFromRenderedText(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return new List<PrivateMindDiarySection>();

		var plain = new StringBuilder(raw.Length);
		bool insideTag = false;
		foreach (char ch in raw)
		{
			if (ch == '[')
			{
				insideTag = true;
				continue;
			}
			if (insideTag)
			{
				if (ch == ']')
					insideTag = false;
				continue;
			}
			plain.Append(ch);
		}

		return ParseDiarySectionsFromText(plain.ToString());
	}

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

		// Fallback: tự dựng diary từ dữ liệu thô - tiếng Việt, không dump JSON
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

			// Nếu không có line nào thực sự thì digest chưa đủ data (synthesis đang fail).
			// Trả false để fallback raw JSON thay vì hiện panel trống chỉ có tiêu đề.
			if (totalLines == 0)
				return false;

			bbcode = sb.ToString().TrimStart('\n');
			return true;
		}

		// Có inner_diary nhưng chỉ có text thuần - render text đó.
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

	// Định nghĩa 4 thanh cố định cho panel cảm xúc.
	// Mỗi thanh tổng hợp từ một hoặc nhiều key trong emotion_debug.items,
	// ánh xạ trực tiếp tới ngữ nghĩa mà user nhìn thấy.
	private readonly struct EmotionPanelSlot
	{
		public readonly string Title;
		public readonly string Note;
		// Các key đóng góp + trọng số (tổng trọng số nên = 1.0).
		// Nếu key không có trong payload, bỏ qua (không ảnh hưởng normalize).
		public readonly (string Key, float Weight, bool Invert)[] Sources;

		public EmotionPanelSlot(string title, string note, params (string Key, float Weight, bool Invert)[] sources)
		{
			Title = title;
			Note = note;
			Sources = sources;
		}
	}

	private static readonly EmotionPanelSlot[] EmotionPanelSlots =
	{
		// Bình tĩnh = arousal thấp + overload thấp + irritation thấp
		new("Bình tĩnh", "Arousal thấp, không quá tải, không khó chịu.",
			("calm_aroused",   0.45f, true),   // arousal cao → bình tĩnh thấp
			("overload",       0.30f, true),   // overload cao → bình tĩnh thấp
			("irritation",     0.25f, true)),  // irritation cao → bình tĩnh thấp

		// Kích thích = arousal + curiosity + thought_stream_pressure
		new("Kích thích", "Hưng phấn, phấn khích, dòng suy nghĩ đang tăng.",
			("calm_aroused",            0.55f, false),
			("curiosity",               0.25f, false),
			("thought_stream_pressure", 0.20f, false)),

		// Mood = stability cao + inertia thấp, lệch theo valence
		new("Mood", "Ổn định tâm trạng, quán tính mood, hướng valence.",
			("emotional_stability", 0.50f, false),
			("mood_inertia",        0.30f, true),   // inertia cao = mood kém ổn
			("calm_aroused",        0.20f, true)),  // arousal cao cũng kéo mood

		// Cảm xúc tích cực = valence gốc + warmth + tenderness + attachment + intimacy
		new("Cảm xúc tích cực", "Ấm áp, gắn bó, dịu dàng, thân mật.",
			("warmth",      0.28f, false),
			("tenderness",  0.26f, false),
			("attachment",  0.26f, false),
			("intimacy",    0.20f, false)),
	};

	private void RefreshEmotionPanelRows()
	{
		if (_emotionSummaryLabel == null)
			return;

		if (_latestEmotionDebug == null || _latestEmotionDebug.Items == null || _latestEmotionDebug.Items.Count == 0)
		{
			_emotionSummaryLabel.Text = "Cảm xúc";
			if (_emotionHintLabel != null)
				_emotionHintLabel.Text = "Chưa có frame cảm xúc.";
			return;
		}

		// Build lookup: key → item (O(n) một lần, dùng lại cho 4 slot)
		var byKey = new Dictionary<string, EmotionDebugItem>(_latestEmotionDebug.Items.Count, StringComparer.Ordinal);
		foreach (var item in _latestEmotionDebug.Items)
			byKey[item.Key] = item;

		// Summary label — dùng valence để tô màu ngữ cảnh
		string summaryMood = string.IsNullOrWhiteSpace(_latestEmotionDebug.SummaryValue) ? "unknown" : _latestEmotionDebug.SummaryValue;
		string summaryState = string.IsNullOrWhiteSpace(_latestEmotionDebug.SummaryState) ? "" : _latestEmotionDebug.SummaryState;
		string summaryDisplay = FormatSummaryValue(summaryMood);
		_emotionSummaryLabel.Text = string.IsNullOrWhiteSpace(summaryDisplay) || summaryDisplay == "unknown"
			? "Cảm xúc"
			: $"Cảm xúc — {summaryDisplay}";

		// Hint line: romcom-style summary
		if (_emotionHintLabel != null)
			_emotionHintLabel.Text = BuildRomcomHint(byKey, _latestEmotionDebug);

		// Render 4 slot cố định
		for (int i = 0; i < _emotionRows.Count && i < EmotionPanelSlots.Length; i++)
		{
			var slot = EmotionPanelSlots[i];
			float value = ComputeSlotValue(slot, byKey);
			_emotionRows[i].Row.Visible = true;
			UpdateEmotionRow(_emotionRows[i], slot.Title, slot.Note, value);
		}
	}

	/// <summary>
	/// Tính giá trị tổng hợp cho một slot bằng weighted average
	/// trên các key thực sự có mặt trong payload (normalize động).
	/// </summary>
	private static float ComputeSlotValue(in EmotionPanelSlot slot, Dictionary<string, EmotionDebugItem> byKey)
	{
		float weightedSum = 0f;
		float totalWeight = 0f;
		foreach (var (key, weight, invert) in slot.Sources)
		{
			if (!byKey.TryGetValue(key, out var item) || !item.HasNumericValue)
				continue;
			float v = invert ? 1f - item.NumericValue : item.NumericValue;
			weightedSum += v * weight;
			totalWeight += weight;
		}
		if (totalWeight <= 0f)
			return 0f;
		// Normalize lại theo trọng số thực tế có mặt
		return Mathf.Clamp(weightedSum / totalWeight, 0f, 1f);
	}

	/// <summary>
	/// Tạo một dòng hint ngắn kiểu romcom từ trạng thái hiện tại,
	/// ví dụ: "Hôm nay ổn, hơi rung động, muốn gần vừa đủ, vẫn giữ nhịp."
	/// </summary>
	private static string BuildRomcomHint(Dictionary<string, EmotionDebugItem> byKey, EmotionDebug debug)
	{
		float GetVal(string key) => byKey.TryGetValue(key, out var it) && it.HasNumericValue ? it.NumericValue : 0f;

		float arousal    = GetVal("calm_aroused");
		float stability  = GetVal("emotional_stability");
		float attachment = GetVal("attachment");
		float tenderness = GetVal("tenderness");
		float warmth     = GetVal("warmth");
		float distance   = GetVal("distance");
		float irritation = GetVal("irritation");
		float intimacy   = GetVal("intimacy");

		// Trạng thái nền
		string mood = (arousal < 0.30f && irritation < 0.25f) ? "ổn" :
		              (irritation >= 0.50f)                   ? "hơi căng" :
		              (arousal >= 0.65f)                      ? "đang hứng" : "bình thường";

		// Rung động / cảm xúc tích cực
		float warmCore = (warmth + tenderness + attachment) / 3f;
		string feel = warmCore >= 0.65f ? "rung động nhiều" :
		              warmCore >= 0.40f ? "hơi rung động"   :
		              warmCore >= 0.20f ? "dịu vừa"         : "phẳng lặng";

		// Khoảng cách xã hội
		string proximity = (intimacy >= 0.55f && distance <= 0.45f) ? "muốn gần" :
		                   (distance >= 0.65f)                       ? "giữ khoảng cách" : "vừa đủ";

		// Ổn định nhịp
		string rhythm = stability >= 0.70f ? "giữ nhịp rất đẹp" :
		                stability >= 0.45f ? "nhịp ổn"          : "nhịp hơi dao động";

		return $"{mood}, {feel}, {proximity}, {rhythm}.";
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
		// Chuẩn hóa alias trước (walk -> stand_walk, v.v.)
		if (_animAliases.TryGetValue(animation, out var mapped))
		{
			GD.Print($"[Anim] Alias '{animation}' -> '{mapped}'");
			animation = mapped;
		}

		// Kiểm tra animation có hợp lệ không
		if (!_validAnimations.Contains(animation))
		{
			// Nếu có direction thì người dùng muốn đi, fallback về stand_walk
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

	private ErisServiceConfig BuildServiceConfig()
	{
		return new ErisServiceConfig
		{
			PythonExecutable = PythonExecutable,
			VisionScriptPath = VisionScriptPath,
			EnableRemoteCognitionApi = EnableRemoteCognitionApi,
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

	// ── Casual mode refresh ───────────────────────────────────────────────────

	private void RefreshCasualMode(Dictionary<string, EmotionDebugItem> byKey, EmotionDebug debug)
	{
		float GetVal(string key) => byKey.TryGetValue(key, out var it) && it.HasNumericValue ? it.NumericValue : 0f;

		// Narrative label
		if (_casualNarrativeLabel != null)
			_casualNarrativeLabel.Text = $"\"{BuildRomcomCore(byKey)}\"";

		// Circumplex dot: valence từ summary, arousal từ calm_aroused
		//   valence: positive=vui (trái), negative=khó chịu (phải) → map sang -1..1
		float rawValence = debug.HasSummaryValence ? Mathf.Clamp(debug.SummaryValence, -1f, 1f) : 0f;
		float rawArousal = GetVal("calm_aroused") * 2f - 1f; // 0..1 → -1..1 (1=kích thích cao)
		_moodDotValence = rawValence;
		_moodDotArousal = rawArousal;
		// State text do AI gửi về — format snake_case → readable
		_moodStateName = FormatSummaryValue(debug.SummaryValue);
		_moodStateDesc = string.IsNullOrWhiteSpace(debug.SummaryState) ? "" : debug.SummaryState;
		_moodDotCanvas?.QueueRedraw();

		// 3 casual bars
		if (_casualBars.Count >= 3)
		{
			// Bar 0: Gắn bó
			float bond = (GetVal("attachment") + GetVal("tenderness") + GetVal("warmth")) / 3f;
			UpdateCasualBar(0, bond, CasualBarDefs[0].Levels);
			// Bar 1: Nhịp điệu (stability, invert mood_inertia)
			float rhythm = GetVal("emotional_stability") * 0.6f + (1f - GetVal("mood_inertia")) * 0.4f;
			UpdateCasualBar(1, Mathf.Clamp(rhythm, 0f, 1f), CasualBarDefs[1].Levels);
			// Bar 2: Muốn nói (payload gửi silence_pressure dưới key "speech_pressure")
			float speech = Mathf.Clamp((GetVal("speech_pressure") + GetVal("social_pressure")) * 0.5f, 0f, 1f);
			UpdateCasualBar(2, speech, CasualBarDefs[2].Levels);
		}

		// Hint = valence + state
		if (_emotionHintLabel != null && debug.HasSummaryValence)
			_emotionHintLabel.Text = $"valence {debug.SummaryValence:+0.00;-0.00}  ·  {debug.SummaryState}";
	}

	private void UpdateCasualBar(int idx, float value, string[] levels)
	{
		const float BarW = 200f; // khớp với BarTrackW trong BuildCasualContent
		var (fillClip, _, wordLabel) = _casualBars[idx];
		float w = Mathf.Clamp(value, 0f, 1f) * BarW;
		fillClip.Size = new Vector2(w, fillClip.Size.Y);
		if (fillClip is Panel p)
			p.CustomMinimumSize = new Vector2(w, p.CustomMinimumSize.Y);
		wordLabel.Text = ValueToWord(value, levels);
	}

	/// <summary>Phiên bản rút gọn của BuildRomcomHint — chỉ lấy core phrase.</summary>
	private static string BuildRomcomCore(Dictionary<string, EmotionDebugItem> byKey)
	{
		float GetVal(string key) => byKey.TryGetValue(key, out var it) && it.HasNumericValue ? it.NumericValue : 0f;
		float arousal    = GetVal("calm_aroused");
		float irritation = GetVal("irritation");
		float warmCore   = (GetVal("warmth") + GetVal("tenderness") + GetVal("attachment")) / 3f;
		float intimacy   = GetVal("intimacy");
		float distance   = GetVal("distance");

		string mood = arousal < 0.30f && irritation < 0.25f ? "ổn, bình tĩnh" :
		              irritation >= 0.55f                   ? "hơi bồn chồn"   :
		              arousal >= 0.65f                      ? "đang hứng khởi" : "bình thường";

		string feel = warmCore >= 0.60f ? "rung động" :
		              warmCore >= 0.35f ? "ấm áp vừa" : "khá phẳng";

		string prox = intimacy >= 0.55f && distance <= 0.45f ? "muốn gần" :
		              distance >= 0.65f                       ? "giữ khoảng cách" : "vừa đủ";

		return $"{mood}, {feel}, {prox}";
	}
}

/// <summary>
/// Control vẽ 2D circumplex wheel — hình tròn gradient + mood dot.
/// valence: -1=vui vẻ(trái) … +1=khó chịu(phải)
/// arousal: +1=hưng phấn(trên) … -1=bình tĩnh(dưới)
/// </summary>
public sealed partial class _MoodDotCanvas : Control
{
	private UdpListener _owner;
	private float _w = 260f, _h = 260f;

	public void SetOwnerListener(UdpListener owner, float w, float h)
	{
		_owner = owner;
		_w = w; _h = h;
	}
	// backward compat
	public void SetOwnerListener(UdpListener owner, float size = 260f)
		=> SetOwnerListener(owner, size, size);

	public override void _Draw()
	{
		float w  = _w > 0 ? _w : Size.X;
		float h  = _h > 0 ? _h : Size.Y;
		float cx = w * 0.5f;
		float cy = h * 0.5f;
		float r  = Mathf.Min(w, h) * 0.40f;  // radius vòng tròn chính

		var ringColor  = new Color(0.95f, 0.72f, 0.84f, 0.90f);
		var axisColor  = new Color(0.90f, 0.72f, 0.82f, 0.55f);
		var tickColor  = new Color(0.93f, 0.60f, 0.76f, 0.80f);
		var heartColor = new Color(0.97f, 0.72f, 0.82f, 0.90f);
		var dotColor   = new Color(0.97f, 0.38f, 0.64f, 1.00f);
		var dotGlow    = new Color(0.97f, 0.38f, 0.64f, 0.20f);

		// ── Gradient fill bên trong vòng tròn (nhiều lớp mờ) ──────────────
		// Quadrant colors: top-left=vàng ấm, top-right=hồng, bottom-left=xanh nhạt, bottom-right=tím nhạt
		int gradSteps = 32;
		for (int i = 0; i < gradSteps; i++)
		{
			float t = (float)i / gradSteps;
			float ri = r * t;
			float alpha = 0.055f * (1f - t * 0.5f);
			// Blend giữa vàng (arousal cao, valence dương) và hồng nhạt
			var fillColor = new Color(1.0f, 0.88f + t * 0.08f, 0.92f - t * 0.10f, alpha * 2.0f);
			DrawCircle(new Vector2(cx, cy), ri, fillColor);
		}

		// Lớp gradient màu hồng lan toa phía dưới-trái (calm+vui = ấm áp)
		for (int i = 0; i < 18; i++)
		{
			float t = (float)i / 18f;
			float gx = cx - r * 0.25f;
			float gy = cy + r * 0.30f;
			float gr = r * 0.55f * (1f - t);
			DrawCircle(new Vector2(gx, gy), gr, new Color(1.0f, 0.82f, 0.72f, 0.04f));
		}
		// Lớp gradient tím nhạt phía trên-phải (arousal cao + khó chịu)
		for (int i = 0; i < 14; i++)
		{
			float t = (float)i / 14f;
			float gx = cx + r * 0.30f;
			float gy = cy - r * 0.25f;
			float gr = r * 0.50f * (1f - t);
			DrawCircle(new Vector2(gx, gy), gr, new Color(0.78f, 0.72f, 0.96f, 0.045f));
		}

		// ── Vòng tròn chính ───────────────────────────────────────────────
		DrawArc(new Vector2(cx, cy), r, 0f, Mathf.Tau, 64, ringColor, 2f);

		// ── Dashed cross lines bên trong ──────────────────────────────────
		const float dash = 4f, gap = 5f;
		// Trục ngang
		for (float x = cx - r; x < cx + r; x += dash + gap)
		{
			float x2 = Mathf.Min(x + dash, cx + r);
			DrawLine(new Vector2(x, cy), new Vector2(x2, cy), axisColor, 1f);
		}
		// Trục dọc
		for (float y = cy - r; y < cy + r; y += dash + gap)
		{
			float y2 = Mathf.Min(y + dash, cy + r);
			DrawLine(new Vector2(cx, y), new Vector2(cx, y2), axisColor, 1f);
		}

		// ── Tick marks trên vòng tròn tại 4 hướng ────────────────────────
		float tickOuter = r + 6f;
		float tickInner = r - 6f;
		foreach (float angle in new[] { 0f, Mathf.Pi * 0.5f, Mathf.Pi, Mathf.Pi * 1.5f })
		{
			float cos = Mathf.Cos(angle), sin = Mathf.Sin(angle);
			DrawLine(
				new Vector2(cx + cos * tickInner, cy + sin * tickInner),
				new Vector2(cx + cos * tickOuter, cy + sin * tickOuter),
				tickColor, 2f);
		}

		// ── Heart icon tại 4 điểm cực (nằm trên vòng tròn) ──────────────
		// Top (hưng phấn), Bottom (bình tĩnh), Left (vui vẻ), Right (khó chịu)
		var heartPositions = new (float Angle, string Label, float LabelDx, float LabelDy)[]
		{
			(-Mathf.Pi * 0.5f, "hưng phấn", -28f, -26f),
			( Mathf.Pi * 0.5f, "bình tĩnh", -22f,   8f),
			( Mathf.Pi,        "vui vẻ",    -50f,  -8f),
			( 0f,              "khó chịu",   10f,  -8f),
		};
		foreach (var (angle, label, ldx, ldy) in heartPositions)
		{
			float cos = Mathf.Cos(angle), sin = Mathf.Sin(angle);
			float hx = cx + cos * (r + 1f);
			float hy = cy + sin * (r + 1f);
			// Heart symbol nhỏ tại điểm
			DrawCircle(new Vector2(hx - 3f, hy - 1.5f), 3.2f, heartColor);
			DrawCircle(new Vector2(hx + 3f, hy - 1.5f), 3.2f, heartColor);
			// Triangle phần dưới trái tim
			DrawColoredPolygon(new Vector2[]
			{
				new Vector2(hx - 6f, hy),
				new Vector2(hx + 6f, hy),
				new Vector2(hx,      hy + 6f),
			}, heartColor);
		}

		// Axis label text vẽ qua DrawString
		// (Godot DrawString trên Control._Draw cần font — dùng theme default font)
		var font = ThemeDB.FallbackFont;
		int fs = 10;
		var labelCol = new Color(0.50f, 0.22f, 0.38f, 0.92f);

		// ♡ + label bên ngoài vòng tròn
		DrawString(font, new Vector2(cx - 24f, cy - r - 14f), "♡  hưng phấn",  HorizontalAlignment.Center, -1, fs, labelCol);
		DrawString(font, new Vector2(cx - 18f, cy + r + 22f), "♡  bình tĩnh",  HorizontalAlignment.Center, -1, fs, labelCol);
		DrawString(font, new Vector2(cx - r - 64f, cy + 4f),  "♡  vui vẻ",     HorizontalAlignment.Left,   -1, fs, labelCol);
		DrawString(font, new Vector2(cx + r + 8f,  cy + 4f),  "♡  khó chịu",   HorizontalAlignment.Left,   -1, fs, labelCol);

		if (_owner == null) return;

		// ── Mood dot ──────────────────────────────────────────────────────
		float dotX = cx + _owner._moodDotValence  * r * 0.82f;
		float dotY = cy - _owner._moodDotArousal  * r * 0.82f;

		// Glow lớn
		DrawCircle(new Vector2(dotX, dotY), 20f, dotGlow);
		DrawCircle(new Vector2(dotX, dotY), 10f, dotColor with { A = 0.30f });
		// Dot chính
		DrawCircle(new Vector2(dotX, dotY),  8f, dotColor);
		DrawArc(new Vector2(dotX, dotY), 8f, 0f, Mathf.Tau, 32, Colors.White with { A = 0.45f }, 1.5f);
		// Highlight nhỏ
		DrawCircle(new Vector2(dotX - 2.5f, dotY - 2.5f), 2.5f, Colors.White with { A = 0.60f });

		// ── State text ở giữa vòng tròn — do AI gửi về ───────────────────
		string stateName = string.IsNullOrWhiteSpace(_owner._moodStateName) ? "—" : _owner._moodStateName;
		string subText   = string.IsNullOrWhiteSpace(_owner._moodStateDesc) ? ""  : _owner._moodStateDesc;

		int fsMain = 13;
		var mainCol = new Color(0.28f, 0.08f, 0.22f, 0.88f);
		var subCol  = new Color(0.55f, 0.28f, 0.42f, 0.75f);

		// Đo width để căn giữa
		float mainW = font.GetStringSize(stateName, HorizontalAlignment.Left, -1, fsMain).X;
		DrawString(font, new Vector2(cx - mainW * 0.5f, cy - 8f), stateName, HorizontalAlignment.Left, -1, fsMain, mainCol);

		if (!string.IsNullOrWhiteSpace(subText))
		{
			float subW = font.GetStringSize(subText, HorizontalAlignment.Left, -1, fs).X;
			DrawString(font, new Vector2(cx - subW * 0.5f, cy + 8f), subText, HorizontalAlignment.Left, -1, fs, subCol);
		}

		// Nhỏ: dấu ✦ dưới sub text
		DrawString(font, new Vector2(cx - 5f, cy + 22f), "✦", HorizontalAlignment.Left, -1, 10, new Color(0.93f, 0.60f, 0.76f, 0.70f));
	}
}
