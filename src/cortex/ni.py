import json
import os
import re
import time
import unicodedata

from .contracts import GoalDriftReport, TelemetrySnapshot


DEFAULT_FOCUS_BIAS = {
    "coding": {"bias": 0.10, "scale": 1.0},
    "documentation": {"bias": 0.08, "scale": 1.0},
    "communication": {"bias": 0.04, "scale": 1.0},
    "system": {"bias": 0.02, "scale": 1.0},
    "general": {"bias": 0.0, "scale": 1.0},
    "entertainment": {"bias": -0.06, "scale": 1.0},
}


def _normalize_for_tokens(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9#\s]+", " ", normalized)
    return " ".join(normalized.split())


def _load_focus_bias_table() -> dict[str, dict[str, float]]:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(project_root, "ni_focus_config.json")

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}

    table: dict[str, dict[str, float]] = {}
    if isinstance(data, dict):
        for kind, cfg in data.items():
            if not isinstance(cfg, dict):
                continue
            try:
                bias = float(cfg.get("bias", 0.0) or 0.0)
            except (TypeError, ValueError):
                bias = 0.0
            try:
                scale = float(cfg.get("scale", 1.0) or 1.0)
            except (TypeError, ValueError):
                scale = 1.0
            table[str(kind)] = {"bias": bias, "scale": scale}

    for kind, cfg in DEFAULT_FOCUS_BIAS.items():
        table.setdefault(kind, cfg)
    return table


FOCUS_BIAS_TABLE = _load_focus_bias_table()


