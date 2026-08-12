# -*- coding: utf-8 -*-
from runtime.ai_orchestrated.contracts import AI_RUNTIME_VERSION
from runtime.ai_orchestrated.startup_grounding import ensure_startup_greeting_payload


def test_runtime_version_marks_opening_director_v26() -> None:
    assert AI_RUNTIME_VERSION == "ai_orchestrated.v28.background_seed_reservoir"


def test_v25_final_greeting_guard_remains_available() -> None:
    assert callable(ensure_startup_greeting_payload)
