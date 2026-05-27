from __future__ import annotations

"""
scripts/prune_dataset_infj.py
=============================

Script prune dataset cho ERIS theo hướng ít prompt-cosplay hơn và bớt heuristic rẻ.

Bản cũ có hai bệnh chính:
    1. Ép một SYSTEM_PROMPT dài vào mọi record. Dataset vì vậy học mùi persona hơn là học hành vi.
    2. Dedupe bằng canonicalize prefix stripping. Gặp paraphrase là trượt, gặp cùng đuôi khác nghĩa là cắt sai.

Bản này đổi sang pipeline nhẹ nhưng có cấu trúc:
    - Không tự ghi đè system prompt theo mặc định.
    - Chuẩn hóa text bằng Unicode + token/shingle fingerprint.
    - Dedupe theo user + assistant + style/topic signature, không chỉ theo user prefix.
    - Lexical/template rule chỉ là fallback để hỗ trợ fingerprint, không làm chân lý.
    - Giữ mẫu theo quality/diversity thay vì giữ N mẫu đầu tiên.

Không dùng embedding để file chạy độc lập, không thêm dependency.
Nếu sau này Ngài có embedding local, chỉ cần thay hàm similarity trong RecordSignature/SimilarityIndex.
Vâng, ta cố làm thứ tử tế mà không triệu hồi thêm một con dependency quái thai nữa.
"""

import argparse
import difflib
import hashlib
import json
import math
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence


SystemMode = Literal["preserve", "strip", "minimal", "file"]

# Prompt ngắn chỉ dùng khi CLI bật --system-mode minimal.
# Mặc định script KHÔNG chèn prompt này. ERIS nên học từ dữ liệu hành vi/state,
# không phải bị xịt nước hoa INFJ vào từng dòng jsonl rồi gọi đó là phát triển.
MINIMAL_SYSTEM_PROMPT = (
    "Bạn là ERIS. Trả lời theo bằng chứng hiện có, tiếng Việt tự nhiên, "
    "giữ ranh giới runtime và không bịa quyền năng ngoài hệ thống."
)


# Các phrase này không dùng để canonicalize record.
# Chúng chỉ dùng để nhận ra assistant đang lặp template style quá rõ,
# từ đó quality score bị trừ hoặc style_signature giống nhau hơn.
TEMPLATE_PHRASES = (
    "hôm nay tôi phải thú thật",
    "nghe có vẻ sến",
    "tôi không giỏi nói mấy chuyện này",
    "câu này hơi khó nói",
    "có lúc tôi",
    "tôi vẫn ở đây",
    "tôi hiểu mà",
    "ngài không cần phải",
    "tôi sẽ không rời đi",
    "một phần nào đó trong tôi",
)

# Một vài nhãn topic rất thô, chỉ phục vụ blocking/similarity nhẹ.
# Topic chính không quyết định sống chết của record. Nó chỉ giúp so sánh nhanh hơn.
TOPIC_CUES: dict[str, tuple[str, ...]] = {
    "technical": (
        "code", "python", "c#", "godot", "bug", "debug", "traceback", "exception",
        "runtime", "module", "class", "function", "method", "json", "api", "repo",
        "kiến trúc", "kien truc", "pipeline", "contract", "test", "lỗi", "loi", "fix", "sửa", "sua",
    ),
    "memory": (
        "memory", "ký ức", "ky uc", "nhớ", "nho", "quên", "quen", "recall", "semantic", "episodic",
    ),
    "relationship": (
        "quan hệ", "quan he", "gắn bó", "gan bo", "yêu", "yeu", "thương", "thuong",
        "bạn gái", "ban gai", "infj", "cạnh tôi", "canh toi", "hiểu tôi", "hieu toi",
    ),
    "distress": (
        "buồn", "buon", "mệt", "met", "stress", "áp lực", "ap luc", "chán", "chan", "cô đơn", "co don",
    ),
    "style": (
        "giọng", "giong", "tone", "prompt", "persona", "style", "lạnh", "lanh", "ấm", "am",
    ),
    "dataset": (
        "dataset", "jsonl", "train", "eval", "dedupe", "duplicate", "prune", "canonical", "sample",
    ),
}

