# -*- coding: utf-8 -*-
"""Kho settings runtime có schema, ghi file nguyên tử và tương thích env cũ.

Mục tiêu của module này không phải tạo thêm một lớp config để mọi người cùng
quên dùng. Nó là nguồn sự thật duy nhất cho policy có thể đổi khi Brain đang
chạy. Env chỉ còn vai trò bootstrap/compat cho các module cũ chưa được di trú.

Thứ tự quyền lực:
    runtime_settings.json -> live UDP patch -> env bootstrap defaults

Secrets/API key tuyệt đối không nằm trong store này.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from runtime.workspace_manager import default_eris_home


_DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 4,
    "architecture": {
        "mode": "ai_orchestrated",
        "startup_greeting": True,
        # Khi UIA/OCR có evidence foreground đủ mạnh, dùng chính evidence đó làm
        # neo cho câu mở đầu thay vì onboarding chung chung.
        "startup_screen_opening": True,
        # OCR/runtime/memory là nguồn neo ưu tiên, không phải điều kiện để ERIS
        # được phép chào. Bật mặc định để startup không hóa câm khi worker chậm.
        "startup_force_speak": True,
    },
    "chat": {
        # Ngôn ngữ câu public là contract cognition riêng, không mượn cấu hình TTS.
        "language": "vi",
        "semantic_authority_mode": "primary_model",
        "reasoning_effort": "medium",
        "support_confidence_threshold": 0.48,
        "critique_mode": "off",
        "max_constrained_reruns": 0,
        "response_contract_gate": False,
        "director_candidate_mode": "off",
        "director_second_pass": "off",
        "low_quality_fail_open": True,
        "auto_fallback": True,
        "completion_chat_tokens": 1280,
        "chat_timeout_seconds": 30,
        "max_concurrency": 4,
    },
    "personality": {
        "retort_mode": "balanced",
        "provocation_policy": "character_safe",
        "style_repair_mode": "self_aware_dry",
        "allow_annoyed_soft": True,
        "allow_sharp_retort": True,
        "allow_cold_boundary": True,
        "forbid_family_literalization": True,
        "forbid_generic_helper_reset": True,
    },
    "capabilities": {
        "source": "registry",
        "respect_runtime_availability": True,
        "launch_app_enabled": True,
        "focus_window_enabled": True,
        "set_volume_enabled": True,
        "media_enabled": True,
        "copy_text_enabled": True,
        "open_url_enabled": True,
        "weather_enabled": True,
        "now_playing_enabled": True,
    },
    "project_ops": {
        "enabled": True,
        "eris_home": str(default_eris_home()),
        "workspace_root": "",
        "allow_implicit_source_repo": False,
        "fallback_to_runtime_source": False,
        "git_clone_timeout_seconds": 600,
        "autonomy_mode": "full",
        "ask_when_uncertain": True,
        "proceed_without_user_reply": True,
        "auto_rollback_on_failure": True,
        "auto_package_patch": True,
        "coding_max_tokens": 5000,
        "coding_timeout_seconds": 120,
        "max_repair_attempts": 2,
    },
    "prompt": {
        "hard_cap_tokens": 0,
        "dds_enabled": True,
        "strict_grounding": True,
    },
    "memory": {
        "semantic_parser": False,
        "background_digest": True,
        "maintenance_enabled": True,
        "maintenance_budget": "small",
    },
    "social_observer": {
        "enabled": True,
        "primary_model": "llama-3.1-8b-instant",
        "deep_enabled": True,
        "deep_model": "llama-3.3-70b-versatile",
        "fallback_enabled": True,
        "fallback_model": "llama-3.1-8b-instant",
        "workers": 2,
        "prompt_context_enabled": True,
        "state_authority": True,
    },
    "stage": {
        "performance_profile": "conversation",
        "performance_acts_enabled": True,
        "interrupt_enabled": True,
        "protocol_enabled": True,
        "segment_tts": False,
        "segment_dispatch": "inline",
        # Conversation profile dùng manager để một request synth cũ bị user hủy
        # không chặn TTS của turn mới ở cùng worker tuần tự.
        "tts_task_manager": True,
        "prefetch_workers": 1,
        "max_tts_segments": 1,
        "min_split_chars": 72,
        "show_plan_enabled": True,
        "stage_replay_enabled": True,
        "stage_replay_size": 160,
    },
    "tts": {
        "enabled": True,
        # Project Eris dùng bubble Việt + voice Nhật theo mặc định.
        "language": "ja",
        "voice": "Aoede",
        "quality": "high",
        "volume": 1.0,
        "speed": 1.0,
        "stage_localize": True,
        # Làm mềm riêng transcript TTS, không sửa bubble/public meaning.
        "speech_persona_polish": True,
        "speech_persona_profile": "infj_5w4_subtle",
        "speech_persona_warmth": 0.24,
        "speech_persona_cuteness": 0.10,
        # Signature chỉ áp vào transcript Nhật. Localizer quyết định theo câu và
        # tích hợp bằng ngữ pháp, không nối chuỗi ``ですね`` một cách máy móc.
        "signature_ending_enabled": True,
        "signature_ending": "desu_ne",
        "signature_ending_rate": 0.42,
        "audio_polish": False,
    },
    "discovery": {
        "enabled": True,
        "local_signal_enabled": True,
        "user_location": "",
        "local_signal_scope": "Việt Nam",
        "minimum_idle_seconds": 240,
        "planning_interval_seconds": 1800,
        "local_signal_interval_seconds": 28800,
        "share_cooldown_seconds": 5400,
    },
    "initiative": {
        "enabled": True,
        # Global cap chỉ là phanh cuối. Cooldown thật nằm theo motive class.
        "hourly_budget": 2,  # legacy UI value; Initiative v3 không dùng làm global cap
        "global_hourly_budget": 40,
        "minimum_interval_seconds": 60,
        "minimum_user_silence_seconds": 12,
        "importance_margin": 0.08,
        "semantic_duplicate_threshold": 0.66,
        "activity_update_cooldown_seconds": 120,
    },
    "commentary": {
        # Companion mode: người dùng mở Eris để nghe cô ấy sống cùng phiên làm
        # việc, không phải để ngắm một hệ thống rất thông minh quyết định im.
        "enabled": True,
        "desired_interval_seconds": 60,
        "maximum_quiet_seconds": 120,
        "startup_delay_seconds": 8,
        "minimum_user_silence_seconds": 12,
    },
    "tutor": {
        "enabled": True,
        "quick_search_enabled": True,
        "research_enabled": True,
        "self_search_enabled": True,
        "low_confidence_clarify_threshold": 0.55,
        "stale_result_guard_enabled": True,
        "persist_research_memory": False,
    },
    "hardening": {
        # Phase 7/8: một nguồn cấu hình cho validation + release stable. Các env
        # cũ vẫn được đọc để migration, nhưng runtime mới nên đi qua block này.
        "profile": "development",
        "production_validation_enabled": False,
        "production_validation_turns": 24,
        "production_validation_dir": "logs/phase7_validation",
        "panel_ack_required": True,
        "provider_registry_strict": True,
        "release_manifest_path": "config/hardening_release.json",
        "release_guard_enabled": True,
        "release_guard_fail_closed": False,
        "legacy_cross_language_tts": False,
        "legacy_romaji_tts": False,
    },
    "danger_zone": {
        "require_preview_before_execute": True,
        "typed_confirmation": True,
        "allow_destructive_maintenance": False,
    },
}


# Mapping này phục vụ migration, không phải nguồn schema chính.
_ENV_BINDINGS: dict[tuple[str, ...], tuple[str, str]] = {
    ("architecture", "mode"): ("ERIS_RUNTIME_ARCHITECTURE", "str"),
    ("architecture", "startup_greeting"): ("ERIS_AI_STARTUP_GREETING_ENABLED", "bool"),
    ("architecture", "startup_screen_opening"): ("ERIS_AI_STARTUP_SCREEN_OPENING", "bool"),
    ("architecture", "startup_force_speak"): ("ERIS_AI_STARTUP_FORCE_SPEAK", "bool"),
    ("chat", "language"): ("ERIS_CHAT_LANGUAGE", "str"),
    ("chat", "semantic_authority_mode"): ("ERIS_SEMANTIC_AUTHORITY", "str"),
    ("chat", "reasoning_effort"): ("ERIS_REASONING_EFFORT", "str"),
    ("chat", "support_confidence_threshold"): ("ERIS_QWEN_SUPPORT_CONFIDENCE", "float"),
    ("chat", "max_constrained_reruns"): ("ERIS_MAX_CONSTRAINED_RERUNS", "int"),
    ("chat", "response_contract_gate"): ("ERIS_RESPONSE_CONTRACT_GATE", "bool"),
    ("chat", "director_second_pass"): ("ERIS_CHAT_DIRECTOR_SECOND_PASS", "adaptive_bool"),
    ("chat", "low_quality_fail_open"): ("ERIS_QWEN_LOW_QUALITY_FAIL_OPEN", "bool"),
    ("chat", "auto_fallback"): ("ERIS_NO_FALLBACK_MODE", "inverse_bool"),
    ("chat", "completion_chat_tokens"): ("ERIS_LLM_COMPLETION_CHAT_TOKENS", "int"),
    ("chat", "chat_timeout_seconds"): ("ERIS_LLM_TIMEOUT_CHAT_S", "int"),
    ("chat", "max_concurrency"): ("ERIS_LLM_MAX_CONCURRENCY", "int"),
    ("personality", "retort_mode"): ("ERIS_RETORT_MODE", "str"),
    ("personality", "forbid_family_literalization"): ("ERIS_FORBID_FAMILY_LITERALIZATION", "bool"),
    ("personality", "forbid_generic_helper_reset"): ("ERIS_FORBID_GENERIC_HELPER_RESET", "bool"),
    ("project_ops", "enabled"): ("ERIS_PROJECT_OPS_ENABLED", "bool"),
    ("project_ops", "eris_home"): ("ERIS_HOME", "str"),
    ("project_ops", "workspace_root"): ("ERIS_WORKSPACES_ROOT", "str"),
    ("project_ops", "allow_implicit_source_repo"): ("ERIS_ALLOW_IMPLICIT_SOURCE_REPO", "bool"),
    ("project_ops", "fallback_to_runtime_source"): ("ERIS_FALLBACK_TO_RUNTIME_SOURCE", "bool"),
    ("project_ops", "git_clone_timeout_seconds"): ("ERIS_GIT_CLONE_TIMEOUT_S", "int"),
    ("project_ops", "autonomy_mode"): ("ERIS_PROJECT_AUTONOMY_MODE", "str"),
    ("project_ops", "ask_when_uncertain"): ("ERIS_PROJECT_ASK_WHEN_UNCERTAIN", "bool"),
    ("project_ops", "proceed_without_user_reply"): ("ERIS_PROJECT_PROCEED_WITHOUT_REPLY", "bool"),
    ("project_ops", "auto_rollback_on_failure"): ("ERIS_PROJECT_AUTO_ROLLBACK", "bool"),
    ("project_ops", "auto_package_patch"): ("ERIS_PROJECT_AUTO_PACKAGE", "bool"),
    ("project_ops", "coding_max_tokens"): ("ERIS_PROJECT_CODING_MAX_TOKENS", "int"),
    ("project_ops", "coding_timeout_seconds"): ("ERIS_PROJECT_CODING_TIMEOUT_S", "int"),
    ("project_ops", "max_repair_attempts"): ("ERIS_PROJECT_MAX_REPAIR_ATTEMPTS", "int"),
    ("discovery", "enabled"): ("ERIS_DISCOVERY_ENABLED", "bool"),
    ("discovery", "local_signal_enabled"): ("ERIS_DISCOVERY_LOCAL_SIGNAL_ENABLED", "bool"),
    ("discovery", "user_location"): ("ERIS_DISCOVERY_USER_LOCATION", "str"),
    ("discovery", "local_signal_scope"): ("ERIS_DISCOVERY_LOCAL_SIGNAL_SCOPE", "str"),
    ("discovery", "minimum_idle_seconds"): ("ERIS_DISCOVERY_MINIMUM_IDLE_SECONDS", "int"),
    ("discovery", "planning_interval_seconds"): ("ERIS_DISCOVERY_PLANNING_INTERVAL_SECONDS", "int"),
    ("discovery", "local_signal_interval_seconds"): ("ERIS_DISCOVERY_LOCAL_SIGNAL_INTERVAL_SECONDS", "int"),
    ("discovery", "share_cooldown_seconds"): ("ERIS_DISCOVERY_SHARE_COOLDOWN_SECONDS", "int"),
    ("initiative", "enabled"): ("ERIS_INITIATIVE_ENABLED", "bool"),
    ("initiative", "hourly_budget"): ("ERIS_INITIATIVE_HOURLY_BUDGET", "int"),
    ("initiative", "global_hourly_budget"): ("ERIS_INITIATIVE_GLOBAL_HOURLY_BUDGET", "int"),
    ("initiative", "minimum_interval_seconds"): ("ERIS_INITIATIVE_MINIMUM_INTERVAL_SECONDS", "int"),
    ("initiative", "minimum_user_silence_seconds"): ("ERIS_INITIATIVE_MINIMUM_USER_SILENCE_SECONDS", "int"),
    ("initiative", "semantic_duplicate_threshold"): ("ERIS_INITIATIVE_SEMANTIC_DUPLICATE_THRESHOLD", "float"),
    ("initiative", "importance_margin"): ("ERIS_INITIATIVE_IMPORTANCE_MARGIN", "float"),
    ("initiative", "activity_update_cooldown_seconds"): ("ERIS_INITIATIVE_ACTIVITY_UPDATE_COOLDOWN_SECONDS", "int"),
    ("commentary", "enabled"): ("ERIS_COMMENTARY_ENABLED", "bool"),
    ("commentary", "desired_interval_seconds"): ("ERIS_COMMENTARY_DESIRED_INTERVAL_SECONDS", "int"),
    ("commentary", "maximum_quiet_seconds"): ("ERIS_COMMENTARY_MAXIMUM_QUIET_SECONDS", "int"),
    ("commentary", "startup_delay_seconds"): ("ERIS_COMMENTARY_STARTUP_DELAY_SECONDS", "int"),
    ("commentary", "minimum_user_silence_seconds"): ("ERIS_COMMENTARY_MINIMUM_USER_SILENCE_SECONDS", "int"),
    ("prompt", "hard_cap_tokens"): ("ERIS_LLM_PROMPT_HARD_CAP_TOKENS", "int"),
    ("prompt", "dds_enabled"): ("ERIS_DDS_ENABLED", "bool"),
    ("prompt", "strict_grounding"): ("ERIS_STRICT_GROUNDING", "bool"),
    ("memory", "semantic_parser"): ("ERIS_MEMORY_SEMANTIC_PARSER", "bool"),
    ("memory", "maintenance_enabled"): ("ERIS_MEMORY_DIGEST_MAINTENANCE", "bool"),
    ("memory", "maintenance_budget"): ("ERIS_MEMORY_MAINTENANCE_BUDGET", "str"),
    ("social_observer", "enabled"): ("ERIS_SOCIAL_OBSERVER_ENABLED", "bool"),
    ("social_observer", "primary_model"): ("ERIS_SOCIAL_OBSERVER_MODEL", "str"),
    ("social_observer", "deep_enabled"): ("ERIS_SOCIAL_OBSERVER_DEEP_ENABLED", "bool"),
    ("social_observer", "deep_model"): ("ERIS_SOCIAL_OBSERVER_DEEP_MODEL", "str"),
    ("social_observer", "fallback_enabled"): ("ERIS_SOCIAL_OBSERVER_FALLBACK_ENABLED", "bool"),
    ("social_observer", "fallback_model"): ("ERIS_SOCIAL_OBSERVER_FALLBACK_MODEL", "str"),
    ("social_observer", "workers"): ("ERIS_SOCIAL_OBSERVER_WORKERS", "int"),
    ("social_observer", "prompt_context_enabled"): ("ERIS_SOCIAL_OBSERVER_PROMPT_CONTEXT", "bool"),
    ("social_observer", "state_authority"): ("ERIS_SOCIAL_OBSERVER_STATE_AUTHORITY", "bool"),
    ("stage", "performance_acts_enabled"): ("ERIS_PERFORMANCE_ACTS_ENABLED", "bool"),
    ("stage", "interrupt_enabled"): ("ERIS_INTERRUPT_ENABLED", "bool"),
    ("stage", "protocol_enabled"): ("ERIS_STAGE_PROTOCOL", "bool"),
    ("stage", "segment_tts"): ("ERIS_STAGE_SEGMENT_TTS", "bool"),
    ("stage", "performance_profile"): ("ERIS_STAGE_PROFILE", "str"),
    ("stage", "segment_dispatch"): ("ERIS_TTS_SEGMENT_DISPATCH", "str"),
    ("stage", "tts_task_manager"): ("ERIS_TTS_TASK_MANAGER", "bool"),
    ("stage", "prefetch_workers"): ("ERIS_TTS_PREFETCH_WORKERS", "int"),
    ("stage", "max_tts_segments"): ("ERIS_STAGE_MAX_TTS_SEGMENTS", "int"),
    ("stage", "min_split_chars"): ("ERIS_STAGE_MIN_SPLIT_CHARS", "int"),
    ("stage", "show_plan_enabled"): ("ERIS_STAGE_SHOW_PLAN", "bool"),
    ("stage", "stage_replay_enabled"): ("ERIS_STAGE_REPLAY", "bool"),
    ("stage", "stage_replay_size"): ("ERIS_STAGE_REPLAY_SIZE", "int"),
    ("tts", "enabled"): ("ERIS_TTS_ENABLED", "bool"),
    ("tts", "language"): ("ERIS_TTS_LANGUAGE", "str"),
    ("tts", "voice"): ("ERIS_TTS_VOICE", "str"),
    ("tts", "quality"): ("ERIS_TTS_QUALITY", "str"),
    ("tts", "stage_localize"): ("ERIS_TTS_STAGE_LOCALIZE", "bool"),
    ("tts", "speech_persona_polish"): ("ERIS_TTS_SPEECH_PERSONA_POLISH", "bool"),
    ("tts", "speech_persona_profile"): ("ERIS_TTS_SPEECH_PERSONA_PROFILE", "str"),
    ("tts", "speech_persona_warmth"): ("ERIS_TTS_SPEECH_PERSONA_WARMTH", "float"),
    ("tts", "speech_persona_cuteness"): ("ERIS_TTS_SPEECH_PERSONA_CUTENESS", "float"),
    ("tts", "signature_ending_enabled"): ("ERIS_TTS_SIGNATURE_ENDING_ENABLED", "bool"),
    ("tts", "signature_ending"): ("ERIS_TTS_SIGNATURE_ENDING", "str"),
    ("tts", "signature_ending_rate"): ("ERIS_TTS_SIGNATURE_ENDING_RATE", "float"),
    ("tts", "audio_polish"): ("ERIS_TTS_AUDIO_POLISH", "bool"),
    ("tutor", "enabled"): ("ERIS_TUTOR_ENABLED", "bool"),
    ("tutor", "quick_search_enabled"): ("ERIS_TUTOR_QUICK_SEARCH_ENABLED", "bool"),
    ("tutor", "research_enabled"): ("ERIS_TUTOR_RESEARCH_ENABLED", "bool"),
    ("tutor", "self_search_enabled"): ("ERIS_TUTOR_SELF_SEARCH_ENABLED", "bool"),
    ("tutor", "stale_result_guard_enabled"): ("ERIS_TUTOR_STALE_GUARD", "bool"),
    ("tutor", "persist_research_memory"): ("ERIS_TUTOR_RESEARCH_PERSIST", "bool"),
    ("hardening", "profile"): ("ERIS_HARDENING_PROFILE", "str"),
    ("hardening", "production_validation_enabled"): ("ERIS_PHASE7_VALIDATION_ENABLED", "bool"),
    ("hardening", "production_validation_turns"): ("ERIS_PHASE7_VALIDATION_TURNS", "int"),
    ("hardening", "production_validation_dir"): ("ERIS_PHASE7_VALIDATION_DIR", "str"),
    ("hardening", "panel_ack_required"): ("ERIS_PANEL_ACK_REQUIRED", "bool"),
    ("hardening", "provider_registry_strict"): ("ERIS_PROVIDER_REGISTRY_STRICT", "bool"),
    ("hardening", "release_manifest_path"): ("ERIS_HARDENING_RELEASE_MANIFEST", "str"),
    ("hardening", "release_guard_enabled"): ("ERIS_HARDENING_RELEASE_GUARD", "bool"),
    ("hardening", "release_guard_fail_closed"): ("ERIS_HARDENING_RELEASE_FAIL_CLOSED", "bool"),
    ("hardening", "legacy_cross_language_tts"): ("ERIS_TTS_LEGACY_CROSS_LANGUAGE", "bool"),
    ("hardening", "legacy_romaji_tts"): ("ERIS_TTS_EDGE_ROMAJI", "bool"),
}


@dataclass(frozen=True, slots=True)
class SettingsUpdateResult:
    settings: dict[str, Any]
    applied: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    restart_required: tuple[str, ...] = ()
    revision: int = 0
    saved_at: float = 0.0

    def to_ack(self, *, scope: str) -> dict[str, Any]:
        return {
            "scope": scope,
            "applied": list(self.applied),
            "rejected": list(self.rejected),
            "restart_required": list(self.restart_required),
            "revision": self.revision,
            "saved_at": self.saved_at,
        }


class RuntimeSettingsStore:
    """Thread-safe settings store với merge có whitelist theo schema mặc định."""

    def __init__(self, path: str | os.PathLike[str] | None = None, *, logger: Any = None) -> None:
        raw_path = path or os.getenv("ERIS_RUNTIME_SETTINGS_PATH", "")
        if raw_path:
            resolved = Path(raw_path).expanduser()
            if not resolved.is_absolute():
                resolved = default_eris_home() / "config" / resolved
        else:
            resolved = default_eris_home() / "config" / "runtime_settings.json"
        self.path = resolved.resolve()
        self.logger = logger
        self._lock = threading.RLock()
        self._settings: dict[str, Any] | None = None
        self._revision = 0
        self._saved_at = 0.0

    def load(self, *, materialize_env: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._settings is not None:
                settings = copy.deepcopy(self._settings)
            elif self.path.exists():
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    payload, migrated = self._migrate_payload(payload)
                    settings = self._validate_full(payload)
                    if migrated:
                        self._atomic_save(settings)
                except Exception as exc:
                    self._log("warning", "[runtime-settings] file lỗi, dùng env compat: %s", exc)
                    settings = self.from_env_compat()
                    self._atomic_save(settings)
                self._settings = settings
            else:
                settings = self.from_env_compat()
                self._settings = settings
                self._atomic_save(settings)
            self._revision = max(1, self._revision)
            result = copy.deepcopy(settings)
        if materialize_env:
            self.materialize_env(result)
        return result

    def snapshot(self) -> dict[str, Any]:
        return self.load(materialize_env=False)

    def get(self, *path: str, default: Any = None) -> Any:
        node: Any = self.load(materialize_env=False)
        for key in path:
            if not isinstance(node, Mapping) or key not in node:
                return default
            node = node[key]
        return copy.deepcopy(node)

    def apply_patch(
        self,
        patch: Mapping[str, Any],
        *,
        restart_required_paths: set[str] | None = None,
        materialize_env: bool = False,
    ) -> SettingsUpdateResult:
        restart_required_paths = restart_required_paths or set()
        with self._lock:
            base = self.load(materialize_env=False)
            applied: list[str] = []
            rejected: list[str] = []
            restart: list[str] = []
            merged = copy.deepcopy(base)
            self._merge_patch(
                merged,
                patch,
                schema=_DEFAULT_SETTINGS,
                prefix="",
                applied=applied,
                rejected=rejected,
                restart=restart,
                restart_required_paths=restart_required_paths,
            )
            merged["version"] = int(_DEFAULT_SETTINGS["version"])
            self._settings = merged
            self._revision += 1
            self._atomic_save(merged)
            result = SettingsUpdateResult(
                settings=copy.deepcopy(merged),
                applied=tuple(applied),
                rejected=tuple(rejected),
                restart_required=tuple(dict.fromkeys(restart)),
                revision=self._revision,
                saved_at=self._saved_at,
            )
        if materialize_env:
            self.materialize_env(result.settings)
        return result

    def replace(self, settings: Mapping[str, Any]) -> SettingsUpdateResult:
        validated = self._validate_full(settings)
        with self._lock:
            self._settings = validated
            self._revision += 1
            self._atomic_save(validated)
            result = SettingsUpdateResult(
                settings=copy.deepcopy(validated),
                applied=("*",),
                revision=self._revision,
                saved_at=self._saved_at,
            )
        return result

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return copy.deepcopy(_DEFAULT_SETTINGS)

    @classmethod
    def from_env_compat(cls) -> dict[str, Any]:
        settings = copy.deepcopy(_DEFAULT_SETTINGS)
        for path, (env_name, kind) in _ENV_BINDINGS.items():
            raw = os.environ.get(env_name)
            if raw is None or str(raw).strip() == "":
                continue
            value = _parse_env_value(raw, kind, _get_path(settings, path))
            _set_path(settings, path, value)
        # Alias cũ dùng tổng prompt thay hard-cap.
        if "ERIS_LLM_PROMPT_HARD_CAP_TOKENS" not in os.environ and os.getenv("ERIS_LLM_PROMPT_TOTAL_TOKENS"):
            _set_path(
                settings,
                ("prompt", "hard_cap_tokens"),
                _parse_env_value(os.getenv("ERIS_LLM_PROMPT_TOTAL_TOKENS", "4800"), "int", 4800),
            )
        return cls._static_validate(settings)

    def materialize_env(self, settings: Mapping[str, Any] | None = None) -> None:
        payload = dict(settings or self.load(materialize_env=False))
        for path, (env_name, kind) in _ENV_BINDINGS.items():
            value = _get_path(payload, path)
            if value is None:
                continue
            os.environ[env_name] = _format_env_value(value, kind)
        # Giữ alias tổng/hard cap đồng nhất cho nhánh token-budget cũ.
        hard_cap_value = _get_path(payload, ("prompt", "hard_cap_tokens"))
        hard_cap = str(0 if hard_cap_value is None else hard_cap_value)
        os.environ["ERIS_LLM_PROMPT_HARD_CAP_TOKENS"] = hard_cap
        os.environ["ERIS_LLM_PROMPT_TOTAL_TOKENS"] = hard_cap

    @classmethod
    def _migrate_payload(cls, payload: Any) -> tuple[dict[str, Any], bool]:
        """Di trú settings theo từng schema, không ghi đè lựa chọn thật.

        v1 -> v2 tách ngôn ngữ public khỏi ngôn ngữ TTS.
        v2 -> v3 nâng đúng baseline warmth 0.18 lên 0.24; giá trị đã được
        người dùng chỉnh khác baseline cũ được giữ nguyên.
        v3 -> v4 thêm companion-commentary cadence và nới ngân sách initiative.
        """
        if not isinstance(payload, Mapping):
            return {}, False
        out = copy.deepcopy(dict(payload))
        try:
            version = int(out.get("version", 0) or 0)
        except (TypeError, ValueError):
            version = 0
        target_version = int(_DEFAULT_SETTINGS["version"])
        if version >= target_version:
            return out, False

        migrated = False
        if version < 2:
            chat = out.get("chat") if isinstance(out.get("chat"), Mapping) else {}
            tts = out.get("tts") if isinstance(out.get("tts"), Mapping) else {}
            chat = dict(chat or {})
            tts = dict(tts or {})
            chat["language"] = str(chat.get("language") or "vi").strip().lower() or "vi"

            raw_tts = str(tts.get("language") or "").strip().lower()
            env_tts = str(os.environ.get("ERIS_TTS_LANGUAGE", "") or "").strip().lower()
            aliases = {"jp": "ja", "japanese": "ja", "ja-jp": "ja", "auto": ""}
            raw_tts = aliases.get(raw_tts, raw_tts)
            env_tts = aliases.get(env_tts, env_tts)
            # v1 từng cưỡng ép vi nên chỉ schema này mới được phục hồi về ja.
            if raw_tts in {"", "vi"}:
                tts["language"] = env_tts if env_tts in {"ja", "en"} else "ja"
            else:
                tts["language"] = raw_tts if raw_tts in {"ja", "en"} else "ja"
            out["chat"] = chat
            out["tts"] = tts
            migrated = True

        if version < 3:
            tts = dict(out.get("tts") or {}) if isinstance(out.get("tts"), Mapping) else {}
            try:
                old_warmth = float(tts.get("speech_persona_warmth"))
            except (TypeError, ValueError):
                old_warmth = -1.0
            if abs(old_warmth - 0.18) <= 1e-9:
                tts["speech_persona_warmth"] = 0.24
                out["tts"] = tts
                migrated = True


        if version < 4:
            initiative = dict(out.get("initiative") or {}) if isinstance(out.get("initiative"), Mapping) else {}
            try:
                old_budget = int(initiative.get("global_hourly_budget", 10) or 10)
            except (TypeError, ValueError):
                old_budget = 10
            # Chỉ nâng đúng baseline cũ; lựa chọn thủ công khác 10 được giữ.
            if old_budget == 10:
                initiative["global_hourly_budget"] = 40
            if int(initiative.get("minimum_interval_seconds", 90) or 90) == 90:
                initiative["minimum_interval_seconds"] = 60
            if int(initiative.get("minimum_user_silence_seconds", 20) or 20) == 20:
                initiative["minimum_user_silence_seconds"] = 12
            if int(initiative.get("activity_update_cooldown_seconds", 180) or 180) == 180:
                initiative["activity_update_cooldown_seconds"] = 120
            out["initiative"] = initiative
            commentary = dict(out.get("commentary") or {}) if isinstance(out.get("commentary"), Mapping) else {}
            commentary.setdefault("enabled", True)
            commentary.setdefault("desired_interval_seconds", 60)
            commentary.setdefault("maximum_quiet_seconds", 120)
            commentary.setdefault("startup_delay_seconds", 8)
            commentary.setdefault("minimum_user_silence_seconds", 12)
            out["commentary"] = commentary
            migrated = True

        out["version"] = target_version
        return out, True if version != target_version else migrated

    def _validate_full(self, payload: Any) -> dict[str, Any]:
        return self._static_validate(payload)

    @classmethod
    def _static_validate(cls, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            payload = {}
        out = copy.deepcopy(_DEFAULT_SETTINGS)
        applied: list[str] = []
        rejected: list[str] = []
        cls._merge_patch_static(out, payload, _DEFAULT_SETTINGS, "", applied, rejected)
        out["version"] = int(_DEFAULT_SETTINGS["version"])
        return out

    @classmethod
    def _merge_patch_static(
        cls,
        target: dict[str, Any],
        patch: Mapping[str, Any],
        schema: Mapping[str, Any],
        prefix: str,
        applied: list[str],
        rejected: list[str],
    ) -> None:
        for key, value in patch.items():
            if key == "version":
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in schema:
                rejected.append(path)
                continue
            expected = schema[key]
            if isinstance(expected, Mapping):
                if not isinstance(value, Mapping):
                    rejected.append(path)
                    continue
                cls._merge_patch_static(target[key], value, expected, path, applied, rejected)
                continue
            ok, normalized = _coerce_setting(path, value, expected)
            if not ok:
                rejected.append(path)
                continue
            target[key] = normalized
            applied.append(path)

    def _merge_patch(
        self,
        target: dict[str, Any],
        patch: Mapping[str, Any],
        *,
        schema: Mapping[str, Any],
        prefix: str,
        applied: list[str],
        rejected: list[str],
        restart: list[str],
        restart_required_paths: set[str],
    ) -> None:
        for key, value in patch.items():
            if key == "version":
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in schema:
                rejected.append(path)
                continue
            expected = schema[key]
            if isinstance(expected, Mapping):
                if not isinstance(value, Mapping):
                    rejected.append(path)
                    continue
                self._merge_patch(
                    target[key], value, schema=expected, prefix=path,
                    applied=applied, rejected=rejected, restart=restart,
                    restart_required_paths=restart_required_paths,
                )
                continue
            ok, normalized = _coerce_setting(path, value, expected)
            if not ok:
                rejected.append(path)
                continue
            target[key] = normalized
            applied.append(path)
            if path in restart_required_paths:
                restart.append(path)

    def _atomic_save(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._saved_at = time.time()
        self._log("info", "[runtime-settings] saved revision=%s path=%s", self._revision, self.path)

    def _log(self, level: str, message: str, *args: Any) -> None:
        method = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(method):
            try:
                method(message, *args)
            except Exception:
                pass


_DEFAULT_STORE: RuntimeSettingsStore | None = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_runtime_settings_store(*, logger: Any = None) -> RuntimeSettingsStore:
    global _DEFAULT_STORE
    store = _DEFAULT_STORE
    if store is not None:
        return store
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = RuntimeSettingsStore(logger=logger)
        return _DEFAULT_STORE


def reset_runtime_settings_store_for_tests() -> None:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = None


def _get_path(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _set_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = payload
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() not in {"", "0", "false", "off", "no", "none"}


def _parse_env_value(raw: Any, kind: str, fallback: Any) -> Any:
    try:
        if kind == "bool":
            return _truthy(raw)
        if kind == "inverse_bool":
            return not _truthy(raw)
        if kind == "adaptive_bool":
            text = str(raw or "").strip().lower()
            return "always" if _truthy(text) else "adaptive"
        if kind == "int":
            return int(float(str(raw).strip()))
        if kind == "float":
            return float(str(raw).strip())
        return str(raw).strip()
    except Exception:
        return fallback


def _format_env_value(value: Any, kind: str) -> str:
    if kind == "bool":
        return "1" if bool(value) else "0"
    if kind == "inverse_bool":
        return "0" if bool(value) else "1"
    if kind == "adaptive_bool":
        return "1" if str(value).strip().lower() in {"always", "on", "true", "1"} else "0"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _coerce_setting(path: str, value: Any, expected: Any) -> tuple[bool, Any]:
    try:
        if isinstance(expected, bool):
            if isinstance(value, bool):
                normalized = value
            elif isinstance(value, (int, float)):
                normalized = bool(value)
            elif isinstance(value, str):
                normalized = _truthy(value)
            else:
                return False, expected
        elif isinstance(expected, int) and not isinstance(expected, bool):
            normalized = int(value)
        elif isinstance(expected, float):
            normalized = float(value)
        elif isinstance(expected, str):
            normalized = str(value).strip()
        else:
            normalized = value
    except Exception:
        return False, expected

    # Whitelist/range theo field. Schema kiểu dữ liệu thôi chưa đủ, vì con người
    # rất sáng tạo trong việc nhập 9000 worker rồi hỏi sao máy nóng.
    enum_values: dict[str, set[str]] = {
        "chat.language": {"vi", "ja", "en"},
        "chat.semantic_authority_mode": {"primary_model", "qwen_first", "legacy"},
        "chat.reasoning_effort": {"low", "medium", "high"},
        "chat.critique_mode": {"off", "advisory", "bounded_refine"},
        "chat.director_candidate_mode": {"off", "adaptive", "always"},
        "chat.director_second_pass": {"off", "adaptive", "always"},
        "personality.retort_mode": {"off", "restrained", "balanced", "sharp"},
        "personality.provocation_policy": {"character_safe", "restrained", "boundary_only"},
        "personality.style_repair_mode": {"self_aware_dry", "direct", "soft"},
        "capabilities.source": {"registry"},
        "memory.maintenance_budget": {"small", "medium", "large"},
        "stage.performance_profile": {"conversation", "custom"},
        "stage.segment_dispatch": {"inline", "queued"},
        "tts.language": {"vi", "ja", "en"},
        "tts.quality": {"balanced", "high"},
        "hardening.profile": {"development", "canary", "stable"},
    }
    if path in enum_values and str(normalized).lower() not in enum_values[path]:
        return False, expected
    if path in enum_values:
        normalized = str(normalized).lower()

    ranges: dict[str, tuple[float, float]] = {
        "chat.support_confidence_threshold": (0.05, 0.95),
        "chat.max_constrained_reruns": (0, 2),
        "chat.completion_chat_tokens": (384, 4096),
        "chat.chat_timeout_seconds": (5, 120),
        "chat.max_concurrency": (1, 16),
        "prompt.hard_cap_tokens": (0, 1_000_000),
        "hardening.production_validation_turns": (20, 30),
        "stage.prefetch_workers": (1, 8),
        "stage.max_tts_segments": (1, 12),
        "stage.min_split_chars": (24, 160),
        "tts.volume": (0.0, 2.0),
        "tts.speed": (0.5, 2.0),
        "tts.speech_persona_warmth": (0.0, 0.5),
        "tts.speech_persona_cuteness": (0.0, 0.35),
        "tts.signature_ending_rate": (0.0, 0.8),
    }
    if path in ranges:
        lo, hi = ranges[path]
        normalized = max(lo, min(hi, normalized))
        if isinstance(expected, int):
            normalized = int(normalized)
    if path == "tts.voice":
        if not normalized or len(normalized) > 64 or not all(ch.isalnum() or ch in {"-", "_"} for ch in normalized):
            return False, expected
    return True, normalized


def runtime_setting(*path: str, default: Any = None) -> Any:
    """Đọc policy runtime từ store; env chỉ được dùng khi file chưa materialize.

    Hàm này cố ý nhỏ để các module cũ di trú từng phần mà không cần giữ một
    reference Coordinator. Mọi giá trị trả về là copy, không ai được lén sửa
    snapshot chung rồi gọi đó là live apply.
    """

    try:
        return get_runtime_settings_store().get(*path, default=default)
    except Exception:
        return default


def runtime_bool(*path: str, default: bool = False) -> bool:
    value = runtime_setting(*path, default=default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() not in {"", "0", "false", "off", "no", "none"}


def runtime_int(*path: str, default: int = 0) -> int:
    try:
        return int(runtime_setting(*path, default=default))
    except Exception:
        return int(default)


def runtime_float(*path: str, default: float = 0.0) -> float:
    try:
        return float(runtime_setting(*path, default=default))
    except Exception:
        return float(default)


def runtime_text(*path: str, default: str = "") -> str:
    value = runtime_setting(*path, default=default)
    return str(value if value is not None else default).strip()


__all__ = [
    "RuntimeSettingsStore",
    "SettingsUpdateResult",
    "get_runtime_settings_store",
    "reset_runtime_settings_store_for_tests",
    "runtime_setting",
    "runtime_bool",
    "runtime_int",
    "runtime_float",
    "runtime_text",
]
