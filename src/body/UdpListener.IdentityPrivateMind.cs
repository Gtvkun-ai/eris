using Godot;
using System;
using System.Collections.Generic;
using System.Text.Json;

public partial class UdpListener : Node2D
{
	// Adapter UI cho private_mind_digest của Architecture C v7 semantic cutover. Panel nhật ký cũ
	// vẫn giữ layout dễ đọc, nhưng nội dung không còn bịa từ Ni/Fe legacy.
	private static bool IsModernIdentityDigest(JsonElement root)
	{
		if (root.ValueKind != JsonValueKind.Object)
			return false;
		if (root.TryGetProperty("active_motives", out JsonElement motives) && motives.ValueKind == JsonValueKind.Array)
			return true;
		if (root.TryGetProperty("active_conflict", out JsonElement conflict) && conflict.ValueKind == JsonValueKind.Object)
			return true;
		if (root.TryGetProperty("architecture", out JsonElement architecture) && architecture.ValueKind == JsonValueKind.String)
			return (architecture.GetString() ?? "").StartsWith("ai_orchestrated.", StringComparison.OrdinalIgnoreCase);
		return false;
	}

	private static List<PrivateMindDiarySection> BuildModernIdentityDiarySlots(JsonElement root)
	{
		var current = new List<PrivateMindDiaryItem>();
		JsonElement interpretation = IdentityObj(root, "self_interpretation");
		IdentityAdd(current, IdentityText(interpretation, "summary"));
		JsonElement intention = IdentityObj(root, "latest_intention");
		string motive = IdentityText(intention, "motive");
		string topic = IdentityText(intention, "topic");
		if (!string.IsNullOrWhiteSpace(motive) || !string.IsNullOrWhiteSpace(topic))
			IdentityAdd(current, $"Motive: {motive} · {topic}".Trim(' ', '·'));

		var future = new List<PrivateMindDiaryItem>();
		string strategy = IdentityText(intention, "strategy");
		string toolIntent = IdentityText(intention, "tool_intent");
		if (!string.IsNullOrWhiteSpace(strategy)) IdentityAdd(future, $"Chiến lược dự kiến: {IdentityPretty(strategy)}");
		if (!string.IsNullOrWhiteSpace(toolIntent)) IdentityAdd(future, $"Tool intent: {toolIntent}");
		JsonElement loops = IdentityArr(root, "open_loops");
		if (loops.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in loops.EnumerateArray())
			{
				if (item.ValueKind == JsonValueKind.String) IdentityAdd(future, item.GetString() ?? "");
				if (future.Count >= 3) break;
			}
		}