# Từ chức năng quá chung. Nếu chỉ thấy chúng thì không nên coi là technical/topic mạnh.
LOW_INFORMATION_TOKENS = {
    "tôi", "toi", "ngài", "ngai", "bạn", "ban", "là", "la", "có", "co", "không", "khong",
    "thì", "thi", "mà", "ma", "này", "nay", "đó", "do", "ấy", "ay", "vậy", "vay",
    "cho", "của", "cua", "với", "voi", "một", "mot", "cái", "cai", "nó", "no",
}


@dataclass(slots=True)
class DatasetRecord:
    """Một record JSONL đã được đọc và tách role.

    original_index giúp preserve thứ tự ban đầu khi ghi ra, nếu hai mẫu có quality ngang nhau.
    raw giữ lại toàn bộ metadata ngoài conversations. Script không nên làm mất dữ liệu phụ.
    """

    original_index: int
    raw: dict[str, Any]
    conversations: list[dict[str, Any]]
    system_text: str = ""
    user_text: str = ""
    assistant_text: str = ""


@dataclass(slots=True)
class RecordSignature:
    """Fingerprint của record để dedupe gần đúng.

    Không có fingerprint nào là chân lý ngữ nghĩa. Đây là tập tín hiệu rẻ nhưng có cấu trúc:
        - surface: text đã normalize để bắt duplicate y hệt/gần y hệt.
        - char/word shingles: bắt paraphrase nhẹ mà không phụ thuộc prefix stripping.
        - style_signature: bắt assistant template lặp.
        - topic_distribution: giúp blocking và tránh so tất cả với tất cả.
    """

    index: int
    user_surface: str
    assistant_surface: str
    pair_hash: str
    user_char_ngrams: frozenset[str]
    assistant_char_ngrams: frozenset[str]
    user_word_ngrams: frozenset[str]
    assistant_word_ngrams: frozenset[str]
    user_tokens: frozenset[str]
    assistant_tokens: frozenset[str]
    style_signature: str
    primary_topic: str
    topic_distribution: dict[str, float]
    assistant_template_hits: tuple[str, ...]
    assistant_sentence_count: int
    assistant_token_count: int
    quality_score: float
    quality_reasons: tuple[str, ...]
    block_keys: tuple[str, ...]


@dataclass(slots=True)
class PruneConfig:
    """Cấu hình prune.

    similarity_threshold:
        Ngưỡng duplicate mạnh khi user và assistant đều giống.
    loose_user_threshold:
        Khi user cực giống, assistant cùng style/topic cũng có thể bị coi duplicate dù assistant khác chữ hơn.
    max_per_cluster:
        Số mẫu tối đa giữ trong một cụm gần trùng.
    max_exact_assistant:
        Không xóa toàn bộ câu assistant bị lặp như bản cũ. Giữ vài mẫu tốt nhất để tránh mất data hữu ích.
    preserve_order:
        Ghi output theo thứ tự gốc, sau khi chọn xong.
    """

    similarity_threshold: float = 0.74
    loose_user_threshold: float = 0.84
    assistant_threshold: float = 0.68
    max_per_cluster: int = 3
    max_exact_assistant: int = 2
    min_quality_score: float = 0.18
    preserve_order: bool = True
    system_mode: SystemMode = "preserve"
    system_prompt_file: Path | None = None
    backup: bool = True
    dry_run: bool = False
    stats_path: Path | None = None


@dataclass(slots=True)
class PruneStats:
    before: int = 0
    after: int = 0
    removed: int = 0
    exact_pair_removed: int = 0
    exact_assistant_removed: int = 0
    near_duplicate_removed: int = 0
    low_quality_removed: int = 0
    invalid_removed: int = 0
    system_mode: str = "preserve"
    clusters_seen: int = 0
    kept_by_topic: dict[str, int] = field(default_factory=dict)
    removed_reasons: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["removed_reasons"] = dict(self.removed_reasons)
        return data


