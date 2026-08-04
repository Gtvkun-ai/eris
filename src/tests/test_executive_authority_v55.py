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


def test_runtime_scheduler_obeys_executive_policy_instead_of_soft_silence_probe():
    source = _source("runtime/ai_orchestrated/self_turn_pipeline.py")
    gate = source[source.index("def _should_deliberate"):source.index("# V18 không còn planner")]
    assert "should_reconsider" in gate
    assert "ERIS_SOCIAL_INITIATIVE_SOFT_SILENCE_SEC" not in gate
    assert "ERIS_SOCIAL_INITIATIVE_PROBE_INTERVAL_SEC" not in gate
    assert "presence_probe" not in gate


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
    assert "resolve_intention" not in environment
    assert "resolve_intention" not in cognition
    assert "capability_input_schema" in tools


def test_deepseek_planners_cannot_select_capabilities():
    model_router = _source("runtime/ai_orchestrated/model_router.py")
    assert "capability authority reserved for Gemma Executive" in model_router
    assert "VALID_SYSTEM_ACTIONS" not in model_router
    assert 'data["tool_intent"] = ""' in model_router


def test_executive_uses_model_owned_shortlisting_not_registry_order_top_n():
    source = _source("runtime/ai_orchestrated/executive_cortex.py")
    tools = _source("runtime/ai_orchestrated/executive_tools.py")
    assert "capability_shortlist" in source
    assert "shortlist_capabilities" in source
    assert "filter_executive_tools" in source
    assert "select_tools_by_id" in source
    assert "max_items=8" not in source
    assert "selected[:" not in tools
    assert "capability_candidates" in source


def test_capability_arguments_are_typed_and_validated_before_legacy_adapter():
    cortex = _source("runtime/ai_orchestrated/executive_cortex.py")
    registry = _source("actions/capability_registry.py")
    orchestrator = _source("runtime/ai_orchestrated/orchestrator.py")
    assert "capability_arguments" in cortex
    assert "validate_arguments_against_schema" in cortex
    executor = _source("actions/executor.py")
    assert "execute_capability" in executor
    assert "encode_capability_arguments" in executor
    assert "encode_capability_arguments" not in cortex
    assert "_CAPABILITY_INPUT_CONTRACTS" in registry
    assert "capability_input" not in cortex
    assert "capability_arguments" in orchestrator


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
