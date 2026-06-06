from types import SimpleNamespace

from cortex.low_level_speech_policy import LowLevelSpeechPolicy, LowLevelSpeechPolicyConfig
from cortex.subconscious import RehearsalAgent, ThoughtObject, WorkerContext
from cortex.surface_arbiter import SurfaceArbiter


class MicroGen:
    def __call__(self, *, impulse, snapshot=None, force_llm=False):
        return "Có vẻ càng vá ERIS, bug càng giống tâm lý học hơn code.", "mock_ok"


def test_rehearsal_can_suppress_wandering_surface():
    thought = ThoughtObject(
        id="to.wandering",
        dominant_theme="repo as organism",
        fragments=("frag.wandering",),
        summary="repo giống sinh vật khó nuôi hơn thư mục code",
        confidence=0.82,
        surface_pressure=0.80,
        suppressed_pressure=0.10,
        evidence_ids=("spark:repo",),
        recommended_route="surface_candidate",
        privacy_level="normal",
        tags=("wandering", "repo_as_organism"),
        created_at=1000.0,
    )
    context = WorkerContext(
        thought_object=thought,
        snapshot=SimpleNamespace(focus_kind="code", keyboard_active=True, idle_seconds=5.0),
        internal_state=SimpleNamespace(interruption_cost=0.7, speech_cost=0.65),
        now=1000.0,
    )

    fragments = tuple(RehearsalAgent().run(context))
    rehearsal = next(fragment for fragment in fragments if fragment.kind == "rehearsal_result")

    assert "winner=say_now" not in rehearsal.content
    assert any(fragment.kind in {"suppressed_impulse", "rehearsal_result"} for fragment in fragments)


def test_wandering_surface_goes_through_surface_arbiter():
    policy = LowLevelSpeechPolicy(
        LowLevelSpeechPolicyConfig(
            high_conf_threshold=0.30,
            min_surface_confidence=0.20,
            body_only_min_confidence=0.10,
            min_surface_interval_seconds=0.0,
            family_cooldown_seconds=0.0,
            always_llm_kinds=("wandering_surface_candidate",),
        )
    )
    arbiter = SurfaceArbiter(policy=policy, llm_micro_gen=MicroGen())
    frame = SimpleNamespace(
        subconscious_seed={
            "topic_seed": "repo as organism",
            "partial_text": "repo giống sinh vật khó nuôi hơn thư mục code",
            "public_seed": "repo giống sinh vật khó nuôi hơn thư mục code",
            "pressure": 0.72,
            "momentum_score": 0.70,
            "novelty": 0.60,
            "evidence": ["spark:repo", "anchor=wandering_drift"],
            "recommended_route": "surface_candidate",
            "impulse_kind": "wandering_surface_candidate",
            "root_source": "wandering",
            "action_opportunity": "wandering_surface_candidate",
            "surface_allowed": True,
        }
    )

    decision = arbiter.arbitrate(cognitive_frame=frame, snapshot=SimpleNamespace(idle_seconds=120.0, focus_kind="idle"), silent_cycles=4)

    assert decision.should_speak is True
    assert decision.kind == "wandering_surface_candidate"
    assert decision.generation_mode in {"normal_llm", "force_llm"}
    assert "tôi đang nghĩ về ngài" not in decision.text.lower()
