from __future__ import annotations

"""
semantic_prototypes.py
======================

Prototype ngữ nghĩa cho các tầng semantic của ERIS.

Vì sao cần prototype?
---------------------
Lexical heuristic hỏi: "câu này có chứa token nào?"
Prototype semantic hỏi: "câu này gần loại ý nghĩa nào?"

Mỗi label được mô tả bằng nhiều câu mẫu ngắn. Encoder sẽ biến các câu mẫu này
thành vector, gộp centroid, rồi so với context hiện tại.

Điểm thiết kế quan trọng
-----------------------
- Prototype không phải rule cứng.
- Prototype không được tự quyết định hành động.
- Prototype chỉ tạo hypothesis có confidence và ambiguity.
- Mỗi prototype nên mô tả *ý nghĩa*, không mô tả keyword.

Sai:
    "youtube video tutorial docs"
Đúng:
    "user is using media as learning material for a technical task"

Tức là bớt thờ phụng token. Một ngày hiếm hoi văn minh.
"""

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence


# Domain dùng string để tránh phụ thuộc cứng vào enum hiện tại.
# Nếu enum ở orientation_context đổi tên, prototype bank vẫn ít vỡ hơn.
DOMAIN_ACTIVITY_INTENT = "activity_intent"
DOMAIN_GOAL_TEXT_KIND = "goal_text_kind"
DOMAIN_GOAL_RELATION = "goal_relation"
DOMAIN_FAILURE_CLASS = "failure_class"
DOMAIN_SPEECH_OPPORTUNITY = "speech_opportunity"


@dataclass(frozen=True, slots=True)
class PrototypePhrase:
    """Một câu mẫu semantic cho một label.

    text:
        Câu mô tả ý nghĩa.
    weight:
        Trọng số câu mẫu. Câu càng canonical càng nặng.
    tags:
        Anchor phụ để hypothesis engine có thể boost nhẹ khi context có cùng
        tag. Đây không phải keyword rule chính, chỉ là phụ gia, như muối. Đổ
        cả lọ vào thì món ăn chết.
    """

    text: str
    weight: float = 1.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrototypeSet:
    """Tập câu mẫu cho một label trong một domain."""

    domain: str
    label: str
    phrases: tuple[PrototypePhrase, ...]
    prior: float = 0.5
    description: str = ""
    negative_labels: tuple[str, ...] = ()

    @property
    def phrase_texts(self) -> tuple[str, ...]:
        return tuple(phrase.text for phrase in self.phrases)

    @property
    def all_tags(self) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for phrase in self.phrases:
            for tag in phrase.tags:
                key = tag.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(tag)
        return tuple(out)


@dataclass(slots=True)
class PrototypeBank:
    """Kho prototype có thể mở rộng.

    Bank giữ dữ liệu thuần. Nó không encode vector. Việc encode nằm ở
    `semantic_hypothesis.py` để cache/model không bị lẫn vào định nghĩa nghĩa.
    """

    sets: dict[tuple[str, str], PrototypeSet] = field(default_factory=dict)

    def add(self, prototype_set: PrototypeSet) -> None:
        if not prototype_set.domain or not prototype_set.label:
            return
        if not prototype_set.phrases:
            return
        self.sets[(prototype_set.domain, prototype_set.label)] = prototype_set

    def extend(self, prototype_sets: Iterable[PrototypeSet]) -> None:
        for prototype_set in prototype_sets:
            self.add(prototype_set)

    def get(self, domain: str, label: str) -> PrototypeSet | None:
        return self.sets.get((domain, label))

    def by_domain(self, domain: str) -> tuple[PrototypeSet, ...]:
        return tuple(item for (item_domain, _), item in self.sets.items() if item_domain == domain)

    def labels(self, domain: str) -> tuple[str, ...]:
        return tuple(item.label for item in self.by_domain(domain))

    def domains(self) -> tuple[str, ...]:
        return tuple(sorted({domain for domain, _ in self.sets}))

    def merge(self, other: "PrototypeBank") -> "PrototypeBank":
        merged = PrototypeBank(dict(self.sets))
        merged.sets.update(other.sets)
        return merged


# ---------------------------------------------------------------------------
# Helper tạo phrase gọn
# ---------------------------------------------------------------------------


def p(text: str, weight: float = 1.0, *tags: str) -> PrototypePhrase:
    return PrototypePhrase(text=text, weight=weight, tags=tuple(tags))


# ---------------------------------------------------------------------------
# Prototype mặc định
# ---------------------------------------------------------------------------


