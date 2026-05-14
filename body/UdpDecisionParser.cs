using Godot;
using System;
using System.Collections.Generic;
using System.Text.Json;

public sealed class UdpDecisionPayload
{
	public string Text { get; init; } = "";
	public bool ParsedJson { get; init; }
	public bool HasTextField { get; init; }
	public bool ShouldSpeak { get; init; } = true;
	public bool HasRemoteMotion { get; init; }
	public MotionCommand MotionCommand { get; init; }
	public BodyBias BodyBias { get; init; }
	public bool HasBodyBias { get; init; }
	public string ParseMode { get; init; } = "";
	public string DebugTrace { get; init; } = "";
	public string ParserTrace { get; init; } = "";
}

public sealed class UdpDecisionParser
{
	private static readonly Dictionary<string, string> AnimAliases = new()
	{
		{ "walk", "stand_walk" },
		{ "walking", "stand_walk" },
		{ "run", "stand_walk" },
		{ "running", "stand_walk" },
		{ "divide", "divine" },
		{ "wave", "stand" },
		{ "idle", "stand" },
	};

	private static readonly HashSet<string> ValidAnimations = new()
	{
		"stand", "sit_down", "sit", "sit_up", "read", "stand_walk",
		"piano", "clone", "divine", "hop", "jump", "sleep", "sad",
		"food", "affection", "climb", "climb_top", "air_swing_l", "air_swing_r",
		"air", "shime", "idle",
	};

	public UdpDecisionPayload Parse(string raw)
	{
		string text = "";
		bool parsedJson = false;
		bool hasTextField = false;
		bool shouldSpeak = true;
		string animation = "stand";
		int direction = 0;
		string nextAnimation = "";
		string bounceAction = "";
		string debugTrace = "";
		string parserTrace = "";
		string parseMode = "";
		string motionIntent = "";
		int motionFacing = 0;
		float motionTargetX = -1f;
		BodyBias bodyBias = null;
		bool hasBodyBias = false;

		try
		{
			string cleaned = StripCodeFence(raw.Trim());
			using var doc = JsonDocument.Parse(cleaned);
			parsedJson = true;
			var root = doc.RootElement;

			if (BodyBias.TryFromJson(root, out bodyBias))
				hasBodyBias = true;
			if (root.TryGetProperty("text", out var t))
			{
				text = t.GetString() ?? "";
				hasTextField = true;
			}
			if (root.TryGetProperty("should_speak", out var ss) && ss.ValueKind == JsonValueKind.False)
				shouldSpeak = false;
			if (root.TryGetProperty("animation", out var a))
				animation = a.GetString() ?? "stand";
			if (root.TryGetProperty("direction", out var d) && d.ValueKind == JsonValueKind.Number)
				direction = d.GetInt32();
			if (root.TryGetProperty("next_animation", out var na))
				nextAnimation = na.GetString() ?? "";
			if (root.TryGetProperty("bounce_action", out var ba))
				bounceAction = ba.GetString() ?? "";
			if (root.TryGetProperty("debug_trace", out var dt))
				debugTrace = dt.GetString() ?? "";
			if (root.TryGetProperty("parser_trace", out var pt))
				parserTrace = pt.GetString() ?? "";
			if (root.TryGetProperty("parse_mode", out var pm))
				parseMode = pm.GetString() ?? "";
			if (root.TryGetProperty("target_x", out var tx) && tx.ValueKind == JsonValueKind.Number)
				motionTargetX = tx.GetSingle();
			if (root.TryGetProperty("motion_intent", out var mi))
				motionIntent = mi.GetString() ?? "";
			if (root.TryGetProperty("motion_facing", out var mf) && mf.ValueKind == JsonValueKind.Number)
				motionFacing = mf.GetInt32();
			if (root.TryGetProperty("motion_target_x", out var mtx) && mtx.ValueKind == JsonValueKind.Number)
				motionTargetX = mtx.GetSingle();
		}
		catch (Exception ex)
		{
			string trimmed = raw.TrimStart();
			bool rawIsPlainText = !trimmed.StartsWith("{", StringComparison.Ordinal) && !trimmed.StartsWith("```", StringComparison.Ordinal);
			GD.PrintErr($"[Parse] Khung du lieu bi hong: {ex.Message}");
			text = rawIsPlainText ? raw : "Loi duong truyen tin hieu.";
			hasTextField = true;
			animation = "stand";
		}

		int resolvedFacing = motionFacing != 0 ? motionFacing : direction;
		animation = NormalizeAnimationName(animation, resolvedFacing);
		nextAnimation = NormalizeAnimationName(nextAnimation, resolvedFacing, allowEmpty: true);
		bounceAction = NormalizeAnimationName(bounceAction, resolvedFacing, allowEmpty: true);
		if (string.IsNullOrWhiteSpace(motionIntent))
			motionIntent = InferMotionIntent(animation, nextAnimation, resolvedFacing, motionTargetX);
		if (motionFacing == 0)
			motionFacing = resolvedFacing;

		bool hasRemoteMotion = HasRemoteMotionCommand(motionIntent, animation, nextAnimation, motionFacing, motionTargetX);
		return new UdpDecisionPayload
		{
			Text = text,
			ParsedJson = parsedJson,
			HasTextField = hasTextField,
			ShouldSpeak = shouldSpeak,
			HasRemoteMotion = hasRemoteMotion,
			MotionCommand = new MotionCommand(motionIntent, animation, nextAnimation, bounceAction, motionFacing, motionTargetX),
			BodyBias = bodyBias,
			HasBodyBias = hasBodyBias,
			ParseMode = parseMode,
			DebugTrace = debugTrace,
			ParserTrace = parserTrace,
		};
	}

	private static string StripCodeFence(string cleaned)
	{
		if (!cleaned.StartsWith("```", StringComparison.Ordinal))
			return cleaned;
		int start = cleaned.IndexOf('\n') + 1;
		int end = cleaned.LastIndexOf("```", StringComparison.Ordinal);
		return start > 0 && end > start ? cleaned.Substring(start, end - start).Trim() : cleaned;
	}

	private static string NormalizeAnimationName(string animation, int facingDir, bool allowEmpty = false)
	{
		string value = (animation ?? "").Trim();
		if (string.IsNullOrEmpty(value))
			return allowEmpty ? "" : "stand";
		if (AnimAliases.TryGetValue(value, out var mapped))
		{
			GD.Print($"[Anim] Alias '{value}' -> '{mapped}'");
			value = mapped;
		}
		if (ValidAnimations.Contains(value))
			return value;
		string fallback = (facingDir == 1 || facingDir == -1) ? "stand_walk" : "stand";
		GD.PrintErr($"[Anim] Animation khong hop le: '{value}', fallback ve '{fallback}'.");
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
}
