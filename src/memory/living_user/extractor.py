# -*- coding: utf-8 -*-
"""Trích xuất patch profile từ semantic claim và tín hiệu hội thoại.

Extractor có hai nhánh:
- Nhánh deterministic cho dữ kiện đã được memory semantic parser xác nhận.
- Nhánh model adapter tùy chọn cho pattern rộng hơn.

Model chỉ đề xuất ``ProfileOperation``. Store mới là nơi quyết định mutation có
được chấp nhận hay không. Nhờ vậy một model hưng phấn không thể tự viết tiểu sử
người dùng như biên kịch phim dài tập.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from memory.semantic_memory import normalize_text

from .models import ProfileOperation, UserMemoryScope, clamp01, compact_text, normalize_path


class UserProfileModelAdapter(Protocol):
    """Contract nhỏ cho model tổng hợp profile.

    Adapter runtime có thể dùng API bất kỳ, miễn trả mapping JSON. Package này
    không phụ thuộc trực tiếp DeepSeek/Gemini/OpenAI nên test được độc lập.
    """

    def propose_profile_operations(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        ...

    def summarize_episode(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        ...


@dataclass(slots=True)
class ProfileExtractionConfig:
    min_model_confidence: float = 0.62
    min_inferred_confidence: float = 0.68
    max_operations_per_turn: int = 8


class UserProfileExtractor:
    def __init__(self, *, model_adapter: UserProfileModelAdapter | None = None, config: ProfileExtractionConfig | None = None) -> None:
        self.model_adapter = model_adapter
        self.config = config or ProfileExtractionConfig()

    def from_semantic_items(
        self,
        items: Iterable[Any],
        *,
        scope: UserMemoryScope | None = None,
    ) -> tuple[ProfileOperation, ...]:
        """Chuyển semantic memory item thành profile patch tổng quát.

        Không liệt kê ``user.name``, ``user.gender``... Predicate nào bắt đầu bằng
        ``user.`` đều có thể trở thành profile path. Đây mới là open schema thật.
        """
        out: list[ProfileOperation] = []
        for item in items:
            metadata = dict(getattr(item, "metadata", {}) or {})
            fact_key = normalize_path(getattr(item, "fact_key", "") or metadata.get("fact_key") or "")
            if not fact_key.startswith("user."):
                continue
            value = getattr(item, "semantic_value", "") or metadata.get("value")
            if value in (None, ""):
                continue
            status = str(getattr(item, "status", "active") or "active")
            if status not in {"active", "tentative"}:
                continue
            evidence_ids = tuple(getattr(item, "evidence_ids", ()) or ())
            if not evidence_ids:
                continue
            confidence = clamp01(getattr(item, "confidence", 0.0), 0.5)
            cardinality = str(metadata.get("cardinality") or "single")
            explicitness = str(metadata.get("explicitness") or "explicit")
            sensitivity = str(metadata.get("sensitivity") or _sensitivity_for_path(fact_key))
            out.append(ProfileOperation(
                op="reinforce",
                path=fact_key,
                value=value,
                confidence=confidence,
                explicitness=explicitness if explicitness in {"explicit", "observed", "inferred"} else "explicit",  # type: ignore[arg-type]
                sensitivity=sensitivity if sensitivity in {"normal", "personal", "private", "sensitive"} else "normal",  # type: ignore[arg-type]
                scope=scope or _scope_from_metadata(metadata),
                cardinality="multi" if cardinality == "multi" else "single",
                evidence_ids=evidence_ids,
                reason="Đồng bộ từ semantic claim đã được commit.",
                source="semantic_memory_sync",
                metadata={"semantic_item_id": str(getattr(item, "id", "") or "")},
            ))
        return tuple(out)

    def from_turn(
        self,
        user_text: str,
        *,
        evidence_ids: Iterable[str],
        context: Mapping[str, Any] | None = None,
        existing_profile: Mapping[str, Any] | None = None,
    ) -> tuple[ProfileOperation, ...]:
        """Trích xuất patch từ một lượt user.

        Nhánh rule chỉ học các tín hiệu hành vi rõ và generic. Fact nội dung được
        semantic parser xử lý để tránh có hai bộ parser tranh nhau quyền giải nghĩa.
        """
        raw = compact_text(user_text, 1400)
        ids = tuple(dict.fromkeys(str(x) for x in evidence_ids if str(x).strip()))
        if not raw or not ids:
            return ()
        context = dict(context or {})
        scope = _scope_from_context(context)
        ops = list(self._behavioral_rules(raw, ids, scope=scope, context=context))

        adapter = self.model_adapter
        if adapter is not None:
            payload = {
                "user_text": raw,
                "evidence_ids": list(ids),
                "scope": scope.to_dict(),
                "context": context,
                "existing_profile": existing_profile or {},
                "contract": {
                    "operations": ["add", "reinforce", "update", "weaken", "supersede", "merge", "archive", "delete"],
                    "explicitness": ["explicit", "observed", "inferred"],
                    "rule": "Không suy diễn thuộc tính nhạy cảm; mọi operation phải có evidence.",
                },
            }
            try:
                response = adapter.propose_profile_operations(payload)
            except Exception:
                response = None
            ops.extend(self._parse_model_operations(response, ids=ids, default_scope=scope))
        return tuple(_dedupe_operations(ops)[: self.config.max_operations_per_turn])

    def _behavioral_rules(
        self,
        raw: str,
        evidence_ids: tuple[str, ...],
        *,
        scope: UserMemoryScope,
        context: Mapping[str, Any],
    ) -> tuple[ProfileOperation, ...]:
        norm = normalize_text(raw)
        out: list[ProfileOperation] = []

        # Ngôn ngữ là tín hiệu rất chắc nhưng vẫn ghi là observed, vì một lượt tiếng
        # Việt không đồng nghĩa người dùng muốn mọi cuộc trò chuyện cả đời bằng Việt.
        vietnamese_markers = (" toi ", " tui ", " minh ", " ban ", " không ", " ko ", " lỗi ", " làm ", " gửi ")
        padded = f" {raw.lower()} "
        if any(mark in padded for mark in vietnamese_markers) or _looks_vietnamese(raw):
            out.append(_op(
                "communication.preferred_language", "vi", evidence_ids, scope,
                confidence=0.78, explicitness="observed", source="behavior_rule",
                reason="Người dùng đang giao tiếp bằng tiếng Việt.",
            ))

        # Yêu cầu trực tiếp về style. Value được giữ dưới dạng rule nguyên tử thay
        # vì ép vào vài enum nghèo nàn.
        style_cues = (
            "trả lời", "tra loi", "nói", "noi", "viết", "viet", "đừng", "dung",
            "ngắn", "ngan", "dài", "dai", "chi tiết", "chi tiet", "máy", "may",
            "tự nhiên", "tu nhien", "thẳng", "thang", "chú thích", "chu thich",
        )
        directive_cues = ("hãy", "hay ", "đừng", "dung ", "nên", "nen ", "phải", "phai ", "tôi muốn", "toi muon", "làm ơn")
        if any(cue in norm for cue in style_cues) and any(cue in norm for cue in directive_cues):
            rule = _extract_instruction(raw)
            if rule:
                out.append(_op(
                    "communication.response_rules", rule, evidence_ids, scope,
                    confidence=0.91, explicitness="explicit", cardinality="multi",
                    source="behavior_rule", reason="Người dùng đưa hướng dẫn trực tiếp về cách phản hồi.",
                ))

        # Feedback âm rõ về output vừa rồi. Không lưu lời chửi nguyên văn vào prompt,
        # chỉ lưu bài học hành vi đã được nén.
        negative = any(cue in norm for cue in (
            "máy vl", "may vl", "máy quá", "may qua", "không ổn", "khong on",
            "chưa elegant", "chua elegant", "làm tiếp", "lam tiep", "sai rồi", "sai roi",
            "không phải", "khong phai", "tệ", "te ", "dở", "do ",
        ))
        if negative:
            lesson = _feedback_lesson(norm)
            out.append(_op(
                "communication.negative_feedback_patterns", lesson, evidence_ids, scope,
                confidence=0.84, explicitness="observed", cardinality="multi",
                source="behavior_rule", reason="Người dùng sửa hoặc bác bỏ cách phản hồi trước.",
                metadata={"assistant_text": compact_text(context.get("assistant_text"), 400)},
            ))

        # Người dùng yêu cầu artifact/file nhiều lần thì đây là preference workflow,
        # không phải fact identity.
        if any(cue in norm for cue in ("gửi file", "gui file", "gửi đi", "gui di", "đóng gói", "dong goi", "zip")):
            out.append(_op(
                "workflow.delivery_preference", "ưu tiên file hoàn chỉnh có thể dùng ngay", evidence_ids, scope,
                confidence=0.86, explicitness="observed", source="behavior_rule",
                reason="Người dùng yêu cầu bàn giao artifact hoàn chỉnh.",
            ))

        if any(cue in norm for cue in ("chú thích tiếng việt", "chu thich tieng viet", "có chú thích", "co chu thich")):
            out.append(_op(
                "technical.code_comment_language", "vi", evidence_ids, scope,
                confidence=0.97, explicitness="explicit", source="behavior_rule",
                reason="Người dùng yêu cầu chú thích mã nguồn bằng tiếng Việt.",
            ))

        return tuple(out)

    def _parse_model_operations(
        self,
        response: Mapping[str, Any] | None,
        *,
        ids: tuple[str, ...],
        default_scope: UserMemoryScope,
    ) -> list[ProfileOperation]:
        if not isinstance(response, Mapping):
            return []
        rows = response.get("operations")
        if not isinstance(rows, list):
            return []
        out: list[ProfileOperation] = []
        for row in rows[: self.config.max_operations_per_turn]:
            if not isinstance(row, Mapping):
                continue
            op = ProfileOperation.from_dict({**dict(row), "evidence_ids": list(row.get("evidence_ids") or ids), "scope": row.get("scope") or default_scope.to_dict(), "source": row.get("source") or "profile_model"})
            if not op.path or op.confidence < self.config.min_model_confidence:
                continue
            if op.explicitness == "inferred" and op.confidence < self.config.min_inferred_confidence:
                continue
            # Không cho model suy diễn thuộc tính nhạy cảm nếu user không nói rõ.
            if op.sensitivity == "sensitive" and op.explicitness != "explicit":
                continue
            out.append(op)
        return out


def _op(
    path: str,
    value: Any,
    evidence_ids: tuple[str, ...],
    scope: UserMemoryScope,
    *,
    confidence: float,
    explicitness: str,
    source: str,
    reason: str,
    cardinality: str = "single",
    metadata: Mapping[str, Any] | None = None,
) -> ProfileOperation:
    return ProfileOperation(
        op="reinforce",
        path=path,
        value=value,
        confidence=confidence,
        explicitness=explicitness,  # type: ignore[arg-type]
        scope=scope,
        cardinality=cardinality,  # type: ignore[arg-type]
        evidence_ids=evidence_ids,
        source=source,
        reason=reason,
        metadata=dict(metadata or {}),
    )


def _scope_from_context(context: Mapping[str, Any]) -> UserMemoryScope:
    project = str(context.get("project_id") or context.get("project") or "").strip()
    if project:
        return UserMemoryScope("project", project)
    session = str(context.get("session_id") or "").strip()
    if bool(context.get("session_only")) and session:
        return UserMemoryScope("session", session)
    return UserMemoryScope()


def _scope_from_metadata(metadata: Mapping[str, Any]) -> UserMemoryScope:
    return UserMemoryScope.from_value(metadata.get("scope") or {"kind": "project", "key": metadata.get("project_id")}) if metadata.get("project_id") else UserMemoryScope.from_value(metadata.get("scope"))


def _sensitivity_for_path(path: str) -> str:
    lowered = path.lower()
    sensitive_fragments = ("health", "medical", "religion", "sexual", "biometric", "political", "password", "credential")
    if any(x in lowered for x in sensitive_fragments):
        return "sensitive"
    if any(x in lowered for x in ("identity", "address", "location", "relationship", "birthday", "gender")):
        return "personal"
    return "normal"


def _looks_vietnamese(text: str) -> bool:
    return bool(re.search(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", text.lower()))


def _extract_instruction(raw: str) -> str:
    clean = compact_text(raw, 260)
    clean = re.sub(r"^(hãy|làm ơn|từ giờ|tôi muốn|mình muốn)\s+", "", clean, flags=re.I)
    return clean.strip(" .,!?")


def _feedback_lesson(norm: str) -> str:
    if "máy" in norm or "may" in norm:
        return "tránh câu chữ kỹ thuật hoặc máy móc ở public surface"
    if "elegant" in norm or "vá" in norm or "va " in norm:
        return "không che technical debt bằng lớp tương thích; nêu rõ phần chưa hoàn thiện"
    if "làm tiếp" in norm or "lam tiep" in norm:
        return "khi user yêu cầu triển khai, ưu tiên hoàn thiện thay vì dừng ở đề xuất"
    return "đọc feedback trực tiếp và sửa hành vi, không phòng thủ"


def _dedupe_operations(operations: Iterable[ProfileOperation]) -> list[ProfileOperation]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ProfileOperation] = []
    for op in operations:
        key = (op.op, op.path, repr(op.value))
        if key in seen:
            continue
        seen.add(key)
        out.append(op)
    return out


__all__ = ["ProfileExtractionConfig", "UserProfileExtractor", "UserProfileModelAdapter"]
