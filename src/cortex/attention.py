import re
import unicodedata

from .contracts import AttentionCandidate, CognitiveBroadcast, PerceptEvent

'''File attention.py là “bộ chọn chú ý” (attention selector): nó nhận một danh sách PerceptEvent 
(các tín hiệu như user_message, active_window, recent_event, vision_fact…), chấm điểm từng cái, 
lấy top-N, rồi tạo ra một CognitiveBroadcast (tóm tắt tín hiệu nổi bật nhất để downstream dùng)'''
def _bounded(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _normalize_tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9_\s]+", " ", normalized)
    stop_words = {
        "a",
        "an",
        "and",
        "at",
        "cua",
        "dang",
        "for",
        "in",
        "is",
        "la",
        "of",
        "on",
        "the",
        "to",
        "toi",
        "trong",
        "va",
    }
    return {token for token in normalized.split() if len(token) >= 3 and token not in stop_words}


def _normalize_for_bias(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("đ", "d")
    normalized = re.sub(r"[^a-z0-9_#\s]+", " ", normalized)
    return " ".join(normalized.split())


class AttentionWorkspace:
    SCORE_KEYS = (
        "novelty",
        "specificity",
        "user_relevance",
        "risk",
        "social_charge",
        "recency",
        "memory_resonance",
        "personality_bias",
    )
    WEIGHTS = {
        "novelty": 0.16,
        "specificity": 0.14,
        "user_relevance": 0.18,
        "risk": 0.14,
        "social_charge": 0.10,
        "recency": 0.08,
        "memory_resonance": 0.08,
        "personality_bias": 0.12,
    }
    RISK_TERMS = (
        "crash",
        "cpu",
        "error",
        "exception",
        "failed",
        "ram",
        "traceback",
        "warning",
        "loi",
        "lỗi",
    )
    SOCIAL_TERMS = (
        "chat",
        "discord",
        "dm",
        "mail",
        "message",
        "messenger",
        "slack",
        "zalo",
        "tin nhan",
        "tin nhắn",
    )
    PERSONALITY_BIAS_TERMS = {
        "hesitation": (
            "hesitation",
            "hesitant",
            "hover",
            "hovering",
            "pause",
            "paused",
            "pausing",
            "stalled",
            "stuck",
            "khung lai",
            "luong lu",
            "ngap ngung",
        ),
        "mood_shift": (
            "angry",
            "rage",
            "resigned",
            "sigh",
            "heavy_sigh",
            "tired",
            "sad",
            "stress",
            "buc",
            "buon",
            "cam chiu",
            "met",
        ),
        "avoidance": (
            "avoid",
            "avoidance",
            "hiding",
            "minimize",
            "minimizing",
            "panic",
            "fragmented",
            "absent",
            "switching",
            "tranh",
        ),
        "continuity": (
            "again",
            "repeat",
            "repeated",
            "resume",
            "continuity",
            "memory",
            "unresolved",
            "loop",
            "momentum",
            "lap lai",
        ),
        "emotional_undertone": (
            "attachment",
            "lonely",
            "connection",
            "voice_call",
            "message",
            "social",
            "fear",
            "quiet",
            "co don",
            "tam trang",
        ),
        "unfinished_intention": (
            "unfinished",
            "intention",
            "draft",
            "deleting",
            "half",
            "blank",
            "no_edits",
            "no_typing",
            "typing_and_deleting",
            "hovering_voice_call",
            "dang do",
            "chua xong",
        ),
    }

    CURRENT_SIGNAL_LABELS = {
        "user_message",
        "user_force_speak",
        "vision_fact",
        "resource_pressure",
        "norm_deviation",
        "cognitive_attractor",
        "substrate_disturbance",
        "persistent_goal",
        "recent_event",
        "evidence",
    }

    def __init__(
        self,
        *,
        broadcast_threshold: float = 0.50,
        secondary_margin: float = 0.14,
        max_candidates: int = 6,
        max_winners: int = 3,
    ):
        self.broadcast_threshold = broadcast_threshold
        self.secondary_margin = secondary_margin
        self.max_candidates = max_candidates
        self.max_winners = max_winners

    def select(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
        long_term_memory: tuple[str, ...] | list[str] = (),
    ) -> tuple[tuple[AttentionCandidate, ...], CognitiveBroadcast]:
        candidates = self.rank(
            percepts,
            channel=channel,
            snapshot=snapshot,
            user_text=user_text,
            long_term_memory=long_term_memory,
        )
        return candidates, self.build_broadcast(candidates)

    def rank(
        self,
        percepts: tuple[PerceptEvent, ...],
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
        long_term_memory: tuple[str, ...] | list[str] = (),
    ) -> tuple[AttentionCandidate, ...]:
        candidates = [
            self.score_event(
                percept,
                channel=channel,
                snapshot=snapshot,
                user_text=user_text,
                long_term_memory=long_term_memory,
            )
            for percept in percepts
        ]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return tuple(candidates[: self.max_candidates])

    def build_broadcast(self, candidates: tuple[AttentionCandidate, ...]) -> CognitiveBroadcast:
        if not candidates:
            return CognitiveBroadcast(reason="attention_workspace:no_percepts")

        current_winners = tuple(
            candidate
            for candidate in candidates
            if candidate.label in self.CURRENT_SIGNAL_LABELS and candidate.score >= self.broadcast_threshold
        )
        pool = current_winners if current_winners else candidates
        top = pool[0]
        winners: list[AttentionCandidate] = []
        for candidate in pool:
            if candidate.label == "cycle_channel":
                continue
            if candidate.score < self.broadcast_threshold:
                continue
            if top.score - candidate.score > self.secondary_margin:
                continue
            winners.append(candidate)
            if len(winners) >= self.max_winners:
                break

        if not winners:
            return CognitiveBroadcast(
                label="low_salience",
                content="",
                score=top.score,
                source=top.source,
                reason=(
                    "attention_workspace:top_below_threshold; "
                    f"top={top.label}:{top.score:.2f}"
                ),
            )

        primary = winners[0]
        return CognitiveBroadcast(
            label=primary.label,
            content=" | ".join(item.content for item in winners),
            score=primary.score,
            source=primary.source,
            reason=(
                "attention_workspace:winners="
                + ",".join(f"{item.label}:{item.score:.2f}" for item in winners)
            ),
            evidence=tuple(dict.fromkeys(item for winner in winners for item in winner.evidence))[:6],
            items=tuple(winners),
        )

    def score_event(
        self,
        percept: PerceptEvent,
        *,
        channel: str = "",
        snapshot=None,
        user_text: str = "",
        long_term_memory: tuple[str, ...] | list[str] = (),
    ) -> AttentionCandidate:
        parts = {
            "novelty": self._score_novelty(percept),
            "specificity": self._score_specificity(percept),
            "user_relevance": self._score_user_relevance(
                percept,
                channel=channel,
                snapshot=snapshot,
                user_text=user_text,
            ),
            "risk": self._score_risk(percept),
            "social_charge": self._score_social_charge(percept, snapshot=snapshot),
            "recency": self._score_recency(percept),
            "memory_resonance": self._score_memory_resonance(percept, long_term_memory),
            "personality_bias": self._score_personality_bias(percept, snapshot=snapshot),
        }
        raw_score = sum(parts[key] * self.WEIGHTS[key] for key in self.SCORE_KEYS)
        confidence_scale = 0.75 + 0.25 * _bounded(percept.confidence, minimum=0.05, maximum=1.0)
        score = _bounded(raw_score * confidence_scale)
        reason = "; ".join(f"{key}={parts[key]:.2f}" for key in self.SCORE_KEYS)
        return AttentionCandidate(
            label=percept.kind,
            content=percept.content,
            score=score,
            source=percept.source,
            reason=reason,
            evidence=percept.evidence,
            privacy_level=percept.privacy_level,
            novelty_hint=percept.novelty_hint,
            score_parts={key: round(parts[key], 3) for key in self.SCORE_KEYS},
        )

    def _score_novelty(self, percept: PerceptEvent) -> float:
        hint = (percept.novelty_hint or "").lower()
        if hint in {"direct_user_input", "explicit_request"}:
            return 1.0
        if hint in {"input_disturbance"} or percept.kind == "substrate_disturbance":
            return 0.74
        if hint in {"new_screen_fact", "threshold_crossed"}:
            return 0.92
        if hint in {"baseline_deviation"}:
            return 0.84
        if hint in {"cognitive_attractor"} or percept.kind == "cognitive_attractor":
            return 0.92
        if hint in {"cognitive_momentum"} or percept.kind == "cognitive_momentum":
            return 0.86
        if hint in {"persistent_goal"} or percept.kind == "persistent_goal":
            return 0.80
        if hint in {"presence_background"} or percept.kind == "social_presence_event":
            return 0.18
        if hint in {"session_resume"} or percept.kind == "session_ritual":
            return 0.38
        if hint in {"concrete_telemetry", "duration_threshold"}:
            return 0.72
        if hint in {"screen_fact"}:
            return 0.66
        if hint in {"cached_screen_fact", "repeated_screen_fact"}:
            return 0.34
        if hint in {"routine_telemetry", "ambient_context", "cycle_marker", "none"}:
            return 0.16
        return 0.30

    def _score_specificity(self, percept: PerceptEvent) -> float:
        if percept.kind == "cycle_channel":
            return 0.05
        if percept.kind == "social_presence_event":
            return 0.18
        if percept.kind == "session_ritual":
            return 0.32
        if percept.kind == "cognitive_attractor":
            score = 0.74
            if percept.evidence:
                score += 0.12
            if "topic=" in percept.content or "loop=" in percept.content:
                score += 0.08
            return _bounded(score)
        if percept.kind == "cognitive_momentum":
            score = 0.62
            if percept.evidence:
                score += 0.12
            if "topic=" in percept.content or "thought=" in percept.content:
                score += 0.08
            return _bounded(score)
        if percept.kind == "persistent_goal":
            score = 0.66
            if percept.evidence:
                score += 0.12
            if "goal=" in percept.content:
                score += 0.08
            return _bounded(score)
        if percept.kind == "substrate_disturbance":
            return 0.50 + (0.12 if percept.evidence else 0.0)
        if percept.kind in {"active_window", "focus_context"}:
            return 0.18
        tokens = _normalize_tokens(percept.content)
        score = 0.25 + min(0.45, len(tokens) * 0.045)
        if percept.evidence:
            score += 0.12
        if any(char.isdigit() for char in percept.content):
            score += 0.08
        if percept.kind == "vision_fact":
            score += 0.18
        elif percept.kind == "resource_pressure":
            score += 0.10
        elif percept.kind == "norm_deviation":
            score += 0.10
        return _bounded(score)

    def _score_user_relevance(self, percept: PerceptEvent, *, channel: str, snapshot=None, user_text: str = "") -> float:
        if percept.kind in {"user_message", "user_force_speak"}:
            return 1.0
        if percept.kind == "substrate_disturbance":
            return 0.72
        if percept.kind == "cognitive_attractor":
            return 0.90
        if percept.kind == "cognitive_momentum":
            return 0.82
        if percept.kind == "persistent_goal":
            return 0.86
        if percept.kind == "social_presence_event":
            return 0.20
        if percept.kind == "session_ritual":
            return 0.38
        if channel in {"chat", "force_speak"} and percept.kind in {"vision_fact", "recent_event", "evidence"}:
            return 0.68
        if percept.kind == "resource_pressure":
            return 0.70
        if percept.kind == "vision_fact":
            return 0.70
        if percept.kind == "norm_deviation":
            return 0.45
        if percept.kind in {"recent_event", "evidence"}:
            return 0.50
        if percept.kind in {"active_window", "focus_context"}:
            return 0.18

        content_tokens = _normalize_tokens(percept.content)
        user_tokens = _normalize_tokens(user_text)
        if content_tokens and user_tokens:
            overlap = len(content_tokens & user_tokens) / max(1, len(user_tokens))
            return _bounded(0.30 + overlap * 0.55)
        return 0.25

    def _score_risk(self, percept: PerceptEvent) -> float:
        lowered = percept.content.lower()
        if percept.kind == "resource_pressure":
            return 0.95
        if percept.kind == "cognitive_attractor":
            return 0.10
        if percept.kind == "cognitive_momentum":
            return 0.08
        if percept.kind == "persistent_goal":
            return 0.06
        if percept.kind == "social_presence_event":
            return 0.02
        if percept.kind == "session_ritual":
            return 0.02
        if percept.kind == "substrate_disturbance":
            return 0.12
        if any(term in lowered for term in self.RISK_TERMS):
            return 0.78
        if percept.kind == "idle_state" and "600" in lowered:
            return 0.42
        return 0.05

    def _score_social_charge(self, percept: PerceptEvent, *, snapshot=None) -> float:
        lowered = percept.content.lower()
        kind = str(getattr(snapshot, "active_window_kind", "") or "")
        if percept.kind == "user_message":
            return 0.70
        if percept.kind == "substrate_disturbance":
            return 0.42
        if percept.kind == "cognitive_attractor":
            return 0.34
        if percept.kind == "cognitive_momentum":
            return 0.30
        if percept.kind == "persistent_goal":
            return 0.32
        if percept.kind == "social_presence_event":
            return 0.16
        if percept.kind == "session_ritual":
            return 0.20
        if kind == "communication":
            return 0.42
        if any(term in lowered for term in self.SOCIAL_TERMS):
            return 0.54
        return 0.05

    def _score_recency(self, percept: PerceptEvent) -> float:
        hint = (percept.novelty_hint or "").lower()
        if hint in {"direct_user_input", "explicit_request", "new_screen_fact", "threshold_crossed"}:
            return 0.90
        if hint in {"input_disturbance"} or percept.kind == "substrate_disturbance":
            return 0.78
        if hint in {"baseline_deviation"}:
            return 0.82
        if hint in {"cognitive_attractor"} or percept.kind == "cognitive_attractor":
            return 0.88
        if hint in {"cognitive_momentum"} or percept.kind == "cognitive_momentum":
            return 0.84
        if hint in {"persistent_goal"} or percept.kind == "persistent_goal":
            return 0.78
        if hint in {"presence_background"} or percept.kind == "social_presence_event":
            return 0.22
        if hint in {"session_resume"} or percept.kind == "session_ritual":
            return 0.42
        if hint in {"concrete_telemetry", "duration_threshold", "screen_fact"}:
            return 0.72
        if hint in {"cached_screen_fact", "repeated_screen_fact"}:
            return 0.34
        if hint in {"ambient_context", "routine_telemetry", "cycle_marker"}:
            return 0.18
        return 0.35

    def _score_memory_resonance(
        self,
        percept: PerceptEvent,
        long_term_memory: tuple[str, ...] | list[str],
    ) -> float:
        content_tokens = _normalize_tokens(" ".join((percept.content, *percept.evidence)))
        if not content_tokens:
            return 0.0
        best = 0.0
        for raw_memory in (long_term_memory or ())[-12:]:
            memory = str(raw_memory or "")
            memory_tokens = _normalize_tokens(memory)
            if not memory_tokens:
                continue
            overlap = len(content_tokens & memory_tokens)
            if overlap <= 0:
                continue
            layer_weight = self._memory_layer_weight(memory)
            score = (overlap / max(4, min(len(content_tokens), 12))) * layer_weight
            if "active_memory_resonance/" in memory:
                score += self._extract_resonance_score(memory) * 0.24
            best = max(best, score)
        return _bounded(best)

    def _score_personality_bias(self, percept: PerceptEvent, *, snapshot=None) -> float:
        text_parts = [
            str(percept.content or ""),
            " ".join(str(item) for item in (percept.evidence or ())),
            str(percept.kind or ""),
            str(percept.novelty_hint or ""),
        ]
        if snapshot is not None:
            user_signals = getattr(snapshot, "user_signals", None)
            text_parts.extend(
                (
                    str(getattr(snapshot, "focus_summary", "") or ""),
                    str(getattr(snapshot, "mood_label", "") or ""),
                    " ".join(str(item) for item in (getattr(snapshot, "recent_events", ()) or ())),
                    str(getattr(user_signals, "typing_speed", "") if user_signals is not None else ""),
                    str(getattr(user_signals, "window_switching", "") if user_signals is not None else ""),
                    str(getattr(user_signals, "focus_pattern", "") if user_signals is not None else ""),
                )
            )
        normalized = _normalize_for_bias(" ".join(part for part in text_parts if part))
        if not normalized:
            return 0.0

        hits: list[str] = []
        if percept.kind == "persistent_goal":
            hits.append("continuity")
        for category, terms in self.PERSONALITY_BIAS_TERMS.items():
            if any(term in normalized for term in terms):
                hits.append(category)
        if not hits:
            return 0.0

        score = 0.38 + min(0.42, len(hits) * 0.12)
        if percept.kind in {"cognitive_momentum", "cognitive_attractor"} and "continuity" in hits:
            score += 0.18
        if percept.kind in {"user_message", "user_force_speak"}:
            score += 0.10
        if percept.kind in {"recent_event", "vision_fact", "substrate_disturbance"}:
            score += 0.08
        return _bounded(score)

    def _memory_layer_weight(self, memory: str) -> float:
        lowered = (memory or "").lower()
        if "active_memory_resonance/working" in lowered or lowered.startswith("working:"):
            return 1.10
        if "active_memory_resonance/procedural" in lowered or lowered.startswith("procedural"):
            return 1.06
        if "active_memory_resonance/relationship" in lowered or lowered.startswith("relationship/"):
            return 1.00
        if "active_memory_resonance/episodic" in lowered or lowered.startswith("episodic:"):
            return 0.96
        if "active_memory_resonance/semantic" in lowered or lowered.startswith("semantic/"):
            return 0.90
        return 0.82

    def _extract_resonance_score(self, memory: str) -> float:
        match = re.search(r"\bscore=([0-9.]+)", memory or "")
        if not match:
            return 0.0
        try:
            return _bounded(float(match.group(1)))
        except ValueError:
            return 0.0
