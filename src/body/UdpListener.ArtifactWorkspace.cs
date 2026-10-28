using Godot;
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

public partial class UdpListener
{
    // Bàn làm việc nhận artifact công cụ, không nhận lời thoại từ Writer/TTS.
    // Tất cả ảnh phải nằm trong thư mục artifact được cấu hình của Eris.
    private PanelContainer _artifactWorkspacePanel;
    private VBoxContainer _artifactWorkspaceRows;
    private Label _artifactWorkspaceTitle;
    private readonly HashSet<string> _artifactWorkspaceSeenJobs = new();

    private string ArtifactWorkspaceRoot()
    {
        string configured = System.Environment.GetEnvironmentVariable("ERIS_ARTIFACT_WORKSPACE") ?? "";
        if (string.IsNullOrWhiteSpace(configured))
            configured = Path.Combine(ProjectSettings.GlobalizePath("res://"), "logs", "eris_artifacts");
        return Path.GetFullPath(configured);
    }

    private void EnsureArtifactWorkspacePanel()
    {
        if (_artifactWorkspacePanel != null) return;
        var parent = GetNode<Control>("CanvasLayer/Control");
        _artifactWorkspacePanel = new PanelContainer
        {
            Name = "ErisArtifactWorkspace", Visible = false,
            Position = new Vector2(440, 75), Size = new Vector2(830, 690),
            CustomMinimumSize = new Vector2(580, 300), ZIndex = 1022,
            MouseFilter = Control.MouseFilterEnum.Stop,
        };
        var layout = new VBoxContainer();
        var header = new HBoxContainer();
        _artifactWorkspaceTitle = new Label
        {
            Text = "Bàn làm việc Eris", SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
        };
        var clear = new Button { Text = "Xóa hiển thị" };
        clear.Pressed += () =>
        {
            foreach (Node child in _artifactWorkspaceRows.GetChildren())
            { _artifactWorkspaceRows.RemoveChild(child); child.QueueFree(); }
            _artifactWorkspaceSeenJobs.Clear();
        };
        var hide = new Button { Text = "Ẩn" };
        hide.Pressed += () =>
        {
            _artifactWorkspacePanel.Visible = false;
            UpdateMousePassthrough();
        };
        header.AddChild(_artifactWorkspaceTitle);
        header.AddChild(clear);
        header.AddChild(hide);
        layout.AddChild(header);
        var scroll = new ScrollContainer { SizeFlagsVertical = Control.SizeFlags.ExpandFill,
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        _artifactWorkspaceRows = new VBoxContainer
        {
            SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
        };
        scroll.AddChild(_artifactWorkspaceRows);
        layout.AddChild(scroll);
        _artifactWorkspacePanel.AddChild(layout);
        parent.AddChild(_artifactWorkspacePanel);
        MakePanelDraggable(_artifactWorkspacePanel);
    }

    private static string ArtifactText(JsonElement item, string name, int limit = 3000)
    {
        if (!item.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
            return "";
        string result = value.GetString() ?? "";
        return result.Length > limit ? result.Substring(0, limit) : result;
    }

    private void AddArtifactLabel(VBoxContainer group, string text, bool monospace = false)
    {
        var label = new RichTextLabel
        {
            BbcodeEnabled = false, FitContent = true, ScrollActive = false,
            SelectionEnabled = true, SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
            CustomMinimumSize = new Vector2(0, monospace ? 50 : 26),
        };
        label.Text = text.Length > 6000 ? text.Substring(0, 6000) + "…" : text;
        group.AddChild(label);
    }

    private bool TryAddArtifactImage(VBoxContainer group, JsonElement item)
    {
        string relative = ArtifactText(item, "path", 256);
        string expectedHash = ArtifactText(item, "sha256", 64);
        if (relative.Length == 0 || expectedHash.Length != 64 ||
            relative.Contains('\\') || relative.StartsWith('/') || relative.Contains("..")) return false;
        string workspace = ArtifactWorkspaceRoot();
        string fullPath = Path.GetFullPath(Path.Combine(workspace, relative.Replace('/', Path.DirectorySeparatorChar)));
        string prefix = workspace.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!fullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return false;
        if (!File.Exists(fullPath)) return false;
        try
        {
            var info = new FileInfo(fullPath);
            if (info.Length > 3_000_000) return false;
            byte[] bytes = File.ReadAllBytes(fullPath);
            string actualHash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase)) return false;
            var picture = new Image();
            if (picture.LoadPngFromBuffer(bytes) != Error.Ok) return false;
            var texture = ImageTexture.CreateFromImage(picture);
            var imageView = new TextureRect
            {
                Texture = texture,
                ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
                StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
                CustomMinimumSize = new Vector2(700, Mathf.Clamp(picture.GetHeight(), 160, 480)),
                SizeFlagsHorizontal = Control.SizeFlags.ExpandFill,
                TooltipText = ArtifactText(item, "alt", 160),
            };
            group.AddChild(imageView);
            return true;
        }
        catch (Exception ex)
        {
            GD.PrintErr("[artifact] Không thể mở ảnh: " + ex.Message);
            return false;
        }
    }

