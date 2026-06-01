# -*- coding: utf-8 -*-
"""
src/runtime/model_budget_policy.py
==================================

Module sinh tử của tầng tự chủ.

Nhiệm vụ:
- Đo CPU/RAM/VRAM/GPU temperature nếu có thể.
- Nhận diện ngữ cảnh nặng: game, Godot, compile, main cognition vừa chạy.
- VETO request gọi Qwen 4B hoặc Main Model khi máy đang đuối.

Luật vận hành:
- Sensory 0.6B rẻ hơn, nhưng vẫn bị chặn nếu hệ thống gần chết.
- Subconscious 4B bị chặn rất gắt trên GTX 1650 Ti 4GB.
- Main Model bị chặn khi tài nguyên quá căng hoặc vừa có main request khác.

Không có module này thì autonomous AI sẽ tranh VRAM với game/dev tool. Một tội ác nhỏ nhưng dai.
"""

from __future__ import annotations

import math
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Optional

ModelTier = Literal["sensory_0_6b", "subconscious_4b", "main_cognition", "vision_compressor", "unknown"]
BudgetVerdict = Literal["allow", "block", "kill"]


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    if math.isnan(n) or math.isinf(n):
        n = default
    return max(0.0, min(1.0, n))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        return default
    if math.isnan(n) or math.isinf(n):
        return default
    return n


def _env_float(name: str, default: float) -> float:
    return _safe_float(os.getenv(name), default)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(slots=True)
class ResourceSnapshot:
    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    gpu_util_percent: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    gpu_temperature_c: float = 0.0
    active_app: str = ""
    active_window_title: str = ""
    is_game_or_heavy_app: bool = False
    is_compile_or_godot: bool = False
    main_cognition_recent: bool = False
    telemetry_ok: bool = True
    notes: tuple[str, ...] = ()

    @property
    def vram_percent(self) -> float:
        if self.vram_total_mb <= 0:
            return 0.0
        return max(0.0, min(100.0, self.vram_used_mb / self.vram_total_mb * 100.0))

    @property
    def resource_pressure(self) -> float:
        return _clamp01(max(self.cpu_percent / 100.0, self.ram_percent / 100.0, self.gpu_util_percent / 100.0, self.vram_percent / 100.0))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["vram_percent"] = self.vram_percent
        data["resource_pressure"] = self.resource_pressure
        return data


@dataclass(slots=True)
class BudgetDecision:
    verdict: BudgetVerdict
    allowed: bool
    tier: ModelTier
    reason: str
    resource_snapshot: ResourceSnapshot
    cooldown_seconds: float = 0.0
    hard_veto: bool = False
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "allowed": self.allowed,
            "tier": self.tier,
            "reason": self.reason,
            "resource_snapshot": self.resource_snapshot.to_dict(),
            "cooldown_seconds": self.cooldown_seconds,
            "hard_veto": self.hard_veto,
            "debug": self.debug,
        }


@dataclass(slots=True)
class ModelBudgetPolicyConfig:
    enabled: bool = field(default_factory=lambda: _env_flag("ERIS_MODEL_BUDGET_POLICY", True))
    cpu_block_percent: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_CPU_BLOCK", 92.0))
    ram_block_percent: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_RAM_BLOCK", 90.0))
    gpu_block_percent: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_GPU_BLOCK", 70.0))
    vram_block_percent: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_VRAM_BLOCK", 72.0))
    gpu_temp_block_c: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_GPU_TEMP_BLOCK", 82.0))
    main_cooldown_seconds: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_MAIN_COOLDOWN", 18.0))
    four_b_cooldown_seconds: float = field(default_factory=lambda: _env_float("ERIS_BUDGET_4B_COOLDOWN", 60.0))
    assume_gtx_1650ti_4gb: bool = field(default_factory=lambda: _env_flag("ERIS_ASSUME_4GB_VRAM", True))
    nvidia_smi_timeout: float = 0.35


