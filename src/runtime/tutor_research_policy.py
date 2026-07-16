# -*- coding: utf-8 -*-
"""Chính sách tra cứu nhẹ qua Tutor hiện có.

Module này cố ý KHÔNG dựng Deep Research API, Google grounding, agent nền hay
EvidenceBundle nhiều tầng. Nó chỉ quyết định khi nào đáng nhờ Tutor, resolve câu
follow-up ngắn về đúng chủ đề trước đó, rồi bọc chủ đề bằng một prompt gọn để
Tutor tự dùng khả năng tìm kiếm của giao diện web nếu cần.

Mục tiêu là giữ chi phí thấp:
- câu kiến thức đơn giản vẫn để main brain trả lời;
- chỉ câu có yêu cầu nghiên cứu/kiểm chứng rõ hoặc đủ phức tạp mới đi Tutor;
- prompt và câu trả lời đều có hard budget;
- không gọi thêm LLM chỉ để rewrite, distill hay "phân tích về việc phân tích".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence


_EXPLICIT_RESEARCH_MARKERS = (
    "nghien cuu", "dao sau", "tim hieu ky", "tra ky", "tra cuu ky",
    "kiem chung", "xac minh", "tim nguon", "tim tai lieu",
    "hoi tutor", "hoi su phu", "hoi gemini", "nho gemini", "keu gemini",
    "gemini hay", "gemini nghien cuu", "tutor nghien cuu",
    "fix elegant", "cach fix", "deep research", "research ky", "research sau",
)

_EXPLICIT_SEARCH_MARKERS = (
    # Search bình thường: user muốn Eris ra ngoài web kiểm tra, nhưng chưa cần
    # phân tích sâu. Tách khỏi research để khỏi mỗi câu “tra cứu giúp” lại kéo
    # theo nghi lễ nghiên cứu nhiều bước, một thú vui rất tốn tiền của loài người.
    "search web", "gemini search", "google thu", "google giup", "len web",
    "len mang", "tim kiem", "tra cuu", "tim giup", "tim ho", "xem web",
    "tim tren web", "check web", "check giup", "check thu", "fact check nhanh",
    "co nguon khong", "dan nguon", "nguon dau", "link dau",
)

_FRESHNESS_MARKERS = (
    "hom nay", "bay gio", "hien tai", "moi nhat", "gan day", "vua ra",
    "vua cong bo", "cap nhat", "lich", "gia", "ty gia", "thoi tiet",
    "tin moi", "phien ban moi", "release", "ban moi", "dang hot",
)

# Dùng để bắt câu hỏi lái/lắt léo: user không nói thẳng "search web",
# nhưng bản chất là đang hỏi một claim có thể sai vì thời điểm, chính sách,
# trạng thái tài khoản/dịch vụ, tin đồn, phiên bản, giá, luật, lịch, v.v.
# Regex thuần kiểu marker vẫn chỉ là hàng rào ngoài cổng, nên khối này cố tình
# chấm theo cặp "dấu hiệu cần verify" + "miền dễ thay đổi" thay vì bắt một câu
# thần chú duy nhất. Con người rất sáng tạo khi muốn làm mơ hồ mọi thứ.
_VERIFY_TRAP_MARKERS = (
    "co that", "that khong", "chuan khong", "dung khong", "co dung la",
    "co phai la", "co phai", "nghe noi", "hinh nhu", "tin don",
    "fake khong", "scam khong", "lua dao khong", "uy tin khong",
    "bi ban", "bi khoa", "bi chan", "bi vo hieu hoa", "het han",
    "con dung duoc", "con hoat dong", "co con", "da doi chua", "doi chua",
    "vua bi", "sap bi", "dang bi", "co bi", "co duoc khong", "hop le khong",
)

_UPDATE_SENSITIVE_MARKERS = (
    "api", "key", "token", "model", "gemini", "openai", "chatgpt",
    "claude", "openrouter", "qwen", "gemma", "terra", "workspace",
    "tai khoan", "account", "server", "website", "web", "app", "plugin",
    "extension", "repo", "github", "driver", "windows", "godot",
    "version", "phien ban", "ban moi", "release", "gia", "ty gia",
    "lich", "su kien", "thoi tiet", "luat", "quy dinh", "chinh sach",
    "ceo", "chu tich", "tong thong", "bo truong", "mini world", "game",
    "ban acc", "green net", "greennet", "workspace",
)

_COMPLEXITY_MARKERS = (
    "so sanh", "danh gia", "phan tich", "chi tiet", "toan dien", "toan bo",
    "chuyen sau", "nhieu nguon", "co nguon", "dan nguon", "bang chung",
    "moi nhat", "hien tai", "vua cong bo", "cap nhat", "thuc hu",
    "kiem tra lai", "doi chieu",
)

_REFERENCE_MARKERS = (
    "phan nay", "phan do", "phan tren", "cai nay", "cai do", "cai tren",
    "y nay", "y do", "y vua roi", "o tren", "vua nay", "luc nay", "hoi nay",
    "chi tiet hon", "sau hon", "ky hon", "them di", "vu nay", "vu do",
)

_FILLER_WORDS = {
    "di", "nhe", "nha", "thu", "dum", "giup", "toi", "cho", "ban", "em",
    "nghien", "cuu", "dao", "sau", "tim", "hieu", "ky", "tra", "cuu", "lai",
    "chi", "tiet", "hon", "phan", "cai", "y", "nay", "do", "tren", "vua",
    "roi", "luc", "hoi", "them", "vu", "ve", "gemini", "tutor", "su", "phu",
    "search", "web", "research", "please", "hay", "fix", "elegant",
}

_SOURCE_HEADINGS = ("nguon", "nguồn", "sources", "tham khao", "tham khảo")


def normalize_marker_text(text: object) -> str:
    """Chuẩn hóa tiếng Việt để detector không phải nuôi cả sở thú dấu câu."""

    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("đ", "d")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _has_marker(normalized: str, marker: str) -> bool:
    """Match marker theo ranh giới token, không match bậy `gia` trong `giao`."""

    if not normalized or not marker:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(marker.strip()) + r"(?![a-z0-9])"
    return re.search(pattern, normalized) is not None


def _has_any_marker(normalized: str, markers: Sequence[str] | Iterable[str]) -> bool:
    return any(_has_marker(normalized, marker) for marker in markers)


def is_explicit_research_request(text: object) -> bool:
    normalized = normalize_marker_text(text)
    return bool(normalized and _has_any_marker(normalized, _EXPLICIT_RESEARCH_MARKERS))


def is_explicit_search_request(text: object) -> bool:
    """User chủ động yêu cầu search/tra cứu nhanh, không nhất thiết research sâu."""

    normalized = normalize_marker_text(text)
    return bool(normalized and _has_any_marker(normalized, _EXPLICIT_SEARCH_MARKERS))


def needs_fresh_web(text: object) -> bool:
    """Câu hỏi có tính thời điểm nên main brain không được tự tin từ trí nhớ cũ."""

    normalized = normalize_marker_text(text)
    return bool(normalized and _has_any_marker(normalized, _FRESHNESS_MARKERS))


def needs_external_verification(text: object) -> bool:
    """Bắt câu hỏi lái cần verify dù user không nói chữ search.

    Ví dụ: "workspace này bị ban à", "key này còn dùng được không",
    "nghe nói model X đổi policy đúng không". Nếu chỉ dùng explicit marker,
    các câu này sẽ lọt và Terra có thể trả bằng trí nhớ cũ. Không vui.
    """

    raw = str(text or "")
    normalized = normalize_marker_text(raw)
    if not normalized:
        return False
    if needs_fresh_web(normalized):
        return True

    has_trap = _has_any_marker(normalized, _VERIFY_TRAP_MARKERS)
    if not has_trap:
        return False

    # Nếu hỏi một claim lắt léo trong miền dễ thay đổi thì route search nhanh.
    if _has_any_marker(normalized, _UPDATE_SENSITIVE_MARKERS):
        return True

    # Câu có URL/domain hoặc mã phiên bản thường cần xác minh ngoài, dù user không
    # dùng từ "search".
    if re.search(r"\b(?:https?://|www\.|[a-z0-9-]+\.(?:com|net|org|io|dev|ai|vn))\b", raw, re.I):
        return True
    if re.search(r"\bv?\d+(?:\.\d+){1,3}\b", raw, re.I):
        return True

    return False


def _looks_reference_only(text: object) -> bool:
    normalized = normalize_marker_text(text)
    if not normalized:
        return True
    if _has_any_marker(normalized, _REFERENCE_MARKERS):
        # Nếu ngoài cụm tham chiếu vẫn còn một chủ đề đủ rõ thì không coi là reference-only.
        tokens = [token for token in normalized.split() if token not in _FILLER_WORDS]
        return len(tokens) <= 2
    tokens = [token for token in normalized.split() if token not in _FILLER_WORDS]
    return len(tokens) <= 1 and is_explicit_research_request(text)


def resolve_research_topic(current_text: object, prior_user_turns: Sequence[object] | Iterable[object] = ()) -> str:
    """Resolve câu kiểu "nghiên cứu sâu phần này" về turn có nội dung trước đó.

    Không dùng LLM. Nếu câu hiện tại đã chứa chủ đề thật, giữ nguyên để tránh rewrite
    làm mất ý. Nếu chỉ là lệnh giao việc/tham chiếu mơ hồ, lấy user turn gần nhất có
    nội dung và không phải một lệnh gọi Tutor khác.
    """

    current = str(current_text or "").strip()
    current_norm = normalize_marker_text(current)
    if current and not _looks_reference_only(current):
        return current[:900]

    for item in reversed(list(prior_user_turns or ())):
        candidate = str(getattr(item, "text", item) or "").strip()
        if not candidate:
            continue
        candidate_norm = normalize_marker_text(candidate)
        if candidate_norm == current_norm:
            continue
        if _looks_reference_only(candidate):
            continue
        return candidate[:900]
    return ""


@dataclass(frozen=True, slots=True)
class TutorResearchDecision:
    should_delegate: bool
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class TutorDelegationDecision:
    should_delegate: bool
    score: float
    reason: str
    mode: str = "none"  # none | quick_search | research


def score_tutor_delegation(text: object, *, intent: str = "", meaning_missing: bool = False) -> TutorDelegationDecision:
    """Gate chung cho Tutor web: quick_search hoặc research.

    - research: cue đào sâu/kiểm chứng phức tạp, có thể cần phân tích lại.
    - quick_search: user chủ động muốn search hoặc câu có freshness rõ.
    - none: kiến thức phổ thông để main Terra tự trả lời.
    """

    research = score_research_need(text, intent=intent, meaning_missing=meaning_missing)
    if research.should_delegate:
        return TutorDelegationDecision(True, research.score, research.reason, "research")

    normalized = normalize_marker_text(text)
    if not normalized:
        return TutorDelegationDecision(False, 0.0, "empty", "none")

    if is_explicit_search_request(text):
        return TutorDelegationDecision(True, 0.88, "explicit_search_cue", "quick_search")

    # Fresh/current queries are dangerous for a frozen/common-knowledge answer.
    # Route only when the turn is actually world knowledge or the classifier is unsure.
    allowed_uncertain_intents = {"world_knowledge", "unclear", "unknown", "other", ""}
    intent_norm = str(intent or "").strip().lower()
    if needs_fresh_web(text) and intent_norm in allowed_uncertain_intents:
        return TutorDelegationDecision(True, 0.78, "freshness_web_needed", "quick_search")

    # Hỏi lái: không có chữ search, nhưng đang kiểm claim/status/policy trong miền
    # dễ thay đổi. Dùng quick_search, không kéo research relay dài dòng.
    if needs_external_verification(text) and intent_norm in allowed_uncertain_intents:
        return TutorDelegationDecision(True, 0.74, "implicit_verification_risk", "quick_search")

    return TutorDelegationDecision(False, research.score, research.reason, "none")


def score_research_need(text: object, *, intent: str = "", meaning_missing: bool = False) -> TutorResearchDecision:
    """Gate rẻ cho Tutor.

    Câu đơn giản kiểu "X là gì" không còn tự động đẩy sang Tutor chỉ vì classifier
    gọi nó là world_knowledge. Con người đã phát minh ra classifier rồi lại bắt nó
    gọi thêm một model cho mọi câu hỏi hai dòng, một chuỗi thức ăn rất văn minh.
    """

    normalized = normalize_marker_text(text)
    if not normalized:
        return TutorResearchDecision(False, 0.0, "empty")

    if is_explicit_research_request(text):
        return TutorResearchDecision(True, 1.0, "explicit_research_cue")

    if str(intent or "").strip().lower() != "world_knowledge":
        return TutorResearchDecision(False, 0.0, "not_world_knowledge")

    score = 0.20
    reasons: list[str] = ["world_knowledge"]

    marker_hits = sum(1 for marker in _COMPLEXITY_MARKERS if _has_marker(normalized, marker))
    if marker_hits:
        score += min(0.48, 0.18 * marker_hits)
        reasons.append(f"complexity_markers={marker_hits}")

    word_count = len(normalized.split())
    if word_count >= 22:
        score += 0.16
        reasons.append("long_query")
    elif word_count >= 14:
        score += 0.08
        reasons.append("medium_query")

    clause_count = sum(normalized.count(token) for token in (" va ", " nhung ", " hay ", " dong thoi "))
    if clause_count >= 2:
        score += 0.10
        reasons.append("multi_clause")

    if meaning_missing:
        score += 0.08
        reasons.append("semantic_uncertainty")

    score = max(0.0, min(1.0, score))
    return TutorResearchDecision(score >= 0.58, score, ",".join(reasons))


def build_lightweight_search_prompt(
    topic: object,
    *,
    context: object = "",
    max_words: int = 160,
    max_chars: int = 395,
) -> str:
    """Prompt search nhanh cho Tutor web, rẻ hơn research-followup."""

    topic_text = " ".join(str(topic or "").split())
    context_text = " ".join(str(context or "").split())
    max_words = max(60, min(260, int(max_words or 160)))
    max_chars = max(220, min(395, int(max_chars or 395)))
    prefix = (
        "Hãy search web nhanh để kiểm tra câu hỏi sau. "
        f"Trả lời tiếng Việt tối đa {max_words} từ; nêu kết luận chính, "
        "ghi nguồn/link nếu tìm thấy, và nói rõ nếu chưa đủ chắc. Câu hỏi: "
    )
    suffix = f" | Ngữ cảnh: {context_text}" if context_text else ""
    available = max_chars - len(prefix) - len(suffix)
    if available < 40 and suffix:
        suffix = ""
        available = max_chars - len(prefix)
    topic_text = topic_text[: max(1, available)].rstrip(" .|:")
    prompt = f"{prefix}{topic_text}{suffix}".strip()
    return prompt[:max_chars].rstrip()


def build_lightweight_research_prompt(
    topic: object,
    *,
    context: object = "",
    max_words: int = 280,
    max_chars: int = 395,
) -> str:
    """Bọc chủ đề bằng lời nhắc nghiên cứu rẻ, vừa contract TutorQuestion 400 ký tự."""

    topic_text = " ".join(str(topic or "").split())
    context_text = " ".join(str(context or "").split())
    max_words = max(80, min(600, int(max_words or 280)))
    max_chars = max(220, min(395, int(max_chars or 395)))

    prefix = (
        "Hãy dùng tìm kiếm web nếu cần để kiểm tra câu hỏi sau. "
        f"Trả lời tiếng Việt cô đọng, tối đa {max_words} từ; ưu tiên nguồn chính thức, "
        "nêu rõ điều chưa chắc và ghi 2-4 nguồn ở cuối. Câu hỏi: "
    )
    suffix = f" | Ngữ cảnh: {context_text}" if context_text else ""
    available = max_chars - len(prefix) - len(suffix)
    if available < 40 and suffix:
        suffix = ""
        available = max_chars - len(prefix)
    topic_text = topic_text[: max(1, available)].rstrip(" .|:")
    prompt = f"{prefix}{topic_text}{suffix}".strip()
    return prompt[:max_chars].rstrip()


def compact_research_answer(text: object, *, max_words: int = 320) -> str:
    """Hard cap không dùng model, cố giữ phần nguồn nếu Tutor trả lời quá dài."""

    value = str(text or "").strip()
    if not value:
        return ""
    words = value.split()
    max_words = max(100, min(800, int(max_words or 320)))
    if len(words) <= max_words:
        return value

    lines = value.splitlines()
    source_index = -1
    for idx, line in enumerate(lines):
        normalized = normalize_marker_text(line)
        if any(normalized.startswith(head) for head in _SOURCE_HEADINGS):
            source_index = idx
            break

    if source_index >= 0:
        source_text = "\n".join(lines[source_index:]).strip()
        source_words = source_text.split()[: min(80, max_words // 3)]
        head_budget = max_words - len(source_words) - 8
        head = " ".join(words[: max(40, head_budget)]).rstrip()
        tail = " ".join(source_words).rstrip()
        return f"{head}\n\n[Đã rút gọn để giữ ngân sách.]\n{tail}".strip()

    return " ".join(words[:max_words]).rstrip() + " … [đã rút gọn]"


__all__ = [
    "TutorDelegationDecision",
    "TutorResearchDecision",
    "build_lightweight_research_prompt",
    "build_lightweight_search_prompt",
    "compact_research_answer",
    "is_explicit_research_request",
    "is_explicit_search_request",
    "needs_external_verification",
    "needs_fresh_web",
    "normalize_marker_text",
    "resolve_research_topic",
    "score_research_need",
    "score_tutor_delegation",
]