def default_activity_intent_sets() -> tuple[PrototypeSet, ...]:
    """Prototype cho activity intent.

    Các câu mẫu tập trung vào nghĩa tình huống, không cố liệt kê app/token.
    """

    return (
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="technical_focus",
            prior=0.58,
            description="Người dùng đang làm việc kỹ thuật, debug, code hoặc thiết kế hệ thống.",
            phrases=(
                p("user is actively working on code implementation or debugging", 1.0, "code", "debug"),
                p("current context is a technical task requiring precise practical help", 1.0, "technical"),
                p("the user is editing, testing, reviewing, or refactoring software", 0.95, "software"),
                p("the active thread is architecture, runtime design, or source code correction", 0.9, "architecture"),
            ),
            negative_labels=("play_or_recovery", "possible_avoidance"),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="research",
            prior=0.54,
            description="Người dùng đang tìm hiểu, đọc tài liệu, xem hướng dẫn hoặc tra cứu để phục vụ hiểu biết.",
            phrases=(
                p("user is using material as a tutorial or reference for learning", 1.0, "learning"),
                p("media or documentation is being consumed to understand a technical topic", 1.0, "tutorial"),
                p("the activity supports investigation, study, or concept clarification", 0.9, "research"),
                p("the user is reading examples or documentation before implementing something", 0.9, "docs"),
            ),
            negative_labels=("possible_avoidance",),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="supportive_background",
            prior=0.46,
            description="Âm thanh/media làm nền hỗ trợ tập trung, không phải task chính.",
            phrases=(
                p("background media is helping the user maintain focus", 1.0, "background"),
                p("music or ambient content is present while the main task continues", 0.95, "music"),
                p("the content is passive support rather than a competing activity", 0.9, "focus_aid"),
            ),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="recovery",
            prior=0.48,
            description="Người dùng đang nghỉ, hồi phục năng lượng, hoặc tạm dừng hợp lý.",
            phrases=(
                p("user is taking a break to recover energy", 1.0, "rest"),
                p("current activity is rest, decompression, or a short pause", 0.95, "recovery"),
                p("the user is not necessarily avoiding work, just recovering", 0.88, "decompression"),
            ),
            negative_labels=("technical_focus", "possible_avoidance"),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="play_or_recovery",
            prior=0.42,
            description="Hoạt động giải trí có thể là chơi hoặc nghỉ, chưa chắc xung đột goal.",
            phrases=(
                p("user is doing entertainment or play that may be harmless recovery", 1.0, "play"),
                p("the activity is leisure and does not by itself prove avoidance", 0.95, "leisure"),
                p("gaming or entertainment appears as a separate low pressure activity", 0.85, "game"),
            ),
            negative_labels=("technical_focus",),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="possible_avoidance",
            prior=0.32,
            description="Có dấu hiệu né friction/task, nhưng phải cần goal pressure và evidence phụ mới được can thiệp.",
            phrases=(
                p("user may be escaping from an unresolved difficult task", 1.0, "avoidance"),
                p("current activity conflicts with a task that still needs action", 0.95, "conflict"),
                p("short form scrolling or repeated distraction appears after friction", 0.9, "doomscroll"),
                p("the user is drifting away from a concrete task with intervention permission", 0.85, "drift"),
            ),
            negative_labels=("research", "recovery", "technical_focus"),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="fragmented_switching",
            prior=0.34,
            description="Người dùng chuyển ngữ cảnh liên tục, attention bị chia nhỏ.",
            phrases=(
                p("user is rapidly switching between unrelated contexts", 1.0, "switching"),
                p("many windows or tasks compete for attention", 0.95, "fragmentation"),
                p("the session rhythm looks scattered rather than focused", 0.9, "scattered"),
            ),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="social_coordination",
            prior=0.42,
            description="Người dùng đang phối hợp xã hội, chat, họp, hoặc xử lý liên lạc.",
            phrases=(
                p("user is coordinating with other people through messages or calls", 1.0, "communication"),
                p("communication is part of the current practical context", 0.9, "chat"),
                p("meeting or messaging may support the active work instead of distracting from it", 0.82, "meeting"),
            ),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="system_waiting",
            prior=0.44,
            description="Hệ thống đang build/install/render/loading, user có thể đang chờ.",
            phrases=(
                p("system is building installing downloading rendering or waiting", 1.0, "wait"),
                p("the task is blocked by a tool or process that is running", 0.95, "build"),
                p("user may be waiting for a technical process to finish", 0.9, "system"),
            ),
        ),
        PrototypeSet(
            domain=DOMAIN_ACTIVITY_INTENT,
            label="unknown",
            prior=0.25,
            description="Không đủ tín hiệu để gán intent.",
            phrases=(
                p("the current activity is ambiguous and should not be overinterpreted", 1.0, "ambiguous"),
                p("there is not enough evidence to classify the user activity", 1.0, "uncertain"),
            ),
        ),
    )