class ModelBudgetPolicy:
    """Quyền phủ quyết model request."""

    def __init__(self, config: ModelBudgetPolicyConfig | None = None, logger: Any = None) -> None:
        self.config = config or ModelBudgetPolicyConfig()
        self.logger = logger
        self.last_main_started_at = 0.0
        self.last_main_finished_at = 0.0
        self.last_4b_started_at = 0.0
        self.last_4b_finished_at = 0.0
        self.last_snapshot = ResourceSnapshot()

    def capture(self, *, active_app: str = "", active_window_title: str = "") -> ResourceSnapshot:
        """Đo tài nguyên best-effort.

        Không có psutil/nvidia-smi thì vẫn trả snapshot thay vì chết. Đáng tiếc là runtime
        cần sống trong thế giới thật, nơi dependency thiếu như cơm bữa.
        """

        cpu = 0.0
        ram = 0.0
        notes: list[str] = []
        try:
            import psutil  # type: ignore

            cpu = float(psutil.cpu_percent(interval=0.0))
            ram = float(psutil.virtual_memory().percent)
        except Exception as exc:
            notes.append(f"psutil_unavailable:{type(exc).__name__}")

        gpu_util, vram_used, vram_total, temp = self._capture_nvidia_smi(notes)
        app_blob = f"{active_app} {active_window_title}".lower()
        heavy = any(x in app_blob for x in ("game", "steam", "unity", "unreal", "genshin", "wuthering", "elden", "skyrim"))
        compile_or_godot = any(x in app_blob for x in ("godot", "visual studio", "msbuild", "compile", "pytest", "cmake", "ninja", "gcc", "clang"))
        now = time.time()
        main_recent = (now - max(self.last_main_started_at, self.last_main_finished_at)) < self.config.main_cooldown_seconds
        snapshot = ResourceSnapshot(
            cpu_percent=cpu,
            ram_percent=ram,
            gpu_util_percent=gpu_util,
            vram_used_mb=vram_used,
            vram_total_mb=vram_total,
            gpu_temperature_c=temp,
            active_app=str(active_app or ""),
            active_window_title=str(active_window_title or ""),
            is_game_or_heavy_app=heavy,
            is_compile_or_godot=compile_or_godot,
            main_cognition_recent=main_recent,
            telemetry_ok=not any(note.startswith("psutil_unavailable") for note in notes),
            notes=tuple(notes),
        )
        self.last_snapshot = snapshot
        return snapshot

    def can_run(
        self,
        tier: ModelTier,
        *,
        resource_snapshot: ResourceSnapshot | None = None,
        reason: str = "",
    ) -> BudgetDecision:
        if not self.config.enabled:
            snapshot = resource_snapshot or self.capture()
            return BudgetDecision("allow", True, tier, "budget_policy_disabled", snapshot, debug={"reason": reason})
        snapshot = resource_snapshot or self.capture()
        now = time.time()
        reasons: list[str] = []
        hard = False

        if snapshot.cpu_percent >= self.config.cpu_block_percent:
            reasons.append("cpu_high")
        if snapshot.ram_percent >= self.config.ram_block_percent:
            reasons.append("ram_high")
        if snapshot.gpu_temperature_c and snapshot.gpu_temperature_c >= self.config.gpu_temp_block_c:
            reasons.append("gpu_hot")
            hard = True

        vram_pct = snapshot.vram_percent
        gpu_busy = snapshot.gpu_util_percent >= self.config.gpu_block_percent
        vram_busy = bool(vram_pct and vram_pct >= self.config.vram_block_percent)

        if tier in {"subconscious_4b", "vision_compressor"}:
            if snapshot.is_game_or_heavy_app:
                reasons.append("heavy_app_or_game_active")
                hard = True
            if snapshot.is_compile_or_godot:
                reasons.append("compile_or_godot_active")
            if snapshot.main_cognition_recent:
                reasons.append("main_cognition_recent")
            if gpu_busy:
                reasons.append("gpu_busy")
            if vram_busy:
                reasons.append("vram_busy")
            if self.config.assume_gtx_1650ti_4gb and snapshot.vram_total_mb and snapshot.vram_total_mb <= 4600 and snapshot.vram_used_mb >= 2600:
                reasons.append("4gb_vram_protected")
                hard = True
            if now - self.last_4b_started_at < self.config.four_b_cooldown_seconds:
                reasons.append("4b_cooldown")
        elif tier == "main_cognition":
            if gpu_busy and vram_busy:
                reasons.append("gpu_and_vram_busy")
            if snapshot.cpu_percent >= 96 or snapshot.ram_percent >= 94:
                reasons.append("system_near_limit")
                hard = True
        elif tier == "sensory_0_6b":
            if snapshot.cpu_percent >= 97 or snapshot.ram_percent >= 95:
                reasons.append("system_near_limit_for_sensory")
                hard = True

        allowed = not reasons
        verdict: BudgetVerdict = "allow" if allowed else ("kill" if hard else "block")
        return BudgetDecision(
            verdict=verdict,
            allowed=allowed,
            tier=tier,
            reason=";".join(reasons) if reasons else "ok",
            resource_snapshot=snapshot,
            hard_veto=hard,
            cooldown_seconds=self._cooldown_for(tier, now),
            debug={"request_reason": reason, "vram_percent": vram_pct},
        )

    def mark_started(self, tier: ModelTier) -> None:
        now = time.time()
        if tier == "main_cognition":
            self.last_main_started_at = now
        elif tier in {"subconscious_4b", "vision_compressor"}:
            self.last_4b_started_at = now

    def mark_finished(self, tier: ModelTier) -> None:
        now = time.time()
        if tier == "main_cognition":
            self.last_main_finished_at = now
        elif tier in {"subconscious_4b", "vision_compressor"}:
            self.last_4b_finished_at = now

    def veto_or_raise(self, tier: ModelTier, *, resource_snapshot: ResourceSnapshot | None = None, reason: str = "") -> BudgetDecision:
        decision = self.can_run(tier, resource_snapshot=resource_snapshot, reason=reason)
        if not decision.allowed:
            raise RuntimeError(f"model_budget_veto:{tier}:{decision.reason}")
        return decision

    def _cooldown_for(self, tier: str, now: float) -> float:
        if tier == "main_cognition":
            return max(0.0, self.config.main_cooldown_seconds - (now - self.last_main_started_at))
        if tier in {"subconscious_4b", "vision_compressor"}:
            return max(0.0, self.config.four_b_cooldown_seconds - (now - self.last_4b_started_at))
        return 0.0

    def _capture_nvidia_smi(self, notes: list[str]) -> tuple[float, float, float, float]:
        try:
            proc = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=self.config.nvidia_smi_timeout,
            )
            if proc.returncode != 0:
                notes.append("nvidia_smi_nonzero")
                return 0.0, 0.0, 0.0, 0.0
            line = (proc.stdout or "").strip().splitlines()[0]
            parts = [x.strip() for x in line.split(",")]
            return (_safe_float(parts[0]), _safe_float(parts[1]), _safe_float(parts[2]), _safe_float(parts[3]))
        except Exception as exc:
            notes.append(f"nvidia_smi_unavailable:{type(exc).__name__}")
            return 0.0, 0.0, 0.0, 0.0
