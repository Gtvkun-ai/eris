# -*- coding: utf-8 -*-
"""Test cho UserModelEvaluator + định tuyến vào Mô_Hình_bạn (Task 2 / R1).

Phủ:
- Evaluator đẻ fragment hướng-bạn có `metadata['facet']` và `evidence_ids` từ dossier.
- Adapter trả None / claim rỗng → không có fragment.
- relevance_signature im khi không có lời người dùng.
- Pipeline → UserModelStore: chỉ fragment có evidence mới vào chân dung (R1.2).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import EvidenceDossier
from cortex.private_mind.mini_evaluators import (
    USER_MODEL_EVALUATOR_NAME,
    MiniEvaluatorPipeline,
    UserModelEvaluator,
)
from cortex.private_mind.user_model import UserModelConfig, UserModelStore


class _FakeAdapter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate_fragment(self, name, dossier):
        self.calls.append(name)
        return self.payload


def _dossier_with_user_turn(text="bạn coi ERIS như một công cụ làm việc."):
    eid = "dossier.user.current"
    return EvidenceDossier(
        dossier_id="d1",
        recent_user_turns=({"evidence_id": eid, "text": text, "intent": "ordinary_dialogue"},),
        runtime_state={"channel": "chat", "idle_seconds": 3.0},
        evidence_index={eid: {"text": text}},
    )


def test_evaluator_emits_facet_and_evidence():
    adapter = _FakeAdapter({
        "claim": "bạn coi ERIS như một công cụ làm việc.",
        "confidence": 0.62,
        "pressure": 0.4,
        "facet": "treats_eris_as",
    })
    ev = UserModelEvaluator(model_adapter=adapter)
    fragment = ev.evaluate(_dossier_with_user_turn())
    assert fragment is not None
    assert fragment.source == USER_MODEL_EVALUATOR_NAME
    assert fragment.metadata.get("facet") == "treats_eris_as"
    assert fragment.evidence_ids  # neo vào evidence của dossier


def test_evaluator_infers_facet_when_model_omits_it():
    adapter = _FakeAdapter({
        "claim": "bạn hay biến mất vào cuối tuần, không quay lại.",
        "confidence": 0.55,
    })
    ev = UserModelEvaluator(model_adapter=adapter)
    fragment = ev.evaluate(_dossier_with_user_turn("Cuối tuần tôi đi vắng."))
    assert fragment is not None
    assert fragment.metadata.get("facet") == "leaving_pattern"


def test_evaluator_returns_none_on_empty_claim_or_none():
    assert UserModelEvaluator(model_adapter=_FakeAdapter(None)).evaluate(_dossier_with_user_turn()) is None
    assert UserModelEvaluator(model_adapter=_FakeAdapter({"claim": ""})).evaluate(_dossier_with_user_turn()) is None


def test_relevance_silent_without_user_turn():
    ev = UserModelEvaluator(model_adapter=_FakeAdapter({"claim": "x"}))
    empty = EvidenceDossier(dossier_id="d0")
    assert ev.relevance_signature(empty) is None
    assert ev.relevance_signature(_dossier_with_user_turn()) is not None


def test_pipeline_routes_into_user_model_store():
    adapter = _FakeAdapter({
        "claim": "bạn coi ERIS như một công cụ làm việc.",
        "confidence": 0.62,
        "facet": "treats_eris_as",
    })
    pipeline = MiniEvaluatorPipeline(
        evaluators=(UserModelEvaluator(model_adapter=adapter),),
        relevance_gate_enabled=False,
    )
    fragments = pipeline.evaluate(_dossier_with_user_turn())
    user_fragments = tuple(f for f in fragments if f.source == USER_MODEL_EVALUATOR_NAME)
    assert user_fragments

    store = UserModelStore(config=UserModelConfig())
    store.update_from_fragments(user_fragments)
    assert len(store) == 1
    assert store.all()[0].facet == "treats_eris_as"
