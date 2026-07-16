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

import re
from typing import Any, Callable, Optional

try:  # pragma: no cover
    from cortex.tutor.secret_scrubber import scrub_secrets
except Exception:  # pragma: no cover
    def scrub_secrets(text: Any) -> str:  # type: ignore
        return str(text or "")


_GENERIC_TELEMETRY_PREFIXES = (
    "active window is ",
    "focus kind is ",
    "there has been no input for ",
    "browser target is visible:",
    "context classification:",
)


def _is_generic_telemetry_line(text: str) -> bool:
    """True nếu một dòng chỉ là telemetry chung chung, KHÔNG phải nội dung màn hình thật."""

    lowered = str(text or "").strip().lower()
    if not lowered:
        return True
    if lowered.startswith(_GENERIC_TELEMETRY_PREFIXES):
        return True
    if re.fullmatch(r"\d+ browser tabs are visible", lowered):
        return True
    if re.fullmatch(r"\d+ windows are open", lowered):
        return True
    return False


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
    distill_fn = _build_distill_fn(runtime_owner, logger)
    thought_sink = _build_thought_sink(runtime_owner, logger)
    drive_fn = _build_drive_fn(runtime_owner)
    already_known_fn = _build_already_known_fn(runtime_owner)

    collector = GapCollector(config)
    formulator = QuestionFormulator(config, generate_fn=generate_fn)
    backend = GeminiWebBackend(config, logger=tutor_logger)
    digest = ClaimDigest(config, ingest_fn=ingest_fn, distill_fn=distill_fn)
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
            topic = scrub_secrets(topic)
            context = scrub_secrets(context)
            gap = collector.collect_from_uncertainty(
                topic, context=context, stake=stake, now=now, kind_hint=kind_hint, force=True,
            )
            if gap is None:
                return False
            collector.push(gap)
            # Chạy ngay (forced bỏ qua idle/rate-limit; vẫn tôn trọng risk guard).
            ep = daemon.run_once(idle=False, now=now)
            if ep is None:
                _warn(logger, f"tutor request_lookup không chạy được episode topic={str(topic)[:120]!r}")
                return False
            if getattr(ep, "fail_reason", None):
                _warn(logger, f"tutor request_lookup failed reason={getattr(ep, 'fail_reason', '')} topic={str(topic)[:120]!r}")
            return ep is not None
        except Exception as exc:
            _warn(logger, f"tutor request_lookup lỗi ({exc!r})")
            return False

    runtime_owner.request_tutor_lookup = request_tutor_lookup

    # API "tra rồi TRẢ LỜI ngay". Khi research=True hoặc search=True, dùng relay nhẹ:
    # local/Gemma đặt câu hỏi cho Tutor Gemini Web, nhận raw answer, rồi local/heuristic
    # chấm lại trước khi trả cho Eris. Không gọi Gemini API/Google grounding fallback.
    def request_tutor_answer(topic, *, context="", research=False, search=False):
        try:
            safe_topic = scrub_secrets(topic)
            safe_context = scrub_secrets(context)
            runtime_owner._last_tutor_research_artifact = {}
            runtime_owner._last_tutor_research_thread = {}
            runtime_owner._last_tutor_research_metrics = {}
            runtime_owner._last_tutor_research_memory_decision = {}
            if search and callable(getattr(daemon, "search_now", None)):
                answer = daemon.search_now(safe_topic, context=safe_context, critic_fn=generate_fn)
            elif research and callable(getattr(daemon, "research_now", None)):
                answer = daemon.research_now(safe_topic, context=safe_context, critic_fn=generate_fn)
            else:
                answer = daemon.ask_now(safe_topic, context=safe_context)
            runtime_owner._last_tutor_research_artifact = dict(getattr(daemon, "last_research_bundle", {}) or {})
            runtime_owner._last_tutor_research_thread = dict(getattr(daemon, "last_research_thread", {}) or {})
            runtime_owner._last_tutor_research_metrics = dict(getattr(daemon, "last_research_metrics", {}) or {})
            runtime_owner._last_tutor_research_memory_decision = dict(getattr(daemon, "last_research_memory_decision", {}) or {})
            if answer:
                return scrub_secrets(answer)
            _warn(logger, f"tutor request_answer không có kết quả topic={str(safe_topic)[:120]!r}")
            return None
        except Exception as exc:
            _warn(logger, f"tutor request_answer lỗi ({exc!r})")
            return None

    runtime_owner.request_tutor_answer = request_tutor_answer

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
    """Local hoặc Remote LLM text gen để sinh câu hỏi/phân loại. None ⇒ heuristic fallback."""

    import os
    import json as _json
    import re

    llm_service = getattr(runtime_owner, "llm_service", None)
    use_remote = (
        os.getenv("ERIS_TUTOR_USE_REMOTE_LLM", "0").strip().lower() in {"1", "true", "yes", "on"}
    )

    if use_remote and llm_service is not None:
        remote_client = llm_service.fallback_client or llm_service.client
        if remote_client is not None:
            def generate_fn(prompt: str) -> str:
                try:
                    messages = [
                        {"role": "system", "content": "Trả về JSON gọn dạng {\"text\": \"...\"} bằng tiếng Việt. Tuyệt đối không thêm lời dẫn hay giải thích ngoài JSON."},
                        {"role": "user", "content": prompt},
                    ]
                    resp = remote_client.create_chat_completion(
                        messages=messages,
                        temperature=0.4,
                        frequency_penalty=0.0,
                        presence_penalty=0.0,
                        max_tokens=150,
                        response_format={"type": "json_object"},
                        timeout=10,
                    )
                    extractor = getattr(llm_service, "_extract_content", None)
                    content = extractor(resp) if callable(extractor) else ""
                    if not content and isinstance(resp, dict):
                        choices = resp.get("choices")
                        if isinstance(choices, list) and choices:
                            content = choices[0].get("message", {}).get("content", "")
                        else:
                            candidates = resp.get("candidates")
                            if isinstance(candidates, list) and candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                content = "".join(p.get("text", "") for p in parts if "text" in p)

                    content = content.strip()
                    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE).strip()
                    content = re.sub(r"\s*```$", "", content).strip()
                    data = _json.loads(content)
                    return str(data.get("text", "") or "").strip()
                except Exception as exc:
                    _warn(logger, f"tutor remote generate_fn lỗi ({exc!r})")
                    return ""
            return generate_fn



