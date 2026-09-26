from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from runtime.ai_orchestrated import orchestrator
from runtime.ai_orchestrated.atomic_state import SQLiteAtomicStateStore
from runtime import pedagogical_runtime
from runtime.pedagogical_contracts import TeachingConcept, TeachingDirective, TeachingPlan
from runtime.runtime_settings_store import RuntimeSettingsStore
from runtime.settings_catalog import build_settings_catalog


def _plan() -> TeachingPlan:
    return TeachingPlan(
        global_goal="Understand the distinction",
        concepts=tuple(
            TeachingConcept(f"concept-{index}", f"Description {index}", f"Objective {index}")
            for index in range(3)
        ),
        success_evidence=("User can contrast the concepts",),
    )


class _FakeBuilder:
    def __init__(self, plan: TeachingPlan | None = None) -> None:
        self.plan = plan
        self.calls: list[Mapping[str, Any]] = []

    def build(self, request_context: Mapping[str, Any]) -> TeachingPlan | None:
        self.calls.append(dict(request_context))
        return self.plan


class _FakeRuntime:
    def __init__(self, episode: Mapping[str, Any] | None = None) -> None:
        self.episode = dict(episode) if episode is not None else None
        self.observations: list[tuple[str, tuple[str, ...], float]] = []
        self.started = []
        self.receipts = []
        self.observed_result = None

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        return {"active_episode": self.episode}

    def start_episode(self, episode: Any) -> bool:
        self.started.append(episode)
        self.episode = episode.to_dict()
        return True

    def observe_user_turn(
        self,
        user_text: str,
        *,
        evidence: tuple[str, ...] = (),
        now: float | None = None,
    ) -> Any:
        self.observations.append((user_text, evidence, float(now or 0.0)))
        return self.observed_result

    def commit_receipt(self, receipt: Any, *, now: float | None = None) -> bool:
        self.receipts.append((receipt, now))
        return True


