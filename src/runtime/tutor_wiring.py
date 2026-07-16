# -*- coding: utf-8 -*-
"""
runtime/tutor_wiring.py
=======================

Ná»‘i Curiosity Tutor vÃ o runtime tháº­t. Má»i adapter Ä‘á»u phÃ²ng thá»§: Master_Switch táº¯t â‡’
`build_tutor_daemon_from_runtime` tráº£ None (khÃ´ng tÃ¡c Ä‘á»™ng gÃ¬); thiáº¿u subsystem â‡’ adapter
Ä‘Ã³ None/no-op chá»© khÃ´ng bao giá» nÃ©m vÃ o hot path.

LÆ¯U Ã AN TOÃ€N: Ä‘Æ°á»ng ghi vÃ o trÃ­ nhá»› dÃ i háº¡n lÃ  nháº¡y cáº£m. Adapter commit claim
(`_build_ingest_fn`) chá»‰ cháº¡y khi tÃ¬m tháº¥y Ä‘Æ°á»ng commit rÃµ rÃ ng; náº¿u khÃ´ng, nÃ³ tráº£ 0 vÃ 
ghi cáº£nh bÃ¡o má»™t láº§n â€” KHÃ”NG Ä‘oÃ¡n API rá»“i ghi rÃ¡c vÃ o memory.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional


_GENERIC_TELEMETRY_PREFIXES = (
    "active window is ",
    "focus kind is ",
    "there has been no input for ",
    "browser target is visible:",
    "context classification:",
)


def _is_generic_telemetry_line(text: str) -> bool:
    """True náº¿u má»™t dÃ²ng chá»‰ lÃ  telemetry chung chung, KHÃ”NG pháº£i ná»™i dung mÃ n hÃ¬nh tháº­t."""

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
    """Dá»±ng TutorDaemon Ä‘Ã£ ná»‘i adapter, hoáº·c None náº¿u Master_Switch táº¯t / lá»—i build."""

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
        _warn(logger, f"tutor: khÃ´ng import Ä‘Æ°á»£c module ({exc!r})")
        return None

    tutor_logger = TutorLogger(sink=logger)
    config = TutorConfig.from_env(tutor_logger)
    if not config.enabled:
        # Master_Switch táº¯t: khÃ´ng dá»±ng gÃ¬, khÃ´ng má»Ÿ trÃ¬nh duyá»‡t, khÃ´ng truy cáº­p máº¡ng.
        return None

    _info(logger, "tutor: Master_Switch Báº¬T â€” Ä‘ang dá»±ng Curiosity Tutor daemon")

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
    # Cho tick truy cáº­p collector Ä‘á»ƒ náº¡p gap.
    runtime_owner._tutor_collector = collector

    # API "Ä‘i há»i theo yÃªu cáº§u": cognition gá»i khi khÃ´ng cháº¯c / user báº£o tra cá»©u.
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
            # Cháº¡y ngay (forced bá» qua idle/rate-limit; váº«n tÃ´n trá»ng risk guard).
            ep = daemon.run_once(idle=False, now=now)
            if ep is None:
                _warn(logger, f"tutor request_lookup khÃ´ng cháº¡y Ä‘Æ°á»£c episode topic={str(topic)[:120]!r}")
                return False
            if getattr(ep, "fail_reason", None):
                _warn(logger, f"tutor request_lookup failed reason={getattr(ep, 'fail_reason', '')} topic={str(topic)[:120]!r}")
            return ep is not None
        except Exception as exc:
            _warn(logger, f"tutor request_lookup lá»—i ({exc!r})")
            return False

    runtime_owner.request_tutor_lookup = request_tutor_lookup

    # API "tra rá»“i TRáº¢ Lá»œI ngay": dÃ¹ng cho nhá»‹p 2 cá»§a chat khi báº¡n há»i cÃ¢u kiáº¿n thá»©c
    # mÃ  Eris chÆ°a biáº¿t. Tráº£ vá» ná»™i dung cÃ¢u tráº£ lá»i (str) hoáº·c None náº¿u tra khÃ´ng ra.
    def request_tutor_answer(topic, *, context=""):
        try:
            answer = daemon.ask_now(topic, context=context)
            if answer:
                return answer
            # Fallback: cÃ¢u há»i kiáº¿n thá»©c khÃ´ng nÃªn phá»¥ thuá»™c hoÃ n toÃ n vÃ o Gemini Web
            # (browser profile/captcha/selector ráº¥t dá»… táº­t). DÃ¹ng Gemini grounding API
            # qua ActionExecutor náº¿u cÃ³, Ä‘á»ƒ nhá»‹p 2 váº«n cÃ³ cÃ¢u tráº£ lá»i.
            fallback = _ask_gemini_grounding_fallback(runtime_owner, topic, logger)
            if fallback:
                _info(logger, "tutor request_answer dÃ¹ng fallback Gemini grounding API")
                return fallback
            _warn(logger, f"tutor request_answer khÃ´ng cÃ³ káº¿t quáº£ topic={str(topic)[:120]!r}")
            return None
        except Exception as exc:
            _warn(logger, f"tutor request_answer lá»—i ({exc!r})")
            fallback = _ask_gemini_grounding_fallback(runtime_owner, topic, logger)
            return fallback or None

    runtime_owner.request_tutor_answer = request_tutor_answer

    # Ná»‘i KnowledgeProvider (Ä‘á»c claim Ä‘Ã£ há»c) vÃ o SituationModel náº¿u reachable.
    try:
        _attach_knowledge_provider(runtime_owner, logger)
    except Exception as exc:
        _warn(logger, f"tutor: khÃ´ng ná»‘i Ä‘Æ°á»£c knowledge provider ({exc!r})")

    return daemon


def _ask_gemini_grounding_fallback(runtime_owner: Any, topic: Any, logger: Any) -> str:
    """Fallback cho request_tutor_answer khi tutor web/browser cháº¿t.

    ÄÃ¢y khÃ´ng thay tháº¿ Curiosity Tutor dÃ i háº¡n; nÃ³ chá»‰ cá»©u Ä‘Æ°á»ng user-facing
    "báº¡n há»i kiáº¿n thá»©c -> Eris tra rá»“i tráº£ lá»i". Náº¿u ActionExecutor cÃ³
    search_web (Gemini grounding API), dÃ¹ng nÃ³ Ä‘á»ƒ trÃ¡nh phá»¥ thuá»™c Playwright.
    """

    query = str(topic or "").strip()
    if not query:
        return ""
    executor = getattr(runtime_owner, "action_executor", None)
    execute = getattr(executor, "execute", None)
    if callable(execute):
        try:
            result = execute("search_web", query)
            if bool(getattr(result, "success", False)):
                data = getattr(result, "data", {}) or {}
                answer = str(data.get("answer") or getattr(result, "message", "") or "").strip()
                sources = str(data.get("sources") or "").strip()
                if answer and sources and "Nguon:" not in answer and "Nguá»“n:" not in answer:
                    return f"{answer}\nNguá»“n:\n{sources}"
                return answer
            _warn(logger, f"tutor fallback search_web failed: {getattr(result, 'message', '')}")
        except Exception as exc:
            _warn(logger, f"tutor fallback search_web lá»—i ({exc!r})")
    return ""


def _attach_knowledge_provider(runtime_owner: Any, logger: Any) -> None:
    """Gáº¯n KnowledgeProvider vÃ o SituationModel Ä‘á»ƒ dá»± Ä‘oÃ¡n dÃ¹ng tri thá»©c Ä‘Ã£ há»c."""

    from cortex.tutor.knowledge_provider import KnowledgeProvider

    store = _reach_semantic_store(runtime_owner)
    if store is None or not callable(getattr(store, "recall", None)):
        _warn(logger, "tutor: khÃ´ng tÃ¬m tháº¥y semantic store cho knowledge provider")
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
        _info(logger, "tutor: Ä‘Ã£ ná»‘i KnowledgeProvider vÃ o SituationModel")
    else:
        _info(logger, "tutor: KnowledgeProvider sáºµn sÃ ng (SituationModel sáº½ ná»‘i khi pipeline dá»±ng)")


def tutor_tick(runtime_owner: Any, *, observer_frame: Any = None, channel: str = "", snapshot: Any = None) -> None:
    """Náº¡p gap (observer + violation) rá»“i cháº¡y má»™t episode náº¿u Ä‘á»§ Ä‘iá»u kiá»‡n. KhÃ´ng bao giá» nÃ©m."""

    import time as _time

    daemon = getattr(runtime_owner, "tutor_daemon", None)
    collector = getattr(runtime_owner, "_tutor_collector", None)
    if daemon is None or collector is None:
        return
    try:
        now = _time.time()
        # Lazy-attach KnowledgeProvider vÃ o SituationModel (shadow pipeline táº¡o nÃ³ lazily).
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
        # Nguá»“n 1: observer 'unknown' â€” kÃ¨m Ä‘Ã³ng gÃ³i ná»™i dung mÃ n hÃ¬nh tháº­t Ä‘á»ƒ Gemini Ä‘oÃ¡n.
        if observer_frame is not None:
            try:
                screen_ctx = _screen_context_from_snapshot(snapshot)
                collector.push(collector.collect_from_observer(observer_frame, now=now, screen_context=screen_ctx))
            except Exception:
                pass
        # Nguá»“n 2: vi pháº¡m ká»³ vá»ng cá»§a SituationModel (náº¿u reachable).
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
# Adapters (phÃ²ng thá»§)
# ---------------------------------------------------------------------------

def _build_generate_fn(runtime_owner: Any, logger: Any) -> Optional[Callable[[str], str]]:
    """Local hoáº·c Remote LLM text gen Ä‘á»ƒ sinh cÃ¢u há»i/phÃ¢n loáº¡i. None â‡’ heuristic fallback."""

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
                        {"role": "system", "content": "Tráº£ vá» JSON gá»n dáº¡ng {\"text\": \"...\"} báº±ng tiáº¿ng Viá»‡t. Tuyá»‡t Ä‘á»‘i khÃ´ng thÃªm lá»i dáº«n hay giáº£i thÃ­ch ngoÃ i JSON."},
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
                    _warn(logger, f"tutor remote generate_fn lá»—i ({exc!r})")
                    return ""
            return generate_fn



def _build_distill_fn(runtime_owner: Any, logger: Any) -> Optional[Callable[[str], list]]:
    """TÃ¡ch cÃ¢u tráº£ lá»i gia sÆ° thÃ nh cÃ¡c fact ngáº¯n, atomic qua local hoáº·c remote LLM.

    None â‡’ ClaimDigest tá»± fallback tÃ¡ch cÃ¢u báº±ng heuristic. Lá»—i LLM khÃ´ng bao giá»
    nÃ©m vÃ o hot path â€” tráº£ [] Ä‘á»ƒ digest dÃ¹ng fallback.
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
                                "Báº¡n tÃ¡ch kiáº¿n thá»©c thÃ nh cÃ¡c sá»± tháº­t ngáº¯n, Ä‘á»™c láº­p, khÃ´ng trÃ¹ng. "
                                "Tráº£ JSON dáº¡ng {\"facts\": [\"...\", ...]} báº±ng tiáº¿ng Viá»‡t, má»—i fact má»™t cÃ¢u "
                                "tá»± Ä‘á»©ng Ä‘Æ°á»£c, tá»‘i Ä‘a 5 fact. Bá» pháº§n khÃ¡ch sÃ¡o/giáº£i thÃ­ch vÃ²ng vo."
                            ),
                        },
                        {"role": "user", "content": f"TÃ¡ch Ä‘oáº¡n sau thÃ nh cÃ¡c sá»± tháº­t atomic:\n{text[:1200]}"},
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
                    _warn(logger, f"tutor remote distill lá»—i ({exc!r})")
                return []
            return distill_fn



