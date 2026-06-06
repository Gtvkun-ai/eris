from cortex.subconscious import FreeAssociationEngine, ThoughtSpark


def test_free_association_creates_weird_but_grounded_link():
    sparks = (
        ThoughtSpark.create(seed="SurfaceArbiter", source="habitat", strength=0.7, clarity=0.55, weirdness=0.42, tags=("surface_arbiter",), now=1000.0),
        ThoughtSpark.create(seed="cửa miệng", source="self_anchor", strength=0.55, clarity=0.45, weirdness=0.58, tags=("mouth_gate",), now=1000.0),
        ThoughtSpark.create(seed="restraint", source="mood", strength=0.45, clarity=0.42, weirdness=0.35, tags=("restraint",), now=1000.0),
    )

    paths = FreeAssociationEngine().associate(sparks, now=1001.0)

    assert paths
    best = paths[0]
    assert best.weirdness >= 0.20
    assert best.groundedness >= 0.22
    assert "SurfaceArbiter" in best.statement or "cửa miệng" in best.statement
    assert best.source_evidence