def _build_distill_fn(runtime_owner: Any, logger: Any) -> Optional[Callable[[str], list]]:
    """Tách câu trả lời gia sư thành các fact ngắn, atomic qua local hoặc remote LLM.

    None ⇒ ClaimDigest tự fallback tách câu bằng heuristic. Lỗi LLM không bao giờ
    ném vào hot path — trả [] để digest dùng fallback.
    """

    import os
    import json as _json
    import re

    llm_service = getattr(runtime_owner, "llm_service", None)
    use_remote = (
        os.getenv("ERIS_TUTOR_USE_REMOTE_LLM", "0").strip().lower() in {"1", "true", "yes", "on"}
    )

    if use_remote and llm_service is not None:
        remote_client = llm_service.fallback_client or llm_service.client
        if remote_client is not None:
            def distill_fn(answer_text: str) -> list:
                text = str(answer_text or "").strip()
                if not text:
                    return []
                try:
                    messages = [
                        {
                            "role": "system",
                            "content": (
                                "Bạn tách kiến thức thành các sự thật ngắn, độc lập, không trùng. "
                                "Trả JSON dạng {\"facts\": [\"...\", ...]} bằng tiếng Việt, mỗi fact một câu "
                                "tự đứng được, tối đa 5 fact. Bỏ phần khách sáo/giải thích vòng vo."
                            ),
                        },
                        {"role": "user", "content": f"Tách đoạn sau thành các sự thật atomic:\n{text[:1200]}"},
                    ]
                    resp = remote_client.create_chat_completion(
                        messages=messages,
                        temperature=0.2,
                        frequency_penalty=0.0,
                        presence_penalty=0.0,
                        max_tokens=300,
                        response_format={"type": "json_object"},
                        timeout=10,
                    )
                    extractor = getattr(llm_service, "_extract_content", None)
                    content = extractor(resp) if callable(extractor) else ""
                    if not content and isinstance(resp, dict):
                        choices = resp.get("choices")
                        if isinstance(choices, list) and choices:
                            content = choices[0].get("message", {}).get("content", "")
                        else:
                            candidates = resp.get("candidates")
                            if isinstance(candidates, list) and candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                content = "".join(p.get("text", "") for p in parts if "text" in p)

                    content = content.strip()
                    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE).strip()
                    content = re.sub(r"\s*```$", "", content).strip()
                    data = _json.loads(content)
                    facts = data.get("facts") or []
                    if isinstance(facts, (list, tuple)):
                        return [str(f).strip() for f in facts if str(f or "").strip()][:5]
                except Exception as exc:
                    _warn(logger, f"tutor remote distill lỗi ({exc!r})")
                return []
            return distill_fn



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

    def ingest_fn(text: str, *, source: str = "tutor", gap_id: str = "", citations=(), confidence: float = 0.66) -> int:
        claim = str(text or "").strip()
        if not claim:
            return 0
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.66
        conf = max(0.4, min(0.85, conf))
        tags = ["tutor", "learned", "curiosity"]
        if bool(citations):
            tags.append("cited")
        if conf < 0.58:
            tags.append("low_confidence")
        request = {
            "target": "semantic_memory",
            "content": claim[:480],
            "confidence": conf,
            "evidence_ids": [gap_id or "tutor"],
            "storage_permission": True,
            "permission_required": False,
            "decay_policy": "normal",
            "reason": "curiosity_tutor",
            "source_module": "curiosity_tutor",
            "tags": tags,
            "metadata": {
                "storage_permission": True,
                "trusted_internal_commit": True,
                "source": str(source or "tutor"),
                "gap_id": gap_id,
                "citations": list(citations or ()),
                "confidence": conf,
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
    """Đóng gói nội dung màn hình THẬT cho Gemini đoán ngữ cảnh.

    Chỉ trả về context khi có nội dung màn hình thực sự (OCR/đường dẫn/vision facts) —
    KHÔNG dá»±ng câu hỏi chỉ từ tên app/cửa sổ của một app chạy ngầm đang idle, và KHÔNG
    nhồi telemetry chung chung (active window is.../focus kind is.../no input...) như thể
    đó là chữ trên màn hình. Mục tiêu: ưu tiên vision thật thay vì hỏi suông vô nghĩa.
    LƯU Ý RIÊNG TƯ: nội dung màn hình (OCR) sẽ được gửi tới Gemini ở nhánh này.
    """

    if snapshot is None:
        return ""
    try:
        from cortex.tutor.config import scrub_identity
    except Exception:
        def scrub_identity(x):  # type: ignore
            return str(x or "")

    app = str(getattr(snapshot, "active_app", "") or "").strip()
    title = str(getattr(snapshot, "active_window_title", "") or "").strip()
    url = str(getattr(snapshot, "url_or_path_hint", "") or "").strip()
    ocr_raw = str(getattr(snapshot, "ocr_text", "") or "").strip()

    # Lọc telemetry chung chung khỏi phần OCR: chỉ giữ dòng là nội dung màn hình thật.
    ocr_lines = [line.strip() for line in ocr_raw.splitlines() if line.strip()]
    real_ocr_lines = [line for line in ocr_lines if not _is_generic_telemetry_line(line)]
    ocr = "\n".join(real_ocr_lines).strip()

    vision_facts = [
        str(item).strip()
        for item in (getattr(snapshot, "vision_facts", ()) or ())
        if str(item).strip() and not _is_generic_telemetry_line(str(item))
    ]

    # Không có ná»™i dung màn hình thật ⇒ không hỏi Gemini, để vision pipeline lo.
    has_real_content = bool(ocr or url or vision_facts)
    if not has_real_content:
        return ""

    parts = []
    if app:
        parts.append(f"app={app}")
    if title:
        parts.append(f"cửa sổ={title}")
    if url:
        parts.append(f"đường dẫn={url}")
    if vision_facts:
        parts.append("vision: " + " | ".join(vision_facts[:3])[:300])
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
