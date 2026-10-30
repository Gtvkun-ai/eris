using Godot;
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using RandomNumberGenerator = System.Security.Cryptography.RandomNumberGenerator;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

public partial class UdpListener
{
    // Rich Chat runs in the user's regular browser, but operates on Eris' LIVE
    // single-writer transcript and existing SendUserChatMessage. No second LLM,
    // no second conversation store, no Python/socket changes.
    private TcpListener _richChatServer;
    private CancellationTokenSource _richChatCancellation;
    private readonly ConcurrentQueue<string> _richChatOutbox = new();
    private readonly Dictionary<string, (byte[] Bytes, string Mime)> _richChatAssets = new();
    private string _richChatToken = "";
    private string _richChatUrl = "";
    private string _richChatSnapshot = "{\"messages\":[],\"status\":\"Đang kết nối\"}";
    private ulong _richChatLastSnapshotMs;
    private void OpenRichChatPortal()
    {
        if (_companionPreview) return;
        try
        {
            if (_richChatServer == null)
            {
                LoadRichChatAssets();
                _richChatToken = Convert.ToHexString(RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
                // TcpListener does not require Windows URLACL privileges (unlike HttpListener).
                _richChatServer = new TcpListener(IPAddress.Loopback, 0);
                _richChatServer.Start(16);
                int port = ((IPEndPoint)_richChatServer.LocalEndpoint).Port;
                _richChatUrl = $"http://127.0.0.1:{port}/{_richChatToken}/";
                _richChatCancellation = new CancellationTokenSource();
                _ = Task.Run(() => RichChatAcceptLoop(_richChatCancellation.Token));
                GD.Print("[RichChat] Browser portal started on loopback only");
            }
            UpdateRichChatSnapshot();
            Error launch = OS.ShellOpen(_richChatUrl);
            if (launch != Error.Ok)
                throw new InvalidOperationException("Không mở được trình duyệt mặc định: " + launch);
        }
        catch (Exception exc)
        {
            GD.PrintErr("[RichChat] Khởi động không thành công: " + exc.Message);
            if (_workspaceNotice != null)
            {
                _workspaceNotice.Text = "Rich Chat chưa mở được, đang dùng chat Godot.";
                _workspaceNotice.Visible = true;
            }
            StopRichChatPortal();
            if (_conversationHistoryPanel != null && !_conversationHistoryPanel.Visible)
                ShowConversationHistoryPanel();
        }
    }

    private void LoadRichChatAssets()
    {
        Assembly assembly = typeof(UdpListener).Assembly;
        var resources = assembly.GetManifestResourceNames();
        string[] files = {
            "index.html", "chat.css", "chat.js", "artifacts.js", "vendor/mathjax.js", "vendor/prism.css",
            "vendor/prism.js", "vendor/prism-clike.js", "vendor/prism-python.js",
            "vendor/prism-javascript.js", "vendor/prism-typescript.js", "vendor/prism-csharp.js",
            "vendor/prism-c.js", "vendor/prism-cpp.js", "vendor/prism-java.js", "vendor/prism-css.js",
            "vendor/prism-markup.js", "vendor/prism-bash.js", "vendor/prism-json.js"
        };
        foreach (string file in files)
        {
            string suffix = "richchat." + file.Replace('/', '.');
            string resource = resources.FirstOrDefault(name => name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase));
            if (resource == null) throw new FileNotFoundException("Embedded Rich Chat asset absent: " + file);
            using Stream stream = assembly.GetManifestResourceStream(resource);
            using var buffer = new MemoryStream();
            stream.CopyTo(buffer);
            string mime = file.EndsWith(".js", StringComparison.Ordinal) ? "text/javascript; charset=utf-8"
                : file.EndsWith(".css", StringComparison.Ordinal) ? "text/css; charset=utf-8"
                : "text/html; charset=utf-8";
            _richChatAssets[file] = (buffer.ToArray(), mime);
        }
    }