		var concerns = new List<PrivateMindDiaryItem>();
		JsonElement conflict = IdentityObj(root, "active_conflict");
		string conflictId = IdentityText(conflict, "conflict_id");
		if (!string.IsNullOrWhiteSpace(conflictId))
			IdentityAdd(concerns, $"{IdentityPretty(conflictId)} · nghiêng về {IdentityPretty(IdentityText(conflict, "chosen_side"))} · residue {IdentityNumber(conflict, "residue"):0.00}");
		JsonElement defenses = IdentityArr(root, "activated_defenses");
		if (defenses.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in defenses.EnumerateArray())
			{
				IdentityAdd(concerns, $"Phòng vệ: {IdentityPretty(IdentityText(item, "key"))} · {IdentityNumber(item, "strength"):0.00}");
				if (concerns.Count >= 3) break;
			}
		}

		var analysis = new List<PrivateMindDiaryItem>();
		JsonElement motives = IdentityArr(root, "active_motives");
		if (motives.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in motives.EnumerateArray())
			{
				IdentityAdd(analysis, $"Động cơ: {IdentityPretty(IdentityText(item, "key"))} · {IdentityNumber(item, "strength"):0.00}");
				if (analysis.Count >= 3) break;
			}
		}
		JsonElement valueChoice = IdentityObj(root, "value_choice");
		string chosen = IdentityText(valueChoice, "chosen");
		if (!string.IsNullOrWhiteSpace(chosen)) IdentityAdd(analysis, $"Giá trị vừa chọn: {IdentityPretty(chosen)}");

		var surface = new List<PrivateMindDiaryItem>();
		JsonElement discovery = IdentityObj(root, "discovery");
		JsonElement activity = IdentityObj(discovery, "current_activity");
		string activityTopic = IdentityText(activity, "topic");
		if (!string.IsNullOrWhiteSpace(activityTopic))
			IdentityAdd(surface, $"Đang {IdentityText(activity, "status")}: {activityTopic}");
		JsonElement ready = IdentityArr(discovery, "ready_to_share");
		if (ready.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in ready.EnumerateArray())
			{
				IdentityAdd(surface, $"Muốn khoe: {IdentityText(item, "topic")}");
				if (surface.Count >= 2) break;
			}
		}
		JsonElement expression = IdentityObj(root, "expression");
		string preset = IdentityText(expression, "preset");
		if (!string.IsNullOrWhiteSpace(preset)) IdentityAdd(surface, $"Biểu hiện sân khấu: {IdentityPretty(preset)}");

		return new List<PrivateMindDiarySection>
		{
			BuildDiarySlot("Suy nghĩ hiện tại", current),
			BuildDiarySlot("Suy nghĩ tương lai", future),
			BuildDiarySlot("Đang bận tâm", concerns),
			BuildDiarySlot("Phân tích gần đây", analysis),
			BuildDiarySlot("Muốn nói", surface),
		};
	}

	private void RefreshModernIdentityConcernStack(JsonElement root)
	{
		if (_diaryConcernList == null)
			return;
		_diaryConcernData.Clear();
		JsonElement conflict = IdentityObj(root, "active_conflict");
		string conflictId = IdentityText(conflict, "conflict_id");
		if (!string.IsNullOrWhiteSpace(conflictId))
			_diaryConcernData.Add((IdentityPretty(conflictId), Mathf.Clamp((float)IdentityNumber(conflict, "activation"), 0f, 1f) * 100f));
		JsonElement defenses = IdentityArr(root, "activated_defenses");
		if (defenses.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in defenses.EnumerateArray())
			{
				string key = IdentityText(item, "key");
				if (!string.IsNullOrWhiteSpace(key))
					_diaryConcernData.Add((IdentityPretty(key), Mathf.Clamp((float)IdentityNumber(item, "strength"), 0f, 1f) * 100f));
				if (_diaryConcernData.Count >= 5) break;
			}
		}
		_diaryConcernExpanded = false;
		RenderDiaryConcernList();
	}

	private void RefreshModernIdentityMemoryEcho(JsonElement root)
	{
		if (_diaryMemoryEchoLabel == null)
			return;
		string echo = "";
		JsonElement loops = IdentityArr(root, "open_loops");
		if (loops.ValueKind == JsonValueKind.Array)
		{
			foreach (JsonElement item in loops.EnumerateArray())
			{
				if (item.ValueKind == JsonValueKind.String)
				{
					echo = item.GetString() ?? "";
					if (!string.IsNullOrWhiteSpace(echo)) break;
				}
			}
		}
		if (string.IsNullOrWhiteSpace(echo))
		{
			JsonElement discovery = IdentityObj(root, "discovery");
			JsonElement ready = IdentityArr(discovery, "ready_to_share");
			if (ready.ValueKind == JsonValueKind.Array)
			{
				foreach (JsonElement item in ready.EnumerateArray())
				{
					echo = IdentityText(item, "topic");
					if (!string.IsNullOrWhiteSpace(echo)) break;
				}
			}
		}
		_diaryMemoryEchoLabel.Text = string.IsNullOrWhiteSpace(echo) ? "“chưa có open loop đáng giữ.”" : $"“{CompactText(echo, 160)}”";
		if (_diaryMemoryEchoMetaLabel != null)
			_diaryMemoryEchoMetaLabel.Text = string.IsNullOrWhiteSpace(echo) ? "" : "— continuity thật";
	}

	private static string RenderModernIdentityDigest(JsonElement root)
	{
		JsonElement interpretation = IdentityObj(root, "self_interpretation");
		string summary = IdentityText(interpretation, "summary");
		JsonElement conflict = IdentityObj(root, "active_conflict");
		string conflictId = IdentityText(conflict, "conflict_id");
		var lines = new List<string>();
		if (!string.IsNullOrWhiteSpace(summary)) lines.Add(summary);
		if (!string.IsNullOrWhiteSpace(conflictId)) lines.Add($"[b]Mâu thuẫn:[/b] {IdentityPretty(conflictId)}");
		JsonElement expression = IdentityObj(root, "expression");
		string preset = IdentityText(expression, "preset");
		if (!string.IsNullOrWhiteSpace(preset)) lines.Add($"[b]Biểu hiện:[/b] {IdentityPretty(preset)}");
		return lines.Count > 0 ? string.Join("\n", lines) : "[i]Identity Kernel đang yên.[/i]";
	}

	private static void IdentityAdd(List<PrivateMindDiaryItem> items, string text)
	{
		text = CompactText(text ?? "", 260);
		if (!string.IsNullOrWhiteSpace(text)) items.Add(new PrivateMindDiaryItem { Text = text, Badge = "" });
	}

	private static JsonElement IdentityObj(JsonElement root, string key)
	{
		return root.ValueKind == JsonValueKind.Object && root.TryGetProperty(key, out JsonElement value) && value.ValueKind == JsonValueKind.Object ? value : default;
	}

	private static JsonElement IdentityArr(JsonElement root, string key)
	{
		return root.ValueKind == JsonValueKind.Object && root.TryGetProperty(key, out JsonElement value) && value.ValueKind == JsonValueKind.Array ? value : default;
	}

	private static string IdentityText(JsonElement root, string key)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)) return "";
		return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : value.ToString();
	}

	private static double IdentityNumber(JsonElement root, string key)
	{
		if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out JsonElement value)) return 0.0;
		return value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double number) ? number : 0.0;
	}

	private static string IdentityPretty(string value)
	{
		return string.IsNullOrWhiteSpace(value) ? "—" : value.Replace("_vs_", " ↔ ").Replace("_", " ").Replace(".", " › ");
	}
}
