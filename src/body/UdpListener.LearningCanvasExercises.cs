using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;

public partial class UdpListener
{
    private readonly Dictionary<string, JsonElement> _canvasActivities = new();
    private readonly Dictionary<string, string> _canvasExerciseDrafts = new(), _canvasExerciseOptions = new();
    private ulong _canvasLastExercisePoll;
    private CodeEdit _canvasCodeEditor;

    private void ApplyLearningCanvasExercise(JsonElement activity)
    {
        if (activity.ValueKind != JsonValueKind.Object) return;
        string node = ReadJsonString(activity, "node_id");
        if (node == "") return;
        if (_canvasActivities.TryGetValue(node, out var previous))
        {
            double oldTime = previous.TryGetProperty("created_at", out var a) ? a.GetDouble() : 0;
            double newTime = activity.TryGetProperty("created_at", out var b) ? b.GetDouble() : 0;
            if (newTime < oldTime) return;
            string oldSubmission = ReadJsonString(previous, "submission_id"), newSubmission = ReadJsonString(activity, "submission_id");
            double oldSubmitted = previous.TryGetProperty("submitted_at", out var c) ? c.GetDouble() : 0;
            double newSubmitted = activity.TryGetProperty("submitted_at", out var d) ? d.GetDouble() : 0;
            bool sameActivity = ReadJsonString(previous, "activity_id") == ReadJsonString(activity, "activity_id");
            if (sameActivity && newSubmitted < oldSubmitted) return;
            if (sameActivity && oldSubmission != "" && oldSubmission == newSubmission && ReadJsonString(previous, "status") != "running"
                && ReadJsonString(activity, "status") == "running") return;
        }
        _canvasActivities[node] = activity.Clone();
    }

    private void CanvasExerciseAction(string action, JsonElement activity, string answer = "")
    {
        var extra = new Dictionary<string, object> { ["activity_id"] = ReadJsonString(activity, "activity_id"),
            ["nonce"] = ReadJsonString(activity, "nonce") };
        if (action == "submit")
        {
            bool java = ReadJsonString(activity, "type") == "java";
            if (java && (string.IsNullOrWhiteSpace(answer) || Encoding.UTF8.GetByteCount(answer) > 12000))
            {
                _canvasStatus.Text = "Nhập code Java, tối đa 12 KB, rồi chạy lại.";
                return;
            }
            extra[java ? "code" : "answer"] = answer;
            if (java) _canvasExerciseDrafts[ReadJsonString(activity, "activity_id")] = answer;
        }
        SendLearningCanvasRequest(action, extra: extra);
    }

    private Button CanvasExerciseButton(string text, Action action, bool enabled = true)
    {
        var button = CreateMemoryButton(text, action, primary: false);
        button.Disabled = !enabled || _canvasPendingRequest != null;
        button.SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;
        button.CustomMinimumSize = new Vector2(0, 36);
        return button;
    }