    private async Task RichChatAcceptLoop(CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                TcpClient client = await _richChatServer.AcceptTcpClientAsync(cancellation);
                _ = Task.Run(() => ServeRichChatClient(client), cancellation);
            }
            catch (OperationCanceledException) { break; }
            catch (ObjectDisposedException) { break; }
            catch (Exception exc)
            {
                if (!cancellation.IsCancellationRequested)
                    GD.PrintErr("[RichChat] Accept error: " + exc.Message);
                break;
            }
        }
    }

    private void ServeRichChatClient(TcpClient client)
    {
        using (client)
        {
            try
            {
                client.ReceiveTimeout = 4000;
                client.SendTimeout = 4000;
                using NetworkStream net = client.GetStream();
                // Bound HTTP request size and close each connection, no websocket/external routing.
                using var data = new MemoryStream();
                byte[] chunk = new byte[4096];
                int headerEnd = -1;
                while (data.Length < 16_384 && headerEnd == -1)
                {
                    int read = net.Read(chunk, 0, chunk.Length);
                    if (read <= 0) return;
                    data.Write(chunk, 0, read);
                    headerEnd = FindHttpSeparator(data.GetBuffer(), (int)data.Length);
                }
                if (headerEnd < 0) { Reply(net, 400, "text/plain", Encoding.UTF8.GetBytes("Bad Request")); return; }
                byte[] bytes = data.ToArray();
                string header = Encoding.ASCII.GetString(bytes, 0, headerEnd);
                string[] lines = header.Split("\r\n");
                string[] request = lines[0].Split(' ');
                if (request.Length != 3) { Reply(net, 400, "text/plain", Array.Empty<byte>()); return; }
                string method = request[0], path = request[1].Split('?')[0];
                // Refuse DNS rebinding and cross-origin writes even when the token leaks.
                string expectedHost = "127.0.0.1:" + ((IPEndPoint)_richChatServer.LocalEndpoint).Port;
                if (!lines.Any(line => line.Equals("Host: " + expectedHost, StringComparison.OrdinalIgnoreCase)))
                { Reply(net, 403, "text/plain", Array.Empty<byte>()); return; }
                string routePrefix = "/" + _richChatToken + "/";
                if (!path.StartsWith(routePrefix, StringComparison.Ordinal))
                { Reply(net, 404, "text/plain", Array.Empty<byte>()); return; }
                string relative = path.Substring(routePrefix.Length);
                if (method == "GET" && relative == "api/state")
                {
                    string snapshot = Volatile.Read(ref _richChatSnapshot);
                    Reply(net, 200, "application/json; charset=utf-8", Encoding.UTF8.GetBytes(snapshot));
                    return;
                }
                if (method == "GET" && relative.StartsWith("api/image/", StringComparison.Ordinal))
                {
                    if (TryReadRichChatArtifactImage(relative, out var png))
                        Reply(net, 200, "image/png", png);
                    else Reply(net, 404, "text/plain", Array.Empty<byte>());
                    return;
                }
                if (method == "POST" && (relative == "api/send" || relative == "api/feedback" || relative == "api/artifact/edit"))
                {
                    int length = -1;
                    foreach (string line in lines.Skip(1))
                        if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase) &&
                            int.TryParse(line.Substring(15).Trim(), out int value)) length = value;
                    if (length < 1 || length > (relative == "api/artifact/edit" ? 80_000 : 12_000))
                    { Reply(net, 413, "application/json", Encoding.UTF8.GetBytes("{\"ok\":false}")); return; }
                    int contentOffset = headerEnd + 4;
                    while (data.Length - contentOffset < length && data.Length < 100_000)
                    {
                        int read = net.Read(chunk, 0, Math.Min(chunk.Length, length - (int)data.Length + contentOffset));
                        if (read <= 0) return;
                        data.Write(chunk, 0, read);
                    }
                    bytes = data.ToArray();
                    using JsonDocument json = JsonDocument.Parse(bytes.AsMemory(contentOffset, length));
                    if (relative == "api/feedback")
                    {
                        // The page MUST be served by this listener, not a cross-origin page.
                        string expectedOrigin = "Origin: http://" + expectedHost;
                        if (!lines.Any(line => line.Equals(expectedOrigin, StringComparison.OrdinalIgnoreCase)) ||
                            !RecordRichChatFeedback(json.RootElement))
                            Reply(net, 400, "application/json", Encoding.UTF8.GetBytes("{\"ok\":false}"));
                        else Reply(net, 202, "application/json", Encoding.UTF8.GetBytes("{\"ok\":true}"));
                        return;
                    }
                    if (relative == "api/artifact/edit")
                    {
                        string expectedOrigin = "Origin: http://" + expectedHost;
                        if (!lines.Any(line => line.Equals(expectedOrigin, StringComparison.OrdinalIgnoreCase)))
                        { Reply(net, 403, "application/json", Encoding.UTF8.GetBytes("{\"ok\":false}")); return; }
                        // The workspace editor backend is not implemented yet.
                        Reply(net, 501, "application/json; charset=utf-8",
                            Encoding.UTF8.GetBytes("{\"ok\":false,\"error\":\"artifact_edit_not_implemented\"}"));
                        return;
                    }
                    string message = json.RootElement.TryGetProperty("message", out var msg) && msg.ValueKind == JsonValueKind.String
                        ? msg.GetString()?.Trim() ?? "" : "";
                    if (message.Length == 0 || message.Length > 6000 || _richChatOutbox.Count >= 15)
                    { Reply(net, 400, "application/json", Encoding.UTF8.GetBytes("{\"ok\":false}")); return; }
                    _richChatOutbox.Enqueue(message);
                    Reply(net, 202, "application/json", Encoding.UTF8.GetBytes("{\"ok\":true}"));
                    return;
                }
                if (method != "GET") { Reply(net, 405, "text/plain", Array.Empty<byte>()); return; }
                string asset = relative.Length == 0 ? "index.html" : relative;
                if (!_richChatAssets.TryGetValue(asset, out var payload))
                { Reply(net, 404, "text/plain", Array.Empty<byte>()); return; }
                Reply(net, 200, payload.Mime, payload.Bytes);
            }
            catch (Exception) { /* Browser closed while requesting: do not disrupt Eris. */ }
        }
    }

    private static int FindHttpSeparator(byte[] bytes, int length)
    {
        for (int i = 0; i < length - 3; i++)
            if (bytes[i] == 13 && bytes[i + 1] == 10 && bytes[i + 2] == 13 && bytes[i + 3] == 10)
                return i;
        return -1;
    }

    private static void Reply(NetworkStream net, int status, string mime, byte[] payload)
    {
        string label = status switch { 200 => "OK", 202 => "Accepted", 409 => "Conflict", 400 => "Bad Request",
            403 => "Forbidden", 404 => "Not Found", 405 => "Method Not Allowed", 413 => "Payload Too Large",
            501 => "Not Implemented", _ => "Error" };
        string headers = $"HTTP/1.1 {status} {label}\r\nContent-Type: {mime}\r\nContent-Length: {payload.Length}\r\n" +
            "Connection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n" +
            "Referrer-Policy: no-referrer\r\nX-Frame-Options: DENY\r\n" +
            "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
            "font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'\r\n\r\n";
        byte[] prefix = Encoding.ASCII.GetBytes(headers);
        net.Write(prefix, 0, prefix.Length);
        net.Write(payload, 0, payload.Length);
    }

    private void UpdateRichChatSnapshot()
    {
        if (_richChatServer == null) return;
        // Main thread only. Snapshot is handed atomically to the HTTP reader thread.
        var visible = _conversationEntries.TakeLast(ConversationHistoryLimit).Select((entry, index) => new {
            id = index, role = entry.Role, text = entry.Text, date = entry.Date, time = entry.Time,
            turnId = entry.Role == "assistant" ? entry.TurnId : "",
        }).ToArray();
        var activeTurns = _conversationEntries.Where(e => e.Role == "assistant" && !string.IsNullOrEmpty(e.TurnId))
            .Select(e => e.TurnId).ToHashSet(StringComparer.Ordinal);
        var bundles = ReadRichChatBundles(activeTurns);
        // Read the existing stage/TTS authority: no independent browser-side guess
        // about which turn is speaking. A stale TTS completion never selects a
        // different transcript row. The page may remain open after Eris exits.
        bool speaking = _ttsAudioIsPlaying || _runtimePresence.Speaking;
        bool thinking = !speaking && (_runtimePresence.Thinking ||
            _conversationState is "thinking" or "preparing" or "buffering");
        string speechTurnId = !string.IsNullOrWhiteSpace(_ttsBodyAudioTurnId)
            ? _ttsBodyAudioTurnId : _runtimePresence.TurnId;
        string phase = speaking ? "speaking" : thinking ? "thinking" : "idle";
        string next = JsonSerializer.Serialize(new {
            messages = visible, bundles, status = _conversationStateLabel, online = true,
            speech = new { phase, turnId = speaking ? speechTurnId : "" },
        });
        Volatile.Write(ref _richChatSnapshot, next);
        _richChatLastSnapshotMs = Time.GetTicksMsec();
    }

    private void TickRichChatPortal()
    {
        if (_richChatServer == null) return;
        int processed = 0;
        while (processed++ < 5 && _richChatOutbox.TryDequeue(out string message))
            SendUserChatMessage(message);
        if (Time.GetTicksMsec() - _richChatLastSnapshotMs >= 500)
            UpdateRichChatSnapshot();
    }

    private void StopRichChatPortal()
    {
        try { _richChatCancellation?.Cancel(); } catch (ObjectDisposedException) { }
        try { _richChatServer?.Stop(); } catch (ObjectDisposedException) { }
        _richChatServer = null;
        _richChatCancellation?.Dispose();
        _richChatCancellation = null;
        _richChatUrl = "";
    }
}
