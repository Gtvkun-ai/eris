using Godot;
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;

public partial class UdpListener
{
    // Godot is only the UDP -> loopback web bridge; no Godot Canvas controls remain.
    private Button _contextLearningCanvasButton;
    private readonly ConcurrentQueue<string> _webCanvasOutbox = new();
    private readonly List<WebCanvasAck> _webCanvasAcks = new();
    private JsonElement _webCanvasSnapshot, _webCanvasExercise, _webCanvasPlayback;
    private string _webCanvasStateJson = "{\"online\":true,\"learning_canvas\":null,\"acks\":[]}";
    private long _webCanvasRevision = -1;
    private long _webCanvasVersion;
    private bool _webCanvasAutoOpened;

    private void InitializeWebLearningCanvas()
    {
        if (_contextLearningCanvasButton != null)
            _contextLearningCanvasButton.Pressed += OpenWebLearningCanvas;
    }

    private void OpenWebLearningCanvas()
    {
        CloseCharacterContextMenu();
        OpenRichChatPortal("canvas.html");
    }

    private void ResetWebCanvasPortal()
    {
        // The local URL/token is invalid after shutdown. Retain the last snapshot
        // for a new portal, but do not reuse requests queued by an old browser.
        while (_webCanvasOutbox.TryDequeue(out _)) { }
        _webCanvasAutoOpened = false;
    }

    // This is called on the HTTP listener worker. Strictly whitelist the browser
    // request; the browser never obtains a raw UDP or arbitrary Python endpoint.
    private bool TryQueueWebCanvasRequest(JsonElement request)
    {
        if (request.ValueKind != JsonValueKind.Object || _webCanvasOutbox.Count >= 8)
            return false;
        string action = ReadJsonString(request, "action");
        string requestId = ReadJsonString(request, "request_id");
        if (requestId.Length < 8 || requestId.Length > 120 ||
            !new[] { "open", "navigate", "exercise", "submit", "hint", "reveal", "exercise_status", "ack_eris_focus" }.Contains(action))
            return false;
        var packet = new Dictionary<string, object>
        {
            ["type"] = "learning_canvas_request", ["group_id"] = "java-di",
            ["action"] = action, ["request_id"] = requestId
        };
        if (action != "open")
        {
            if (!request.TryGetProperty("base_revision", out var rev) ||
                rev.ValueKind != JsonValueKind.Number || !rev.TryGetInt64(out long revision) || revision < 0)
                return false;
            packet["base_revision"] = revision;
        }
        string[] stringFields = { "node_id", "exercise_id", "activity_id", "nonce", "answer", "code", "cause_id" };
        foreach (string field in stringFields)
        {
            if (!request.TryGetProperty(field, out var value)) continue;
            if (value.ValueKind != JsonValueKind.String) return false;
            string text = value.GetString() ?? "";
            int maxBytes = field == "code" ? 12_000 : field == "answer" ? 800 : 200;
            if (Encoding.UTF8.GetByteCount(text) > maxBytes) return false;
            packet[field] = text;
        }
        if ((action is "navigate" or "exercise") && !packet.ContainsKey("node_id")) return false;
        if (action == "exercise" && !packet.ContainsKey("exercise_id")) return false;
        if ((action is "submit" or "hint" or "reveal" or "exercise_status") &&
            (!packet.ContainsKey("activity_id") || !packet.ContainsKey("nonce"))) return false;
        if (action == "submit" && !packet.ContainsKey("code") && !packet.ContainsKey("answer")) return false;
        if (action == "ack_eris_focus" && !packet.ContainsKey("cause_id")) return false;
        _webCanvasOutbox.Enqueue(JsonSerializer.Serialize(packet));
        return true;
    }

    private void TickWebLearningCanvas()
    {
        // Godot networking must stay on the main thread. No HTTP worker sends UDP.
        int count = 0;
        while (count++ < 4 && _webCanvasOutbox.TryDequeue(out string packet))
        {
            if (_chatSend == null || _chatSend.PutPacket(Encoding.UTF8.GetBytes(packet)) != Error.Ok)
            {
                using var rejected = JsonDocument.Parse(packet);
                RecordWebCanvasAck(ReadJsonString(rejected.RootElement, "request_id"),
                    "unavailable", "Không gửi được yêu cầu đến backend.", "");
                PublishWebCanvasState();
            }
        }
    }