# -----------------------------------------------------------------------------
# Chuẩn hóa text / token / similarity
# -----------------------------------------------------------------------------


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để so sánh mềm.

    Chỉ dùng cho fingerprint/dedupe. Không dùng để ghi output.
    """

    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_surface(text: str) -> str:
    """Normalize surface để bắt gần trùng.

    Không strip prefix thủ công. Ta giữ toàn bộ ý, chỉ chuẩn hóa Unicode/dấu câu/khoảng trắng.
    """

    text = unicodedata.normalize("NFC", text or "")
    text = strip_accents(text.lower())
    text = re.sub(r"https?://\S+", " <url> ", text)
    text = re.sub(r"`{1,3}.*?`{1,3}", " <code> ", text, flags=re.DOTALL)
    text = re.sub(r"[^\w\s<>#./+-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    surface = normalize_surface(text)
    if not surface:
        return []
    tokens = re.findall(r"[\w<>#./+-]+", surface, flags=re.UNICODE)
    return [tok for tok in tokens if tok and tok not in LOW_INFORMATION_TOKENS]


def char_ngrams(text: str, n: int = 4) -> frozenset[str]:
    surface = normalize_surface(text)
    if not surface:
        return frozenset()
    compact = re.sub(r"\s+", " ", surface)
    if len(compact) <= n:
        return frozenset({compact})
    return frozenset(compact[i : i + n] for i in range(len(compact) - n + 1))


def word_ngrams(tokens: Sequence[str], n: int = 2) -> frozenset[str]:
    if not tokens:
        return frozenset()
    if len(tokens) <= n:
        return frozenset({" ".join(tokens)})
    return frozenset(" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def sequence_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    # difflib hơi chậm nhưng dùng sau blocking nên ổn. Máy tính cũng cần lao động, đáng tiếc.
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def stable_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for part in parts:
        h.update(part.encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()[:20]


# -----------------------------------------------------------------------------
# Đọc / ghi dataset
# -----------------------------------------------------------------------------


def first_role(conversations: Sequence[dict[str, Any]], role: str) -> str:
    for item in conversations:
        if item.get("role") == role:
            return str(item.get("content", "") or "").strip()
    return ""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL lỗi ở dòng {line_no}: {exc}") from exc
    return records


def to_dataset_record(raw: dict[str, Any], index: int) -> DatasetRecord | None:
    conv = raw.get("conversations", [])
    if not isinstance(conv, list):
        return None
    conversations = [dict(item) for item in conv if isinstance(item, dict)]
    user = first_role(conversations, "user")
    assistant = first_role(conversations, "assistant")
    system = first_role(conversations, "system")
    if not user or not assistant:
        return None
    copied = dict(raw)
    copied["conversations"] = conversations
    return DatasetRecord(
        original_index=index,
        raw=copied,
        conversations=conversations,
        system_text=system,
        user_text=user,
        assistant_text=assistant,
    )


def apply_system_policy(record: DatasetRecord, config: PruneConfig) -> DatasetRecord:
    """Áp policy system prompt.

    preserve: giữ nguyên system prompt hiện có, không chèn mới.
    strip: bỏ toàn bộ system prompt khỏi record.
    minimal: đặt prompt cực ngắn.
    file: đọc prompt từ file do CLI chỉ định.

    Mặc định là preserve. Script prune không nên cosplay prompt builder.
    """

    mode = config.system_mode
    conversations = [dict(item) for item in record.conversations]

    if mode == "preserve":
        new_conv = conversations
    elif mode == "strip":
        new_conv = [item for item in conversations if item.get("role") != "system"]
    else:
        if mode == "minimal":
            prompt = MINIMAL_SYSTEM_PROMPT
        elif mode == "file":
            if not config.system_prompt_file:
                raise ValueError("--system-mode file cần --system-prompt-file")
            prompt = config.system_prompt_file.read_text(encoding="utf-8").strip()
        else:
            raise ValueError(f"system_mode không hợp lệ: {mode}")
        prompt = re.sub(r"\s+", " ", prompt).strip()
        without_system = [item for item in conversations if item.get("role") != "system"]
        new_conv = ([{"role": "system", "content": prompt}] if prompt else []) + without_system

    raw = dict(record.raw)
    raw["conversations"] = new_conv
    return DatasetRecord(
        original_index=record.original_index,
        raw=raw,
        conversations=new_conv,
        system_text=first_role(new_conv, "system"),
        user_text=first_role(new_conv, "user"),
        assistant_text=first_role(new_conv, "assistant"),
    )


# -----------------------------------------------------------------------------
# Feature extraction
# -----------------------------------------------------------------------------


def phrase_present(text: str, phrase: str) -> bool:
    """Boundary-aware phrase check.

    Không dùng `phrase in text` trần vì `ai` có thể match trong đủ thứ rác.
    Với phrase nhiều token, boundary vẫn bảo vệ hai đầu.
    """

    text_norm = normalize_surface(text)
    phrase_norm = normalize_surface(phrase)
    if not text_norm or not phrase_norm:
        return False
    pattern = rf"(?<![\w]){re.escape(phrase_norm)}(?![\w])"
    return re.search(pattern, text_norm, flags=re.UNICODE) is not None


def topic_distribution(user_text: str, assistant_text: str) -> dict[str, float]:
    """Tạo phân phối topic nhẹ từ user + assistant.

    Đây không phải classifier ngữ nghĩa. Nó chỉ giúp blocking/similarity.
    Điểm saturating để nhiều cue cùng loại tăng nhẹ, không bùng như pháo hoa heuristic.
    """

    combined = f"{user_text}\n{assistant_text}"
    scores: dict[str, float] = {}
    for topic, cues in TOPIC_CUES.items():
        hits = sum(1 for cue in cues if phrase_present(combined, cue))
        if hits:
            scores[topic] = min(1.0, 0.22 + math.log1p(hits) * 0.30)
    if not scores:
        return {"general": 0.35}
    total = sum(scores.values())
    if total <= 0:
        return {"general": 0.35}
    return {k: round(v / total, 4) for k, v in sorted(scores.items(), key=lambda item: item[1], reverse=True)}


def primary_topic(distribution: dict[str, float]) -> str:
    if not distribution:
        return "general"
    return max(distribution.items(), key=lambda item: item[1])[0]


def topic_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def assistant_template_hits(text: str) -> tuple[str, ...]:
    hits = [phrase for phrase in TEMPLATE_PHRASES if phrase_present(text, phrase)]
    return tuple(hits)


def sentence_count(text: str) -> int:
    chunks = [part.strip() for part in re.split(r"[.!?。！？\n]+", text or "") if part.strip()]
    return max(1, len(chunks)) if text.strip() else 0


def style_signature(assistant_text: str) -> str:
    """Rút signature style để phát hiện template lặp.

    Signature này không dùng để ép giọng ERIS. Nó chỉ giúp prune các câu assistant quá cùng khuôn.
    """

    text = assistant_text or ""
    surface = normalize_surface(text)
    tokens = tokenize(text)
    count = len(tokens)
    sentences = sentence_count(text)
    hits = assistant_template_hits(text)

    length_bucket = "short" if count <= 28 else "medium" if count <= 90 else "long"
    sentence_bucket = "one" if sentences <= 1 else "few" if sentences <= 3 else "many"
    has_ngai = "ngai" in tokens
    has_toi = "toi" in tokens
    has_boundary = any(phrase_present(text, cue) for cue in ("không phải", "khong phai", "runtime", "không bịa", "khong bia"))
    has_technical = any(phrase_present(text, cue) for cue in TOPIC_CUES["technical"])
    has_attachment = any(phrase_present(text, cue) for cue in TOPIC_CUES["relationship"])
    has_template = bool(hits)
    starts = ""
    if surface:
        starts = "_".join(surface.split()[:3])[:36]

    parts = [
        f"len={length_bucket}",
        f"sent={sentence_bucket}",
        f"ngai={int(has_ngai)}",
        f"toi={int(has_toi)}",
        f"boundary={int(has_boundary)}",
        f"tech={int(has_technical)}",
        f"attach={int(has_attachment)}",
        f"template={int(has_template)}",
        f"start={starts}",
    ]
    return ";".join(parts)


def quality_score(record: DatasetRecord) -> tuple[float, tuple[str, ...]]:
    """Chấm quality để khi duplicate thì giữ mẫu tốt hơn.

    Đây là heuristic, nhưng dùng cho ranking sau khi đã có duplicate signal,
    không dùng để phán bản chất record. Nhẹ tay thôi, không làm quan tòa văn học.
    """

    user = record.user_text
    assistant = record.assistant_text
    user_tokens = tokenize(user)
    assistant_tokens = tokenize(assistant)
    reasons: list[str] = []

    score = 0.55

    # Độ dài vừa phải thường tốt hơn câu quá cộc hoặc diễn văn.
    alen = len(assistant_tokens)
    if 12 <= alen <= 120:
        score += 0.12
        reasons.append("length_ok")
    elif alen < 6:
        score -= 0.20
        reasons.append("assistant_too_short")
    elif alen > 180:
        score -= 0.16
        reasons.append("assistant_too_long")

    # User quá ngắn nhưng assistant quá dài dễ là overfit style.
    if len(user_tokens) <= 4 and alen > 90:
        score -= 0.12
        reasons.append("long_answer_for_tiny_user")

    # Template style bị phạt nhẹ, không xóa ngay.
    hits = assistant_template_hits(assistant)
    if hits:
        score -= min(0.18, 0.06 * len(hits))
        reasons.append("template_phrase")

    # Technical user mà assistant có dấu hiệu action/step thì giữ ưu tiên hơn.
    user_topic = topic_distribution(user, "")
    if primary_topic(user_topic) == "technical":
        if any(phrase_present(assistant, cue) for cue in ("sửa", "sua", "thêm", "them", "file", "hàm", "ham", "test", "bước", "buoc")):
            score += 0.10
            reasons.append("technical_actionable")
        if any(phrase_present(assistant, cue) for cue in ("tâm trạng", "tam trang", "cảm xúc", "cam xuc")):
            score -= 0.10
            reasons.append("technical_style_drift")

    # Cấm dấu chấm cảm nếu dataset cũ muốn vậy, nhưng không biến thành luật vĩnh cửu của ERIS.
    if "!" in assistant:
        score -= 0.08
        reasons.append("exclamation")

    # Assistant duplicate exact quá nhiều thường là template rác, nhưng xử ở pass riêng.
    if len(set(assistant_tokens)) < max(4, len(assistant_tokens) * 0.35):
        score -= 0.08
        reasons.append("low_token_diversity")

    # Bảo toàn ranh giới runtime nếu record có nói năng lực/hệ thống.
    if any(phrase_present(user, cue) for cue in ("bạn là ai", "ban la ai", "người thật", "nguoi that", "waifu", "tool")):
        if any(phrase_present(assistant, cue) for cue in ("runtime", "không phải người", "khong phai nguoi", "không phải", "khong phai")):
            score += 0.08
            reasons.append("identity_boundary")

    return max(0.0, min(1.0, score)), tuple(reasons)


def make_signature(record: DatasetRecord) -> RecordSignature:
    user_surface = normalize_surface(record.user_text)
    assistant_surface = normalize_surface(record.assistant_text)
    user_tokens = tokenize(record.user_text)
    assistant_tokens = tokenize(record.assistant_text)
    topic_dist = topic_distribution(record.user_text, record.assistant_text)
    topic = primary_topic(topic_dist)
    qscore, qreasons = quality_score(record)
    pair_hash = stable_hash(user_surface, assistant_surface)

    # Blocking keys giảm so sánh O(N^2). Nếu key quá nghèo thì vẫn có topic/style làm fallback.
    first_user = " ".join(user_tokens[:5]) if user_tokens else "empty_user"
    first_assistant = " ".join(assistant_tokens[:5]) if assistant_tokens else "empty_assistant"
    style = style_signature(record.assistant_text)
    style_hash = stable_hash(style)[:10]

    block_keys = tuple(dict.fromkeys(
        key for key in (
            f"pair:{pair_hash}",
            f"topic:{topic}",
            f"user_start:{stable_hash(first_user)[:10]}",
            f"assistant_start:{stable_hash(first_assistant)[:10]}",
            f"style:{style_hash}",
            f"topic_style:{topic}:{style_hash}",
        ) if key
    ))

    return RecordSignature(
        index=record.original_index,
        user_surface=user_surface,
        assistant_surface=assistant_surface,
        pair_hash=pair_hash,
        user_char_ngrams=char_ngrams(record.user_text, 4),
        assistant_char_ngrams=char_ngrams(record.assistant_text, 4),
        user_word_ngrams=word_ngrams(user_tokens, 2),
        assistant_word_ngrams=word_ngrams(assistant_tokens, 2),
        user_tokens=frozenset(user_tokens),
        assistant_tokens=frozenset(assistant_tokens),
        style_signature=style,
        primary_topic=topic,
        topic_distribution=topic_dist,
        assistant_template_hits=assistant_template_hits(record.assistant_text),
        assistant_sentence_count=sentence_count(record.assistant_text),
        assistant_token_count=len(assistant_tokens),
        quality_score=qscore,
        quality_reasons=qreasons,
        block_keys=block_keys,
    )


# -----------------------------------------------------------------------------
# Duplicate detection
# -----------------------------------------------------------------------------


def user_similarity(a: RecordSignature, b: RecordSignature) -> float:
    surface = sequence_ratio(a.user_surface, b.user_surface)
    char_sim = jaccard(a.user_char_ngrams, b.user_char_ngrams)
    word_sim = jaccard(a.user_word_ngrams, b.user_word_ngrams)
    token_sim = jaccard(a.user_tokens, b.user_tokens)
    return max(surface * 0.85 + char_sim * 0.15, word_sim * 0.65 + token_sim * 0.35)


def assistant_similarity(a: RecordSignature, b: RecordSignature) -> float:
    surface = sequence_ratio(a.assistant_surface, b.assistant_surface)
    char_sim = jaccard(a.assistant_char_ngrams, b.assistant_char_ngrams)
    word_sim = jaccard(a.assistant_word_ngrams, b.assistant_word_ngrams)
    token_sim = jaccard(a.assistant_tokens, b.assistant_tokens)
    style_bonus = 0.08 if a.style_signature == b.style_signature else 0.0
    return min(1.0, max(surface * 0.80 + char_sim * 0.20, word_sim * 0.62 + token_sim * 0.30) + style_bonus)


def record_similarity(a: RecordSignature, b: RecordSignature) -> dict[str, float]:
    usim = user_similarity(a, b)
    asim = assistant_similarity(a, b)
    tsim = topic_similarity(a.topic_distribution, b.topic_distribution)
    same_style = 1.0 if a.style_signature == b.style_signature else 0.0
    combined = usim * 0.46 + asim * 0.42 + tsim * 0.08 + same_style * 0.04
    return {
        "user": usim,
        "assistant": asim,
        "topic": tsim,
        "same_style": same_style,
        "combined": combined,
    }


def is_near_duplicate(a: RecordSignature, b: RecordSignature, config: PruneConfig) -> tuple[bool, str, dict[str, float]]:
    """Quyết định duplicate gần đúng.

    Không dùng một ngưỡng duy nhất vì dataset chat có nhiều kiểu trùng:
        - user và assistant gần y hệt: duplicate mạnh.
        - user rất giống, assistant khác chữ nhưng cùng style/topic: template paraphrase.
        - assistant y hệt nhưng user hơi khác: có thể là template spam.
    """

    if a.pair_hash == b.pair_hash:
        return True, "exact_pair", {"combined": 1.0, "user": 1.0, "assistant": 1.0, "topic": 1.0, "same_style": 1.0}

    sim = record_similarity(a, b)
    if sim["combined"] >= config.similarity_threshold and sim["user"] >= 0.62 and sim["assistant"] >= 0.58:
        return True, "near_pair", sim

    if sim["user"] >= config.loose_user_threshold and sim["assistant"] >= config.assistant_threshold:
        return True, "same_user_similar_answer", sim

    if sim["user"] >= config.loose_user_threshold and sim["same_style"] >= 1.0 and sim["topic"] >= 0.82 and sim["assistant"] >= 0.52:
        return True, "same_user_template_style", sim

    if sim["assistant"] >= 0.92 and sim["topic"] >= 0.70:
        return True, "assistant_template_duplicate", sim

    return False, "", sim


class SimilarityIndex:
    """Chỉ mục blocking để tìm candidate gần trùng nhanh hơn.

    Thay vì so record mới với toàn bộ record đã giữ, ta chỉ so với những record chung block key.
    Đây không phải semantic index, nhưng đủ tốt cho dataset vừa/nhỏ và chạy độc lập.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, list[int]] = defaultdict(list)
        self._signatures: dict[int, RecordSignature] = {}

    def add(self, signature: RecordSignature) -> None:
        self._signatures[signature.index] = signature
        for key in signature.block_keys:
            self._by_key[key].append(signature.index)

    def candidates(self, signature: RecordSignature, *, limit: int = 160) -> list[RecordSignature]:
        counts: Counter[int] = Counter()
        for key in signature.block_keys:
            for idx in self._by_key.get(key, []):
                counts[idx] += 1
        # Ưu tiên candidate chung nhiều block key, sau đó mới theo index.
        out: list[RecordSignature] = []
        for idx, _ in counts.most_common(limit):
            sig = self._signatures.get(idx)
            if sig is not None:
                out.append(sig)
        return out


