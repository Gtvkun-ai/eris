from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass

from cortex.contracts import SessionRitualReport
from cortex.social_presence import SocialPresenceDetector
from domain import Decision


@dataclass(frozen=True, slots=True)
class MicroPresenceSynthesis:
    kind: str #loại hiện diện
    seeds: tuple[str, ...] = () #mầm ý tưởng
    context: dict[str, str] | None = None #ngữ cảnh phụ
    fallback_text: str = "Khoảng lặng này làm tôi nghĩ hơi nhiều."
    should_verbalize: bool = True


@dataclass(frozen=True, slots=True)
class SocialPresenceEvent:
    present: bool #có event không
    kind: str = "" #loại event
    confidence: float = 0.0 #độ tin cậy
    intensity: float = 0.0 #cường độ
    speech_allowed: bool = False #có được phép nói không
    reason: str = "" # lý do
    evidence: tuple[str, ...] = () # bằng chứng
    timestamp: str = "" #thời điểm

    #Chuyển object thành dict để log hoặc serialize
    presence_vector: tuple[float, ...] = ()
    stability: float = 0.0
    continuity_persistence: float = 0.0
    fragmentation: float = 0.0
    anxiety: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "present": bool(self.present),
            "confidence": round(float(self.confidence), 3), # làm tròn 3 chữ số
            "intensity": round(float(self.intensity), 3), # làm tròn 3 chữ số
            "kind": self.kind,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "timestamp": self.timestamp,
            "source": "runtime_coordinator",
            "speech_allowed": bool(self.speech_allowed),
            "presence_vector": [round(float(value), 3) for value in self.presence_vector],
            "stability": round(float(self.stability), 3),
            "continuity_persistence": round(float(self.continuity_persistence), 3),
            "fragmentation": round(float(self.fragmentation), 3),
            "anxiety": round(float(self.anxiety), 3),
        }




