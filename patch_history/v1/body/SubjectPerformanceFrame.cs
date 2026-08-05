using System;
using System.Collections.Generic;
using System.Text.Json;

/// <summary>
/// Versioned body-only contract emitted by the Python performance adapter.
/// It intentionally contains no beliefs, raw need activations, hidden evidence,
/// narrative hypotheses or other private Subject Core state.
/// </summary>
public sealed class SubjectPerformanceFrame
{
    public const string Protocol = "eris.subject.performance";
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public string PlanId { get; init; } = "";
    public string DecisionId { get; init; } = "";
    public string DeliveryId { get; init; } = "";
    public int Sequence { get; init; }
    public float Energy { get; init; } = 0.5f;
    public float Pace { get; init; } = 0.5f;
    public float Vulnerability { get; init; }
    public float Restraint { get; init; } = 0.5f;
    public string GazeTarget { get; init; } = "user";
    public IReadOnlyList<string> BodyCues { get; init; } = Array.Empty<string>();

    public static bool TryParse(string raw, out SubjectPerformanceFrame frame)
    {
        frame = null;
        if (string.IsNullOrWhiteSpace(raw))
            return false;

        try
        {
            using JsonDocument document = JsonDocument.Parse(raw);
            JsonElement root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("protocol", out JsonElement protocol)
                || !string.Equals(protocol.GetString(), Protocol, StringComparison.Ordinal))
                return false;

            int schemaVersion = ReadInt(root, "schema_version", CurrentSchemaVersion);
            if (schemaVersion != CurrentSchemaVersion)
                return false;

            var cues = new List<string>();
            if (root.TryGetProperty("body_cues", out JsonElement cueRoot)
                && cueRoot.ValueKind == JsonValueKind.Array)
            {
                foreach (JsonElement item in cueRoot.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString()))
                        cues.Add(item.GetString());
                }
            }

            frame = new SubjectPerformanceFrame
            {
                SchemaVersion = schemaVersion,
                PlanId = ReadString(root, "plan_id"),
                DecisionId = ReadString(root, "decision_id"),
                DeliveryId = ReadString(root, "delivery_id"),
                Sequence = ReadInt(root, "sequence", 0),
                Energy = ReadScore(root, "energy", 0.5f),
                Pace = ReadScore(root, "pace", 0.5f),
                Vulnerability = ReadScore(root, "vulnerability", 0f),
                Restraint = ReadScore(root, "restraint", 0.5f),
                GazeTarget = ReadString(root, "gaze_target", "user"),
                BodyCues = cues,
            };
            return !string.IsNullOrWhiteSpace(frame.PlanId);
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static string ReadString(JsonElement root, string name, string fallback = "")
    {
        return root.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? fallback
            : fallback;
    }

    private static int ReadInt(JsonElement root, string name, int fallback)
    {
        return root.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.Number
            && value.TryGetInt32(out int result)
            ? result
            : fallback;
    }

    private static float ReadScore(JsonElement root, string name, float fallback)
    {
        if (!root.TryGetProperty(name, out JsonElement value) || value.ValueKind != JsonValueKind.Number
            || !value.TryGetSingle(out float result))
            return fallback;
        return Math.Clamp(result, 0f, 1f);
    }
}
