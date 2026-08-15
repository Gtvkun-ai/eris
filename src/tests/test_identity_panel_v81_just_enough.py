from __future__ import annotations

from pathlib import Path


def _body() -> str:
    return (Path(__file__).parents[1] / "body" / "UdpListener.DepthPanel.cs").read_text(encoding="utf-8")


def test_v83_identity_is_one_panel_with_self_trace_tabs() -> None:
    text = _body()
    assert 'AddDepthTab(tabs, "self", "SELF"' in text
    assert 'AddDepthTab(tabs, "inner", "INNER//"' not in text
    assert 'AddDepthTab(tabs, "trace", "TRACE•"' in text
    assert 'ERIS / IDENTITY_01' in text
    assert 'GEMMA // OBSERVER' in text
    assert 'private const string IdentityAssetRoot = "res://asset/identy/";' in text
    assert 'RenderIdentityInnerV82' not in text


def test_v83_normal_identity_ui_avoids_metric_bar_dashboard() -> None:
    text = _body()
    self_tab = text[text.index("private void RenderIdentitySelfV82") : text.index("private void RenderIdentityTraceV82")]
    trace_tab = text[text.index("private void RenderIdentityTraceV82") : text.index("private PanelContainer NewIdentityDossierSheet")]
    assert "AddMetricBar" not in self_tab
    assert "AddMetricBar" not in trace_tab
    assert '"DESIRE"' in self_tab
    assert '"TENSION"' in self_tab
    assert '"CORE"' in self_tab
    assert '"THEN"' in trace_tab
    assert '"NOW"' in trace_tab


def test_v83_identity_uses_gemma_observer_without_extra_identity_model_lane() -> None:
    text = _body()
    assert "ReadGemmaObserverCommentV82" in text
    assert "observer_comment" in text
    adapter = (Path(__file__).parents[1] / "runtime" / "private_mind_model_adapter.py").read_text(encoding="utf-8")
    assert 'observer_comment' in adapter
    assert 'write_thought_shards' in adapter
