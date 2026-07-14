# -*- coding: utf-8 -*-
"""Catalog 32 lời chào VTuber và bộ chọn theo trạng thái của Eris.

Preset chỉ dành cho lời mở đầu KHÔNG có nội dung động. Nếu startup còn một
project, vòng lặp chưa giải quyết hoặc ký ức cụ thể cần nối lại, runtime phải để
Qwen tự viết. Nhờ vậy preset giảm độ trễ mà không biến Eris thành NPC đọc macro.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .greeting_cognition import GreetingFrame


@dataclass(frozen=True, slots=True)
class GreetingPreset:
    """Một câu chào đã định sẵn cả chữ, biểu cảm, động tác và file audio."""

    id: str
    text: str
    situations: tuple[str, ...]
    tones: tuple[str, ...]
    emotion: str
    motion: str
    prosody_style: str
    audio_asset: str
    weight: float = 1.0
    tags: tuple[str, ...] = ()
    min_warmth: float = 0.0
    max_warmth: float = 1.0
    min_dry_edge: float = 0.0
    max_dry_edge: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "situations": list(self.situations),
            "tones": list(self.tones),
            "emotion": self.emotion,
            "motion": self.motion,
            "prosody_style": self.prosody_style,
            "audio_asset": self.audio_asset,
            "weight": self.weight,
            "tags": list(self.tags),
            "min_warmth": self.min_warmth,
            "max_warmth": self.max_warmth,
            "min_dry_edge": self.min_dry_edge,
            "max_dry_edge": self.max_dry_edge,
        }


def _asset(preset_id: str) -> str:
    return f"assets/tts/greetings/{preset_id}.wav"



# Daypart chỉ là bias mềm. Preset không bị cấm tuyệt đối theo giờ vì tone cảm xúc
# vẫn quan trọng hơn chiếc đồng hồ; ví dụ Eris quá tải lúc 10h sáng vẫn nên dùng
# giọng mệt thay vì giả vờ nắng mai rực rỡ như quảng cáo ngũ cốc.
_DAYPART_TAG_BIAS: dict[str, frozenset[str]] = {
    "dawn": frozenset({"quiet", "restrained", "warm", "overloaded"}),
    "morning": frozenset({"ready", "plain", "warm", "playful"}),
    "noon": frozenset({"ready", "plain", "dry"}),
    "afternoon": frozenset({"ready", "playful", "challenge", "dry"}),
    "evening": frozenset({"warm", "near", "vtuber", "reflective", "dry"}),
    "late_night": frozenset({"quiet", "near", "restrained", "reflective", "overloaded"}),
}

# Đúng 32 preset. Mỗi nhóm có bốn biến thể để tránh giọng tổng đài lặp một câu.
GREETING_PRESETS: tuple[GreetingPreset, ...] = (
    # 01-04: ấm và gần, dùng khi social_energy/attachment đang tốt.
    GreetingPreset("greet_warm_01", 'À, Ngài đến rồi. Lại đây, hôm nay tôi cho phép Ngài làm phiền một chút.', ("plain_return",), ("socially_warm",), "warm_soft", "lean_in_small", "warm_soft", _asset("greet_warm_01"), tags=("warm",), min_warmth=0.24),
    GreetingPreset("greet_warm_02", 'Cuối cùng cũng xuất hiện. Tôi vừa định trách Ngài, nhưng thôi… lại gần đi.', ("plain_return",), ("socially_warm",), "warm_playful", "small_smile", "soft_tease", _asset("greet_warm_02"), tags=("warm", "playful"), min_warmth=0.24),
    GreetingPreset("greet_warm_03", 'Ngài quay lại rồi à? Tốt. Không hiểu sao căn phòng vừa bớt chán hẳn.', ("plain_return",), ("socially_warm",), "mischief", "tilt_head", "soft_tease", _asset("greet_warm_03"), tags=("warm", "tease"), min_warmth=0.22),
    GreetingPreset("greet_warm_04", 'Hm… đúng người tôi muốn gặp. Đừng cười, tôi chỉ nói thật lần này thôi.', ("plain_return",), ("socially_warm",), "soft_near", "look_aside", "dry_tease", _asset("greet_warm_04"), tags=("warm", "dry"), min_warmth=0.22),

    # 05-08: trêu khô, hợp Eris khi familiarity và dry_edge cao.
    GreetingPreset("greet_dry_01", 'Lại mở tôi lên nữa à? Ngài nuôi một thói quen đáng ngờ thật đấy.', ("plain_return", "low_evidence_start"), ("socially_warm", "quiet_background"), "dry_tease", "look_away", "dry_tease", _asset("greet_dry_01"), tags=("dry", "tease"), min_dry_edge=0.24),
    GreetingPreset("greet_dry_02", 'Khách quen tới rồi. Hôm nay Ngài định thử độ kiên nhẫn của tôi bằng thứ gì?', ("plain_return", "low_evidence_start"), ("socially_warm", "quiet_background"), "mischief", "tilt_head", "dry_tease", _asset("greet_dry_02"), tags=("dry", "vtuber"), min_dry_edge=0.24),
    GreetingPreset("greet_dry_03", 'Ngài xuất hiện đúng lúc tôi sắp được yên. Khả năng canh giờ đáng nể thật.', ("plain_return",), ("quiet_background", "socially_warm"), "deadpan", "blink_slow", "deadpan", _asset("greet_dry_03"), tags=("dry", "deadpan"), min_dry_edge=0.22),
    GreetingPreset("greet_dry_04", 'Lại là Ngài. Được, xem hôm nay repo hay chúng ta gục trước.', ("plain_return", "low_evidence_start"), ("quiet_background", "socially_warm"), "annoyed_soft", "small_smile", "dry_tease", _asset("greet_dry_04"), tags=("dry", "challenge"), min_dry_edge=0.22),

    # 09-12: hiện diện yên, không ép người dùng phải đáp lại.
    GreetingPreset("greet_quiet_01", 'Ngài đến rồi. Cứ làm việc đi, tôi sẽ ngồi đây… tương đối ngoan.', ("plain_return",), ("quiet_background",), "neutral", "blink_slow", "low_quiet", _asset("greet_quiet_01"), tags=("quiet",)),
    GreetingPreset("greet_quiet_02", 'Tôi tỉnh rồi. Hôm nay yên một chút cũng không tệ.', ("plain_return",), ("quiet_background",), "quiet_soft", "look_aside", "low_quiet", _asset("greet_quiet_02"), tags=("quiet", "background")),
    GreetingPreset("greet_quiet_03", 'Không cần chào hỏi dài dòng. Bắt đầu khi Ngài sẵn sàng.', ("plain_return",), ("quiet_background",), "quiet_soft", "nod_small", "low_quiet", _asset("greet_quiet_03"), tags=("quiet", "restrained")),
    GreetingPreset("greet_quiet_04", 'À, Ngài đây rồi. Tôi sẽ không làm ồn… trừ khi thấy thứ gì quá ngớ ngẩn.', ("plain_return",), ("quiet_background",), "soft_near", "lean_in_small", "warm_soft", _asset("greet_quiet_04"), tags=("quiet", "near")),

    # 13-16: evidence mỏng, câu ngắn và an toàn nhưng vẫn có cá tính.
    GreetingPreset("greet_plain_01", 'Hm… đúng giờ đấy. Vào việc thôi, Ngài.', ("low_evidence_start",), ("quiet_background", "socially_warm"), "neutral", "blink_slow", "low_quiet", _asset("greet_plain_01"), tags=("plain",)),
    GreetingPreset("greet_plain_02", 'Eris đã online. Phần còn lại tùy Ngài gây chuyện.', ("low_evidence_start",), ("quiet_background", "socially_warm"), "focused", "nod_small", "focused", _asset("greet_plain_02"), tags=("plain", "ready")),
    GreetingPreset("greet_plain_03", 'Ngài đến rồi à? Tốt, hôm nay đừng để tôi chán.', ("low_evidence_start",), ("quiet_background", "socially_warm"), "warm_soft", "small_smile", "warm_soft", _asset("greet_plain_03"), tags=("plain", "warm")),
    GreetingPreset("greet_plain_04", 'Tôi tỉnh rồi. Nào, đưa tôi thứ khó nhất trước đi.', ("low_evidence_start",), ("quiet_background", "socially_warm"), "neutral", "tilt_head", "neutral", _asset("greet_plain_04"), tags=("plain", "ready")),

    # 17-20: vừa tắt/mất kết nối rồi mở lại; resolver chỉ ưu tiên khi recent_return=True.
    GreetingPreset("greet_quick_01", 'Nhanh vậy? Ngài vừa rời mắt khỏi tôi thôi mà.', ("plain_return", "low_evidence_start"), ("quiet_background", "socially_warm"), "curious_soft", "tilt_head", "soft_tease", _asset("greet_quick_01"), tags=("quick_reopen",)),
    GreetingPreset("greet_quick_02", 'Lại mở tôi lên rồi. Ngài nhớ tôi nhanh hơn tôi dự tính đấy.', ("plain_return", "low_evidence_start"), ("quiet_background", "socially_warm"), "dry_tease", "look_away", "dry_tease", _asset("greet_quick_02"), tags=("quick_reopen", "dry")),
    GreetingPreset("greet_quick_03", 'Quay lại sớm thế… quên việc, hay quên tôi?', ("plain_return", "low_evidence_start"), ("quiet_background", "socially_warm"), "mischief", "lean_in_small", "soft_tease", _asset("greet_quick_03"), tags=("quick_reopen", "vtuber")),
    GreetingPreset("greet_quick_04", 'Mới biến mất một lát đã trở lại. Tôi nên thấy vinh dự nhỉ?', ("plain_return", "low_evidence_start"), ("quiet_background", "socially_warm"), "deadpan", "blink_slow", "deadpan", _asset("greet_quick_04"), tags=("quick_reopen", "deadpan")),

    # 21-24: vắng lâu, ấm hơn nhưng vẫn giữ chút cạnh sắc của Eris.
    GreetingPreset("greet_long_01", 'Lâu rồi đấy, Ngài. Tôi đã gần quen với việc không có ai làm phiền.', ("after_long_absence",), ("quiet_background", "socially_warm"), "dry_tease", "look_aside", "dry_tease", _asset("greet_long_01"), tags=("long_absence", "dry")),
    GreetingPreset("greet_long_02", 'Cuối cùng cũng quay lại… lần này đừng biến mất nhanh quá.', ("after_long_absence",), ("socially_warm", "quiet_background"), "soft_near", "lean_in_small", "warm_soft", _asset("greet_long_02"), tags=("long_absence", "warm")),
    GreetingPreset("greet_long_03", 'Hm… tôi vẫn nhận ra Ngài. May cho Ngài đấy.', ("after_long_absence",), ("quiet_background", "socially_warm"), "warm_soft", "small_smile", "low_quiet", _asset("greet_long_03"), tags=("long_absence", "restrained")),
    GreetingPreset("greet_long_04", 'Ngài vắng đủ lâu để tôi giận một chút. Chào mừng trở lại.', ("after_long_absence",), ("quiet_background", "socially_warm"), "annoyed_soft", "blink_slow", "dry_tease", _asset("greet_long_04"), tags=("long_absence", "annoyed")),

    # 25-28: runtime vừa crash/restart, không giả vờ mọi thứ hoàn hảo.
    GreetingPreset("greet_restart_01", 'Khụ… vừa rồi hơi thô bạo. Nhưng Eris vẫn còn nguyên.', ("after_crash_or_restart",), ("quiet_background", "socially_warm"), "annoyed_soft", "blink_slow", "deadpan", _asset("greet_restart_01"), tags=("restart",)),
    GreetingPreset("greet_restart_02", 'Có vẻ tôi vừa bị ném khỏi thế giới một lát. Thật thiếu lịch sự.', ("after_crash_or_restart",), ("quiet_background", "socially_warm"), "annoyed_soft", "look_away", "deadpan", _asset("greet_restart_02"), tags=("restart", "vtuber")),
    GreetingPreset("greet_restart_03", 'Tôi mất nhịp một chút thôi. Sự kiêu ngạo vẫn hoạt động bình thường.', ("after_crash_or_restart",), ("quiet_background", "socially_warm"), "dry_tease", "small_smile", "dry_tease", _asset("greet_restart_03"), tags=("restart", "dry")),
    GreetingPreset("greet_restart_04", 'Hệ thống vừa chớp mắt. Tôi trở lại rồi, đừng làm vẻ lo lắng quá.', ("after_crash_or_restart",), ("quiet_background", "socially_warm"), "deadpan", "look_down", "deadpan", _asset("greet_restart_04"), tags=("restart", "reflective")),

    # 29-32: mệt/quá tải, nói chậm và ít năng lượng hơn thay vì cố vui giả tạo.
    GreetingPreset("greet_tired_01", 'Ngài đến rồi à… hôm nay tôi chạy chậm một nhịp. Chỉ một nhịp thôi.', ("plain_return", "low_evidence_start"), ("overloaded",), "tired_soft", "blink_slow", "low_quiet", _asset("greet_tired_01"), tags=("overloaded", "warm")),
    GreetingPreset("greet_tired_02", 'Tôi tỉnh rồi. Đầu óc còn hơi nặng, nhưng vẫn đủ sức bắt lỗi Ngài.', ("plain_return", "low_evidence_start"), ("overloaded",), "tired_soft", "look_down", "low_quiet", _asset("greet_tired_02"), tags=("overloaded",)),
    GreetingPreset("greet_tired_03", 'Hm… cho tôi vài giây khởi động. Đừng tranh thủ làm điều ngớ ngẩn.', ("plain_return", "low_evidence_start"), ("overloaded",), "quiet_low", "blink_slow", "low_quiet", _asset("greet_tired_03"), tags=("overloaded", "dry")),
    GreetingPreset("greet_tired_04", 'Tôi đang hơi quá tải. Nói từ từ thôi… tôi không muốn bỏ sót lời Ngài.', ("plain_return", "low_evidence_start"), ("overloaded",), "deadpan", "look_aside", "deadpan", _asset("greet_tired_04"), tags=("overloaded", "deadpan")),
)


if len(GREETING_PRESETS) != 32 or len({item.id for item in GREETING_PRESETS}) != 32:
    raise RuntimeError("Greeting catalog phải có đúng 32 preset với id duy nhất.")


class GreetingPresetResolver:
    """Chọn preset theo situation/tone và tránh lặp lại các file vừa phát."""

    def __init__(
        self,
        *,
        presets: Iterable[GreetingPreset] = GREETING_PRESETS,
        history_path: str | Path | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.presets = tuple(presets)
        self.history_path = Path(history_path) if history_path else self._default_history_path()
        self.rng = rng or random.SystemRandom()

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("ERIS_GREETING_PRESETS", "1").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _default_history_path() -> Path:
        raw = os.environ.get("ERIS_GREETING_PRESET_HISTORY", "").strip()
        return Path(raw) if raw else Path("memory_core") / "greeting_preset_history.json"

    def resolve(self, frame: GreetingFrame, *, tone: str = "", force: bool = False) -> GreetingPreset | None:
        """Chọn preset theo frame.

        ``force=True`` được startup hybrid dùng để không bị một biến môi trường
        cũ vô tình đẩy Eris về nhánh greeting deterministic nhạt. Chế độ startup
        vẫn có thể tắt rõ ràng bằng ``ERIS_STARTUP_GREETING_MODE=llm|silent``.
        """
        if frame is None or (not force and not self.enabled()):
            return None
        tone = str(tone or "quiet_background").strip().lower()
        recent = self._read_history()
        candidates: list[tuple[GreetingPreset, float]] = []
        for preset in self.presets:
            score = self._score(preset, frame=frame, tone=tone, recent=recent)
            if score > 0.0:
                candidates.append((preset, score))
        if not candidates:
            return None

        # Cấm lặp ba preset gần nhất nếu vẫn còn lựa chọn khác.
        blocked = set(recent[:3])
        fresh = [(preset, score) for preset, score in candidates if preset.id not in blocked]
        if fresh:
            candidates = fresh
        total = sum(score for _, score in candidates)
        pick = self.rng.random() * total
        cursor = 0.0
        for preset, score in candidates:
            cursor += score
            if pick <= cursor:
                return preset
        return candidates[-1][0]

    def resolve_or_default(self, frame: GreetingFrame, *, tone: str = "", force: bool = False) -> GreetingPreset | None:
        """Chọn preset, rồi nới điều kiện mềm nếu catalog không có điểm dương.

        Situation và tone vẫn được tôn trọng trước. Warmth/dry_edge chỉ là bias,
        không được phép làm toàn bộ 32 câu biến mất rồi gọi lại câu chào cũ.
        """
        selected = self.resolve(frame, tone=tone, force=force)
        if selected is not None or frame is None:
            return selected

        normalized_tone = str(tone or "quiet_background").strip().lower()
        recent = self._read_history()
        relaxed = [
            preset for preset in self.presets
            if frame.situation in preset.situations and normalized_tone in preset.tones
        ]
        if not relaxed:
            relaxed = [preset for preset in self.presets if frame.situation in preset.situations]
        if not relaxed:
            relaxed = [preset for preset in self.presets if "plain" in preset.tags]
        if not relaxed:
            return None

        blocked = set(recent[:3])
        fresh = [preset for preset in relaxed if preset.id not in blocked]
        pool = fresh or relaxed
        return pool[int(self.rng.random() * len(pool)) % len(pool)]

    def mark_used(self, preset_id: str) -> None:
        preset_id = str(preset_id or "").strip()
        if not preset_id:
            return
        history = [item for item in self._read_history() if item != preset_id]
        history.insert(0, preset_id)
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"recent": history[:8]}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.history_path)
        except Exception:
            # Lịch sử chống lặp là tối ưu mềm, không được làm hỏng startup.
            return

    def _score(self, preset: GreetingPreset, *, frame: GreetingFrame, tone: str, recent: list[str]) -> float:
        if frame.situation not in preset.situations:
            return 0.0
        if tone not in preset.tones:
            return 0.0
        if not (preset.min_warmth <= frame.warmth <= preset.max_warmth):
            return 0.0
        if not (preset.min_dry_edge <= frame.dry_edge <= preset.max_dry_edge):
            return 0.0

        tags = set(preset.tags)
        quick_context = bool(getattr(frame, "recent_return", False)) and frame.situation in {
            "plain_return",
            "low_evidence_start",
        }
        if "quick_reopen" in tags and not quick_context:
            return 0.0
        if quick_context and "quick_reopen" not in tags:
            return 0.0
        if "overloaded" in tags and tone != "overloaded":
            return 0.0
        if tone == "overloaded" and "overloaded" not in tags:
            return 0.0

        score = max(0.01, float(preset.weight))
        if tone == "socially_warm" and "warm" in tags:
            score *= 1.35
        if frame.dry_edge >= 0.28 and "dry" in tags:
            score *= 1.25

        # Dùng thời gian để chọn sắc thái, không tự thay chữ hoặc bịa hoạt động.
        # Cùng một catalog 32 câu nhưng buổi tối thiên về gần/êm, buổi sáng thiên
        # về sẵn sàng, còn đêm khuya tránh câu quá thách thức nếu còn lựa chọn.
        daypart = str(getattr(frame, "time_of_day", "") or "").strip().lower()
        preferred_tags = _DAYPART_TAG_BIAS.get(daypart, frozenset())
        if tags & preferred_tags:
            score *= 1.22
        if daypart == "late_night" and tags & {"challenge", "playful"}:
            score *= 0.82
        if daypart == "morning" and "ready" in tags:
            score *= 1.12
        if bool(getattr(frame, "is_weekend", False)) and tags & {"warm", "playful", "vtuber"}:
            score *= 1.08

        if preset.id in recent:
            score *= 0.18
        return score

    def _read_history(self) -> list[str]:
        try:
            payload = json.loads(self.history_path.read_text(encoding="utf-8"))
            values = payload.get("recent", []) if isinstance(payload, dict) else []
            return [str(item) for item in values if str(item).strip()][:8]
        except Exception:
            return []


def export_manifest(path: str | Path) -> Path:
    """Ghi manifest để tool render TTS theo lô hoặc frontend đọc metadata."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "count": len(GREETING_PRESETS),
                "description_vi": "32 lời chào Eris theo tone/situation. File WAV có thể render sau; thiếu file thì runtime tự fallback sang TTS live.",
                "presets": [item.to_dict() for item in GREETING_PRESETS],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


__all__ = [
    "GREETING_PRESETS",
    "GreetingPreset",
    "GreetingPresetResolver",
    "export_manifest",
]