class _FakeWriter:
    def __init__(self, events: list[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.events = events

    def generate_public_reply(self, **kwargs: Any) -> dict[str, Any]:
        if self.events is not None:
            self.events.append("writer")
        self.calls.append(dict(kwargs))
        return {"text": "one bounded chunk"}


def test_flag_off_does_not_resolve_runtime_or_change_writer_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = []
    builder = _FakeBuilder(_plan())
    writer = _FakeWriter()
    host = SimpleNamespace(pedagogical_controller_enabled=False, ai_teaching_plan_builder=builder)
    monkeypatch.setattr(orchestrator, "ensure_pedagogical_runtime", lambda value: resolved.append(value))

    runtime, directive = orchestrator._prepare_pedagogical_turn(
        host,
        user_text="Explain this briefly",
        turn_id="turn-off",
        recent_history=(),
        now=100.0,
    )
    result = orchestrator._generate_public_reply(writer, teaching_directive=directive, user_text="hello")

    assert runtime is None
    assert directive is None
    assert resolved == []
    assert builder.calls == []
    assert result["text"] == "one bounded chunk"
    assert "teaching_directive" not in writer.calls[0]


def test_runtime_enablement_uses_runtime_settings_after_host_overrides(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def enabled_from_catalog(*path: str, default: bool = False) -> bool:
        calls.append(path)
        return path == ("pedagogy", "enabled")

    monkeypatch.setattr(pedagogical_runtime, "runtime_bool", enabled_from_catalog, raising=False)

    shared_store = SQLiteAtomicStateStore(tmp_path / "pedagogy.sqlite")
    configured_host = SimpleNamespace(ai_social_atomic_store=shared_store)
    assert isinstance(
        pedagogical_runtime.ensure_pedagogical_runtime(configured_host),
        pedagogical_runtime.PedagogicalRuntime,
    )
    assert pedagogical_runtime.ensure_pedagogical_runtime(
        SimpleNamespace(pedagogical_controller_enabled=False, ai_social_atomic_store=shared_store)
    ) is None
    assert calls == [("pedagogy", "enabled")]


def test_explicit_activation_starts_episode_and_reaches_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _FakeRuntime()
    builder = _FakeBuilder(_plan())
    writer = _FakeWriter()
    host = SimpleNamespace(
        pedagogical_controller_enabled=True,
        ai_teaching_plan_builder=builder,
    )
    monkeypatch.setattr(orchestrator, "ensure_pedagogical_runtime", lambda _host: runtime)
    oversized = "x" * 5000

    selected_runtime, directive = orchestrator._prepare_pedagogical_turn(
        host,
        user_text="Mình muốn thật sự hiểu core 7 và core 8",
        turn_id="turn-learn",
        recent_history=(
            {"role": "assistant", "content": oversized, "private_reasoning": oversized},
            {"role": "user", "content": "prior public turn"},
        ),
        now=200.0,
    )
    orchestrator._generate_public_reply(writer, teaching_directive=directive, user_text="learn")

    assert selected_runtime is runtime
    assert len(builder.calls) == 1
    assert builder.calls[0]["explicit_plan_request"] is True
    assert len(builder.calls[0]["current_turn"]) <= 1200
    assert set(builder.calls[0]["recent_public_history"][0]) == {"role", "content"}
    assert len(builder.calls[0]["recent_public_history"][0]["content"]) <= 600
    assert len(runtime.started) == 1
    assert isinstance(directive, TeachingDirective)
    assert directive.stop_after_chunk is True
    assert writer.calls[0]["teaching_directive"] is directive


def test_active_episode_observation_precedes_writer_and_can_cancel_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = _FakeRuntime({"episode_id": "active", "status": "waiting_user"})
    runtime.observed_result = SimpleNamespace(
        action=SimpleNamespace(directive=None),
        episode=SimpleNamespace(status="waiting_user"),
    )
    original_observe = runtime.observe_user_turn

    def observe(*args: Any, **kwargs: Any) -> Any:
        events.append("observe")
        return original_observe(*args, **kwargs)

    runtime.observe_user_turn = observe  # type: ignore[method-assign]
    host = SimpleNamespace(pedagogical_controller_enabled=True)
    monkeypatch.setattr(orchestrator, "ensure_pedagogical_runtime", lambda _host: runtime)
    writer = _FakeWriter(events)

    _, directive = orchestrator._prepare_pedagogical_turn(
        host,
        user_text="ok",
        turn_id="turn-active",
        recent_history=(),
        now=300.0,
    )
    orchestrator._generate_public_reply(writer, teaching_directive=directive, user_text="ok")

    assert events == ["observe", "writer"]
    assert runtime.observations == [("ok", (), 300.0)]
    assert "teaching_directive" not in writer.calls[0]


def test_active_episode_observation_receives_only_a_bounded_current_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _FakeRuntime({"episode_id": "active", "status": "waiting_user"})
    runtime.observed_result = SimpleNamespace(action=SimpleNamespace(directive=None))
    host = SimpleNamespace(pedagogical_controller_enabled=True)
    monkeypatch.setattr(orchestrator, "ensure_pedagogical_runtime", lambda _host: runtime)

    orchestrator._prepare_pedagogical_turn(
        host,
        user_text="x" * 5000,
        turn_id="turn-active-bounded",
        recent_history=(),
        now=350.0,
    )

    observed_text, evidence, observed_at = runtime.observations[0]
    assert len(observed_text) == 1200
    assert evidence == ()
    assert observed_at == 350.0


def test_valid_sealed_public_output_commits_one_matching_receipt() -> None:
    runtime = _FakeRuntime()
    directive = TeachingDirective(
        episode_id="episode-1",
        plan_revision=3,
        chunk_id="chunk-2",
        global_goal="goal",
        current_objective="objective",
        claim="claim",
        contrast="contrast",
        example_policy="allowed",
        max_ideas=2,
        max_sentences=4,
        allow_question=True,
        stop_after_chunk=True,
        allow_autonomous_resume=True,
    )
    decision = SimpleNamespace(parse_mode="json", failure_meta=None, should_speak=True)

    committed = orchestrator._commit_pedagogical_receipt(
        runtime,
        directive,
        public_text="A valid sealed teaching chunk",
        turn_id="turn-9",
        decision=decision,
        payload={"grounding_risk": {"allowed": True}},
        assistant_meta={},
        now=400.0,
    )

    assert committed is True
    assert len(runtime.receipts) == 1
    receipt, committed_at = runtime.receipts[0]
    assert (receipt.episode_id, receipt.plan_revision, receipt.chunk_id, receipt.turn_id) == (
        "episode-1", 3, "chunk-2", "turn-9",
    )
    assert receipt.text_signature.startswith("sha256:")
    assert len(receipt.text_signature) == 71
    assert committed_at == 400.0


@pytest.mark.parametrize(
    ("public_text", "assistant_meta", "decision", "payload"),
    (
        ("", {}, SimpleNamespace(parse_mode="json", failure_meta=None, should_speak=True), {}),
        ("text", None, SimpleNamespace(parse_mode="json", failure_meta=None, should_speak=True), {}),
        ("text", {}, SimpleNamespace(parse_mode="typed_discourse_fallback", failure_meta=None, should_speak=True), {}),
        ("text", {}, SimpleNamespace(parse_mode="json", failure_meta={"kind": "parse"}, should_speak=True), {}),
        ("text", {}, SimpleNamespace(parse_mode="json", failure_meta=None, should_speak=False), {}),
        (
            "text",
            {},
            SimpleNamespace(parse_mode="json", failure_meta=None, should_speak=True),
            {"grounding_risk": {"allowed": False}},
        ),
        (
            "text",
            {},
            SimpleNamespace(parse_mode="json", failure_meta=None, should_speak=True),
            {"utterance_degraded": True},
        ),
    ),
)
def test_failed_fallback_suppressed_or_empty_output_does_not_consume_chunk(
    public_text: str,
    assistant_meta: Mapping[str, Any] | None,
    decision: Any,
    payload: Mapping[str, Any],
) -> None:
    runtime = _FakeRuntime({"pending_chunk": {"chunk_id": "still-pending"}})
    directive = TeachingDirective(
        "episode", 1, "chunk", "goal", "objective", "claim", "", "allowed", 2, 4,
        True, True, True,
    )

    committed = orchestrator._commit_pedagogical_receipt(
        runtime,
        directive,
        public_text=public_text,
        turn_id="turn-failed",
        decision=decision,
        payload=payload,
        assistant_meta=assistant_meta,
        now=500.0,
    )

    assert committed is False
    assert runtime.receipts == []
    assert runtime.snapshot()["active_episode"]["pending_chunk"]["chunk_id"] == "still-pending"


def test_pedagogy_settings_default_off_parse_clamp_and_catalog(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ERIS_PEDAGOGICAL_CONTROLLER_ENABLED", "true")
    env_settings = RuntimeSettingsStore.from_env_compat()
    assert env_settings["pedagogy"]["enabled"] is True
    monkeypatch.delenv("ERIS_PEDAGOGICAL_CONTROLLER_ENABLED")

    store = RuntimeSettingsStore(tmp_path / "runtime-settings.json")
    defaults = store.defaults()["pedagogy"]
    assert defaults["enabled"] is False
    result = store.apply_patch({
        "pedagogy": {
            "minimum_dwell_seconds": -5,
            "maximum_dwell_seconds": 100000,
            "max_autonomous_chunks": 99,
            "max_repair_attempts": 99,
            "max_consecutive_stalls": 99,
            "episode_expiry_seconds": 5,
        }
    })
    values = result.settings["pedagogy"]
    assert values == {
        "enabled": False,
        "minimum_dwell_seconds": 0.5,
        "maximum_dwell_seconds": 300.0,
        "max_autonomous_chunks": 8,
        "max_repair_attempts": 5,
        "max_consecutive_stalls": 8,
        "episode_expiry_seconds": 60.0,
    }

    fields = {item["path"]: item for item in build_settings_catalog()["fields"]}
    assert fields["pedagogy.enabled"]["default"] is False
    assert fields["pedagogy.minimum_dwell_seconds"]["min"] == 0.5
    assert fields["pedagogy.maximum_dwell_seconds"]["max"] == 300.0