    private void AppendArtifactJob(JsonElement doc)
    {
        string title = ArtifactText(doc, "title", 140);
        _artifactWorkspaceTitle.Text = "Bàn làm việc Eris · " + (title == "" ? "Artifact" : title);
        var group = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        group.AddChild(new HSeparator());
        group.AddChild(new Label { Text = "● " + (title == "" ? "Kết quả mới" : title) });
        if (doc.TryGetProperty("artifacts", out var artifacts) && artifacts.ValueKind == JsonValueKind.Array)
        {
            int count = 0;
            foreach (JsonElement artifact in artifacts.EnumerateArray())
            {
                if (++count > 30 || artifact.ValueKind != JsonValueKind.Object) break;
                string type = ArtifactText(artifact, "type", 30);
                if (type == "image")
                {
                    if (!TryAddArtifactImage(group, artifact)) AddArtifactLabel(group, "Không thể xác thực ảnh artifact.");
                }
                else if (type == "formula")
                {
                    AddArtifactLabel(group, "LaTeX: " + ArtifactText(artifact, "latex", 1200));
                }
                else if (type == "text" || type == "code")
                {
                    AddArtifactLabel(group, ArtifactText(artifact, "text", 6000), type == "code");
                }
                else if (type == "table")
                {
                    var lines = new List<string>();
                    if (artifact.TryGetProperty("headers", out var headers) && headers.ValueKind == JsonValueKind.Array)
                    {
                        var h = new List<string>();
                        foreach (var cell in headers.EnumerateArray()) h.Add(cell.ToString());
                        lines.Add(string.Join("    |    ", h));
                    }
                    if (artifact.TryGetProperty("rows", out var rows) && rows.ValueKind == JsonValueKind.Array)
                    {
                        foreach (var row in rows.EnumerateArray())
                        {
                            if (lines.Count > 18) break;
                            if (row.ValueKind != JsonValueKind.Array) continue;
                            var cells = new List<string>();
                            foreach (var cell in row.EnumerateArray()) cells.Add(cell.ToString());
                            lines.Add(string.Join("    |    ", cells));
                        }
                    }
                    AddArtifactLabel(group, string.Join("\n", lines), true);
                }
            }
        }
        _artifactWorkspaceRows.AddChild(group);
        while (_artifactWorkspaceRows.GetChildCount() > 12)
        {
            var old = _artifactWorkspaceRows.GetChild(0);
            _artifactWorkspaceRows.RemoveChild(old);
            old.QueueFree();
        }
    }

    private bool TryHandleWorkspaceArtifactPacket(string raw)
    {
        if (string.IsNullOrEmpty(raw) || !raw.Contains("workspace_artifact", StringComparison.Ordinal))
            return false;
        try
        {
            using var parsed = JsonDocument.Parse(raw);
            JsonElement root = parsed.RootElement;
            if (root.ValueKind != JsonValueKind.Object ||
                !root.TryGetProperty("parse_mode", out var parseMode) ||
                parseMode.GetString() != "workspace_artifact") return false;
            string jobId = ArtifactText(root, "job_id", 64);
            if (jobId.Length == 0 || _artifactWorkspaceSeenJobs.Contains(jobId)) return true;
            if (!root.TryGetProperty("workspace_version", out var version) || version.GetInt32() != 1)
                return true;
            EnsureArtifactWorkspacePanel();
            AppendArtifactJob(root);
            _artifactWorkspaceSeenJobs.Add(jobId);
            _artifactWorkspacePanel.Visible = true;
            UpdateMousePassthrough();
            return true;
        }
        catch (Exception ex)
        {
            GD.PrintErr("[artifact] Gói dữ liệu không hợp lệ: " + ex.Message);
            return true;
        }
    }
}
