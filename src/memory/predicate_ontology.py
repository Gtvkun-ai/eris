from __future__ import annotations

"""
predicate_ontology.py
=====================

Ontology predicate cho semantic memory.

Đây là nơi định nghĩa:
- predicate nào trả lời query nào;
- predicate nào mâu thuẫn với predicate nào;
- predicate nào TUYỆT ĐỐI không được dùng để trả lời loại query khác.

Không có ontology, memory sẽ rơi về overlap text. Và overlap text là con đường ngắn nhất
đưa ERIS tới câu: "Ngài thích Hà Tĩnh, vậy quê Ngài là Hà Tĩnh". Một màn xiếc không ai cần.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

try:
    from .semantic_claim import SemanticClaim
except Exception:  # pragma: no cover
    from semantic_claim import SemanticClaim  # type: ignore


class EntailmentType(str, Enum):
    EXACT = "exact"              # Claim trả lời trực tiếp query.
    COMPATIBLE = "compatible"    # Claim hỗ trợ yếu/phụ, không đủ để answer fact chính.
    RELATED = "related"          # Có liên quan nhưng không được surface như câu trả lời.
    CONTRADICTS = "contradicts"  # Mâu thuẫn.
    FORBIDDEN = "forbidden"      # Cấm dùng để answer query này.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PredicateSpec:
    name: str
    object_type: str = "unknown"
    modality: str = "fact"
    default_temporal: str = "unknown"
    default_scope: str = "self"
    answer_targets: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    compatible_with: tuple[str, ...] = ()
    forbidden_for: tuple[str, ...] = ()
    fact_key: str = ""
    storage_layer: str = "semantic_memory"
    default_decay: str = "normal"
    retention_class: str = "medium_term"
    importance: float = 0.50
    aliases: tuple[str, ...] = field(default_factory=tuple)


# Tên answer target dùng bởi QueryIntent. Không phải mọi predicate cùng object đều entail nhau.
PREDICATES: dict[str, PredicateSpec] = {
    "name_is": PredicateSpec(
        name="name_is",
        object_type="person_name",
        modality="fact",
        default_temporal="stable",
        answer_targets=("user_name",),
        contradicts=("name_is",),
        fact_key="user.name",
        default_decay="slow",
        retention_class="long_term",
        importance=0.96,
        aliases=("tên", "ten", "name", "preferred name"),
    ),
    "nickname_is": PredicateSpec(
        name="nickname_is",
        object_type="person_name",
        modality="fact",
        default_temporal="stable",
        answer_targets=("user_nickname",),
        # Chỉ mâu thuẫn với chính nó. Biệt danh KHÔNG được phép contradict tên thật
        # (name_is) — user có thể có cả tên "Hoà" lẫn biệt danh "Gtvkun" cùng lúc.
        contradicts=("nickname_is",),
        fact_key="user.nickname",
        default_decay="slow",
        retention_class="long_term",
        importance=0.94,
        aliases=("biệt danh", "biet danh", "nickname", "biệt hiệu", "biet hieu", "tên gọi", "ten goi"),
    ),
    "birth_month_is": PredicateSpec(
        name="birth_month_is",
        object_type="month",
        modality="fact",
        default_temporal="stable",
        answer_targets=("user_birth_month",),
        contradicts=("birth_month_is",),
        fact_key="user.birth_month",
        default_decay="slow",
        retention_class="long_term",
        importance=0.88,
        aliases=("tháng sinh", "thang sinh", "birth month", "birthday"),
    ),
    "birth_year_is": PredicateSpec(
        name="birth_year_is",
        object_type="year",
        modality="fact",
        default_temporal="stable",
        answer_targets=("user_birth_year",),
        contradicts=("birth_year_is",),
        fact_key="user.birth_year",
        default_decay="slow",
        retention_class="long_term",
        importance=0.90,
        aliases=("năm sinh", "nam sinh", "birth year", "2k"),
    ),
    "age_observed_is": PredicateSpec(
        name="age_observed_is",
        object_type="age",
        modality="observation",
        default_temporal="current",
        answer_targets=("user_age_observed",),
        contradicts=("age_observed_is",),
        fact_key="user.age_observed",
        default_decay="fast",
        retention_class="short_term",
        importance=0.62,
        aliases=("tuổi", "tuoi", "age"),
    ),
    "current_location_is": PredicateSpec(
        name="current_location_is",
        object_type="location",
        modality="observation",
        default_temporal="current",
        answer_targets=("user_current_location",),
        contradicts=("current_location_is",),
        forbidden_for=("user_living_location", "user_hometown", "user_location_preference"),
        fact_key="user.current_location",
        default_decay="fast",
        retention_class="short_term",
        importance=0.68,
        aliases=("đang ở", "dang o", "current location", "hiện ở", "hien o"),
    ),
    "living_location_is": PredicateSpec(
        name="living_location_is",
        object_type="location",
        modality="fact",
        default_temporal="current",
        answer_targets=("user_living_location",),
        contradicts=("living_location_is",),
        forbidden_for=("user_current_location", "user_hometown", "user_location_preference"),
        fact_key="user.living_location",
        default_decay="normal",
        retention_class="medium_term",
        importance=0.78,
        aliases=("sống ở", "song o", "nơi ở", "noi o", "living location"),
    ),
    "hometown_is": PredicateSpec(
        name="hometown_is",
        object_type="location",
        modality="fact",
        default_temporal="stable",
        answer_targets=("user_hometown",),
        contradicts=("hometown_is",),
        forbidden_for=("user_current_location", "user_living_location", "user_location_preference"),
        fact_key="user.hometown",
        default_decay="slow",
        retention_class="long_term",
        importance=0.86,
        aliases=("quê", "que", "hometown", "quê quán", "que quan"),
    ),
    "preference_location": PredicateSpec(
        name="preference_location",
        object_type="location",
        modality="preference",
        default_temporal="stable",
        answer_targets=("user_location_preference",),
        contradicts=("preference_location",),
        compatible_with=("mentioned_location",),
        forbidden_for=("user_current_location", "user_living_location", "user_hometown"),
        fact_key="user.preference.location",
        default_decay="slow",
        retention_class="long_term",
        importance=0.74,
        aliases=("thích nơi", "thich noi", "thích ở", "thich o", "location preference"),
    ),
    "mentioned_location": PredicateSpec(
        name="mentioned_location",
        object_type="location",
        modality="observation",
        default_temporal="session",
        answer_targets=("mentioned_location",),
        compatible_with=("preference_location", "current_location_is", "living_location_is", "hometown_is"),
        forbidden_for=("user_current_location", "user_living_location", "user_hometown", "user_location_preference"),
        fact_key="user.mentioned_location",
        storage_layer="memory_candidate",
        default_decay="session_only",
        retention_class="session",
        importance=0.30,
        aliases=("nhắc", "nhac", "mentioned location"),
    ),
    "study_field_is": PredicateSpec(
        name="study_field_is",
        object_type="study_field",
        modality="fact",
        default_temporal="current",
        answer_targets=("user_study_field",),
        contradicts=("study_field_is",),
        fact_key="user.study_field",
        default_decay="normal",
        retention_class="medium_term",
        importance=0.74,
        aliases=("ngành học", "nganh hoc", "học IT", "hoc IT", "study field", "major"),
    ),
    "response_style_prefers": PredicateSpec(
        name="response_style_prefers",
        object_type="style_rule",
        modality="preference",
        default_temporal="stable",
        answer_targets=("user_response_style",),
        contradicts=("response_style_prefers",),
        fact_key="user.response_style",
        default_decay="slow",
        retention_class="long_term",
        importance=0.82,
        aliases=("cách trả lời", "cach tra loi", "response style", "chú thích", "comment"),
    ),
    "general_preference": PredicateSpec(
        name="general_preference",
        object_type="unknown",
        modality="preference",
        default_temporal="stable",
        answer_targets=("user_general_preference",),
        fact_key="user.preference.general",
        default_decay="normal",
        retention_class="medium_term",
        importance=0.62,
        aliases=("sở thích", "so thich", "preference", "thích", "không thích"),
    ),
    "asked_about": PredicateSpec(
        name="asked_about",
        object_type="topic",
        modality="observation",
        default_temporal="session",
        answer_targets=("session_question",),
        storage_layer="session_turn_ledger",
        default_decay="session_only",
        retention_class="session",
        importance=0.20,
    ),
    "greeted": PredicateSpec(
        name="greeted",
        object_type="utterance",
        modality="observation",
        default_temporal="session",
        answer_targets=("session_greeting",),
        storage_layer="session_turn_ledger",
        default_decay="session_only",
        retention_class="transient",
        importance=0.10,
    ),
    "remember_unresolved": PredicateSpec(
        name="remember_unresolved",
        object_type="text",
        modality="memory",
        default_temporal="stable",
        answer_targets=("memory_candidate",),
        fact_key="memory_candidate.unresolved",
        storage_layer="memory_candidate",
        default_decay="candidate",
        retention_class="candidate",
        importance=0.68,
        aliases=("nhớ nhưng chưa rõ", "unresolved memory", "candidate"),
    ),
}

FACT_KEY_TO_PREDICATE: dict[str, str] = {spec.fact_key: name for name, spec in PREDICATES.items() if spec.fact_key}

# Các cặp forbidden rõ ràng. Dùng answer target để dễ đọc hơn predicate chéo.
FORBIDDEN_PREDICATE_TO_TARGET: dict[str, set[str]] = {
    name: set(spec.forbidden_for) for name, spec in PREDICATES.items() if spec.forbidden_for
}


def get_predicate(name: str) -> PredicateSpec:
    return PREDICATES.get(str(name or ""), PredicateSpec(name=str(name or "unknown")))


def fact_key_for_predicate(predicate: str) -> str:
    return get_predicate(predicate).fact_key


def predicate_for_fact_key(fact_key: str) -> str:
    return FACT_KEY_TO_PREDICATE.get(str(fact_key or ""), "")


def predicate_aliases(predicate: str) -> tuple[str, ...]:
    return get_predicate(predicate).aliases


def entailment_for_target(claim: SemanticClaim, target: str) -> EntailmentType:
    """Claim có được dùng để trả lời answer target không?

    Ví dụ:
    - preference_location -> user_hometown = FORBIDDEN
    - mentioned_location -> user_current_location = FORBIDDEN
    - hometown_is -> user_hometown = EXACT
    """

    spec = get_predicate(claim.predicate)
    target = str(target or "")

    if target in spec.answer_targets:
        if claim.assertion == "denied":
            return EntailmentType.CONTRADICTS
        if claim.assertion in {"hypothetical", "quoted"}:
            return EntailmentType.RELATED
        return EntailmentType.EXACT

    if target in FORBIDDEN_PREDICATE_TO_TARGET.get(claim.predicate, set()):
        return EntailmentType.FORBIDDEN

    if target in _compatible_targets(spec.compatible_with):
        return EntailmentType.COMPATIBLE

    # Cùng object_type location nhưng target khác thì thường là forbidden hơn là related.
    # Đây là chốt quan trọng cho location. Không cho "cùng là Hà Tĩnh" làm cầu bậy.
    if spec.object_type == "location" and ((target.startswith("user_") and "location" in target) or target == "user_hometown"):
        return EntailmentType.FORBIDDEN

    return EntailmentType.UNKNOWN


def contradicts(a: SemanticClaim, b: SemanticClaim) -> bool:
    """Mâu thuẫn rõ khi cùng subject + predicate contradicts + object khác.

    Không cố NLP sâu ở đây. Nếu claim phức tạp, để consolidator giữ cả hai và đánh dấu uncertain.
    """

    if a.subject != b.subject:
        return False
    spec = get_predicate(a.predicate)
    if b.predicate not in spec.contradicts:
        return False
    if a.assertion == "denied" or b.assertion == "denied":
        return True
    return _norm(a.object_text) != _norm(b.object_text)


def is_long_term_predicate(predicate: str) -> bool:
    return get_predicate(predicate).retention_class in {"medium_term", "long_term"}


def storage_layer_for_predicate(predicate: str) -> str:
    return get_predicate(predicate).storage_layer


def default_decay_for_predicate(predicate: str) -> str:
    return get_predicate(predicate).default_decay


def importance_for_predicate(predicate: str) -> float:
    return float(get_predicate(predicate).importance)


def _compatible_targets(predicates: Iterable[str]) -> set[str]:
    targets: set[str] = set()
    for pred in predicates:
        targets.update(get_predicate(pred).answer_targets)
    return targets


def _norm(text: str) -> str:
    import unicodedata
    import re

    t = unicodedata.normalize("NFD", str(text or "").lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = t.replace("đ", "d")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


__all__ = [
    "EntailmentType",
    "PredicateSpec",
    "PREDICATES",
    "get_predicate",
    "fact_key_for_predicate",
    "predicate_for_fact_key",
    "predicate_aliases",
    "entailment_for_target",
    "contradicts",
    "is_long_term_predicate",
    "storage_layer_for_predicate",
    "default_decay_for_predicate",
    "importance_for_predicate",
]