    private void RenderLearningCanvasExercises(JsonElement detail)
    {
        _canvasCodeEditor = null;
        _canvasDetail.AddChild(CanvasLabel("Luyện tập", 18));
        var choose = new HBoxContainer();
        _canvasDetail.AddChild(choose);
        foreach (var exercise in detail.GetProperty("exercises").EnumerateArray())
        {
            string exerciseId = ReadJsonString(exercise, "id");
            bool java = ReadJsonString(exercise, "type") == "java";
            choose.AddChild(CanvasExerciseButton(java ? "Viết Java" : "Trắc nghiệm", () =>
                SendLearningCanvasRequest("exercise", _canvasSelectedNode, extra: new Dictionary<string, object> { ["exercise_id"] = exerciseId })));
        }
        if (!_canvasActivities.TryGetValue(_canvasSelectedNode, out var activity))
        {
            _canvasDetail.AddChild(CanvasLabel("Chọn dạng bài để bắt đầu. Kết quả được lưu sau khi chấm.", 12, MemoryInkSoft));
            return;
        }
        string id = ReadJsonString(activity, "activity_id"), status = ReadJsonString(activity, "status");
        string notice = ReadJsonString(activity, "unavailable_notice");
        if (notice != "") _canvasDetail.AddChild(CanvasLabel("Java chưa khả dụng; đã chuyển sang trắc nghiệm. " + notice, 12, new Color("8a5a22")));
        bool running = status == "running", isJava = ReadJsonString(activity, "type") == "java";
        _canvasDetail.AddChild(CanvasLabel(ReadJsonString(activity, "prompt"), 14));
        if (isJava)
        {
            if (!_canvasExerciseDrafts.ContainsKey(id)) _canvasExerciseDrafts[id] = ReadJsonString(activity, "code");
            var editor = new CodeEdit { Text = _canvasExerciseDrafts[id], CustomMinimumSize = new Vector2(0, 260),
                SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, Editable = !running,
                WrapMode = TextEdit.LineWrappingMode.Boundary };
            editor.AddThemeFontOverride("font", new SystemFont { FontNames = new[] { "Consolas", "Cascadia Mono", "monospace" } });
            editor.AddThemeFontSizeOverride("font_size", 13);
            var codeSurface = MakeFlatStyle(new Color("f4f1f8"), ErisBorder, 10, 1, 10);
            editor.AddThemeStyleboxOverride("normal", codeSurface);
            editor.AddThemeStyleboxOverride("read_only", codeSurface);
            editor.AddThemeStyleboxOverride("focus", MakeFlatStyle(Colors.Transparent, MemoryPink, 10, 1, 0));
            editor.AddThemeColorOverride("font_color", MemoryInk);
            editor.AddThemeColorOverride("font_readonly_color", MemoryInkSoft);
            editor.AddThemeColorOverride("caret_color", MemoryPink);
            editor.AddThemeColorOverride("selection_color", new Color("f3bed8"));
            editor.TextChanged += () => _canvasExerciseDrafts[id] = editor.Text;
            _canvasCodeEditor = editor;
            _canvasDetail.AddChild(editor);
            _canvasDetail.AddChild(CanvasExerciseButton(running ? "Đang chạy trong Docker…" : "Chạy Java", () =>
                CanvasExerciseAction("submit", activity, editor.Text), !running && !string.IsNullOrWhiteSpace(editor.Text)));
        }
        else
        {
            foreach (var option in activity.GetProperty("options").EnumerateArray())
            {
                string key = ReadJsonString(option, "id");
                var button = CanvasExerciseButton(key.ToUpperInvariant() + ". " + ReadJsonString(option, "text"), () =>
                {
                    _canvasExerciseOptions[id] = key;
                    RenderLearningCanvasDetail();
                });
                button.Name = "CanvasOption_" + key;
                // Button text wraps through a child label instead of truncating the answer.
                button.Text = "";
                button.CustomMinimumSize = new Vector2(0, 70);
                var margin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
                margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
                foreach (string side in new[] { "left", "right", "top", "bottom" }) margin.AddThemeConstantOverride("margin_" + side, 10);
                button.AddChild(margin);
                var optionText = CanvasLabel(key.ToUpperInvariant() + ". " + ReadJsonString(option, "text"), 13);
                margin.AddChild(optionText);
                optionText.Resized += () => button.CustomMinimumSize = new Vector2(0, Mathf.Max(70, optionText.GetMinimumSize().Y + 20));
                if (_canvasExerciseOptions.GetValueOrDefault(id) == key) button.AddThemeStyleboxOverride("normal",
                    MakeFlatStyle(new Color("fce6f1"), MemoryPink, 10, 2, 0));
                _canvasDetail.AddChild(button);
            }
            _canvasDetail.AddChild(CanvasExerciseButton("Nộp đáp án", () =>
                CanvasExerciseAction("submit", activity, _canvasExerciseOptions.GetValueOrDefault(id, "")),
                _canvasExerciseOptions.ContainsKey(id)));
        }
        var helpRow = new HBoxContainer();
        _canvasDetail.AddChild(helpRow);
        helpRow.AddChild(CanvasExerciseButton("Gợi ý", () => CanvasExerciseAction("hint", activity), !running));
        helpRow.AddChild(CanvasExerciseButton("Xem lời giải", () => CanvasExerciseAction("reveal", activity), !running));
        string assistance = ReadJsonString(activity, "assistance");
        _canvasDetail.AddChild(CanvasLabel(assistance == "independent" ? "Tự làm" : assistance == "hinted"
            ? "Đã dùng gợi ý · Kết quả được ghi kèm trợ giúp" : "Đã xem lời giải · Kết quả được ghi kèm trợ giúp", 11, MemoryInkSoft));
        string help = ReadJsonString(activity, "help");
        if (help != "") _canvasDetail.AddChild(CanvasLabel(help, 13));
        if (status == "completed")
        {
            string result = ReadJsonString(activity, "result");
            _canvasDetail.AddChild(CanvasLabel(result == "correct" ? "Đúng · Đã lưu kết quả" : result == "partial"
                ? "Đúng một phần · Đã lưu kết quả" : "Chưa đúng · Đã lưu kết quả", 15));
            if (activity.TryGetProperty("tests", out var tests))
                foreach (var test in tests.EnumerateArray())
                    _canvasDetail.AddChild(CanvasLabel((test.GetProperty("passed").GetBoolean() ? "✓ " : "× ") + ReadJsonString(test, "description"), 13));
            string reason = ReadJsonString(activity, "reason"), diagnostic = ReadJsonString(activity, "diagnostic");
            if (reason is "compile_error" or "runtime_error" or "timeout" or "output_limit" or "resource_limit")
                _canvasDetail.AddChild(CanvasLabel((reason switch { "compile_error" => "Lỗi biên dịch", "runtime_error" => "Lỗi khi chạy",
                    "timeout" => "Chạy quá thời gian cho phép", "resource_limit" => "Chạy vượt giới hạn tài nguyên", _ => "Đầu ra vượt giới hạn" })
                    + (diagnostic == "" ? "" : "\n" + diagnostic), 12, MemoryInkSoft));
        }
        else if (status == "unavailable")
        {
            _canvasDetail.AddChild(CanvasLabel("Java chưa khả dụng. " + ReadJsonString(activity, "guidance") +
                "\nBạn có thể chọn Trắc nghiệm ở phía trên.", 13, new Color("8a5a22")));
        }
    }

    private void TickLearningCanvasExercise()
    {
        if (_learningCanvasPanel?.Visible != true || _canvasPendingRequest != null
            || Time.GetTicksMsec() - _canvasLastExercisePoll < 600) return;
        if (!_canvasActivities.TryGetValue(_canvasSelectedNode, out var activity) || ReadJsonString(activity, "status") != "running") return;
        _canvasLastExercisePoll = Time.GetTicksMsec();
        CanvasExerciseAction("exercise_status", activity);
    }
}