def default_goal_text_kind_sets() -> tuple[PrototypeSet, ...]:
    """Prototype cho việc phân loại user text thành goal/casual/commentary."""

    return (
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "concrete_task",
            prior=0.62,
            description="User yêu cầu làm/sửa/tạo một việc cụ thể có thể hành động.",
            phrases=(
                p("user is directly asking to implement, fix, create, or modify something", 1.0, "task"),
                p("the request has a concrete deliverable and action should follow", 1.0, "deliverable"),
                p("the assistant should produce code, a patch, a file, or a direct fix", 0.95, "action"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "debug_thread",
            prior=0.58,
            description="User đang theo một lỗi/bug/test failure cần debug.",
            phrases=(
                p("user is investigating a bug or failing test", 1.0, "bug"),
                p("the conversation is about diagnosing why code or runtime behavior is wrong", 1.0, "debug"),
                p("the user expects technical fault analysis and repair direction", 0.92, "diagnosis"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "design_direction",
            prior=0.50,
            description="User đang định hướng kiến trúc dài hạn, không nhất thiết cần patch ngay.",
            phrases=(
                p("user is asking about architecture direction and long term system design", 1.0, "architecture"),
                p("the topic is conceptual structure rather than one immediate bug", 0.9, "design"),
                p("the user wants a better framework for future development", 0.9, "roadmap"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "research_thread",
            prior=0.46,
            description="User muốn tìm hiểu/so sánh/giải thích để hiểu trước khi làm.",
            phrases=(
                p("user is asking to understand or research a topic", 1.0, "research"),
                p("the request is exploratory and knowledge oriented", 0.9, "learning"),
                p("the user wants explanation rather than immediate implementation", 0.82, "explain"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "review_request",
            prior=0.52,
            description="User muốn đánh giá, soi lỗi, xem ổn chưa.",
            phrases=(
                p("user asks for review, critique, or validation", 1.0, "review"),
                p("the assistant should evaluate quality and hidden problems", 0.95, "critique"),
                p("the user wants to know whether the current solution is good enough", 0.9, "validation"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "correction_thread",
            prior=0.60,
            description="User đang sửa một hiểu lầm hoặc phản hồi trước đó.",
            phrases=(
                p("user is correcting a previous wrong interpretation", 1.0, "correction"),
                p("the assistant misunderstood or missed the requested action", 1.0, "repair"),
                p("the next answer should acknowledge the correction and adjust", 0.92, "misread"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "casual",
            prior=0.36,
            description="Nói chuyện thường, đùa, comment nhẹ, không phải goal bền.",
            phrases=(
                p("user is casually chatting without asking for a durable task", 1.0, "casual"),
                p("the message is playful commentary rather than an action request", 0.95, "playful"),
                p("there is no need to persist this as a goal", 0.9, "no_goal"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "recovery",
            prior=0.34,
            description="User nói về nghỉ ngơi/hồi phục, không nên biến thành task.",
            phrases=(
                p("user indicates rest, tiredness, or recovery", 1.0, "rest"),
                p("the message should not be turned into a productivity goal", 0.95, "recovery"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "commentary",
            prior=0.38,
            description="Nhận xét/kết luận/đánh giá của user, có thể hữu ích nhưng không phải task rõ.",
            phrases=(
                p("user is making a technical comment but not clearly asking for action", 1.0, "commentary"),
                p("the message provides framing or opinion rather than a direct deliverable", 0.9, "framing"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_TEXT_KIND,
            "none",
            prior=0.25,
            description="Không có goal đủ rõ.",
            phrases=(
                p("there is not enough commitment to store or pursue a goal", 1.0, "none"),
                p("the text is too thin or ambiguous to become a persistent thread", 0.9, "uncertain"),
            ),
        ),
    )


def default_goal_relation_sets() -> tuple[PrototypeSet, ...]:
    """Prototype cho quan hệ giữa context hiện tại và active goal."""

    return (
        PrototypeSet(
            DOMAIN_GOAL_RELATION,
            "aligned",
            prior=0.56,
            description="Hoạt động hiện tại trực tiếp hỗ trợ goal.",
            phrases=(
                p("current activity directly supports the active goal", 1.0, "aligned"),
                p("the user is continuing the same task or a necessary subtask", 0.95, "continuation"),
                p("the context is useful for solving the unresolved technical thread", 0.9, "support"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_RELATION,
            "adjacent",
            prior=0.46,
            description="Hoạt động liên quan gián tiếp hoặc hỗ trợ nền.",
            phrases=(
                p("current activity is adjacent to the goal but not the main action", 1.0, "adjacent"),
                p("the context may support coordination, reference, or preparation", 0.92, "support"),
                p("the activity does not strongly conflict with the active goal", 0.86, "neutral_support"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_RELATION,
            "neutral",
            prior=0.42,
            description="Không rõ hỗ trợ hay xung đột; nên giữ bình tĩnh, điều khó khăn hiếm thấy.",
            phrases=(
                p("current activity is separate and does not clearly affect the active goal", 1.0, "neutral"),
                p("there is no strong evidence of alignment or conflict", 0.95, "uncertain"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_RELATION,
            "conflicting",
            prior=0.28,
            description="Hoạt động có vẻ xung đột goal, nhưng cần confidence cao và permission mới can thiệp.",
            phrases=(
                p("current activity blocks or competes with a concrete unresolved goal", 1.0, "conflict"),
                p("the user is moving away from a task that still needs action", 0.95, "drift"),
                p("the activity suggests avoidance only when goal pressure is active", 0.88, "avoidance"),
            ),
        ),
        PrototypeSet(
            DOMAIN_GOAL_RELATION,
            "unknown",
            prior=0.24,
            description="Không đủ dữ kiện để xét quan hệ với goal.",
            phrases=(
                p("the relationship to the active goal is unknown", 1.0, "unknown"),
                p("more context is required before judging goal relation", 0.95, "ambiguous"),
            ),
        ),
    )


def default_failure_class_sets() -> tuple[PrototypeSet, ...]:
    """Prototype cho phân loại lỗi hội thoại/cognition.

    Tầng này chưa bắt buộc dùng trong orientation, nhưng để sẵn vì repair memory
    và self_observation sẽ cần semantic thật hơn keyword trong tương lai.
    """

    return (
        PrototypeSet(
            DOMAIN_FAILURE_CLASS,
            "misread",
            phrases=(
                p("assistant understood the user request as something else", 1.0, "misread"),
                p("the response answered the wrong interpretation of the prompt", 0.95, "wrong_intent"),
            ),
        ),
        PrototypeSet(
            DOMAIN_FAILURE_CLASS,
            "overread",
            phrases=(
                p("assistant inferred hidden emotion or motive without enough evidence", 1.0, "overread"),
                p("the response went too deep psychologically for a simple message", 0.95, "mindreading"),
            ),
        ),
        PrototypeSet(
            DOMAIN_FAILURE_CLASS,
            "underacted",
            phrases=(
                p("assistant talked about the issue instead of performing the requested action", 1.0, "underacted"),
                p("the user wanted code or a patch but received abstract explanation", 0.95, "no_action"),
            ),
        ),
        PrototypeSet(
            DOMAIN_FAILURE_CLASS,
            "tone_mismatch",
            phrases=(
                p("assistant used the wrong tone for a technical or repair context", 1.0, "tone"),
                p("the style became too poetic, emotional, generic, or assistant-like", 0.92, "style"),
            ),
        ),
    )


def default_speech_opportunity_sets() -> tuple[PrototypeSet, ...]:
    """Prototype cho mode nói/im lặng.

    Chỉ là hypothesis. Quyền nói thật vẫn phải qua SpeechOpportunity,
    Permission, Homeostasis và Arbitration.
    """

    return (
        PrototypeSet(
            DOMAIN_SPEECH_OPPORTUNITY,
            "practical_help",
            phrases=(
                p("the useful action is to give direct practical help", 1.0, "help"),
                p("the user needs an answer, patch, or concrete next step", 0.95, "answer"),
            ),
        ),
        PrototypeSet(
            DOMAIN_SPEECH_OPPORTUNITY,
            "technical_diagnosis",
            phrases=(
                p("the useful action is technical diagnosis with evidence", 1.0, "diagnosis"),
                p("the answer should identify cause, risk, and fix direction", 0.95, "debug"),
            ),
        ),
        PrototypeSet(
            DOMAIN_SPEECH_OPPORTUNITY,
            "silence",
            phrases=(
                p("speaking would be intrusive or not useful right now", 1.0, "silence"),
                p("there is no new meaning strong enough to interrupt", 0.95, "no_shift"),
            ),
        ),
        PrototypeSet(
            DOMAIN_SPEECH_OPPORTUNITY,
            "repair",
            phrases=(
                p("the assistant should repair a previous misunderstanding", 1.0, "repair"),
                p("the next response should acknowledge correction and act", 0.95, "correction"),
            ),
        ),
    )


def build_default_prototype_bank(*, include_failure: bool = True, include_speech: bool = True) -> PrototypeBank:
    """Tạo prototype bank mặc định cho ERIS."""

    bank = PrototypeBank()
    bank.extend(default_activity_intent_sets())
    bank.extend(default_goal_text_kind_sets())
    bank.extend(default_goal_relation_sets())
    if include_failure:
        bank.extend(default_failure_class_sets())
    if include_speech:
        bank.extend(default_speech_opportunity_sets())
    return bank


DEFAULT_PROTOTYPE_BANK = build_default_prototype_bank()
