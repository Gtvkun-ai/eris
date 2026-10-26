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
from core.di import resolve_dependency

import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from memory.semantic_memory import normalize_text

from .models import (
    ProfileOperation,
    UserMemoryScope,
    clamp01,
    compact_text,
    determine_memory_tier,
    is_ephemeral_directive,
    is_fragment_or_noise,
    is_invalid_response_rule,
    is_metaphor_or_sarcasm_leak,
    normalize_path,
)


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
        self.config = resolve_dependency(config, lambda: ProfileExtractionConfig())

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
        return _clean_operations(out)

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
            except Exception as exc:
                from .runtime_adapter import CuratorInferenceError
                if isinstance(exc, CuratorInferenceError):
                    raise  # Không xóa dấu lỗi; envelope phải được retry.
                response = None
            ops.extend(self._parse_model_operations(response, ids=ids, default_scope=scope))
        return tuple(_clean_operations(ops)[: self.config.max_operations_per_turn])

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

        # Yêu cầu trực tiếp về style/response rule. Phải là chỉ dẫn style thực sự,
        # không phải câu hỏi, đố vui, gaming leak hay chỉ thị tạm thời theo lượt.
        style_intent = bool(
            re.search(
                r"(?i)\b(?:trả\s*lời|nói|viết|giải\s*thích|phản\s*hồi|chú\s*thích)\s+(?:ngắn|gọn|chi\s*tiết|tự\s*nhiên|thẳng|rõ|đầy\s*đủ|(?:bằng\s+)?tiếng\s*(?:việt|anh))\b",
                raw,
            )
            or re.search(
                r"(?i)\b(?:đừng|không\s*nên|tránh)\s+(?:trả\s*lời|nói|viết)\s+(?:máy\s*móc|dài\s*dòng|vòng\s*vo)\b",
                raw,
            )
            or re.search(
                r"(?i)\b(?:từ\s*giờ|khi\s*trả\s*lời|lúc\s*nói)\s+.*?\b(?:hãy|nên|đừng|phải)\b",
                raw,
            )
            or (
                re.search(r"(?i)\b(?:hãy|nên|đừng|phải|tôi\s*muốn|làm\s*ơn)\b", raw)
                and re.search(r"(?i)\b(?:trả\s*lời|nói|viết|xưng\s*hô|chú\s*thích)\b", raw)
                and re.search(r"(?i)\b(?:ngắn|dài|chi\s*tiết|tự\s*nhiên|máy\s*móc|thẳng|tiếng\s*việt|tiếng\s*anh)\b", raw)
            )
        )
        if style_intent and not raw.strip().endswith("?"):
            rule = _extract_instruction(raw)
            if (
                rule
                and not is_ephemeral_directive(raw)
                and not is_invalid_response_rule("communication.response_rules", rule)
            ):
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

        # Companion Consolidation: những thứ user *đang học/đang làm* thuộc Living
        # User Memory canonical, không thuộc AdaptiveCompanion. Đây chỉ là context
        # hiện hành, tuyệt đối không được dùng như bằng chứng mastery/experience.
        # Gắn expires_at để profile tự cũ đi nếu user không nhắc lại trong thời gian dài.
        now = time.time()
        for topic in _extract_learning_fragments(raw):
            out.append(_op(
                "learning.active_topics", topic, evidence_ids, UserMemoryScope(),
                confidence=0.92, explicitness="explicit", cardinality="multi",
                source="behavior_rule", reason="Người dùng nói rõ chủ đề mình đang học/tìm hiểu.",
                metadata={"expires_at": now + 120.0 * 86400.0, "context_only": True},
            ))

        for activity in _extract_activity_fragments(raw):
            out.append(_op(
                "projects.current_activities", activity, evidence_ids, scope,
                confidence=0.90, explicitness="explicit", cardinality="multi",
                source="behavior_rule", reason="Người dùng nói rõ project/công việc mình đang làm.",
                metadata={"expires_at": now + 120.0 * 86400.0, "context_only": True},
            ))

        return _clean_operations(out)

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
        return list(_clean_operations(out))


def _extract_learning_fragments(raw: str) -> tuple[str, ...]:
    """Lấy explicit learning topic bảo thủ; không suy từ việc user chỉ hỏi kỹ thuật."""
    fragments: list[str] = []
    pattern = r"(?:tôi\s+)?(?:đang|muốn|định|cần)?\s*(?:học|tìm hiểu|luyện|learn(?:ing)?|study)\s+([^,!?;\n]+)"
    for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
        value = compact_text(match.group(1), 180).strip(" .,:;!?-")
        value = re.split(
            r"\b(?:còn|nhưng|để\s+làm|và\s+đồ\s+án|và\s+đang\s+(?:làm|xây|code|phát\s+triển))\b",
            value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        if len(value) >= 2:
            fragments.append(value)
    return tuple(dict.fromkeys(fragments))[:4]


def _extract_activity_fragments(raw: str) -> tuple[str, ...]:
    """Lấy activity/project mà user tự nói đang làm; tránh biến mọi câu 'làm đi' thành project."""
    fragments: list[str] = []
    patterns = (
        r"(?:đồ\s*án|project|dự\s*án)(?:\s+(?:hiện\s*tại|này|của\s+tôi))?[^,.!?;]{0,60}?(?:đang\s+làm|là|:)\s*([^,!?;\n]+)",
        r"(?:tôi\s+)?đang\s+(?:làm|xây|code|phát\s+triển)\s+([^,!?;\n]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            value = compact_text(match.group(1), 180).strip(" .,:;!?-")
            if len(value) >= 2:
                fragments.append(value)
    return tuple(dict.fromkeys(fragments))[:4]


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


def _clean_operations(operations: Iterable[ProfileOperation]) -> tuple[ProfileOperation, ...]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ProfileOperation] = []
    for op in operations:
        if is_fragment_or_noise(op.path, op.value):
            continue
        if is_metaphor_or_sarcasm_leak(op.path, op.value):
            continue
        if is_ephemeral_directive(op.value) or (
            op.path.endswith("response_rules") and is_invalid_response_rule(op.path, op.value)
        ):
            continue
        if op.tier is None:
            op.tier = determine_memory_tier(op.path, op.explicitness, 1, op.value)
        key = (op.op, op.path, repr(op.value))
        if key in seen:
            continue
        seen.add(key)
        out.append(op)
    return tuple(out)


__all__ = ["ProfileExtractionConfig", "UserProfileExtractor", "UserProfileModelAdapter"]
