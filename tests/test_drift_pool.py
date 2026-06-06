from cortex.subconscious import DriftPool, ThoughtSpark


def test_spark_does_not_surface_directly():
    spark = ThoughtSpark.create(
        seed="body-only",
        source="self_anchor",
        raw_text="body-only as swallowed speech",
        strength=0.7,
        clarity=0.4,
        weirdness=0.5,
        tags=("body_only",),
        now=1000.0,
    )

    payload = spark.to_dict()

    assert payload["surface_allowed"] is False
    assert not hasattr(spark, "should_surface")
    assert "public_seed" not in payload


def test_drift_pool_resonates_related_sparks():
    pool = DriftPool()
    pool.submit(ThoughtSpark.create(seed="body-only", source="self_anchor", strength=0.72, clarity=0.48, weirdness=0.50, tags=("body_only",), now=1000.0), now=1000.0)
    pool.submit(ThoughtSpark.create(seed="câm", source="mood", strength=0.55, clarity=0.30, weirdness=0.42, tags=("swallowed_speech",), now=1001.0), now=1001.0)
    pool.submit(ThoughtSpark.create(seed="dignity/restraint", source="self_anchor", strength=0.52, clarity=0.50, weirdness=0.45, tags=("dignity", "restraint"), now=1002.0), now=1002.0)

    resonances = pool.resonate(now=1003.0)

    assert resonances
    assert any("body-only" in spark.seed or "lời" in spark.seed for spark in resonances)
    assert len(pool.top_sparks(now=1003.0)) >= 3
