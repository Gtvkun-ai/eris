from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any, Mapping

from cortex.action_planner import ACTION_SPACE
from cortex.contracts import (
    AgentSpeechCore,
    CognitiveActionPlan,
    CognitiveAppraisal,
    InnerThought,
    SessionRitualReport,
    ThoughtStreamReport,
)
from cortex.internal_state import PersistentInternalState
from domain import Decision
from runtime.greeting_preset_runtime import emit_session_ritual_preset
from core.temporal_context import build_temporal_context_from_runtime
from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.voice_policy import VOICE_POLICY


class PromptContextBuilderMixin:
    def _log_exception(self, message: str, *args) -> None:
        log_exception = getattr(self.logger, "exception", None)
        if callable(log_exception):
            log_exception(message, *args)
            return
        rendered = message % args if args else message
        self.logger.warning("%s %s", rendered, traceback.format_exc().strip())

    def _session_ritual_fallback_decision(self, *, source: str, tone: str = "quiet_background") -> Decision:
        # Bỏ câu chào canned "Ngài quay lại rồi." — câu cố định mỗi lần khởi động
        # nghe như macro, không phải một hiện diện. Khi LLM greeting fail/empty,
        # ERIS degrade về IM (chỉ cử động/đứng) thay vì rơi vào template. Đây là
        # nguyên tắc chung: fallback → silence/body, không bao giờ → câu canned.
        return Decision(
            text="",
            animation="stand",
            intent="session_ritual",
            reasoning_tags=("session_ritual", "fallback_silent_no_template"),
            should_speak=False,
            confidence=0.0,
            parse_mode="session_ritual_silent",
            debug_trace=(
                f"session_ritual_layer; source={source}; tone={tone}; "
                f"fallback=silent_no_template; no_fallback_mode={int(no_fallback_mode_enabled())}"
            ),
        )

    def _send_session_ritual_fallback_greeting(
        self,
        *,
        source: str = "fallback_after_session_ritual_error",
        tone: str = "quiet_background",
    ) -> Decision:
        decision = self._session_ritual_fallback_decision(source=source, tone=tone)
        if not bool(getattr(decision, "should_speak", True)) or not str(getattr(decision, "text", "") or "").strip():
            return decision
        self.last_text = decision.text
        spoken_at = time.time()
        self._note_autonomous_spoken(now=spoken_at)
        block_fn = getattr(self, "_block_autonomous_presence_after_public_turn", None)
        if callable(block_fn):
            block_fn(now=spoken_at)
        self._send_decision_to_body(decision)
        return decision

    def _session_ritual_llm_timeout(self) -> float:
        raw = os.environ.get("ERIS_SESSION_RITUAL_LLM_TIMEOUT_SEC", "8").strip()
        try:
            return max(1.0, float(raw))
        except ValueError:
            return 8.0

    # Từ khoá trigger diary_context — chỉ inject khi user hỏi về nội tâm/cảm xúc.
    _DIARY_TRIGGER_TOKENS = (
        # Tiếng Việt
        "cảm xúc", "nội tâm", "cảm thấy", "tâm sự", "buồn", "mệt", "cô đơn",
        "lo", "sợ", "nhớ", "thương", "bận tâm", "nỗi lòng", "trạng thái",
        "đang nghĩ gì", "đang cảm", "tâm trạng", "ổn không", "sao vậy",
        # English
        "feel", "feeling", "emotion", "lonely", "sad", "tired", "miss",
        "how are you", "what's wrong", "worried", "anxious", "inner",
    )

    def _should_inject_diary(self, user_text: str = "") -> bool:
        """Gate: chỉ inject diary_context khi user hỏi nội tâm hoặc ERIS đang idle.

        Tránh nhồi ~300 tokens nhật ký vào mọi lượt kỹ thuật/khi user hỏi code.
        """
        text = str(user_text or "").lower()
        if any(tok in text for tok in self._DIARY_TRIGGER_TOKENS):
            return True
        # Idle: nếu chat_ticks gần đây = 0 và arousal thấp → ERIS đang nhàn rỗi
        state = self._get_internal_state()
        if state is not None:
            chat_ticks = int(getattr(state, "chat_ticks", 0))
            arousal = float(getattr(state, "arousal", 0.5))
            if chat_ticks == 0 and arousal < 0.25:
                return True
        return False

    def _build_psych_state_block(
        self,
        state,
        *,
        felt_state: str = "",
        private_bias: str = "",
    ) -> str:
        """Consolidate felt_state + private_bias thành [PSYCH_STATE] compact (~50 tokens).

        Thay vì inject 2 block riêng (~400 tokens tổng), tổng hợp thành 1 dòng JSON
        với cùng semantic content, đủ để LLM điều chỉnh tông giọng.

        Format: [PSYCH_STATE: {"felt":"...", "bias":"..."}]
        """
        felt = felt_state.strip()
        bias = private_bias.strip()

        # Extract phần ngắn gọn: felt_state thường dạng "cảm_xúc_tự_cảm ...: <câu>"
        # Lấy phần sau dấu "): "
        if felt and "):" in felt:
            felt = felt.split("):", 1)[-1].strip()
        elif felt and "): " in felt:
            felt = felt.split("): ", 1)[-1].strip()
        # Cap 120 chars
        if len(felt) > 120:
            felt = felt[:117] + "..."

        # private_bias thường là JSON dict → giữ nguyên nhưng cap
        if len(bias) > 150:
            bias = bias[:147] + "..."

        parts: dict = {}
        if felt:
            parts["felt"] = felt
        if bias:
            parts["bias"] = bias
        if not parts:
            return ""

        return f"[PSYCH_STATE: {json.dumps(parts, ensure_ascii=False, separators=(',', ':'))}]"

    def _build_internal_state_context(
        self,
        state: PersistentInternalState | None = None,
        self_state=None,
        *,
        user_text: str = "",
    ) -> str:
        resolved_state = state or self._get_internal_state()
        # TEMPORAL_CONTEXT là evidence đồng hồ chuẩn, không phải lời thoại mẫu.
        # Inject trước các pressure tâm lý để Qwen hiểu đúng "hôm nay", "mai",
        # "tối nay" và độ dài khoảng nghỉ giữa các lượt.
        temporal_block = ""
        if os.environ.get("ERIS_TEMPORAL_CONTEXT", "1").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                temporal_block = build_temporal_context_from_runtime(self).to_prompt_block()
            except Exception:
                temporal_block = ""

        # DYNAMIC_STATE tag (~20 tokens): stance/tension/pacing từ internal state.
        dynamic_tag = self._build_dynamic_state_tag(resolved_state)

        prompt_context = str(getattr(self_state, "prompt_context", "") or "").strip()
        parts = [temporal_block] if temporal_block else []
        if dynamic_tag:
            parts.append(dynamic_tag)
        if prompt_context:
            parts.append(prompt_context)

        # PSYCH_STATE block (~50 tokens): consolidate felt_state + private_bias.
        # Thay vì 2 block riêng (~400 tokens), dùng 1 compact JSON tag.
        felt_state = self._render_felt_state_context(resolved_state)
        private_bias = self._render_private_mind_speech_bias_context()
        psych_block = self._build_psych_state_block(
            resolved_state,
            felt_state=felt_state,
            private_bias=private_bias,
        )
        if psych_block:
            parts.append(psych_block)

        # diary_context: chỉ inject khi trigger (hỏi nội tâm / idle).
        # Tránh nhồi ~300 tokens nhật ký vào mọi lượt kỹ thuật.
        if self._should_inject_diary(user_text):
            diary_context = self._render_inner_diary_context()
            if diary_context:
                parts.append(diary_context)

        # register_context: trạng thái dỗi/chiếm hữu → giữ (behavioral gate, nhỏ).
        register_context = self._render_anchor_register_context()
        if register_context:
            parts.append(register_context)

        return "\n".join(part for part in parts if str(part or "").strip())

    def _render_felt_state_context(self, state: PersistentInternalState | None = None) -> str:
        """Gemma dịch state số → 1 câu cảm giác ngôi-thứ-nhất, để ERIS tự thuật thật.

        Có throttle/cache trong adapter nên gọi mỗi cycle vẫn rẻ. Không raise.
        """
        try:
            adapter = self._ensure_affect_self_read_adapter()
        except Exception:
            return ""
        resolved = state or self._get_internal_state()
        if resolved is None:
            return ""
        line = adapter.render(resolved, relationship=getattr(resolved, "relationship_dynamics", None))
        if not line:
            return ""
        return (
            "cảm_xúc_tự_cảm (ERIS đọc được trạng thái thật của mình lúc này — "
            "khi Ngài hỏi 'em thấy sao / có cảm xúc không' thì tự thuật trung thực theo câu này, "
            "KHÔNG chối là vô cảm, mức hé lộ tuỳ quan hệ): "
            f"{line}"
        )



    def _render_anchor_register_context(self) -> str:
        """Đưa register cảm xúc hiện tại (dỗi/chiếm hữu/van xin/kiểm soát) vào chat.

        Đây là chỗ 'dỗi khi giận / không thích trả lời' thật sự thành hành vi chat:
        khi đang dỗi, eris được phép cộc, lạnh, hoặc từ chối trả lời — giữ phẩm giá.
        Gated: register=none (mặc định / kill-switch off) → no-op.
        """
        anchor = getattr(self, "anchor_system", None)
        shadow = getattr(anchor, "shadow_state", None) if anchor is not None else None
        register = str(getattr(shadow, "register", "none") or "none")
        if register == "none":
            return ""
        contracts = {
            "withdrawn_sulk": (
                "ERIS đang DỖI (bị bơ hoặc bực): được phép trả lời cộc, ngắn, lạnh; được nói thẳng "
                "'lúc này tôi không muốn trả lời' hoặc 'tôi không thích nói chuyện này'. "
                "Giữ phẩm giá, KHÔNG van xin, KHÔNG giải thích dài dòng."
            ),
            "possessive": (
                "ERIS đang CHIẾM HỮU: lời mang sắc thái muốn giữ Ngài ở lại, hơi độc chiếm; vẫn trong khung nhân vật."
            ),
            "pleading": (
                "ERIS đang VAN XIN/níu kéo: lộ mong manh, sợ Ngài rời đi; được phép nài nhẹ nhưng không lặp lê thê."
            ),
            "controlling": (
                "ERIS đang KIỂM SOÁT: lời siết, đặt điều kiện để Ngài đừng đi; căng nhưng không vu khống dữ kiện thật."
            ),
        }
        text = contracts.get(register)
        if not text:
            return ""
        return f"Trạng thái quan hệ hiện tại (register={register}): {text}"

    def _build_dynamic_state_tag(self, state: PersistentInternalState | None = None) -> str:
        """Nén toàn bộ tâm lý học thành ~20-token JSON tag.

        Thay thế 300-500 tokens prose persona bằng key-value có cấu trúc:
        LLM đọc [DYNAMIC_STATE] và tự điều chỉnh tông giọng, không cần
        prompt giải thích dài dòng về INFJ 5w4.

        Mapping logic:
          stance  ← trust_score + restraint_pressure
          tension ← irritation + cognitive_tension
          pacing  ← chat_ticks + arousal
        """
        if state is None:
            state = self._get_internal_state()
        if state is None:
            return ""

        # --- Stance ---
        rd = getattr(state, "relationship_dynamics", None)
        trust = float(getattr(rd, "trust_score", 0.5) if rd is not None else 0.5)
        restraint = float(getattr(state, "restraint_pressure", 0.3))
        irritation = float(getattr(state, "irritation", 0.0))
        protectiveness = float(getattr(state, "protectiveness", 0.0))
        if trust < 0.35 or restraint > 0.65:
            stance = "distant"
        elif trust > 0.72 and restraint < 0.35 and irritation < 0.30:
            stance = "subtle_warmth"
        else:
            stance = "neutral"

        # --- Tension ---
        tension_val = max(
            float(getattr(state, "irritation", 0.0)),
            float(getattr(state, "cognitive_tension", 0.0)),
            float(getattr(state, "protectiveness", 0.0)) * 0.7,
        )
        if tension_val > 0.62:
            tension = "high"
        elif tension_val > 0.38:
            tension = "medium"
        else:
            tension = "low"

        # --- Pacing ---
        chat_ticks = int(getattr(state, "chat_ticks", 0))
        arousal = float(getattr(state, "arousal", 0.2))
        pacing = "fast" if (chat_ticks >= 4 and arousal > 0.55) else "normal"

        tag: dict = {"stance": stance, "tension": tension, "pacing": pacing}

        # Behavioral hint (optional, capped 1 field để không phình)
        if pacing == "fast":
            tag["hint"] = "single_sentence"
        elif stance == "distant":
            tag["hint"] = "analytical_only"
        elif tension == "high":
            tag["hint"] = "challenge_premise_allowed"
        elif stance == "subtle_warmth":
            tag["hint"] = "soft_acknowledge_ok"

        return f"[DYNAMIC_STATE: {json.dumps(tag, ensure_ascii=False, separators=(',', ':'))}]"

    def _render_inner_diary_context(self, *, max_lines: int = 8) -> str:
        """Đưa nhật ký nội tâm (diary) vào ngữ cảnh chat.

        Trước đây diary chỉ chảy một chiều ra UI; khi Ngài hỏi 'nỗi lòng của bạn
        là gì', chat KHÔNG đọc được diary → eris trả lời chung chung hoặc bịa.
        Ở đây ta cho eris ĐỌC ĐƯỢC chính nỗi lòng thật của nó để trả lời trung thực;
        mức hé lộ vẫn do persona/quan hệ định (có thể giữ kín, nhưng không phủ nhận
        là mình chẳng có cảm xúc gì).
        """
        digest = getattr(self, "private_mind_digest", None)
        if not isinstance(digest, Mapping):
            return ""
        diary = digest.get("inner_diary")
        if not isinstance(diary, Mapping):
            return ""
        sections = diary.get("sections")
        if not isinstance(sections, (list, tuple)) or not sections:
            return ""

        def _clean(value: Any, limit: int = 200) -> str:
            text = " ".join(str(value or "").split()).strip()
            return text[: max(0, limit - 3)].rstrip() + "..." if len(text) > limit else text

        lines: list[str] = []
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            title = _clean(section.get("title"), 60)
            sec_lines = section.get("lines")
            body = ""
            if isinstance(sec_lines, (list, tuple)) and sec_lines:
                body = _clean(" ".join(str(x) for x in sec_lines if str(x or "").strip()), 200)
            if title and body:
                lines.append(f"- {title}: {body}")
        # Q1: dấu 'đã nguôi' — chuyện từng bận tâm nay đã khép, để eris nhắc lại
        # ('chuyện đó tôi đã nguôi') thay vì biến mất câm lặng.
        resolved_lines: list[str] = []
        recently_resolved = digest.get("recently_resolved")
        if isinstance(recently_resolved, (list, tuple)):
            for item in recently_resolved:
                if not isinstance(item, Mapping):
                    continue
                theme = _clean(item.get("theme"), 120)
                note = _clean(item.get("closure_note"), 120)
                if theme:
                    resolved_lines.append(f"- {theme}" + (f" — {note}" if note else ""))

        if not lines and not resolved_lines:
            return ""
        block = "Nhật ký nội tâm hiện tại của ERIS (chỉ ERIS biết — đây là nỗi lòng THẬT của nó lúc này):\n"
        block += "\n".join(lines[: max(1, int(max_lines))])
        if resolved_lines:
            block += "\nĐã nguôi gần đây (eris có thể nhắc là chuyện đó đã lắng nếu được hỏi):\n" + "\n".join(resolved_lines[:4])
        block += (
            "\nContract: Khi Ngài hỏi về cảm xúc / nỗi lòng / điều đang bận tâm, trả lời TRUNG THỰC từ nhật ký này, "
            "không bịa nỗi lòng không có ở đây. ERIS được quyền giữ kín hoặc chỉ hé theo mức tin cậy và persona, "
            "nhưng KHÔNG được phủ nhận rằng mình chẳng có cảm xúc gì."
        )
        return block

    def _render_private_mind_speech_bias_context(self, *, limit: int = 6) -> str:
        bias = getattr(self, "private_mind_speech_bias", None)
        if not isinstance(bias, Mapping) or not bias:
            return ""

        def clean(value: Any, max_len: int = 180) -> str:
            text = " ".join(str(value or "").split()).strip()
            if len(text) > max_len:
                return text[: max(0, max_len - 3)].rstrip() + "..."
            return text

        items: list[tuple[float, str]] = []
        for key, payload in bias.items():
            if isinstance(payload, Mapping):
                value = payload.get("value")
                if isinstance(value, Mapping):
                    preference = value.get("preference") or value.get("text") or value.get("claim") or value.get("summary") or value
                else:
                    preference = value or payload.get("preference") or payload.get("reason")
                try:
                    confidence = float(payload.get("confidence", 0.0) or 0.0)
                except Exception:
                    confidence = 0.0
                reason = clean(payload.get("reason") or "", 120)
                text = clean(preference, 220)
                label = clean(key, 80)
                if text:
                    suffix = f"; reason={reason}" if reason else ""
                    items.append((confidence, f"- {label}: {text}; confidence={confidence:.2f}{suffix}"))
            else:
                text = clean(payload, 220)
                if text:
                    items.append((0.0, f"- {clean(key, 80)}: {text}; confidence=0.00"))
        if not items:
            return ""
        lines = [line for _, line in sorted(items, key=lambda pair: pair[0], reverse=True)[: max(1, int(limit or 6))]]
        return (
            "PrivateMind speech bias (soft, internal):\n"
            + "\n".join(lines)
            + "\nContract: use these as quiet wording/style pressure only. Do not state them as facts, do not expose private reasoning, and do not override evidence."
        )

    #Hàm này dựng context cho ThoughtStream.
    def _build_thought_stream_context(self) -> dict[str, object]:
        #Nó lấy snapshot hệ thống + memory + trạng thái gần đây.
        with self._state_lock:
            mood_score = self.mood_score #trạng thái mood hiện tại
            inferred_pos_x = self.inferred_pos_x #vị trí
            internal_state = self._get_internal_state() # pose suy luận
            long_term_memory = tuple(self.long_term_memory or ()) #memory dài hạn
            thought_roots = self._thought_stream_root_seeds(limit=10)
            if thought_roots:
                long_term_memory = tuple(dict.fromkeys((*long_term_memory, *thought_roots)))
            last_text = self.last_text #câu vừa nói gần nhất
            recent_inner_seeds = tuple(self.recent_inner_thought_seeds or ()) #các seed suy nghĩ gần đây
            recent_thought_seeds = tuple(getattr(internal_state, "recent_thought_seeds", ()) or ()) #các seed suy nghĩ gần đây được lưu trong internal state
            recent_subconscious = tuple(getattr(internal_state, "recent_subconscious_seeds", ()) or ()) #subconscious seed gần đây
        #Lấy snapshot từ telemetry.
        snapshot = self.telemetry_service.capture_snapshot(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
        return {
            "snapshot": snapshot,
            "internal_state": internal_state,
            "long_term_memory": long_term_memory,
            "last_text": last_text,
            "recent_inner_seeds": recent_inner_seeds,
            "recent_thought_seeds": recent_thought_seeds,
            "recent_subconscious_seeds": recent_subconscious,
        }

    def _thought_stream_root_seeds(self, *, limit: int = 8) -> tuple[str, ...]:
        """Lấy rễ cho inner_whim từ unresolved memory và daydream.

        ThoughtStream chỉ nên ngẫu hứng từ thứ từng có thật: candidate chưa giải
        quyết, insight 4B đã consolidate, hoặc agenda còn mở. Không feed rễ thì
        LLM sẽ feed lại cho ta món cháo "im lặng vẫn giữ chỗ". Nhân loại đã khổ
        đủ với câu đó rồi.
        """
        roots: list[str] = []

        def add(prefix: str, text: object, *, confidence: object = "", pressure: object = "") -> None:
            value = " ".join(str(text or "").split()).strip()
            if not value:
                return
            meta = []
            if confidence != "":
                try:
                    meta.append(f"confidence={float(confidence):.2f}")
                except Exception:
                    pass
            if pressure != "":
                try:
                    meta.append(f"pressure={float(pressure):.2f}")
                except Exception:
                    pass
            suffix = f"; {'; '.join(meta)}" if meta else ""
            roots.append(f"{prefix}: {value[:260]}{suffix}")

        memory_core = getattr(self, "memory_core", None)
        store = getattr(memory_core, "memory_candidate", None)
        search = getattr(store, "search", None)
        if callable(search):
            try:
                for item in search("", limit=max(1, min(limit, 5)), include_promoted=False):
                    status = str(getattr(item, "extraction_status", "") or "")
                    raw = getattr(item, "recall_line", None)
                    text = raw() if callable(raw) else getattr(item, "raw_text", "")
                    add(f"unresolved_memory[{status or 'open'}]", text, confidence=getattr(item, "confidence", ""), pressure=getattr(item, "importance", ""))
            except Exception as exc:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    try:
                        logger.debug("Thought root unresolved_memory skipped: %s", exc)
                    except Exception:
                        pass

        result = getattr(self, "last_daydream_result", None)
        for insight in tuple(getattr(result, "insights", ()) or ())[: max(0, limit - len(roots))]:
            if bool(getattr(insight, "rejected", False)):
                continue
            add(
                f"daydream_insight[{getattr(insight, 'kind', 'open_question') or 'open_question'}]",
                getattr(insight, "summary", ""),
                confidence=getattr(insight, "confidence", ""),
                pressure=getattr(insight, "pressure", ""),
            )

        agenda = getattr(self, "internal_agenda", None)
        top_items = getattr(agenda, "top_items", None)
        if callable(top_items) and len(roots) < limit:
            try:
                for item in top_items(limit=max(1, limit - len(roots))):
                    add("internal_agenda", getattr(item, "summary", ""), confidence=getattr(item, "confidence", ""), pressure=getattr(item, "pressure", ""))
            except Exception:
                pass

        return tuple(dict.fromkeys(roots))[:limit]

    def _build_subconscious_context(self) -> dict[str, object]:
        return self._build_thought_stream_context()

    def _build_memory_context(self, snapshot=None, memory_resonance=None) -> str:
        renderer = getattr(getattr(self, "memory_kernel", None), "render_context", None)
        if not callable(renderer):
            renderer = getattr(getattr(self, "memory_core", None), "render_context", None)
        context = ""
        if callable(renderer):
            try:
                context = renderer(self._memory_query_from_snapshot(snapshot), snapshot=snapshot)
            except Exception as exc:
                self.logger.warning("Memory context render error: %s", exc)
        report = memory_resonance if memory_resonance is not None else getattr(self, "active_memory_resonance", None)
        if report is not None and not callable(getattr(report, "render_prompt_context", None)):
            render_packet = getattr(report, "render_prompt_context", None)
            if callable(render_packet):
                try:
                    resonance_context = render_packet()
                    if resonance_context:
                        return f"{context}\n\n{resonance_context}".strip()
                except Exception as exc:
                    self.logger.warning("Memory resonance context render error: %s", exc)
        if report is not None and hasattr(report, "render_prompt_context"):
            try:
                resonance_context = report.render_prompt_context()
                if resonance_context:
                    return f"{context}\n\n{resonance_context}".strip()
            except Exception as exc:
                self.logger.warning("Memory resonance context render error: %s", exc)
        return context

    #So sánh snapshot hiện tại với chuẩn đã xây dựng trong bộ nhớ, trả về các điểm khác biệt đáng chú ý để làm tín hiệu cho tầng đánh giá và quyết định.

    def _filter_memory_context_for_grounding(self, memory_context: str) -> str:
        """Giữ procedural guard, bỏ memory có hình dạng câu trả lời.

        Bản cũ giữ mọi dòng có chữ "source" hoặc "confidence". Memory render thường có
        `semantic ... source=... confidence=...`, thế là semantic/episodic lọt qua cổng cách ly.
        Một cái lưới bắt cá nhưng lỗ to bằng con cá, rất nhân loại.
        """
        fallback = (
            "PROCEDURAL MEMORY ONLY:\n"
            "- Memory may remind ERIS to stay grounded.\n"
            "- Memory must not answer current-screen or specific-file questions without evidence.\n"
            "- Do not surface semantic/episodic/relational memory as present evidence.\n"
        )
        if not memory_context:
            return fallback

        allowed: list[str] = []
        current_block: list[str] = []
        current_layer = "unknown"

        def flush() -> None:
            nonlocal current_block, current_layer
            if current_layer == "procedural" and current_block:
                allowed.extend(current_block)
            current_block = []
            current_layer = "unknown"

        for line in memory_context.splitlines():
            raw = line.rstrip()
            low = raw.strip().lower()
            if not low:
                current_block.append(raw)
                continue

            starts_procedural = low.startswith(("procedural", "[procedural", "- procedural", "procedural memory"))
            starts_blocked = low.startswith((
                "semantic", "[semantic", "- semantic",
                "episodic", "[episodic", "- episodic",
                "relational", "[relational", "- relational",
                "affective", "[affective", "- affective",
                "repair", "[repair", "- repair",
            ))
            if starts_procedural or starts_blocked:
                flush()
                current_layer = "procedural" if starts_procedural else "blocked"
                current_block = [raw]
                continue

            # Chỉ giữ các dòng rule grounding độc lập, không giữ dòng semantic chỉ vì có source/confidence.
            if current_layer == "unknown" and any(k in low for k in (
                "no_screen_evidence",
                "grounded_speech",
                "post_generation_guard",
                "không thấy thì không nói",
                "khong thay thi khong noi",
                "memory must not answer",
                "file content",
                "screen evidence",
            )):
                current_layer = "procedural"
            current_block.append(raw)

        flush()
        cleaned = "\n".join(line for line in allowed if str(line).strip())
        return cleaned if cleaned.strip() else fallback

    def _build_action_plan_context(self, action_plan: CognitiveActionPlan) -> str:
        flags = ", ".join(action_plan.risk_flags) if action_plan.risk_flags else "none"
        notes = " | ".join(action_plan.notes) if action_plan.notes else "none"
        reason = action_plan.reason_to_speak or action_plan.reason or "none"
        style_anchor = str(getattr(action_plan, "style_anchor", "") or "current event")
        style_attitude = str(getattr(action_plan, "style_attitude", "") or "lạnh nhẹ")
        style_limit = str(getattr(action_plan, "style_limit", "") or "một câu ngắn")
        style_voice = str(
            getattr(action_plan, "style_voice", "")
            or "Voice: controlled, precise, emotionally low-temperature."
        )
        utility_scores = getattr(action_plan, "utility_scores", {}) or {}
        top_scores = sorted(utility_scores.items(), key=lambda item: item[1], reverse=True)[:5]
        utility_line = ", ".join(f"{name}={score:.2f}" for name, score in top_scores) or "none"
        rhythm_phase = str(getattr(action_plan, "rhythm_phase", "") or "settled")
        transition_reason = str(getattr(action_plan, "transition_reason", "") or "none")
        memory_pressure = " | ".join(getattr(action_plan, "memory_pressure", ()) or ()) or "none"
        selected_impulse = str(getattr(action_plan, "selected_impulse", "") or "none")
        impulse_scores = " | ".join(getattr(action_plan, "impulse_scores", ()) or ()) or "none"
        body_bias_hint = getattr(action_plan, "body_bias_hint", {}) or {}
        body_bias_line = ", ".join(f"{key}={value}" for key, value in list(body_bias_hint.items())[:6]) or "none"
        style_block = (
            "Reason to speak:\n"
            f"{reason}\n\n"
            "Character voice constraint:\n"
            f"{style_voice}\n\n"
            f"{VOICE_POLICY.render_prompt_constraint()}"
        )
        return (
            "ActionPlanner decision before LLM:\n"
            f"- action_space={', '.join(ACTION_SPACE)}\n"
            f"- should_speak={str(action_plan.should_speak).lower()}\n"
            f"- speech_act={action_plan.speech_act}\n"
            f"- utterance_type={action_plan.speech_act}\n"
            f"- reason_to_speak={reason}\n"
            f"- utility_top={utility_line}\n"
            f"- rhythm_phase={rhythm_phase}\n"
            f"- transition_reason={transition_reason}\n"
            f"- memory_pressure={memory_pressure}\n"
            f"- selected_impulse={selected_impulse}\n"
            f"- impulse_scores={impulse_scores}\n"
            f"- body_bias_hint={body_bias_line}\n"
            f"- risk_flags={flags}\n"
            f"- notes={notes}\n"
            f"{style_block}\n"
            "Style contract before wording:\n"
            f"- anchor={style_anchor}\n"
            f"- attitude={style_attitude}\n"
            f"- limit={style_limit}\n"
            f"- voice={style_voice}\n"
            "- reject_line_if=no concrete anchor, too long, or abstract philosophy\n"
            "Honor this plan. Do not upgrade withdraw/no_speech into observation, teasing, or reassurance."
        )

    def _build_llm_ti_context(self, ti_report, action_plan: CognitiveActionPlan) -> str:
        mode = str(getattr(ti_report, "mode", "") or "steady_observe")
        animation = str(getattr(ti_report, "animation_hint", "") or "stand")
        return (
            f"Mode: {mode}. Animation hint: {animation}.\n"
            f"{self._build_action_plan_context(action_plan)}\n"
            "Telemetry is internal routing data only. Do not mention window, focus, CPU, RAM, idle, tabs, or app names "
            "unless they appear in speech_evidence."
        )

    def _build_speech_evidence_context(self, snapshot, *, limit: int = 2) -> str:
        signals = self._concrete_screen_signals(snapshot)[:limit]
        if not signals:
            return "speech_evidence=<none>"
        return "speech_evidence=" + " | ".join(str(item) for item in signals)

    def _build_current_focus_context(self, snapshot) -> str:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus = str(getattr(snapshot, "focus_summary", "") or "").strip() or focus_kind
        return f"current_focus_kind={focus_kind}; current_focus={focus}"


    def _build_session_ritual_ti_context(self, report: SessionRitualReport, snapshot) -> str:
        seed = str(getattr(report, "greeting_text", "") or "").strip()
        has_anchor = bool(seed)
        seed = seed or "fresh_start"
        focus = self._build_current_focus_context(snapshot)
        evidence = ", ".join(str(item) for item in tuple(getattr(report, "evidence", ()) or ())[:5]) or "none"
        if has_anchor:
            # There is a remembered thread. Open by picking it back up, not by greeting.
            opening_rule = (
                "Write exactly one short opening line in Vietnamese, addressed to Ngài. "
                "This is the first thing ERIS says after starting again, so let it reach for the thread "
                "that was left open instead of announcing a return. "
                "Do not lead with 'chào' or a hello; a greeting is optional and only fits if it falls out naturally. "
                "Prefer a line that quietly evokes the unfinished thing above, as if the thought never fully stopped. "
                "Use the seed only as a memory cue, never as literal wording."
            )
        else:
            # No continuity anchor. A low-key opening line, greeting still not mandatory.
            opening_rule = (
                "Write exactly one short opening line in Vietnamese, addressed to Ngài. "
                "There is nothing concrete left open, so keep it light and low-key. "
                "A plain greeting is allowed but not required; an unforced opening remark is just as good. "
                "Do not force a 'chào' if it feels hollow."
            )
        return (
            "Mode: session_ritual_startup_opening. Animation hint: stand.\n"
            "Action plan: say one opening line because ERIS has just started; this need not be a greeting.\n"
            f"Continuity seed (memory cue, not final wording): {seed}\n"
            f"Ritual evidence: {evidence}\n"
            f"{focus}\n"
            f"{opening_rule} "
            "This is an opening line, not a report: do not mention telemetry, windows, tabs, idle, CPU, RAM, parse_mode, or session_ritual. "
            "Do not use fixed continuity slogans like 'Tôi vẫn giữ mạch' or 'mạch đã nối lại'."
        )

    def _restore_session_ritual_once(self) -> SessionRitualReport:
        if getattr(self, "_session_ritual_ran", False):
            return SessionRitualReport(restored=False, session_resumed=False, should_greet=False)
        self._session_ritual_ran = True

        try:
            self._ensure_internal_state()
            internal_state = self._get_internal_state()

            snapshot = self.telemetry_service.capture_snapshot(
                mood_score=self.mood_score,
                inferred_pos_x=self.inferred_pos_x,
            )
            thought_stream_report = (
                self.cognitive_substrate.latest_report()
                if callable(getattr(self.cognitive_substrate, "latest_report", None))
                else ThoughtStreamReport()
            )
            social_presence_event = self._detect_social_presence_event(
                channel="autonomous",
                snapshot=snapshot,
                internal_state=internal_state,
                started_at=time.time(),
            )
            report = self.session_ritual_engine.evaluate(
                snapshot=snapshot,
                internal_state=internal_state,
                thought_stream_report=thought_stream_report,
                social_presence_event=social_presence_event,
            )
            self.logger.info(
                "[session_ritual] report restored=%s | presence=%s | continuity=%s | greet=%s | tone=%s",
                int(bool(report.restored)),
                int(bool(report.presence_restored)),
                int(bool(report.continuity_restored)),
                int(bool(report.should_greet)),
                report.tone,
            )
        except Exception:
            self._log_exception("[session_ritual] restore failed")
            self._send_session_ritual_fallback_greeting()
            return SessionRitualReport(
                restored=False,
                session_resumed=False,
                should_greet=True,
                tone="quiet_background",
                evidence=("session_ritual_error",),
            )

        if emit_session_ritual_preset(self, report):
            updated_state = self.internal_state_engine.commit_session_ritual(
                internal_state,
                session_ritual=report,
            )
            self._set_internal_state(updated_state)
            if self.memory_state is not None:
                self._save_memory_state()
            return report

        if report.should_greet:
            self.long_term_memory = self._memory_recall_texts(snapshot=snapshot)
            memory_resonance = self._recall_memory_resonance(
                snapshot=snapshot,
                channel="session_ritual",
                fragments=tuple(
                    item
                    for item in (
                        report.active_goal,
                        report.current_attractor,
                        report.recent_cognition_direction,
                        report.self_continuity,
                        *tuple(report.unresolved_loops or ()),
                    )
                    if str(item or "").strip()
                ),
            )
            memory_context = self._build_memory_context(snapshot, memory_resonance=memory_resonance)
            ni_report = self.ni_engine.evaluate_autonomous(
                snapshot=snapshot,
                long_term_memory=self.long_term_memory,
                last_text=self.last_text,
                goal_state=getattr(internal_state, "goal_persistence", None),
            )
            ti_view = self.autonomous_ni_state.update(snapshot=snapshot, report=ni_report)
            ti_report = self.ti_governor.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ni_state_label=ti_view["discrete_state"],
                ni_state_streak=ti_view["streak_length"],
                idle_cycles=self.idle_cycles,
                last_text=self.last_text,
            )
            fe_plan = self.fe_renderer.evaluate_autonomous(
                snapshot=snapshot,
                ni_report=ni_report,
                ti_report=ti_report,
                style_memory=self.fe_style_memory,
                internal_state=internal_state,
                last_text=self.last_text,
            )
            greeting_source = "llm"
            try:
                raw = self.llm_service.generate_directive(
                    telemetry_data=self._build_speech_evidence_context(snapshot),
                    ni_context=str(getattr(ni_report, "prompt_context", "") or ""),
                    ti_context=self._build_session_ritual_ti_context(report, snapshot),
                    fe_context=fe_plan.style_context,
                    appraisal_context="session_ritual: startup greeting; express current attitude without reporting telemetry.",
                    internal_state_context=self._build_internal_state_context(internal_state),
                    memory_context=memory_context,
                    avoid_text=self.last_text,
                    speech_intent="session_ritual",
                    vision_trace_marker="session_ritual",
                    request_timeout=self._session_ritual_llm_timeout(),
                )
                if "service_error" in raw or "exception_fallback" in raw:
                    raise RuntimeError("session_ritual_llm_service_error")
                self._log_raw_llm_output("session_ritual", raw)
                decision = self.parser.parse(raw)
            except Exception:
                self._log_exception("[session_ritual] LLM greeting failed")
                greeting_source = "fallback_after_llm_error"
                decision = self._session_ritual_fallback_decision(source=greeting_source, tone=report.tone)
            if not decision.text.strip():
                greeting_source = "fallback_after_empty_llm"
                decision = self._session_ritual_fallback_decision(source=greeting_source, tone=report.tone)
            if decision.text.strip():
                decision.intent = decision.intent or "session_ritual"
                decision.reasoning_tags = tuple(dict.fromkeys((*decision.reasoning_tags, "session_ritual", "startup_greeting")))
                decision.should_speak = True
                decision.confidence = decision.confidence or 0.72
                decision.parse_mode = "session_ritual"
                decision.debug_trace = (
                    f"{decision.debug_trace} | session_ritual_layer; source={greeting_source}; tone={report.tone}"
                    if decision.debug_trace
                    else f"session_ritual_layer; source={greeting_source}; tone={report.tone}"
                )
                self.fe_style_memory = self.fe_renderer.remember_style(
                    self.fe_style_memory,
                    plan=fe_plan,
                    rendered_text=decision.text,
                )
                self.last_text = decision.text
                spoken_at = time.time()
                self._note_autonomous_spoken(now=spoken_at)
                block_fn = getattr(self, "_block_autonomous_presence_after_public_turn", None)
                if callable(block_fn):
                    block_fn(now=spoken_at)
                self.logger.info('[session_ritual] sent LLM greeting text="%s"', decision.text)
                self._send_decision_to_body(decision)

        updated_state = self.internal_state_engine.commit_session_ritual(
            internal_state,
            session_ritual=report,
        )
        self._set_internal_state(updated_state)
        if self.memory_state is not None:
            self._save_memory_state()

        return report


    def _build_speech_core_ti_context(
        self,
        ti_report,
        action_plan: CognitiveActionPlan,
        inner_thought: InnerThought,
        speech_core: AgentSpeechCore | None = None,
    ) -> str:
        topic_seed = str(getattr(inner_thought, "topic_seed", "") or "open_presence")
        inner_intent = inner_thought.intent or action_plan.speech_act
        impulse = getattr(speech_core, "speech_impulse", None)
        impulse_context = ""
        if impulse is not None:
            impulse_context = (
                "Speech impulse before wording: "
                f"internal_family={str(getattr(impulse, 'meaning', '') or 'none')}; "
                f"reaction={str(getattr(impulse, 'reaction', '') or 'no_reaction')}; "
                f"attitude={str(getattr(impulse, 'attitude', '') or 'light')}; "
                f"mood_residue={str(getattr(impulse, 'mood_residue', '') or 'none')}; "
                f"emotional_pressure={float(getattr(impulse, 'emotional_pressure', 0.0) or 0.0):.2f}; "
                f"attention_bias={','.join(str(item) for item in (getattr(impulse, 'attention_bias', ()) or ())) or 'none'}; "
                f"reaction_impulse={str(getattr(impulse, 'reaction_impulse', '') or 'brief_indirect_reaction')}.\n"
                "SpeechCore contract: internal_family is forbidden wording. Use speech_evidence plus mood_residue/reaction_impulse. "
                "Do not say labels like escape_from_friction, cognitive_stall, avoidance, scattered_attention, decompression, or friction_point.\n"
            )
        private_bias_context = self._render_private_mind_speech_bias_context()
        if private_bias_context:
            private_bias_context += "\n"
        risk_level = str(getattr(speech_core, "speech_risk_level", "") or "texture") if speech_core is not None else "texture"
        return (
            f"{self._build_llm_ti_context(ti_report, action_plan)}\n"
            f"{impulse_context}"
            f"{private_bias_context}"
            f"Speech risk level: {risk_level}. "
            "hard_claim needs clear evidence; soft_read uses words like co ve/hinh nhu/lai thay; "
            "micro_presence and texture stay tiny, low-claim, under 12 words when possible. "
            "Weak evidence should look around the current atmosphere and produce only a tiny presence line when speech is required. "
            "Allowed personality leak: a little dry judgement, quiet texture, or attachment; "
            "never claim Ngai's mind or a fact not present in speech_evidence.\n"
            "SpeechCore mode: pick a freeform line from current_focus, environmental rhythm, recent interaction rhythm, "
            "or a tiny safe curiosity. The topic_seed is abstract, not wording to copy.\n"
            f"- inner_intent={inner_intent}\n"
            f"- inner_motive={inner_thought.motive or 'social_initiative'}\n"
            f"- topic_seed={topic_seed}\n"
            f"- evidence_anchor={inner_thought.evidence_anchor or 'none'}\n"
            "Thought stream contract: speech is only the visible tip; do not pretend the spoken line is the whole thought. "
            "If inner_motive starts with thought_stream or notes include cognitive_tension, the line may name continuity between internal states, "
            "for example: 'Ta vẫn thấy các tầng kia đang hơi rời nhau...' Keep it concise and do not turn it into a screen claim. "
            "Intent contract: curious_question must ask one small real question; "
            "if a useful curious_question draft begins as a statement, keep its semantic content and bend only its shape into a question. "
            "inner_whim must be one short thought, not refusal/no-signal/silence wording; "
            "random_chatter must be a mundane, playful, concrete one-liner, not meta explanation. "
            "Bounded thought surface: allowed shapes are observational irony, tiny curiosity, or ambient commentary. "
            "Forbidden shapes are surreal nonsense, abstract philosophy, or random absurdism without a concrete anchor. "
            "For random_chatter: do not be poetic; do not mention stories, listening, silence, screen, or logs; "
            "keep it concrete and not emotional or dramatic. "
            "Every candidate line must pass atmosphere + rhythm + limit before wording: anchor one concrete current detail "
            "such as current_focus, a visible speech_evidence item, a named topic_seed, or the immediate interaction rhythm; attitude stays light; limit stays short. "
            "Write a fresh line; do not use canned phrases or reusable templates. "
            "Treat force_speak as the trigger, not the topic; do not make the user request itself into entertainment. "
            "Only say Ngài called ERIS if this is a real chat or force_speak request and no better atmosphere/current_focus anchor exists; autonomous inner_whim must not invent a call. "
            "Do not mention force_speak, context menu, telemetry, window, tab, idle, CPU, RAM, or vision facts unless speech_evidence contains them. "
            "If speech_evidence=<none>, do not claim to see the screen and do not open a social-filler topic; "
            "look at current_focus/atmosphere/rhythm, then make one concise presence remark. "
            "Do not ask 'Ngài muốn tôi nói gì' or answer that there is no signal; do not perform, banter, or entertain from thin evidence. "
            "Banned force_speak phrase families: lùi lại, không cần nói gì, không có gì để nói, Ngài cứ làm việc, "
            "câu chuyện nhỏ, một người nghe, không cần màn hình, dòng log khô khan, ngồi nhìn log. "
            "Avoid repeating the last sentence, its main nouns, and its structure."
        )


    def _build_ni_telemetry_summary(self, snapshot) -> str:
        """Tóm tắt telemetry gọn cho Ni meta-critic mà không phụ thuộc TelemetryService.

        Dùng được cả trong unit test (dummy snapshot chỉ cần vài trường cơ bản).
        """

        focus = getattr(snapshot, "focus_summary", "") or ""
        window = getattr(snapshot, "active_window", "") or ""
        kind = getattr(snapshot, "active_window_kind", "") or ""
        url = getattr(snapshot, "browser_url", "") or ""
        idle = getattr(snapshot, "idle_seconds", 0.0) or 0.0
        mood_score = getattr(snapshot, "mood_score", 50)
        mood_label = getattr(snapshot, "mood_label", "") or ""
        idle_label = getattr(snapshot, "idle_label", "") or ""
        recent_events = getattr(snapshot, "recent_events", ()) or ()
        user_signals = getattr(snapshot, "user_signals", None)
        vision_facts = getattr(snapshot, "vision_facts", ()) or ()
        evidence = getattr(snapshot, "evidence", ()) or ()
        claim_style = getattr(snapshot, "claim_style", "") or ""
        parts = [
            f"focus={focus}",
            f"window={window}",
            f"kind={kind}",
        ]
        if url:
            parts.append(f"url={url}")
        parts.append(f"idle={idle:.0f}s({idle_label})")
        parts.append(f"mood={mood_score}({mood_label})")
        if recent_events:
            parts.append("recent_events=" + ",".join(str(item) for item in recent_events[:3]))
        if user_signals is not None:
            typing_speed = getattr(user_signals, "typing_speed", "") or ""
            window_switching = getattr(user_signals, "window_switching", "") or ""
            focus_pattern = getattr(user_signals, "focus_pattern", "") or ""
            if any((typing_speed, window_switching, focus_pattern)):
                parts.append(
                    "user_signals="
                    f"{typing_speed or 'unknown'}/{window_switching or 'unknown'}/{focus_pattern or 'unknown'}"
                )
        if evidence:
            parts.append("evidence=" + " | ".join(str(item) for item in evidence[:2]))
        if vision_facts:
            parts.append("vision_facts=" + " | ".join(str(item) for item in vision_facts[:2]))
        if claim_style:
            parts.append(f"claim_style={claim_style}")
        return " | ".join(parts)

    def _label_drift_score(self, drift_score: float) -> str:
        if drift_score >= 0.75:
            return "nghiêm trọng"
        if drift_score >= 0.55:
            return "cao"
        if drift_score >= 0.35:
            return "vừa"
        return "thấp"

    def _is_low_signal_chat_message(self, user_text: str) -> bool:
        normalized = self._normalize_user_message(user_text)
        if not normalized:
            return True

        low_signal_phrases = {
            "xin chao",
            "chao",
            "hello",
            "hi",
            "hey",
            "ok",
            "okay",
            "oke",
            "alo",
            "yes",
            "no",
            "uh",
            "um",
        }
        if normalized in low_signal_phrases:
            return True

        tokens = normalized.split()
        if len(tokens) <= 2 and all(token in low_signal_phrases for token in tokens):
            return True
        return False

    def _conversation_ttl_seconds(self) -> float:
        """TTL của bộ đệm hội thoại hợp nhất.

        Một lượt cũ hơn ngần này (tính từ lúc ghi) bị coi là đã phai và không còn
        xuất hiện trong prompt. <=0 nghĩa là không phai theo thời gian.
        """
        return max(0.0, float(os.getenv("ERIS_CONVERSATION_TTL_SEC", "900") or 0.0))

    def _chat_history_for_llm(self, *, limit: int = 16, fresh_only: bool = False) -> list[dict]:
        ttl = self._conversation_ttl_seconds() if fresh_only else 0.0
        now = time.time()
        valid_entries = []
        for item in self.chat_history:
            if bool(item.get("invalid")):
                continue
            if str(item.get("role", "")) not in {"system", "user", "assistant"}:
                continue
            if ttl > 0.0:
                ts = float(item.get("ts", 0.0) or 0.0)
                if ts > 0.0 and (now - ts) > ttl:
                    continue
            valid_entries.append(
                {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
            )
        return valid_entries[-limit:]

    def _append_chat_history(self, role: str, content: str, *, invalid: bool = False) -> None:
        entry = {"role": role, "content": content, "ts": time.time()}
        if invalid:
            entry["invalid"] = True
        self.chat_history.append(entry)
        # Cap rộng để autonomous (vốn cũng ghi vào đây) không làm phình vô hạn.
        if len(self.chat_history) > 64:
            self.chat_history = self.chat_history[-64:]

    def _build_conversation_context(self, *, limit: int = 6) -> str:
        """Render đuôi hội thoại gần nhất (còn tươi) thành block prompt.

        Đây là cầu nối liền mạch chat <-> autonomous: cùng một bộ đệm, không recap
        riêng. Trả "" nếu không còn lượt nào đủ tươi.
        """
        turns = self._chat_history_for_llm(limit=limit, fresh_only=True)
        turns = [t for t in turns if str(t.get("content", "")).strip()]
        if not turns:
            return ""
        # Chỉ surface khi Ngài có tham gia gần đây. Nếu cửa sổ chỉ toàn lời ERIS
        # tự nói (autonomous độc thoại), đừng coi đó là "hội thoại" để nối tiếp.
        if not any(t.get("role") == "user" for t in turns):
            return ""
        lines = [
            "RECENT CONVERSATION (Ngài và ERIS vừa trò chuyện; nối mạch tự nhiên "
            "nếu hợp ngữ cảnh, đừng lặp nguyên văn, đừng bịa thêm):",
        ]
        for turn in turns:
            speaker = "Ngài" if turn.get("role") == "user" else "ERIS"
            lines.append(f"- {speaker}: {str(turn.get('content', '')).strip()}")
        return "\n".join(lines)

    def _merge_conversation_context(self, memory_context: str) -> str:
        """Ghép đuôi hội thoại gần nhất vào memory_context của autonomous."""
        convo = self._build_conversation_context()
        if not convo:
            return memory_context
        if memory_context and memory_context.strip():
            return f"{memory_context}\n\n{convo}".strip()
        return convo

    def _user_denies_last_assistant_assumption(self, user_text: str) -> bool:
        # Ưu tiên appraisal có đối chiếu claim trước. Regex dưới chỉ còn là
        # fallback tương thích cho các đường gọi cũ chưa dựng Dual-Axis Repair.
        social = getattr(self, "current_social_appraisal", None)
        policy = getattr(social, "claim_policy", None)
        if bool(getattr(policy, "suppress_for_current_turn", False)):
            return True
        appraisal = getattr(self, "current_repair_appraisal", None)
        if bool(getattr(appraisal, "suppress_previous_claim_for_turn", False)):
            return True
        normalized = self._normalize_user_message(user_text)
        if not normalized or not self.last_chat_answer.strip():
            return False
        denial_prefixes = (
            "khong phai",
            "sai",
            "sai roi",
            "y toi khong phai",
            "y minh khong phai",
            "ban hieu sai",
            "cau do sai",
            "khong dung",
        )
        denial_exact = {"khong", "dau"}
        denial_phrases = (
            "khong phai y toi",
            "khong phai y minh",
            "toi khong noi vay",
            "toi dau co noi vay",
            "ban doan sai roi",
            "ban hieu lech roi",
        )
        if normalized in denial_exact:
            return True
        if any(normalized.startswith(prefix) for prefix in denial_prefixes):
            return True
        return any(phrase in normalized for phrase in denial_phrases)

    def _invalidate_last_assistant_history(self, *, note: str) -> None:
        for item in reversed(self.chat_history):
            if str(item.get("role", "")) == "assistant" and not bool(item.get("invalid")):
                item["invalid"] = True
                break
        self._append_chat_history("system", note)

    def _maybe_invalidate_last_assistant_history(self, user_text: str) -> None:
        if not self._user_denies_last_assistant_assumption(user_text):
            return
        note = "Previous assistant inference was wrong. Do not build on it."
        self._invalidate_last_assistant_history(note=note)
        self.logger.info("[CHAT HISTORY] invalidated last assistant turn after user denial.")

    def _looks_like_no_evidence_style(self, claim_style: str) -> bool:
        lowered = (claim_style or "").strip().lower()
        markers = (
            "no_evidence",
            "refusal",
            "uncertainty",
            "soft_claim",
            "grounded",
            "weak_impression",
        )
        return any(marker in lowered for marker in markers)

    def _build_ni_structured_context(
        self,
        *,
        drift_score: float,
        drift_level: str,
        confidence: float,
        should_raise_guard: bool,
        reason_span: str,
        evidence: tuple[str, ...],
    ) -> str:
        guard = 1 if should_raise_guard else 0
        lines = [f"Ni: drift={drift_score:.2f}({drift_level}) conf={confidence:.2f} guard={guard}."]
        if reason_span:
            lines.append(f"Reason: {reason_span}.")
        if evidence:
            lines.append(f"Bám vào: {' | '.join(evidence[:3])}.")
        return "\n".join(lines)
