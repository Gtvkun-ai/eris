from types import SimpleNamespace

from cortex.subconscious import (
    SubconsciousBlackboard,
    TopicSeedPool,
    WanderingThoughtEngine,
    WanderingTopicMemory,
    ThoughtSpark,
)
from cortex.subconscious.wandering_contracts import AssociationPath


def test_wandering_thought_not_user_anchored_only():
    pool = TopicSeedPool()
    seeds = pool.generate(now=1000.0)

    assert seeds
    assert pool.non_user_ratio(seeds) >= 0.5
    assert {seed.source for seed in seeds} & {"self_anchor", "habitat", "mood", "rhythm", "random"}


def test_wandering_fragment_enters_blackboard():
    blackboard = SubconsciousBlackboard()
    engine = WanderingThoughtEngine(min_idle_seconds=10.0, min_resonance_for_fragment=0.18)
    snapshot = SimpleNamespace(idle_seconds=120.0, focus_kind="idle")
    internal = SimpleNamespace(boredom=0.6, solitude=0.4, curiosity=0.4, restraint=0.3)

    result = engine.tick(snapshot=snapshot, internal_state=internal, blackboard=blackboard, now=1000.0)

    assert result.sparks
    assert result.fragments
    assert len(blackboard.top_fragments(now=1000.0)) >= 1
    assert any("wandering" in fragment.tags for fragment in blackboard.top_fragments(now=1000.0))


def test_random_chat_not_status_ping():
    engine = WanderingThoughtEngine(min_idle_seconds=10.0, min_resonance_for_fragment=0.18)
    snapshot = SimpleNamespace(idle_seconds=120.0, focus_kind="idle")
    internal = SimpleNamespace(boredom=0.7, solitude=0.3, curiosity=0.4, restraint=0.2)

    result = engine.tick(snapshot=snapshot, internal_state=internal, now=1000.0)
    joined = "\n".join(fragment.content.lower() for fragment in result.fragments)

    assert "tôi đang nghĩ về bạn" not in joined
    assert "status ping" not in joined
    assert "idle_seconds=" not in joined


def test_topic_continuity_across_ticks():
    memory = WanderingTopicMemory()
    spark = ThoughtSpark.create(seed="body-only as swallowed speech", source="self_anchor", tags=("body_only",), now=1000.0)
    topic1 = memory.touch_sparks((spark,), now=1000.0)[0]
    path = AssociationPath(
        spark_ids=(spark.id,),
        seeds=(spark.seed, "dignity/restraint"),
        statement="Có những câu không bị giữ lại vì sai; chúng bị giữ lại vì nói ra làm chúng rẻ đi.",
        weirdness=0.54,
        groundedness=0.48,
        source_evidence=("spark_seed:body-only",),
        tags=("wandering", "body_only", "restraint"),
    )
    topic2 = memory.touch_association(path, now=1060.0)

    assert topic1.id == topic2.id
    assert topic2.recurrence > topic1.recurrence
    assert any(topic.theme == "body-only as swallowed speech" for topic in memory.active_topics())


def test_wandering_does_not_interrupt_deep_focus():
    engine = WanderingThoughtEngine(min_idle_seconds=10.0, min_resonance_for_fragment=0.18)
    snapshot = SimpleNamespace(idle_seconds=5.0, focus_kind="code", keyboard_active=True, user_is_typing=True)
    internal = SimpleNamespace(boredom=0.8, solitude=0.5, curiosity=0.5, restraint=0.2)

    result = engine.tick(snapshot=snapshot, internal_state=internal, now=1000.0)

    assert not any(fragment.surface_allowed for fragment in result.fragments)
    assert "deep_focus" in result.debug_reason
