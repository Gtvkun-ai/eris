from __future__ import annotations

from types import SimpleNamespace

from actions.capability_registry import canonicalize_action_id
from actions.confirmation import public_action_text
from actions.contracts import ActionExecutionResult, ActionExecutionStatus
from llm.token_pressure import TokenPressureGovernor
from memory.provenance_policy import ContestedClaimStore, MemoryProvenancePolicy, PublicMemoryMode
from runtime.final_surface_sanitizer import FinalSurfaceSanitizer
from runtime.repair_state import RepairStateController
from runtime.semantic_equivalence_gate import SemanticEquivalenceGate
from runtime.speech_contract import SpeechContractResolver
from runtime.stage_contracts import StageFrameBuilder
from runtime.stage_transformers import StageTransformerChain
from runtime.text_repeat_guard import TextRepeatGuardMixin
from runtime.tts_circuit_breaker import BreakerState, TtsCircuitBreaker


def test_director_semantic_gate_rejects_dispatch_escalation():
    gate = SemanticEquivalenceGate()
    result = gate.evaluate(
        "Tôi đã gửi yêu cầu chỉnh âm lượng về 100 phần trăm.",
        "Tôi đã tăng âm lượng lên 100 phần trăm.",
        intent="direct_action",
    )
    assert result.accepted is False
    assert result.reason == "dispatch_escalated_to_success"


def test_director_semantic_gate_accepts_safe_paraphrase():
    gate = SemanticEquivalenceGate()
    result = gate.evaluate(
        "Tôi chưa có bằng chứng hiện tại để khẳng định điều đó.",
        "Hiện tôi chưa đủ bằng chứng để khẳng định điều đó.",
        intent="factual",
    )
    assert result.accepted is True


def test_final_surface_sanitizer_blocks_secret_internal_url_and_stage_note():
    sanitizer = FinalSurfaceSanitizer()
    text = "(nháy mắt) key=AIza1234567890abcdefghijklmnop xem http://127.0.0.1:4242/debug"
    result = sanitizer.sanitize(text, surface="display")
    assert "nháy mắt" not in result.text
    assert "AIza" not in result.text
    assert "127.0.0.1" not in result.text
    assert {"stage_direction", "secret", "private_url"}.issubset(set(result.blocked_kinds))


def test_stage_chain_drops_singing_action_when_capability_off(monkeypatch):
    monkeypatch.setenv("ERIS_SINGING_CAPABILITY", "0")
    surfaces = StageTransformerChain().transform("Mùa xuân đến rồi. (hát một câu đầu tiên của bài hát)")
    assert surfaces.display_text == "Mùa xuân đến rồi."
    assert "sing_tease" not in surfaces.marks.actions
    assert surfaces.tts_text == "Mùa xuân đến rồi."


def test_action_contract_distinguishes_dispatched_from_observed():
    result = ActionExecutionResult(
        action_name="set_volume",
        action_input="100",
        success=True,
        data={"level": "100"},
    )
    assert canonicalize_action_id("adjust_volume") == "set_volume"
    assert result.status == ActionExecutionStatus.DISPATCHED
    assert result.confirmed is False
    assert result.public_mode == "request_sent"
    assert "gửi yêu cầu" in public_action_text(result)
    assert "đã tăng" not in public_action_text(result).lower()


def test_read_only_action_is_observed():
    result = ActionExecutionResult(
        action_name="get_local_time",
        success=True,
        message="Bây giờ là 19:00.",
    )
    assert result.status == ActionExecutionStatus.OBSERVED
    assert result.confirmed is True
    assert result.public_mode == "observed_success"


def test_observed_side_effect_may_use_confirmed_wording():
    result = ActionExecutionResult(
        action_name="set_volume",
        action_input="80",
        success=True,
        message="Âm lượng đã được xác nhận ở khoảng 80 phần trăm.",
        status=ActionExecutionStatus.OBSERVED,
        evidence=("observer:system_volume=80",),
    )
    assert result.confirmed is True
    assert public_action_text(result) == result.message