# -----------------------------------------------------------------------------
# Prune core
# -----------------------------------------------------------------------------


def build_records(raw_records: Sequence[dict[str, Any]], config: PruneConfig, stats: PruneStats) -> list[DatasetRecord]:
    records: list[DatasetRecord] = []
    for i, raw in enumerate(raw_records):
        rec = to_dataset_record(raw, i)
        if rec is None:
            stats.invalid_removed += 1
            stats.removed_reasons["invalid_or_missing_user_assistant"] += 1
            continue
        rec = apply_system_policy(rec, config)
        records.append(rec)
    return records


def prune(records: list[DatasetRecord], config: PruneConfig) -> tuple[list[DatasetRecord], PruneStats]:
    stats = PruneStats(before=len(records), system_mode=config.system_mode)
    signatures = {record.original_index: make_signature(record) for record in records}

    # Exact assistant lặp không bị xóa toàn bộ. Ta giữ vài mẫu tốt nhất cho mỗi exact assistant.
    exact_assistant_groups: dict[str, list[int]] = defaultdict(list)
    for sig in signatures.values():
        if sig.assistant_surface:
            exact_assistant_groups[sig.assistant_surface].append(sig.index)

    blocked_exact_assistant: set[int] = set()
    for assistant_surface, indexes in exact_assistant_groups.items():
        if len(indexes) <= config.max_exact_assistant:
            continue
        ranked = sorted(indexes, key=lambda idx: (signatures[idx].quality_score, -idx), reverse=True)
        allowed = set(ranked[: config.max_exact_assistant])
        for idx in indexes:
            if idx not in allowed:
                blocked_exact_assistant.add(idx)

    # Duyệt record chất lượng cao trước để cụm duplicate giữ mẫu tốt nhất.
    ranked_records = sorted(records, key=lambda r: (signatures[r.original_index].quality_score, -r.original_index), reverse=True)

    index = SimilarityIndex()
    kept: list[DatasetRecord] = []
    kept_by_cluster_anchor: dict[int, int] = defaultdict(int)
    removed_indexes: set[int] = set()
    exact_pair_seen: set[str] = set()

    for record in ranked_records:
        sig = signatures[record.original_index]

        if sig.quality_score < config.min_quality_score:
            removed_indexes.add(record.original_index)
            stats.low_quality_removed += 1
            stats.removed_reasons["low_quality"] += 1
            continue

        if sig.pair_hash in exact_pair_seen:
            removed_indexes.add(record.original_index)
            stats.exact_pair_removed += 1
            stats.removed_reasons["exact_pair"] += 1
            continue
        exact_pair_seen.add(sig.pair_hash)

        if record.original_index in blocked_exact_assistant:
            removed_indexes.add(record.original_index)
            stats.exact_assistant_removed += 1
            stats.removed_reasons["exact_assistant_over_cap"] += 1
            continue

        duplicate_anchor: int | None = None
        duplicate_reason = ""
        for candidate in index.candidates(sig):
            is_dup, reason, _sim = is_near_duplicate(sig, candidate, config)
            if not is_dup:
                continue
            # Mỗi anchor cluster chỉ giữ tối đa N mẫu. Nếu chưa đầy cụm, có thể giữ để đa dạng.
            anchor = candidate.index
            if kept_by_cluster_anchor[anchor] < config.max_per_cluster - 1:
                kept_by_cluster_anchor[anchor] += 1
                duplicate_anchor = None
                duplicate_reason = ""
                break
            duplicate_anchor = anchor
            duplicate_reason = reason
            break

        if duplicate_anchor is not None:
            removed_indexes.add(record.original_index)
            stats.near_duplicate_removed += 1
            stats.removed_reasons[duplicate_reason or "near_duplicate"] += 1
            continue

        kept.append(record)
        index.add(sig)

    if config.preserve_order:
        kept.sort(key=lambda r: r.original_index)

    stats.after = len(kept)
    stats.removed = stats.before - stats.after
    stats.clusters_seen = len(index._signatures)
    stats.kept_by_topic = dict(Counter(signatures[r.original_index].primary_topic for r in kept))
    return kept, stats


