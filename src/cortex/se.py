import json
import os
import re
from urllib.parse import urlparse

from .contracts import TelemetrySnapshot, UserSignals


class SeLens:
    _GENERIC_PROMPT_EVENTS = {
        "coding_window_active",
        "reference_window_active",
        "communication_window_active",
        "entertainment_window_active",
        "focus_aid_media_window_active",
        "general_window_active",
        "browser_url_visible",
        "many_browser_tabs_visible",
        "many_windows_open",
        "long_idle_period",
        "system_monitoring_visible",
    }

    _CODING_KEYWORDS = (
        "visual studio code",
        "vscode",
        "visual studio",
        "rider",
        "pycharm",
        "intellij",
        "godot",
        "terminal",
        "powershell",
        "cmd.exe",
        "git bash",
    )
    _DOC_KEYWORDS = (
        "docs",
        "documentation",
        "readme",
        "stackoverflow",
        "stack overflow",
        "developer.mozilla",
        "learn.microsoft",
        "python.org",
    )
    _COMMUNICATION_KEYWORDS = (
        "discord",
        "telegram",
        "slack",
        "messenger",
        "outlook",
        "zalo",
        "zoom",
        "teams",
        "meet",
    )
    _ENTERTAINMENT_KEYWORDS = (
        "netflix",
        "steam",
        "game",
        "twitch",
    )
    _BROWSER_SURFACE_KEYWORDS = (
        "chrome",
        "firefox",
        "edge",
        "brave",
        "opera",
        "browser",
    )
    _WEAK_CONTEXT_HINT_RULES = (
        (("youtube", "youtu.be"), "youtube visible"),
        (("tiktok",), "tiktok visible"),
        (("reddit",), "reddit visible"),
        (("gmail", "mail.google"), "gmail visible"),
        (("github",), "github visible"),
        (
            ("stackoverflow", "stack overflow", "developer.mozilla", "learn.microsoft", "python.org"),
            "reference docs visible",
        ),
    )

    _CLAIM_STYLE_ALIASES = {
        "direct_fact": "DIRECT_FACT",
        "observed_pattern": "OBSERVED_PATTERN",
        "weak_impression": "WEAK_IMPRESSION",
        "forbidden_inference": "FORBIDDEN_INFERENCE",
        "soft_grounded": "OBSERVED_PATTERN",
        "grounded": "OBSERVED_PATTERN",
        "idle_self_reflection": "OBSERVED_PATTERN",
        "game_observation": "OBSERVED_PATTERN",
        "no_evidence_refusal": "WEAK_IMPRESSION",
        "idle_silence_boundary": "WEAK_IMPRESSION",
        "uncertainty": "WEAK_IMPRESSION",
        "soft_claim": "WEAK_IMPRESSION",
    }

    def __init__(self):
        self._context_overrides = self._load_context_overrides()

    #raw dict vào, snapshot có nghĩa đi ra.
    def build_snapshot(self, raw: dict) -> TelemetrySnapshot:
        active_window = str(raw.get("active_window", "") or raw.get("active_app", "") or "Desktop")
        active_app = str(raw.get("active_app", "") or active_window)
        browser_url = str(raw.get("browser_url", "") or "")
        browser_tabs = self._normalize_string_tuple(raw.get("browser_tabs", ()))
        open_windows = self._normalize_string_tuple(raw.get("open_windows", ()))
        #Phân loại bối cảnh
        active_window_kind = self._classify_window_kind(active_window, browser_url, browser_tabs)
        idle_seconds = float(raw.get("idle_seconds", 0.0) or 0.0)
        cpu_percent = float(raw.get("cpu_percent", 0.0) or 0.0)
        ram_percent = float(raw.get("ram_percent", 0.0) or 0.0)
        recent_events = self._build_recent_events(
            raw=raw,
            active_app=active_app,
            active_window_kind=active_window_kind,
            browser_url=browser_url,
            browser_tabs=browser_tabs,
            open_windows=open_windows,
            idle_seconds=idle_seconds,
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
        )
        user_signals = self._build_user_signals(
            raw=raw,
            active_window_kind=active_window_kind,
            idle_seconds=idle_seconds,
            browser_tabs=browser_tabs,
            open_windows=open_windows,
        )
        evidence = self._build_evidence(
            raw=raw,
            active_app=active_app,
            active_window_kind=active_window_kind,
            browser_url=browser_url,
            browser_tabs=browser_tabs,
            open_windows=open_windows,
            idle_seconds=idle_seconds,
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            recent_events=recent_events,
        )
        claim_style = self._build_claim_style(
            raw=raw,
            active_window_kind=active_window_kind,
            idle_seconds=idle_seconds,
            evidence=evidence,
        )
        ambient_seed = int(raw.get("ambient_tone_score", raw.get("mood_score", 50)) or 50)

        return TelemetrySnapshot(
            captured_at=str(raw.get("captured_at", "") or raw.get("time", "") or ""),
            active_window=active_window,
            active_window_kind=active_window_kind,
            focus_summary=self._focus_summary_for_kind(active_window_kind, active_app, browser_url),
            active_app=active_app,
            browser_url=browser_url,
            browser_tabs=browser_tabs,
            open_windows=open_windows,
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            ambient_tone=self._label_ambient_tone(ambient_seed),
            tease_bias=self._label_tease_bias(ambient_seed),
            inferred_pos_x=float(raw.get("inferred_pos_x", 0.5) or 0.5),
            position_label=self._label_position(float(raw.get("inferred_pos_x", 0.5) or 0.5)),
            idle_seconds=idle_seconds,
            idle_label=self._label_idle(idle_seconds),
            recent_events=recent_events,
            user_signals=user_signals,
            evidence=evidence,
            claim_style=claim_style,
            vision_facts=self._normalize_string_tuple(raw.get("vision_facts", ())),
        )

    def build_machine_context(self, raw: dict) -> dict[str, object]:
        return self.build_snapshot(raw).to_machine_context()

    def _load_context_overrides(self) -> dict[str, tuple[str, ...]]:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        config_path = os.path.join(project_root, "focus_context_config.json")
        defaults = {
            "force_communication": (),
            "focus_aid_media": (),
        }
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return defaults

        if not isinstance(data, dict):
            return defaults

        normalized: dict[str, tuple[str, ...]] = {}
        for key, fallback in defaults.items():
            raw_values = data.get(key, ())
            if not isinstance(raw_values, (list, tuple)):
                normalized[key] = fallback
                continue
            normalized[key] = tuple(
                str(value).strip().lower()
                for value in raw_values
                if str(value).strip()
            )
        return normalized

    def _contains_override(self, haystack: str, key: str) -> bool:
        keywords = self._context_overrides.get(key, ())
        return any(keyword in haystack for keyword in keywords)

    def format_snapshot(self, snapshot: TelemetrySnapshot) -> str:
        machine_context = snapshot.to_machine_context()
        lines = [
            "Machine context observed from runtime.",
            f"- time: {machine_context['time']}",
            f"- active_app: {machine_context['active_app']}",
            f"- active_window_kind: {machine_context['active_window_kind']}",
            f"- focus_summary: {machine_context['focus_summary']}",
            f"- idle_seconds: {machine_context['idle_seconds']}",
            f"- recent_events: {json.dumps(machine_context['recent_events'], ensure_ascii=False)}",
            f"- user_signals: {json.dumps(machine_context['user_signals'], ensure_ascii=False, sort_keys=True)}",
            f"- evidence: {json.dumps(machine_context['evidence'], ensure_ascii=False)}",
            f"- claim_style: {machine_context['claim_style']}",
            f"- browser_url: {machine_context['browser_url'] or ''}",
            f"- browser_tabs: {json.dumps(machine_context['browser_tabs'], ensure_ascii=False)}",
            f"- open_windows: {json.dumps(machine_context['open_windows'], ensure_ascii=False)}",
            f"- cpu_percent: {machine_context['cpu_percent']}",
            f"- ram_percent: {machine_context['ram_percent']}",
            f"- ambient_tone: {machine_context['ambient_tone']}",
            f"- tease_bias: {machine_context['tease_bias']}",
            f"- position: {machine_context['position_label']} ({machine_context['inferred_pos_x']})",
            f"- idle_label: {machine_context['idle_label']}",
        ]
        return "\n".join(lines)

    #tạo context nhẹ cho LLM:
    def format_directive_snapshot(self, snapshot: TelemetrySnapshot) -> str:
        lines = [
            "Ambient cues from runtime. Keep them mostly invisible in the reply.",
            f"- room_feel: {self._describe_prompt_scene(snapshot)}; {self._describe_prompt_pace(snapshot)}",
            f"- human_rhythm: {self._describe_prompt_focus(snapshot)}",
            f"- claim_style: {snapshot.claim_style}", #kiểu phát ngôn an toàn hiện tại từ snapshot
            f"- ambient_tone: {snapshot.ambient_tone}; tease_bias={snapshot.tease_bias}",
            f"- visible_context: {self._format_visible_context(snapshot)}",
        ]
        screen_facts = self._build_prompt_screen_facts(snapshot)
        if screen_facts:
            lines.append(f"- screen_facts: {json.dumps(screen_facts, ensure_ascii=False)}")
        #Gắn thêm cue hướng dẫn giọng và chiến lược trả lời
        cues = self._build_prompt_cues(snapshot) 
        if cues:
            lines.append(f"- cues: {json.dumps(cues, ensure_ascii=False)}")
        return "\n".join(lines)

    def _format_visible_context(self, snapshot: TelemetrySnapshot) -> str:
        app = (snapshot.active_app or snapshot.active_window or "Desktop").strip()
        app = app.replace("\n", " ")
        if len(app) > 96:
            app = app[:93].rstrip() + "..."
        return f"{app} | kind={snapshot.active_window_kind} | idle={snapshot.idle_label}"

    def _is_generic_prompt_event(self, event: str) -> bool:
        normalized = str(event or "").strip().lower()
        return normalized in self._GENERIC_PROMPT_EVENTS or normalized.endswith("_window_active")

    def _is_generic_prompt_evidence(self, evidence: str) -> bool:
        lowered = str(evidence or "").strip().lower()
        if not lowered:
            return True
        generic_prefixes = (
            "active window is ",
            "focus kind is ",
            "there has been no input for ",
            "browser target is visible:",
        )
        if lowered.startswith(generic_prefixes):
            return True
        if re.fullmatch(r"\d+ browser tabs are visible", lowered):
            return True
        if re.fullmatch(r"\d+ windows are open", lowered):
            return True
        if lowered.startswith("recent events include "):
            listed = lowered.removeprefix("recent events include ")
            events = [item.strip() for item in listed.split(",") if item.strip()]
            return bool(events) and all(self._is_generic_prompt_event(item) for item in events)
        return False

    def _build_prompt_screen_facts(self, snapshot: TelemetrySnapshot) -> list[str]:
        facts: list[str] = []
        for item in getattr(snapshot, "vision_facts", ()) or ():
            facts.append(str(item))
        for event in snapshot.recent_events:
            if not self._is_generic_prompt_event(event):
                facts.append(str(event))
        for item in snapshot.evidence:
            if not self._is_generic_prompt_evidence(item):
                facts.append(str(item))
        return facts[:4]

    def _normalize_string_tuple(self, values) -> tuple[str, ...]:
        normalized: list[str] = []
        if not isinstance(values, (list, tuple)):
            return ()
        for value in values:
            if isinstance(value, str):
                item = value.strip()
            else:
                item = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if item:
                normalized.append(item)
        return tuple(normalized)

    def _build_recent_events(
        self,
        *,
        raw: dict,
        active_app: str,
        active_window_kind: str,
        browser_url: str,
        browser_tabs: tuple[str, ...],
        open_windows: tuple[str, ...],
        idle_seconds: float,
        cpu_percent: float,
        ram_percent: float,
    ) -> tuple[str, ...]:
        explicit = self._normalize_string_tuple(raw.get("recent_events", ()))
        if explicit:
            return explicit

        events: list[str] = []
        if active_window_kind == "coding":
            events.append("coding_window_active")
        elif active_window_kind == "documentation":
            events.append("reference_window_active")
        elif active_window_kind == "communication":
            events.append("communication_window_active")
        elif active_window_kind == "focus_aid_media":
            events.append("focus_aid_media_window_active")
        elif active_window_kind == "entertainment":
            events.append("entertainment_window_active")
        else:
            events.append("general_window_active")

        if browser_url:
            events.append("browser_url_visible")
        if len(browser_tabs) >= 4:
            events.append("many_browser_tabs_visible")
        if len(open_windows) >= 7:
            events.append("many_windows_open")
        if idle_seconds >= 300:
            events.append("long_idle_period")
        if "task manager" in active_app.lower():
            events.append("system_monitoring_visible")
        return tuple(events)

    def _build_user_signals(
        self,
        *,
        raw: dict,
        active_window_kind: str,
        idle_seconds: float,
        browser_tabs: tuple[str, ...],
        open_windows: tuple[str, ...],
    ) -> UserSignals:
        explicit = raw.get("user_signals", {})
        if not isinstance(explicit, dict):
            explicit = {}

        typing_speed = str(explicit.get("typing_speed", "") or self._infer_typing_speed(idle_seconds))
        window_switching = str(
            explicit.get("window_switching", "")
            or self._infer_window_switching(len(open_windows), len(browser_tabs))
        )
        focus_pattern = str(
            explicit.get("focus_pattern", "")
            or self._infer_focus_pattern(
                active_window_kind=active_window_kind,
                idle_seconds=idle_seconds,
                open_window_count=len(open_windows),
                browser_tab_count=len(browser_tabs),
            )
        )
        return UserSignals(
            typing_speed=typing_speed,
            window_switching=window_switching,
            focus_pattern=focus_pattern,
        )

    def _infer_typing_speed(self, idle_seconds: float) -> str:
        if idle_seconds < 5:
            return "high"
        if idle_seconds < 30:
            return "moderate"
        if idle_seconds < 90:
            return "low"
        return "zero"

    def _infer_window_switching(self, open_window_count: int, browser_tab_count: int) -> str:
        spread = max(open_window_count, browser_tab_count)
        if spread >= 10:
            return "high"
        if spread >= 6:
            return "moderate"
        return "low"

    def _infer_focus_pattern(
        self,
        *,
        active_window_kind: str,
        idle_seconds: float,
        open_window_count: int,
        browser_tab_count: int,
    ) -> str:
        if active_window_kind in {"coding", "documentation"}:
            if idle_seconds >= 180:
                return "stuck"
            if max(open_window_count, browser_tab_count) >= 8:
                return "fragmented"
            return "deep_work"
        if active_window_kind == "communication":
            return "conversation"
        if active_window_kind == "focus_aid_media":
            if idle_seconds >= 180:
                return "ambient_media"
            if max(open_window_count, browser_tab_count) >= 8:
                return "split_attention"
            return "background_media"
        if active_window_kind == "entertainment":
            if idle_seconds >= 180:
                return "passive_consumption"
            return "active_consumption"
        if idle_seconds >= 300:
            return "absent"
        if max(open_window_count, browser_tab_count) >= 8:
            return "fragmented"
        return "steady"

    #tạo bằng chứng dạng text:
    def _build_evidence(
        self,
        *,
        raw: dict,
        active_app: str,
        active_window_kind: str,
        browser_url: str,
        browser_tabs: tuple[str, ...],
        open_windows: tuple[str, ...],
        idle_seconds: float,
        cpu_percent: float,
        ram_percent: float,
        recent_events: tuple[str, ...],
    ) -> tuple[str, ...]:
        explicit = self._normalize_string_tuple(raw.get("evidence", ()))
        if explicit:
            return explicit

        evidence = [
            f"active window is {active_app}",
            f"focus kind is {active_window_kind}",
            f"there has been no input for {int(idle_seconds)} seconds",
        ]
        if browser_url:
            parsed = urlparse(browser_url)
            browser_target = parsed.netloc or browser_url
            evidence.append(f"browser target is visible: {browser_target}")
        evidence.extend(
            self._build_weak_context_hints(
                active_window=active_app,
                browser_url=browser_url,
                browser_tabs=browser_tabs,
            )
        )
        if browser_tabs:
            evidence.append(f"{len(browser_tabs)} browser tabs are visible")
        if open_windows:
            evidence.append(f"{len(open_windows)} windows are open")
        if recent_events:
            evidence.append(f"recent events include {', '.join(recent_events[:2])}")
        return tuple(dict.fromkeys(evidence))[:8]

    def _build_claim_style(
        self,
        *,
        raw: dict,
        active_window_kind: str,
        idle_seconds: float,
        evidence: tuple[str, ...],
    ) -> str:
        explicit = str(raw.get("claim_style", "") or "").strip()
        if explicit:
            return self._normalize_claim_style(explicit)
        concrete_evidence = self._concrete_evidence(evidence)
        quality_score = self._evidence_quality_score(concrete_evidence)
        if active_window_kind in {"communication", "documentation", "system", "focus_aid_media"} and idle_seconds >= 600:
            return "WEAK_IMPRESSION"
        if not concrete_evidence or quality_score < 1.0:
            return "WEAK_IMPRESSION"
        if len(concrete_evidence) >= 2 and quality_score < 1.6:
            return "WEAK_IMPRESSION"
        if len(concrete_evidence) >= 2 and quality_score >= 2.0:
            return "OBSERVED_PATTERN"
        return "DIRECT_FACT"

    def _normalize_claim_style(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        canonical = normalized.upper()
        if canonical in {"DIRECT_FACT", "OBSERVED_PATTERN", "WEAK_IMPRESSION", "FORBIDDEN_INFERENCE"}:
            return canonical
        return self._CLAIM_STYLE_ALIASES.get(normalized.lower(), "WEAK_IMPRESSION")

    #Phân loại cửa sổ
    def _classify_window_kind(self, active_window: str, browser_url: str, browser_tabs: tuple[str, ...]) -> str:
        active_haystack = str(active_window or "").lower()
        browser_haystack = " | ".join((browser_url, *browser_tabs)).lower()
        combined_haystack = " | ".join(part for part in (active_haystack, browser_haystack) if part)

        if any(keyword in active_haystack for keyword in self._CODING_KEYWORDS):
            return "coding"
        if any(keyword in active_haystack for keyword in self._DOC_KEYWORDS):
            return "documentation"
        if self._contains_override(combined_haystack, "force_communication"):
            return "communication"
        if self._contains_override(combined_haystack, "focus_aid_media"):
            return "focus_aid_media"
        if any(keyword in browser_haystack for keyword in self._DOC_KEYWORDS):
            return "documentation"
        if self._looks_like_browser_surface(active_window, browser_url, browser_tabs):
            return "general"
        if any(keyword in active_haystack for keyword in self._COMMUNICATION_KEYWORDS):
            return "communication"
        if any(keyword in active_haystack for keyword in self._ENTERTAINMENT_KEYWORDS):
            return "entertainment"
        if any(keyword in combined_haystack for keyword in ("settings", "task manager", "file explorer")):
            return "system"
        return "general"

    def _build_focus_summary(self, active_window_kind: str, active_app: str, browser_url: str) -> str:
        if active_window_kind == "coding":
            return f"Ngài đang ở bối cảnh code hoặc project: {active_app}"
        if active_window_kind == "documentation":
            return f"Ngài đang đọc tài liệu hoặc reference: {browser_url or active_app}"
        if active_window_kind == "communication":
            return f"Ngài đang ở bối cảnh giao tiếp: {active_app}"
        if active_window_kind == "entertainment":
            return f"Ngài đang nghiêng sang giải trí: {active_app}"
        if active_window_kind == "system":
            return f"Ngài đang thao tác hệ thống: {active_app}"
        return f"Ngài đang ở bối cảnh tổng quát: {active_app}"

    def _label_position(self, inferred_pos_x: float) -> str:
        if inferred_pos_x <= 0.15:
            return "mép trái"
        if inferred_pos_x >= 0.85:
            return "mép phải"
        if 0.4 <= inferred_pos_x <= 0.6:
            return "giữa màn hình"
        return "lệch tâm"

    def _label_idle(self, idle_seconds: float) -> str:
        if idle_seconds >= 600:
            return "rất lâu không tương tác"
        if idle_seconds >= 180:
            return "đang nhàn rỗi"
        if idle_seconds >= 45:
            return "đang chậm lại"
        return "đang hoạt động"
    def _describe_prompt_scene(self, snapshot: TelemetrySnapshot) -> str:
        kind = snapshot.active_window_kind
        app = snapshot.active_app or snapshot.active_window or "Desktop"
        if kind == "coding":
            return "workbench glow, project nearby"
        if kind == "documentation":
            return "reference material nearby"
        if kind == "communication":
            return "conversation nearby"
        if kind == "focus_aid_media":
            return "ambient media nearby"
        if kind == "entertainment":
            return "leisure nearby"
        if kind == "system":
            return "system surface nearby"
        return "ordinary desktop quiet"

    def _describe_prompt_pace(self, snapshot: TelemetrySnapshot) -> str:
        if snapshot.idle_seconds >= 600:
            return "very quiet for a while"
        if snapshot.idle_seconds >= 180:
            return "a noticeable pause is present"
        if snapshot.idle_seconds >= 45:
            return "slowing down"
        return "active"

    def _describe_prompt_focus(self, snapshot: TelemetrySnapshot) -> str:
        signals = snapshot.user_signals
        focus_pattern = signals.focus_pattern or "unknown"
        if focus_pattern in {"deep_work", "conversation", "steady"}:
            return "settled"
        if focus_pattern in {"stuck", "absent"}:
            return "quiet pause"
        if focus_pattern in {"fragmented", "passive_consumption", "active_consumption", "background_media", "ambient_media", "split_attention"}:
            return "attention lightly spread"
        return "unclear, keep claims soft"

    def _build_prompt_cues(self, snapshot: TelemetrySnapshot) -> list[str]:
        cues: list[str] = [
            "Telemetry is weak ambient evidence, not proof of mood, intent, productivity, or laziness.",
            "Use it for pacing and light presence only.",
        ]
        kind = snapshot.active_window_kind
        focus_pattern = snapshot.user_signals.focus_pattern or ""
        switching = snapshot.user_signals.window_switching or ""

        if kind in {"coding", "documentation"}:
            cues.append("keep close to the work context instead of narrating the desktop")
        elif kind == "communication":
            cues.append("treat this as light conversation, not a productivity lecture")
        elif kind == "focus_aid_media":
            cues.append("treat visible media as possible background aid, not automatic leisure or avoidance")
        elif kind == "entertainment":
            cues.append("do not overcorrect a leisure moment unless drift is obvious")

        if focus_pattern == "stuck":
            cues.append("there may be a quiet stall, so a small concrete observation is enough")
        elif focus_pattern in {"fragmented", "split_attention"} or switching == "high":
            cues.append("attention may be spread out, but avoid quoting counts or inventories")
        elif focus_pattern == "deep_work":
            cues.append("respect concentration and keep the line brief")

        if snapshot.claim_style == "OBSERVED_PATTERN":
            cues.append("observed patterns are allowed only when grounded by concrete, non-generic evidence")
        elif snapshot.claim_style == "WEAK_IMPRESSION":
            cues.append("use explicit hedge words such as co le, toi nghi, or toi co cam giac")

        return cues[:6]

    def _looks_like_browser_surface(self, active_window: str, browser_url: str, browser_tabs: tuple[str, ...]) -> bool:
        title = str(active_window or "").lower()
        return any(keyword in title for keyword in self._BROWSER_SURFACE_KEYWORDS)

    def _build_weak_context_hints(
        self,
        *,
        active_window: str,
        browser_url: str,
        browser_tabs: tuple[str, ...],
    ) -> tuple[str, ...]:
        haystack = " | ".join((active_window, browser_url, *browser_tabs)).lower()
        hints: list[str] = []
        for needles, label in self._WEAK_CONTEXT_HINT_RULES:
            if any(needle in haystack for needle in needles):
                hints.append(f"weak context hint: {label}")
        return tuple(dict.fromkeys(hints))[:3]

    def _is_weak_context_hint_evidence(self, evidence: str) -> bool:
        lowered = str(evidence or "").strip().lower()
        return lowered.startswith("weak context hint:")

    def _concrete_evidence(self, evidence: tuple[str, ...]) -> tuple[str, ...]:
        items = [
            item
            for item in evidence
            if item
            and not self._is_generic_prompt_evidence(item)
            and not self._is_weak_context_hint_evidence(item)
        ]
        return tuple(items)

    def _evidence_quality_score(self, evidence: tuple[str, ...]) -> float:
        return sum(self._evidence_item_quality(item) for item in evidence)

    def _evidence_item_quality(self, evidence: str) -> float:
        lowered = str(evidence or "").strip().lower()
        if not lowered:
            return 0.0
        if any(
            marker in lowered
            for marker in (
                "browser target is visible",
                "browser tabs are visible",
                "windows are open",
                "browser_url_visible",
            )
        ):
            return 0.2
        if any(
            marker in lowered
            for marker in (
                "error",
                "traceback",
                "exception",
                "failed build",
                "compile failed",
                "task manager",
                "file explorer",
                "settings",
                "zoom",
                "teams",
                "meet",
                "meeting",
                "edited",
                "saved",
                "selection",
            )
        ):
            return 1.3
        if any(
            marker in lowered
            for marker in (
                "debug",
                "build",
                "terminal",
                "documentation",
                "reference",
                "readme",
                "github",
                "youtube",
                "tiktok",
                "reddit",
                "gmail",
            )
        ):
            return 0.6
        return 0.9

    def _label_ambient_tone(self, ambient_seed: int) -> str:
        if ambient_seed >= 80:
            return "bright"
        if ambient_seed <= 30:
            return "dry"
        return "neutral"

    def _label_tease_bias(self, ambient_seed: int) -> str:
        if ambient_seed >= 80:
            return "playful"
        if ambient_seed <= 30:
            return "wry"
        return "neutral"

    def _focus_summary_for_kind(self, active_window_kind: str, active_app: str, browser_url: str) -> str:
        if active_window_kind == "focus_aid_media":
            return f"Background media may be present alongside the main task: {active_app}"
        return self._build_focus_summary(active_window_kind, active_app, browser_url)
