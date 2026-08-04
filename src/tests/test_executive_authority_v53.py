from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_autonomous_pipeline_collects_before_claim_and_has_no_legacy_fallback():
    source = _source("runtime/ai_orchestrated/self_turn_pipeline.py")
    selection = source[source.index("# Collect-before-claim"):source.index("candidate_ms =", source.index("# Collect-before-claim"))]
    assert ".peek_due(" in selection
    assert ".claim_due(" not in selection
    assert "legacy candidate retained" not in source
    assert "selected_affordance_stale" in source


def test_semantic_marker_router_is_not_called_by_production_runtime():
    production = "\n".join(
        _source(path)
        for path in (
            "runtime/user_control_runtime.py",
            "actions/capability_runtime.py",
            "runtime/ai_orchestrated/orchestrator.py",
            "runtime/ai_orchestrated/self_turn_pipeline.py",
        )
    )
    assert ".route_chat(" not in production
    assert "action_router_unavailable" not in _source("actions/capability_runtime.py")


def test_semantic_marker_router_is_deleted_not_shadowed():
    assert not (ROOT / "actions/router.py").exists()
    exports = _source("actions/__init__.py")
    bootstrap = _source("runtime/coordinator_bootstrap.py")
    assert "ActionRouter" not in exports
    assert "action_router" not in bootstrap


def test_capability_contracts_have_typed_effects_and_no_language_markers():
    registry = _source("actions/capability_registry.py")
    tools = _source("runtime/ai_orchestrated/executive_tools.py")
    environment = _source("runtime/environment_capabilities.py")
    cognition = _source("runtime/internal_cognitive_capabilities.py")
    assert "example_phrases" not in registry
    assert "capability_surface_keywords" not in registry
    assert "render_capability_registry_prompt" not in registry
    assert "_ACTION_ALIASES" not in registry
    assert "effect: str" in registry
    assert "_EFFECT_BY_CAPABILITY" not in tools
    assert "resolve_intention" not in environment
    assert "resolve_intention" not in cognition


def test_deepseek_planners_cannot_select_capabilities():
    model_router = _source("runtime/ai_orchestrated/model_router.py")
    assert "capability authority reserved for Gemma Executive" in model_router
    assert "VALID_SYSTEM_ACTIONS" not in model_router
    assert 'data["tool_intent"] = ""' in model_router


def test_executive_uses_bounded_typed_capability_retrieval_not_registry_dump():
    source = _source("runtime/ai_orchestrated/executive_cortex.py")
    tools = _source("runtime/ai_orchestrated/executive_tools.py")
    assert "build_capability_index" in source
    assert "retrieve_executive_tools" in source
    assert "max_items=8" in source
    assert "example_phrases" not in tools
    assert "max_items: int = 64" not in tools


def test_generic_liveness_fallback_cannot_be_resurrected_by_old_flag():
    source = _source("runtime/ai_orchestrated/social_initiative.py")
    assert "legacy_social_fallback_enabled" not in source
    assert "legacy_social_fallback_enabled" not in _source("runtime/architecture_flags.py")
    assert "initiative_local_liveness" not in source
    assert "Generic liveness fallback was removed, not shadowed" in source


def test_llm_parser_accepts_only_exact_capability_ids() -> None:
    service = _source("llm/service.py")
    assert "_SYSTEM_ACTION_ALIASES" not in service
    assert "volume_up" not in service
    assert "raw_action in VALID_SYSTEM_ACTIONS" in service
