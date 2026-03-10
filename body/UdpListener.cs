using Godot;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	private PacketPeerUdp _udp = new PacketPeerUdp();
	private int _port = 4242;
	private AnimatedSprite2D _monika;
	private CharacterBody2D _body;
	private RichTextLabel _label;
	private Process _visionProcess;

	[Export] public string PythonExecutable = "python";
	[Export] public string VisionScriptPath = "src/vision.py";

	// Di chuyển
	private float _moveSpeed = 60f;   // pixel/giây
	private float _moveDir = 1f;      // 1 = phải, -1 = trái
	private bool _isWalking = false;
	private string _currentAction = "stand";
	private float _gravity = 980f; // Gia tốc trọng trường tiêu chuẩn
	private float _velocityY = 0f;
    private bool _isFalling = false;
	private Vector2 _spriteHalfSize; // Lấy từ CollisionShape2D trong _Ready()

	// Climb
	private enum ClimbPhase { None, GoingToWall, Up, Top, Down }
	private ClimbPhase _climbPhase = ClimbPhase.None;
	private float _climbUpWallX;    // X của tường leo lên
	private float _climbDownWallX;  // X của tường leo xuống
	private const float ClimbSpeed = 50f;

	private TextureButton _pointBtn;
	private TextureButton _chatBtn;
	private Panel _chatPanel;
	private LineEdit _chatInput;
	private PacketPeerUdp _chatSend = new PacketPeerUdp();
	private Tween _textTween;
	private AudioStreamPlayer _audioPlayer;
	private readonly Random _rng = new Random();
	private Control _bubble;
	private string _nextAction = ""; // Lưu trữ hành động chờ thực thi
	private string _bounceAction = ""; // animation phát tại tường trước khi đổi chiều (loop mãi)
	private float _targetX = float.NaN; // target_x tuyệt đối trên màn hình (NaN = không có mục tiêu)
	private Vector2 _bubbleBasePos; // vị trí gốc của bubble trong không gian local của sprite

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

	// Animation → danh sách sound (tên ngẫu nhiên, sẽ rename sau)
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
		_udp.Bind(_port);
		_body   = GetNode<CharacterBody2D>("Monika2");
		_monika = GetNode<AnimatedSprite2D>("Monika2/Monika");
		_label  = GetNode<RichTextLabel>("Monika2/Monika/BubbleContainer/MessageLabel");
		_bubble   = GetNode<Control>("Monika2/Monika/BubbleContainer");
		_pointBtn = GetNode<TextureButton>("CanvasLayer/Control/MarginContainer/VBoxContainer/point");
		_chatBtn  = GetNode<TextureButton>("CanvasLayer/Control/MarginContainer/VBoxContainer/chat");
		ConnectButtonEffects(_pointBtn);
		ConnectButtonEffects(_chatBtn);
		_chatBtn.Pressed += ToggleChatPanel;

		_chatPanel = GetNode<Panel>("CanvasLayer/Control/ChatPanel");
		_chatInput = GetNode<LineEdit>("CanvasLayer/Control/ChatPanel/HBoxContainer/LineEdit");
		GetNode<Button>("CanvasLayer/Control/ChatPanel/HBoxContainer/SendButton").Pressed += OnSendPressed;
		GetNode<Button>("CanvasLayer/Control/ChatPanel/HBoxContainer/CloseButton").Pressed += CloseChatPanel;
		_chatInput.TextSubmitted += _ => OnSendPressed();
		_chatSend.ConnectToHost("127.0.0.1", 4243);

		var cs  = GetNode<CollisionShape2D>("Monika2/CollisionShape2D");

		// Hoist offset của children vào body, rồi reset children về gốc
		Vector2 startPos   = _monika.GlobalPosition; // (646, 360) theo tscn
		_monika.Position   = Vector2.Zero;
		cs.Position        = Vector2.Zero;
		_body.GlobalPosition = startPos;

		// Lấy half-size từ shape thực sự thay vì hardcode
		_spriteHalfSize = ((RectangleShape2D)cs.Shape).Size / 2;

		// Đặt nhân vật sát đáy màn hình ngay từ đầu, không cần rơi
		Vector2 screenSize = GetViewportRect().Size;
		_body.GlobalPosition = new Vector2(_body.GlobalPosition.X, screenSize.Y - _spriteHalfSize.Y);
		_velocityY = 0f;
		_isFalling = false;

		// Khởi tạo AudioStreamPlayer
		_audioPlayer = new AudioStreamPlayer();
		AddChild(_audioPlayer);
		_audioPlayer.Finished += OnAudioFinished;

		// Trạng thái mặc định khi khởi động
		_monika.Play("stand");
		_label.Text = "Chờ lệnh từ AI...";

		_bubbleBasePos = _bubble.Position;
		_monika.AnimationFinished += OnBounceAnimationFinished;
		GD.Print($"[Ready] Đang lắng nghe UDP cổng 4242. HalfSize={_spriteHalfSize}");
		StartVisionProcess();
	}

	public override void _ExitTree()
	{
		StopVisionProcess();
		_udp.Close();
		_chatSend.Close();
	}


	public override void _Process(double delta)
	{
		float d = (float)delta;
		Vector2 pos = _body.Position;

		Vector2 screenSize = GetViewportRect().Size;

		if (_climbPhase != ClimbPhase.None)
		{
			UpdateClimbMovement(ref pos, screenSize, d);
		}
		else
		{
			// Xử lý trọng lực trục Y
			_velocityY += _gravity * d;
			pos.Y += _velocityY * d;

			//Va chạm đáy màn hình
			if (pos.Y >= screenSize.Y - _spriteHalfSize.Y)
			{
				pos.Y = screenSize.Y - _spriteHalfSize.Y;
				_velocityY = 0f;
				_isFalling = false;
			}
			else
			{
				_isFalling = true;
			}

			//Va chạm trần
			if (pos.Y <= _spriteHalfSize.Y)
			{
				pos.Y = _spriteHalfSize.Y;
				_velocityY = 0f;
			}

			// Xử lý di chuyển khi đang walk
			if (_isWalking)
			{
				pos.X += _moveSpeed * _moveDir * d;

				// --- Di chuyển có mục tiêu vị trí (target_x) ---
				if (!float.IsNaN(_targetX))
				{
					bool reached = (_moveDir > 0f && pos.X >= _targetX) || (_moveDir < 0f && pos.X <= _targetX);
					if (reached)
					{
						pos.X = _targetX;
						_targetX = float.NaN;
						if (!string.IsNullOrEmpty(_nextAction))
						{
							string action = _nextAction;
							_nextAction = "";
							ApplyAnimationCommand(action, 0, "");
						}
						else
						{
							_isWalking = false;
							_currentAction = "stand";
							_monika.Scale = Vector2.One;
							_bubble.Scale = Vector2.One;
							_bubble.Position = _bubbleBasePos;
						}
					}
				}
				else
				{
					// Va chạm hai bên tường (chỉ khi không có target)
					if (pos.X >= screenSize.X - _spriteHalfSize.X)
					{
						pos.X = screenSize.X - _spriteHalfSize.X;
						if (!string.IsNullOrEmpty(_bounceAction)) {
							// Đổi chiều trước rồi phát bounce animation
							_moveDir = -1f;
							_currentAction = _bounceAction;
							_isWalking = false;
							_monika.Scale = Vector2.One;
							_bubble.Scale = Vector2.One;
							_bubble.Position = _bubbleBasePos;
							PlaySoundForAnimation(_bounceAction);
						} else if (!string.IsNullOrEmpty(_nextAction)) {
							string action = _nextAction;
							_nextAction = "";
							int nextDir = (action == "stand_walk") ? -1 : 0;
							ApplyAnimationCommand(action, nextDir, "");
						} else {
							_moveDir = -1f;
						}
					}
					else if (pos.X <= _spriteHalfSize.X)
					{
						pos.X = _spriteHalfSize.X;
						if (!string.IsNullOrEmpty(_bounceAction)) {
							_moveDir = 1f;
							_currentAction = _bounceAction;
							_isWalking = false;
							_monika.Scale = Vector2.One;
							_bubble.Scale = Vector2.One;
							_bubble.Position = _bubbleBasePos;
							PlaySoundForAnimation(_bounceAction);
						} else if (!string.IsNullOrEmpty(_nextAction)) {
							string action = _nextAction;
							_nextAction = "";
							int nextDir = (action == "stand_walk") ? 1 : 0;
							ApplyAnimationCommand(action, nextDir, "");
						} else {
							_moveDir = 1f;
						}
					}
				}
			}		}

		_body.Position = pos;
		UpdateAnimation();
		ClampBubbleToScreen();

		//Lắng nghe UDP
		if (_udp.GetAvailablePacketCount() > 0)
		{
			string raw = Encoding.UTF8.GetString(_udp.GetPacket());
			ParseAndApply(raw);
		}
	}

	private void ToggleChatPanel()
	{
		if (_chatPanel.Visible)
			CloseChatPanel();
		else
		{
			_chatPanel.Visible = true;
			_chatInput.GrabFocus();
			SendChatSignal("chat_start");
		}
	}

	private void CloseChatPanel()
	{
		_chatPanel.Visible = false;
		_chatInput.Text = "";
		SendChatSignal("chat_end");
	}

	private void OnSendPressed()
	{
		string msg = _chatInput.Text.Trim();
		if (string.IsNullOrEmpty(msg)) return;
		_chatInput.Text = "";
		_chatInput.GrabFocus();
		string payload = $"{{\"type\":\"chat\",\"message\":{JsonSerializer.Serialize(msg)}}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
		ApplyTypewriterEffect($"[Chủ nhân]: {msg}");
	}

	private void SendChatSignal(string type)
	{
		string payload = $"{{\"type\":\"{type}\"}}";
		_chatSend.PutPacket(Encoding.UTF8.GetBytes(payload));
	}

	private void ConnectButtonEffects(TextureButton btn)
	{
		btn.MouseEntered += () => TweenButtonColor(btn, new Color(1.4f, 1.4f, 0.8f)); // hover: vàng sáng
		btn.MouseExited  += () => TweenButtonColor(btn, Colors.White);
		btn.ButtonDown   += () => TweenButtonColor(btn, new Color(0.6f, 0.85f, 1.0f)); // nhấn: xanh dương
		btn.ButtonUp     += () => TweenButtonColor(btn, new Color(1.4f, 1.4f, 0.8f));
	}

	private void TweenButtonColor(TextureButton btn, Color target)
	{
		var tween = CreateTween();
		tween.TweenProperty(btn, "modulate", target, 0.12f);
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

		//thực thi hiệu ứng gõ chữ
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
		if (_climbPhase == ClimbPhase.Top)
		{
			if (_monika.Animation != "climb_top") _monika.Play("climb_top");
			_monika.Scale = new Vector2(1f, -1f);  // lộn ngược
			_bubble.Scale = new Vector2(1f, -1f);  // counter-scale để text không bị lộn
			_bubble.Position = _bubbleBasePos;
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
				float flipX = _moveDir == 1f ? -1f : 1f;
				_monika.Scale = new Vector2(flipX, 1f);
				_bubble.Scale = new Vector2(flipX, 1f);
				// Bù offset ngược lại để bubble giữ nguyên vị trí thực trên màn hình khi sprite lật
				_bubble.Position = new Vector2(_bubbleBasePos.X * flipX, _bubbleBasePos.Y);
			}
		}
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

	private void ParseAndApply(string raw)
    {
        string text = raw;
        string animation = "stand";
		int direction = 0;
		string nextAnimation = "";
		string bounceAction = "";
		// Reset targets trước khi xử lý lệnh mới
		_targetX = float.NaN;
		_bounceAction = ""; 

        try
        {
            string cleaned = raw.Trim();
            if (cleaned.StartsWith("```"))
            {
                int start = cleaned.IndexOf('\n') + 1;
                int end = cleaned.LastIndexOf("```");
                if (start > 0 && end > start)
                {
                    cleaned = cleaned.Substring(start, end - start).Trim();
                }
            }

            using var doc = JsonDocument.Parse(cleaned);
            var root = doc.RootElement;
            if (root.TryGetProperty("text", out var t)) text = t.GetString() ?? raw;
            if (root.TryGetProperty("animation", out var a)) animation = a.GetString() ?? "stand";
			if (root.TryGetProperty("direction", out var d) && d.ValueKind == JsonValueKind.Number) 
            {
                direction = d.GetInt32(); // 1 = phải, -1 = trái
            }
			if (root.TryGetProperty("next_animation", out var na)) nextAnimation = na.GetString() ?? "";
			if (root.TryGetProperty("bounce_action", out var ba)) bounceAction = ba.GetString() ?? "";
            
            // CHỈ XỬ LÝ TARGET_X KHI NÓ >= 0 ---
            if (root.TryGetProperty("target_x", out var tx) && tx.ValueKind == JsonValueKind.Number)
            {
                float rawTx = tx.GetSingle();
                
                // Nếu AI truyền -1 (không có đích), ta bỏ qua hoàn toàn khối lệnh này
                if (rawTx >= 0f) 
                {
                    float frac = Mathf.Clamp(rawTx, 0f, 1f); // đảm bảo target_x là tỉ lệ phần trăm giữa 0 và 1
                    Vector2 sz = GetViewportRect().Size; // kích thước màn hình
                    
                    float absX = Mathf.Clamp(frac * sz.X, _spriteHalfSize.X, sz.X - _spriteHalfSize.X);
                    _targetX = absX;
                    
                    direction = (_targetX > _body.Position.X) ? 1 : -1;
                    animation = "stand_walk"; // Chỉ ép thành đi bộ khi thực sự có target_x hợp lệ
                    GD.Print($"[Physics] target_x={frac:F2} → absX={absX:F0}, dir={direction}");
                }
            }
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[Parse] Khung dữ liệu bị hỏng: {ex.Message}");
            text = "Lỗi đường truyền tín hiệu.";
            animation = "stand";
        }

		ApplyTypewriterEffect(text);
		_bounceAction = bounceAction; // set trước ApplyAnimationCommand để không bị ghi đè
        ApplyAnimationCommand(animation, direction, nextAnimation);
    }

	private void ApplyAnimationCommand(string animation, int direction, string nextAnimation)
	{
		_nextAction = nextAnimation;
		// Chuẩn hoá alias trước (walk → stand_walk, v.v.)
		if (_animAliases.TryGetValue(animation, out var mapped))
		{
			GD.Print($"[Anim] Alias '{animation}' → '{mapped}'");
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
            GD.Print($"[Physics] Đổi hướng di chuyển thành: {direction}");
        }

		// Ngắt climb đang chạy nếu có
		if (_climbPhase != ClimbPhase.None)
		{
			_climbPhase = ClimbPhase.None;
			_monika.Scale = Vector2.One;
			_bubble.Scale = Vector2.One;
			_velocityY = 0f;
			_isFalling = false;
		}

		_currentAction = animation;
		_isWalking = (animation == "stand_walk");

		if (!_isWalking)
		{
			_monika.Scale = new Vector2(1f, 1f);
			_bubble.Scale = new Vector2(1f, 1f);
			_bubble.Position = _bubbleBasePos;
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
				float dx2 = _climbDownWallX - pos.X;
				pos.X += Mathf.Sign(dx2) * _moveSpeed * d;
				if (Mathf.Abs(dx2) < _moveSpeed * d + 2f)
				{
					pos.X = _climbDownWallX;
					_climbPhase = ClimbPhase.Down;
				}
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
					_monika.Scale  = Vector2.One;
					_bubble.Scale  = Vector2.One;
				}
				break;
		}
	}

	private void OnBounceAnimationFinished()
	{
		// Sau khi bounce animation kết thúc → tiếp tục đi theo hướng đã flip
		if (!string.IsNullOrEmpty(_bounceAction) && _currentAction == _bounceAction && !_isWalking)
		{
			_currentAction = "stand_walk";
			_isWalking = true;
			PlaySoundForAnimation("stand_walk");
		}
	}

	private void OnAudioFinished()
	{
		if (_loopingSoundAnims.Contains(_currentAction))
			PlaySoundForAnimation(_currentAction);
	}

	private void PlaySoundForAnimation(string animation)
	{
		if (!_soundMap.TryGetValue(animation, out var sounds)) return;
		string path = sounds[_rng.Next(sounds.Length)];
		var stream = GD.Load<AudioStream>(path);
		if (stream == null)
		{
			GD.PrintErr($"[Sound] Không tải được: {path}");
			return;
		}
		_audioPlayer.Stream = stream;
		_audioPlayer.Play();
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
		if (_visionProcess != null && !_visionProcess.HasExited)
		{
			GD.Print($"[Vision] Đã chạy sẵn, PID={_visionProcess.Id}");
			return;
		}

		string projectRoot = ProjectSettings.GlobalizePath("res://");
		string visionScriptFullPath = Path.Combine(projectRoot, VisionScriptPath.Replace('/', Path.DirectorySeparatorChar));

		if (!File.Exists(visionScriptFullPath))
		{
			GD.PrintErr($"[Vision] Không tìm thấy script: {visionScriptFullPath}");
			return;
		}

		try
		{
			var startInfo = new ProcessStartInfo
			{
				FileName = PythonExecutable,
				Arguments = $"\"{visionScriptFullPath}\"",
				WorkingDirectory = projectRoot,
				UseShellExecute = false,
				CreateNoWindow = true,
				RedirectStandardOutput = true,
				RedirectStandardError = true,
				StandardOutputEncoding = Encoding.UTF8,
				StandardErrorEncoding = Encoding.UTF8,
			};
			startInfo.Environment["PYTHONUTF8"] = "1";
			startInfo.Environment["PYTHONIOENCODING"] = "utf-8";
			startInfo.Environment["PYTHONUNBUFFERED"] = "1";

			var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
			process.OutputDataReceived += (_, e) =>
			{
				if (!string.IsNullOrWhiteSpace(e.Data))
				{
					GD.Print($"[vision.py] {e.Data}");
				}
			};
			process.ErrorDataReceived += (_, e) =>
			{
				if (!string.IsNullOrWhiteSpace(e.Data))
				{
					GD.PrintErr($"[vision.py][ERR] {e.Data}");
				}
			};
			process.Exited += (_, _) =>
			{
				GD.Print($"[Vision] vision.py đã thoát (PID={process.Id}, code={process.ExitCode}).");
			};

			bool started = process.Start();
			if (!started)
			{
				GD.PrintErr("[Vision] Không thể khởi chạy vision.py.");
				return;
			}

			_visionProcess = process;
			process.BeginOutputReadLine();
			process.BeginErrorReadLine();
			GD.Print($"[Vision] Đã khởi chạy vision.py PID={process.Id}");
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Vision] Lỗi khi chạy vision.py: {ex.Message}");
		}
	}

	private void StopVisionProcess()
	{
		if (_visionProcess == null)
		{
			return;
		}

		try
		{
			if (!_visionProcess.HasExited)
			{
				GD.Print($"[Vision] Đang dừng vision.py PID={_visionProcess.Id}...");
				_visionProcess.Kill(true);
				_visionProcess.WaitForExit(3000);
			}
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Vision] Không thể dừng vision.py sạch sẽ: {ex.Message}");
		}
		finally
		{
			_visionProcess.Dispose();
			_visionProcess = null;
		}
	}
}