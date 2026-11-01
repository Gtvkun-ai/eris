using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

// Native renderer and actual request/ack handling; fixtures and persistence are RAM only.
public partial class LearningCanvasPreview : UdpListener
{
    public override async void _Ready()
    {
        try
        {
            InitializeLearningCanvasPreview();
            if (OS.GetCmdlineUserArgs().Contains("--verify"))
            {
                await VerifyLearningCanvasPreview();
                GetTree().Quit();
            }
        }
        catch (Exception ex) { GD.PrintErr(ex); GetTree().Quit(1); }
    }

    public override void _Process(double delta) => TickLearningCanvasPreview();
    public override void _Input(InputEvent input) => LearningCanvasPreviewInput(input);
    public override void _UnhandledInput(InputEvent input) { }
    public override void _ExitTree() { }
}

public partial class UdpListener
{
    private JsonObject _canvasPreviewState;
    private JsonArray _canvasPreviewDetails;
    private readonly Queue<Dictionary<string, object>> _canvasPreviewRequests = new();
    private readonly List<string> _canvasPreviewActions = new();
    private bool _canvasPreviewHold;
    private JsonArray _canvasPreviewExerciseDefinitions;
    private readonly Dictionary<string, JsonObject> _canvasPreviewActivities = new();
    private readonly Dictionary<string, string> _canvasPreviewLatest = new();
    private string _canvasPreviewJavaJob = "";
    private int _canvasPreviewJavaFrames;
    private bool _canvasPreviewJavaUnavailable;

    protected void InitializeLearningCanvasPreview()
    {
        _canvasPreview = true;
        EnableDesktopOverlayWindow = EnableMousePassthrough = false;
        GetViewport().TransparentBg = false;
        DisplayServer.WindowSetFlag(DisplayServer.WindowFlags.Transparent, false);
        DisplayServer.WindowSetFlag(DisplayServer.WindowFlags.Borderless, false);
        GetWindow().Title = "Eris · Learning Canvas · Dữ liệu minh họa";
        var layer = new CanvasLayer { Name = "CanvasLayer" };
        AddChild(layer);
        var control = new Control { Name = "Control", MouseFilter = Control.MouseFilterEnum.Ignore };
        control.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        layer.AddChild(control);
        var fixture = JsonNode.Parse(FileAccess.GetFileAsString("res://tools/ui-preview/learning_canvas_fixture.json"));
        _canvasPreviewState = (JsonObject)fixture["snapshot"].DeepClone();
        _canvasPreviewDetails = (JsonArray)fixture["details"].DeepClone();
        _canvasPreviewExerciseDefinitions = (JsonArray)fixture["exercise_previews"].DeepClone();
        if (OS.GetCmdlineUserArgs().Contains("--empty")) _canvasPreviewState["nodes"] = new JsonArray();
        _canvasPreviewSend = request => _canvasPreviewRequests.Enqueue(request);
        InitializeLearningCanvas();
        ShowLearningCanvas();
    }

    protected void TickLearningCanvasPreview()
    {
        if (!_canvasPreviewHold && _canvasPreviewRequests.Count > 0) DeliverLearningCanvasPreviewRequest();
        if (!_canvasPreviewHold && _canvasPreviewJavaJob != "" && --_canvasPreviewJavaFrames <= 0) FinishLearningCanvasPreviewJava();
        TickLearningCanvas();
    }

    protected void LearningCanvasPreviewInput(InputEvent input)
    {
        if (input is InputEventKey { Pressed: true, Keycode: Key.Escape }) CloseLearningCanvas();
    }

