from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any, Mapping

from cortex.contracts import (
    ThoughtStreamReport,
)
from cortex.internal_state import PersistentInternalState
from domain import Decision
from core.temporal_context import build_temporal_context_from_runtime
from runtime.diagnostic_logging import safe_log
from runtime.no_fallback_policy import no_fallback_mode_enabled
from runtime.voice_policy import VOICE_POLICY


class PromptContextBuilderMixin:




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
                except (TypeError, ValueError):
                    pass
            if pressure != "":
                try:
                    meta.append(f"pressure={float(pressure):.2f}")
                except (TypeError, ValueError):
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
                    safe_log(logger, "debug", "Thought root unresolved_memory skipped: %s", exc)

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
            except Exception as exc:
                safe_log(getattr(self, "logger", None), "debug", "Internal agenda roots unavailable: %s", exc)

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
        # Đồng thời ghi journal episode cho living user memory. Đây chỉ là buffer
        # tóm tắt; raw conversation history vẫn thuộc chat/event ledger.
        if not invalid:
            living_user = getattr(getattr(self, "memory_kernel", None), "living_user", None)
            recorder = getattr(living_user, "record_conversation_turn", None)
            if callable(recorder):
                try:
                    session_id = ""
                    stage_bus = getattr(self, "stage_event_bus", None)
                    snapshot_fn = getattr(stage_bus, "session_snapshot", None)
                    if callable(snapshot_fn):
                        session_id = str((snapshot_fn() or {}).get("session_id") or "")
                    workspace = getattr(self, "workspace_manager", None)
                    project_id = str(
                        getattr(workspace, "active_project_id", "")
                        or getattr(self, "active_project_id", "")
                        or ""
                    )
                    recorder(
                        role,
                        content,
                        session_id=session_id,
                        context={"project_id": project_id},
                    )
                except Exception:
                    # Episode journal là enrichment; không được làm hỏng chat history.
                    pass
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
        # Chỉ surface khi bạn có tham gia gần đây. Nếu cửa sổ chỉ toàn lời ERIS
        # tự nói (autonomous độc thoại), đừng coi đó là "hội thoại" để nối tiếp.
        if not any(t.get("role") == "user" for t in turns):
            return ""
        lines = [
            "RECENT CONVERSATION (bạn và ERIS vừa trò chuyện; nối mạch tự nhiên "
            "nếu hợp ngữ cảnh, đừng lặp nguyên văn, đừng bịa thêm):",
        ]
        for turn in turns:
            speaker = "bạn" if turn.get("role") == "user" else "ERIS"
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