    private void RecordWebCanvasAck(string id, string status, string message, string action)
    {
        if (string.IsNullOrWhiteSpace(id)) return;
        _webCanvasAcks.RemoveAll(a => a.request_id == id);
        _webCanvasAcks.Add(new WebCanvasAck(id, status, message, action));
        if (_webCanvasAcks.Count > 16) _webCanvasAcks.RemoveAt(0);
    }

    private sealed class WebCanvasAck
    {
        public string request_id { get; }
        public string status { get; }
        public string message { get; }
        public string action { get; }
        public WebCanvasAck(string id, string result, string detail, string operation)
        {
            request_id = id; status = result; message = detail; action = operation;
        }
    }

    private bool TryHandleWebLearningCanvasPacket(string raw)
    {
        try
        {
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            string type = ReadJsonString(root, "type");
            if (type is "canvas_playback" or "canvas_highlight")
            {
                _webCanvasPlayback = root.Clone();
                PublishWebCanvasState();
                return true;
            }
            if (type is not ("learning_canvas_ack" or "learning_canvas_state")) return false;
            if (root.TryGetProperty("learning_canvas", out var snapshot) && snapshot.ValueKind == JsonValueKind.Object &&
                ReadJsonString(snapshot, "schema") == "eris.learning.canvas.v1" &&
                snapshot.TryGetProperty("focus", out var focus) && focus.TryGetProperty("revision", out var rev) &&
                rev.TryGetInt64(out long revision))
            {
                // Backend restarts can reset revision; a new playback stream is
                // the backend-authoritative epoch, not a stale in-flight packet.
                string nextStream = ReadJsonString(snapshot, "playback_stream_id");
                string lastStream = _webCanvasSnapshot.ValueKind == JsonValueKind.Object
                    ? ReadJsonString(_webCanvasSnapshot, "playback_stream_id") : "";
                if (nextStream != "" && lastStream != "" && nextStream != lastStream)
                {
                    _webCanvasRevision = -1;
                    _webCanvasExercise = default;
                    _webCanvasPlayback = default;
                }
                if (revision >= _webCanvasRevision)
                {
                    _webCanvasRevision = revision;
                    _webCanvasSnapshot = snapshot.Clone();
                    if (snapshot.TryGetProperty("activity", out var activity) && activity.ValueKind == JsonValueKind.Object)
                        _webCanvasExercise = activity.Clone();
                    if (snapshot.TryGetProperty("playback", out var playback) && playback.ValueKind == JsonValueKind.Object)
                        _webCanvasPlayback = playback.Clone();
                }
            }
            if (root.TryGetProperty("exercise_update", out var update) && update.ValueKind == JsonValueKind.Object)
                _webCanvasExercise = update.Clone();
            if (type == "learning_canvas_ack")
                RecordWebCanvasAck(ReadJsonString(root, "request_id"), ReadJsonString(root, "status"),
                    ReadJsonString(root, "message"), ReadJsonString(root, "action"));
            PublishWebCanvasState();
            // A backend-initiated focus change used to open the Godot panel. Now
            // the same notification opens the web page at most once per session.
            if (type == "learning_canvas_state" && !_webCanvasAutoOpened &&
                root.TryGetProperty("open_panel", out var open) && open.ValueKind == JsonValueKind.True)
            {
                _webCanvasAutoOpened = true;
                OpenWebLearningCanvas();
            }
            return true;
        }
        catch (JsonException) { return false; }
        catch (InvalidOperationException) { return false; }
    }

    private void PublishWebCanvasState()
    {
        // Always serialize on Godot's main thread; the HTTP thread reads a single
        // atomically swapped immutable string, never a mutable JsonDocument.
        object snapshot = _webCanvasSnapshot.ValueKind == JsonValueKind.Object ? _webCanvasSnapshot : null;
        object activity = _webCanvasExercise.ValueKind == JsonValueKind.Object ? _webCanvasExercise : null;
        object playback = _webCanvasPlayback.ValueKind == JsonValueKind.Object ? _webCanvasPlayback : null;
        string json = JsonSerializer.Serialize(new
        {
            online = true, version = ++_webCanvasVersion,
            learning_canvas = snapshot, exercise_update = activity,
            playback, acks = _webCanvasAcks.ToArray()
        });
        Volatile.Write(ref _webCanvasStateJson, json);
    }
}