    private void DeliverLearningCanvasPreviewRequest()
    {
        var request = _canvasPreviewRequests.Dequeue();
        string action = (string)request["action"];
        _canvasPreviewActions.Add(action);
        var focus = _canvasPreviewState["focus"];
        string status = "ok";
        if (action != "open" && (long)request["base_revision"] != focus["revision"].GetValue<long>()) status = "conflict";
        else if (action == "navigate")
        {
            string proposed = focus["suggested_node_id"]?.GetValue<string>() ?? "";
            string proposedCause = focus["suggested_cause_id"]?.GetValue<string>() ?? "";
            bool acceptedSuggestion = (string)request["node_id"] == proposed && proposedCause != "";
            focus["node_id"] = (string)request["node_id"];
            focus["set_by"] = acceptedSuggestion ? "eris" : "user";
            focus["pinned"] = !acceptedSuggestion;
            focus["cause_id"] = acceptedSuggestion ? proposedCause : "";
            if (acceptedSuggestion) { focus["suggested_node_id"] = ""; focus["suggested_cause_id"] = ""; }
            focus["revision"] = focus["revision"].GetValue<long>() + 1;
        }
        else if (action == "ack_eris_focus")
        {
            if (!request.TryGetValue("cause_id", out var cause) || (string)cause != focus["cause_id"].GetValue<string>())
                throw new InvalidOperationException("Eris focus must acknowledge the original cause.");
            focus["acknowledged_cause_id"] = (string)cause;
            focus["revision"] = focus["revision"].GetValue<long>() + 1;
        }
        JsonObject exerciseUpdate = null;
        if (status == "ok" && action == "exercise")
        {
            var definition = _canvasPreviewExerciseDefinitions.First(n => n["exercise_id"].GetValue<string>() == (string)request["exercise_id"]);
            var activity = (JsonObject)definition.DeepClone();
            string id = "preview-activity-" + Guid.NewGuid().ToString("N");
            activity["activity_id"] = id;
            activity["created_at"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            _canvasPreviewActivities[id] = activity;
            _canvasPreviewLatest[activity["node_id"].GetValue<string>()] = id;
            exerciseUpdate = activity;
        }
        else if (status == "ok" && action is "submit" or "hint" or "reveal" or "exercise_status")
        {
            var activity = _canvasPreviewActivities[(string)request["activity_id"]];
            if (action is "hint" or "reveal")
            {
                if (activity["assistance"].GetValue<string>() != "answer_revealed")
                    activity["assistance"] = action == "hint" ? "hinted" : "answer_revealed";
                activity["help"] = action == "hint" ? "Gợi ý minh họa: chọn cộng tác viên tại thời điểm khởi tạo."
                    : "Lời giải minh họa: truyền PaymentGateway từ bên ngoài vào constructor.";
            }
            else if (action == "submit")
            {
                activity["submission_id"] = (string)request["request_id"];
                activity["submitted_at"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                if (activity["type"].GetValue<string>() == "java")
                {
                    activity["code"] = (string)request["code"];
                    activity["status"] = "running";
                    _canvasPreviewJavaJob = (string)request["activity_id"];
                    _canvasPreviewJavaFrames = 20;
                }
                else
                {
                    // RAM preview only. Actual grading is exercised by Python ledger tests.
                    activity["status"] = "completed";
                    activity["result"] = (string)request["answer"] == "a" ? "correct" : "incorrect";
                }
            }
            exerciseUpdate = activity;
        }
        var snapshot = (JsonObject)_canvasPreviewState.DeepClone();
        if (snapshot["nodes"].AsArray().Count > 0)
        {
            string selected = focus["node_id"].GetValue<string>();
            snapshot["detail"] = _canvasPreviewDetails.First(n => n["id"].GetValue<string>() == selected).DeepClone();
            if (_canvasPreviewLatest.TryGetValue(selected, out var latest)) snapshot["activity"] = _canvasPreviewActivities[latest].DeepClone();
        }
        TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_ack", status,
            request_id = (string)request["request_id"], learning_canvas = snapshot, exercise_update = exerciseUpdate }));
    }

    private void FinishLearningCanvasPreviewJava()
    {
        var activity = _canvasPreviewActivities[_canvasPreviewJavaJob];
        activity["status"] = _canvasPreviewJavaUnavailable ? "unavailable" : "completed";
        if (_canvasPreviewJavaUnavailable) activity["guidance"] = "Khởi động Docker Desktop và tải image JDK.";
        else
        {
            activity["result"] = "partial";
            activity["tests"] = JsonNode.Parse("[{\"id\":\"delegates\",\"description\":\"Chuyển đúng amount tới gateway\",\"passed\":true},{\"id\":\"null_guard\",\"description\":\"Constructor từ chối null\",\"passed\":false}]");
        }
        _canvasPreviewJavaJob = "";
        var snapshot = (JsonObject)_canvasPreviewState.DeepClone();
        if (_canvasPreviewJavaUnavailable)
        {
            var fallback = (JsonObject)_canvasPreviewExerciseDefinitions.First(n => n["exercise_id"].GetValue<string>() == "di.constructor.choice").DeepClone();
            string id = "preview-fallback-" + Guid.NewGuid().ToString("N");
            fallback["activity_id"] = id;
            fallback["created_at"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 + .001;
            fallback["unavailable_notice"] = activity["guidance"].DeepClone();
            _canvasPreviewActivities[id] = fallback;
            _canvasPreviewLatest["javadi:v1:constructor"] = id;
            snapshot["activity"] = fallback.DeepClone();
        }
        TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_state", status = "ok",
            learning_canvas = snapshot, exercise_update = activity }));
    }

    protected async Task VerifyLearningCanvasPreview()
    {
        void Check(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
            GD.Print("PASS: " + message);
        }
        async Task Settle()
        {
            for (int i = 0; i < 6; i++) await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
        }
        await Settle();
        bool empty = OS.GetCmdlineUserArgs().Contains("--empty");
        Check(_canvasNodeButtons.Count == (empty ? 0 : 5), "Backend snapshot drives the native map / empty state");
        string directory = ProjectSettings.GlobalizePath("res://scratch/ui-qa/learning-canvas");
        System.IO.Directory.CreateDirectory(directory);
        foreach (var size in new[] { new Vector2I(1440, 900), new Vector2I(1000, 760), new Vector2I(720, 760), new Vector2I(480, 760), new Vector2I(360, 640) })
        {
            GetWindow().Size = size;
            _canvasShowMap = true;
            UpdateLearningCanvasLayout();
            await Settle();
            UpdateLearningCanvasLayout();
            await Settle();
            var panel = _learningCanvasPanel.GetGlobalRect();
            Check(panel.Size.X <= size.X && panel.Size.Y <= size.Y, $"Panel fits {size}");
            Check(panel.Encloses(_canvasStatus.GetGlobalRect()), $"Status contained at {size}");
            Check(_canvasMapScroll.GlobalPosition.Y - panel.Position.Y < 180, $"Compact heading leaves room for content at {size}");
            Check(_canvasMapScroll.Visible && panel.Encloses(_canvasMapScroll.GetGlobalRect()), $"Map accessible at {size}");
            foreach (var button in _canvasNodeButtons.Values)
                Check(button.Size.X > 100 && button.Size.X <= _canvasMapScroll.Size.X, $"Node has readable width at {size}");
            await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
            GetViewport().GetTexture().GetImage().SavePng($"{directory}/{(empty ? "empty" : "map")}-{size.X}.png");
            if (!empty)
            {
                SelectLearningCanvasNode("javadi:v1:constructor");
                await Settle();
                Check(_canvasSelectedNode == "javadi:v1:constructor" && _canvasDetailCache.ContainsKey(_canvasSelectedNode), "Constructor content is fetched and selected");
                Check(_canvasDetail.FindChildren("*", "RichTextLabel", true, false).OfType<RichTextLabel>().Any(c => c.Text.Contains("OrderService(PaymentGateway")), "Read-only Java code comes from the actual pack");
                var code = _canvasDetail.FindChildren("*", "RichTextLabel", true, false).OfType<RichTextLabel>().First();
                Check(code.Size.X <= _canvasDetailScroll.Size.X && code.SelectionEnabled && !code.BbcodeEnabled,
                    $"Literal Java remains selectable and contained at {size}");
                Check(panel.Encloses(_canvasDetailScroll.GetGlobalRect()) && _canvasDetailScroll.Visible, $"Reading accessible at {size}");
                if (_canvasNarrow) Check(!_canvasMapScroll.Visible, "Narrow view switches between map and reading");
                await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
                GetViewport().GetTexture().GetImage().SavePng($"{directory}/reading-{size.X}.png");
                if (_canvasNarrow)
                {
                    _canvasDetailScroll.ScrollVertical = (int)(code.GlobalPosition.Y - _canvasDetail.GlobalPosition.Y);
                    await Settle();
                    await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
                    GetViewport().GetTexture().GetImage().SavePng($"{directory}/code-{size.X}.png");
                }
            }
        }
        if (!empty)
        {
            _canvasPreviewHold = true;
            SelectLearningCanvasNode("javadi:v1:testing");
            SelectLearningCanvasNode("javadi:v1:composition-root");
            SelectLearningCanvasNode("javadi:v1:setter-field");
            Check(_canvasSelectedNode == "javadi:v1:setter-field", "Rapid clicks update focus before ack");
            Check(_canvasPreviewRequests.Count == 1, "Only one navigate is in flight");
            DeliverLearningCanvasPreviewRequest();
            Check(_canvasSelectedNode == "javadi:v1:setter-field", "Earlier ack never pulls focus back");
            Check(_canvasPreviewRequests.Count == 1 && (string)_canvasPreviewRequests.Peek()["node_id"] == "javadi:v1:setter-field", "Latest click is coalesced after ack");
            DeliverLearningCanvasPreviewRequest();
            Check(_canvasDesiredNode == "" && _canvasPinLabel.Text.Contains("ghim"), "Final navigation is acknowledged and pinned");

            // Simulate a competing revision, then verify authoritative retry.
            SelectLearningCanvasNode("javadi:v1:testing");
            var focus = _canvasPreviewState["focus"];
            focus["revision"] = focus["revision"].GetValue<long>() + 1;
            DeliverLearningCanvasPreviewRequest();
            Check(_canvasDesiredNode == "javadi:v1:testing" && _canvasPreviewRequests.Count == 1, "Conflict preserves intent and retries with current revision");
            DeliverLearningCanvasPreviewRequest();

            focus["node_id"] = "javadi:v1:constructor";
            focus["set_by"] = "eris";
            focus["pinned"] = false;
            focus["cause_id"] = "preview-eris-focus";
            focus["revision"] = focus["revision"].GetValue<long>() + 1;
            int navigations = _canvasPreviewActions.Count(a => a == "navigate");
            TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_state", status = "ok", learning_canvas = _canvasPreviewState }));
            DeliverLearningCanvasPreviewRequest();
            Check(_canvasSelectedNode == "javadi:v1:constructor" && _canvasPreviewActions.Last() == "ack_eris_focus"
                && _canvasPreviewActions.Count(a => a == "navigate") == navigations, "Eris state acknowledges cause without navigation echo");

            // Ignore an obsolete UDP ack; a lost request times out without inventing saved focus.
            TryHandleLearningCanvasPacket("{\"type\":\"learning_canvas_ack\",\"request_id\":\"obsolete\",\"status\":\"ok\"}");
            SelectLearningCanvasNode("javadi:v1:dependency");
            _canvasSendCount = 3;
            _canvasSentAt = Time.GetTicksMsec() - 1000;
            TickLearningCanvas();
            _canvasPreviewRequests.Clear();
            Check(_canvasPendingRequest == null && _canvasSelectedNode == "javadi:v1:constructor", "Lost ack restores last confirmed focus and offers refresh");
            SelectLearningCanvasNode("javadi:v1:dependency");
            string unavailableId = (string)_canvasPendingRequest["request_id"];
            TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_ack", status = "unavailable",
                request_id = unavailableId, message = "Learning Canvas chưa sẵn sàng." }));
            _canvasPreviewRequests.Clear();
            Check(_canvasPendingRequest == null && _canvasDesiredNode == "" && _canvasSelectedNode == "javadi:v1:constructor",
                "Unavailable backend restores confirmed selection");
            _canvasPreviewHold = false;
            CloseLearningCanvas();
            ShowLearningCanvas();
            await Settle();
            Check(_canvasSelectedNode == "javadi:v1:constructor", "Closing and reopening reloads the durable backend cursor");
            await VerifyLearningCanvasExercisesPreview(directory, Check, Settle);
            await VerifyLearningCanvasPlaybackPreview(directory, Check, Settle);
        }
        GD.Print(empty ? "ALL EMPTY LEARNING CANVAS CHECKS PASSED" : "ALL LEARNING CANVAS CHECKS PASSED");
    }

    private async Task VerifyLearningCanvasExercisesPreview(string directory, Action<bool, string> check, Func<Task> settle)
    {
        Button FindButton(string text) => _canvasDetail.FindChildren("*", "Button", true, false).OfType<Button>().First(b => b.Text == text);
        void Press(string text) => FindButton(text).EmitSignal(Button.SignalName.Pressed);
        Press("Trắc nghiệm");
        await settle();
        var activity = _canvasActivities["javadi:v1:constructor"];
        check(activity.GetProperty("options").GetArrayLength() == 3, "Native choices use server activity options and nonce");
        Press("Gợi ý");
        await settle();
        activity = _canvasActivities["javadi:v1:constructor"];
        check(ReadJsonString(activity, "assistance") == "hinted" && ReadJsonString(activity, "help") != "", "Hint is shown with persisted assistance label");
        _canvasDetail.FindChildren("CanvasOption_a", "Button", true, false).OfType<Button>().First().EmitSignal(Button.SignalName.Pressed);
        Press("Nộp đáp án");
        await settle();
        activity = _canvasActivities["javadi:v1:constructor"];
        check(ReadJsonString(activity, "result") == "correct" && ReadJsonString(activity, "assistance") == "hinted", "Quiz result preserves assisted status");
        Press("Xem lời giải");
        await settle();
        check(ReadJsonString(_canvasActivities["javadi:v1:constructor"], "assistance") == "answer_revealed", "Reveal cannot count as independent work");
        _canvasDetailScroll.ScrollVertical = 100000;
        await settle();
        await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
        GetViewport().GetTexture().GetImage().SavePng(directory + "/quiz-result-360.png");

        Press("Viết Java");
        await settle();
        check(_canvasCodeEditor != null && _canvasCodeEditor.Editable, "Java uses a native editable CodeEdit");
        _canvasCodeEditor.Text = "class OrderService {\n    // Bản nháp minh họa\n}";
        string draft = _canvasCodeEditor.Text;
        _canvasPreviewHold = true;
        Press("Chạy Java");
        DeliverLearningCanvasPreviewRequest();
        check(ReadJsonString(_canvasActivities["javadi:v1:constructor"], "status") == "running", "Java submit immediately shows running status");
        check(_canvasCodeEditor.Text == draft, "Queued Java preserves the submitted draft");
        FinishLearningCanvasPreviewJava();
        await settle();
        activity = _canvasActivities["javadi:v1:constructor"];
        check(ReadJsonString(activity, "result") == "partial" && activity.GetProperty("tests").GetArrayLength() == 2, "Per-test Java receipt renders partial result");
        check(_canvasCodeEditor.Size.X <= _canvasDetailScroll.Size.X, "Java editor fits narrow reading pane");
        _canvasDetailScroll.ScrollVertical = (int)_canvasCodeEditor.Position.Y;
        await settle();
        await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
        GetViewport().GetTexture().GetImage().SavePng(directory + "/java-editor-360.png");
        _canvasPreviewJavaUnavailable = true;
        Press("Chạy Java");
        DeliverLearningCanvasPreviewRequest();
        FinishLearningCanvasPreviewJava();
        await settle();
        check(ReadJsonString(_canvasActivities["javadi:v1:constructor"], "type") == "multiple_choice"
            && ReadJsonString(_canvasActivities["javadi:v1:constructor"], "unavailable_notice") != "" && !FindButton("Trắc nghiệm").Disabled,
            "Docker unavailable automatically switches to quiz with guidance");
        _canvasPreviewHold = false;
        CloseLearningCanvas();
        TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_state", status = "ok",
            open_panel = true, learning_canvas = _canvasPreviewState }));
        check(_learningCanvasPanel.Visible && _canvasPreviewRequests.Count == 0, "Root state opens native Canvas without navigate echo");
        GD.Print("ALL LEARNING CANVAS EXERCISE UI CHECKS PASSED (RAM fixture; not a Docker execution)");
    }

    private async Task VerifyLearningCanvasPlaybackPreview(string directory, Action<bool, string> check, Func<Task> settle)
    {
        const string a = "javadi:v1:constructor", b = "javadi:v1:testing";
        _canvasPreviewHold = true;
        string stream = _canvasPlaybackStream == "" ? "preview-playback" : _canvasPlaybackStream;
        void Playback(string turn, string node, string kind, int segment, string block, long seq, long generation = 20, bool final = false, string overrideStream = null)
        {
            TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = kind == "queued" ? "canvas_playback" : "canvas_highlight",
                stream_id = overrideStream ?? stream, session_id = "preview", turn_id = turn, node_id = node,
                event_type = kind, segment_id = segment, block_id = block, seq, generation, final }));
        }
        SelectLearningCanvasNode(a);
        DeliverLearningCanvasPreviewRequest();
        Playback("A", a, "queued", 0, "", 1000);
        check(_canvasActiveBlock == "", "Queued speech never highlights a block");
        Playback("A", a, "audio_start", 0, "di.constructor.meaning", 1001);
        check(_canvasActiveBlock == "di.constructor.meaning", "Actual segment start selects its authored block");
        check(((StyleBoxFlat)_canvasBlockControls[_canvasActiveBlock].GetThemeStylebox("panel")).BorderWidthLeft == 2, "Active block is visibly highlighted");
        SelectLearningCanvasNode(b);
        DeliverLearningCanvasPreviewRequest();
        await settle();
        check(_canvasSelectedNode == b && _canvasSpeakingChip.Visible && _canvasSpeakingLabel.Text.Contains("Constructor"), "Changing node keeps current speech in a return chip");
        await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
        GetViewport().GetTexture().GetImage().SavePng(directory + "/speaking-other-360.png");
        Playback("A", a, "audio_start", 1, "di.constructor.java", 1002);
        check(_canvasSelectedNode == b, "Audio highlight never pulls the reading focus back");
        _canvasSpeakingChip.EmitSignal(Button.SignalName.Pressed);
        DeliverLearningCanvasPreviewRequest();
        await settle();
        check(_canvasSelectedNode == a && _canvasActiveBlock == "di.constructor.java", "Return chip navigates only when clicked");
        _canvasDetailScroll.ScrollVertical = (int)(_canvasBlockControls[_canvasActiveBlock].GlobalPosition.Y - _canvasDetail.GlobalPosition.Y);
        await settle();
        await ToSignal(RenderingServer.Singleton, RenderingServer.SignalName.FramePostDraw);
        GetViewport().GetTexture().GetImage().SavePng(directory + "/highlight-360.png");
        Playback("A", a, "audio_done", 1, "", 1003, final: true);
        check(_canvasActiveBlock == "" && !_canvasSpeakingChip.Visible, "Terminal audio clears highlight and return chip");
        Playback("B", b, "queued", 0, "", 1004, generation: 21);
        Playback("B", b, "audio_start", 0, "di.testing.meaning", 1005, generation: 21);
        Playback("A", a, "audio_start", 0, "di.constructor.meaning", 1006);
        check(_canvasSpeakingTurn == "B" && _canvasActiveBlock == "di.testing.meaning", "An old turn/generation cannot replace current highlight");
        Playback("B", b, "audio_failed", 0, "", 1007, generation: 21, final: true);
        check(_canvasActiveBlock == "", "Audio failure clears the highlight");

        var focus = _canvasPreviewState["focus"];
        focus["suggested_node_id"] = b;
        focus["suggested_cause_id"] = "preview-suggestion:B";
        focus["revision"] = focus["revision"].GetValue<long>() + 1;
        TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_state", status = "ok", learning_canvas = _canvasPreviewState }));
        check(_canvasSelectedNode == a && _canvasNodeButtons[b].FindChildren("*", "Label", true, false).OfType<Label>().Any(l => l.Text.Contains("Eris gợi ý")), "Pinned focus shows a suggestion badge without moving");
        SelectLearningCanvasNode(b);
        DeliverLearningCanvasPreviewRequest();
        check(_canvasPinLabel.Text == "Theo Eris" && !focus["pinned"].GetValue<bool>(), "Clicking the proposed node accepts it and releases the pin");
        _canvasPreviewState["playback_stream_id"] = "restarted-preview";
        TryHandleLearningCanvasPacket(JsonSerializer.Serialize(new { type = "learning_canvas_state", status = "ok", learning_canvas = _canvasPreviewState }));
        Playback("new-stream", b, "queued", 0, "", 1, generation: 0, overrideStream: "restarted-preview");
        Playback("B", b, "audio_start", 0, "di.testing.meaning", 9000, generation: 21);
        check(_canvasSpeakingTurn == "new-stream" && _canvasActiveBlock == "", "Backend restart resets sequence and rejects packets from the retired stream");
        _canvasPreviewHold = false;
        GD.Print("ALL LEARNING CANVAS PLAYBACK/FOCUS UI CHECKS PASSED (synthetic lifecycle events)");
    }
}
