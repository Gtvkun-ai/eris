using Godot;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

public sealed class ErisServiceConfig
{
	//đây là “bảng điều khiển”. Muốn đổi model, đổi port, bật Gemini, bật local vision thì chỉnh ở đây.
	public string PythonExecutable { get; init; } = "python";
	public string VisionScriptPath { get; init; } = "src/vision.py";
	public string LlamaServerPath { get; init; } = "";
	public string ModelPath { get; init; } = "src/model.gguf";
	public string MmprojPath { get; init; } = "src/mmproj-F16.gguf";
	public bool EnableLocalVisionInput { get; init; }
	public int LlamaServerPort { get; init; } = 8080;
	public string LlamaServerNgl { get; init; } = "all";
	public int LlamaServerCtx { get; init; } = 8192;
	public bool LlamaServerFlashAttn { get; init; } = true;
	public string LlamaServerExtraArgs { get; init; } = "";
	public bool EnableRemoteCognitionApi { get; init; }
	public bool EnableLocalStyleRewrite { get; init; } = false;
	public string DefaultRemoteApiKey { get; init; } = "";
	public string RemoteApiProvider { get; init; } = "gemini";
	public string RemoteApiBaseUrl { get; init; } = "";
	public string RemoteApiModelName { get; init; } = "";
}

public sealed class ErisProcessManager
{	
	private Process _visionProcess; //Đây là handle tới process Python.
	private Process _llamaServerProcess;
	private bool _visionTracebackActive; //Đây là state machine mini.
	private readonly Action _onStatusChanged;

	public ErisProcessManager(Action onStatusChanged = null)
	{
		_onStatusChanged = onStatusChanged ?? (() => { });
	}

