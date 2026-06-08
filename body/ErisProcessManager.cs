using Godot;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

public sealed class ErisServiceConfig
{
	public string PythonExecutable { get; init; } = "python";
	public string VisionScriptPath { get; init; } = "src/vision.py";
	public bool EnableRemoteCognitionApi { get; init; } = true;
	public string DefaultRemoteApiKey { get; init; } = "";
	public string RemoteApiProvider { get; init; } = "gemini";
	public string RemoteApiBaseUrl { get; init; } = "";
	public string RemoteApiModelName { get; init; } = "";
}

public sealed class ErisProcessManager
{
	private Process _visionProcess;
	private bool _visionTracebackActive;
	private readonly Action _onStatusChanged;

	public ErisProcessManager(Action onStatusChanged = null)
	{
		_onStatusChanged = onStatusChanged ?? (() => { });
	}

	public void StartVision(ErisServiceConfig config)
	{
		if (_visionProcess != null && !_visionProcess.HasExited)
		{
			GD.Print($"[Vision] Da chay san, PID={_visionProcess.Id}");
			return;
		}

		string projectRoot = GetProjectRoot();
		string visionScriptFullPath = ResolveProjectPath(config.VisionScriptPath);
		if (!File.Exists(visionScriptFullPath))
		{
			GD.PrintErr($"[Vision] Khong tim thay script: {visionScriptFullPath}");
			return;
		}

		try
		{
			var startInfo = new ProcessStartInfo
			{
				FileName = config.PythonExecutable,
				Arguments = $"\"{visionScriptFullPath}\"",
				WorkingDirectory = projectRoot,
				UseShellExecute = false,
				CreateNoWindow = true,
				RedirectStandardOutput = true,
				RedirectStandardError = true,
				StandardOutputEncoding = Encoding.UTF8,
				StandardErrorEncoding = Encoding.UTF8,
			};
			PopulateVisionEnvironment(startInfo, config);

			var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
			process.OutputDataReceived += (_, e) =>
			{
				if (!string.IsNullOrWhiteSpace(e.Data) && ShouldLogVisionOutput(e.Data))
					GD.Print($"[vision.py] {e.Data.Trim()}");
			};
			process.ErrorDataReceived += (_, e) => HandleVisionStderr(e.Data);
			process.Exited += (_, _) =>
			{
				GD.Print($"[Vision] vision.py da thoat (PID={process.Id}, code={process.ExitCode}).");
				_onStatusChanged();
			};

			if (!process.Start())
			{
				GD.PrintErr("[Vision] Khong the khoi chay vision.py.");
				return;
			}

			_visionProcess = process;
			process.BeginOutputReadLine();
			process.BeginErrorReadLine();
			GD.Print($"[Vision] Da khoi chay vision.py PID={process.Id}");
			_onStatusChanged();
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[Vision] Loi khi chay vision.py: {ex.Message}");
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

	public void StopAll()
	{
		StopVision();
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
		startInfo.Environment["ERIS_REMOTE_API_ENABLED"] = config.EnableRemoteCognitionApi ? "1" : "0";
		startInfo.Environment["ERIS_REMOTE_PROVIDER"] = config.RemoteApiProvider;
		startInfo.Environment["ERIS_REMOTE_BASE_URL"] = config.RemoteApiBaseUrl;
		startInfo.Environment["ERIS_REMOTE_MODEL"] = config.RemoteApiModelName;
		startInfo.Environment["ERIS_LOCAL_STYLE_REWRITE_ENABLED"] = "0";
		startInfo.Environment["ERIS_LOCAL_VISION_FACTS"] = "0";
		if (!string.IsNullOrWhiteSpace(config.DefaultRemoteApiKey))
		{
			startInfo.Environment["ERIS_REMOTE_API_KEY"] = config.DefaultRemoteApiKey;
			startInfo.Environment["GEMINI_API_KEY"] = config.DefaultRemoteApiKey;
		}
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
			line.Contains("No connection could be made", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("JSON khong hop le", StringComparison.OrdinalIgnoreCase);

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
				GD.Print($"[{label}] Dang dung {processName} PID={process.Id}...");
				process.Kill(true);
				process.WaitForExit(3000);
			}
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[{label}] Khong the dung {processName} sach se: {ex.Message}");
		}
		finally
		{
			process.Dispose();
			process = null;
			_onStatusChanged();
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
			trimmed.Contains("[Loi", StringComparison.OrdinalIgnoreCase) ||
			trimmed.Contains("[Error]", StringComparison.OrdinalIgnoreCase);
	}

	private static bool ShouldLogVisionStderr(string line)
	{
		if (string.IsNullOrWhiteSpace(line))
			return false;
		return
			line.Contains("Traceback", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("Exception", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("No connection could be made", StringComparison.OrdinalIgnoreCase) ||
			line.Contains("JSON khong hop le", StringComparison.OrdinalIgnoreCase);
	}
}
