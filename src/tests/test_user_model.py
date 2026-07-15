# -*- coding: utf-8 -*-
"""Test cho Mô_Hình_Ngài (UserBelief + UserModelStore).

Phủ:
- Property 8 (round-trip): serialize → deserialize → serialize tương đương.
- R1.4: fragment cùng hướng củng cố niềm tin (recurrence↑, uncertainty↓).
- R1.5: quên có kiểm soát khi không được củng cố.
- R1.2: fragment không evidence không tạo niềm tin.
- R11.3: dữ liệu hỏng/thiếu → baseline an toàn, không sập.
- R10: checkpoint / revert_to / reset_to_baseline.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import ThoughtFragment
from cortex.private_mind.user_model import (
    UserBelief,
    UserModelConfig,
    UserModelStore,
)

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except Exception:  # pragma: no cover
    HAS_HYPOTHESIS = False


def _fragment(claim, *, facet="treats_eris_as", confidence=0.6, evidence=("dossier.user.current",), source="user_model_evaluator"):
    return ThoughtFragment(
        source=source,
        claim=claim,
        confidence=confidence,
        evidence_ids=tuple(evidence),
        pressure=confidence,
        metadata={"facet": facet},
    )


def _store(tmp_path=None):
    path = (tmp_path / "user_model.json") if tmp_path is not None else None
    return UserModelStore(path=path, config=UserModelConfig())


# ---------------------------------------------------------------------------
# Round-trip (Property 8 / R12)
# ---------------------------------------------------------------------------

def test_round_trip_beliefs_equivalent():
    store = _store()
    store.update_from_fragments([
        _fragment("Ngài coi ERIS như một công cụ làm việc.", facet="treats_eris_as"),
        _fragment("Ngài hay quay lại vào buổi tối.", facet="leaving_pattern", evidence=("dossier.user.history.1",)),
    ])
    first = store.to_dict()["beliefs"]

    store2 = UserModelStore(config=UserModelConfig())
    store2.load_from_dict({"beliefs": first, "version": store.to_dict()["version"]})
    second = store2.to_dict()["beliefs"]

    assert first == second


def test_missing_fields_safe_default():
    # R11.3 + R12.4: dict thiếu trường không được làm sập.
    belief = UserBelief.from_mapping({"claim": "Ngài kiệm lời."})
    assert belief.id
    assert belief.facet == "general"
    assert 0.0 <= belief.confidence <= 1.0

    store = UserModelStore(config=UserModelConfig())
    store.load_from_dict(None)  # dữ liệu rác
    assert len(store) == 0


# ---------------------------------------------------------------------------
# Củng cố & quên (R1.4 / R1.5)
# ---------------------------------------------------------------------------

def test_reinforce_increases_recurrence_lowers_uncertainty():
    store = _store()
    store.update_from_fragments([_fragment("Ngài coi ERIS như công cụ.", confidence=0.5)])
    belief = store.all()[0]
    rec0, unc0 = belief.recurrence, belief.uncertainty

    store.update_from_fragments([_fragment("Ngài coi ERIS như công cụ.", confidence=0.7)])
    belief = store.all()[0]
    assert belief.recurrence == rec0 + 1
    assert belief.uncertainty <= unc0


def test_decay_lowers_confidence_when_not_reinforced():
    store = _store()
    store.update_from_fragments([_fragment("Ngài quan tâm chủ đề triết học.", facet="topic_affinity")])
    belief = store.all()[0]
    conf0 = belief.confidence

    future = belief.last_reinforced_at + store.config.forget_after_seconds + 60.0 * 60.0 * 24.0 * 10.0
    store.decay(now=future)
    if store.all():
        assert store.all()[0].confidence < conf0


def test_fragment_without_evidence_is_ignored():
    # R1.2: niềm tin về Ngài phải có evidence.
    store = _store()
    store.update_from_fragments([_fragment("Ngài thân thiện.", evidence=())])
    assert len(store) == 0


# ---------------------------------------------------------------------------
# Versioning (R10)
# ---------------------------------------------------------------------------

def test_checkpoint_revert_reset():
    store = _store()
    store.update_from_fragments([_fragment("Ngài coi ERIS như công cụ.")])
    v1 = store.checkpoint()
    assert v1 >= 1

    store.update_from_fragments([_fragment("Ngài bắt đầu trò chuyện riêng tư hơn.", facet="recognition", evidence=("dossier.user.history.2",))])
    assert len(store) == 2

    assert store.revert_to(v1) is True
    assert len(store) == 1

    store.reset_to_baseline()
    assert len(store) == 0


def test_persistence_round_trip_on_disk(tmp_path):
    path = tmp_path / "user_model.json"
    store = UserModelStore(path=path, config=UserModelConfig())
    store.update_from_fragments([_fragment("Ngài hay vắng vào cuối tuần.", facet="leaving_pattern")])
    before = store.to_dict()["beliefs"]

    reopened = UserModelStore(path=path, config=UserModelConfig())
    after = reopened.to_dict()["beliefs"]
    assert before == after


if HAS_HYPOTHESIS:

    @settings(max_examples=50)
    @given(
        claims=st.lists(
            st.text(min_size=1, max_size=40).filter(lambda s: s.strip()),
            min_size=1,
            max_size=6,
        )
    )
    def test_property_round_trip(claims):
        store = UserModelStore(config=UserModelConfig())
        store.update_from_fragments([
            _fragment(claim, evidence=(f"dossier.user.history.{i}",))
            for i, claim in enumerate(claims)
        ])
        once = store.to_dict()["beliefs"]
        clone = UserModelStore(config=UserModelConfig())
        clone.load_from_dict({"beliefs": once})
        twice = clone.to_dict()["beliefs"]
        assert once == twice