	//Đây là flow boot vision.py.
	public void StartVision(ErisServiceConfig config)
	{	
		//Nếu đang chạy:khỏi boot lại, tránh duplicate process
			if (_visionProcess != null && !_visionProcess.HasExited)
		{
			GD.Print($"[Vision] Đã chạy sẵn, PID={_visionProcess.Id}");
			return;
		}

		string projectRoot = GetProjectRoot();
		//absolute path
		//Godot dùng virtual path nên phải convert.
		string visionScriptFullPath = ResolveProjectPath(config.VisionScriptPath);
		if (!File.Exists(visionScriptFullPath))
		{
			GD.PrintErr($"[Vision] Không tìm thấy script: {visionScriptFullPath}");
			return;
		}

		try
		{
			// nếu local rewrite ON và hoặc local vision ON thì cần llama sever
			bool needsLocalLlmServer = config.EnableLocalStyleRewrite || config.EnableLocalVisionInput;
			// nếu server chưa reachable và boot fail
			if (needsLocalLlmServer && !IsLlamaServerReachable(config) && !StartLlamaServer(config))
			{
				//=> hủy boot vision.py.
				GD.PrintErr("[Vision] Không thể khởi động vision.py vì llama-server chưa sẵn sàng.");
				return;
			}

			//Đây là config spawn process.
			var startInfo = new ProcessStartInfo
			{
				FileName = config.PythonExecutable,
				Arguments = $"\"{visionScriptFullPath}\"", //python "src/vision.py"
				WorkingDirectory = projectRoot,
				UseShellExecute = false,
				CreateNoWindow = true,
				RedirectStandardOutput = true, //Cho phép C# đọc stdout Python.
				RedirectStandardError = true,
				StandardOutputEncoding = Encoding.UTF8,
				StandardErrorEncoding = Encoding.UTF8,
			};
			PopulateVisionEnvironment(startInfo, config); //Nó inject ENV VAR.
			/*Đây là bridge config giữa:
				Godot
				Python */

			var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
			//event async đọc stdout realtime.
			process.OutputDataReceived += (_, e) =>
			{
				if (!string.IsNullOrWhiteSpace(e.Data) && ShouldLogVisionOutput(e.Data))
					GD.Print($"[vision.py] {e.Data.Trim()}");
			};
			//stderr handler đặc biệt để detect traceback và lỗi nghiêm trọng.
			process.ErrorDataReceived += (_, e) => HandleVisionStderr(e.Data);
			process.Exited += (_, _) =>
			{
				GD.Print($"[Vision] vision.py đã thoát (PID={process.Id}, code={process.ExitCode}).");
				_onStatusChanged();
			};

			if (!process.Start())
			{
				GD.PrintErr("[Vision] Không thể khởi chạy vision.py.");
				return;
			}

			_visionProcess = process;
			process.BeginOutputReadLine();
			process.BeginErrorReadLine();
			GD.Print($"[Vision] Đã khởi chạy vision.py PID={process.Id}");
			_onStatusChanged();
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Vision] Lỗi khi chạy vision.py: {ex.Message}");
		}
	}

	public void StopVision()
	{
		StopProcess(ref _visionProcess, "Vision", "vision.py");
	}

	public void ToggleVision(ErisServiceConfig config)
	{
		if (_visionProcess != null && !_visionProcess.HasExited)
			StopVision();
		else
			StartVision(config);
	}

	public bool StartLlamaServer(ErisServiceConfig config)
	{
		if ((_llamaServerProcess != null && !_llamaServerProcess.HasExited) || IsLlamaServerReachable(config))
		{
			GD.Print($"[LLM] llama-server đã sẵn sàng trên cổng {config.LlamaServerPort}.");
			_onStatusChanged();
			return true;
		}

		string serverPath = ResolveProjectPath(config.LlamaServerPath);
		string modelPath = ResolveProjectPath(config.ModelPath);
		if (!File.Exists(serverPath))
		{
			GD.PrintErr($"[LLM] Không tìm thấy llama-server.exe: {serverPath}");
			return false;
		}
		if (!File.Exists(modelPath))
		{
			GD.PrintErr($"[LLM] Không tìm thấy model.gguf: {modelPath}");
			return false;
		}

		try
		{
			var startInfo = new ProcessStartInfo
			{
				FileName = serverPath,
				Arguments = BuildLlamaArguments(config, modelPath), //build CLI args
				//Ví dụ:
				//-m "model.gguf" Offload toàn bộ layer lên GPU.
				//-c 8192 Bật Flash Attention. Tăng tốc attention kernel.
				//-ngl all Attach vision projector. Dùng cho multimodal.
				WorkingDirectory = Path.GetDirectoryName(serverPath) ?? GetProjectRoot(),
				UseShellExecute = false,
				CreateNoWindow = true,
				RedirectStandardOutput = true,
				RedirectStandardError = true,
				StandardOutputEncoding = Encoding.UTF8,
				StandardErrorEncoding = Encoding.UTF8,
			};

			var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
			process.OutputDataReceived += (_, e) =>
			{
				if (!string.IsNullOrWhiteSpace(e.Data) && ShouldLogLlamaOutput(e.Data))
					GD.Print($"[llama-server] {e.Data.Trim()}");
			};
			process.ErrorDataReceived += (_, e) =>
			{
				if (!string.IsNullOrWhiteSpace(e.Data) && ShouldLogLlamaOutput(e.Data))
					GD.Print($"[llama-server][stderr] {e.Data.Trim()}");
			};
			process.Exited += (_, _) =>
			{
				GD.Print($"[LLM] llama-server đã thoát (PID={process.Id}, code={process.ExitCode}).");
				_onStatusChanged();
			};

			if (!process.Start())
			{
				GD.PrintErr("[LLM] Không thể khởi động llama-server.");
				return false;
			}

			_llamaServerProcess = process;
			process.BeginOutputReadLine();
			process.BeginErrorReadLine();
			GD.Print($"[LLM] Đã khởi chạy llama-server PID={process.Id}");
			_onStatusChanged();
			return true;
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[LLM] Lỗi khi chạy llama-server: {ex.Message}");
			return false;
		}
	}

	public void StopLlamaServer()
	{
		StopProcess(ref _llamaServerProcess, "LLM", "llama-server");
	}

	public void ToggleLlamaServer(ErisServiceConfig config)
	{
		if ((_llamaServerProcess != null && !_llamaServerProcess.HasExited) || IsLlamaServerReachable(config))
			StopLlamaServer();
		else
			StartLlamaServer(config);
	}

	public void StopAll()
	{
		StopVision();
		StopLlamaServer();
	}

	private void PopulateVisionEnvironment(ProcessStartInfo startInfo, ErisServiceConfig config)
	{
		foreach (var secret in LoadProjectSecretsEnvironment())
		{
			if (!string.IsNullOrWhiteSpace(secret.Key) && !string.IsNullOrWhiteSpace(secret.Value))
				startInfo.Environment[secret.Key] = secret.Value;
		}

		startInfo.Environment["PYTHONUTF8"] = "1";
		startInfo.Environment["PYTHONIOENCODING"] = "utf-8";
		startInfo.Environment["PYTHONUNBUFFERED"] = "1";
		startInfo.Environment["LLAMA_SERVER_EXE"] = ResolveProjectPath(config.LlamaServerPath);
		startInfo.Environment["LLAMA_SERVER_URL"] = $"http://127.0.0.1:{config.LlamaServerPort}/v1";
		startInfo.Environment["LLAMA_SERVER_HOST"] = "127.0.0.1";
		startInfo.Environment["LLAMA_SERVER_PORT"] = config.LlamaServerPort.ToString();
		startInfo.Environment["LLAMA_SERVER_NGL"] = config.LlamaServerNgl;
		startInfo.Environment["LLAMA_SERVER_FLASH_ATTN"] = config.LlamaServerFlashAttn ? "on" : "off";
		startInfo.Environment["LLAMA_SERVER_EXTRA_ARGS"] = config.LlamaServerExtraArgs;
		startInfo.Environment["LLAMA_SERVER_MMPROJ"] = config.EnableLocalVisionInput ? ResolveProjectPath(config.MmprojPath) : "";
		startInfo.Environment["GGUF_MODEL_PATH"] = ResolveProjectPath(config.ModelPath);
		startInfo.Environment["ERIS_N_CTX"] = config.LlamaServerCtx.ToString();
		startInfo.Environment["ERIS_REMOTE_API_ENABLED"] = config.EnableRemoteCognitionApi ? "1" : "0";
		startInfo.Environment["ERIS_REMOTE_PROVIDER"] = config.RemoteApiProvider;
		startInfo.Environment["ERIS_REMOTE_BASE_URL"] = config.RemoteApiBaseUrl;
		startInfo.Environment["ERIS_REMOTE_MODEL"] = config.RemoteApiModelName;
		if (!string.IsNullOrWhiteSpace(config.DefaultRemoteApiKey))
		{
			startInfo.Environment["ERIS_REMOTE_API_KEY"] = config.DefaultRemoteApiKey;
			startInfo.Environment["GEMINI_API_KEY"] = config.DefaultRemoteApiKey;
		}
		startInfo.Environment["ERIS_LOCAL_STYLE_REWRITE_ENABLED"] = config.EnableLocalStyleRewrite ? "1" : "0";
		startInfo.Environment["ERIS_LOCAL_VISION_FACTS"] = config.EnableLocalVisionInput ? "1" : "0";
	}

	private Dictionary<string, string> LoadProjectSecretsEnvironment()
	{
		var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
		string secretsPath = Path.Combine(GetProjectRoot(), "config", "secrets.json");
		if (!File.Exists(secretsPath))
			return values;

		try
		{
			using JsonDocument document = JsonDocument.Parse(File.ReadAllText(secretsPath));
			JsonElement root = document.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return values;

			AddSecretsFromObject(root, values);
			foreach (string sectionName in new[] { "api_keys", "env", "secrets" })
			{
				if (root.TryGetProperty(sectionName, out JsonElement section))
					AddSecretsFromObject(section, values);
			}
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Secrets] Khong doc duoc config/secrets.json: {ex.Message}");
		}

		return values;
	}

	private void AddSecretsFromObject(JsonElement source, Dictionary<string, string> values)
	{
		if (source.ValueKind != JsonValueKind.Object)
			return;

		foreach (JsonProperty property in source.EnumerateObject())
		{
			if (property.Value.ValueKind != JsonValueKind.String)
				continue;
			string value = property.Value.GetString() ?? "";
			if (!string.IsNullOrWhiteSpace(property.Name) && !string.IsNullOrWhiteSpace(value))
				values[property.Name] = value.Trim();
		}
	}

	private string BuildLlamaArguments(ErisServiceConfig config, string modelPath)
	{
		string flashAttnArgs = config.LlamaServerFlashAttn ? " --flash-attn on" : "";
		string mmprojPath = ResolveProjectPath(config.MmprojPath);
		bool extraArgsHasMmproj = !string.IsNullOrWhiteSpace(config.LlamaServerExtraArgs) &&
			config.LlamaServerExtraArgs.Contains("--mmproj", StringComparison.OrdinalIgnoreCase);
		bool extraArgsHasMmprojOffload = !string.IsNullOrWhiteSpace(config.LlamaServerExtraArgs) &&
			config.LlamaServerExtraArgs.Contains("mmproj-offload", StringComparison.OrdinalIgnoreCase);
		bool extraArgsHasCacheRam = !string.IsNullOrWhiteSpace(config.LlamaServerExtraArgs) &&
			config.LlamaServerExtraArgs.Contains("--cache-ram", StringComparison.OrdinalIgnoreCase);
		string mmprojArgs = "";
		if (config.EnableLocalVisionInput && !extraArgsHasMmproj)
		{
			if (File.Exists(mmprojPath))
			{
				string mmprojOffloadArgs = extraArgsHasMmprojOffload ? "" : " --mmproj-offload";
				mmprojArgs = $" --mmproj \"{mmprojPath}\"{mmprojOffloadArgs}";
			}
			else
				GD.PrintErr($"[LLM] Vision input đang bật nhưng không tìm thấy mmproj: {mmprojPath}");
		}
		string cacheRamArgs = extraArgsHasCacheRam ? "" : " --cache-ram 1024";
		string extraArgs = string.IsNullOrWhiteSpace(config.LlamaServerExtraArgs) ? "" : $" {config.LlamaServerExtraArgs}";
		return $"-m \"{modelPath}\"{mmprojArgs} -c {config.LlamaServerCtx} -ngl {config.LlamaServerNgl} --host 127.0.0.1 --port {config.LlamaServerPort} --no-warmup --jinja --reasoning-format deepseek{cacheRamArgs}{flashAttnArgs}{extraArgs}";
	}

	private void HandleVisionStderr(string data)
	{
		if (string.IsNullOrWhiteSpace(data))
			return;
		string rawLine = data;
		string line = rawLine.Trim();
		if (_visionTracebackActive)
		{
			if (string.IsNullOrWhiteSpace(line))
			{
				_visionTracebackActive = false;
			}
			else
			{
				GD.PrintErr($"[vision.py][ERR] {rawLine}");
				bool tracebackTail =
					rawLine.StartsWith(" ", StringComparison.Ordinal) ||
					rawLine.StartsWith("\t", StringComparison.Ordinal) ||
					line.StartsWith("File ", StringComparison.OrdinalIgnoreCase) ||
					line.StartsWith("During handling of the above exception", StringComparison.OrdinalIgnoreCase) ||
					line.Contains("Error:", StringComparison.OrdinalIgnoreCase) ||
					line.Contains("Exception:", StringComparison.OrdinalIgnoreCase);
				if (!tracebackTail)
					_visionTracebackActive = false;
				return;
			}
		}

		bool looksFatal =
			line.Contains("Traceback", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("Exception", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("error loading model", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("failed to load model", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("No connection could be made", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("JSON không hợp lệ", StringComparison.OrdinalIgnoreCase);

		if (looksFatal)
		{
			if (line.Contains("Traceback", StringComparison.OrdinalIgnoreCase))
				_visionTracebackActive = true;
			GD.PrintErr($"[vision.py][ERR] {rawLine}");
		}
		else if (ShouldLogVisionStderr(line))
			GD.Print($"[vision.py][stderr] {line}");
	}

	private void StopProcess(ref Process process, string label, string processName)
	{
		if (process == null)
		{
			_onStatusChanged();
			return;
		}
		try
		{
			if (!process.HasExited)
			{
				GD.Print($"[{label}] Đang dừng {processName} PID={process.Id}...");
				process.Kill(true);
				process.WaitForExit(3000);
			}
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[{label}] Không thể dừng {processName} sạch sẽ: {ex.Message}");
		}
		finally
		{
			process.Dispose();
			process = null;
			_onStatusChanged();
		}
	}

	private bool IsLlamaServerReachable(ErisServiceConfig config)
	{
		try
		{
			using var client = new TcpClient();
			var result = client.BeginConnect("127.0.0.1", config.LlamaServerPort, null, null);
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

	private static string GetProjectRoot()
	{
		return ProjectSettings.GlobalizePath("res://");
	}

	private static string ResolveProjectPath(string path)
	{
		return Path.Combine(GetProjectRoot(), (path ?? "").Replace('/', Path.DirectorySeparatorChar));
	}

	private static bool ShouldLogVisionOutput(string line)
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
			trimmed.Contains("[chat raw]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[directive raw]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[raw]", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Lỗi", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Error]", StringComparison.OrdinalIgnoreCase);
	}

	private static bool ShouldLogVisionStderr(string line)
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

	private static bool ShouldLogLlamaOutput(string line)
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
}
