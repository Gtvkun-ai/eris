# -*- coding: utf-8 -*-
"""Smoke test thủ công cho Social Cognition V2, không cần gọi API.

Chạy từ thư mục src:
    PYTHONPATH=. python tools/run_social_cognition_v2_smoke.py

Script chỉ in contract và fallback deterministic. Nó không ghi memory thật.
"""

from __future__ import annotations

import threading

from runtime.social_cognition_v2 import SocialCognitionEngine, SocialOutcomeMemory


class _NoDiskMemory(SocialOutcomeMemory):
    def __init__(self) -> None:
        self.stats = {}
        self._lock = threading.RLock()

    def _save(self) -> None:
        return None


def show(engine: SocialCognitionEngine, user_text: str) -> None:
    contract = engine.analyze(user_text)
    hypotheses = ", ".join(
        f"{item.intent}:{item.probability:.2f}" for item in contract.hypotheses
    )
    print(f"\nUSER : {user_text}")
    print(f"MOVE : {contract.response_move}")
    print(f"HYP  : {hypotheses}")
    print(
        "STATE:",
        f"warmth={contract.social_state['warmth']:.2f}",
        f"irritation={contract.social_state['irritation']:.2f}",
        f"anger={int(contract.social_state['anger_level'])}",
    )
    fallback = engine.fallback_text(contract)
    if fallback:
        print(f"FALLBACK: {fallback}")


def main() -> None:
    print("=== Eris Social Cognition V2 smoke test ===")

    repair = SocialCognitionEngine(outcome_memory=_NoDiskMemory())
    repair.record_public_response("Tôi nghĩ bạn đang gây chuyện rồi.")
    show(repair, "không phải em gây chuyện hả")
    show(repair, "em hiểu sai cái gì nè")
    show(repair, "là phần nào cơ")

    joke = SocialCognitionEngine(outcome_memory=_NoDiskMemory())
    show(joke, "1 mẹ mày béo + 1 mẹ mày béo ra gì")

    agency = SocialCognitionEngine(outcome_memory=_NoDiskMemory())
    show(agency, "đếm từ 1 đến 100 đi Eris")
    show(agency, "đếm từ 1 đến 100 đi Eris")
    show(agency, "đếm từ 1 đến 100 đi Eris")

    technical = SocialCognitionEngine(outcome_memory=_NoDiskMemory())
    show(technical, "đếm từ 1 đến 100 để test TTS")

    anger = SocialCognitionEngine(outcome_memory=_NoDiskMemory())
    for _ in range(4):
        show(anger, "mẹ mày béo")


if __name__ == "__main__":
    main()
