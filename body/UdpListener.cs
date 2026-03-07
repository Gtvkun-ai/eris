using Godot;
using System;
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

	// Giới hạn màn hình: dùng screenSize - _spriteHalfSize, không hardcode

	public override void _Ready()
	{
		_udp.Bind(_port);
		_body   = GetNode<CharacterBody2D>("Monika2");
		_monika = GetNode<AnimatedSprite2D>("Monika2/Monika");
		_label  = GetNode<RichTextLabel>("Monika2/Monika/MessageLabel");
		var cs  = GetNode<CollisionShape2D>("Monika2/CollisionShape2D");

		// Hoist offset của children vào body, rồi reset children về gốc
		Vector2 startPos   = _monika.GlobalPosition; // (646, 360) theo tscn
		_monika.Position   = Vector2.Zero;
		cs.Position        = Vector2.Zero;
		_body.GlobalPosition = startPos;

		// Lấy half-size từ shape thực sự thay vì hardcode
		_spriteHalfSize = ((RectangleShape2D)cs.Shape).Size / 2;

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

		// Xử lý trọng lực trục Y
		_velocityY += _gravity * d; // Tăng tốc độ rơi theo thời gian
		pos.Y += _velocityY * d; // Cập nhật vị trí theo tốc độ

		//Va chạm đáy màn hình
		if(pos.Y >= screenSize.Y - _spriteHalfSize.Y)
		{
			pos.Y = screenSize.Y - _spriteHalfSize.Y; // Đặt lại vị trí trên mặt đất
			_velocityY = 0f; // Dừng rơi
			_isFalling = false;
		}
		else
		{
			_isFalling = true;
		}

		//Va chạm trần
		if(pos.Y <= _spriteHalfSize.Y){
			pos.Y = _spriteHalfSize.Y; // Đặt lại vị trí dưới trần
			_velocityY = 0f; // Triệt tiêu lực bốc lên
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
            _moveDir = -1f; // Đảo chiều trái
        }
        else if (pos.X <= _spriteHalfSize.X)
        {
            pos.X = _spriteHalfSize.X;
            _moveDir = 1f;  // Đảo chiều phải
        }

			_body.Position = pos;
			UpdateAnimation();

			//Lắng nghe UDP
			if (_udp.GetAvailablePacketCount() > 0)
        	{
            	string raw = Encoding.UTF8.GetString(_udp.GetPacket()); // Đọc gói UDP
            	ParseAndApply(raw);
        	}

		}

	private void UpdateAnimation(){
		if(_isFalling){
			if(_monika.Animation != "air"){
				_monika.Play("air");
				GD.Print("[Anim] Chuyển sang animation: air (rơi tự do)");
			}
		}
		else{
			if (_monika.Animation != _currentAction)
            {
                _monika.Play(_currentAction);
            }
			if(_isWalking){
				_monika.Scale = new Vector2(_moveDir == 1f ? 1f : -1f, 1f); // Lật sprite theo hướng đi
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

        _label.Text = text;
        ApplyAnimationCommand(animation);
    }

	private void ApplyAnimationCommand(string animation){
		_currentAction = animation;
		 _isWalking = (animation == "stand_walk");

		 if(!_isWalking){
			_monika.Scale = new Vector2(1f, 1f); // Đảm bảo không bị lật khi không đi bộ
		 }
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