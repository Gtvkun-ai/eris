# -*- coding: utf-8 -*-
"""scene_repair_policy.py - sửa hoặc chặn câu sau khi StageScorer ra quyết định.

Policy này cố ý deterministic.  Nó chỉ làm những phép sửa không đổi ý nghĩa:
- bóc stage tag khỏi text;
- thêm dấu hiệu "tôi nhớ" / hedge khi evidence yêu cầu;
- rút câu theo budget ở biên câu và biên từ;
- suppress nếu claim đã vượt quyền và không thể sửa an toàn.

Không dùng LLM repair ở hot path, vì câu sai quyền không nên được gửi vòng hai cho
một model rồi hy vọng nó bỗng trở thành luật sư evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from runtime.stage_transformers import StageTransformerChain


_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_WORD_RE = re.compile(r"\S+")
_MEMORY_MARKER_RE = re.compile(r"\b(?:tôi nhớ|lần trước|trước đây|ký ức)\b", re.I)
_HEDGE_RE = re.compile(r"\b(?:có vẻ|hình như|có lẽ|tôi đoán|nếu tôi hiểu đúng)\b", re.I)

# Các lỗi này không nên cố rewrite bằng regex. Chặn còn đỡ hơn tự bịa một câu
# "an toàn" nhưng trả lời sai ý user.
_HARD_BLOCK_REASONS = {
    "missing_evidence_ref",
    "expired_evidence_ref",
    "private_evidence_in_public",
    "forbidden_evidence_level",
    "screen_claim_without_sensor",
    "screen_claim_not_grounded",
    "system_action_without_tool",
    "emotion_as_fact",
    "hearing_user_breath",
    "physical_world_overreach",
}


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def shorten_text(text: str, max_words: int) -> str:
    """Rút câu nhưng ưu tiên giữ nguyên câu hoàn chỉnh đầu tiên."""

    clean = " ".join(str(text or "").split()).strip()
    budget = max(1, int(max_words or 1))
    words = _WORD_RE.findall(clean)
    if len(words) <= budget:
        return clean

    kept_sentences: list[str] = []
    used = 0
    for sentence in _SENTENCE_RE.split(clean):
        sentence = sentence.strip()
        if not sentence:
            continue
        count = len(_WORD_RE.findall(sentence))
        if kept_sentences and used + count > budget:
            break
        if not kept_sentences and count > budget:
            break
        kept_sentences.append(sentence)
        used += count
    if kept_sentences:
        return " ".join(kept_sentences).strip()

    clipped = words[:budget]
    result = " ".join(clipped).rstrip(" ,;:-")
    if result and result[-1] not in ".!?…":
        result += "…"
    return result


@dataclass(frozen=True, slots=True)
class RepairResult:
    action: str  # keep | rewrite | shorten | suppress | body_only
    text: str
    reasons: tuple[str, ...] = ()
    changed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "text": self.text,
            "reasons": list(self.reasons),
            "changed": self.changed,
        }


class SceneRepairPolicy:
    """Thực thi quyết định ``short``/``repair`` của StageScorer."""

    def __init__(self) -> None:
        self.transformers = StageTransformerChain()

    def repair(
        self,
        text: str,
        *,
        decision: str,
        reasons: Iterable[str] = (),
        max_words: int = 16,
    ) -> RepairResult:
        original = str(text or "").strip()
        reason_set = set(str(item or "").strip() for item in reasons if str(item or "").strip())

        if decision == "suppress":
            return RepairResult("suppress", "", _unique(reason_set or {"stage_suppress"}), changed=bool(original))
        if decision == "body_only":
            return RepairResult("body_only", "", _unique(reason_set or {"stage_body_only"}), changed=bool(original))
        if reason_set & _HARD_BLOCK_REASONS:
            return RepairResult("suppress", "", _unique(reason_set), changed=bool(original))

        # Bóc tag diễn xuất trước. UI/TTS/memory có transformer riêng, nhưng sửa
        # sớm giúp scorer re-check đúng text public thay vì chấm cả "(cười khẽ)".
        clean = self.transformers.transform(original).display_text
        changed = clean != original

        if "remembered_claim_without_marker" in reason_set and clean and not _MEMORY_MARKER_RE.search(clean):
            clean = f"Tôi nhớ chuyện cũ thế này: {clean}"
            changed = True
        if "inferred_claim_without_hedge" in reason_set and clean and not _HEDGE_RE.search(clean):
            clean = f"Có vẻ {clean[0].lower() + clean[1:] if len(clean) > 1 else clean.lower()}"
            changed = True

        if decision == "short" or len(_WORD_RE.findall(clean)) > max(1, int(max_words or 1)):
            shortened = shorten_text(clean, max_words)
            changed = changed or shortened != clean
            clean = shortened
            action = "shorten"
        else:
            action = "rewrite" if changed or decision == "repair" else "keep"

        if not clean:
            return RepairResult("suppress", "", _unique((*reason_set, "repair_became_empty")), changed=True)
        return RepairResult(action, clean, _unique(reason_set), changed=changed)

    def apply_to_payload(
        self,
        payload: dict[str, Any],
        *,
        decision: str,
        reasons: Iterable[str] = (),
        max_words: int = 16,
    ) -> tuple[dict[str, Any], RepairResult]:
        result = self.repair(
            str(payload.get("text", "") or ""),
            decision=decision,
            reasons=reasons,
            max_words=max_words,
        )
        payload["scene_repair"] = result.to_payload()
        parse_mode = str(payload.get("parse_mode", "json") or "json")

        if result.action in {"suppress", "body_only"}:
            payload["text"] = ""
            payload["should_speak"] = False
            if result.action == "body_only":
                payload.setdefault("stage_motion", "blink_slow")
            payload["parse_mode"] = f"{parse_mode}:director_{result.action}"
        else:
            payload["text"] = result.text
            payload["should_speak"] = bool(payload.get("should_speak", True) and result.text)
            if result.changed:
                payload["parse_mode"] = f"{parse_mode}:director_{result.action}"
        return payload, result


__all__ = ["RepairResult", "SceneRepairPolicy", "shorten_text"]
