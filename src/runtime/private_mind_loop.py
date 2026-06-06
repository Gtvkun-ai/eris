# -*- coding: utf-8 -*-
"""
runtime/private_mind_loop.py
============================

Runtime loop cho private mind 5 phase:
A. contracts + concern store
B. evidence dossier
C. 4 mini-evaluator API/rules
D. Gemma inner synthesizer
E. state mutation + surface valve

Loop này không tự nói với user. Nó chỉ cập nhật state và enqueue surface impulse
nếu SurfaceValve cho phép. Vì dĩ nhiên, raw InternalJudgment mà nổi thẳng ra
public thì đó không phải chiều sâu, đó là logcat có trang điểm.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from cortex.private_mind import (
    ConcernStore,
    EvidenceDossierBuilder,
    GemmaInnerSynthesizer,
    MiniEvaluatorPipeline,
    PrivateMindTickResult,
    StateMutationBus,
    SurfaceValve,
)
from cortex.private_mind.contracts import SurfaceCandidate, to_plain
from eris_secrets import apply_secrets_to_environ
from runtime.private_mind_model_adapter import RuntimePrivateMindModelAdapter


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}


@dataclass(slots=True)
class PrivateMindLoopConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_PRIVATE_MIND_ENABLED", True))
    min_interval_seconds: float = field(default_factory=lambda: float(os.getenv("ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC", "12") or 12.0))
    min_fragments_for_synthesis: int = 3
    concern_store_path: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_CONCERNS_PATH", "") or ""))
    log_ticks: bool = field(default_factory=lambda: _env_flag("ERIS_PRIVATE_MIND_LOG_TICKS", True))


class PrivateMindLoop:
    """Orchestrator của private mind."""

    def __init__(
        self,
        *,
        config: PrivateMindLoopConfig | None = None,
        concern_store: ConcernStore | None = None,
        dossier_builder: EvidenceDossierBuilder | None = None,
        evaluator_pipeline: MiniEvaluatorPipeline | None = None,
        synthesizer: GemmaInnerSynthesizer | None = None,
        mutation_bus: StateMutationBus | None = None,
        surface_valve: SurfaceValve | None = None,
        model_adapter: Any = None,
        logger: Any = None,
    ) -> None:
        self.config = config or PrivateMindLoopConfig()
        self.logger = logger
        self.model_adapter = model_adapter
        self.concern_store = concern_store or ConcernStore(path=self._resolve_concern_path(), logger=logger)
        self.dossier_builder = dossier_builder or EvidenceDossierBuilder()
        self.evaluator_pipeline = evaluator_pipeline or MiniEvaluatorPipeline(model_adapter=model_adapter)
        self.synthesizer = synthesizer or GemmaInnerSynthesizer(model_adapter=model_adapter, min_fragments_for_model=self.config.min_fragments_for_synthesis)
        self.mutation_bus = mutation_bus or StateMutationBus(logger=logger)
        self.surface_valve = surface_valve or SurfaceValve()
        self.last_tick_at = 0.0
        self.last_result: PrivateMindTickResult | None = None
        self.last_digest: dict[str, Any] = {}

    @classmethod
    def from_runtime(cls, *, runtime_owner: Any, llm_service: Any = None, logger: Any = None) -> "PrivateMindLoop | None":
        apply_secrets_to_environ()
        config = PrivateMindLoopConfig()
        if not config.enabled:
            return None
        model_adapter = RuntimePrivateMindModelAdapter.from_env(llm_service=llm_service, logger=logger)
        return cls(config=config, model_adapter=model_adapter, logger=logger)

    def tick(
        self,
        *,
        user_text: str = "",
        channel: str = "autonomous",
        snapshot: Any = None,
        observer_frame: Any = None,
        wake_decision: Any = None,
        memory_core: Any = None,
        state_committer: Any = None,
        memory_hits: Iterable[Any] = (),
        session_turn_ledger: Any = None,
        internal_agenda: Any = None,
        thought_stream: Any = None,
        surface_candidate_queue: list[Any] | None = None,
        runtime_owner: Any = None,
        surface_outcome: Mapping[str, Any] | None = None,
        force: bool = False,
    ) -> PrivateMindTickResult | None:
        if not self.config.enabled:
            return None
        now = time.time()
        if not force and now - self.last_tick_at < max(1.0, self.config.min_interval_seconds):
            return self.last_result
        self.last_tick_at = now
        api_status = self._model_api_status()
        dossier = self.dossier_builder.build(
            user_text=user_text,
            channel=channel,
            snapshot=snapshot,
            observer_frame=observer_frame,
            wake_decision=wake_decision,
            memory_core=memory_core,
            memory_hits=memory_hits,
            session_turn_ledger=session_turn_ledger,
            internal_agenda=internal_agenda,
            concern_store=self.concern_store,
            surface_outcome=surface_outcome,
            metadata={
                "private_mind_tick_at": now,
                "api_degraded": bool(api_status.get("api_degraded", False)),
                "api_invalid_json": bool(api_status.get("api_invalid_json", False)),
                "api_last_error": str(api_status.get("last_error", "") or ""),
            },
        )
        fragments = self.evaluator_pipeline.evaluate(dossier)
        concerns = self.concern_store.update_from_fragments(fragments)
        judgment = self.synthesizer.synthesize(dossier=dossier, fragments=fragments)
        if judgment is not None:
            self.concern_store.update_from_judgment(judgment.private_concern_update)
        candidate = self.surface_valve.filter(judgment)
        applied = self.mutation_bus.apply(
            judgment,
            agenda_stack=internal_agenda,
            memory_core=memory_core,
            state_committer=state_committer,
            thought_stream=thought_stream,
            surface_candidate_queue=surface_candidate_queue,
            concern_store=self.concern_store,
            runtime_owner=runtime_owner,
        ) if judgment is not None else ()
        # Enqueue bản SurfaceImpulse đã lọc, không enqueue raw candidate nếu SurfaceArbiter đang dùng impulse.
        if candidate is not None and surface_candidate_queue is not None:
            impulse = self.surface_valve.to_surface_impulse(candidate)
            if impulse is not None:
                existing = {str(getattr(x, "id", "") or getattr(x, "topic_seed", "")) for x in surface_candidate_queue}
                key = str(getattr(impulse, "topic_seed", getattr(candidate, "id", "")) or "")
                if key not in existing:
                    surface_candidate_queue.append(impulse)
                    while len(surface_candidate_queue) > 12:
                        surface_candidate_queue.pop(0)
        result = PrivateMindTickResult(
            dossier=dossier,
            fragments=fragments,
            concerns=concerns,
            judgment=judgment,
            applied_mutations=applied,
            surface_candidate=candidate,
            debug={
                "model_used": bool(self.model_adapter),
                "fragment_count": len(fragments),
                "concern_count": len(self.concern_store),
                "mutation_reports": to_plain(applied),
            },
        )
        self.last_result = result
        self.last_digest = self.digest(surface_queue=surface_candidate_queue)
        self._log_tick(result)
        return result

    def digest(self, *, surface_queue: list[Any] | None = None) -> dict[str, Any]:
        """Compact dev payload for private mind state.

        This intentionally exposes summaries and mutation reports, not raw prompts.
        """

        result = self.last_result
        judgment = getattr(result, "judgment", None) if result is not None else None
        dossier = getattr(result, "dossier", None) if result is not None else None
        fragments = tuple(getattr(result, "fragments", ()) or ()) if result is not None else ()
        fragment_dicts = [to_plain(fragment.to_dict() if callable(getattr(fragment, "to_dict", None)) else fragment) for fragment in fragments[:12]]
        judgment_dict = to_plain(judgment.to_dict()) if judgment is not None and callable(getattr(judgment, "to_dict", None)) else None
        dossier_dict = to_plain(dossier.to_dict()) if dossier is not None and callable(getattr(dossier, "to_dict", None)) else {}
        state_mutations = to_plain(tuple(getattr(judgment, "state_mutations", ()) or ())) if judgment is not None else ()
        applied_mutations = to_plain(getattr(result, "applied_mutations", ()) if result is not None else ())
        surface_queue_payload = [
            item.to_context() if callable(getattr(item, "to_context", None)) else to_plain(item)
            for item in tuple(surface_queue or ())[:8]
        ]
        current = {
            "dominant_judgment": str(getattr(judgment, "dominant_judgment", "") or "") if judgment is not None else "",
            "confidence": round(float(getattr(judgment, "confidence", 0.0) or 0.0), 3) if judgment is not None else 0.0,
            "pressure": round(float(getattr(judgment, "pressure", 0.0) or 0.0), 3) if judgment is not None else 0.0,
            "source": str(getattr(judgment, "source", "") or "") if judgment is not None else "",
            "evidence_ids": list(tuple(getattr(judgment, "evidence_ids", ()) or ())[:12]) if judgment is not None else [],
            "surface_candidate": (
                to_plain(getattr(result, "surface_candidate", None))
                if result is not None and getattr(result, "surface_candidate", None) is not None
                else None
            ),
        }
        retained = {
            "concerns": list(self.concern_store.snapshots(limit=8)),
            "speech_bias": to_plain(getattr(self.mutation_bus.bias_state, "speech_bias", {})),
            "thought_pressure": round(float(getattr(self.mutation_bus.bias_state, "thought_stream_pressure", 0.0) or 0.0), 3),
            "inquiry_plan": to_plain(getattr(self.mutation_bus.bias_state, "inquiry_plan", [])[-8:]),
            "belief_core_shadow": to_plain(getattr(self.mutation_bus.bias_state, "belief_core", {})),
        }
        pulled = {
            "mutations": applied_mutations,
            "surface_queue": surface_queue_payload,
        }
        temporary = {
            "fragments": [
                {
                    "id": str(getattr(fragment, "id", "") or ""),
                    "source": str(getattr(fragment, "source", "") or ""),
                    "claim": str(getattr(fragment, "claim", "") or "")[:240],
                    "score": round(float(getattr(fragment, "score", 0.0) or 0.0), 3),
                    "pressure": round(float(getattr(fragment, "pressure", 0.0) or 0.0), 3),
                    "hypotheses": to_plain(tuple(getattr(fragment, "hypotheses", ()) or ())[:3]),
                    "suggested_question": str(getattr(fragment, "suggested_question", "") or "")[:180],
                }
                for fragment in fragments[:8]
            ],
            "open_questions": list(tuple(getattr(judgment, "open_questions", ()) or ())[:6]) if judgment is not None else [],
        }
        debug_api = {}
        status = getattr(self.model_adapter, "debug_status", None)
        if callable(status):
            try:
                debug_api = status()
            except Exception:
                debug_api = {"error": "debug_status_failed"}
        else:
            debug_api = {"enabled": bool(self.model_adapter), "provider": "", "model": "", "cost_known": False}
        future_bias = {
            "speech_bias": retained["speech_bias"],
            "inquiry_plan": retained["inquiry_plan"],
            "thought_pressure": retained["thought_pressure"],
            "belief_core_shadow": retained["belief_core_shadow"],
        }
        menu = {
            "snapshot_current": {
                "last_tick_at": round(float(self.last_tick_at or 0.0), 3),
                "runtime_state": dossier_dict.get("runtime_state", {}),
                "recent_user_turns": dossier_dict.get("recent_user_turns", []),
                "surface_outcome": dossier_dict.get("surface_outcome", {}),
            },
            "current_thought": current,
            "retained_thoughts": retained,
            "pulled_thoughts": pulled,
            "temporary_thoughts": temporary,
            "open_concerns": list(self.concern_store.snapshots(limit=16)),
            "evidence_dossier": dossier_dict,
            "mini_evaluators": fragment_dicts,
            "inner_judgment": judgment_dict,
            "state_mutations": {
                "requested": state_mutations,
                "applied": applied_mutations,
            },
            "future_bias": future_bias,
            "surface_queue": surface_queue_payload,
            "speech_silence_reason": {},
            "debug_api": debug_api,
        }
        return {
            "last_tick_at": round(float(self.last_tick_at or 0.0), 3),
            "current": current,
            "retained": retained,
            "pulled": pulled,
            "temporary": temporary,
            "menu": menu,
            **menu,
            "debug": to_plain(getattr(result, "debug", {}) if result is not None else {}),
        }

    def drain_surface_impulses(self, queue: list[Any], *, limit: int = 4) -> tuple[Any, ...]:
        items: list[Any] = []
        while queue and len(items) < max(1, limit):
            items.append(queue.pop(0))
        return tuple(items)

    def _model_api_status(self) -> dict[str, Any]:
        status_fn = getattr(self.model_adapter, "debug_status", None)
        if not callable(status_fn):
            return {"api_degraded": False, "api_invalid_json": False, "last_error": ""}
        try:
            status = status_fn()
        except Exception:
            return {"api_degraded": True, "api_invalid_json": False, "last_error": "debug_status_failed"}
        last_error = str(status.get("last_error", "") or "") if isinstance(status, Mapping) else ""
        return {
            "api_degraded": bool(last_error),
            "api_invalid_json": "invalid_json" in last_error,
            "last_error": last_error,
        }

    def _resolve_concern_path(self) -> str | None:
        if self.config.concern_store_path:
            return self.config.concern_store_path
        root = os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core")
        return str(Path(root) / "private_concerns.json")

    def _log_tick(self, result: PrivateMindTickResult) -> None:
        if not self.config.log_ticks:
            return
        fn = getattr(self.logger, "info", None) if self.logger is not None else None
        if not callable(fn):
            return
        judgment = result.judgment
        fn(
            "[PrivateMind] fragments=%d concerns=%d judgment=%s confidence=%.2f pressure=%.2f surface=%s mutations=%d",
            len(result.fragments),
            len(result.concerns),
            "yes" if judgment else "no",
            float(getattr(judgment, "confidence", 0.0) or 0.0),
            float(getattr(judgment, "pressure", 0.0) or 0.0),
            "yes" if result.surface_candidate else "no",
            len(result.applied_mutations),
        )
