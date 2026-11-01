using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

public partial class UdpListener
{
    private Button _canvasSpeakingChip;
    private Label _canvasSpeakingLabel;
    private string _canvasSpeakingTurn = "", _canvasSpeakingNode = "", _canvasSpeakingSession = "", _canvasActiveBlock = "";
    private long _canvasSpeakingGeneration = -1, _canvasPlaybackSeq = -1;
    private int _canvasSpeakingSegment = -1;
    private bool _canvasAudioStarted;
    private JsonElement _canvasDeferredPlayback;
    private readonly HashSet<string> _canvasRetiredTurns = new();
    private readonly HashSet<string> _canvasRetiredStreams = new();
    private string _canvasPlaybackStream = "";
    private readonly Dictionary<string, PanelContainer> _canvasBlockControls = new();

    private void InitializeLearningCanvasPlaybackUi(VBoxContainer root)
    {
        _canvasSpeakingChip = CreateMemoryButton("", () => SelectLearningCanvasNode(_canvasSpeakingNode), primary: false);
        _canvasSpeakingChip.Visible = false;
        _canvasSpeakingChip.CustomMinimumSize = new Vector2(0, 48);
        root.AddChild(_canvasSpeakingChip);
        var margin = new MarginContainer { MouseFilter = Control.MouseFilterEnum.Ignore };
        margin.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        foreach (string side in new[] { "left", "right", "top", "bottom" }) margin.AddThemeConstantOverride("margin_" + side, 8);
        _canvasSpeakingChip.AddChild(margin);
        _canvasSpeakingLabel = CanvasLabel("", 12);
        margin.AddChild(_canvasSpeakingLabel);
        _canvasSpeakingLabel.Resized += () => _canvasSpeakingChip.CustomMinimumSize = new Vector2(0, Mathf.Max(48, _canvasSpeakingLabel.GetMinimumSize().Y + 16));
    }

    private void UpdateCanvasSpeakingChip()
    {
        if (_canvasSpeakingChip == null) return;
        _canvasSpeakingChip.Visible = _canvasSpeakingTurn != "" && _canvasSpeakingNode != _canvasSelectedNode;
        _canvasSpeakingLabel.Text = (_canvasAudioStarted ? "Eris đang nói về " : "Eris đang chuẩn bị nói về ")
            + CanvasNodeTitle(_canvasSpeakingNode) + " · Bấm để quay lại";
    }

    private bool ObserveCanvasPlaybackStream(string stream)
    {
        if (stream == "" || stream == _canvasPlaybackStream) return true;
        if (_canvasRetiredStreams.Contains(stream)) return false;
        if (_canvasPlaybackStream != "") _canvasRetiredStreams.Add(_canvasPlaybackStream);
        _canvasPlaybackStream = stream;
        _canvasPlaybackSeq = -1;
        _canvasSpeakingGeneration = -1;
        _canvasSpeakingTurn = _canvasSpeakingNode = _canvasActiveBlock = _canvasSpeakingSession = "";
        _canvasRetiredTurns.Clear();
        UpdateCanvasSpeakingChip();
        UpdateCanvasBlockHighlight();
        return true;
    }

    private void ApplyLearningCanvasPlayback(JsonElement packet)
    {
        if (packet.ValueKind != JsonValueKind.Object || !packet.TryGetProperty("seq", out var seqNode)) return;
        string stream = ReadJsonString(packet, "stream_id");
        // A state snapshot announces a new backend. Delayed audio alone cannot reset it.
        if (_canvasPlaybackStream != "" && stream != _canvasPlaybackStream) return;
        if (!ObserveCanvasPlaybackStream(stream)) return;
        long seq = seqNode.GetInt64();
        if (seq <= _canvasPlaybackSeq) return;
        string turn = ReadJsonString(packet, "turn_id"), node = ReadJsonString(packet, "node_id");
        if (turn == "" || _canvasRetiredTurns.Contains(turn)) return;
        if (!CanvasNodes().Any(n => ReadJsonString(n, "id") == node))
        {
            _canvasDeferredPlayback = packet.Clone();
            return;
        }
        string session = ReadJsonString(packet, "session_id"), kind = ReadJsonString(packet, "event_type");
        long generation = packet.GetProperty("generation").GetInt64();
        int segment = packet.GetProperty("segment_id").GetInt32();
        if (session == _canvasSpeakingSession && generation < _canvasSpeakingGeneration) return;
        if (kind is "queued" or "audio_start")
        {
            if (_canvasSpeakingTurn != turn)
            {
                if (_canvasSpeakingTurn != "") _canvasRetiredTurns.Add(_canvasSpeakingTurn);
                _canvasSpeakingTurn = turn;
                _canvasSpeakingNode = node;
                _canvasSpeakingSession = session;
                _canvasSpeakingGeneration = generation;
                _canvasSpeakingSegment = -1;
                _canvasActiveBlock = "";
                _canvasAudioStarted = false;
            }
            if (kind == "audio_start")
            {
                if (segment < _canvasSpeakingSegment) return;
                _canvasSpeakingSegment = segment;
                _canvasAudioStarted = true;
                _canvasActiveBlock = ReadJsonString(packet, "block_id");
            }
        }
        else
        {
            if (turn != _canvasSpeakingTurn || generation != _canvasSpeakingGeneration || segment < _canvasSpeakingSegment) return;
            _canvasActiveBlock = "";
            if (packet.TryGetProperty("final", out var final) && final.GetBoolean())
            {
                _canvasRetiredTurns.Add(turn);
                _canvasSpeakingTurn = _canvasSpeakingNode = "";
                _canvasAudioStarted = false;
            }
        }
        _canvasPlaybackSeq = seq;
        if (_canvasRetiredTurns.Count > 128) _canvasRetiredTurns.Remove(_canvasRetiredTurns.First());
        UpdateCanvasSpeakingChip();
        UpdateCanvasBlockHighlight();
    }

    private void UpdateCanvasBlockHighlight()
    {
        foreach (var pair in _canvasBlockControls)
        {
            bool active = _canvasSpeakingNode == _canvasSelectedNode && pair.Key == _canvasActiveBlock;
            pair.Value.AddThemeStyleboxOverride("panel", MakeFlatStyle(active ? new Color("fff0d9") : Colors.Transparent,
                active ? MemoryPink : Colors.Transparent, 10, active ? 2 : 0, 8));
        }
    }
}
