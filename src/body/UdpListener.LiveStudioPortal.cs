using Godot;
using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;

public partial class UdpListener
{
    // P4: 1 portal same-origin dùng token sẵn có. Không mở public HTTP port.
    // HTTP worker không đụng PacketPeerUdp; queue được drain trên Godot main thread.
    private readonly ConcurrentQueue<string> _liveStudioOutbox = new();
    private string _liveStudioSnapshot = "{\"active\":false,\"online\":false,\"message\":\"Chưa nhận trạng thái từ Cortex\"}";
    private long _liveStudioLastPollTicks;

    private void RequestLiveStudioStatus()
    {
        long now = DateTime.UtcNow.Ticks;
        long last = Interlocked.Read(ref _liveStudioLastPollTicks);
        if (now - last < TimeSpan.FromMilliseconds(900).Ticks) return;
        if (Interlocked.CompareExchange(ref _liveStudioLastPollTicks, now, last) != last) return;
        if (_liveStudioOutbox.Count < 8)
            _liveStudioOutbox.Enqueue("{\"type\":\"live_control\",\"action\":\"status\",\"request_id\":\"poll\"}");
    }

    private bool TryQueueLiveStudioCommand(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object) return false;
        static string ReadText(JsonElement obj, string key, int limit)
        {
            if (!obj.TryGetProperty(key, out var v) || v.ValueKind != JsonValueKind.String) return "";
            string value = v.GetString() ?? "";
            return value.Length <= limit && !value.Any(char.IsControl) ? value : "";
        }
        string action = ReadText(root, "action", 32);
        if (!new[] { "start_live", "start_simulator", "stop", "emergency_stop", "simulate", "tick", "validate" }.Contains(action))
            return false;
        string requestId = ReadText(root, "request_id", 64);
        if (requestId.Length < 8 || !requestId.All(c => char.IsAsciiLetterOrDigit(c) || c == '-'))
            return false;
        string room = ReadText(root, "room", 40);
        string scenario = ReadText(root, "scenario", 25);
        string comment = ReadText(root, "comment", 300);
        if (action == "start_live" && (room.Length < 2 || room.Length > 33 ||
            !room.TrimStart('@').All(c => char.IsAsciiLetterOrDigit(c) || c == '.' || c == '_'))) return false;
        if (action == "simulate" && !new[] { "conversation", "crowd", "gifts", "support", "injection", "custom" }.Contains(scenario))
            return false;
        if (action == "simulate" && scenario == "custom" && string.IsNullOrWhiteSpace(comment)) return false;
        if (_liveStudioOutbox.Count >= 8) return false;
        _liveStudioOutbox.Enqueue(JsonSerializer.Serialize(new {
            type = "live_control", action, request_id = requestId, room, scenario, comment,
        }));
        return true;
    }

    private bool TryHandleLiveStudioPacket(string raw)
    {
        if (string.IsNullOrEmpty(raw) || !raw.Contains("live_studio_status", StringComparison.Ordinal)) return false;
        // Không cho gói UDP từ địa chỉ không phải loopback chiếm trạng thái UI.
        string ip = _udp.GetPacketIP();
        if (ip != "127.0.0.1" && ip != "::1") return true;
        if (Encoding.UTF8.GetByteCount(raw) > 16000) return true;
        try
        {
            using JsonDocument packet = JsonDocument.Parse(raw);
            JsonElement root = packet.RootElement;
            if (root.ValueKind != JsonValueKind.Object ||
                !root.TryGetProperty("type", out var type) || type.GetString() != "live_studio_status" ||
                !root.TryGetProperty("payload", out var payload) || payload.ValueKind != JsonValueKind.Object)
                return true;
            if (!payload.TryGetProperty("status_version", out var version) || !version.TryGetInt32(out int v) || v != 1)
                return true;
            // JSON hoàn toàn do Python runtime tạo, chỉ chuyển tới trang local có token.
            Volatile.Write(ref _liveStudioSnapshot, payload.GetRawText());
            return true;
        }
        catch (JsonException) { return true; }
    }

    private void TickLiveStudioPortal()
    {
        int sent = 0;
        while (sent++ < 8 && _liveStudioOutbox.TryDequeue(out string command))
            _chatSend.PutPacket(Encoding.UTF8.GetBytes(command));
    }
}
