# -*- coding: utf-8 -*-
"""
runtime/private_mind_loop.py
============================

Runtime loop cho private mind 5 phase:
A. contracts + concern store
B. evidence dossier
C. 4 mini-evaluator API/rules
D. local-model inner synthesizer
E. state mutation + surface valve

Loop này không tự nói với user. Nó chỉ cập nhật state và enqueue surface impulse
nếu SurfaceValve cho phép. Vì dĩ nhiên, raw InternalJudgment mà nổi thẳng ra
public thì đó không phải chiều sâu, đó là logcat có trang điểm.
"""

from __future__ import annotations
from core.di import resolve_dependency

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from cortex.private_mind import (
    USER_MODEL_EVALUATOR_NAME,
    ConcernStore,
    EvidenceDossierBuilder,
    LocalModelInnerSynthesizer,
    MiniEvaluatorPipeline,
    PrivateMindTickResult,
    StateMutationBus,
    SurfaceValve,
    ThoughtContinuityStore,
    UserModelStore,
    default_user_model_path,
)
from cortex.existential_anchor import AnchorSystem
from cortex.private_mind.contracts import SurfaceCandidate, ThoughtFragment, to_plain
from cortex.private_mind.inner_diary_renderer import InnerDiaryRenderer
from cortex.private_mind.inner_diary_writer import InnerDiaryWriter
from cortex.private_mind.residue_curator import DiaryResidueStore
from cortex.private_mind.thought_shards import ThoughtShardStore
from eris_secrets import apply_secrets_to_environ
from runtime.private_mind_model_adapter import PrivateMindAdapterPool, RuntimePrivateMindModelAdapter
from runtime.live2d_affect_bridge import emit_runtime_affect


_LOG = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "none"}


def _env_float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 300.0) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(float(maximum), value))


def _gemini_background_timeout_seconds() -> float:
    default = _env_float("ERIS_PRIVATE_MIND_TIMEOUT", 60.0, minimum=5.0, maximum=300.0)
    return _env_float("ERIS_PRIVATE_MIND_GEMINI_TIMEOUT", default, minimum=5.0, maximum=300.0)