def _build_ingest_fn(runtime_owner: Any, tutor_logger: Any, logger: Any) -> Optional[Callable[..., int]]:
    """ÄÆ°á»ng commit claim vÃ o trÃ­ nhá»› ngá»¯ nghÄ©a (cÃ³ embedding) qua memory core/kernel.

    Claim Ä‘Æ°á»£c lÆ°u vá»›i tag "tutor"/"learned" + source provenance, confidence vá»«a pháº£i, vÃ 
    storage_permission=True (commit ná»™i bá»™ tin cáº­y). Store ngá»¯ nghÄ©a Ä‘Ã£ gáº¯n embedding_index
    â‡’ bÃ i há»c cÃ³ embedding, recall láº§n sau dÃ¹ng Ä‘Æ°á»£c.
    """

    # Cho phÃ©p ngÆ°á»i dÃ¹ng override hoÃ n toÃ n náº¿u muá»‘n.
    custom = getattr(runtime_owner, "tutor_ingest_fn", None)
    if callable(custom):
        return custom

    committer = _reach_memory_commit(runtime_owner)
    if committer is None:
        _warn(logger, "tutor: khÃ´ng tÃ¬m tháº¥y Ä‘Æ°á»ng commit memory â€” claim sáº½ khÃ´ng Ä‘Æ°á»£c lÆ°u")
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
            _warn(logger, f"tutor: commit claim lá»—i ({exc!r})")
            return 0
        outcome = str(getattr(decision, "outcome", "") or "")
        stored = str(getattr(decision, "stored_id", "") or "")
        return 1 if (outcome in {"accepted", "tentative"} and stored) else 0

    return ingest_fn


