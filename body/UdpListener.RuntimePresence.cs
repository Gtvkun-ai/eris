using Godot;
using System;
using System.Collections.Generic;
using System.Text;
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
		public string LifecycleState = "IDLE";
		public string StatusLabel = "";
		public string SessionId = "";
		public long EventSeq;
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
	private PanelContainer _runtimePresenceIndicator;
	private Label _runtimePresenceIndicatorLabel;
	private string _runtimePresenceAvatarReadySession = "";

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

			JsonElement data = RuntimePresenceObject(root, "data");
			string sessionId = RuntimePresenceString(root, "session_id");
			long eventSeq = RuntimePresenceLong(root, "event_seq", 0L);
			if (stageProtocol)
			{
				EnsureStageAvatarReady(sessionId);
				SendStageAck(sessionId, eventSeq, eventType);
				if (!AcceptStageEvent(sessionId, eventSeq))
					return;
			}

			_runtimePresence.LastPacketAtMs = Time.GetTicksMsec();
			_runtimePresence.LastEventType = eventType;
			string turnId = RuntimePresenceString(root, "turn_id");
			if (string.IsNullOrWhiteSpace(turnId))
				turnId = RuntimePresenceString(data, "turn_id");
			if (!string.IsNullOrWhiteSpace(turnId))
				_runtimePresence.TurnId = turnId;

			string lifecycleState = RuntimePresenceString(data, "state").Trim().ToUpperInvariant();
			if (!string.IsNullOrWhiteSpace(lifecycleState))
				_runtimePresence.LifecycleState = lifecycleState;
			string statusLabel = RuntimePresenceString(data, "label").Trim();
			if (!string.IsNullOrWhiteSpace(statusLabel))
				_runtimePresence.StatusLabel = statusLabel;
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
				case "received":
					SetRuntimePresenceThinking("received");
					break;
				case "thinking_started":
					SetRuntimePresenceThinking("thinking");
					break;
				case "content_committed":
					SetRuntimePresenceThinking("content_committed");
					break;
				case "audio_buffering":
				case "stage_segment_prepare":
				case "stage_segment_queued":
				case "tts_audio_ready":
					SetRuntimePresenceThinking("audio_buffering");
					break;
				case "thinking_finished":
					ApplyThinkingFinishedTarget(lifecycleState);
					break;
				case "speaking":
				case "audio_playback_started":
					_runtimePresence.Speaking = true;
					_runtimePresence.Thinking = false;
					_runtimePresence.Stage = "speaking";
					break;
				case "degraded":
					SetRuntimePresenceTerminal("degraded");
					break;
				case "interrupted":
					SetRuntimePresenceTerminal("interrupted");
					break;
				case "done":
				case "audio_playback_done":
				case "stage_segment_cancelled":
				case "stage_segment_failed":
				case "continuation_cancelled":
					SetRuntimePresenceTerminal("afterglow");
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

			ApplyRuntimePresencePose(eventType, lifecycleState);
			RefreshRuntimePresenceIndicator();
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
		ulong now = Time.GetTicksMsec();
		if ((_runtimePresence.Thinking || _runtimePresence.Speaking)
			&& _runtimePresence.LastPacketAtMs > 0
			&& now - _runtimePresence.LastPacketAtMs > 45000)
		{
			SetRuntimePresenceTerminal("idle");
			RefreshRuntimePresenceIndicator();
		}
		if (_emotionPanel == null || !_emotionPanel.Visible)
			return;
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

	private void SetRuntimePresenceThinking(string stage)
	{
		_runtimePresence.Thinking = true;
		_runtimePresence.Speaking = false;
		_runtimePresence.Stage = stage;
		if (string.IsNullOrWhiteSpace(_runtimePresence.StatusLabel))
			_runtimePresence.StatusLabel = "Đang suy nghĩ…";
	}

	private void SetRuntimePresenceTerminal(string stage)
	{
		_runtimePresence.Speaking = false;
		_runtimePresence.Thinking = false;
		_runtimePresence.Stage = stage;
		_runtimePresence.StatusLabel = "";
	}

	private void ApplyThinkingFinishedTarget(string lifecycleState)
	{
		switch (lifecycleState)
		{
			case "SPEAKING":
				_runtimePresence.Speaking = true;
				_runtimePresence.Thinking = false;
				_runtimePresence.Stage = "speaking";
				break;
			case "DEGRADED":
				SetRuntimePresenceTerminal("degraded");
				break;
			case "INTERRUPTED":
				SetRuntimePresenceTerminal("interrupted");
				break;
			case "DONE":
				SetRuntimePresenceTerminal("afterglow");
				break;
			default:
				_runtimePresence.Thinking = false;
				_runtimePresence.Stage = "settling";
				break;
		}
	}

	private void ApplyRuntimePresencePose(string eventType, string lifecycleState)
	{
		if (_isLive2DMode || _motion == null || _body == null)
			return;
		bool thinkingEvent = eventType is "received" or "thinking_started" or "content_committed" or "audio_buffering";
		if (thinkingEvent)
		{
			_lastRemoteMotionAt = GetRuntimeSeconds();
			if (!string.Equals(_motion.CurrentAction, "read", StringComparison.Ordinal))
				_motion.ApplySilentPose("read", -1);
			return;
		}
		bool terminalEvent = eventType is "done" or "degraded" or "interrupted"
			or "audio_playback_done" or "stage_segment_cancelled" or "stage_segment_failed"
			or "continuation_cancelled";
		bool thinkingFinishedTerminal = eventType == "thinking_finished"
			&& (lifecycleState == "DEGRADED" || lifecycleState == "INTERRUPTED" || lifecycleState == "DONE");
		if ((terminalEvent || thinkingFinishedTerminal)
			&& !string.Equals(_motion.CurrentAction, "stand", StringComparison.Ordinal))
		{
			_motion.ApplySilentPose("stand");
		}
	}

	private void RefreshRuntimePresenceIndicator()
	{
		bool visible = _runtimePresence.Thinking && !_runtimePresence.Speaking;
		if (!visible && _runtimePresenceIndicator == null)
			return;
		EnsureRuntimePresenceIndicator();
		if (_runtimePresenceIndicator == null || _runtimePresenceIndicatorLabel == null)
			return;
		_runtimePresenceIndicatorLabel.Text = string.IsNullOrWhiteSpace(_runtimePresence.StatusLabel)
			? "Đang suy nghĩ…"
			: _runtimePresence.StatusLabel;
		_runtimePresenceIndicator.Visible = visible;
	}

	private void EnsureRuntimePresenceIndicator()
	{
		if (_runtimePresenceIndicator != null && GodotObject.IsInstanceValid(_runtimePresenceIndicator))
			return;
		Control root = GetNodeOrNull<Control>("CanvasLayer/Control");
		if (root == null)
			return;

		var panel = new PanelContainer
		{
			Name = "RuntimePresenceIndicator",
			Visible = false,
			MouseFilter = Control.MouseFilterEnum.Ignore,
			ZIndex = 120,
			CustomMinimumSize = new Vector2(196f, 38f),
		};
		panel.AnchorLeft = 0.5f;
		panel.AnchorRight = 0.5f;
		panel.AnchorTop = 0f;
		panel.AnchorBottom = 0f;
		panel.OffsetLeft = -98f;
		panel.OffsetRight = 98f;
		panel.OffsetTop = 18f;
		panel.OffsetBottom = 56f;
		panel.AddThemeStyleboxOverride("panel", new StyleBoxFlat
		{
			BgColor = new Color(0.07f, 0.06f, 0.09f, 0.88f),
			BorderColor = new Color(0.92f, 0.72f, 0.84f, 0.72f),
			BorderWidthLeft = 1,
			BorderWidthTop = 1,
			BorderWidthRight = 1,
			BorderWidthBottom = 1,
			CornerRadiusTopLeft = 18,
			CornerRadiusTopRight = 18,
			CornerRadiusBottomLeft = 18,
			CornerRadiusBottomRight = 18,
			ContentMarginLeft = 16f,
			ContentMarginRight = 16f,
			ContentMarginTop = 7f,
			ContentMarginBottom = 7f,
			ShadowColor = new Color(0f, 0f, 0f, 0.28f),
			ShadowSize = 3,
		});

		var label = new Label
		{
			Text = "Đang suy nghĩ…",
			HorizontalAlignment = HorizontalAlignment.Center,
			VerticalAlignment = VerticalAlignment.Center,
			MouseFilter = Control.MouseFilterEnum.Ignore,
		};
		label.AddThemeColorOverride("font_color", new Color(1f, 0.93f, 0.97f, 1f));
		label.AddThemeFontSizeOverride("font_size", 14);
		panel.AddChild(label);
		root.AddChild(panel);
		_runtimePresenceIndicator = panel;
		_runtimePresenceIndicatorLabel = label;
	}

	private bool AcceptStageEvent(string sessionId, long eventSeq)
	{
		if (!string.IsNullOrWhiteSpace(sessionId)
			&& !string.Equals(sessionId, _runtimePresence.SessionId, StringComparison.Ordinal))
		{
			_runtimePresence.SessionId = sessionId;
			_runtimePresence.EventSeq = 0;
			_runtimePresence.TurnId = "";
		}
		if (eventSeq <= 0)
			return true;
		if (eventSeq <= _runtimePresence.EventSeq)
			return false;
		_runtimePresence.EventSeq = eventSeq;
		return true;
	}

	private void EnsureStageAvatarReady(string sessionId)
	{
		if (string.IsNullOrWhiteSpace(sessionId)
			|| string.Equals(_runtimePresenceAvatarReadySession, sessionId, StringComparison.Ordinal))
			return;
		_runtimePresenceAvatarReadySession = sessionId;
		SendStageInbound(new
		{
			protocol = "eris.stage",
			version = 2,
			type = "avatar_ready",
			session_id = sessionId,
			timestamp = Time.GetUnixTimeFromSystem(),
		});
	}

	private void SendStageAck(string sessionId, long eventSeq, string eventType)
	{
		if (eventSeq <= 0 || string.IsNullOrWhiteSpace(sessionId))
			return;
		if (string.Equals(eventType, "stage_ack_received", StringComparison.Ordinal)
			|| string.Equals(eventType, "avatar_ready_ack", StringComparison.Ordinal)
			|| eventType.EndsWith("_ack", StringComparison.Ordinal))
			return;
		SendStageInbound(new
		{
			protocol = "eris.stage",
			version = 2,
			type = "stage_ack",
			session_id = sessionId,
			event_seq = eventSeq,
			timestamp = Time.GetUnixTimeFromSystem(),
			data = new { event_seq = eventSeq },
		});
	}

	private void SendStageInbound(object payload)
	{
		try
		{
			string raw = JsonSerializer.Serialize(payload);
			_chatSend.PutPacket(Encoding.UTF8.GetBytes(raw));
		}
		catch (Exception ex)
		{
			GD.PrintErr($"[RuntimePresence] inbound stage event failed: {ex.Message}");
		}
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
		_runtimePresence.LifecycleState = "IDLE";
		_runtimePresence.StatusLabel = "";
		_runtimePresence.SessionId = "";
		_runtimePresence.EventSeq = 0;
		_runtimePresenceAvatarReadySession = "";
		_runtimePresence.ThoughtPressure = 0f;
		_runtimePresence.Confidence = 0f;
		_runtimePresence.DiaryUpdated = false;
		_runtimePresence.Speaking = false;
		_runtimePresence.Thinking = false;
		_runtimePresence.LastPacketAtMs = 0;
		_runtimePresence.LastAffectAtMs = 0;
		_runtimePresenceLastUiRefreshMs = 0;
		if (_runtimePresenceIndicator != null)
			_runtimePresenceIndicator.Visible = false;
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
		"received", "thinking_started", "content_committed", "audio_buffering", "thinking_finished",
		"speaking", "done", "degraded", "interrupted", "continuation_cancelled",
		"stage_segment_prepare", "stage_segment_queued", "tts_audio_ready",
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

	private static long RuntimePresenceLong(JsonElement root, string key, long fallback)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)
			|| value.ValueKind != JsonValueKind.Number || !value.TryGetInt64(out long number))
			return fallback;
		return number;
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
		"received" => "đã nhận lượt",
		"thinking" => "đang suy nghĩ",
		"content_committed" => "đã chốt nội dung",
		"audio_buffering" => "đang chuẩn bị giọng",
		"speaking" => "đang nói",
		"degraded" => "đã hạ cấp",
		"interrupted" => "đã bị ngắt",
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