# -----------------------------------------------------------------------------
# Ghi output / CLI
# -----------------------------------------------------------------------------


def write_jsonl(path: Path, records: Sequence[DatasetRecord]) -> None:
    text = "\n".join(json.dumps(record.raw, ensure_ascii=False) for record in records)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def write_stats(path: Path, stats: PruneStats) -> None:
    path.write_text(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prune near-duplicate ERIS dataset records without forcing a long persona prompt."
    )
    parser.add_argument("path", nargs="?", default="src/dataset.jsonl", help="Đường dẫn dataset JSONL đầu vào.")
    parser.add_argument("--output", "-o", default="", help="Đường dẫn output. Bỏ trống thì ghi đè input.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in thống kê, không ghi file.")
    parser.add_argument("--no-backup", action="store_true", help="Không tạo .bak trước khi ghi đè input.")
    parser.add_argument("--stats", default="", help="Ghi thống kê prune ra file JSON.")

    parser.add_argument(
        "--system-mode",
        choices=("preserve", "strip", "minimal", "file"),
        default="preserve",
        help=(
            "Policy system prompt: preserve=giữ nguyên, strip=xóa, "
            "minimal=đặt prompt rất ngắn, file=đọc từ --system-prompt-file. Mặc định preserve."
        ),
    )
    parser.add_argument("--system-prompt-file", default="", help="File prompt dùng khi --system-mode file.")

    parser.add_argument("--similarity-threshold", type=float, default=0.74)
    parser.add_argument("--loose-user-threshold", type=float, default=0.84)
    parser.add_argument("--assistant-threshold", type=float, default=0.68)
    parser.add_argument("--max-per-cluster", type=int, default=3)
    parser.add_argument("--max-exact-assistant", type=int, default=2)
    parser.add_argument("--min-quality-score", type=float, default=0.18)
    parser.add_argument("--keep-ranked-order", action="store_true", help="Ghi theo thứ tự quality ranking thay vì thứ tự gốc.")
    return parser