def _build_thought_sink(runtime_owner: Any, logger: Any) -> Optional[Any]:
    """Äáº©y Share_Impulse vÃ o internal_agenda náº¿u cÃ³. None â‡’ khÃ´ng khoe (an toÃ n)."""

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
    """True náº¿u Eris Ä‘Ã£ biáº¿t topic (recall trÃ­ nhá»› trÃºng) â‡’ router skip, Ä‘á»¡ há»i láº¡i."""

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
# Reach helpers â€” dÃ² má»m vÃ o subsystem, khÃ´ng bÃ¡m cá»©ng.
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
    """ÄÃ³ng gÃ³i ná»™i dung mÃ n hÃ¬nh THáº¬T cho Gemini Ä‘oÃ¡n ngá»¯ cáº£nh.

    Chá»‰ tráº£ vá» context khi cÃ³ ná»™i dung mÃ n hÃ¬nh thá»±c sá»± (OCR/Ä‘Æ°á»ng dáº«n/vision facts) â€”
    KHÃ”NG dá»±ng cÃ¢u há»i chá»‰ tá»« tÃªn app/cá»­a sá»• cá»§a má»™t app cháº¡y ngáº§m Ä‘ang idle, vÃ  KHÃ”NG
    nhá»“i telemetry chung chung (active window is.../focus kind is.../no input...) nhÆ° thá»ƒ
    Ä‘Ã³ lÃ  chá»¯ trÃªn mÃ n hÃ¬nh. Má»¥c tiÃªu: Æ°u tiÃªn vision tháº­t thay vÃ¬ há»i suÃ´ng vÃ´ nghÄ©a.
    LÆ¯U Ã RIÃŠNG TÆ¯: ná»™i dung mÃ n hÃ¬nh (OCR) sáº½ Ä‘Æ°á»£c gá»­i tá»›i Gemini á»Ÿ nhÃ¡nh nÃ y.
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

    # Lá»c telemetry chung chung khá»i pháº§n OCR: chá»‰ giá»¯ dÃ²ng lÃ  ná»™i dung mÃ n hÃ¬nh tháº­t.
    ocr_lines = [line.strip() for line in ocr_raw.splitlines() if line.strip()]
    real_ocr_lines = [line for line in ocr_lines if not _is_generic_telemetry_line(line)]
    ocr = "\n".join(real_ocr_lines).strip()

    vision_facts = [
        str(item).strip()
        for item in (getattr(snapshot, "vision_facts", ()) or ())
        if str(item).strip() and not _is_generic_telemetry_line(str(item))
    ]

    # KhÃ´ng cÃ³ ná»™i dung mÃ n hÃ¬nh tháº­t â‡’ khÃ´ng há»i Gemini, Ä‘á»ƒ vision pipeline lo.
    has_real_content = bool(ocr or url or vision_facts)
    if not has_real_content:
        return ""

    parts = []
    if app:
        parts.append(f"app={app}")
    if title:
        parts.append(f"cá»­a sá»•={title}")
    if url:
        parts.append(f"Ä‘Æ°á»ng dáº«n={url}")
    if vision_facts:
        parts.append("vision: " + " | ".join(vision_facts[:3])[:300])
    if ocr:
        parts.append(f"chá»¯ trÃªn mÃ n hÃ¬nh: {ocr[:300]}")
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
    """Tráº£ callable commit(request) tá»« memory_kernel/memory_core náº¿u cÃ³."""

    for attr in ("memory_kernel", "memory_core"):
        obj = getattr(runtime_owner, attr, None)
        if obj is not None and callable(getattr(obj, "commit", None)):
            return obj.commit
    return None


def _reach_semantic_store(runtime_owner: Any) -> Optional[Any]:
    """Tráº£ semantic store (cÃ³ recall + embedding_index) tá»« memory core/kernel."""

    candidates = []
    for attr in ("memory_core", "memory_kernel"):
        obj = getattr(runtime_owner, attr, None)
        if obj is None:
            continue
        candidates.append(obj)
        # kernel cÃ³ thá»ƒ bá»c core qua .core/.cognition/.memory_cognition
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
