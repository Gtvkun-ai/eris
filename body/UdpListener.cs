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

	private Tween _textTween;
	private AudioStreamPlayer _audioPlayer;
	private readonly Random _rng = new Random();
	private Control _bubble;

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
		_bubble = GetNode<Control>("Monika2/Monika/BubbleContainer");
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

		GD.Print($"[Ready] Đang lắng nghe UDP cổng 4242. HalfSize={_spriteHalfSize}");
		StartVisionProcess();
	}

	public override void _ExitTree()
	{
		StopVisionProcess();
		_udp.Close();
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
			}

			// Va chạm hai bên tường
			if (pos.X >= screenSize.X - _spriteHalfSize.X)
			{
				pos.X = screenSize.X - _spriteHalfSize.X;
				_moveDir = -1f;
			}
			else if (pos.X <= _spriteHalfSize.X)
			{
				pos.X = _spriteHalfSize.X;
				_moveDir = 1f;
			}
		}

		_body.Position = pos;
		UpdateAnimation();

		//Lắng nghe UDP
		if (_udp.GetAvailablePacketCount() > 0)
		{
			string raw = Encoding.UTF8.GetString(_udp.GetPacket());
			ParseAndApply(raw);
		}
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
			return;
		}
		if (_climbPhase == ClimbPhase.Up || _climbPhase == ClimbPhase.Down)
		{
			if (_monika.Animation != "climb") _monika.Play("climb");
			float wallX = _climbPhase == ClimbPhase.Up ? _climbUpWallX : _climbDownWallX;
			float scaleX = wallX < GetViewportRect().Size.X / 2f ? 1f : -1f;
			_monika.Scale = new Vector2(scaleX, 1f);
			_bubble.Scale = new Vector2(scaleX, 1f);
			return;
		}
		if (_climbPhase == ClimbPhase.Top)
		{
			if (_monika.Animation != "climb_top") _monika.Play("climb_top");
			_monika.Scale = new Vector2(1f, -1f);  // lộn ngược
			_bubble.Scale = new Vector2(1f, -1f);  // counter-scale để text không bị lộn
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
			}
		}
	}


	private void ParseAndApply(string raw)
    {
        string text = raw;
        string animation = "stand";

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
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[Parse] Khung dữ liệu bị hỏng: {ex.Message}");
            text = "Lỗi đường truyền tín hiệu.";
            animation = "stand";
        }

		ApplyTypewriterEffect(text);
        ApplyAnimationCommand(animation);
    }

	private void ApplyAnimationCommand(string animation)
	{
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