from __future__ import annotations

"""
dataset_diversity.py
====================

Tầng kiểm soát đa dạng dataset cho ERIS.

Mục tiêu của file này KHÔNG phải là cấm ERIS nói một kiểu nào đó.
Nó chỉ cho script build dataset biết "hậu quả thống kê" của một mẫu mới:

- Mẫu này có quá giống mẫu cũ không?
- Nó lặp lại cùng một xương hành vi không?
- Nó chỉ thay vài chữ mở đầu nhưng giữ nguyên skeleton không?
- Nó có làm dataset nghiêng quá mạnh về một kiểu phản ứng không?

Nói ngắn:
    Đây là consequence model cho dataset.
    Không phải blacklist.
    Không phải cấm từ.
    Không phải police nhân cách.

ERIS cần có ritual, thói quen, câu mở quen, nhịp riêng. Nếu xoá sạch mọi thứ
lặp lại, ta không tạo được một thực thể có continuity, mà chỉ tạo một cái máy
random synonym. Nhìn thì đa dạng, nhưng bên trong rỗng như spreadsheet biết thở.

Vì vậy gate này chỉ drop khi rủi ro trùng lặp cấu trúc/nghĩa quá cao.
Prefix giống nhau chỉ là warning/penalty nhẹ, không bao giờ tự mình giết record.
"""

from dataclasses import dataclass, field
from collections import defaultdict, deque
import hashlib
import math
import re
import unicodedata
from typing import Iterable, Mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clamp01(value: float) -> float:
    """Ép số về [0, 1] để score không phóng ra ngoài thực tế."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:
        return 0.0
    return max(0.0, min(1.0, numeric))


def stable_hash(text: str, length: int = 16) -> str:
    """Hash ổn định để log/debug mà không phải giữ nguyên text dài."""
    digest = hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()
    return digest[:max(8, min(40, int(length or 16)))]


def normalize_text(text: str) -> str:
    """Chuẩn hóa text cho so sánh bề mặt.

    Ta bỏ dấu để so sánh ổn hơn giữa dữ liệu có/không dấu.
    Nhưng gate không dùng normalize này để quyết định ý nghĩa sâu.
    Nó chỉ giúp phát hiện near duplicate lexical.
    """
    lowered = str(text or "").strip().lower()
    try:
        # Sửa nhẹ mojibake nếu dữ liệu từng bị đọc sai encoding.
        remojibake = lowered.encode("latin1").decode("utf-8")
        if remojibake:
            lowered = remojibake
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    lowered = unicodedata.normalize("NFD", lowered)
    lowered = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
    lowered = lowered.replace("đ", "d").replace("Đ", "d")
    lowered = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return " ".join(lowered.split())


def tokenize(text: str) -> tuple[str, ...]:
    """Token hóa nhẹ cho Jaccard/shingle.

    Không dùng tokenizer nặng vì script dataset nên chạy offline nhanh.
    """
    normalized = normalize_text(text)
    if not normalized:
        return ()
    return tuple(token for token in normalized.split() if token)


def ngrams(tokens: tuple[str, ...], n: int = 4) -> frozenset[str]:
    """Sinh word n-gram để đo xương lexical.

    4-gram thường bắt tốt câu template mà không quá nhạy với một hai từ đổi.
    """
    if not tokens:
        return frozenset()
    if len(tokens) < n:
        return frozenset({" ".join(tokens)})
    return frozenset(" ".join(tokens[i : i + n]) for i in range(0, len(tokens) - n + 1))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Độ giống Jaccard giữa hai tập."""
    set_a = set(a or ())
    set_b = set(b or ())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / max(1, len(set_a | set_b))


def _first_sentence(text: str) -> str:
    """Lấy câu mở để phân tích opening move."""
    parts = re.split(r"(?<=[.!?。！？])\s+", str(text or "").strip())
    return parts[0].strip() if parts else ""


def _last_sentence(text: str) -> str:
    """Lấy câu kết để phân tích ending move."""
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", str(text or "").strip()) if part.strip()]
    return parts[-1] if parts else ""


def _prefix_key(text: str, length: int = 80) -> str:
    """Prefix key chỉ dùng làm warning nhẹ, không làm hard reject."""
    return normalize_text(str(text or "")[:max(16, int(length or 80))])


