# -*- coding: utf-8 -*-
from types import SimpleNamespace

from domain import Decision
from runtime.final_passthrough_policy import PublicSpeechSnapshot, final_passthrough_enabled
from semantic_authority import SemanticAuthorityPolicy


def _decision(text="raw tốt hơn final"):
    return Decision(text=text, animation="stand", should_speak=True, intent="chat")


def test_final_passthrough_is_default_on():
    assert final_passthrough_enabled() is True


def test_semantic_policy_disables_all_second_pass_writers():
    policy = SemanticAuthorityPolicy(final_passthrough_setting=True)
    assert policy.bounded_refine_enabled is False
    assert policy.generate_director_candidates is False
    assert policy.enforce_response_contract is False
    assert policy.hard_only_final_guards is True
    assert policy.low_quality_fail_open is True


def test_snapshot_restores_public_speech_but_not_tool_state():
    decision = _decision("Có tôi đây, bạn nói đi.")
    decision.system_action = "open_url"
    snap = PublicSpeechSnapshot.capture(decision)

    decision.text = "Có mặt đây, bạn."
    decision.should_speak = False
    decision.intent = "rewritten"
    decision.system_action = ""  # action executor is allowed to consume it

    snap.restore(decision, stage="unit_test")
    assert decision.text == "Có tôi đây, bạn nói đi."
    assert decision.should_speak is True
    assert decision.intent == "chat"
    assert decision.system_action == ""
    assert "final_passthrough" in decision.reasoning_tags
    assert "mutation_discarded" in decision.debug_trace


def test_runtime_settings_cannot_reenable_final_editors(monkeypatch):
    class FakeStore:
        def get(self, section, key=None, default=None):
            if section == "chat":
                return {
                    "director_candidate_mode": "always",
                    "critique_mode": "bounded_refine",
                    "max_constrained_reruns": 2,
                    "response_contract_gate": True,
                    "low_quality_fail_open": False,
                }
            if section == "pipeline" and key == "final_passthrough":
                return False
            return default

    import runtime.runtime_settings_store as settings_module

    monkeypatch.setattr(settings_module, "get_runtime_settings_store", lambda: FakeStore())
    policy = SemanticAuthorityPolicy.from_runtime()
    assert policy.final_passthrough is True
    assert policy.generate_director_candidates is False
    assert policy.bounded_refine_enabled is False


def test_directive_self_critique_cannot_drop_or_rerun_raw():
    from runtime.self_critique import SelfCritiqueEscalationMixin

    class Dummy(SelfCritiqueEscalationMixin):
        def _self_critique_enabled(self):  # pragma: no cover - must not be reached
            raise AssertionError("self critique must remain audit-only")

    decision = _decision("Raw autonomous cũng phải sống.")
    result = Dummy()._maybe_escalate_directive_decision(
        decision,
        channel="autonomous",
        snapshot=SimpleNamespace(),
        ti_report=SimpleNamespace(),
        directive_kwargs={},
    )
    assert result is decision
    assert result.text == "Raw autonomous cũng phải sống."
    assert "final_passthrough" in result.reasoning_tags
    assert "self_critique_autonomous" in result.debug_trace


def test_runtime_coordinator_overriding_loop_has_passthrough_restore():
    import inspect
    from runtime.coordinator import RuntimeCoordinator

    # RuntimeCoordinator định nghĩa method riêng nên override AutonomousCycleMixin.
    # Test này khóa đúng đường production đang thắng MRO, không chỉ khóa mixin đẹp mã.
    source = inspect.getsource(RuntimeCoordinator._run_loop_iteration)
    assert RuntimeCoordinator._run_loop_iteration.__module__ == "runtime.coordinator"
    assert "coordinator_autonomous_inner_precommit" in source
    assert "coordinator_autonomous_precommit" in source