def config_from_args(args: argparse.Namespace) -> PruneConfig:
    system_prompt_file = Path(args.system_prompt_file) if args.system_prompt_file else None
    if args.system_mode == "file" and system_prompt_file is None:
        raise SystemExit("--system-mode file cần --system-prompt-file")

    return PruneConfig(
        similarity_threshold=float(args.similarity_threshold),
        loose_user_threshold=float(args.loose_user_threshold),
        assistant_threshold=float(args.assistant_threshold),
        max_per_cluster=max(1, int(args.max_per_cluster)),
        max_exact_assistant=max(1, int(args.max_exact_assistant)),
        min_quality_score=max(0.0, min(1.0, float(args.min_quality_score))),
        preserve_order=not bool(args.keep_ranked_order),
        system_mode=args.system_mode,
        system_prompt_file=system_prompt_file,
        backup=not bool(args.no_backup),
        dry_run=bool(args.dry_run),
        stats_path=Path(args.stats) if args.stats else None,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    input_path = Path(args.path)
    output_path = Path(args.output) if args.output else input_path

    raw_records = load_jsonl(input_path)
    initial_stats = PruneStats(before=len(raw_records), system_mode=config.system_mode)
    records = build_records(raw_records, config, initial_stats)
    kept, stats = prune(records, config)

    # Gộp invalid_removed từ bước build vào stats chính.
    stats.before = len(raw_records)
    stats.invalid_removed = initial_stats.invalid_removed
    stats.removed_reasons.update(initial_stats.removed_reasons)
    stats.after = len(kept)
    stats.removed = stats.before - stats.after

    if not config.dry_run:
        if output_path == input_path and config.backup:
            backup_path = input_path.with_suffix(input_path.suffix + ".bak")
            shutil.copy2(input_path, backup_path)
        write_jsonl(output_path, kept)

    if config.stats_path:
        write_stats(config.stats_path, stats)

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