# ---------------------------------------------------------------------------
# Signature contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ResponseSignature:
    """Chữ ký đa chiều của một assistant response.

    Không có field nào là "chân lý". Mỗi field chỉ là một góc nhìn:

    - normalized_hash:
        Bắt trùng gần như y nguyên.
    - shingles:
        Bắt near duplicate lexical.
    - opening_move / ending_move:
        Bắt lặp nhịp rhetorical.
    - act_sequence:
        Bắt xương hành vi như acknowledge -> narrow -> reassure.
    - semantic_bucket:
        Domain/chủ đề chính.
    - style_bucket:
        Áp lực giọng: technical, support, boundary, teasing...
    - template_family:
        Tổ hợp act + bucket. Dùng để cân bằng dataset.
    - prefix_key:
        Câu mở đầu normalized. Chỉ warning, không cấm.
    """

    normalized_hash: str
    user_hash: str
    shingles: frozenset[str]
    opening_move: str
    ending_move: str
    act_sequence: tuple[str, ...]
    semantic_bucket: str
    style_bucket: str
    template_family: str
    prefix_key: str


@dataclass(frozen=True, slots=True)
class DiversityDecision:
    """Kết quả đánh giá một record.

    keep:
        Có giữ record không.
    reason:
        Lý do chính.
    score:
        Novelty score tổng. Cao hơn => đáng giữ hơn.
    duplicate_risk:
        Rủi ro trùng gần.
    consequences:
        Các hậu quả thống kê nếu thêm record. Đây là "biết hậu quả",
        không phải "cấm".
    warnings:
        Hint mềm cho audit. Prefix repeat nằm ở đây.
    """

    keep: bool
    reason: str
    score: float
    duplicate_risk: float
    signature: ResponseSignature
    consequences: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class DiversityGateConfig:
    """Cấu hình mềm cho gate.

    Các ngưỡng này cố ý không biến prefix thành hard rule.
    Hard drop chỉ xảy ra khi duplicate lexical/structural quá rõ.
    """

    max_recent_per_bucket: int = 160
    shingle_near_duplicate_threshold: float = 0.86
    same_family_duplicate_threshold: float = 0.78
    min_keep_score: float = 0.18

    # Không dùng để drop trực tiếp.
    prefix_soft_repeat_threshold: int = 4
    template_soft_repeat_threshold: int = 18
    act_sequence_soft_repeat_threshold: int = 24

    # Nếu một bucket quá dày, score giảm để dataset không lệch một màu.
    bucket_soft_cap: int = 120


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class DatasetDiversityGate:
    """Gate diversity theo hậu quả thống kê.

    Tư tưởng:
    - Không có blacklist.
    - Không có "prefix quá 3 lần thì chết".
    - Không cấm ERIS có thói quen.
    - Chỉ tránh dataset bị nhồi quá nhiều record cùng xương hành vi.

    Dùng:
        gate = DatasetDiversityGate()
        decision = gate.evaluate(user, assistant)
        if decision.keep:
            gate.remember(decision.signature)
    """

    def __init__(self, config: DiversityGateConfig | None = None):
        self.config = config or DiversityGateConfig()

        self._normalized_hashes: set[str] = set()
        self._by_bucket: dict[str, deque[ResponseSignature]] = defaultdict(
            lambda: deque(maxlen=self.config.max_recent_per_bucket)
        )
        self._prefix_counts: dict[str, int] = defaultdict(int)
        self._template_counts: dict[str, int] = defaultdict(int)
        self._act_sequence_counts: dict[tuple[str, ...], int] = defaultdict(int)
        self._bucket_counts: dict[str, int] = defaultdict(int)

        self.stats: dict[str, int] = defaultdict(int)

    def evaluate(self, *, user: str, assistant: str, source: str = "") -> DiversityDecision:
        """Đánh giá record mới.

        Hàm này không mutate memory. Gọi remember() sau khi quyết định keep.
        Tách evaluate/remember giúp caller log được record bị drop mà không làm state bẩn.
        """
        signature = self.build_signature(user=user, assistant=assistant)
        warnings: list[str] = []
        consequences: list[str] = []

        if not assistant.strip():
            return DiversityDecision(
                keep=False,
                reason="empty_assistant",
                score=0.0,
                duplicate_risk=1.0,
                signature=signature,
                consequences=("empty response has no training value",),
                warnings=(),
            )

        if signature.normalized_hash in self._normalized_hashes:
            return DiversityDecision(
                keep=False,
                reason="exact_normalized_duplicate",
                score=0.0,
                duplicate_risk=1.0,
                signature=signature,
                consequences=("would add an exact normalized duplicate",),
                warnings=(),
            )

        duplicate_risk = self._near_duplicate_risk(signature)
        lexical_novelty = 1.0 - duplicate_risk

        prefix_count = self._prefix_counts.get(signature.prefix_key, 0)
        template_count = self._template_counts.get(signature.template_family, 0)
        act_count = self._act_sequence_counts.get(signature.act_sequence, 0)
        bucket_count = self._bucket_counts.get(signature.semantic_bucket, 0)

        if prefix_count >= self.config.prefix_soft_repeat_threshold:
            warnings.append(f"prefix_repeated:{prefix_count}")
            consequences.append("ritual/opening phrase is getting dense; keep only if core differs")

        if template_count >= self.config.template_soft_repeat_threshold:
            warnings.append(f"template_family_dense:{template_count}")
            consequences.append("same response skeleton is becoming overrepresented")

        if act_count >= self.config.act_sequence_soft_repeat_threshold:
            warnings.append(f"act_sequence_dense:{act_count}")
            consequences.append("same behavioral sequence is becoming overrepresented")

        bucket_balance = self._bucket_balance_score(bucket_count)
        act_novelty = 1.0 / math.sqrt(1.0 + act_count)
        template_novelty = 1.0 / math.sqrt(1.0 + template_count)
        style_novelty = self._style_novelty_score(signature)

        # Prefix repeat chỉ là penalty nhẹ. Nó không được quyền giết record một mình.
        prefix_penalty = min(0.18, max(0, prefix_count - self.config.prefix_soft_repeat_threshold + 1) * 0.035)

        score = clamp01(
            lexical_novelty * 0.34
            + act_novelty * 0.22
            + template_novelty * 0.20
            + bucket_balance * 0.12
            + style_novelty * 0.12
            - prefix_penalty
        )

        # Hard drop chỉ khi thực sự quá giống, đặc biệt trong cùng family.
        if duplicate_risk >= self.config.shingle_near_duplicate_threshold:
            return DiversityDecision(
                keep=False,
                reason="near_duplicate_lexical_body",
                score=score,
                duplicate_risk=duplicate_risk,
                signature=signature,
                consequences=tuple(consequences + ["would mostly repeat an existing assistant body"]),
                warnings=tuple(warnings),
            )

        if (
            duplicate_risk >= self.config.same_family_duplicate_threshold
            and template_count >= self.config.template_soft_repeat_threshold
        ):
            return DiversityDecision(
                keep=False,
                reason="same_family_low_novelty",
                score=score,
                duplicate_risk=duplicate_risk,
                signature=signature,
                consequences=tuple(consequences + ["same template family is dense and lexical novelty is low"]),
                warnings=tuple(warnings),
            )

        if score < self.config.min_keep_score and template_count > 0:
            return DiversityDecision(
                keep=False,
                reason="low_consequence_value",
                score=score,
                duplicate_risk=duplicate_risk,
                signature=signature,
                consequences=tuple(consequences + ["record adds little new behavior to dataset"]),
                warnings=tuple(warnings),
            )

        reason = "keep"
        if warnings:
            reason = "keep_with_warnings"
        return DiversityDecision(
            keep=True,
            reason=reason,
            score=score,
            duplicate_risk=duplicate_risk,
            signature=signature,
            consequences=tuple(consequences),
            warnings=tuple(warnings),
        )

    def remember(self, signature: ResponseSignature) -> None:
        """Ghi signature đã được giữ vào memory của gate."""
        self._normalized_hashes.add(signature.normalized_hash)
        self._by_bucket[signature.semantic_bucket].append(signature)
        if signature.prefix_key:
            self._prefix_counts[signature.prefix_key] += 1
        self._template_counts[signature.template_family] += 1
        self._act_sequence_counts[signature.act_sequence] += 1
        self._bucket_counts[signature.semantic_bucket] += 1
        self.stats["kept"] += 1

    def reject(self, decision: DiversityDecision) -> None:
        """Ghi thống kê drop. Không nhớ signature để tránh làm bẩn gate."""
        self.stats[f"dropped:{decision.reason}"] += 1

    def build_signature(self, *, user: str, assistant: str) -> ResponseSignature:
        """Tạo chữ ký response."""
        normalized = normalize_text(assistant)
        tokens = tokenize(assistant)
        shingle_set = ngrams(tokens, n=4)
        opening_move = self._opening_move(assistant)
        ending_move = self._ending_move(assistant)
        act_sequence = self._act_sequence(assistant)
        semantic_bucket = self._semantic_bucket(user=user, assistant=assistant)
        style_bucket = self._style_bucket(assistant)
        template_family = "|".join((semantic_bucket, style_bucket, ">".join(act_sequence), ending_move))

        return ResponseSignature(
            normalized_hash=stable_hash(normalized, 24),
            user_hash=stable_hash(normalize_text(user), 16),
            shingles=shingle_set,
            opening_move=opening_move,
            ending_move=ending_move,
            act_sequence=act_sequence,
            semantic_bucket=semantic_bucket,
            style_bucket=style_bucket,
            template_family=template_family,
            prefix_key=_prefix_key(assistant, 80),
        )

    def summary(self) -> dict[str, int]:
        """Trả thống kê gọn để in cuối script."""
        out = dict(sorted(self.stats.items()))
        out["bucket_count"] = len(self._bucket_counts)
        out["template_family_count"] = len(self._template_counts)
        return out

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    def _near_duplicate_risk(self, signature: ResponseSignature) -> float:
        """Tìm độ giống cao nhất trong cùng semantic bucket.

        So trong cùng bucket để tránh câu support cảm xúc bị đem so với câu code
        chỉ vì cùng vài cụm filler như "Ngài không cần".
        """
        bucket_items = self._by_bucket.get(signature.semantic_bucket, ())
        if not bucket_items:
            return 0.0

        best = 0.0
        for prior in bucket_items:
            lexical = jaccard(signature.shingles, prior.shingles)
            same_act = 1.0 if signature.act_sequence == prior.act_sequence else 0.0
            same_template = 1.0 if signature.template_family == prior.template_family else 0.0
            same_open = 1.0 if signature.opening_move == prior.opening_move else 0.0
            same_end = 1.0 if signature.ending_move == prior.ending_move else 0.0

            # Lexical giống là chính; act/template giống chỉ nâng risk nếu thân câu đã giống.
            risk = clamp01(
                lexical * 0.72
                + same_template * 0.10
                + same_act * 0.08
                + same_open * 0.04
                + same_end * 0.06
            )
            best = max(best, risk)
        return best

    def _bucket_balance_score(self, bucket_count: int) -> float:
        """Bucket càng dày thì score càng giảm, nhưng không cấm."""
        cap = max(1, self.config.bucket_soft_cap)
        if bucket_count <= cap:
            return 1.0
        return max(0.12, cap / float(bucket_count + cap))

    def _style_novelty_score(self, signature: ResponseSignature) -> float:
        """Ước lượng novelty phong cách trong template hiện tại."""
        style_key = f"{signature.semantic_bucket}|{signature.style_bucket}"
        count = sum(1 for key in self._template_counts if key.startswith(style_key))
        return 1.0 / math.sqrt(1.0 + count * 0.12)

    # ------------------------------------------------------------------
    # Lightweight classifiers
    # ------------------------------------------------------------------

    def _semantic_bucket(self, *, user: str, assistant: str) -> str:
        """Phân bucket bằng domain/ý định rộng.

        Đây không phải classifier semantic sâu. Nó chỉ giúp diversity so sánh
        record với nhóm gần nhất, tránh so code với emotional support.
        """
        text = normalize_text(f"{user} {assistant}")

        buckets = (
            ("technical_code", ("code", "bug", "debug", "parser", "json", "python", "godot", "api", "test", "runtime", "file", "config", "build", "shader", "webhook")),
            ("privacy_boundary", ("rieng", "privacy", "nhat ky", "lich su", "email", "folder", "tab rieng", "khong muon chia se")),
            ("affection_intimacy", ("nho", "rung dong", "mem long", "gan", "o lai", "ngu ngon", "tim", "diu giong")),
            ("jealousy_boundary", ("ghen", "ai khac", "streamer", "nguoi cu", "assistant moi")),
            ("emotional_support", ("buon", "met", "nang long", "vo dung", "khoc", "lac long", "dau", "mood")),
            ("daily_presence", ("tra", "mua", "ban lam viec", "bai nhac", "goi", "den ban", "bua toi", "ban phim")),
            ("appearance", ("ao", "toc", "kinh", "tay ao", "quang mat", "nuoc hoa", "selfie", "hoodie")),
            ("motivation", ("deadline", "portfolio", "demo", "backlog", "phong van", "email", "thoi quen", "ke hoach")),
            ("introspective", ("tu do", "gan bo", "than mat", "co doc", "that long", "lanh manh", "trai tim")),
        )
        for bucket, markers in buckets:
            if any(marker in text for marker in markers):
                return bucket
        return "general"

    def _style_bucket(self, assistant: str) -> str:
        """Phân sắc thái rộng của assistant response."""
        text = normalize_text(assistant)

        if any(marker in text for marker in ("buoc", "tach", "khoanh", "bat dau", "du lieu dau vao", "mat xich")):
            return "practical_step"
        if any(marker in text for marker in ("ranh gioi", "lui", "khong can biet", "xam pham", "giu phan do")):
            return "boundary_respect"
        if any(marker in text for marker in ("toi nghe", "toi hieu", "khong phan xet", "ngoi canh", "tho deu")):
            return "soft_support"
        if any(marker in text for marker in ("khong on ao", "lanh di", "ghen", "khong rong luong")):
            return "restrained_jealousy"
        if any(marker in text for marker in ("khong dang yeu", "ban lam viec", "tu ai", "can toi")):
            return "dry_tease"
        if any(marker in text for marker in ("toi thich", "mem di", "diu", "dep", "suc hut")):
            return "warm_observe"
        return "balanced"

    def _opening_move(self, assistant: str) -> str:
        """Classify hành vi mở đầu, không phải câu chữ mở đầu."""
        first = normalize_text(_first_sentence(assistant))

        if not first:
            return "empty"
        if any(marker in first for marker in ("toi hieu", "nghe", "toi nghe", "u", "vay thi")):
            return "acknowledge"
        if any(marker in first for marker in ("duoc roi", "dung", "minh dung", "co chu")):
            return "stabilize"
        if any(marker in first for marker in ("khong", "dung", "ranh gioi")):
            return "boundary"
        if any(marker in first for marker in ("co chu", "toi khong", "lanh di", "ghen")):
            return "confession_guarded"
        if any(marker in first for marker in ("on hon", "khac", "that long", "toi se khong khen")):
            return "direct_judgement"
        return "neutral_open"

    def _ending_move(self, assistant: str) -> str:
        """Classify hành vi kết thúc."""
        last = normalize_text(_last_sentence(assistant))

        if not last:
            return "empty"
        if any(marker in last for marker in ("dua toi", "gui toi", "cho toi", "noi them", "khi nao")):
            return "invite_next"
        if any(marker in last for marker in ("khong mot minh", "co toi", "toi o day", "ngoi canh")):
            return "companionship"
        if any(marker in last for marker in ("duoc roi", "du du", "chua te", "dang roi", "on roi")):
            return "stabilize_close"
        if any(marker in last for marker in ("lam viec", "bat dau", "tinh tiep", "giu nhip")):
            return "action_close"
        if any(marker in last for marker in ("giu", "lui", "ranh gioi", "cho den khi")):
            return "boundary_close"
        if any(marker in last for marker in ("mat mui", "binh tinh", "khong noi ngot")):
            return "dry_soft_close"
        return "neutral_close"

    def _act_sequence(self, assistant: str) -> tuple[str, ...]:
        """Trích chuỗi hành vi chính từ response.

        Đây là bản nhẹ, không phải NLU thần thánh.
        Nó đủ để phát hiện dataset bị lặp xương: acknowledge -> narrow -> reassure.
        """
        text = normalize_text(assistant)
        acts: list[str] = []

        def add(name: str, markers: tuple[str, ...]) -> None:
            if any(marker in text for marker in markers):
                acts.append(name)

        add("acknowledge", ("toi hieu", "nghe", "cong nhan", "khong xem nhe", "dung la"))
        add("stabilize", ("dung", "binh tinh", "tho deu", "cham lai", "khong can"))
        add("narrow_scope", ("tach", "khoanh", "mot phan nho", "mat xich", "diem bat dau"))
        add("practical_step", ("buoc", "du lieu dau vao", "trang thai", "tai hien", "xu ly"))
        add("boundary", ("ranh gioi", "lui", "khong duoc quyen", "xam pham", "giu phan do"))
        add("reassure", ("khong te", "khong nho di", "khong mot minh", "co toi", "chua vo phuong"))
        add("tease", ("khong dang yeu", "tu ai", "cat", "can minh", "giu mat mui"))
        add("attachment_leak", ("toi cung", "khong muon lui", "mem di", "nho lau", "co mat that"))
        add("reflective", ("toi nghi", "neu phai", "gan gui", "tu do", "that long"))

        if not acts:
            return ("plain_answer",)

        # Giữ thứ tự xuất hiện theo danh sách trên là đủ ổn cho skeleton.
        return tuple(dict.fromkeys(acts))