def test_speech_contract_is_pinned_into_stage_frame():
    decision = SimpleNamespace(
        text="Xin chào.", intent="chat", should_speak=True, delivery_hint="",
        nonverbal_cue="", stage_motion="", animation="stand", speech_act="",
        preset_id="", audio_asset="", preset_emotion="",
        resolve_motion_intent=lambda: "",
    )
    frame = StageFrameBuilder(language_hint="vi").build(
        decision,
        payload={
            "text": "Xin chào.",
            "speech_contract": {
                "language": "vi",
                "locale": "vi-VN",
                "voice_family": "Aoede",
                "provider_tier": "primary",
                "can_translate": False,
            },
        },
    )
    assert frame.speech_contract["language"] == "vi"
    assert frame.speech_contract["locale"] == "vi-VN"
    assert frame.speech_contract["voice_family"] == "Aoede"
    assert frame.to_payload_patch()["stage"]["speech_contract"]["language"] == "vi"


def test_speech_contract_auto_defaults_to_vietnamese_not_provider_guessing():
    contract = SpeechContractResolver(default_language="auto").resolve({}, text="Câu tiếng Việt bình thường")
    assert contract.language == "vi"
    assert contract.locale == "vi-VN"


def test_tts_breaker_opens_then_half_opens_with_limited_probe():
    breaker = TtsCircuitBreaker(failure_threshold=2, cooldown_s=10, successful_probes=1, max_half_open_probes=1)
    key = ("gemini", "tts", "Aoede", "vi-VN")
    assert breaker.allow(key, now=0).allowed
    breaker.record_failure(key, kind="rate_limit", now=1)
    breaker.record_failure(key, kind="rate_limit", now=2)
    assert breaker.state(key) == BreakerState.OPEN
    assert breaker.allow(key, now=5).allowed is False
    probe = breaker.allow(key, now=13)
    assert probe.allowed is True
    assert probe.state == BreakerState.HALF_OPEN
    assert breaker.allow(key, now=13).allowed is False
    breaker.record_success(key)
    assert breaker.state(key) == BreakerState.CLOSED


def test_memory_provenance_hedges_weak_recall_and_blocks_contested_claim(monkeypatch):
    policy = MemoryProvenancePolicy()
    weak = policy.decide(source="session_turn_graph", confidence=0.65, evidence=("turn:1",), text="Tên bạn là Nam.")
    assert weak.mode == PublicMemoryMode.HEDGED
    assert "Nếu tôi nhớ nhầm" in policy.render("Tên bạn là Nam.", weak)

    # Test store riêng để kiểm tra TTL/turn mà không làm bẩn singleton của suite.
    store = ContestedClaimStore(ttl_s=60, turns=2)
    store.mark("Tên bạn là Nam.", now=0)
    assert store.is_contested("Tên bạn là Nam.", now=1)
    assert store.is_contested("Tên bạn là Nam.", consume_turn=True, now=1)


def test_repair_state_exhausts_instead_of_reopening_forever():
    state = RepairStateController(ttl_s=60, max_public_turns=2)
    state.begin(target="claim_correction", now=0)
    assert state.consume_public_turn(now=1)
    assert state.consume_public_turn(now=2)
    assert state.state.exhausted is True
    state.begin(target="same_loop", now=2)
    assert state.state.active is False
    state.clear()
    state.begin(target="new_topic", now=3)
    assert state.state.active is True


class _RepeatHarness(TextRepeatGuardMixin):
    @staticmethod
    def _normalize_user_message(text: str) -> str:
        return " ".join(str(text or "").lower().split())


def test_semantic_repeat_exempts_repair_after_failure():
    guard = _RepeatHarness()
    assert guard._semantic_repeat_match("tăng âm lượng", "tăng âm lượng") is True
    assert guard._semantic_repeat_match(
        "tăng âm lượng", "tăng âm lượng", follow_up_after_failure=True
    ) is False


def test_token_governor_sheds_localizer_lane_under_pressure():
    governor = TokenPressureGovernor(window_seconds=60, budgets={"gemini": 1000})
    governor.record_request("gemini", lane="chat", prompt_tokens=900, output_tokens=100, now=0)
    plan = governor.plan_request(
        "gemini",
        lane="speech_localizer",
        prompt_tokens=300,
        requested_output_tokens=200,
        optional_pass=True,
        now=1,
    )
    assert plan.allowed is False
    assert plan.snapshot.shed_optional_passes is True
