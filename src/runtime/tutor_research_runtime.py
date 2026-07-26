# -*- coding: utf-8 -*-
"""Tutor delegation, research lifecycle and stale-result protection.

Extracted from RuntimeCoordinator so the composition root stops owning every policy.
"""
from __future__ import annotations

import random
import re
import threading
import time
from types import SimpleNamespace

from domain import Decision


class TutorResearchRuntimeMixin:
    def _tutor_boundary_note(self, event: str, exc: BaseException) -> None:
        logger = getattr(self, "logger", None)
        debug = getattr(logger, "debug", None)
        if callable(debug):
            try:
                debug("[tutor research] degraded event=%s error=%s", event, exc)
                return
            except Exception:
                return

    """Coordinator-facing mixin with no independent lifecycle."""

    def _looks_like_light_tutor_research_request(self, text: str) -> bool:
        try:
            from runtime.tutor_research_policy import score_research_need
            return bool(score_research_need(text, intent="world_knowledge", meaning_missing=False).should_delegate)
        except Exception:
            normalized = self._normalize_marker_text(text)
            return any(cue in normalized for cue in self._LIGHT_TUTOR_RESEARCH_CUES)


    def _is_tutor_research_delegation_only(self, text: str) -> bool:
        normalized = self._normalize_marker_text(text)
        if not normalized:
            return False
        try:
            from runtime.tutor_research_policy import is_explicit_research_request
            explicit = is_explicit_research_request(text)
        except Exception:
            explicit = any(cue in normalized for cue in self._LIGHT_TUTOR_RESEARCH_CUES)
        if not explicit:
            return False
        tokens = [tok for tok in normalized.split() if tok not in {"di", "nhe", "nha", "giup", "dum", "cho", "toi", "em", "hay"}]
        content = [tok for tok in tokens if tok not in {"nghien", "cuu", "dao", "sau", "search", "web", "gemini", "tutor", "fix", "elegant", "kiem", "chung"}]
        return len(content) <= 1


    def _strip_light_tutor_command(self, text: str) -> str:
        value = str(text or "").strip()
        normalized = self._normalize_marker_text(value)
        for phrase in ("gemini hãy search web nghiên cứu cho tôi về", "gemini hay search web nghien cuu cho toi ve", "nghiên cứu sâu", "nghien cuu sau", "hỏi sư phụ gemini", "hoi su phu gemini", "hỏi gemini", "hoi gemini"):
            norm_phrase = self._normalize_marker_text(phrase)
            if normalized.startswith(norm_phrase):
                return value[len(phrase):].strip(" :,-–—") or value
        return value


    def _topic_is_referent_only(self, text: str) -> bool:
        normalized = self._normalize_marker_text(text)
        if not normalized:
            return True
        return any(marker in normalized for marker in self._LIGHT_TUTOR_REFERENT_ONLY) and len(normalized.split()) <= 6


    def _build_light_tutor_research_prompt(self, topic: str, *, context: str = "") -> str:
        try:
            from runtime.tutor_research_policy import build_lightweight_research_prompt
            prompt = build_lightweight_research_prompt(topic, context=context)
            if "Hãy tìm hiểu kỹ" not in prompt:
                prompt = prompt.replace("Hãy dùng tìm kiếm web nếu cần để kiểm tra", "Hãy tìm hiểu kỹ và dùng tìm kiếm web nếu cần để kiểm tra", 1)
            if "tối đa 6 ý" not in prompt:
                prompt = prompt.replace("Trả lời tiếng Việt cô đọng,", "Trả lời tiếng Việt cô đọng, tối đa 6 ý,", 1)
            if "Không chain-of-thought" not in prompt:
                prompt = prompt.replace("Câu hỏi:", "Không chain-of-thought. Câu hỏi:", 1)
            return prompt[:395].rstrip()
        except Exception:
            return str(topic or "")[:395]


    def _is_tutor_delegation_only(self, text: str) -> bool:
        normalized = self._normalize_marker_text(text)
        if not normalized:
            return False
        markers = (
            "hoi su phu gemini", "hoi su phu", "hoi gemini", "nho gemini",
            "keu gemini", "tra gemini", "ask gemini", "ask your tutor",
        )
        stripped = normalized
        for token in ("di", "dum", "giup", "cho toi", "cho ban", "thu", "xem"):
            stripped = re.sub(rf"\b{re.escape(token)}\b", " ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return any(stripped == marker or stripped.startswith(marker + " ") for marker in markers) and len(stripped.split()) <= 6


    def _resolve_tutor_research_topic(self, current_text: str) -> str:
        """Resolve follow-up nghiên cứu bằng heuristic rẻ, không gọi thêm model."""

        candidates: list[str] = []
        previous = str(getattr(self, "last_user_text_for_semantics", "") or "").strip()
        if previous:
            candidates.append(previous)
        try:
            turns = self._ensure_session_turn_ledger().user_turns()
            candidates.extend(str(turn.text or "").strip() for turn in turns[-8:])
        except Exception as exc:
            self._tutor_boundary_note("session anchor history", exc)
        try:
            from runtime.tutor_research_policy import resolve_research_anchor
            resolution = resolve_research_anchor(current_text, candidates)
            self._last_tutor_anchor_resolution = {
                "topic": str(getattr(resolution, "topic", "") or "")[:900],
                "confidence": float(getattr(resolution, "confidence", 0.0) or 0.0),
                "anchor_text": str(getattr(resolution, "anchor_text", "") or "")[:900],
                "anchor_index": int(getattr(resolution, "anchor_index", -1) or -1),
                "assumption_note": str(getattr(resolution, "assumption_note", "") or ""),
                "misread_risk": str(getattr(resolution, "misread_risk", "") or ""),
            }
            return str(getattr(resolution, "topic", "") or "")
        except Exception:
            # Fallback cũ: ít thông minh hơn nhưng vẫn không ném vào chat hot path.
            current_norm = self._normalize_marker_text(current_text)
            for candidate in reversed(candidates):
                if not candidate or self._normalize_marker_text(candidate) == current_norm:
                    continue
                if self._is_tutor_delegation_only(candidate):
                    continue
                self._last_tutor_anchor_resolution = {
                    "topic": candidate[:900],
                    "confidence": 0.52,
                    "anchor_text": candidate[:900],
                    "anchor_index": -1,
                    "assumption_note": "fallback_recent_context",
                    "misread_risk": "medium",
                }
                return candidate
            self._last_tutor_anchor_resolution = {"topic": "", "confidence": 0.0, "misread_risk": "high"}
            return ""


    def _maybe_tutor_on_unclear_user(self, user_text, frame) -> None:
        """Khi Eris không hiểu/không phân loại nổi tin user → định tuyến.

        NGUYÊN TẮC: mặc định TỰ HỌC (hỏi Gemini âm thầm) — bạn KHÔNG phải giải thích
        kiến thức chung (vd "INTP 538", "Rust", tên phim). Chỉ HỎI LẠI BẠN khi đó là
        tham chiếu CÁ NHÂN mơ hồ mà Gemini không thể biết ("vụ đó hôm qua", "ý m là sao").

        - hỏi Gemini: chạy nền, im lặng, có throttle (Eris vẫn trả lời tự nhiên lượt này,
          học để lần sau hiểu hơn).
        - hỏi lại bạn: câu trả lời lượt này thành câu làm rõ ngắn (giọng Eris).
        No-op khi Master_Switch tắt.
        """

        self._clarify_user_pending = False
        self._research_pending = False
        self._research_topic = ""
        daemon = getattr(self, "tutor_daemon", None)
        if daemon is None:
            return
        try:
            text = str(user_text or "").strip()
            mark_stale = getattr(self, "_mark_active_research_stale_if_user_changed", None)
            if callable(mark_stale):
                mark_stale(text)
            words = text.split()
            meaning = ""
            ml = getattr(frame, "meaning_layer", None)
            if ml is not None:
                meaning = str(getattr(ml, "meaning", "") or "")
            intent = str(getattr(self, "last_user_intent", "") or "").strip().lower()
            unclear = (not meaning) or intent in ("", "unknown", "unclear", "other")

            # Route Tutor nhẹ: explicit research thì đào sâu vừa đủ; explicit search /
            # dữ kiện mới thì search nhanh. Câu kiến thức phổ thông vẫn để Terra trả lời,
            # vì gọi thêm Tutor cho "Pytest là gì" là cách biến điện thành tiếng thở dài.
            try:
                from runtime.tutor_research_policy import score_tutor_delegation
                tutor_decision = score_tutor_delegation(
                    text,
                    intent=intent,
                    meaning_missing=not bool(meaning),
                )
            except Exception:
                tutor_decision = SimpleNamespace(should_delegate=False, score=0.0, reason="policy_error", mode="none")

            if bool(getattr(tutor_decision, "should_delegate", False)) and callable(
                getattr(self, "request_tutor_answer", None)
            ):
                topic = self._resolve_tutor_research_topic(text)
                if topic and self._research_can_start():
                    mode = str(getattr(tutor_decision, "mode", "research") or "research")
                    anchor_meta = dict(getattr(self, "_last_tutor_anchor_resolution", {}) or {})
                    # Low-confidence anchor: hỏi lại trước, đừng search nhầm rồi
                    # đem kết quả đúng của câu sai về khoe. Máy móc cũng nên biết xấu hổ.
                    try:
                        from runtime.tutor_research_policy import anchor_resolution_needs_clarification
                        runtime_float = getattr(self, "_tutor_runtime_float", None)
                        floor = runtime_float("tutor", "low_confidence_clarify_threshold", default=0.55) if callable(runtime_float) else 0.55
                        probe = SimpleNamespace(**anchor_meta)
                        if anchor_resolution_needs_clarification(probe, confidence_floor=floor):
                            self._clarify_user_pending = True
                            self._research_pending = False
                            self._research_topic = ""
                            return
                    except Exception as exc:
                        self._tutor_boundary_note("anchor clarification probe", exc)
                    self._research_pending = True
                    self._research_topic = topic
                    anchor_note = (
                        f"anchor_conf={anchor_meta.get('confidence', 0):.2f}; "
                        f"anchor_risk={anchor_meta.get('misread_risk', '')}; "
                        f"assumption={anchor_meta.get('assumption_note', '')}; "
                    ) if anchor_meta else ""
                    if mode == "quick_search":
                        context = (
                            "Search nhanh qua Tutor web; trả lời cô đọng, ưu tiên nguồn/link nếu có. "
                            f"route={getattr(tutor_decision, 'reason', '')}; "
                            f"{anchor_note}"
                            "không dùng Deep Research API hoặc Google grounding"
                        )
                    else:
                        context = (
                            "Tra cứu nhẹ qua Tutor web; trả lời cô đọng, ưu tiên nguồn chính. "
                            f"route={getattr(tutor_decision, 'reason', '')}; "
                            f"{anchor_note}"
                            "không dùng Deep Research API hoặc Google grounding"
                        )
                    try:
                        self._fire_research_followup(topic, context=context, mode=mode)
                    except TypeError:
                        # Test doubles/legacy runtime chưa nhận mode; giữ tương thích.
                        self._fire_research_followup(topic, context=context)
                    return

            # Tin nhắn quá ngắn và không có cue nghiên cứu thì không đáng mở Tutor.
            if len(words) < 3:
                return

            low = text.lower()
            # Tham chiếu cá nhân/mơ hồ — chỉ bạn giải đáp được → hỏi lại bạn.
            personal_markers = (
                "vụ đó", "vụ này", "cái đó", "cái này", "cái kia", "cái nớ", "hôm qua",
                "lúc nãy", "khi nãy", "hồi nãy", "bữa đó", "như thế", "như vậy",
                "ý m là sao", "ý mày là sao", "ý em là sao", "ý là sao", "sao cơ", "hả?",
            )
            is_personal_ambiguous = (len(words) <= 6 and any(m in low for m in personal_markers))

            if is_personal_ambiguous:
                # Không hiểu bạn ám chỉ gì → hỏi lại bạn ngay trong câu trả lời lượt này.
                self._clarify_user_pending = True
                return

            # Mặc định: tự học qua Gemini (âm thầm, throttle). Eris vẫn trả lời tự nhiên.
            if not unclear:
                return
            self._fire_tutor_lookup(text, context="Khái niệm trong tin nhắn Eris chưa rõ")
        except Exception as exc:
            self._tutor_boundary_note("curiosity tutor unclear", exc)


    def _fire_tutor_lookup(self, topic: str, *, context: str = "") -> None:
        """Bắn một lượt hỏi Gemini ở thread nền (có throttle). Không chặn trả lời chat."""

        daemon = getattr(self, "tutor_daemon", None)
        lookup = getattr(self, "request_tutor_lookup", None)
        if daemon is None or not callable(lookup):
            return
        now = time.time()
        last = float(getattr(self, "_last_unclear_tutor_ts", 0.0) or 0.0)
        cooldown = float(getattr(getattr(daemon, "config", None), "min_seconds_between_episodes", 120.0) or 120.0)
        if now - last < cooldown:
            return
        self._last_unclear_tutor_ts = now

        def _bg():
            try:
                ok = lookup(topic, context=context, kind_hint="ask_gemini", stake=0.7)
                if not ok:
                    self.logger.info("[tutor lookup] no_episode topic=%r context=%r", str(topic)[:120], str(context)[:120])
            except Exception as exc:
                self.logger.warning("[tutor lookup] background error: %s", exc)

        threading.Thread(target=_bg, name="ERIS-TutorOnUnclear", daemon=True).start()


    def _looks_like_knowledge_question(self, low: str) -> bool:
        """Legacy diagnostic only. Tutor user-facing phải gate bằng intent world_knowledge."""

        low = str(low or "")
        return any(marker in low for marker in self._KNOWLEDGE_QUESTION_MARKERS)


    def _tutor_runtime_bool(self, *path: str, default: bool = True) -> bool:
        try:
            from runtime.runtime_settings_store import runtime_bool
            return bool(runtime_bool(*path, default=default))
        except Exception:
            return bool(default)


    def _tutor_runtime_float(self, *path: str, default: float = 0.0) -> float:
        try:
            from runtime.runtime_settings_store import runtime_float
            return float(runtime_float(*path, default=default))
        except Exception:
            return float(default)


    def _mark_active_research_stale_if_user_changed(self, user_text: str) -> None:
        """Nếu user đổi chủ đề trong lúc Tutor chạy, đánh dấu job cũ là stale."""

        if not getattr(self, "_research_in_flight", False):
            return
        if not self._tutor_runtime_bool("tutor", "stale_result_guard_enabled", default=True):
            return
        active = getattr(self, "_active_research_job", None)
        if not isinstance(active, dict):
            return
        topic = str(active.get("topic", "") or "")
        incoming = str(user_text or "").strip()
        if not incoming or not topic:
            return
        try:
            from runtime.tutor_search_jobs import looks_same_topic
            same = looks_same_topic(incoming, topic)
        except Exception:
            same = incoming.lower().strip() in topic.lower() or topic.lower().strip() in incoming.lower()
        if same:
            return
        active["stale"] = True
        active["stale_reason"] = "user_changed_topic"
        active["stale_user_text"] = incoming[:180]
        self._active_research_job = active
        try:
            self.logger.info("[tutor research] marked stale job=%s reason=user_changed_topic topic=%r new=%r", active.get("job_id"), topic[:80], incoming[:80])
        except Exception as exc:
            self._tutor_boundary_note("mark stale log", exc)


    def _research_can_start(self) -> bool:
        """Debounce nhịp tra cứu: không tra khi đang có lượt tra chạy, và cách nhau tối thiểu."""

        runtime_bool = getattr(self, "_tutor_runtime_bool", None)
        if callable(runtime_bool) and not runtime_bool("tutor", "enabled", default=True):
            return False
        if getattr(self, "_research_in_flight", False):
            return False
        now = time.time()
        last = float(getattr(self, "_last_research_ts", 0.0) or 0.0)
        if now - last < 6.0:
            return False
        return True


    def _maybe_start_self_declared_tutor_search(self, decision: Decision, *, user_text: str, frame=None) -> Decision:
        """Nếu Eris tự nói "đợi em tra", biến lời hứa đó thành hành động thật.

        Đây là lớp tự do có kiểm soát: pre-detector có thể lọt câu hỏi lái, nhưng
        main brain vẫn được phép tự nhận ra cần search. Khi nó surface lời hứa
        search/kiểm tra, runtime spawn Tutor ở nền và thay câu lượt này bằng
        nhịp chờ ngắn, không để nó vừa hứa tra vừa đoán luôn. Rất tiếc cho thói
        quen bịa tự tin, nó không qua cửa này.
        """

        try:
            if decision is None:
                return decision
            # Nếu prepass đã route Tutor rồi thì không spawn lần hai.
            already_delegated = bool(
                getattr(self, "_research_pending", False)
                or getattr(self, "_research_in_flight", False)
            )
            from runtime.tutor_self_search_bridge import (
                build_self_search_wait_text,
                detect_self_search_request,
            )

            self_search_decision = detect_self_search_request(
                user_text,
                getattr(decision, "text", ""),
                already_delegated=already_delegated,
            )
            if not bool(getattr(self_search_decision, "should_start", False)):
                return decision
            runtime_bool = getattr(self, "_tutor_runtime_bool", None)
            if callable(runtime_bool) and not runtime_bool("tutor", "self_search_enabled", default=True):
                return decision
            if not callable(getattr(self, "request_tutor_answer", None)):
                return decision
            if not self._research_can_start():
                return decision

            topic = self._resolve_tutor_research_topic(user_text)
            if not topic:
                return decision
            anchor_meta = dict(getattr(self, "_last_tutor_anchor_resolution", {}) or {})
            try:
                from runtime.tutor_research_policy import anchor_resolution_needs_clarification
                runtime_float = getattr(self, "_tutor_runtime_float", None)
                floor = runtime_float("tutor", "low_confidence_clarify_threshold", default=0.55) if callable(runtime_float) else 0.55
                if anchor_resolution_needs_clarification(SimpleNamespace(**anchor_meta), confidence_floor=floor):
                    decision.text = "Tôi biết vụ này cần tra, nhưng neo hiện tại hơi mù. Bạn chỉ rõ tôi đang tra phần nào đã, kẻo tôi lại search nhầm như một cái GPS bị xúc phạm."
                    decision.action = "tutor_anchor_clarify"
                    decision.should_speak = True
                    decision.confidence = min(float(getattr(decision, "confidence", 0.72) or 0.72), 0.55)
                    return decision
            except Exception as exc:
                self._tutor_boundary_note("self search anchor guard", exc)
            mode = str(getattr(self_search_decision, "mode", "quick_search") or "quick_search")
            if mode not in {"quick_search", "research"}:
                mode = "quick_search"

            self._research_pending = True
            self._research_topic = topic
            anchor_note = (
                f"anchor_conf={anchor_meta.get('confidence', 0):.2f}; "
                f"anchor_risk={anchor_meta.get('misread_risk', '')}; "
                f"assumption={anchor_meta.get('assumption_note', '')}; "
            ) if anchor_meta else ""
            context = (
                "Eris tự nhận ra câu này cần tra cứu sau khi pre-detector không bắt được; "
                f"route={getattr(self_search_decision, 'reason', '')}; "
                f"{anchor_note}"
                "dùng Tutor/Gemini Web hiện có, trả lời cô đọng, ưu tiên nguồn/link; "
                "không dùng Deep Research API hoặc Google grounding"
            )
            self._fire_research_followup(topic, context=context, mode=mode)

            decision.text = build_self_search_wait_text(mode=mode, topic=topic)
            decision.intent = "world_knowledge"
            decision.action = "tutor_self_search_wait"
            decision.should_speak = True
            decision.confidence = min(float(getattr(decision, "confidence", 0.72) or 0.72), 0.72)
            decision.reasoning_tags = tuple(dict.fromkeys((
                *tuple(getattr(decision, "reasoning_tags", ()) or ()),
                "tutor_self_declared_wait",
                "quick_search" if mode == "quick_search" else "research_followup",
            )))
            decision.debug_trace = self._join_debug_trace(
                getattr(decision, "debug_trace", ""),
                f"self_declared_tutor_search:{mode}:{getattr(self_search_decision, 'reason', '')}",
            )
            try:
                if frame is not None:
                    frame.debug_notes.append(
                        f"self_declared_tutor_search={mode}:{getattr(self_search_decision, 'reason', '')}"
                    )
            except Exception as exc:
                self._tutor_boundary_note("self search frame note", exc)
            return decision
        except Exception as exc:
            self._tutor_boundary_note("self search bridge", exc)
            return decision


    def _fire_research_followup(self, topic: str, *, context: str = "", mode: str = "research") -> None:
        """Nhịp 2: thread nền đi hỏi gia sư rồi gửi đáp án về (không chặn trả lời lượt này)."""

        answerer = getattr(self, "request_tutor_answer", None)
        if not callable(answerer):
            return
        self._last_research_ts = time.time()
        self._research_in_flight = True
        try:
            from runtime.tutor_search_jobs import make_tutor_search_job
            seq = int(getattr(self, "_research_job_seq", 0) or 0) + 1
            self._research_job_seq = seq
            job = make_tutor_search_job(topic, mode=mode, seq=seq, user_turn_id=str(getattr(self, "current_user_turn_id", "") or ""))
            self._active_research_job = {**job.to_dict(), "topic": str(topic or ""), "stale": False}
        except Exception:
            job = SimpleNamespace(job_id=f"research_{int(time.time() * 1000)}", topic_hash="", mode=mode)
            self._active_research_job = {"job_id": job.job_id, "topic": str(topic or ""), "stale": False, "mode": str(mode or "research")}

        def _bg():
            answer = None
            try:
                # Để nhịp 1 ("đợi em tra chút") kịp ra trước câu trả lời.
                time.sleep(1.5)
                try:
                    if str(mode or "research") == "quick_search":
                        answer = answerer(topic, context=context, search=True)
                    else:
                        answer = answerer(topic, context=context, research=True)
                except TypeError:
                    # Adapter cũ/test double chưa có cờ research vẫn chạy được.
                    answer = answerer(topic, context=context)
                if not answer:
                    self.logger.info("[tutor research] empty_answer topic=%r context=%r", str(topic)[:120], str(context)[:120])
            except Exception as exc:
                self.logger.warning("[tutor research] background error: %s", exc)
                answer = None
            finally:
                try:
                    self._deliver_research_followup(topic, answer, mode=mode, job_id=str(getattr(job, "job_id", "") or ""))
                except Exception as exc:
                    self.logger.warning("[tutor research] deliver error: %s", exc)
                active = getattr(self, "_active_research_job", None)
                if not isinstance(active, dict) or str(active.get("job_id", "")) == str(getattr(job, "job_id", "")):
                    self._research_in_flight = False
                    self._active_research_job = None

        threading.Thread(target=_bg, name="ERIS-ResearchFollowup", daemon=True).start()


    def _deliver_research_followup(self, topic: str, answer, *, mode: str = "research", job_id: str = "") -> None:
        """Gửi câu trả lời nhịp 2 ra body bằng giọng Eris (qua đường decision chuẩn)."""

        active = getattr(self, "_active_research_job", None)
        runtime_bool = getattr(self, "_tutor_runtime_bool", None)
        stale_guard_enabled = runtime_bool("tutor", "stale_result_guard_enabled", default=True) if callable(runtime_bool) else True
        if stale_guard_enabled and isinstance(active, dict):
            if job_id and str(active.get("job_id", "")) != str(job_id):
                try:
                    self.logger.info("[tutor research] drop stale result job=%s active=%s", job_id, active.get("job_id"))
                except Exception as exc:
                    self._tutor_boundary_note("stale result job log", exc)
                return
            if bool(active.get("stale", False)):
                try:
                    self.logger.info("[tutor research] drop stale result job=%s reason=%s", job_id or active.get("job_id"), active.get("stale_reason", "stale"))
                except Exception as exc:
                    self._tutor_boundary_note("stale result reason log", exc)
                return

        answer = str(answer or "").strip()
        if answer:
            if str(mode or "research") == "quick_search":
                lead = random.choice((
                    "Em search nhanh ra rồi nè. ",
                    "Rồi, em kiểm tra nhanh được thế này. ",
                    "Em vừa tra nhanh xong. ",
                ))
            else:
                lead = random.choice((
                    "Rồi, em tra xong rồi nha. ",
                    "Đây ạ, em vừa tra được: ",
                    "Em tra ra rồi nè. ",
                ))
            text = f"{lead}{answer}"
        else:
            text = random.choice((
                "Em lục một vòng mà chưa ra cái gì chắc chắn về vụ này. Em chưa dám nói bừa đâu.",
                "Hừm, vụ này em tra chưa tới nơi. Để em đào lại sau rồi nói bạn nghe.",
            ))
        artifact = {}
        research_thread = {}
        research_metrics = {}
        memory_decision = {}
        try:
            artifact = dict(getattr(self, "_last_tutor_research_artifact", {}) or {})
            research_thread = dict(getattr(self, "_last_tutor_research_thread", {}) or {})
            research_metrics = dict(getattr(self, "_last_tutor_research_metrics", {}) or {})
            memory_decision = dict(getattr(self, "_last_tutor_research_memory_decision", {}) or {})
        except Exception:
            artifact = {}
            research_thread = {}
            research_metrics = {}
            memory_decision = {}
        verification_status = ""
        try:
            verification_status = str((artifact.get("verification") or {}).get("overall_status") or "")
        except Exception:
            verification_status = ""
        decision = Decision(
            text=text,
            animation="stand",
            intent="world_knowledge",
            action="tutor_search_followup" if str(mode or "research") == "quick_search" else "tutor_followup",
            reasoning_tags=(
                "tutor_grounded",
                "quick_search" if str(mode or "research") == "quick_search" else "research_followup",
                f"verification:{verification_status}" if verification_status else "verification:unknown",
            ),
            should_speak=True,
            confidence=0.78 if answer else 0.35,
            parse_mode="chat",
            debug_trace=f"{str(mode or 'research')}_followup; topic={str(topic)[:120]}; verification={verification_status or 'unknown'}",
        )
        # Tutor follow-up dùng cùng public commit/stage transport. Wording không
        # đi qua legacy style guards; evidence bundle mới là authority.
        try:
            from actions.capability_registry import canonicalize_action_id
            decision.system_action = canonicalize_action_id(decision.system_action)
        except Exception as exc:
            self._tutor_boundary_note("canonicalize tutor action", exc)
        try:
            from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
            commit_surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(decision.text)
            public_text = commit_surfaces.display_text
            memory_text = commit_surfaces.memory_text
        except Exception:
            public_text = str(decision.text or "").strip()
            memory_text = public_text
        if public_text:
            if memory_text:
                self._append_chat_history("assistant", memory_text, invalid=False)
            ledger_meta = {
                "intent": decision.intent,
                "parse_mode": decision.parse_mode,
                "source": "tutor_followup",
                "research_mode": str(mode or "research"),
                "research_job_id": str(job_id or ""),
            }
            anchor_meta = dict(getattr(self, "_last_tutor_anchor_resolution", {}) or {})
            if anchor_meta:
                ledger_meta["anchor_resolution"] = anchor_meta
            if research_thread:
                ledger_meta["research_thread"] = research_thread
            if artifact:
                ledger_meta["evidence_bundle_id"] = str(artifact.get("bundle_id") or "")
                ledger_meta["verification"] = dict(artifact.get("verification") or {})
            if research_metrics:
                ledger_meta["research_metrics"] = research_metrics
            if memory_decision:
                ledger_meta["research_memory_policy"] = memory_decision
            self._ensure_session_turn_ledger().record_assistant(
                public_text,
                meta=ledger_meta,
            )
            self.last_chat_answer = public_text
        self._send_decision_to_body(decision, channel="chat")


__all__ = ["TutorResearchRuntimeMixin"]