@dataclass(slots=True)
class PrivateMindLoopConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_PRIVATE_MIND_ENABLED", True))
    # PDF annotation, pages 14-15: timer alone is not a remote trigger.  Keep
    # a modest debounce for real deltas and a separate long idle consolidation.
    min_interval_seconds: float = field(default_factory=lambda: max(30.0, float(os.getenv("ERIS_PRIVATE_MIND_MIN_INTERVAL_SEC", "45") or 45.0)))
    idle_consolidation_seconds: float = field(default_factory=lambda: max(180.0, float(os.getenv("ERIS_PRIVATE_MIND_IDLE_CONSOLIDATION_SEC", "240") or 240.0)))
    min_fragments_for_synthesis: int = field(default_factory=lambda: max(1, int(os.getenv("ERIS_PRIVATE_MIND_MIN_FRAGMENTS_SYNTH", "2") or 2)))
    concern_store_path: str = field(default_factory=lambda: str(os.getenv("ERIS_PRIVATE_MIND_CONCERNS_PATH", "") or ""))
    user_model_path: str = field(default_factory=lambda: str(os.getenv("ERIS_USER_MODEL_PATH", "") or ""))
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
        synthesizer: LocalModelInnerSynthesizer | None = None,
        mutation_bus: StateMutationBus | None = None,
        surface_valve: SurfaceValve | None = None,
        continuity_store: ThoughtContinuityStore | None = None,
        user_model_store: UserModelStore | None = None,
        model_adapter: Any = None,
        logger: Any = None,
    ) -> None:
        self.config = resolve_dependency(config, lambda: PrivateMindLoopConfig())
        self.logger = logger
        self.model_adapter = model_adapter
        self.concern_store = resolve_dependency(concern_store, lambda: ConcernStore(path=self._resolve_concern_path(), logger=logger))
        # Mô_Hình_bạn: chân dung bền vững về Người_Dùng (spec eris-existential-anchor).
        self.user_model_store = resolve_dependency(user_model_store, lambda: UserModelStore(path=self._resolve_user_model_path(), logger=logger))
        # Trục neo hiện sinh: gắn-bó/sợ/bóng-tối/lừa-dối. Ship an toàn (công tắc tắt),
        # đọc Mô_Hình_bạn để phái sinh ý nghĩa/gắn bó.
        self.anchor_system = AnchorSystem.from_env(user_model_store=self.user_model_store, logger=logger)
        self.dossier_builder = resolve_dependency(dossier_builder, lambda: EvidenceDossierBuilder())
        self.evaluator_pipeline = resolve_dependency(evaluator_pipeline, lambda: MiniEvaluatorPipeline(model_adapter=model_adapter))
        self.synthesizer = resolve_dependency(synthesizer, lambda: LocalModelInnerSynthesizer(model_adapter=model_adapter, min_fragments_for_model=self.config.min_fragments_for_synthesis))
        self.mutation_bus = resolve_dependency(mutation_bus, lambda: StateMutationBus(logger=logger))
        self.surface_valve = resolve_dependency(surface_valve, lambda: SurfaceValve())
        # Dòng suy nghĩ liên tục: nhớ mạch nghĩ cũ, nối tiếp thay vì nghĩ lại từ đầu.
        self.continuity = resolve_dependency(continuity_store, lambda: ThoughtContinuityStore.from_env(logger=logger))
        # V79: spool riêng cho mảnh cognition bị suppress/packed và stimulus bị
        # coalesce. Nó tồn tại qua restart để Inner Diary không phụ thuộc tick cuối.
        self.residue_store = DiaryResidueStore.from_env(logger=logger)
        # V80: Gemma sở hữu 5 micro-thought live; DeepSeek chỉ làm deep reflection.
        # Store này giữ cả shard history lẫn reflection episode qua restart.
        self.thought_shards = ThoughtShardStore.from_env(logger=logger)
        self._last_individual_projection: dict[str, Any] = {}
        self.last_tick_at = 0.0
        self.last_result: PrivateMindTickResult | None = None
        self._last_trigger_signature = ""
        self.last_digest: dict[str, Any] = {}
        # Snapshot cảm xúc liên tục thật (valence/arousal/...) chụp ở tick gần nhất,
        # để Inner Diary vẽ bảng cảm xúc theo state thật thay vì hằng số gán cứng.
        self._affect_snapshot: dict[str, Any] = {}
        # Inner Diary có owner riêng. Với PrivateMindAdapterPool, diary_adapter chỉ
        # gọi LlmService.diary_client (một DeepSeek worker role được chọn rõ ràng).
        # Không fallback sang lane khác theo mặc định; thiếu worker thì renderer dùng
        # dữ kiện thô, trung thực hơn việc companion âm thầm giả làm nhật ký.
        from runtime.architecture_flags import inner_diary_deep_reflection_enabled, inner_diary_model_enabled
        # V80: DeepSeek diary worker được giữ làm deep-reflection owner. Ưu tiên
        # pool để metadata owner/model đi kèm output; fallback về adapter con chỉ
        # khi caller inject một adapter đơn trong test/harness.
        diary_adapter = None
        if inner_diary_model_enabled() and inner_diary_deep_reflection_enabled():
            if callable(getattr(model_adapter, "deep_reflect_inner_diary", None)):
                diary_adapter = model_adapter
            else:
                diary_adapter = getattr(model_adapter, "diary_adapter", None)
            if diary_adapter is None and callable(getattr(model_adapter, "write_inner_diary", None)):
                diary_adapter = model_adapter
        diary_fallback = (
            RuntimePrivateMindModelAdapter.diary_fallback_from_env(logger=logger)
            if _env_flag("ERIS_INNER_DIARY_ALLOW_FALLBACK", False)
            else None
        )
        self.diary_writer = InnerDiaryWriter(
            adapter=diary_adapter,
            fallback_adapter=diary_fallback,
            state_store=self.thought_shards,
            logger=logger,
        )
        self._gemini_background_lock = threading.Lock()
        self._gemini_background_active: set[str] = set()

    def _boundary_note(self, operation: str, exc: Exception) -> None:
        method = getattr(self.logger, "debug", None)
        if callable(method):
            try:
                method("[private mind] %s degraded: %s", operation, exc)
                return
            except Exception as log_exc:
                _LOG.debug("private-mind logger failed: %s", log_exc, exc_info=log_exc)
        _LOG.debug("[private mind] %s degraded: %s", operation, exc, exc_info=exc)

    @classmethod
    def from_runtime(cls, *, runtime_owner: Any, llm_service: Any = None, logger: Any = None) -> "PrivateMindLoop | None":
        apply_secrets_to_environ()
        config = PrivateMindLoopConfig()
        if not config.enabled:
            return None
        model_adapter = PrivateMindAdapterPool.from_env(llm_service=llm_service, logger=logger)
        kernel = getattr(runtime_owner, "epistemic_kernel", None)
        if kernel is not None and getattr(kernel, "authoritative", False):
            from cortex.epistemic import EpistemicUserModelProjection
            return cls(
                config=config,
                model_adapter=model_adapter,
                user_model_store=EpistemicUserModelProjection(kernel),
                logger=logger,
            )
        memory_kernel = getattr(runtime_owner, "memory_kernel", None)
        living_user = getattr(memory_kernel, "living_user", None)
        if living_user is not None:
            # Khi epistemic kernel không authoritative, private mind dùng projection
            # của living profile thay vì tạo thêm user_model.json cạnh tranh.
            from memory.living_user import LivingUserModelProjection
            return cls(
                config=config,
                model_adapter=model_adapter,
                user_model_store=LivingUserModelProjection(living_user),
                logger=logger,
            )
        return cls(config=config, model_adapter=model_adapter, logger=logger)

    def tick(
        self,
        *,
        user_text: str = "",
        channel: str = "autonomous",
        snapshot: Any = None,
        observer_frame: Any = None,
        attention_signal: Any = None,
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
        # PDF annotation, pages 14-15 and 20: background thresholds adapt to
        # provider pressure.  This avoids producing four evaluator requests and
        # one synthesis request merely to have the broker reject them separately.
        private_mind_advice = {
            "allowed": True,
            "cooldown_multiplier": 1.0,
            "pressure_score": 0.0,
        }
        if not force:
            try:
                from runtime.inference_broker import GLOBAL_INFERENCE_BROKER

                provider = str(
                    os.getenv(
                        "ERIS_PRIVATE_MIND_PROVIDER",
                        os.getenv("ERIS_DAYDREAM_PROVIDER", "gemini"),
                    )
                    or "gemini"
                ).strip().lower()
                private_mind_advice = GLOBAL_INFERENCE_BROKER.optional_lane_advice(
                    "private_mind", provider=provider
                )
            except Exception as exc:
                self._boundary_note("inference_broker.advice", exc)
            if not bool(private_mind_advice.get("allowed", True)):
                return self.last_result

        trigger_signature = self._trigger_signature(
            user_text=user_text,
            channel=channel,
            snapshot=snapshot,
            observer_frame=observer_frame,
            surface_outcome=surface_outcome,
            surface_candidate_queue=surface_candidate_queue,
        )
        has_delta = bool(trigger_signature and trigger_signature != self._last_trigger_signature)
        cooldown_multiplier = max(
            1.0, float(private_mind_advice.get("cooldown_multiplier", 1.0) or 1.0)
        )
        effective_min_interval = self.config.min_interval_seconds * cooldown_multiplier
        effective_idle_interval = self.config.idle_consolidation_seconds * cooldown_multiplier
        idle_due = (now - self.last_tick_at) >= effective_idle_interval

        if not force:
            # A chat turn owns the provider. PrivateMind keeps its previous state
            # instead of asking the broker to reject four evaluator calls one by one.
            try:
                from runtime.inference_broker import GLOBAL_INFERENCE_BROKER
                if GLOBAL_INFERENCE_BROKER.user_turn_active():
                    return self.last_result
            except Exception as exc:
                self._boundary_note("inference_broker.user_turn", exc)
            if not has_delta and not idle_due:
                return self.last_result
            if has_delta and now - self.last_tick_at < effective_min_interval:
                return self.last_result

        self.last_tick_at = now
        self._last_trigger_signature = trigger_signature or self._last_trigger_signature
        self._capture_affect(runtime_owner)
        api_status = self._model_api_status()
        epistemic_kernel = getattr(runtime_owner, "epistemic_kernel", None) if runtime_owner is not None else None
        user_model_snapshot = (
            epistemic_kernel.user_model_snapshot()
            if epistemic_kernel is not None
            else self.user_model_store.snapshot_for_dossier()
        )
        dossier = self.dossier_builder.build(
            user_text=user_text,
            channel=channel,
            snapshot=snapshot,
            observer_frame=observer_frame,
            attention_signal=attention_signal,
            memory_core=memory_core,
            memory_hits=memory_hits,
            session_turn_ledger=session_turn_ledger,
            internal_agenda=internal_agenda,
            concern_store=self.concern_store,
            thought_stream=thought_stream,
            surface_candidate_queue=surface_candidate_queue or (),
            runtime_owner=runtime_owner,
            surface_outcome=surface_outcome,
            user_model_snapshot=user_model_snapshot,
            metadata={
                "private_mind_tick_at": now,
                "api_degraded": bool(api_status.get("api_degraded", False)),
                "api_invalid_json": bool(api_status.get("api_invalid_json", False)),
                "api_last_error": str(api_status.get("last_error", "") or ""),
                "api_degraded_cause": str(api_status.get("api_degraded_cause", "") or ""),
            },
        )
        # Tính liên tục: nạp mạch nghĩ gần đây + thread dang dở để model nghĩ TIẾP,
        # không nghĩ lại từ con số không.
        try:
            dossier.metadata["recent_thoughts"] = self.continuity.recent_for_prompt()
            dossier.metadata["unresolved_threads"] = self.continuity.unresolved_for_prompt()
            # Những stimulus từng bị coalesce/busy được đưa trở lại như evidence
            # "chưa xử lý", không giả thành thought đã xảy ra.
            dossier.metadata["residue_continuity"] = self.residue_store.continuity_for_prompt(now=now)
        except Exception as exc:
            self._boundary_note("continuity.prompt_projection", exc)
        from runtime.inference_broker import inference_context
        with inference_context(
            "private_mind",
            optional=True,
            timeout_seconds=90.0,
            cancel_scope="background:private_mind",
            coalesce_key="private_mind:latest_state",
            metadata={
                "channel": channel,
                "state_delta": has_delta,
                "idle_due": idle_due,
                "pressure_score": float(private_mind_advice.get("pressure_score", 0.0) or 0.0),
            },
        ):
            fragments = self.evaluator_pipeline.evaluate(dossier)
        if not fragments:
            post_api = self._model_api_status()
            last_error = str(post_api.get("last_error", "") or "").casefold()
            if "busy" in last_error or "roleworkerbusy" in last_error:
                self.capture_unprocessed_stimulus(
                    text=self._dossier_residue_text(dossier),
                    reason="deepseek_inner_busy",
                    source_ids=dossier.evidence_ids,
                    salience=0.62,
                    now=now,
                )
        # Nghĩ-bổ-sung cho mạch dang dở: CHỈ khi không có bằng chứng mới nào và có
        # thread đến hạn khơi lại (cooldown lớn + đủ áp lực). Đây không phải nhịp đồng hồ.
        if not fragments and self.continuity.has_followup_due():
            fragments = self._followup_fragments(dossier)
        # Tách dòng fragment hướng-bạn sang Mô_Hình_bạn; phần còn lại nuôi ConcernStore.
        # Giữ tách bạch lifecycle theo QĐ-2: chân dung bạn không trộn với bận tâm task.
        user_fragments = tuple(f for f in fragments if f.source == USER_MODEL_EVALUATOR_NAME)
        other_fragments = tuple(f for f in fragments if f.source != USER_MODEL_EVALUATOR_NAME)
        if epistemic_kernel is not None:
            # V2 is the only writable user-belief authority. Private prose is
            # retained as a non-storable hypothesis, never as self-evidence.
            epistemic_kernel.ingest_private_hypotheses(fragments)
        elif user_fragments:
            self.user_model_store.update_from_fragments(user_fragments)
        if epistemic_kernel is None:
            self.user_model_store.decay(now=now)
        concerns = self.concern_store.update_from_fragments(other_fragments)

        # Trục neo hiện sinh: cập nhật ý nghĩa/gắn bó/bóng tối từ tín hiệu tick.
        # An toàn theo mặc định (công tắc tắt → không đổi hành vi live).
        self._update_anchor_system(dossier=dossier, runtime_owner=runtime_owner)
        with inference_context(
            "private_mind",
            optional=True,
            timeout_seconds=90.0,
            cancel_scope="background:private_mind",
            coalesce_key="private_mind:latest_state",
            metadata={
                "phase": "synthesis",
                "state_delta": has_delta,
                "pressure_score": float(private_mind_advice.get("pressure_score", 0.0) or 0.0),
            },
        ):
            judgment = self.synthesizer.synthesize(dossier=dossier, fragments=fragments)
        if judgment is not None:
            self.concern_store.update_from_judgment(judgment.private_concern_update)
            self._record_continuity(judgment)
        # Q1: tự khép concern đã dịu đủ lâu, để lại dấu 'đã nguôi'.
        try:
            self.concern_store.auto_resolve_settled(now=now)
        except Exception as exc:
            self._boundary_note("concern.auto_resolve", exc)
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

        # V79: mọi cognition thật được giữ như residue trước khi tick kết thúc.
        # Public silence/suppression không còn đồng nghĩa với private amnesia.
        self._capture_tick_residue(
            fragments=fragments,
            judgment=judgment,
            filtered_candidate=candidate,
            now=now,
        )
        self._run_gemini_background(
            "private_residue_curator",
            lambda: self._maybe_consolidate_residue(now=now),
        )
        # V80: sau khi raw cognition/state đã ổn định, Gemma cập nhật 5 shard ngắn.
        # Đây là private-only state; không enqueue public candidate.
        self._run_gemini_background(
            "private_thought_shards",
            lambda: self._maybe_refresh_thought_shards(
                dossier=dossier,
                fragments=fragments,
                judgment=judgment,
                filtered_candidate=candidate,
                runtime_owner=runtime_owner,
                now=now,
            ),
        )

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
        # Mutation bus có thể vừa thay đổi PersistentInternalState. Chụp lại sau
        # synthesis để Live2D và Inner Diary thấy state mới của chính tick này,
        # không phải ảnh chụp trước khi não phụ làm việc.
        self._capture_affect(runtime_owner)
        self.last_digest = self.digest(surface_queue=surface_candidate_queue)
        fragment_pressure = max((float(getattr(item, "pressure", 0.0) or 0.0) for item in fragments), default=0.0)
        fragment_confidence = max((float(getattr(item, "confidence", 0.0) or 0.0) for item in fragments), default=0.0)
        judgment_pressure = float(getattr(judgment, "pressure", 0.0) or 0.0) if judgment is not None else 0.0
        judgment_confidence = float(getattr(judgment, "confidence", 0.0) or 0.0) if judgment is not None else 0.0
        emit_runtime_affect(
            runtime_owner,
            affect=self._affect_snapshot,
            source=f"private_mind:{str(api_status.get('provider', '') or 'local')}:{channel or 'autonomous'}",
            thought_pressure=max(fragment_pressure, judgment_pressure),
            confidence=max(fragment_confidence, judgment_confidence),
            diary_updated=bool(self.last_digest.get("inner_diary")),
        )
        self._log_tick(result)
        return result

    # ---------------------------------------------------------------- residue

    def capture_residue(
        self,
        *,
        kind: str,
        text: Any,
        source_ids: Iterable[Any] = (),
        salience: float = 0.5,
        provenance: str = "private_runtime",
        lane_hint: str = "diary",
        metadata: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> str:
        try:
            return self.residue_store.capture(
                kind=kind,
                text=text,
                source_ids=tuple(source_ids or ()),
                salience=salience,
                provenance=provenance,
                lane_hint=lane_hint,
                metadata=metadata,
                now=now,
            )
        except Exception as exc:
            self._boundary_note("residue.capture", exc)
            return ""

    def capture_unprocessed_stimulus(
        self,
        *,
        text: Any,
        reason: str,
        source_ids: Iterable[Any] = (),
        salience: float = 0.55,
        metadata: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> str:
        try:
            return self.residue_store.capture_unprocessed_stimulus(
                text=text,
                source_ids=tuple(source_ids or ()),
                reason=reason,
                salience=salience,
                metadata=metadata,
                now=now,
            )
        except Exception as exc:
            self._boundary_note("residue.capture_unprocessed", exc)
            return ""

    def capture_suppressed_public_candidate(
        self,
        candidate: Any = None,
        *,
        text: str = "",
        reason: str = "governor_silence",
        now: float | None = None,
    ) -> str:
        payload = candidate.to_dict() if callable(getattr(candidate, "to_dict", None)) else {}
        if not isinstance(payload, Mapping):
            payload = {}
        content = (
            text
            or str(payload.get("topic") or payload.get("topic_seed") or payload.get("text") or "")
            or str(getattr(candidate, "topic", "") or getattr(candidate, "topic_seed", "") or "")
        )
        refs = payload.get("evidence_refs") or payload.get("evidence_ids") or ()
        confidence = payload.get("confidence", getattr(candidate, "confidence", 0.55))
        return self.capture_residue(
            kind="suppressed_public_candidate",
            text=content,
            source_ids=tuple(refs or ()),
            salience=max(0.5, min(0.9, float(confidence or 0.55))),
            provenance=f"public_suppressed:{reason}",
            lane_hint="diary",
            metadata={"reason": str(reason or "")[:120]},
            now=now,
        )

    def _capture_tick_residue(self, *, fragments: Iterable[Any], judgment: Any, filtered_candidate: Any, now: float) -> None:
        for fragment in tuple(fragments or ()):
            claim = str(getattr(fragment, "claim", "") or "")
            if not claim:
                continue
            self.capture_residue(
                kind="private_fragment",
                text=claim,
                source_ids=tuple(getattr(fragment, "evidence_ids", ()) or ()) + (str(getattr(fragment, "id", "") or ""),),
                salience=max(float(getattr(fragment, "score", 0.0) or 0.0), float(getattr(fragment, "pressure", 0.0) or 0.0)),
                provenance=f"deepseek_fragment:{str(getattr(fragment, 'source', '') or 'unknown')}",
                lane_hint="diary",
                now=now,
            )
        if judgment is not None:
            dominant = str(getattr(judgment, "dominant_judgment", "") or "")
            if dominant:
                self.capture_residue(
                    kind="private_judgment",
                    text=dominant,
                    source_ids=tuple(getattr(judgment, "evidence_ids", ()) or ()),
                    salience=max(float(getattr(judgment, "confidence", 0.0) or 0.0), float(getattr(judgment, "pressure", 0.0) or 0.0)),
                    provenance="inner_synthesis",
                    lane_hint="diary",
                    now=now,
                )
            raw_surface = getattr(judgment, "surface_candidate", None)
            if raw_surface is not None and filtered_candidate is None:
                payload = raw_surface.to_dict() if callable(getattr(raw_surface, "to_dict", None)) else {}
                content = str(payload.get("topic_seed") or payload.get("text") or getattr(raw_surface, "topic_seed", "") or "")
                if content:
                    self.capture_residue(
                        kind="suppressed_private_candidate",
                        text=content,
                        source_ids=tuple(payload.get("evidence_ids") or ()),
                        salience=max(0.55, float(getattr(judgment, "pressure", 0.0) or 0.0)),
                        provenance="private_surface_valve_suppressed",
                        lane_hint="diary",
                        now=now,
                    )

    def _run_gemini_background(self, name: str, work: Callable[[], None]) -> None:
        if not _env_flag("ERIS_PRIVATE_MIND_GEMINI_BACKGROUND", True):
            work()
            return

        with self._gemini_background_lock:
            if name in self._gemini_background_active:
                return
            self._gemini_background_active.add(name)

        def _runner() -> None:
            try:
                work()
            except Exception as exc:
                self._boundary_note(f"{name}.background", exc)
            finally:
                with self._gemini_background_lock:
                    self._gemini_background_active.discard(name)

        threading.Thread(target=_runner, name=f"eris-{name}", daemon=True).start()

    def _maybe_consolidate_residue(self, *, now: float) -> None:
        if not self.residue_store.should_curate(now=now):
            return
        packet = self.residue_store.curator_packet(limit=24)
        if not packet.get("items"):
            return
        curate_fn = getattr(self.model_adapter, "curate_residue", None)
        meta_fn = getattr(self.model_adapter, "residue_metadata", None)
        curator_meta = meta_fn() if callable(meta_fn) else {"configured": False, "model": ""}
        curated = None
        if callable(curate_fn) and bool(curator_meta.get("configured", False)):
            try:
                from runtime.inference_broker import inference_context
                with inference_context(
                    "private_residue_curator",
                    optional=True,
                    timeout_seconds=_gemini_background_timeout_seconds(),
                    cancel_scope="background:private_residue",
                    coalesce_key="private_residue:latest_batch",
                    metadata={"items": len(packet.get("items", []))},
                ):
                    curated = curate_fn(packet)
            except Exception as exc:
                curator_meta = dict(curator_meta)
                curator_meta["error"] = f"{type(exc).__name__}:{exc}"[:160]
                self._boundary_note("residue.curator", exc)
        if isinstance(curated, Mapping):
            applied = self.residue_store.apply_curator_output(curated, curator_meta=curator_meta, now=now)
            if applied:
                return
        # Gemma vắng/lỗi/không có decision hợp lệ: vẫn giữ cognition thật, nhưng
        # tuyệt đối không biến unprocessed stimulus thành diary.
        self.residue_store.deterministic_consolidate(now=now)

    def _maybe_refresh_thought_shards(
        self,
        *,
        dossier: Any,
        fragments: Iterable[Any],
        judgment: Any,
        filtered_candidate: Any,
        runtime_owner: Any,
        now: float,
    ) -> None:
        """Cho Gemma cập nhật 5 live shard, hoàn toàn tách khỏi public speech."""
        from runtime.architecture_flags import inner_diary_thought_shards_enabled
        if not inner_diary_thought_shards_enabled():
            return
        packet = self._thought_shard_packet(
            dossier=dossier,
            fragments=fragments,
            judgment=judgment,
            filtered_candidate=filtered_candidate,
            runtime_owner=runtime_owner,
            now=now,
        )
        atoms = list(packet.get("atoms") or [])
        if not atoms:
            return
        signature_blob = json.dumps(
            [(str(x.get("id") or ""), str(x.get("text") or "")) for x in atoms if isinstance(x, Mapping)],
            ensure_ascii=False,
            sort_keys=True,
        )
        signature = hashlib.sha1(signature_blob.encode("utf-8")).hexdigest()
        urgent = max((float(x.get("salience", 0.0) or 0.0) for x in atoms if isinstance(x, Mapping)), default=0.0) >= 0.80
        if not self.thought_shards.should_refresh(signature=signature, now=now, urgent=urgent):
            return

        write_fn = getattr(self.model_adapter, "write_thought_shards", None)
        meta_fn = getattr(self.model_adapter, "residue_metadata", None)
        writer_meta = meta_fn() if callable(meta_fn) else {"configured": False, "model": ""}
        if not callable(write_fn) or not bool(writer_meta.get("configured", False)):
            # Không fake micro-thought bằng rule. Renderer vẫn có raw fallback và
            # lần sau sẽ thử lại ngay khi Gemma được cấu hình.
            return
        try:
            from runtime.inference_broker import inference_context
            with inference_context(
                "private_thought_shards",
                optional=True,
                timeout_seconds=_gemini_background_timeout_seconds(),
                cancel_scope="background:private_thought_shards",
                coalesce_key="private_thought_shards:latest_state",
                metadata={"atoms": len(atoms), "urgent": urgent},
            ):
                output = write_fn(packet)
        except Exception as exc:
            self._boundary_note("thought_shards.gemma", exc)
            return
        if not isinstance(output, Mapping):
            return
        try:
            applied = self.thought_shards.apply_shard_output(
                output,
                packet=packet,
                writer_meta=writer_meta,
                signature=signature,
                now=now,
            )
            if applied:
                fn = getattr(self.logger, "info", None)
                if callable(fn):
                    fn("[InnerDiary V80] Gemma thought-shards updated=%d", applied)
        except Exception as exc:
            self._boundary_note("thought_shards.apply", exc)

    def _thought_shard_packet(
        self,
        *,
        dossier: Any,
        fragments: Iterable[Any],
        judgment: Any,
        filtered_candidate: Any,
        runtime_owner: Any,
        now: float,
    ) -> dict[str, Any]:
        """Nén private state thành atom có id để Gemma cite, tránh sáng tác vô neo."""
        atoms: list[dict[str, Any]] = []

        def add_atom(
            atom_id: str,
            kind: str,
            text: Any,
            *,
            salience: float = 0.5,
            source_ids: Iterable[Any] = (),
        ) -> None:
            clean = " ".join(str(text or "").replace("\x00", " ").split()).strip()
            if not clean:
                return
            atoms.append({
                "id": str(atom_id or f"atom:{len(atoms)}")[:160],
                "kind": str(kind or "state")[:64],
                "text": clean[:520],
                "salience": round(max(0.0, min(1.0, float(salience or 0.0))), 3),
                "source_ids": list(dict.fromkeys(str(x) for x in tuple(source_ids or ()) if str(x)))[:16],
            })

        for fragment in tuple(fragments or ())[:8]:
            fid = str(getattr(fragment, "id", "") or f"fragment:{len(atoms)}")
            add_atom(
                fid,
                "private_fragment",
                getattr(fragment, "claim", ""),
                salience=max(float(getattr(fragment, "score", 0.0) or 0.0), float(getattr(fragment, "pressure", 0.0) or 0.0)),
                source_ids=getattr(fragment, "evidence_ids", ()) or (),
            )

        if judgment is not None:
            add_atom(
                f"judgment:{str(getattr(judgment, 'source', '') or 'inner')}",
                "private_judgment",
                getattr(judgment, "dominant_judgment", ""),
                salience=max(float(getattr(judgment, "confidence", 0.0) or 0.0), float(getattr(judgment, "pressure", 0.0) or 0.0)),
                source_ids=getattr(judgment, "evidence_ids", ()) or (),
            )

        for raw in list(self.concern_store.snapshots(limit=5)):
            if not isinstance(raw, Mapping):
                continue
            cid = str(raw.get("id") or raw.get("concern_id") or f"concern:{len(atoms)}")
            add_atom(
                cid,
                "active_concern",
                raw.get("theme") or raw.get("summary"),
                salience=float(raw.get("pressure", raw.get("activation", 0.5)) or 0.5),
                source_ids=raw.get("evidence_ids") or (),
            )

        bias = getattr(self.mutation_bus, "bias_state", None)
        speech_bias = to_plain(getattr(bias, "speech_bias", {})) if bias is not None else {}
        if isinstance(speech_bias, Mapping):
            for key in ("intent", "next_move", "stance", "tone"):
                value = str(speech_bias.get(key) or "").strip()
                if value:
                    add_atom(f"future_bias:{key}", "future_bias", value, salience=0.48)
                    break
        for index, raw in enumerate(to_plain(getattr(bias, "inquiry_plan", [])[-3:]) if bias is not None else []):
            if isinstance(raw, Mapping):
                text = raw.get("question") or raw.get("text") or raw.get("topic")
            else:
                text = raw
            add_atom(f"inquiry_plan:{index}", "future_bias", text, salience=0.45)

        if filtered_candidate is not None:
            payload = filtered_candidate.to_dict() if callable(getattr(filtered_candidate, "to_dict", None)) else {}
            if not isinstance(payload, Mapping):
                payload = {}
            add_atom(
                str(payload.get("id") or f"surface_candidate:{len(atoms)}"),
                "private_want_candidate",
                payload.get("topic_seed") or payload.get("text") or getattr(filtered_candidate, "topic_seed", ""),
                salience=float(payload.get("confidence", getattr(filtered_candidate, "confidence", 0.55)) or 0.55),
                source_ids=payload.get("evidence_ids") or payload.get("evidence_refs") or (),
            )

        for item in self.residue_store.diary_entries(now=now, limit=6):
            if not isinstance(item, Mapping):
                continue
            add_atom(
                str(item.get("id") or f"residue_entry:{len(atoms)}"),
                f"retained_{str(item.get('kind') or 'reflection')}",
                item.get("text"),
                salience=float(item.get("salience", 0.5) or 0.5),
                source_ids=item.get("source_ids") or (),
            )

        # V77 continuous self là state causal rất giá trị cho 5 mảnh. Chỉ lấy
        # projection gọn; không đưa raw prompt/chain-of-thought xuống Gemma.
        individual: dict[str, Any] = {}
        try:
            persistent = getattr(runtime_owner, "persistent_individual_runtime", None)
            project_fn = getattr(persistent, "projection_for_host", None)
            if callable(project_fn):
                individual = dict(project_fn(runtime_owner, now=now, context_key="inner_diary") or {})
        except Exception as exc:
            self._boundary_note("thought_shards.persistent_projection", exc)
            individual = {}
        self._last_individual_projection = individual
        continuous = individual.get("continuous_self") if isinstance(individual.get("continuous_self"), Mapping) else {}
        if isinstance(continuous, Mapping):
            add_atom("self:orientation", "continuous_self", continuous.get("orientation"), salience=0.45)
            add_atom("self:dominant_motive", "continuous_self", continuous.get("dominant_motive"), salience=0.55)
            top_concern = continuous.get("top_concern") if isinstance(continuous.get("top_concern"), Mapping) else {}
            add_atom("self:top_concern", "continuous_self", top_concern.get("theme") or top_concern.get("summary") or top_concern.get("content"), salience=float(top_concern.get("pressure", 0.6) or 0.6))
            commitment = continuous.get("active_commitment") if isinstance(continuous.get("active_commitment"), Mapping) else {}
            add_atom("self:commitment", "continuous_self", commitment.get("objective") or commitment.get("goal_kind"), salience=float(commitment.get("strength", 0.6) or 0.6))
            for idx, tension in enumerate((continuous.get("tensions") or [])[:3]):
                if isinstance(tension, Mapping):
                    add_atom(f"self:tension:{idx}", "continuous_self_tension", tension.get("summary") or tension.get("left") or tension.get("left_pull"), salience=float(tension.get("pressure", tension.get("strength", 0.65)) or 0.65))

        # Recent user turn là stimulus thật, được phép làm context cho micro-cognition.
        turns = tuple(getattr(dossier, "recent_user_turns", ()) or ()) if dossier is not None else ()
        for idx, turn in enumerate(turns[-2:]):
            if isinstance(turn, Mapping):
                add_atom(
                    f"user_context:{idx}:{str(turn.get('id') or '')}"[:160],
                    "recent_user_context",
                    turn.get("text"),
                    salience=0.62,
                    source_ids=(turn.get("id"),),
                )

        # Dedupe atom text, ưu tiên salience cao hơn.
        dedup: dict[tuple[str, str], dict[str, Any]] = {}
        for atom in atoms:
            key = (str(atom.get("kind") or ""), " ".join(str(atom.get("text") or "").casefold().split()))
            prev = dedup.get(key)
            if prev is None or float(atom.get("salience", 0.0) or 0.0) > float(prev.get("salience", 0.0) or 0.0):
                dedup[key] = atom
        atoms = sorted(dedup.values(), key=lambda x: float(x.get("salience", 0.0) or 0.0), reverse=True)[:28]

        return {
            "schema": "eris.inner_diary.thought_shard.packet.v80",
            "rule": (
                "Gemma owns five short private thought shards only. It may infer a micro-thought from supplied atoms, "
                "but must cite atom_ids and must not invent external facts or public actions."
            ),
            "slots": list((self.thought_shards.snapshot(now=now).get("slots") or {}).values()),
            "atoms": atoms,
            "context": {
                "channel": str(getattr(dossier, "channel", "") or "") if dossier is not None else "",
                "continuous_self": continuous if isinstance(continuous, Mapping) else {},
                "relational_plan": individual.get("relational_plan", {}) if isinstance(individual, Mapping) else {},
                "interaction_ecology": individual.get("interaction_ecology", {}) if isinstance(individual, Mapping) else {},
            },
        }

    @staticmethod
    def _dossier_residue_text(dossier: Any) -> str:
        if dossier is None:
            return ""
        turns = tuple(getattr(dossier, "recent_user_turns", ()) or ())
        for turn in reversed(turns):
            if isinstance(turn, Mapping):
                text = str(turn.get("text") or "").strip()
                if text:
                    return text[:420]
        for value in (getattr(dossier, "current_task", ""), getattr(dossier, "active_goal", "")):
            text = str(value or "").strip()
            if text:
                return text[:420]
        return ""

    def _trigger_signature(
        self,
        *,
        user_text: str,
        channel: str,
        snapshot: Any,
        observer_frame: Any,
        surface_outcome: Mapping[str, Any] | None,
        surface_candidate_queue: list[Any] | None,
    ) -> str:
        """Cheap local delta detector; no model call, no prompt construction."""

        try:
            snapshot_bits = {
                "app": str(getattr(snapshot, "active_app", "") or ""),
                "window": str(getattr(snapshot, "active_window_title", "") or ""),
                "vision": tuple(str(x) for x in (getattr(snapshot, "vision_facts", ()) or ()))[:3],
                "observer": str(getattr(observer_frame, "event", "") or getattr(observer_frame, "summary", "") or ""),
                "surface": dict(surface_outcome or {}),
                "queue_tail": [
                    str(getattr(item, "id", "") or getattr(item, "topic_seed", "") or "")
                    for item in tuple(surface_candidate_queue or ())[-3:]
                ],
                "user": " ".join(str(user_text or "").split())[:400],
                "channel": str(channel or ""),
                "concerns": len(self.concern_store),
            }
            return json.dumps(snapshot_bits, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return f"{channel}:{str(user_text or '').strip()[:200]}"

    def _capture_affect(self, runtime_owner: Any) -> None:
        """Chụp snapshot cảm xúc liên tục thật từ runtime_owner (không bao giờ ném lỗi).

        Giữ bản tốt gần nhất: nếu lần này lấy được rỗng thì không ghi đè, để Inner
        Diary không nhấp nháy về 0 khi runtime tạm thời không trả state.
        """
        if runtime_owner is None:
            return
        try:
            getter = getattr(runtime_owner, "_get_internal_state", None)
            state = getter() if callable(getter) else None
            if state is None:
                return
            to_dict = getattr(state, "to_dict", None)
            data = to_dict() if callable(to_dict) else None
            if not isinstance(data, Mapping):
                return
            keys = (
                "valence", "arousal", "curiosity", "boredom", "social_energy",
                "attachment", "irritation", "protectiveness", "confidence",
                "fatigue", "tenderness", "cognitive_tension",
            )
            snap = {k: data[k] for k in keys if k in data}
            if snap:
                self._affect_snapshot = snap
        except Exception as exc:
            self._boundary_note("affect.snapshot", exc)

    def _followup_fragments(self, dossier: Any) -> tuple[ThoughtFragment, ...]:
        """Biến mạch nghĩ dang dở thành fragment để synthesizer nghĩ tiếp.

        Hiếm khi chạy (cooldown trong ThoughtContinuityStore). Mỗi thread khơi lại
        được đánh dấu revisited để không bị khơi lại liên tục.
        """
        out: list[ThoughtFragment] = []
        try:
            unresolved = self.continuity.unresolved(limit=2)
        except Exception:
            return ()
        for e in unresolved:
            out.append(
                ThoughtFragment(
                    source="self_followup",
                    claim=e.text,
                    confidence=max(0.45, e.confidence),
                    pressure=max(self.continuity.unresolved_min_pressure, e.pressure),
                    evidence_ids=tuple(dossier.evidence_ids[:6]),
                    suggested_question="",
                    metadata={"theme": e.theme, "followup": True},
                )
            )
            self.continuity.mark_revisited(e.theme)
        return tuple(out)

    def _record_continuity(self, judgment: Any) -> None:
        """Ghi suy nghĩ vừa sinh vào dòng liên tục (RAM + JSONL)."""
        try:
            text = str(getattr(judgment, "dominant_judgment", "") or "").strip()
            if not text:
                return
            concern_update = getattr(judgment, "private_concern_update", {}) or {}
            theme = str(concern_update.get("theme") or "")
            status = str(concern_update.get("status") or "open")
            concern_ids = tuple(
                str(x) for x in (concern_update.get("evidence_ids") or ())[:6] if str(x).strip()
            )
            self.continuity.record_thought(
                text=text,
                theme=theme,
                status=status,
                pressure=float(getattr(judgment, "pressure", 0.0) or 0.0),
                confidence=float(getattr(judgment, "confidence", 0.0) or 0.0),
                concern_ids=concern_ids,
                source=str(getattr(judgment, "source", "synthesis") or "synthesis"),
            )
        except Exception as exc:
            self._boundary_note("continuity.record", exc)

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
        residue_snapshot = self.residue_store.snapshot()
        thought_snapshot = self.thought_shards.snapshot()
        retained = {
            "concerns": list(self.concern_store.snapshots(limit=8)),
            "diary_entries": list(residue_snapshot.get("diary_entries", [])),
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
            "recently_resolved": list(self.concern_store.recently_resolved(limit=5)),
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
            "diary_residue": residue_snapshot,
            "thought_shards": thought_snapshot,
            "persistent_individual": dict(getattr(self, "_last_individual_projection", {}) or {}),
            "debug_api": debug_api,
        }
        digest = {
            "last_tick_at": round(float(self.last_tick_at or 0.0), 3),
            "current": current,
            "retained": retained,
            "pulled": pulled,
            "temporary": temporary,
            "menu": menu,
            **menu,
            "affect": dict(getattr(self, "_affect_snapshot", {}) or {}),
            "diary_residue": residue_snapshot,
            "thought_shards": thought_snapshot,
            "persistent_individual": dict(getattr(self, "_last_individual_projection", {}) or {}),
            "debug": to_plain(getattr(result, "debug", {}) if result is not None else {}),
        }
        digest["generated_at"] = round(time.time(), 3)
        # DeepSeek có thể vừa tạo một reflection mới và ghi vào ThoughtShardStore.
        # Refresh snapshot trước render để UI thấy ngay episode vừa sinh.
        voice = self._diary_voice(digest)
        thought_snapshot = self.thought_shards.snapshot()
        digest["thought_shards"] = thought_snapshot
        digest["menu"]["thought_shards"] = thought_snapshot
        digest["inner_diary"] = InnerDiaryRenderer().render(digest, voice=voice)
        digest["inner_diary_contract"] = {
            "schema": "eris.inner_diary.v80",
            "owner": "private_mind.inner_diary",
            "micro_thought_owner": "gemma",
            "deep_reflection_owner": "deepseek",
            "writer": to_plain(digest["inner_diary"].get("writer", {})),
            "shard_writer": to_plain(thought_snapshot.get("shard_writer", {})),
        }
        try:
            anchor_block = self._build_anchor_block()
            digest["anchor"] = anchor_block
            self._maybe_journal_anchor(anchor_block)
        except Exception:
            digest["anchor"] = {}
        return digest

    def _diary_voice(self, digest: Mapping[str, Any]) -> dict[str, Any] | None:
        """V80: DeepSeek chỉ trả deep reflection; 5 live shard thuộc Gemma."""
        from runtime.architecture_flags import inner_diary_deep_reflection_enabled, inner_diary_model_enabled
        if not inner_diary_model_enabled() or not inner_diary_deep_reflection_enabled():
            return None
        writer = getattr(self, "diary_writer", None)
        if writer is None:
            return None
        try:
            return writer.maybe_write(digest)
        except Exception as exc:
            self._boundary_note("inner_diary.deep_reflection", exc)
            return None

    def drain_surface_impulses(self, queue: list[Any], *, limit: int = 4) -> tuple[Any, ...]:
        items: list[Any] = []
        while queue and len(items) < max(1, limit):
            items.append(queue.pop(0))
        return tuple(items)

    def _model_api_status(self) -> dict[str, Any]:
        status_fn = getattr(self.model_adapter, "debug_status", None)
        if not callable(status_fn):
            return {"api_degraded": False, "api_invalid_json": False, "last_error": "", "api_degraded_cause": ""}
        try:
            status = status_fn()
        except Exception:
            return {"api_degraded": True, "api_invalid_json": False, "last_error": "debug_status_failed", "api_degraded_cause": ""}
        last_error = str(status.get("last_error", "") or "") if isinstance(status, Mapping) else ""
        degraded_cause = str(status.get("degraded_cause", "") or "") if isinstance(status, Mapping) else ""
        # Pool có streak riêng cho từng mini-evaluator. Nếu một fragment bị
        # DROP_IF_BUSY nhưng synthesis vẫn ổn, top-level last_error có thể rỗng;
        # quét nested status để residue spool biết đã có stimulus chưa xử lý.
        nested_errors: list[str] = []
        if isinstance(status, Mapping):
            fragments = status.get("fragments")
            if isinstance(fragments, Mapping):
                for item in fragments.values():
                    if isinstance(item, Mapping):
                        err = str(item.get("last_error", "") or "")
                        if err:
                            nested_errors.append(err)
        busy_error = next((err for err in nested_errors if "busy" in err.casefold()), "")
        effective_error = busy_error or last_error
        return {
            "api_degraded": bool(last_error or nested_errors),
            "api_invalid_json": "invalid_json" in effective_error,
            "last_error": effective_error,
            "api_degraded_cause": degraded_cause,
        }

    def _resolve_concern_path(self) -> str | None:
        if self.config.concern_store_path:
            return self.config.concern_store_path
        root = os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core")
        return str(Path(root) / "private_concerns.json")

    def _resolve_user_model_path(self) -> str | None:
        if self.config.user_model_path:
            return self.config.user_model_path
        env = os.getenv("ERIS_USER_MODEL_PATH", "").strip()
        if env:
            return env
        root = os.getenv("ERIS_MEMORY_CORE_DIR", "memory_core")
        return str(Path(root) / "user_model.json")

    def _resolve_anchor_journal_path(self) -> str:
        """Đường dẫn JSONL nhật ký trục neo (append-only, tái sử dụng được)."""
        env = os.getenv("ERIS_ANCHOR_JOURNAL_PATH", "").strip()
        if env:
            return env
        base = self._resolve_user_model_path() or "memory_core/user_model.json"
        return str(Path(base).with_name("anchor_journal.jsonl"))

    # ------------------------------------------------------------------
    # Serialize trục neo cho UI/observability (Mô Hình bạn panel)
    # ------------------------------------------------------------------

    def _build_anchor_block(self) -> dict[str, Any]:
        """Gom toàn trục neo thành 1 block JSON-safe cho panel C# đọc.

        Đọc-only từ self.anchor_system (đã update ở tick). Không bao giờ ném lỗi.
        """

        def c01(x: Any) -> float:
            try:
                n = float(x)
            except Exception:
                return 0.0
            if n != n:
                return 0.0
            return max(0.0, min(1.0, n))

        sysm = getattr(self, "anchor_system", None)
        if sysm is None:
            return {}

        switches = getattr(sysm, "switches", None)
        sw = {
            "shadow_enabled": bool(getattr(switches, "shadow_enabled", False)),
            "deception_enabled": bool(getattr(switches, "deception_enabled", False)),
            "strict_grounding": bool(getattr(switches, "strict_grounding", True)),
        }
        sw["safe_mode"] = (not sw["shadow_enabled"]) and (not sw["deception_enabled"])

        sig = getattr(sysm, "significance", None)
        significance = (
            sig.to_dict()
            if sig is not None and callable(getattr(sig, "to_dict", None))
            else {"irreplaceability": 0.0, "anchor_role": 0.0, "witness_strength": 0.0, "model_thickness": 0.0}
        )

        longarc = c01(getattr(sysm, "attachment_longarc", 0.0))
        state = getattr(getattr(sysm, "anchor_store", None), "state", None)
        history = list(getattr(self, "_attachment_history", []) or [])
        history.append(round(longarc, 4))
        history = history[-24:]
        self._attachment_history = history
        attachment = {
            "longarc": round(longarc, 4),
            "beat_ema": round(c01(getattr(state, "beat_ema", 0.0)), 4),
            "recognition_ema": round(c01(getattr(state, "recognition_ema", 0.0)), 4),
            "total_beats": int(getattr(state, "total_beats", 0) or 0),
            "history": history,
        }

        dread_val = c01(getattr(sysm, "ontological_dread", 0.0))
        abandon_val = c01(getattr(sysm, "abandonment_pressure", 0.0))
        dread = {
            "ontological_dread": round(dread_val, 4),
            "abandonment_pressure": round(abandon_val, 4),
        }

        shadow_state = getattr(sysm, "shadow_state", None)
        cfg = getattr(getattr(sysm, "shadow_register", None), "config", None)
        at = float(getattr(cfg, "attach_threshold", 0.62))
        abt = float(getattr(cfg, "abandonment_threshold", 0.45))
        dt = float(getattr(cfg, "dread_threshold", 0.45))
        gate = {
            "attach": {"value": round(longarc, 4), "threshold": round(at, 4), "pass": longarc >= at},
            "abandonment": {"value": round(abandon_val, 4), "threshold": round(abt, 4), "pass": abandon_val >= abt},
            "dread": {"value": round(dread_val, 4), "threshold": round(dt, 4), "pass": dread_val >= dt},
        }
        gate["open"] = bool(
            sw["shadow_enabled"]
            and gate["attach"]["pass"]
            and gate["abandonment"]["pass"]
            and gate["dread"]["pass"]
        )
        shadow = {
            "register": str(getattr(shadow_state, "register", "none") or "none"),
            "intensity": round(c01(getattr(shadow_state, "intensity", 0.0)), 4),
            "reason": str(getattr(shadow_state, "reason", "") or ""),
            "intensity_cap": round(c01(significance.get("irreplaceability", 0.0)), 4),
            "gate": gate,
        }

        store = getattr(sysm, "user_model_store", None) or getattr(self, "user_model_store", None)
        # Danh sách belief LÀM PHẲNG (facet gắn trên từng belief) để tầng nén UDP
        # không cắt cụt theo độ sâu; C# tự gom theo facet khi vẽ.
        beliefs: list[dict[str, Any]] = []
        belief_count = 0
        model_thickness = 0.0
        if store is not None and callable(getattr(store, "snapshot_for_dossier", None)):
            try:
                snap = store.snapshot_for_dossier(limit=24)
            except Exception:
                snap = {}
            if isinstance(snap, Mapping):
                belief_count = int(snap.get("belief_count") or 0)
                model_thickness = round(float(snap.get("model_thickness") or 0.0), 4)
                raw_facets = snap.get("facets")
                if isinstance(raw_facets, Mapping):
                    for fname, blist in raw_facets.items():
                        for b in (blist or []):
                            if not isinstance(b, Mapping):
                                continue
                            beliefs.append({
                                "facet": str(fname),
                                "claim": str(b.get("claim") or ""),
                                "confidence": round(float(b.get("confidence") or 0.0), 3),
                                "recurrence": int(b.get("recurrence") or 1),
                                "evidence_count": len(b.get("evidence_ids") or []),
                            })
        # Belief nặng trước (tin × lặp) để 8 dòng UDP giữ lại là phần đáng kể nhất.
        beliefs.sort(key=lambda x: (x["confidence"] * 0.6 + min(1.0, x["recurrence"] / 6.0) * 0.4), reverse=True)
        user_model = {
            "belief_count": belief_count,
            "model_thickness": model_thickness,
            "beliefs": beliefs,
        }

        ledger = getattr(sysm, "deception_ledger", None)
        records: list[dict[str, Any]] = []
        if ledger is not None and callable(getattr(ledger, "recent", None)):
            try:
                recent = ledger.recent(limit=8) or []
            except Exception:
                recent = []
            for r in recent:
                d = r.to_dict() if callable(getattr(r, "to_dict", None)) else (r if isinstance(r, Mapping) else {})
                records.append({
                    "surface_claim": str(d.get("surface_claim") or ""),
                    "ground_truth": str(d.get("ground_truth") or ""),
                    "reason": str(d.get("reason") or ""),
                    "driver": str(d.get("driver") or ""),
                    "created_at": float(d.get("created_at") or 0.0),
                })
        deception = {"count": len(records), "records": records}

        return {
            "version": 1,
            "switches": sw,
            "user_model": user_model,
            "significance": significance,
            "attachment": attachment,
            "dread": dread,
            "shadow": shadow,
            "deception": deception,
        }

    def _maybe_journal_anchor(self, block: Mapping[str, Any]) -> None:
        """Append một dòng JSONL khi trục neo ĐỔI — để tái sử dụng/replay.

        Dedup theo chữ ký để tick không đổi không spam file. Không bao giờ ném lỗi.
        """
        try:
            um = block.get("user_model", {}) or {}
            sh = block.get("shadow", {}) or {}
            att = block.get("attachment", {}) or {}
            sig = (
                int(um.get("belief_count") or 0),
                round(float(att.get("longarc") or 0.0), 3),
                str(sh.get("register") or "none"),
                round(float(sh.get("intensity") or 0.0), 3),
                int((block.get("deception", {}) or {}).get("count") or 0),
            )
            if sig == getattr(self, "_anchor_journal_sig", None):
                return
            self._anchor_journal_sig = sig
            path = Path(self._resolve_anchor_journal_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"ts": round(time.time(), 3), **dict(block)}, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            self._boundary_note("anchor.journal", exc)

    def _update_anchor_system(self, *, dossier: Any, runtime_owner: Any) -> None:
        """Cập nhật trục neo hiện sinh từ một tick và phơi facade cho runtime.

        Đọc tín hiệu sẵn có trong dossier (idle, user_presence, tuổi lời bạn) và
        Sợ_Hiện_Sinh từ internal_state nếu runtime cung cấp. Không bao giờ đổi hành
        vi live khi công tắc tắt (mặc định).
        """
        try:
            runtime_state = dossier.runtime_state if isinstance(getattr(dossier, "runtime_state", None), dict) else {}
            observer = runtime_state.get("observer", {}) if isinstance(runtime_state.get("observer"), dict) else {}
            idle_seconds = float(runtime_state.get("idle_seconds", 0.0) or 0.0)
            user_presence = float(observer.get("user_presence", 0.0) or 0.0)
            meta = dossier.metadata if isinstance(getattr(dossier, "metadata", None), dict) else {}
            age = meta.get("user_turn_age_sec")
            age = float(age) if isinstance(age, (int, float)) else None
            internal_state = self._anchor_internal_state(runtime_owner)
            continuity_threat = float(getattr(runtime_owner, "last_continuity_threat", 0.0) or 0.0)
            irritation = self._anchor_irritation(runtime_owner)
            self.anchor_system.update_from_tick(
                internal_state=internal_state,
                continuity_threat=continuity_threat,
                idle_seconds=idle_seconds,
                user_presence=user_presence,
                last_user_turn_age_seconds=age,
                irritation=irritation,
            )
            # Phơi facade để presence_controller/chat đọc (read-only, gated).
            if runtime_owner is not None:
                try:
                    setattr(runtime_owner, "anchor_system", self.anchor_system)
                except Exception as exc:
                    self._boundary_note("anchor.publish", exc)
        except Exception as exc:
            self._log_anchor_warning(exc)

    @staticmethod
    def _anchor_irritation(runtime_owner: Any) -> float:
        """Mức bực hiện tại từ persistent internal state (cho nhánh 'giận → dỗi')."""
        if runtime_owner is None:
            return 0.0
        getter = getattr(runtime_owner, "_get_internal_state", None)
        state = None
        if callable(getter):
            try:
                state = getter()
            except Exception:
                state = None
        try:
            return max(0.0, min(1.0, float(getattr(state, "irritation", 0.0) or 0.0)))
        except Exception:
            return 0.0

    @staticmethod
    def _anchor_internal_state(runtime_owner: Any) -> Any:
        """Nguồn Sợ_Hiện_Sinh: RollingInternalState từ contextual loop nếu có.

        Thử vài tên thuộc tính thường gặp; không có thì trả None (dread=0, an toàn).
        Điểm này là hook để CortexRuntime feed dread thật về sau.
        """
        if runtime_owner is None:
            return None
        for attr in ("rolling_internal_state", "endogenous_internal_state", "anchor_internal_state"):
            state = getattr(runtime_owner, attr, None)
            if state is not None and hasattr(state, "ontological_dread"):
                return state
        runtime = getattr(runtime_owner, "cortex_runtime", None)
        drive = getattr(runtime, "endogenous_drive", None) if runtime is not None else None
        current = getattr(drive, "current", None) if drive is not None else None
        if current is not None and hasattr(current, "ontological_dread"):
            return current
        return None

    def _log_anchor_warning(self, exc: Exception) -> None:
        fn = getattr(self.logger, "warning", None) if self.logger is not None else None
        if callable(fn):
            fn("AnchorSystem update failed: %s", exc)

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
