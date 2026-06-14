# -*- coding: utf-8 -*-
"""
runtime/tutor_wiring.py
=======================

Nối Curiosity Tutor vào runtime thật. Mọi adapter đều phòng thủ: Master_Switch tắt ⇒
`build_tutor_daemon_from_runtime` trả None (không tác động gì); thiếu subsystem ⇒ adapter
đó None/no-op chứ không bao giờ ném vào hot path.

LƯU Ý AN TOÀN: đường ghi vào trí nhớ dài hạn là nhạy cảm. Adapter commit claim
(`_build_ingest_fn`) chỉ chạy khi tìm thấy đường commit rõ ràng; nếu không, nó trả 0 và
ghi cảnh báo một lần — KHÔNG đoán API rồi ghi rác vào memory.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def build_tutor_daemon_from_runtime(runtime_owner: Any) -> Optional[Any]:
    """Dựng TutorDaemon đã nối adapter, hoặc None nếu Master_Switch tắt / lỗi build."""

    logger = getattr(runtime_owner, "logger", None)

    try:
        from cortex.tutor.config import TutorConfig, TutorLogger, TutorRiskGuard
        from cortex.tutor.gap_collector import GapCollector
        from cortex.tutor.curiosity_gate import CuriosityGate
        from cortex.tutor.question_formulator import QuestionFormulator
        from cortex.tutor.claim_digest import ClaimDigest
        from cortex.tutor.share_impulse import LearningShareImpulse
        from llm.tutor_backend import GeminiWebBackend
        from runtime.tutor_daemon import TutorDaemon, TutorStageEmitter
        from cortex.tutor.knowledge_classifier import KnowledgeClassifier
        from cortex.tutor.curiosity_router import CuriosityRouter
    except Exception as exc:  # pragma: no cover
        _warn(logger, f"tutor: không import được module ({exc!r})")
        return None

    tutor_logger = TutorLogger(sink=logger)
    config = TutorConfig.from_env(tutor_logger)
    if not config.enabled:
        # Master_Switch tắt: không dựng gì, không mở trình duyệt, không truy cập mạng.
        return None

    _info(logger, "tutor: Master_Switch BẬT — đang dựng Curiosity Tutor daemon")

    generate_fn = _build_generate_fn(runtime_owner, logger)
    ingest_fn = _build_ingest_fn(runtime_owner, tutor_logger, logger)
    thought_sink = _build_thought_sink(runtime_owner, logger)
    drive_fn = _build_drive_fn(runtime_owner)
    already_known_fn = _build_already_known_fn(runtime_owner)

    collector = GapCollector(config)
    formulator = QuestionFormulator(config, generate_fn=generate_fn)
    backend = GeminiWebBackend(config, logger=tutor_logger)
    digest = ClaimDigest(config, ingest_fn=ingest_fn)
    share = LearningShareImpulse(
        config,
        formulator=formulator,
        thought_sink=thought_sink,
        novelty_fn=None,
        logger=tutor_logger,
    )
    emitter = TutorStageEmitter(transport=getattr(runtime_owner, "transport", None), logger=tutor_logger)
    daemon = TutorDaemon(
        config,
        collector=collector,
        gate=CuriosityGate(config),
        formulator=formulator,
        backend=backend,
        digest=digest,
        share_impulse=share,
        classifier=KnowledgeClassifier(generate_fn=generate_fn),
        router=CuriosityRouter(generate_fn=generate_fn, already_known_fn=already_known_fn),
        emitter=emitter,
        risk_guard=TutorRiskGuard(config),
        logger=tutor_logger,
        drive_fn=drive_fn,
    )
    # Cho tick truy cập collector để nạp gap.
    runtime_owner._tutor_collector = collector

    # API "đi hỏi theo yêu cầu": cognition gọi khi không chắc / user bảo tra cứu.
    def request_tutor_lookup(topic, *, context="", kind_hint="durable", stake=0.7):
        try:
            import time as _t
            now = _t.time()
            gap = collector.collect_from_uncertainty(
                topic, context=context, stake=stake, now=now, kind_hint=kind_hint, force=True,
            )
            if gap is None:
                return False
            collector.push(gap)
            # Chạy ngay (forced bỏ qua idle/rate-limit; vẫn tôn trọng risk guard).
            ep = daemon.run_once(idle=False, now=now)
            return ep is not None
        except Exception as exc:
            _warn(logger, f"tutor request_lookup lỗi ({exc!r})")
            return False

    runtime_owner.request_tutor_lookup = request_tutor_lookup

    # Nối KnowledgeProvider (đọc claim đã học) vào SituationModel nếu reachable.
    try:
        _attach_knowledge_provider(runtime_owner, logger)
    except Exception as exc:
        _warn(logger, f"tutor: không nối được knowledge provider ({exc!r})")

    return daemon


def _attach_knowledge_provider(runtime_owner: Any, logger: Any) -> None:
    """Gắn KnowledgeProvider vào SituationModel để dự đoán dùng tri thức đã học."""

    from cortex.tutor.knowledge_provider import KnowledgeProvider

    store = _reach_semantic_store(runtime_owner)
    if store is None or not callable(getattr(store, "recall", None)):
        _warn(logger, "tutor: không tìm thấy semantic store cho knowledge provider")
        return

    def recall_fn(query: str):
        try:
            return store.recall(query, limit=4)
        except Exception:
            return []

    provider = KnowledgeProvider(recall_fn)
    runtime_owner.tutor_knowledge_provider = provider

    sm = _reach_situation_model(runtime_owner)
    if sm is not None and callable(getattr(sm, "set_knowledge_provider", None)):
        sm.set_knowledge_provider(provider)
        _info(logger, "tutor: đã nối KnowledgeProvider vào SituationModel")
    else:
        _info(logger, "tutor: KnowledgeProvider sẵn sàng (SituationModel sẽ nối khi pipeline dựng)")


def tutor_tick(runtime_owner: Any, *, observer_frame: Any = None, channel: str = "", snapshot: Any = None) -> None:
    """Nạp gap (observer + violation) rồi chạy một episode nếu đủ điều kiện. Không bao giờ ném."""

    import time as _time

    daemon = getattr(runtime_owner, "tutor_daemon", None)
    collector = getattr(runtime_owner, "_tutor_collector", None)
    if daemon is None or collector is None:
        return
    try:
        now = _time.time()
        # Lazy-attach KnowledgeProvider vào SituationModel (shadow pipeline tạo nó lazily).
        sm = _reach_situation_model(runtime_owner)
        if sm is not None:
            prov = getattr(runtime_owner, "tutor_knowledge_provider", None)
            if (prov is not None
                    and getattr(sm, "_knowledge_provider", None) is None
                    and callable(getattr(sm, "set_knowledge_provider", None))):
                try:
                    sm.set_knowledge_provider(prov)
                except Exception:
                    pass
        # Nguồn 1: observer 'unknown' — kèm đóng gói nội dung màn hình thật để Gemini đoán.
        if observer_frame is not None:
            try:
                screen_ctx = _screen_context_from_snapshot(snapshot)
                collector.push(collector.collect_from_observer(observer_frame, now=now, screen_context=screen_ctx))
            except Exception:
                pass
        # Nguồn 2: vi phạm kỳ vọng của SituationModel (nếu reachable).
        violation = None
        if sm is not None:
            expose = getattr(sm, "expose_violation", None)
            if callable(expose):
                try:
                    violation = expose()
                except Exception:
                    violation = None
        if violation is not None:
            try:
                stake = float(getattr(violation, "prediction_error", 0.0) or 0.0)
                collector.push(collector.collect_from_violation(violation, stake_relevance=stake, now=now))
            except Exception:
                pass
        idle = (channel == "autonomous") and not bool(getattr(runtime_owner, "chat_mode", False))
        daemon.run_once(idle=idle, now=now)
    except Exception as exc:
        _warn(getattr(runtime_owner, "logger", None), f"tutor tick error: {exc!r}")


# ---------------------------------------------------------------------------
# Adapters (phòng thủ)
# ---------------------------------------------------------------------------

def _build_generate_fn(runtime_owner: Any, logger: Any) -> Optional[Callable[[str], str]]:
    """Local LLM text gen qua engine local (JSON wrapper). None ⇒ heuristic fallback."""

    try:
        from llm.local_llama_engine import build_local_or_ollama_client
    except Exception:
        return None

    import os
    model = os.getenv("ERIS_TUTOR_LOCAL_MODEL", os.getenv("ERIS_OBSERVER_MODEL", "qwen3:1.7b"))

    def generate_fn(prompt: str) -> str:
        try:
            client = build_local_or_ollama_client()
            messages = [
                {"role": "system", "content": "Trả về JSON gọn dạng {\"text\": \"...\"} bằng tiếng Việt."},
                {"role": "user", "content": prompt},
            ]
            res = client.chat_json(model, messages, temperature=0.4)
            if getattr(res, "ok", False):
                data = getattr(res, "parsed", {}) or {}
                return str(data.get("text", "") or "").strip()
        except Exception:
            return ""
        return ""

    return generate_fn


def _build_ingest_fn(runtime_owner: Any, tutor_logger: Any, logger: Any) -> Optional[Callable[..., int]]:
    """Đường commit claim vào trí nhớ ngữ nghĩa (có embedding) qua memory core/kernel.

    Claim được lưu với tag "tutor"/"learned" + source provenance, confidence vừa phải, và
    storage_permission=True (commit nội bộ tin cậy). Store ngữ nghĩa đã gắn embedding_index
    ⇒ bài học có embedding, recall lần sau dùng được.
    """

    # Cho phép người dùng override hoàn toàn nếu muốn.
    custom = getattr(runtime_owner, "tutor_ingest_fn", None)
    if callable(custom):
        return custom

    committer = _reach_memory_commit(runtime_owner)
    if committer is None:
        _warn(logger, "tutor: không tìm thấy đường commit memory — claim sẽ không được lưu")
        return None

    def ingest_fn(text: str, *, source: str = "tutor", gap_id: str = "", citations=()) -> int:
        claim = str(text or "").strip()
        if not claim:
            return 0
        request = {
            "target": "semantic_memory",
            "content": claim[:480],
            "confidence": 0.66,
            "evidence_ids": [gap_id or "tutor"],
            "storage_permission": True,
            "permission_required": False,
            "decay_policy": "normal",
            "reason": "curiosity_tutor",
            "source_module": "curiosity_tutor",
            "tags": ["tutor", "learned", "curiosity"],
            "metadata": {
                "storage_permission": True,
                "trusted_internal_commit": True,
                "source": str(source or "tutor"),
                "gap_id": gap_id,
                "citations": list(citations or ()),
            },
        }
        try:
            decision = committer(request)
        except Exception as exc:
            _warn(logger, f"tutor: commit claim lỗi ({exc!r})")
            return 0
        outcome = str(getattr(decision, "outcome", "") or "")
        stored = str(getattr(decision, "stored_id", "") or "")
        return 1 if (outcome in {"accepted", "tentative"} and stored) else 0

    return ingest_fn


def _build_thought_sink(runtime_owner: Any, logger: Any) -> Optional[Any]:
    """Đẩy Share_Impulse vào internal_agenda nếu có. None ⇒ không khoe (an toàn)."""

    agenda = _reach_internal_agenda(runtime_owner)
    if agenda is None or not callable(getattr(agenda, "add", None)):
        return None

    class _AgendaSink:
        def push_share_impulse(self, highlight: str, *, priority: float) -> None:
            try:
                agenda.add(
                    kind="misc",
                    summary=str(highlight)[:240],
                    source="tutor",
                    speech_value=float(priority),
                    confidence=float(priority),
                    ttl_seconds=1800.0,
                )
            except Exception:
                pass

    return _AgendaSink()


def _build_already_known_fn(runtime_owner: Any) -> Optional[Callable[[str], bool]]:
    """True nếu Eris đã biết topic (recall trí nhớ trúng) ⇒ router skip, đỡ hỏi lại."""

    store = _reach_semantic_store(runtime_owner)
    if store is None or not callable(getattr(store, "recall", None)):
        return None

    def already_known(topic: str) -> bool:
        topic = str(topic or "").strip()
        if not topic:
            return False
        try:
            hits = store.recall(topic, limit=1, min_score=0.6)
            return bool(hits)
        except Exception:
            return False

    return already_known


def _build_drive_fn(runtime_owner: Any) -> Optional[Callable[[], float]]:
    def drive_fn() -> float:
        for attr in ("endogenous_drive_level", "curiosity_level"):
            val = getattr(runtime_owner, attr, None)
            if isinstance(val, (int, float)):
                return max(0.0, min(1.0, float(val)))
        return 1.0

    return drive_fn


# ---------------------------------------------------------------------------
# Reach helpers — dò mềm vào subsystem, không bám cứng.
# ---------------------------------------------------------------------------

def _reach_internal_agenda(runtime_owner: Any) -> Optional[Any]:
    for attr in ("internal_agenda", "agenda"):
        obj = getattr(runtime_owner, attr, None)
        if obj is not None and callable(getattr(obj, "add", None)):
            return obj
    state = getattr(runtime_owner, "rolling_internal_state", None) or getattr(runtime_owner, "_internal_state", None)
    if state is not None:
        agenda = getattr(state, "internal_agenda", None)
        if agenda is not None and callable(getattr(agenda, "add", None)):
            return agenda
    return None


def _screen_context_from_snapshot(snapshot: Any) -> str:
    """Đóng gói nội dung màn hình thật cho Gemini đoán ngữ cảnh.

    Lấy app/cửa sổ/đường dẫn + một đoạn OCR (đã cắt). Lọc email để bớt rò định danh.
    LƯU Ý RIÊNG TƯ: nội dung màn hình (OCR) sẽ được gửi tới Gemini ở nhánh này.
    """

    if snapshot is None:
        return ""
    try:
        from cortex.tutor.config import scrub_identity
    except Exception:
        def scrub_identity(x):  # type: ignore
            return str(x or "")

    parts = []
    app = str(getattr(snapshot, "active_app", "") or "").strip()
    title = str(getattr(snapshot, "active_window_title", "") or "").strip()
    url = str(getattr(snapshot, "url_or_path_hint", "") or "").strip()
    ocr = str(getattr(snapshot, "ocr_text", "") or "").strip()
    if app:
        parts.append(f"app={app}")
    if title:
        parts.append(f"cửa sổ={title}")
    if url:
        parts.append(f"đường dẫn={url}")
    if ocr:
        parts.append(f"chữ trên màn hình: {ocr[:300]}")
    return scrub_identity(" | ".join(parts))[:500]


def _reach_situation_model(runtime_owner: Any) -> Optional[Any]:
    sm = getattr(runtime_owner, "situation_model", None)
    if sm is None:
        for attr in ("cognitive_pipeline", "shadow_pipeline", "v3_pipeline", "_shadow_pipeline_instance"):
            pipeline = getattr(runtime_owner, attr, None)
            if pipeline is not None:
                sm = getattr(pipeline, "situation_model", None)
                if sm is not None:
                    break
    return sm


def _reach_situation_violation(runtime_owner: Any) -> Optional[Any]:
    sm = _reach_situation_model(runtime_owner)
    if sm is None:
        return None
    expose = getattr(sm, "expose_violation", None)
    if callable(expose):
        try:
            return expose()
        except Exception:
            return None
    return None


def _reach_memory_commit(runtime_owner: Any) -> Optional[Callable[[Any], Any]]:
    """Trả callable commit(request) từ memory_kernel/memory_core nếu có."""

    for attr in ("memory_kernel", "memory_core"):
        obj = getattr(runtime_owner, attr, None)
        if obj is not None and callable(getattr(obj, "commit", None)):
            return obj.commit
    return None


def _reach_semantic_store(runtime_owner: Any) -> Optional[Any]:
    """Trả semantic store (có recall + embedding_index) từ memory core/kernel."""

    candidates = []
    for attr in ("memory_core", "memory_kernel"):
        obj = getattr(runtime_owner, attr, None)
        if obj is None:
            continue
        candidates.append(obj)
        # kernel có thể bọc core qua .core/.cognition/.memory_cognition
        for inner in ("core", "cognition", "memory_cognition"):
            nested = getattr(obj, inner, None)
            if nested is not None:
                candidates.append(nested)
    for obj in candidates:
        store = getattr(obj, "semantic", None)
        if store is not None and callable(getattr(store, "recall", None)):
            return store
        if callable(getattr(obj, "recall", None)) and getattr(obj, "semantic", None) is not None:
            return getattr(obj, "semantic", None)
    return None


def _warn(logger: Any, message: str) -> None:
    try:
        if logger is not None and callable(getattr(logger, "warning", None)):
            logger.warning("%s", message)
    except Exception:
        pass


def _info(logger: Any, message: str) -> None:
    try:
        if logger is not None and callable(getattr(logger, "info", None)):
            logger.info("%s", message)
    except Exception:
        pass


__all__ = ["build_tutor_daemon_from_runtime", "tutor_tick"]
