using Godot;
using System;
using System.Collections.Generic;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	// Contract panel chính cho runtime mới. emotion_debug vẫn được giữ như lớp
	// compatibility, nhưng khí sắc sống và trạng thái sân khấu phải đi từ
	// eris.stage v2; nếu không panel chỉ là ảnh chụp cũ mặc áo mới.
	private sealed class RuntimePresenceState
	{
		public readonly Dictionary<string, float> Affect = new(StringComparer.Ordinal);
		public string Source = "";
		public string StageSource = "";
		public string Stage = "idle";
		public string Emotion = "";
		public string Motion = "";
		public string TurnId = "";
		public string LastEventType = "";
		public float ThoughtPressure;
		public float Confidence;
		public bool DiaryUpdated;
		public bool Speaking;
		public bool Thinking;
		public ulong LastPacketAtMs;
		public ulong LastAffectAtMs;
	}

	private readonly RuntimePresenceState _runtimePresence = new();
	private ulong _runtimePresenceLastUiRefreshMs;

	private void TryCaptureRuntimePresence(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return;
		try
		{
			using JsonDocument doc = JsonDocument.Parse(raw);
			JsonElement root = doc.RootElement;
			if (root.ValueKind != JsonValueKind.Object)
				return;

			string protocol = RuntimePresenceString(root, "protocol");
			string eventType = RuntimePresenceString(root, "type").Trim().ToLowerInvariant();
			bool stageProtocol = string.Equals(protocol, "eris.stage", StringComparison.OrdinalIgnoreCase);
			if (!stageProtocol && !RuntimePresenceEventTypes.Contains(eventType))
				return;

			_runtimePresence.LastPacketAtMs = Time.GetTicksMsec();
			_runtimePresence.LastEventType = eventType;
			string turnId = RuntimePresenceString(root, "turn_id");
			if (!string.IsNullOrWhiteSpace(turnId))
				_runtimePresence.TurnId = turnId;

			JsonElement data = RuntimePresenceObject(root, "data");
			string topSource = RuntimePresenceString(root, "source");
			string dataSource = RuntimePresenceString(data, "source");
			string resolvedSource = !string.IsNullOrWhiteSpace(dataSource) ? dataSource : topSource;
			if (!string.IsNullOrWhiteSpace(resolvedSource))
				_runtimePresence.StageSource = resolvedSource;

			if (eventType is "affect_state" or "cognitive_affect" or "inner_affect")
			{
				JsonElement affect = RuntimePresenceObject(data, "affect");
				if (affect.ValueKind != JsonValueKind.Object)
					affect = RuntimePresenceObject(root, "affect");
				RuntimePresenceReadAffect(affect);
				_runtimePresence.ThoughtPressure = RuntimePresenceFloat(data, "thought_pressure", _runtimePresence.ThoughtPressure, signed: false);
				_runtimePresence.Confidence = RuntimePresenceFloat(data, "confidence", _runtimePresence.Confidence, signed: false);
				_runtimePresence.DiaryUpdated = RuntimePresenceBool(data, "diary_updated", false);
				if (!string.IsNullOrWhiteSpace(resolvedSource))
					_runtimePresence.Source = resolvedSource;
				_runtimePresence.LastAffectAtMs = _runtimePresence.LastPacketAtMs;
			}
			else if (data.ValueKind == JsonValueKind.Object && data.TryGetProperty("affect", out JsonElement nestedAffect))
			{
				RuntimePresenceReadAffect(nestedAffect);
				if (!string.IsNullOrWhiteSpace(resolvedSource))
					_runtimePresence.Source = resolvedSource;
				_runtimePresence.LastAffectAtMs = _runtimePresence.LastPacketAtMs;
			}

			string explicitEmotion = RuntimePresenceString(root, "emotion").Trim().ToLowerInvariant();
			string explicitMotion = RuntimePresenceString(root, "motion").Trim().ToLowerInvariant();
			if (!string.IsNullOrWhiteSpace(explicitEmotion))
				_runtimePresence.Emotion = explicitEmotion;
			if (!string.IsNullOrWhiteSpace(explicitMotion))
				_runtimePresence.Motion = explicitMotion;

			switch (eventType)
			{
				case "thinking_started":
					_runtimePresence.Thinking = true;
					_runtimePresence.Speaking = false;
					_runtimePresence.Stage = "thinking";
					break;
				case "thinking_finished":
					_runtimePresence.Thinking = false;
					_runtimePresence.Stage = "settling";
					break;
				case "audio_playback_started":
					_runtimePresence.Speaking = true;
					_runtimePresence.Thinking = false;
					_runtimePresence.Stage = "speaking";
					break;
				case "audio_playback_done":
				case "stage_segment_cancelled":
				case "stage_segment_failed":
				case "continuation_cancelled":
					_runtimePresence.Speaking = false;
					_runtimePresence.Thinking = false;
					_runtimePresence.Stage = "afterglow";
					break;
				case "stage_segment":
					if (!_runtimePresence.Speaking && !_runtimePresence.Thinking)
						_runtimePresence.Stage = "staged";
					break;
				case "show_plan":
					if (!_runtimePresence.Speaking && !_runtimePresence.Thinking)
						_runtimePresence.Stage = "planning";
					break;
			}

			_latestEmotionDebug = MergeRuntimePresence(_latestEmotionDebug);
			if (_emotionPanel != null && _emotionPanel.Visible)
				RefreshEmotionPanel();
		}
		catch (JsonException)
		{
			// Packet text/legacy không thuộc stage protocol, bỏ qua im lặng.
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[RuntimePresence] capture failed: {ex.Message}");
		}
	}

	private void TickRuntimePresencePanel()
	{
		if (_emotionPanel == null || !_emotionPanel.Visible)
			return;
		ulong now = Time.GetTicksMsec();
		if (now - _runtimePresenceLastUiRefreshMs < 500)
			return;
		_runtimePresenceLastUiRefreshMs = now;

		ulong age = _runtimePresence.LastPacketAtMs > 0 ? now - _runtimePresence.LastPacketAtMs : ulong.MaxValue;
		if (!_runtimePresence.Speaking && !_runtimePresence.Thinking && age > 12000)
			_runtimePresence.Stage = "idle";
		if (age > 45000)
		{
			_runtimePresence.Emotion = "";
			_runtimePresence.Motion = "";
		}
		_latestEmotionDebug = MergeRuntimePresence(_latestEmotionDebug);
		RefreshEmotionPanel();
	}

	private EmotionDebug MergeRuntimePresence(EmotionDebug baseline)
	{
		var items = new List<EmotionDebugItem>();
		var occupied = new HashSet<string>(StringComparer.Ordinal);

		void AddNumeric(string key, string label, float value, string group, string note = "")
		{
			float numeric = Mathf.Clamp(value, 0f, 1f);
			items.Add(new EmotionDebugItem
			{
				Key = key,
				Label = label,
				Group = group,
				ValueText = numeric.ToString("0.00"),
				NumericValue = numeric,
				HasNumericValue = true,
				Note = note,
			});
			occupied.Add(key);
		}

		void AddText(string key, string label, string value, string group, string note = "")
		{
			if (string.IsNullOrWhiteSpace(value))
				return;
			items.Add(new EmotionDebugItem
			{
				Key = key,
				Label = label,
				Group = group,
				ValueText = value,
				HasNumericValue = false,
				Note = note,
			});
			occupied.Add(key);
		}

		if (_runtimePresence.LastPacketAtMs > 0)
		{
			AddText("runtime_stage", "nhịp hiện tại", RuntimePresenceStageVi(_runtimePresence.Stage), "presence");
			AddText("runtime_event", "event gần nhất", _runtimePresence.LastEventType, "presence");
			AddText("runtime_source", "nguồn affect", RuntimePresenceSourceVi(_runtimePresence.Source), "presence");
			AddText("runtime_stage_source", "nguồn sân khấu", RuntimePresenceSourceVi(_runtimePresence.StageSource), "presence");
			AddText("runtime_idle_bias", "idle bias", RuntimePresenceIdleBias(), "presence", "Xu hướng vi chuyển động, không phải motion cưỡng bức.");
			AddText("runtime_emotion", "biểu cảm sân khấu", _runtimePresence.Emotion, "surface");
			AddText("runtime_motion", "motion sân khấu", _runtimePresence.Motion, "surface");
			if (_runtimePresence.DiaryUpdated)
				AddText("runtime_diary", "inner diary", "vừa cập nhật", "presence", "Chỉ nhận metadata; không lộ nội dung nhật ký.");
		}

		float Get(string key, float fallback = 0f) => _runtimePresence.Affect.TryGetValue(key, out float value) ? value : fallback;
		bool hasLiveAffect = _runtimePresence.Affect.Count > 0;
		if (hasLiveAffect)
		{
			float arousal = Get("arousal");
			float irritation = Get("irritation");
			float tension = Get("cognitive_tension");
			float tenderness = Get("tenderness");
			float attachment = Get("attachment");
			float curiosity = Get("curiosity");
			float socialEnergy = Get("social_energy");
			float thoughtPressure = Math.Max(_runtimePresence.ThoughtPressure, tension);
			float overload = Math.Max(tension, Math.Max(irritation, arousal * 0.55f));
			float stability = 1f - Math.Max(arousal, Math.Max(irritation, tension));
			float warmth = Math.Max(tenderness, attachment * 0.68f);

			AddNumeric("calm_aroused", "arousal sống", arousal, "live_affect");
			AddNumeric("emotional_stability", "ổn định hiện tại", stability, "live_affect");
			AddNumeric("overload", "quá tải hiện tại", overload, "live_affect");
			AddNumeric("curiosity", "tò mò", curiosity, "live_affect");
			AddNumeric("irritation", "khó chịu", irritation, "live_affect");
			AddNumeric("cognitive_tension", "căng nhận thức", tension, "live_affect");
			AddNumeric("thought_stream_pressure", "áp lực suy nghĩ", thoughtPressure, "live_affect");
			AddNumeric("thought_pressure", "thought pressure", _runtimePresence.ThoughtPressure, "live_affect");
			AddNumeric("confidence", "độ tin cậy affect", _runtimePresence.Confidence, "live_affect");
			AddNumeric("attachment", "gắn bó", attachment, "live_affect");
			AddNumeric("tenderness", "dịu dàng", tenderness, "live_affect");
			AddNumeric("warmth", "độ ấm", warmth, "live_affect");
			AddNumeric("intimacy", "độ gần", attachment * 0.78f, "live_affect");
			AddNumeric("social_energy", "năng lượng xã hội", socialEnergy, "live_affect");
			AddNumeric("speech_pressure", "muốn biểu đạt", Math.Max(socialEnergy, thoughtPressure * 0.62f), "live_affect");
			AddNumeric("social_pressure", "động lực giao tiếp", socialEnergy, "live_affect");
			foreach (string key in new[] { "boredom", "protectiveness", "fatigue" })
				if (_runtimePresence.Affect.ContainsKey(key))
					AddNumeric(key, RuntimePresenceAffectLabel(key), Get(key), "live_affect");
		}

		if (baseline != null && baseline.Items != null)
		{
			foreach (EmotionDebugItem item in baseline.Items)
			{
				if (item == null || string.IsNullOrWhiteSpace(item.Key)
					|| occupied.Contains(item.Key)
					|| item.Key.StartsWith("runtime_", StringComparison.Ordinal))
					continue;
				items.Add(item);
				occupied.Add(item.Key);
			}
		}

		float valence = hasLiveAffect ? Mathf.Clamp(Get("valence"), -1f, 1f) : (baseline?.SummaryValence ?? 0f);
		bool hasValence = hasLiveAffect || (baseline?.HasSummaryValence ?? false);
		float liveIrritation = Get("irritation");
		string mood = hasLiveAffect
			? (liveIrritation >= 0.50f || valence <= -0.28f ? "kho_chiu" : valence >= 0.28f ? "vui" : "trung_tinh")
			: (baseline?.SummaryValue ?? "trung_tinh");
		string state = _runtimePresence.LastPacketAtMs > 0
			? $"{RuntimePresenceStageVi(_runtimePresence.Stage)} · {RuntimePresenceSourceVi(_runtimePresence.Source)}"
			: (baseline?.SummaryState ?? "");

		return new EmotionDebug
		{
			SummaryLabel = hasLiveAffect ? "khí sắc sống" : (baseline?.SummaryLabel ?? "khí sắc"),
			SummaryValue = mood,
			SummaryState = state,
			SummaryValence = valence,
			HasSummaryValence = hasValence,
			Items = items,
		};
	}

	private void ResetRuntimePresenceState()
	{
		_runtimePresence.Affect.Clear();
		_runtimePresence.Source = "";
		_runtimePresence.StageSource = "";
		_runtimePresence.Stage = "idle";
		_runtimePresence.Emotion = "";
		_runtimePresence.Motion = "";
		_runtimePresence.TurnId = "";
		_runtimePresence.LastEventType = "";
		_runtimePresence.ThoughtPressure = 0f;
		_runtimePresence.Confidence = 0f;
		_runtimePresence.DiaryUpdated = false;
		_runtimePresence.Speaking = false;
		_runtimePresence.Thinking = false;
		_runtimePresence.LastPacketAtMs = 0;
		_runtimePresence.LastAffectAtMs = 0;
		_runtimePresenceLastUiRefreshMs = 0;
	}

	private void RuntimePresenceReadAffect(JsonElement affect)
	{
		if (affect.ValueKind != JsonValueKind.Object)
			return;
		foreach (JsonProperty property in affect.EnumerateObject())
		{
			if (property.Value.ValueKind != JsonValueKind.Number || !property.Value.TryGetSingle(out float value))
				continue;
			value = string.Equals(property.Name, "valence", StringComparison.Ordinal)
				? Mathf.Clamp(value, -1f, 1f)
				: Mathf.Clamp(value, 0f, 1f);
			_runtimePresence.Affect[property.Name] = value;
		}
	}

	private string RuntimePresenceIdleBias()
	{
		if (_runtimePresence.Speaking)
			return "giảm idle để ưu tiên lip-sync";
		if (_runtimePresence.Thinking)
			return "ponder nhẹ";
		float fatigue = _runtimePresence.Affect.TryGetValue("fatigue", out float f) ? f : 0f;
		float curiosity = _runtimePresence.Affect.TryGetValue("curiosity", out float c) ? c : 0f;
		float tension = _runtimePresence.Affect.TryGetValue("cognitive_tension", out float t) ? t : 0f;
		if (tension >= 0.58f || _runtimePresence.ThoughtPressure >= 0.58f)
			return "nghiêng đầu / giữ nét suy nghĩ";
		if (fatigue >= 0.58f)
			return "chớp chậm / chuyển động nhỏ";
		if (curiosity >= 0.52f)
			return "liếc nhẹ / tilt tò mò";
		return "ambient micro-motion";
	}

	private static readonly HashSet<string> RuntimePresenceEventTypes = new(StringComparer.Ordinal)
	{
		"affect_state", "cognitive_affect", "inner_affect", "stage_segment", "show_plan",
		"thinking_started", "thinking_finished", "continuation_cancelled",
		"audio_playback_started", "audio_playback_done", "stage_segment_cancelled", "stage_segment_failed",
	};

	private static JsonElement RuntimePresenceObject(JsonElement root, string key)
	{
		return root.ValueKind == JsonValueKind.Object
			&& root.TryGetProperty(key, out JsonElement value)
			&& value.ValueKind == JsonValueKind.Object ? value : default;
	}

	private static string RuntimePresenceString(JsonElement root, string key)
	{
		return root.ValueKind == JsonValueKind.Object
			&& root.TryGetProperty(key, out JsonElement value)
			&& value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
	}

	private static bool RuntimePresenceBool(JsonElement root, string key, bool fallback)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value))
			return fallback;
		return value.ValueKind == JsonValueKind.True ? true : value.ValueKind == JsonValueKind.False ? false : fallback;
	}

	private static float RuntimePresenceFloat(JsonElement root, string key, float fallback, bool signed)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)
			|| value.ValueKind != JsonValueKind.Number || !value.TryGetSingle(out float number))
			return fallback;
		return signed ? Mathf.Clamp(number, -1f, 1f) : Mathf.Clamp(number, 0f, 1f);
	}

	private static string RuntimePresenceStageVi(string stage) => stage switch
	{
		"thinking" => "đang suy nghĩ",
		"speaking" => "đang nói",
		"staged" => "đã xếp câu diễn",
		"planning" => "đang dựng nhịp",
		"settling" => "đang hạ nhịp",
		"afterglow" => "dư âm sau câu nói",
		_ => "idle sống",
	};

	private static string RuntimePresenceSourceVi(string source)
	{
		if (string.IsNullOrWhiteSpace(source))
			return "runtime";
		return source.Replace("private_mind:", "não phụ · ", StringComparison.OrdinalIgnoreCase)
			.Replace("public_chat", "chat công khai", StringComparison.OrdinalIgnoreCase)
			.Replace('_', ' ');
	}

	private static string RuntimePresenceAffectLabel(string key) => key switch
	{
		"boredom" => "chán",
		"protectiveness" => "bảo vệ",
		"fatigue" => "mệt",
		_ => key.Replace('_', ' '),
	};
}