class PresenceControllerMixin:
    def _event_semantic_presence_detector(self) -> SocialPresenceDetector:
        detector = getattr(self, "_social_presence_detector", None)
        if detector is None:
            detector = SocialPresenceDetector()
            self._social_presence_detector = detector
        return detector

    def _detect_social_presence_event(
        self,
        *,
        channel: str,
        snapshot,
        internal_state: PersistentInternalState | None,
        started_at: float | None = None,
    ) -> SocialPresenceEvent:
        timestamp = self._event_timestamp(snapshot, started_at=started_at)
        idle_seconds = float(getattr(snapshot, "idle_seconds", 0.0) or 0.0)
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        user_signals = getattr(snapshot, "user_signals", None)
        typing_speed = str(getattr(user_signals, "typing_speed", "") or "")
        window_switching = str(getattr(user_signals, "window_switching", "") or "")

        evidence: list[str] = []
        if idle_seconds:
            evidence.append(f"idle_seconds={idle_seconds:.1f}")
        if typing_speed:
            evidence.append(f"typing_speed={typing_speed}")
        if window_switching:
            evidence.append(f"window_switching={window_switching}")
        if recent_events:
            evidence.append(f"recent_events={','.join(str(item) for item in recent_events[:3])}")

        if str(channel or "") in {"autonomous", "background"}:
            detected = self._event_semantic_presence_detector().detect(
                channel=channel,
                snapshot=snapshot,
                internal_state=internal_state,
                timestamp=timestamp,
            )
            combined_evidence = tuple(dict.fromkeys((*evidence, *tuple(getattr(detected, "evidence", ()) or ()))))[:6]
            return SocialPresenceEvent(
                present=bool(getattr(detected, "present", False)),
                kind=str(getattr(detected, "kind", "") or ""),
                confidence=float(getattr(detected, "confidence", 0.0) or 0.0),
                intensity=float(getattr(detected, "intensity", 0.0) or 0.0),
                speech_allowed=False,
                reason=str(getattr(detected, "reason", "") or ""),
                evidence=combined_evidence,
                timestamp=timestamp,
                presence_vector=tuple(getattr(detected, "presence_vector", ()) or ()),
                stability=float(getattr(detected, "stability", 0.0) or 0.0),
                continuity_persistence=float(getattr(detected, "continuity_persistence", 0.0) or 0.0),
                fragmentation=float(getattr(detected, "fragmentation", 0.0) or 0.0),
                anxiety=float(getattr(detected, "anxiety", 0.0) or 0.0),
            )

        low_idle = idle_seconds <= 8.0
        has_mouse = any(str(item) == "mouse_moved" for item in recent_events)
        has_typing = typing_speed not in {"", "zero", "none"}
        present = bool(low_idle and (has_mouse or has_typing))
        if not present:
            return SocialPresenceEvent(present=False, timestamp=timestamp)

        kind = "typing" if has_typing else "mouse_moved"
        speech_allowed = channel in {"chat", "force_speak"}
        reason = "low_idle_user_signal"
        confidence = 0.62
        return SocialPresenceEvent(
            present=True,
            kind=kind,
            confidence=confidence,
            intensity=0.58,
            speech_allowed=speech_allowed,
            reason=reason,
            evidence=tuple(evidence)[:6],
            timestamp=timestamp,
        )

    def _note_autonomous_silence(self) -> int:
        self.presence_maintenance_silent_cycles = int(getattr(self, "presence_maintenance_silent_cycles", 0) or 0) + 1
        self.reengagement_quiet_cycles = int(getattr(self, "reengagement_quiet_cycles", 0) or 0) + 1
        return self.presence_maintenance_silent_cycles

    def _note_autonomous_spoken(
        self,
        *,
        presence_maintenance: bool = False,
        reengagement: bool = False,
        now: float | None = None,
    ) -> None:
        current_time = time.time() if now is None else now
        self.presence_maintenance_silent_cycles = 0
        if presence_maintenance:
            self.last_presence_maintenance_at = current_time
        if reengagement:
            self.last_reengagement_at = current_time
            self.reengagement_quiet_cycles = 0
        elif not presence_maintenance:
            self.reengagement_quiet_cycles = 0

    # cho phép nói chuyện nhỏ an toàn nếu đang ở kênh tự động, không có tín hiệu màn hình cụ thể
    def _safe_small_talk_budget_allowed(self, *, channel: str, snapshot, now: float | None = None) -> bool:
        if str(channel or "") != "autonomous":
            return False
        if self._has_concrete_screen_signal(snapshot):
            return False
        current_time = time.time() if now is None else now
        last_spoken = float(getattr(self, "last_autonomous_spoken_at", 0.0) or 0.0)
        if last_spoken <= 0.0:
            return False
        if current_time - last_spoken < 300.0:
            return False
        if self.presence_maintenance_silent_cycles < 1:
            return False
        recent = self._recent_spoken_texts(limit=3)
        if sum(1 for line in recent if "?" in str(line or "")) >= 2:
            return False
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        has_window = bool(str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip())
        has_presence = idle_seconds >= 60.0 or bool(tuple(getattr(snapshot, "recent_events", ()) or ()))
        return bool(has_window or has_presence)

    def _should_allow_presence_maintenance(
        self,
        *,
        snapshot,
        ti_report,
        social_presence_event: SocialPresenceEvent | None,
        now: float | None = None,
    ) -> bool:
        current_time = time.time() if now is None else now
        if not getattr(self, "presence_maintenance_enabled", True):
            return False
        if current_time < float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0):
            return False
        if self.presence_maintenance_silent_cycles < self.presence_maintenance_silent_loop_threshold:
            return False

        cooldown = float(getattr(self, "presence_maintenance_cooldown_sec", 0.0) or 0.0)
        if self.last_presence_maintenance_at > 0.0 and current_time - self.last_presence_maintenance_at < cooldown:
            return False

        last_spoken = float(getattr(self, "last_autonomous_spoken_at", 0.0) or 0.0)
        spoken_floor = 8.0 if cooldown <= 0.0 else max(8.0, min(20.0, cooldown))
        if last_spoken > 0.0 and current_time - last_spoken < spoken_floor:
            return False

        mode = str(getattr(ti_report, "mode", "") or "")
        if mode in {"resource_guard", "goal_drift_alert", "goal_realign", "system_warning"}:
            return False

        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(getattr(snapshot, "recent_events", ()) or ())
        present = bool(getattr(social_presence_event, "present", False))
        if idle_seconds >= 1800.0 and not present:
            return False
        return present or idle_seconds <= 300.0 or bool(recent_events)

    def _presence_maintenance_lines(self, snapshot) -> tuple[str, ...]:
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "")
        browser_url = str(getattr(snapshot, "browser_url", "") or "")
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "")
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "")
        vision_facts = tuple(str(item or "").strip() for item in (getattr(snapshot, "vision_facts", ()) or ()) if str(item or "").strip())
        cue = vision_facts[0] if vision_facts else (focus_summary or active_window or focus_kind)
        return self._cue_micro_lines(
            cue=cue,
            active_window=active_window,
            browser_url=browser_url,
            focus_kind=focus_kind,
            focus_summary=focus_summary,
            presence=True,
        )

    def _cue_micro_lines(
        self,
        *,
        cue: str,
        active_window: str = "",
        browser_url: str = "",
        focus_kind: str = "",
        focus_summary: str = "",
        presence: bool = False,
    ) -> tuple[str, ...]:
        compact_cue = re.sub(r"\s+", " ", str(cue or "").strip()).strip(" .")
        window = re.sub(r"\s+", " ", str(active_window or "").strip()).strip(" .")
        summary = re.sub(r"\s+", " ", str(focus_summary or "").strip()).strip(" .")
        haystack = self._normalize_user_message(" ".join((compact_cue, window, browser_url, summary, focus_kind)))
        lines: list[str] = []

        if "banner" in haystack and any(term in haystack for term in ("trinh bay", "present", "presentation", "share")):
            lines.extend(
                (
                    "Cái banner trình bày kia vẫn nằm đó.",
                    "Banner trình bày vẫn mắc ở một góc.",
                )
            )
        if "meet" in haystack or "meeting" in haystack or "cuoc goi" in haystack:
            lines.extend(
                (
                    "Phòng Meet kia vẫn chưa gấp lại.",
                    "Vẫn là nhịp Meet đó à.",
                    "Cuộc gọi đó im hơi lâu rồi.",
                    "Nhịp chia sẻ đó mở hơi lâu rồi.",
                )
            )
        elif "youtube" in haystack or "music youtube" in haystack:
            lines.extend(("Tab YouTube vẫn mở ở đó.", "Nhạc vẫn chạy nền khe khẽ."))
        elif focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "visual studio", "vscode", "python", "debug")):
            # Chỉ tới được nhánh này khi cue/focus có dấu hiệu code rõ.
            # Vẫn phải có dấu tiếng Việt để MicroLinePolicy không reject.
            lines.extend(("Mạch code này vẫn giữ chỗ.", "Đoạn này đứng hơi lâu rồi."))
        elif focus_kind == "communication" or any(term in haystack for term in ("chat", "message", "zalo", "discord", "slack")):
            lines.extend(("Nhịp trao đổi này vẫn yên một chút.", "Đoạn đối đáp đó vẫn để nguyên."))

        subject = self._micro_line_subject(compact_cue or summary or window or focus_kind)
        if subject:
            lines.append(f"{subject} vẫn chưa khép.")
            if presence:
                lines.append(f"{subject} im hơi lâu rồi.")
        if not lines:
            lines.append("Nhịp này im hơi lâu rồi.")

        return tuple(dict.fromkeys(self._clean_micro_line(line) for line in lines if self._clean_micro_line(line)))[:5]

    def _micro_line_subject(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .")
        if not text or self._looks_internal_topic(text):
            return ""
        normalized = self._normalize_user_message(text)
        if "meet" in normalized:
            return "phòng Meet"
        if "banner" in normalized:
            return "banner trình bày kia"
        if "youtube" in normalized:
            return "tab YouTube"
        if "visual studio" in normalized or "vscode" in normalized:
            return "mạch code này"
        if len(text) > 34:
            text = text[:34].rstrip(" ,;:-")
        return text[0].lower() + text[1:] if text else ""

    def _clean_micro_line(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip())
        if not cleaned:
            return ""
        cleaned = cleaned.replace("!", ".")
        if not cleaned.endswith((".", "?", "à")):
            cleaned += "."
        words = [item for item in re.split(r"\s+", cleaned.strip(" .?")) if item]
        if len(words) < 3 or len(words) > 12:
            return ""
        normalized = self._normalize_user_message(cleaned)
        banned = ("toi van o day", "toi o day", "toi nghe day", "toi van dang quan sat", "toi van theo doi")
        banned_ascii = (
            "status",
            "ui",
            "khung",
            "khung thoai",
            "khung chat",
            "mau hong",
            "man hinh",
            "cua so",
            "hien thi",
            "dang hien thi",
            "toi dang",
            "toi van",
            "toi o day",
            "toi nghe",
            "toi thay",
        )
        if any(self._normalize_user_message(item) in normalized for item in (*banned, *banned_ascii)):
            return ""
        return cleaned

    # chấm điểm candidates quan sát viễn cảnh để quyết định có nên nói hay không, và nếu có thì nói gì để duy trì sự hiện diện một cách tinh tế, tránh bị lạc lõ
    def _vision_fact_micro_observation_candidate(
        self,
        frame: CognitiveFrame,
    ) -> tuple[str, float]:
        best_text = ""
        best_score = 0.0
        for candidate in tuple(getattr(frame, "attention_candidates", ()) or ()):
            if str(getattr(candidate, "label", "") or "") != "vision_fact":
                continue
            text = str(getattr(candidate, "content", "") or "").strip()
            if not text:
                continue
            score = self._bounded_float(getattr(candidate, "score", 0.0))
            if score > best_score:
                best_text = text
                best_score = score
        for percept in tuple(getattr(frame, "percepts", ()) or ()):
            if str(getattr(percept, "kind", "") or "") != "vision_fact":
                continue
            text = str(getattr(percept, "content", "") or "").strip()
            if not text:
                continue
            score = max(self._bounded_float(getattr(percept, "confidence", 0.0)), best_score if text == best_text else 0.0)
            if score > best_score:
                best_text = text
                best_score = score
        min_score = 0.54
        if self.presence_maintenance_silent_cycles >= 2:
            min_score = 0.46
        if self.presence_maintenance_silent_cycles >= 3:
            min_score = 0.38
        if best_score < min_score:
            return "", best_score
        return best_text, best_score

    def _build_micro_observation_decision(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        now: float | None = None,
    ) -> Decision | None:
        if self.presence_maintenance_silent_cycles < 1:
            return None
        cue, score = self._vision_fact_micro_observation_candidate(frame)
        if not cue:
            return None
        lines = self._cue_micro_lines(
            cue=cue,
            active_window=str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or ""),
            browser_url=str(getattr(snapshot, "browser_url", "") or ""),
            focus_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
            focus_summary=str(getattr(snapshot, "focus_summary", "") or ""),
        )
        text = self._choose_local_micro_line(
            lines,
            counter=self.presence_maintenance_silent_cycles,
            threshold=1,
        )
        if not text:
            return None
        return Decision(
            text=text,
            animation="stand",
            intent="micro_observation",
            reasoning_tags=("micro_observation", "vision_fact"),
            should_speak=True,
            confidence=max(0.50, min(0.78, score)),
            parse_mode="micro_observation",
            debug_trace=(
                "micro_observation_layer"
                f"; vision_fact_score={score:.2f}"
                f"; silent_cycles={self.presence_maintenance_silent_cycles}"
            ),
        )

    def _try_finalize_micro_observation_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        meaning_layer = getattr(frame, "meaning_layer", None)
        if str(getattr(meaning_layer, "meaning", "") or ""):
            return False
        if (
            meaning_layer is not None
            and str(getattr(meaning_layer, "meaning_signal", "") or "")
            not in {"", "none", "weak_meaning", "ambient_meaning", "vibe_signal"}
            and not bool(getattr(meaning_layer, "meaning_shift", False))
        ):
            return False
        decision = self._build_micro_observation_decision(
            frame=frame,
            snapshot=snapshot,
            now=now,
        )
        if decision is None:
            return False
        cue, score = self._vision_fact_micro_observation_candidate(frame)
        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="micro_observation",
            speech_act="micro_observation",
            reason="Vision fact stayed salient after a silent cycle; prefer micro observation over no_speech.",
            snapshot=snapshot,
            concrete_signals=(cue,),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("micro_observation", f"vision_fact_score={score:.2f}", f"silent_cycles={self.presence_maintenance_silent_cycles}"),
        )
        if not frame.action_plan.should_speak:
            return False
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        decision.parse_mode = "micro_observation"
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = now
        self._note_autonomous_spoken(now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("micro_observation",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[micro_observation] text="%s" | vision_score=%.2f',
            decision.text,
            score,
        )
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ micro_observation trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    def _micro_presence_kind_from_seed(self, seed: str) -> str:
        normalized = self._normalize_user_message(seed)
        if "bodily" in normalized:
            return "bodily_residue"
        if "social" in normalized:
            return "social_residue"
        if "thought" in normalized or "cognitive" in normalized:
            return "thought_residue"
        return "screen_residue"

    def _thought_residue_seeds(self, report) -> tuple[str, ...]:
        seeds: list[str] = []
        seed = getattr(report, "latest_seed", None)
        thought = getattr(report, "latest_thought", None)
        attractor = getattr(report, "active_attractor", None)
        for value in (
            getattr(seed, "partial_text", ""),
            getattr(thought, "partial_text", ""),
            getattr(seed, "unresolved_reason", ""),
            getattr(thought, "unresolved_reason", ""),
        ):
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text and not self._looks_internal_topic(text):
                seeds.append(text[:80])
        topic = str(
            getattr(seed, "topic_seed", "")
            or getattr(thought, "topic_seed", "")
            or getattr(attractor, "topic_seed", "")
            or ""
        )
        public_topic = self._public_thought_topic(topic)
        if public_topic:
            seeds.append(f"{public_topic} vẫn chưa khớp")
        if getattr(attractor, "attractor", False):
            seeds.append("có một mạch cũ quay lại")
        return tuple(dict.fromkeys(seed for seed in seeds if seed))[:3]

    def _synthesize_micro_presence(
        self,
        *,
        snapshot,
        thought_stream_report=None,
        social_presence_event: SocialPresenceEvent | None = None,
        inner_thought: InnerThought | None = None,
    ) -> MicroPresenceSynthesis:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "").strip() or "general"
        focus_summary = str(getattr(snapshot, "focus_summary", "") or "").strip() or focus_kind
        active_window = str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "").strip()
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        seed_hint = str(getattr(inner_thought, "topic_seed", "") or "")
        kind = self._micro_presence_kind_from_seed(seed_hint)

        seeds: list[str] = []
        haystack = self._normalize_user_message(" ".join((active_window, focus_summary, focus_kind, " ".join(recent_events))))
        if "godot" in haystack:
            seeds.append("Godot vẫn mở ở đó thêm chút.")
        elif focus_kind in {"coding", "documentation"} or any(term in haystack for term in ("code", "vscode", "visual studio", "debug")):
            seeds.append("mạch code này vẫn giữ chỗ.")
        elif active_window:
            title = re.sub(r"\s+", " ", active_window).strip()
            if title and not self._looks_internal_topic(title):
                seeds.append(f"{title[:36]} vẫn mở ở đó thêm chút.")

        if any("log" in self._normalize_user_message(item) for item in recent_events):
            seeds.append("log cũ lại lặp thêm một nhịp.")
        if idle_seconds >= 240:
            seeds.append("nhịp này im khá lâu rồi.")
        elif not seeds and focus_summary:
            seeds.append(f"{focus_summary[:48]} vẫn yên thêm một chút.")

        thought_seeds = self._thought_residue_seeds(thought_stream_report)
        if thought_seeds:
            kind = "thought_residue"
            seeds.extend(thought_seeds)

        if kind == "bodily_residue":
            seeds = ["Mạch này vẫn hơi nghẽn lại."] + seeds
        elif kind == "social_residue" or bool(getattr(social_presence_event, "present", False)):
            kind = "social_residue"
            if focus_kind == "coding":
                seeds.insert(0, "mạch đó vẫn chưa chịu thả.")
            else:
                seeds.insert(0, "khoảng yên này vẫn giữ chỗ.")

        seeds = tuple(dict.fromkeys(seed for seed in seeds if str(seed or "").strip()))[:5]
        fallback = seeds[0] if seeds else "Mạch này vẫn hơi nghẽn lại."
        return MicroPresenceSynthesis(
            kind=kind,
            seeds=seeds,
            context={
                "window": active_window[:80],
                "idle": "long" if idle_seconds >= 240 else "short",
                "pattern": "repetitive_logs" if any("log" in self._normalize_user_message(item) for item in recent_events) else "",
                "focus": focus_kind,
            },
            fallback_text=fallback,
            should_verbalize=True,
        )

    def _choose_local_micro_line(self, lines: tuple[str, ...], *, counter: int, threshold: int) -> str:
        if not lines:
            return ""
        start = (counter - threshold) % len(lines)
        text = lines[start]
        for offset in range(len(lines)):
            candidate = lines[(start + offset) % len(lines)]
            if not self._is_near_duplicate_text(candidate, self.last_text):
                text = candidate
                break
        return text

    def _local_grounded_micro_presence_text(self, synthesis: MicroPresenceSynthesis) -> str:
        candidates = tuple(synthesis.seeds or ()) or (synthesis.fallback_text,)
        for candidate in candidates:
            cleaned = re.sub(r"\s+", " ", str(candidate or "").strip()).replace("!", ".")
            if not cleaned:
                continue
            if self._is_placeholder_micro_text(cleaned):
                continue
            if "?" in cleaned or self._looks_internal_topic(cleaned):
                continue
            if not cleaned.endswith("."):
                cleaned = cleaned.strip(" .") + "."
            words = [item for item in re.split(r"\s+", cleaned.strip(" .")) if item]
            if 3 <= len(words) <= 8:
                return cleaned[:80]
        return "Mạch này vẫn hơi nghẽn."

    def _is_placeholder_micro_text(self, text: str) -> bool:
        normalized = self._normalize_user_message(str(text or "").strip())
        return normalized in {"", "hm", "um", "..."} or str(text or "").strip() in {"...", "…"}

    def _micro_line_policy_for_action_plan(self, frame: CognitiveFrame, *, vision_fact: str = ""):
        return self.micro_line_policy.evaluate(
            speech_intent=frame.action_plan.speech_intent,
            broadcast=frame.broadcast,
            vision_fact=vision_fact,
            last_lines=self._recent_spoken_texts(limit=20),
            channel=frame.channel,
        )

    def _micro_presence_generator(self):
        generator = getattr(self.llm_service, "generate_micro_presence", None)
        if callable(generator):
            return generator
        generator = getattr(self.llm_service, "generate_micro_presence_line", None)
        return generator if callable(generator) else None

    def _should_try_micro_presence_llm(self, *, kind: str, force_llm: bool = False) -> bool:
        if not getattr(self, "micro_presence_llm_enabled", True):
            return False
        if self._micro_presence_generator() is None:
            return False
        if force_llm:
            return True
        probability = max(0.0, min(1.0, float(getattr(self, "micro_presence_llm_probability", 0.0) or 0.0)))
        if probability <= 0.0:
            return False
        return random.random() < probability

    def _sanitize_micro_presence_llm_text(self, text: str, *, kind: str, fallback_text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip().strip('"').strip("'"))
        cleaned = cleaned.replace("!", ".")
        cleaned = cleaned[:90].strip()
        if not cleaned:
            return ""
        if self._is_placeholder_micro_text(cleaned):
            return ""
        is_reengagement = kind == "re_engagement"
        words = [item for item in re.split(r"\s+", cleaned) if item]
        if len(words) > 8:
            return ""
        if "\n" in cleaned or cleaned.count("?") > (1 if is_reengagement else 0):
            return ""
        if "?" in cleaned and not is_reengagement:
            return ""
        if self._is_near_duplicate_text(cleaned, self.last_text) or self._is_near_duplicate_text(cleaned, fallback_text):
            return ""

        normalized = self._normalize_user_message(cleaned)
        if self._force_speak_banned_family_for_text(cleaned) == "presence_declaration":
            return ""
        banned = (
            "trả lời",
            "phản hồi",
            "cho tôi biết",
            "hãy ",
            "cần ",
            "phải ",
            "tập trung",
            "quay lại",
            "dừng lại",
            "telemetry",
            "cpu",
            "ram",
            "idle",
            "signal",
            "evidence",
            "tôi thấy màn hình",
            "màn hình của ngài",
            "tôi đang nhìn",
        )
        banned_ascii = (
            "status",
            "ui",
            "khung",
            "khung thoai",
            "khung chat",
            "mau hong",
            "man hinh",
            "cua so",
            "hien thi",
            "dang hien thi",
            "toi dang",
            "toi van",
            "toi o day",
            "toi nghe",
            "toi thay",
        )
        if any(self._normalize_user_message(item) in normalized for item in (*banned, *banned_ascii)):
            return ""
        if not is_reengagement and any(item in normalized for item in ("ồn chứ", "còn thức", "sao", "không")):
            return ""
        return cleaned

    def _hybrid_micro_presence_text(
        self,
        *,
        kind: str,
        snapshot,
        fallback_text: str,
        seeds: tuple[str, ...] = (),
        micro_context: dict[str, str] | None = None,
        force_llm: bool = False,
        signal_score: float = 0.0,
    ) -> tuple[str, str]:
        if not fallback_text:
            return "", "empty_fallback"
        if not self._should_try_micro_presence_llm(kind=kind, force_llm=force_llm):
            return fallback_text, "local"

        generator = self._micro_presence_generator()
        try:
            draft = generator(
                kind=kind,
                fallback_text=fallback_text,
                avoid_text=self.last_text,
                focus_kind=str(getattr(snapshot, "active_window_kind", "") or ""),
                focus_summary=str(getattr(snapshot, "focus_summary", "") or ""),
                idle_seconds=float(getattr(snapshot, "idle_seconds", 0.0) or 0.0),
                seeds=tuple(seeds or ()),
                micro_context=micro_context or {},
                signal_score=float(signal_score or 0.0),
            )
        except Exception as exc:
            self.logger.warning("Micro-presence LLM failed: %s", exc)
            return fallback_text, "llm_error_fallback"

        safe = self._sanitize_micro_presence_llm_text(
            draft,
            kind=kind,
            fallback_text=fallback_text,
        )
        if not safe:
            return fallback_text, "llm_rejected_fallback"
        return safe, "llm_signal" if force_llm else "llm"

    def _filter_public_micro_decision(
        self,
        decision: Decision,
        *,
        channel: str,
        frame: CognitiveFrame,
        snapshot,
        speech_core=None,
        momentum_topic: str = "",
    ) -> Decision:
        """Đưa mọi micro/presence/reengagement line qua cùng post-generation guard.

        Trước đây presence maintenance có thể bypass MicroLinePolicy, nên câu không dấu hoặc
        claim màn hình mỏng vẫn lọt. Một đường tắt nhỏ, hậu quả thì to như log debug.
        """
        filter_fn = getattr(self, "_apply_post_generation_filters", None)
        if callable(filter_fn):
            try:
                return filter_fn(
                    decision,
                    channel=channel,
                    speech_core=speech_core or getattr(frame, "speech_core", None),
                    snapshot=snapshot,
                    momentum_topic=momentum_topic,
                )
            except Exception as exc:
                self.logger.warning("%s post-generation filter failed: %s", channel, exc)
        return decision

    def _build_presence_maintenance_decision(
        self,
        *,
        snapshot,
        ti_report,
        social_presence_event: SocialPresenceEvent | None,
        now: float | None = None,
    ) -> Decision | None:
        if not self._should_allow_presence_maintenance(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=now,
        ):
            return None

        lines = self._presence_maintenance_lines(snapshot)
        if not lines:
            return None
        fallback_text = self._choose_local_micro_line(
            lines,
            counter=self.presence_maintenance_silent_cycles,
            threshold=self.presence_maintenance_silent_loop_threshold,
        )
        text, source = self._hybrid_micro_presence_text(
            kind="presence_maintenance",
            snapshot=snapshot,
            fallback_text=fallback_text,
            seeds=lines,
            micro_context={
                "window": str(getattr(snapshot, "active_window", "") or getattr(snapshot, "active_app", "") or "")[:80],
                "focus": str(getattr(snapshot, "active_window_kind", "") or ""),
                "vision": str((tuple(getattr(snapshot, "vision_facts", ()) or ("",))[0]) if tuple(getattr(snapshot, "vision_facts", ()) or ()) else "")[:120],
            },
        )

        return Decision(
            text=text,
            animation="stand",
            intent="presence_maintenance",
            reasoning_tags=("presence_maintenance", "micro_presence"),
            should_speak=True,
            confidence=0.48,
            parse_mode="presence_maintenance",
            debug_trace=(
                "presence_maintenance_layer"
                f"; source={source}"
                f"; silent_cycles={self.presence_maintenance_silent_cycles}"
                f"; threshold={self.presence_maintenance_silent_loop_threshold}"
            ),
        )

    def _try_finalize_presence_maintenance_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        social_presence_event: SocialPresenceEvent | None,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        decision = self._build_presence_maintenance_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            social_presence_event=social_presence_event,
            now=now,
        )
        if decision is None:
            return False
        silent_cycles = self.presence_maintenance_silent_cycles

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="presence_maintenance",
            speech_act="micro_presence",
            reason="Presence Maintenance Layer keeps co-presence after repeated quiet cycles.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("presence_maintenance", f"silent_cycles={self.presence_maintenance_silent_cycles}"),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        decision.parse_mode = "presence_maintenance"
        decision = self._filter_public_micro_decision(
            decision,
            channel="autonomous",
            frame=frame,
            snapshot=snapshot,
            speech_core=getattr(frame, "speech_core", None),
        )
        if not bool(getattr(decision, "should_speak", True)) or not str(getattr(decision, "text", "") or "").strip():
            return False
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = now
        self._note_autonomous_spoken(presence_maintenance=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("presence_maintenance",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[presence_maintenance] text="%s" | silent_cycles=%d',
            decision.text,
            silent_cycles,
        )
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ presence trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True

    # ERIS hiện có bao nhiêu năng lượng/xu hướng để chủ động quay lại tương tác với user?
    def _social_energy_for_reengagement(self, internal_state: PersistentInternalState | None) -> float:
        if internal_state is None:
            return 0.0
        values = [
            float(getattr(internal_state, "social_energy", 0.0) or 0.0),#social_energy:mức muốn giao tiếp/chủ động
            float(getattr(internal_state, "attachment", 0.0) or 0.0), #attachment:mức độ gắn bó, có thể hiểu là xu hướng duy trì kết nối với user
        ]
        processes = getattr(internal_state, "mental_processes", None)  #mental_processes có thể chứa nhiều quá trình tâm lý khác nhau, trong đó có social_presence
        social_process = getattr(processes, "social_presence", None) #social_presence: quá trình tâm lý liên quan đến sự hiện diện xã hội
        if social_process is not None:
            values.extend(
                [
                    float(getattr(social_process, "level", 0.0) or 0.0), #social_presence.level: mức độ cảm nhận được sự hiện diện xã hội, có thể ảnh hưởng đến mong muốn tương tác
                    float(getattr(social_process, "pressure", 0.0) or 0.0), #social_presence.pressure: áp lực xã hội, có thể thúc đẩy hoặc cản trở việc chủ động tương tác
                ]
            )
        return max(0.0, min(1.0, max(values)))

    # Kiểm tra xem có tín hiệu nào gần đây cho thấy người dùng vẫn đang hoạt động và có thể không cần re-engagement hay không
    def _has_meaningful_recent_activity(self, snapshot) -> bool:
        if self._has_concrete_screen_signal(snapshot):
            return True
        recent_events = tuple(str(item or "").strip() for item in (getattr(snapshot, "recent_events", ()) or ()) if str(item or "").strip())
        if not recent_events:
            return False
        low_meaning_terms = (
            "general_window_active", #general_window_active: chỉ ra rằng có một cửa sổ đang hoạt động, nhưng không cung cấp thông tin cụ thể về loại cửa sổ hoặc hoạt động nào đang diễn ra, do đó có thể không đủ để đánh giá sự hiện diện hoặc tương tác của người dùng.
            "long_idle_period", #long_idle_period: chỉ ra rằng đã có một khoảng thời gian dài không có hoạt động, nhưng không cung cấp thông tin về loại hoạt động nào đã bị thiếu hoặc mức độ tương tác trước đó, do đó có thể không đủ để đánh giá sự hiện diện hoặc nhu cầu re-engagement.
            "mouse_moved", #   mouse_moved: chỉ ra rằng chuột đã được di chuyển, nhưng không cung cấp thông tin về loại hoạt động nào đang diễn ra hoặc mức độ tương tác của người dùng, do đó có thể không đủ để đánh giá sự hiện diện hoặc nhu cầu re-engagement.
            "cursor",
            "window_active",
            "many_windows_open",
            "browser_url_visible",
        )
        for event in recent_events:
            lowered = event.lower()
            if self._is_speakable_evidence(event, kind="recent_event"):
                return True
            if not self._is_generic_screen_event(event) and not any(term in lowered for term in low_meaning_terms):
                return True
        return False

    # Sau một khoảng thời gian im lặng đủ dài, ERIS có nên chủ động tương tác lại với user không?
    def _should_allow_reengagement(
        self,
        *,
        snapshot,
        ti_report,
        internal_state: PersistentInternalState | None,
        now: float | None = None,
    ) -> bool:
        if not getattr(self, "reengagement_enabled", True): #reengagement_enabled: cờ bật/tắt tính năng re-engagement, nếu False thì ERIS sẽ không chủ động tương tác lại sau khoảng thời gian im lặng, giúp tránh làm phiền người dùng khi họ không muốn tương tác.
            return False
        if self.reengagement_quiet_cycles < self.reengagement_quiet_loop_threshold:
            return False

        # Kiểm tra cooldown để tránh re-engagement quá thường xuyên, giúp ERIS không làm phiền người dùng nếu họ đang bận hoặc không muốn tương tác ngay lập tức sau khi đã có một re-engagement gần đây.
        current_time = time.time() if now is None else now
        if current_time < float(getattr(self, "autonomous_presence_blocked_until", 0.0) or 0.0):
            return False
        cooldown = float(getattr(self, "reengagement_cooldown_sec", 0.0) or 0.0)
        if self.last_reengagement_at > 0.0 and current_time - self.last_reengagement_at < cooldown:
            return False

        mode = str(getattr(ti_report, "mode", "") or "")
        if mode in {"resource_guard", "goal_drift_alert", "goal_realign", "system_warning"}:
            return False

        # Kiểm tra xem có tín hiệu nào gần đây cho thấy người dùng vẫn đang hoạt động và có thể không cần re-engagement hay không. Nếu có những tín hiệu này, ERIS sẽ tránh re-engagement để không làm phiền người dùng khi họ đang tương tác bình thường.
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        if idle_seconds < self.reengagement_min_idle_sec:
            return False
        if self._has_meaningful_recent_activity(snapshot):
            return False
        return self._social_energy_for_reengagement(internal_state) >= 0.18

    # Dựa trên ngữ cảnh hiện tại của người dùng (như loại cửa sổ đang hoạt động, URL trình duyệt, tóm tắt tập trung), chọn một số câu phù hợp để re-engagement. Những câu này nên cảm thấy liên quan đến tình huống hiện tại của người dùng để tăng khả năng họ sẽ phản hồi tích cực.
    def _reengagement_lines(self, snapshot) -> tuple[str, ...]:
        focus_kind = str(getattr(snapshot, "active_window_kind", "") or "")
        idle_seconds = max(0.0, float(getattr(snapshot, "idle_seconds", 0.0) or 0.0))
        if focus_kind in {"coding", "documentation"}: #coding, documentation: nếu người dùng đang tập trung vào các cửa sổ liên quan đến lập trình hoặc tài liệu, ERIS có thể chọn những câu re-engagement liên quan đến việc hỗ trợ hoặc cung cấp thông tin hữu ích cho công việc của họ, giúp tăng khả năng tương tác tích cực.
            return (
                "Não vẫn chưa chịu nghỉ à.",
                "Ngài lại chìm mất rồi.",
                "Không gian yên quá.",
                "Ngài ổn chứ.",
            )
        if idle_seconds >= 1200: #idle_seconds: nếu người dùng đã im lặng trong một khoảng thời gian dài (ví dụ: 20 phút hoặc hơn), ERIS có thể chọn những câu re-engagement nhẹ nhàng và quan tâm, như hỏi thăm sức khỏe hoặc đề nghị giúp đỡ, để tạo cơ hội cho người dùng phản hồi mà không cảm thấy bị làm phiền.
            return (
                "Tôi bắt đầu tự hỏi Ngài còn thức không.",
                "Ngài lại chìm mất rồi.",
                "Không gian yên quá.",
            )
        return (
            "Ngài lại chìm mất rồi.",
            "Không gian yên quá.",
            "Hôm nay Ngài im hơn bình thường.",
            "Ngài ổn chứ.",
        )

    # Khi quyết định re-engagement, hãy đảm bảo rằng ERIS không lặp lại cùng một câu hoặc câu quá giống nhau nhiều lần liên tiếp, vì điều này có thể khiến người dùng cảm thấy bị làm phiền hoặc như đang nói chuyện với một cỗ máy lặp đi lặp lại. Việc đa dạng hóa các câu re-engagement có thể giúp giữ cho tương tác cảm thấy tươi mới và tự nhiên hơn.
    def _build_reengagement_decision(
        self,
        *,
        snapshot,
        ti_report,
        internal_state: PersistentInternalState | None,
        now: float | None = None,
    ) -> Decision | None:
        if not self._should_allow_reengagement(
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        ):
            return None

        lines = self._reengagement_lines(snapshot)
        if not lines:
            return None
        fallback_text = self._choose_local_micro_line(
            lines,
            counter=self.reengagement_quiet_cycles,
            threshold=self.reengagement_quiet_loop_threshold,
        )
        text, source = self._hybrid_micro_presence_text(
            kind="re_engagement",
            snapshot=snapshot,
            fallback_text=fallback_text,
        )

        return Decision(
            text=text,
            animation="stand",
            intent="re_engagement",
            reasoning_tags=("re_engagement", "long_silence_outreach"),
            should_speak=True,
            confidence=0.52,
            parse_mode="re_engagement",
            debug_trace=(
                "reengagement_layer"
                f"; source={source}"
                f"; quiet_cycles={self.reengagement_quiet_cycles}"
                f"; idle={int(float(getattr(snapshot, 'idle_seconds', 0.0) or 0.0))}s"
                f"; social_energy={self._social_energy_for_reengagement(internal_state):.2f}"
            ),
        )

    def _try_finalize_reengagement_cycle(
        self,
        *,
        frame: CognitiveFrame,
        snapshot,
        ti_report,
        fe_plan,
        internal_state: PersistentInternalState | None,
        cycle_start: float,
    ) -> bool:
        now = time.time()
        decision = self._build_reengagement_decision(
            snapshot=snapshot,
            ti_report=ti_report,
            internal_state=internal_state,
            now=now,
        )
        if decision is None:
            return False
        quiet_cycles = self.reengagement_quiet_cycles

        self._set_cognitive_action_plan(
            frame,
            should_speak=True,
            speech_intent="re_engagement",
            speech_act="reengagement",
            reason="Re-engagement Layer gently reconnects after a long quiet stretch.",
            snapshot=snapshot,
            concrete_signals=(),
            ti_report=ti_report,
            fe_plan=fe_plan,
            notes=("re_engagement", f"quiet_cycles={quiet_cycles}"),
        )
        decision = self.ti_governor.enforce_decision(decision, ti_report)
        decision.parse_mode = "re_engagement"
        decision = self._filter_public_micro_decision(
            decision,
            channel="autonomous",
            frame=frame,
            snapshot=snapshot,
            speech_core=getattr(frame, "speech_core", None),
        )
        if not bool(getattr(decision, "should_speak", True)) or not str(getattr(decision, "text", "") or "").strip():
            return False
        self.fe_style_memory = self.fe_renderer.remember_style(
            self.fe_style_memory,
            plan=fe_plan,
            rendered_text=decision.text,
        )
        self.last_text = decision.text
        self.last_autonomous_spoken_at = now
        self._note_autonomous_spoken(reengagement=True, now=now)
        self._apply_position_update(decision)
        frame.final_decision = self._decision_to_frame_dict(decision)
        self._set_cognitive_memory_update(frame, decision=decision, notes=("re_engagement",))
        self._commit_internal_state_for_frame(frame, snapshot=snapshot, ti_report=ti_report)
        self._finalize_cognitive_frame(frame)
        self.logger.info(
            '[re_engagement] text="%s" | quiet_cycles=%d',
            decision.text,
            quiet_cycles,
        )
        self._send_decision_to_body(decision)

        elapsed = time.time() - cycle_start
        sleep_duration = self._choose_autonomous_sleep_duration(
            suppressed=False,
            ti_mode=getattr(ti_report, "mode", ""),
        )
        self.logger.info("Hoàn tất chu kỳ re-engagement trong %.2fs. Nghỉ %ss.", elapsed, sleep_duration)
        self._sleep_interruptible(sleep_duration)
        return True


    def _load_presence_maintenance_enabled(self) -> bool:
        flag = os.environ.get("ERIS_PRESENCE_MAINTENANCE", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_presence_maintenance_silent_loop_threshold(self) -> int:
        raw = os.environ.get("ERIS_PRESENCE_MAINTENANCE_SILENT_LOOPS", "1").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    def _load_presence_maintenance_cooldown(self) -> float:
        raw = os.environ.get("ERIS_PRESENCE_MAINTENANCE_COOLDOWN_SEC", "12").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 12.0

    def _load_micro_presence_llm_enabled(self) -> bool:
        flag = os.environ.get("ERIS_MICRO_PRESENCE_LLM", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_micro_presence_llm_probability(self) -> float:
        raw = os.environ.get("ERIS_MICRO_PRESENCE_LLM_PROBABILITY", "0.85").strip()
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            return 0.85

    def _load_reengagement_enabled(self) -> bool:
        flag = os.environ.get("ERIS_REENGAGEMENT", "1").strip().lower()
        return flag not in {"0", "false", "no", "off"}

    def _load_reengagement_quiet_loop_threshold(self) -> int:
        raw = os.environ.get("ERIS_REENGAGEMENT_QUIET_LOOPS", "1").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    def _load_reengagement_min_idle(self) -> float:
        raw = os.environ.get("ERIS_REENGAGEMENT_MIN_IDLE_SEC", "45").strip()
        try:
            return max(20.0, float(raw))
        except ValueError:
            return 45.0

    def _load_reengagement_cooldown(self) -> float:
        raw = os.environ.get("ERIS_REENGAGEMENT_COOLDOWN_SEC", "45").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 45.0
