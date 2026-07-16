from __future__ import annotations

import json

from runtime.social_cognition_v2 import SocialHypothesis, TaskAppraisal
from runtime.social_model_router import SocialModelRouter


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


class _Service:
    def __init__(self):
        self.social_parser_client = _Client({
            "hypotheses": [
                {"intent": "playful_provocation", "probability": 0.7, "target": "eris", "evidence_spans": ["mẹ mày béo"], "expected_response": "playful_counter"},
                {"intent": "genuine_insult", "probability": 0.3, "target": "eris", "evidence_spans": ["mẹ mày béo"], "expected_response": "cool_boundary"},
            ]
        })
        self.social_critic_client = _Client({
            "response_move": "playful_counter",
            "why": "banter likely",
            "risk_flags": [],
            "required_content": "counter without moralizing",
        })
        self.client = _Client({
            "text": "Lại bài đó. Bạn giữ nó kỹ hơn cả mật khẩu nhỉ.",
            "delivery_hint": "dry_tease",
            "nonverbal_cue": "small_smirk",
            "stage_motion": "tilt_head",
        })


def test_router_refines_deliberates_and_rewrites():
    service = _Service()
    router = SocialModelRouter(service)
    hypotheses = (SocialHypothesis("normal_chat", 0.5), SocialHypothesis("genuine_insult", 0.5))
    refined = router.refine_hypotheses(
        user_text="mẹ mày béo",
        history=(),
        hypotheses=hypotheses,
        failed_claim="",
        task=TaskAppraisal().to_dict(),
        ambiguity=0.8,
    )
    assert refined[0].intent == "playful_provocation"
    deliberation = router.deliberate(
        user_text="mẹ mày béo",
        history=(),
        hypotheses=refined,
        failed_claim="",
        social_state={"anger_level": 0},
        task=TaskAppraisal().to_dict(),
    )
    assert deliberation["response_move"] == "playful_counter"
    rewrite = router.rewrite_with_main(
        candidate_text="Tôi không thể tiếp tục.",
        user_text="mẹ mày béo",
        contract={"response_move": "playful_counter"},
        instruction="avoid support bot boundary",
    )
    assert "mật khẩu" in rewrite["text"]