class NiEngine:
    def __init__(self):
        pass

    def evaluate_autonomous(
        self,
        *,
        snapshot: TelemetrySnapshot,
        long_term_memory: list[str],
        last_text: str,
    ) -> GoalDriftReport:
        recent_signals = long_term_memory[-6:]
        channels = {
            "focus": snapshot.focus_summary or "",
            "window": snapshot.active_window or "",
            "browsing": " ".join(
                part
                for part in (
                    snapshot.browser_url,
                    " ".join(snapshot.browser_tabs[:4]),
                )
                if part
            ),
            "memory": " ".join(recent_signals),
            "current": last_text or "",
        }
        return self._analyze(snapshot=snapshot, channels=channels)

    def evaluate_chat(
        self,
        *,
        snapshot: TelemetrySnapshot,
        long_term_memory: list[str],
        user_text: str,
    ) -> GoalDriftReport:
        recent_signals = long_term_memory[-6:]
        channels = {
            "focus": snapshot.focus_summary or "",
            "window": snapshot.active_window or "",
            "browsing": " ".join(
                part
                for part in (
                    snapshot.browser_url,
                    " ".join(snapshot.browser_tabs[:4]),
                )
                if part
            ),
            "memory": " ".join(recent_signals),
            "current": user_text or "",
        }
        return self._analyze(snapshot=snapshot, channels=channels)

    def _analyze(
        self,
        *,
        snapshot: TelemetrySnapshot,
        channels: dict[str, str],
    ) -> GoalDriftReport:
        raw_similarity, signal_channels, evidence = self._estimate_attention_signal(
            snapshot=snapshot,
            channels=channels,
        )
        similarity = self._adjust_similarity(raw_similarity, focus_kind=snapshot.active_window_kind)
        drift_score = max(0.0, min(1.0, 1.0 - similarity))
        drift_level = self._label_drift(drift_score)

        self._log_drift_sample(
            focus_kind=snapshot.active_window_kind,
            raw_similarity=raw_similarity,
            drift_score=drift_score,
            should_raise_guard=drift_score >= 0.55,
            channels=signal_channels,
        )

        return GoalDriftReport(
            similarity=similarity,
            drift_score=drift_score,
            drift_level=drift_level,
            prompt_context=self._build_prompt_context(
                similarity=similarity,
                drift_score=drift_score,
                drift_level=drift_level,
                evidence=evidence,
            ),
            evidence=tuple(evidence),
            should_raise_guard=drift_score >= 0.55,
            vector_method="attention_signal_local",
        )

    def _estimate_attention_signal(
        self,
        *,
        snapshot: TelemetrySnapshot,
        channels: dict[str, str],
    ) -> tuple[float, dict[str, float], list[str]]:
        combined = " ".join(
            part
            for part in (
                channels.get("focus", ""),
                channels.get("window", ""),
                channels.get("browsing", ""),
                channels.get("memory", ""),
                channels.get("current", ""),
            )
            if part
        )
        normalized = _normalize_for_tokens(combined)
        kind = snapshot.active_window_kind or "general"

        signal = self._focus_kind_baseline(kind)
        signal_channels: dict[str, float] = {"baseline": signal}
        evidence = [f"focus_kind={kind}", f"baseline={signal:.2f}"]

        text_adjust = self._focus_text_adjustment(normalized, focus_kind=kind)
        if text_adjust:
            signal += text_adjust
            signal_channels["text"] = max(0.0, min(1.0, signal))
            evidence.append(f"text_adjust={text_adjust:+.2f}")

        idle_adjust = self._idle_adjustment(snapshot.idle_seconds, focus_kind=kind)
        if idle_adjust:
            signal += idle_adjust
            signal_channels["idle"] = max(0.0, min(1.0, signal))
            evidence.append(f"idle_adjust={idle_adjust:+.2f}")

        window_adjust = self._window_sprawl_adjustment(len(snapshot.open_windows), focus_kind=kind)
        if window_adjust:
            signal += window_adjust
            signal_channels["window_sprawl"] = max(0.0, min(1.0, signal))
            evidence.append(f"window_adjust={window_adjust:+.2f}")

        resource_adjust = self._resource_adjustment(snapshot.cpu_percent, snapshot.ram_percent)
        if resource_adjust:
            signal += resource_adjust
            signal_channels["resources"] = max(0.0, min(1.0, signal))
            evidence.append(f"resource_adjust={resource_adjust:+.2f}")

        raw_similarity = max(0.0, min(1.0, signal))
        evidence.append(f"attention_signal={raw_similarity:.2f}")
        return raw_similarity, signal_channels, evidence

    def _focus_kind_baseline(self, focus_kind: str) -> float:
        mapping = {
            "coding": 0.80,
            "documentation": 0.76,
            "communication": 0.62,
            "system": 0.58,
            "general": 0.46,
            "entertainment": 0.22,
        }
        return mapping.get(focus_kind or "", 0.46)

    def _focus_text_adjustment(self, normalized: str, *, focus_kind: str) -> float:
        positive_terms = (
            "code", "coding", "project", "source", "bug", "debug", "fix",
            "terminal", "commit", "review", "python", "godot", "vscode",
            "cursor", "visual studio", "documentation", "docs", "readme",
            "api", "stack overflow", "github",
        )
        negative_terms = (
            "youtube", "netflix", "steam", "game", "gaming", "tiktok",
            "reel", "shorts", "anime", "movie", "manga",
        )
        communication_terms = (
            "zalo", "messenger", "facebook", "discord", "slack", "teams",
            "telegram", "gmail", "mail", "meeting", "meet", "chat",
        )

        adjust = 0.0
        if any(term in normalized for term in positive_terms):
            adjust += 0.08
        if any(term in normalized for term in negative_terms):
            adjust -= 0.14
        if any(term in normalized for term in communication_terms):
            adjust += 0.04 if focus_kind == "communication" else 0.02
        return adjust

    def _idle_adjustment(self, idle_seconds: float, *, focus_kind: str) -> float:
        idle = float(idle_seconds or 0.0)
        if focus_kind == "communication":
            if idle >= 900:
                return -0.14
            if idle >= 300:
                return -0.08
            return 0.0
        if idle >= 900:
            return -0.22
        if idle >= 300:
            return -0.14
        if idle >= 60:
            return -0.06
        return 0.0

    def _window_sprawl_adjustment(self, open_window_count: int, *, focus_kind: str) -> float:
        if focus_kind == "communication":
            return 0.0
        if open_window_count >= 10:
            return -0.10
        if open_window_count >= 7:
            return -0.05
        return 0.0

    def _resource_adjustment(self, cpu_percent: float, ram_percent: float) -> float:
        if cpu_percent >= 92 or ram_percent >= 94:
            return -0.06
        if cpu_percent >= 85 or ram_percent >= 90:
            return -0.03
        return 0.0

    def _adjust_similarity(self, raw_similarity: float, *, focus_kind: str) -> float:
        config = FOCUS_BIAS_TABLE.get(focus_kind, {"bias": 0.0, "scale": 1.0})
        try:
            bias = float(config.get("bias", 0.0) or 0.0)
        except (TypeError, ValueError):
            bias = 0.0
        try:
            scale = float(config.get("scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        adjusted = raw_similarity * scale + bias
        return max(0.0, min(1.0, adjusted))

    def _label_drift(self, drift_score: float) -> str:
        if drift_score >= 0.75:
            return "nghiem trong"
        if drift_score >= 0.55:
            return "cao"
        if drift_score >= 0.35:
            return "vua"
        return "thap"

    def _build_prompt_context(
        self,
        *,
        similarity: float,
        drift_score: float,
        drift_level: str,
        evidence: list[str],
    ) -> str:
        lines = [
            "Phân tích Ni hiện tại.",
            f"Tín hiệu chú ý hiện tại: {similarity:.2f}.",
            f"Mức chệch nhịp quan sát: {drift_score:.2f} ({drift_level}).",
        ]
        if evidence:
            lines.append(f"Bằng chứng: {' | '.join(evidence[:4])}.")
        lines.append("Chỉ dùng nó như nền cảnh quan sát, không biến thành bài chấm hiệu suất.")
        return "\n".join(lines)

    def _log_drift_sample(
        self,
        *,
        focus_kind: str,
        raw_similarity: float,
        drift_score: float,
        should_raise_guard: bool,
        channels: dict[str, float],
    ) -> None:
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            log_path = os.path.join(project_root, "ni_drift_samples.jsonl")
            payload = {
                "focus_kind": focus_kind or "unknown",
                "raw_similarity": float(raw_similarity),
                "drift_score": float(drift_score),
                "should_raise_guard": bool(should_raise_guard),
                "channels": {str(name): float(score) for name, score in (channels or {}).items()},
            }
            with open(log_path, "a", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
        except Exception:
            return


class NiStateMachine:
    def __init__(
        self,
        *,
        window_seconds: float = 600.0,
        borderline_threshold: float = 0.35,
        off_goal_threshold: float = 0.65,
        max_recent: int = 120,
    ) -> None:
        self.window_seconds = window_seconds
        self.borderline_threshold = borderline_threshold
        self.off_goal_threshold = off_goal_threshold
        self.max_recent = max_recent
        self._recent_scores: list[tuple[float, float]] = []
        self.current_state: str = "ON_GOAL"
        self.streak_length: int = 0

    def update(
        self,
        *,
        snapshot: TelemetrySnapshot,
        report: GoalDriftReport,
    ) -> dict[str, object]:
        now = time.time()
        self._recent_scores.append((now, report.drift_score))
        cutoff = now - self.window_seconds
        self._recent_scores = [(t, s) for (t, s) in self._recent_scores if t >= cutoff][-self.max_recent :]

        recent_values = [s for (_t, s) in self._recent_scores[-5:]]
        avg_recent = sum(recent_values) / len(recent_values) if recent_values else report.drift_score

        if avg_recent >= self.off_goal_threshold:
            state = "OFF_GOAL"
        elif avg_recent >= self.borderline_threshold:
            state = "BORDERLINE"
        else:
            state = "ON_GOAL"

        if snapshot.active_window_kind == "entertainment" and state == "ON_GOAL":
            state = "BORDERLINE"

        if state == self.current_state:
            self.streak_length += 1
        else:
            self.current_state = state
            self.streak_length = 1

        return {
            "discrete_state": self.current_state,
            "streak_length": self.streak_length,
            "average_recent_drift": avg_recent,
            "samples_in_window": len(self._recent_scores),
        }
