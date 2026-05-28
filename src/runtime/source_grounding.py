from __future__ import annotations

"""
runtime/source_grounding.py

Tầng này là "cổng nguồn" trước khi ERIS gọi LLM hoặc dựng câu trả lời.

Nhiệm vụ:
- Phát hiện user đang hỏi về file cụ thể.
- Phát hiện user đang trỏ vào màn hình hiện tại.
- Phát hiện user có paste code hay không.
- Phân loại nguồn trả lời chính.
- Cap confidence theo độ chắc của nguồn.
- Tạo prompt context cho LLM để tránh overclaim.
- Tạo fallback decision khi thiếu evidence.

Nguyên tắc:
- File này KHÔNG đọc file thật, KHÔNG OCR, KHÔNG gọi web, KHÔNG ghi memory.
- Nó chỉ nhìn các tín hiệu đã có trong frame/runtime và quyết định "được phép dựa vào nguồn nào".
- Nếu thiếu evidence, nó phải ép fallback thay vì để model bịa "tôi thấy/đọc được".
"""

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping, Sequence


SourceKind = Literal[
    "pasted_code",
    "uploaded_file",
    "filename_only",
    "current_screen",
    "live_vision",
    "user_text",
    "memory",
    "web",
    "runtime_state",
    "unknown",
]


@dataclass(slots=True)
class SourceCandidate:
    """
    Một nguồn có thể dùng để trả lời.

    confidence ở đây là confidence của quyền dùng nguồn, không phải confidence của câu trả lời cuối.
    Ví dụ: user paste code rõ ràng -> pasted_code confidence cao.
    User nói "nhìn màn hình đi" nhưng không có OCR/vision fact -> current_screen candidate vẫn có,
    nhưng missing evidence sẽ kéo fallback.
    """

    kind: SourceKind
    confidence: float
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    evidence_preview: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceFallbackDecision:
    """
    Decision tối thiểu khi thiếu evidence.

    Đây không nhất thiết là `domain.Decision` thật của repo.
    Runtime có thể dùng `to_payload()` hoặc `to_runtime_decision()` để nối.
    """

    should_fallback: bool
    text: str
    parse_mode: str = "source_grounding_fallback"
    confidence: float = 0.30
    reason: str = ""
    missing_evidence: list[str] = field(default_factory=list)
    debug_trace: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "should_speak": bool(self.should_fallback and self.text.strip()),
            "parse_mode": self.parse_mode,
            "confidence": self.confidence,
            "debug_trace": self.debug_trace or self.reason,
        }

    def to_runtime_decision(self) -> Any:
        """
        Cố chuyển sang domain.Decision nếu repo có class này.
        Nếu không import được, trả payload dict. Đừng bắt cả runtime chết vì một helper.
        """

        try:
            from domain import Decision  # type: ignore

            return Decision(
                text=self.text,
                should_speak=bool(self.should_fallback and self.text.strip()),
                confidence=self.confidence,
                parse_mode=self.parse_mode,
                debug_trace=self.debug_trace or self.reason,
            )
        except Exception:
            return self.to_payload()


@dataclass(slots=True)
class MemoryAnswerProfile:
    """Semantic policy for memory/history questions.

    This is deliberately a profile, not a fallback sentence.  The LLM still
    words the answer, while downstream layers get stable metadata for
    confidence caps and action labels.
    """

    mode: Literal[
        "none",
        "continuity_check",
        "specific_recall",
        "session_history",
        "memory_lookup",
    ] = "none"
    speech_intent: str = ""
    speech_act: str = ""
    confidence_cap: float = 1.0
    requires_specific_anchor: bool = False
    has_specific_anchor: bool = False
    anchor_evidence_ids: list[str] = field(default_factory=list)
    evidence_preview: list[str] = field(default_factory=list)
    epistemic_stance: Literal["none", "partial_continuity", "anchored_recall", "admit_uncertainty"] = "none"
    reason: str = ""
    prompt_rules: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.mode != "none"

    def apply_cap(self, raw_confidence: float) -> float:
        try:
            return max(0.0, min(float(raw_confidence), float(self.confidence_cap)))
        except Exception:
            return float(self.confidence_cap)


@dataclass(slots=True)
class SourceGroundingReport:
    """
    Báo cáo grounding nguồn cho một turn.

    primary_source:
        Nguồn chính LLM được phép dựa vào.
    confidence_cap:
        Trần confidence cho output cuối. LLM/parser/Ti nên min(raw_confidence, cap).
    missing_evidence:
        Nếu có các mục thiếu nghiêm trọng, nên fallback hoặc hỏi user cung cấp evidence.
    forbidden_assumptions:
        Các claim không được nói ra.
    prompt_context:
        Context ngắn đưa vào prompt LLM.
    """

    user_text: str
    primary_source: SourceKind
    confidence_cap: float

    asks_about_file: bool = False
    file_mentions: list[str] = field(default_factory=list)

    refers_to_current_screen: bool = False
    screen_reference_strength: float = 0.0

    pasted_code_detected: bool = False
    code_language: str = "unknown"
    code_block_count: int = 0

    candidates: list[SourceCandidate] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    allowed_sources: list[SourceKind] = field(default_factory=list)
    grounding_source: str = "unknown"
    missing_evidence: list[str] = field(default_factory=list)
    preempt_mode: str = ""
    preempt_recommended: bool = False
    memory_allowed: bool = True
    memory_surface_allowed: bool = True
    memory_answer_allowed: bool = True
    memory_allowed_layers: tuple[str, ...] = ("procedural", "semantic", "episodic")
    memory_answer_profile: MemoryAnswerProfile = field(default_factory=MemoryAnswerProfile)
    warnings: list[str] = field(default_factory=list)
    forbidden_assumptions: list[str] = field(default_factory=list)
    answer_style_rules: list[str] = field(default_factory=list)
    prompt_context: str = ""
    fallback_decision: SourceFallbackDecision | None = None
    notes: list[str] = field(default_factory=list)

    def should_fallback(self) -> bool:
        return bool(self.fallback_decision and self.fallback_decision.should_fallback)

    @property
    def should_preempt_llm(self) -> bool:
        return bool(self.preempt_recommended)

    @property
    def max_confidence(self) -> float:
        return float(self.confidence_cap)

    def apply_cap(self, raw_confidence: float) -> float:
        try:
            return max(0.0, min(float(raw_confidence), float(self.confidence_cap)))
        except Exception:
            return self.confidence_cap

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceGroundingEngine:
    """
    Bộ phân loại grounding nguồn cho runtime.

    Cách dùng tối thiểu:
        report = SourceGroundingEngine().analyze(user_text, frame=frame)
        frame.source_grounding = report
        prompt += report.prompt_context
        if report.should_fallback():
            return report.fallback_decision.to_runtime_decision()

    Các nguồn được ưu tiên theo tính trực tiếp:
    1. pasted_code: user tự paste code vào chat.
    2. uploaded_file: user hỏi file/tệp/pdf/code file đã attach, nếu runtime có evidence file.
    3. current_screen: user trỏ màn hình, nếu runtime có vision/ocr/screen evidence.
    4. user_text: chỉ dựa vào câu user.
    5. memory/runtime_state: chỉ dùng như context phụ, không thay evidence hiện tại.
    """

    # Trần confidence theo nguồn. Đây là trần mềm, guard sau vẫn có thể hạ thêm.
    CONFIDENCE_CAPS: dict[SourceKind, float] = {
        "pasted_code": 0.95,
        "uploaded_file": 0.92,
        "current_screen": 0.78,
        "user_text": 0.86,
        "memory": 0.68,
        "web": 0.60,
        "runtime_state": 0.64,
        "unknown": 0.35,
        "filename_only": 0.28,
        "live_vision": 0.75,
    }

    # Khi nguồn được nhắc nhưng thiếu evidence trực tiếp.
    MISSING_SOURCE_CAPS: dict[SourceKind, float] = {
        "uploaded_file": 0.28,
        "current_screen": 0.25,
        "memory": 0.42,
        "web": 0.35,
        "unknown": 0.30,
        "runtime_state": 0.42,
        "user_text": 0.60,
        "pasted_code": 0.40,
        "filename_only": 0.28,
        "live_vision": 0.75,
    }

    FILE_EXTENSIONS = (
        "py", "txt", "pdf", "docx", "pptx", "xlsx", "csv", "json", "jsonl",
        "xml", "yaml", "yml", "md", "cs", "gd", "ts", "tsx", "js", "jsx",
        "java", "kt", "cpp", "c", "h", "hpp", "rs", "go", "php", "rb",
        "html", "css", "scss", "sql", "ipynb", "log", "toml", "ini",
    )

    FILE_REFERENCE_MARKERS = (
        "file này", "file kia", "file đó", "file vừa gửi", "file tôi gửi",
        "tệp này", "tệp vừa gửi", "pdf này", "ảnh này", "hình này",
        "screenshot này", "slide này", "deck này", "bài này", "văn bản đã dán",
        "trong file", "trong tệp", "đọc file", "mở file", "xem file",
        "attachment", "attached file", "uploaded file", "this file", "the file",
    )

    FILE_CONTENT_REQUEST_MARKERS = (
        "xem file",
        "doc file",
        "đọc file",
        "trong file",
        "noi dung file",
        "nội dung file",
        "review file",
        "tom tat file",
        "tóm tắt file",
        "giai thich file",
        "giải thích file",
        "file nay",
        "tệp này",
        "loi gi",
        "lỗi gì",
        "la gi",
        "là gì",
        "ham nao",
        "class nao",
    )

    SCREEN_REFERENCE_MARKERS = (
        "màn hình", "screen", "trên màn", "đang mở", "đang hiện",
        "nhìn này", "nhìn cái này", "nhìn màn hình", "xem màn hình",
        "chỗ này", "cái này", "nút này", "ô này", "lỗi này", "ảnh này",
        "hình này", "game này", "web này", "tab này", "cửa sổ này",
        "bấm gì", "click gì", "ấn gì", "nó hiện", "đang bị",
        "what is on my screen", "this screen", "look at this", "this error",
        "xem di", "ban xem di", "toi dang code gi", "dang code gi", "doan dang mo",
        "xem đi", "bạn xem đi", "tôi đang code gì", "đoạn đang mở",
    )

    MEMORY_REFERENCE_MARKERS = (
        "lần trước", "hôm trước", "trước đó", "như cũ", "như lần nãy",
        "đã nói", "đã bàn", "tôi từng", "bạn nhớ", "còn nhớ", "nhớ không",
        "previously", "last time", "remember when", "as before",
    )

    WEB_REFERENCE_MARKERS = (
        "mới nhất", "hiện tại", "bây giờ", "hôm nay", "giá", "lịch",
        "latest", "current", "today", "recent", "news", "release",
    )

    DEICTIC_SCREEN_MARKERS = (
        "cái này",
        "chỗ này",
        "nút này",
        "ô này",
        "lỗi này",
        "tab này",
        "màn này",
        "ảnh này",
        "hình này",
        "đây là gì",
        "cái kia",
        "xem di",
        "ban xem di",
        "toi dang code gi",
        "dang code gi",
        "doan dang mo",
        "xem đi",
        "bạn xem đi",
        "tôi đang code gì",
        "đoạn đang mở",
    )

    CODE_FENCE_RE = re.compile(r"```(?P<lang>[a-zA-Z0-9_+\-#.]*).*?```", re.DOTALL)
    FILENAME_RE = re.compile(
        r"(?<![\w./\\-])([\w .()\[\]-]{1,80}\.(?:"
        + "|".join(FILE_EXTENSIONS)
        + r"))(?![\w/\\-])",
        re.IGNORECASE,
    )

    def analyze(
        self,
        user_text: str,
        *,
        frame: Any = None,
        active_files: Sequence[Any] | None = None,
        screen_facts: Sequence[Any] | None = None,
        memory_packet: Any = None,
        runtime_state: Any = None,
        allow_web: bool = False,
        attach_to_frame: bool = True,
    ) -> SourceGroundingReport:
        """
        Phân tích nguồn trả lời chính.

        Parameters
        ----------
        user_text:
            Text user gửi trong turn hiện tại.
        frame:
            CognitiveFrame/runtime frame nếu có.
        active_files:
            Danh sách file/evidence file mà runtime đã biết. Có thể là string, dict, dataclass.
        screen_facts:
            OCR/vision/screen facts hiện có. Nếu None, engine tự thử đọc từ frame.
        memory_packet:
            MemoryPacket nếu prompt muốn dùng memory như context phụ.
        runtime_state:
            State runtime nếu cần detect current active file/window.
        allow_web:
            Nếu True, cho phép phân loại web là nguồn khả thi. Nếu False, web marker chỉ tạo missing evidence.
        attach_to_frame:
            Gắn report vào frame.source_grounding nếu có thể.
        """

        text = str(user_text or "")
        normalized = self._normalize(text)
        candidates: list[SourceCandidate] = []
        notes: list[str] = []

        file_mentions = self._detect_file_mentions(text, normalized)
        asks_about_file = bool(file_mentions or self._has_any(normalized, self.FILE_REFERENCE_MARKERS))

        code_info = self._detect_pasted_code(text)
        refers_to_screen, screen_strength = self._detect_screen_reference(normalized)

        memory_ref = self._has_any(normalized, self.MEMORY_REFERENCE_MARKERS)
        web_ref = self._has_any(normalized, self.WEB_REFERENCE_MARKERS)

        file_evidence = self._collect_file_evidence(frame=frame, active_files=active_files, runtime_state=runtime_state)
        screen_evidence = self._collect_screen_evidence(frame=frame, screen_facts=screen_facts, runtime_state=runtime_state)
        memory_evidence = self._collect_memory_evidence(frame=frame, memory_packet=memory_packet)
        user_evidence = self._collect_user_text_evidence(frame=frame, user_text=text)
        memory_profile = self._derive_memory_answer_profile(
            normalized=normalized,
            user_text=text,
            memory_ref=memory_ref,
            memory_evidence=memory_evidence,
        )

        if code_info["detected"]:
            candidates.append(
                SourceCandidate(
                    kind="pasted_code",
                    confidence=code_info["confidence"],
                    reason="User paste code trực tiếp trong chat.",
                    evidence_ids=user_evidence["ids"],
                    evidence_preview=code_info["preview"],
                )
            )

        if asks_about_file:
            if file_evidence["present"]:
                candidates.append(
                    SourceCandidate(
                        kind="uploaded_file",
                        confidence=file_evidence["confidence"],
                        reason="User hỏi về file/tệp và runtime có evidence file.",
                        evidence_ids=file_evidence["ids"],
                        evidence_preview=file_evidence["preview"],
                    )
                )
            else:
                candidates.append(
                    SourceCandidate(
                        kind="uploaded_file",
                        confidence=0.25,
                        reason="User hỏi về file/tệp nhưng runtime chưa có evidence file.",
                        evidence_ids=[],
                        evidence_preview=[],
                        missing=["file_evidence"],
                    )
                )

        if refers_to_screen:
            if screen_evidence["present"]:
                confidence = min(0.78, max(0.45, screen_evidence["confidence"] * (0.75 + screen_strength * 0.25)))
                candidates.append(
                    SourceCandidate(
                        kind="current_screen",
                        confidence=confidence,
                        reason="User trỏ vào màn hình và runtime có screen/vision/ocr evidence.",
                        evidence_ids=screen_evidence["ids"],
                        evidence_preview=screen_evidence["preview"],
                    )
                )
            else:
                candidates.append(
                    SourceCandidate(
                        kind="current_screen",
                        confidence=0.22,
                        reason="User trỏ vào màn hình nhưng không có screen/vision/ocr evidence.",
                        evidence_ids=[],
                        evidence_preview=[],
                        missing=["screen_evidence"],
                    )
                )

        if memory_ref:
            if memory_evidence["present"]:
                candidates.append(
                    SourceCandidate(
                        kind="memory",
                        confidence=memory_evidence["confidence"],
                        reason="User tham chiếu lịch sử/điều đã nói và runtime có memory packet.",
                        evidence_ids=memory_evidence["ids"],
                        evidence_preview=memory_evidence["preview"],
                    )
                )
            else:
                candidates.append(
                    SourceCandidate(
                        kind="memory",
                        confidence=0.38,
                        reason="User tham chiếu lịch sử nhưng không có memory packet đáng tin.",
                        evidence_ids=[],
                        evidence_preview=[],
                        missing=["memory_packet"],
                    )
                )

        if web_ref:
            candidates.append(
                SourceCandidate(
                    kind="web",
                    confidence=0.60 if allow_web else 0.32,
                    reason="User dùng marker cần thông tin hiện tại/web.",
                    evidence_ids=[],
                    evidence_preview=[],
                    missing=[] if allow_web else ["web_access_or_search_result"],
                )
            )

        # User text luôn là nguồn nền nếu có text.
        if text.strip():
            candidates.append(
                SourceCandidate(
                    kind="user_text",
                    confidence=0.72 if not candidates else 0.55,
                    reason="Có thể trả lời dựa trên câu user hiện tại.",
                    evidence_ids=user_evidence["ids"],
                    evidence_preview=user_evidence["preview"],
                )
            )

        if not candidates:
            candidates.append(
                SourceCandidate(
                    kind="unknown",
                    confidence=0.20,
                    reason="Không có text/evidence đủ rõ.",
                    missing=["user_text_or_evidence"],
                )
            )

        primary = self._choose_primary_source(candidates)
        missing_evidence = self._derive_missing_evidence(primary, candidates)

        # QUAN TRỌNG:
        # Nếu user đã paste code trực tiếp, nội dung code trong chat chính là evidence.
        # Không được để marker kiểu "file này" kéo hệ thống về missing=file_evidence nữa.
        # Lỗi cũ: user paste code + hỏi "file này lỗi gì" vẫn bị fallback như chưa có file.
        if code_info["detected"] and "file_evidence" in missing_evidence:
            missing_evidence = [item for item in missing_evidence if item != "file_evidence"]
            notes.append("pasted_code_satisfies_file_content_request")

        deictic = refers_to_screen and self._is_deictic_screen_reference(normalized)
        has_fresh_vision = bool(screen_evidence["present"])
        has_retrieved_file = bool(file_evidence["present"])
        visible_code = has_fresh_vision
        user_code = bool(code_info["detected"])
        memory_allowed = True
        memory_surface_allowed = True
        memory_answer_allowed = True
        memory_allowed_layers: tuple[str, ...] = ("procedural", "semantic", "episodic")
        warnings: list[str] = []
        primary_source: SourceKind = primary.kind
        grounding_source = primary.kind
        confidence_cap_override: float | None = None
        should_preempt = False

        # Nếu user paste code rồi nói "đoạn này/cái này", đó là deictic trỏ vào code vừa paste,
        # không phải bắt buộc trỏ màn hình. Pasted code phải thắng screen-deictic.
        if deictic and not user_code:
            if has_fresh_vision:
                primary_source = "live_vision"
                grounding_source = "live_vision"
                confidence_cap_override = 0.75
                memory_surface_allowed = False
                memory_answer_allowed = False
                memory_allowed_layers = ("procedural",)
            else:
                primary_source = "unknown"
                grounding_source = "unknown"
                confidence_cap_override = 0.28
                should_preempt = True
                memory_surface_allowed = False
                memory_answer_allowed = False
                memory_allowed_layers = ("procedural",)
                warnings.append("deictic_screen_query_without_fresh_vision")
        elif (
            asks_about_file
            and self._looks_like_file_content_request(normalized)
            and not has_retrieved_file
            and not visible_code
            and not user_code
        ):
            primary_source = "filename_only"
            grounding_source = "filename_only"
            confidence_cap_override = 0.28
            should_preempt = True
            memory_surface_allowed = False
            memory_answer_allowed = False
            memory_allowed_layers = ("procedural",)
            warnings.append("specific_file_reference_without_content")

        if memory_profile.active and confidence_cap_override is None:
            # MemoryAnswerProfile already encodes the epistemic shape of the
            # request.  Let it own the cap instead of letting the generic
            # primary source cap flatten session-history and recall queries.
            confidence_cap_override = float(memory_profile.confidence_cap)
            notes.append(f"memory_answer_profile={memory_profile.mode}")

        forbidden = self._derive_forbidden_assumptions(
            primary_source=primary_source,
            asks_about_file=asks_about_file,
            refers_to_screen=refers_to_screen,
            code_detected=bool(code_info["detected"]),
            file_evidence_present=bool(file_evidence["present"]),
            screen_evidence_present=bool(screen_evidence["present"]),
            memory_evidence_present=bool(memory_evidence["present"]),
            allow_web=allow_web,
            web_ref=web_ref,
        )
        answer_rules = self._derive_answer_style_rules(primary_source, missing_evidence=missing_evidence)

        allowed_sources = [candidate.kind for candidate in candidates if not candidate.missing and candidate.confidence >= 0.45]
        if primary_source == "live_vision":
            allowed_sources = self._dedupe([*allowed_sources, "live_vision"])
        confidence_cap = confidence_cap_override if confidence_cap_override is not None else self._cap_for(primary, missing_evidence=missing_evidence)
        preempt_mode = ""
        if should_preempt:
            preempt_mode = self._derive_preempt_mode(
                normalized=normalized,
                file_mentions=file_mentions,
                missing_evidence=missing_evidence,
            )
        if should_preempt and not preempt_mode:
            preempt_mode = "deictic_without_vision" if deictic else "filename_only"

        report = SourceGroundingReport(
            user_text=text,
            primary_source=primary_source,
            confidence_cap=confidence_cap,
            asks_about_file=asks_about_file,
            file_mentions=file_mentions,
            refers_to_current_screen=refers_to_screen,
            screen_reference_strength=screen_strength,
            pasted_code_detected=bool(code_info["detected"]),
            code_language=str(code_info["language"]),
            code_block_count=int(code_info["block_count"]),
            candidates=candidates,
            evidence_ids=self._dedupe([*primary.evidence_ids, *file_evidence["ids"], *screen_evidence["ids"], *memory_evidence["ids"], *user_evidence["ids"]])[:20],
            allowed_sources=self._dedupe(allowed_sources),
            grounding_source=grounding_source,
            missing_evidence=missing_evidence,
            preempt_mode=preempt_mode,
            preempt_recommended=should_preempt or preempt_mode in {"filename_only", "deictic_without_vision"},
            memory_allowed=memory_allowed,
            memory_surface_allowed=memory_surface_allowed,
            memory_answer_allowed=memory_answer_allowed,
            memory_allowed_layers=memory_allowed_layers,
            memory_answer_profile=memory_profile,
            warnings=warnings,
            forbidden_assumptions=forbidden,
            answer_style_rules=answer_rules,
            notes=notes,
        )

        report.prompt_context = self.render_prompt_context(report)
        report.fallback_decision = self.build_fallback_decision(report)

        if attach_to_frame:
            self._safe_setattr(frame, "source_grounding", report)
            self._safe_setattr(frame, "grounding", report)
            # Cho các guard cũ đọc dễ hơn mà không phải biết dataclass mới.
            self._safe_setattr(frame, "source_confidence_cap", report.confidence_cap)
            self._safe_setattr(frame, "source_forbidden_assumptions", tuple(report.forbidden_assumptions))
            self._safe_setattr(frame, "source_grounding_source", report.grounding_source)
            self._safe_setattr(frame, "source_grounding_preempt_mode", report.preempt_mode)
            self._safe_setattr(frame, "source_grounding_memory_answer_allowed", report.memory_answer_allowed)
            self._safe_setattr(frame, "source_memory_answer_profile", report.memory_answer_profile)

        return report

    def classify(self, *args: Any, **kwargs: Any) -> SourceGroundingReport:
        return self.analyze(*args, **kwargs)

    def analyze_frame(self, frame: Any, **kwargs: Any) -> SourceGroundingReport:
        """
        Helper khi caller chỉ có frame.

        Cố lấy user_text từ percepts/final input của frame.
        """

        user_text = self._extract_user_text_from_frame(frame)
        return self.analyze(user_text, frame=frame, **kwargs)

    def apply_confidence_cap(self, raw_confidence: float, report_or_frame: Any) -> float:
        """
        Cap confidence ngoài pipeline.

        Có thể truyền SourceGroundingReport hoặc frame có `source_grounding`.
        """

        report = report_or_frame
        if not isinstance(report_or_frame, SourceGroundingReport):
            report = getattr(report_or_frame, "source_grounding", None) or getattr(report_or_frame, "grounding", None)
        if isinstance(report, SourceGroundingReport):
            return report.apply_cap(raw_confidence)
        try:
            return max(0.0, min(0.50, float(raw_confidence)))
        except Exception:
            return 0.35

    def should_preempt(
        self,
        report_or_frame: Any,
        *,
        modes: Sequence[str] = ("filename_only", "deictic_without_vision"),
    ) -> bool:
        report = report_or_frame
        if not isinstance(report_or_frame, SourceGroundingReport):
            report = getattr(report_or_frame, "source_grounding", None) or getattr(report_or_frame, "grounding", None)
        if not isinstance(report, SourceGroundingReport):
            return False
        return bool(report.should_preempt_llm or (report.preempt_mode and report.preempt_mode in set(modes)))

    def render_prompt_context(self, report: SourceGroundingReport) -> str:
        """
        Tạo prompt context ngắn cho LLM.

        Context này không phải văn phong. Nó là giới hạn nhận thức:
        LLM được phép dựa vào gì và không được claim gì.
        """

        lines: list[str] = [
            "[SOURCE_GROUNDING]",
            f"primary_source: {report.primary_source}",
            f"confidence_cap: {report.confidence_cap:.2f}",
        ]

        if report.allowed_sources:
            lines.append("allowed_sources: " + ", ".join(report.allowed_sources))
        if report.file_mentions:
            lines.append("file_mentions: " + ", ".join(report.file_mentions[:6]))
        if report.pasted_code_detected:
            lines.append(f"pasted_code: yes; language={report.code_language}; blocks={report.code_block_count}")
        if report.refers_to_current_screen:
            lines.append(f"current_screen_reference: yes; strength={report.screen_reference_strength:.2f}")
        if report.evidence_ids:
            lines.append("evidence_ids: " + ", ".join(report.evidence_ids[:12]))
        if report.missing_evidence:
            lines.append("missing_evidence: " + ", ".join(report.missing_evidence))
        if report.warnings:
            lines.append("warnings: " + ", ".join(report.warnings))
        lines.append(
            "memory_policy: "
            f"allowed={int(report.memory_allowed)}; "
            f"surface_allowed={int(report.memory_surface_allowed)}; "
            f"answer_allowed={int(report.memory_answer_allowed)}; "
            f"layers={', '.join(report.memory_allowed_layers)}"
        )
        memory_profile = getattr(report, "memory_answer_profile", None)
        if getattr(memory_profile, "active", False):
            lines.append(
                "memory_answer_profile: "
                f"mode={memory_profile.mode}; "
                f"speech_intent={memory_profile.speech_intent}; "
                f"speech_act={memory_profile.speech_act}; "
                f"confidence_cap={memory_profile.confidence_cap:.2f}; "
                f"requires_specific_anchor={int(memory_profile.requires_specific_anchor)}; "
                f"has_specific_anchor={int(memory_profile.has_specific_anchor)}; "
                f"stance={memory_profile.epistemic_stance}"
            )
            if memory_profile.evidence_preview:
                lines.append("memory_anchor_preview: " + " | ".join(memory_profile.evidence_preview[:3]))
            if memory_profile.prompt_rules:
                lines.append("memory_answer_rules:")
                for rule in memory_profile.prompt_rules[:8]:
                    lines.append(f"- {rule}")
        if report.forbidden_assumptions:
            lines.append("forbidden_assumptions:")
            for item in report.forbidden_assumptions[:8]:
                lines.append(f"- {item}")
        if report.answer_style_rules:
            lines.append("answer_rules:")
            for rule in report.answer_style_rules[:8]:
                lines.append(f"- {rule}")

        lines.append("[/SOURCE_GROUNDING]")
        return "\n".join(lines)

    def build_fallback_decision(self, report: SourceGroundingReport) -> SourceFallbackDecision:
        """
        Tạo fallback nếu nguồn user yêu cầu chưa có evidence.

        Rule:
        - Hỏi file mà không có file evidence: không được tóm tắt/đánh giá file.
        - Trỏ màn hình mà không có screen evidence: không được nói đang thấy gì.
        - Hỏi thông tin mới nhất nhưng chưa search: không được phán theo memory.
        """

        missing = set(report.missing_evidence)
        if not missing:
            return SourceFallbackDecision(
                should_fallback=False,
                text="",
                confidence=report.confidence_cap,
                reason="source_grounding_ok",
                debug_trace="source_grounding:ok",
            )

        text = ""
        reason = "missing_evidence"

        if "file_evidence" in missing:
            file_name = (report.file_mentions[0] if getattr(report, "file_mentions", None) else "file đó")
            text = (
                f"Tôi chưa đọc được nội dung `{file_name}` trong runtime này. "
                "Nếu chỉ dựa vào tên file hoặc ký ức cũ thì tôi chỉ đang đoán. "
                "Mở file lên rõ hơn hoặc paste đoạn cần xem, rồi tôi phân tích chắc."
            )
            reason = "missing_file_evidence"
        elif "screen_evidence" in missing:
            text = "Tôi chưa có bằng chứng màn hình ở turn này, nên không được giả vờ là đang thấy nó. Gửi ảnh, OCR hoặc mô tả lỗi hiện trên màn hình."
            reason = "missing_screen_evidence"
        elif "web_access_or_search_result" in missing:
            text = "Thông tin này cần nguồn hiện tại. Chưa có kết quả web/search trong frame, nên tôi không nên phán như thể vừa kiểm tra."
            reason = "missing_web_evidence"
        elif "memory_packet" in missing:
            text = "Tôi chưa có memory packet đủ chắc cho chi tiết đó. Tôi có thể trả lời theo phần Ngài vừa nói, nhưng không nên giả vờ nhớ chính xác."
            reason = "missing_memory_evidence"
        else:
            text = "Tín hiệu chưa đủ để trả lời chắc. Cần thêm evidence trước khi kết luận."
            reason = "missing_required_evidence"

        return SourceFallbackDecision(
            should_fallback=True,
            text=text,
            confidence=min(0.35, report.confidence_cap),
            reason=reason,
            missing_evidence=report.missing_evidence,
            debug_trace=f"source_grounding:{reason}:{','.join(report.missing_evidence)}",
        )

    def build_preemptive_reply(self, report: SourceGroundingReport) -> str:
        fallback = self.build_fallback_decision(report)
        return str(getattr(fallback, "text", "") or "").strip()

    def _derive_memory_answer_profile(
        self,
        *,
        normalized: str,
        user_text: str,
        memory_ref: bool,
        memory_evidence: Mapping[str, Any],
    ) -> MemoryAnswerProfile:
        """Infer the memory/history answer shape for this turn.

        This does not produce a fallback sentence. It produces an epistemic
        policy: what kind of answer is being asked for, whether a concrete
        memory anchor is required, how confident the answer is allowed to be,
        and how the action plan should be labeled.
        """

        tokens = set((normalized or "").split())
        has_memory_verb = bool({"nho", "remember", "recall"} & tokens)
        has_question_shape = bool({"khong", "gi", "nao", "la", "what", "which", "when"} & tokens) or "?" in str(user_text or "")
        temporal_reference = any(
            phrase in normalized
            for phrase in (
                "truoc do",
                "lan truoc",
                "hom truoc",
                "vua nay",
                "luc nay",
                "last time",
                "previously",
                "before",
            )
        )
        asks_session_order = (
            (("cau" in tokens or "tin" in tokens or "message" in tokens) and ("dau" in tokens or "first" in tokens))
            or "cau dau tien" in normalized
            or "tin dau tien" in normalized
            or "first message" in normalized
        )
        asks_prior_content = any(
            phrase in normalized
            for phrase in (
                "da noi gi",
                "da bao gi",
                "da doc gi",
                "doc bai",
                "bai tho",
                "poem",
                "noi truoc do",
                "nghe truoc do",
            )
        )
        asks_continuity_check = has_memory_verb and has_question_shape and not (
            temporal_reference or asks_session_order or asks_prior_content
        )
        asks_memory_lookup = bool(memory_ref or temporal_reference or asks_prior_content or asks_session_order or asks_continuity_check)
        if not asks_memory_lookup:
            return MemoryAnswerProfile()

        anchor_ids = list(memory_evidence.get("ids", []) or [])
        previews = [str(item) for item in list(memory_evidence.get("preview", []) or []) if str(item).strip()]
        has_anchor = bool(previews or anchor_ids)

        if asks_session_order:
            return MemoryAnswerProfile(
                mode="session_history",
                speech_intent="history_lookup",
                speech_act="answer_direct",
                confidence_cap=0.92,
                requires_specific_anchor=True,
                has_specific_anchor=True,
                anchor_evidence_ids=anchor_ids,
                evidence_preview=previews[:3],
                epistemic_stance="anchored_recall",
                reason="user asks for an auditable fact from the current session order",
                prompt_rules=[
                    "Answer from the current chat/session transcript, not from long-term memory if the transcript is available.",
                    "Quote or paraphrase the concrete turn if known; otherwise explicitly say the session record is insufficient.",
                    "Do not label this as emotional mirroring; it is a history lookup.",
                ],
            )

        if asks_continuity_check:
            return MemoryAnswerProfile(
                mode="continuity_check",
                speech_intent="memory_lookup",
                speech_act="memory_lookup",
                confidence_cap=0.75,
                requires_specific_anchor=False,
                has_specific_anchor=has_anchor,
                anchor_evidence_ids=anchor_ids,
                evidence_preview=previews[:3],
                epistemic_stance="partial_continuity",
                reason="user asks whether ERIS remembers, but not a concrete retrievable episode",
                prompt_rules=[
                    "Answer as partial runtime continuity, not perfect human memory.",
                    "Avoid absolute scope claims such as remembering everything or storing everything.",
                    "Use a restrained clause like 'the parts still recorded' or 'what remains in continuity' naturally, not as a disclaimer dump.",
                ],
            )

        if asks_prior_content:
            cap = 0.78 if has_anchor else 0.55
            return MemoryAnswerProfile(
                mode="specific_recall",
                speech_intent="memory_lookup",
                speech_act="memory_lookup",
                confidence_cap=cap,
                requires_specific_anchor=True,
                has_specific_anchor=has_anchor,
                anchor_evidence_ids=anchor_ids,
                evidence_preview=previews[:3],
                epistemic_stance="anchored_recall" if has_anchor else "admit_uncertainty",
                reason="user asks for specific previous content",
                prompt_rules=[
                    "A concrete prior content answer requires a retrieved anchor, quote, transcript item, or memory evidence.",
                    "If no anchor is available, answer that the current memory packet is insufficient; do not invent the prior content.",
                    "Do not perform warmth as evidence. Warmth is style; memory is evidence.",
                ],
            )

        cap = 0.82 if has_anchor else 0.68
        return MemoryAnswerProfile(
            mode="memory_lookup",
            speech_intent="memory_lookup",
            speech_act="memory_lookup",
            confidence_cap=cap,
            requires_specific_anchor=False,
            has_specific_anchor=has_anchor,
            anchor_evidence_ids=anchor_ids,
            evidence_preview=previews[:3],
            epistemic_stance="anchored_recall" if has_anchor else "partial_continuity",
            reason="user references memory/history without demanding exact current evidence",
            prompt_rules=[
                "Use retrieved memory as bounded evidence, not as proof of perfect recall.",
                "State uncertainty through phrasing if the memory anchor is weak or absent.",
            ],
        )

    def _choose_primary_source(self, candidates: Sequence[SourceCandidate]) -> SourceCandidate:
        """
        Chọn nguồn chính.

        Ưu tiên nguồn trực tiếp và ít suy diễn hơn.
        Nếu nguồn user yêu cầu bị thiếu evidence, vẫn chọn nó làm primary để fallback đúng lý do,
        thay vì rơi xuống user_text rồi để LLM lách.
        """

        priority: dict[SourceKind, int] = {
            "pasted_code": 100,
            "uploaded_file": 92,
            "filename_only": 91,
            "live_vision": 90,
            "current_screen": 88,
            "web": 76,
            "memory": 70,
            "user_text": 60,
            "runtime_state": 50,
            "unknown": 0,
        }

        def score(candidate: SourceCandidate) -> float:
            missing_penalty = -8.0 if candidate.missing else 0.0
            return priority.get(candidate.kind, 0) + candidate.confidence * 10.0 + missing_penalty

        return max(candidates, key=score)

    def _cap_for(self, primary: SourceCandidate, *, missing_evidence: Sequence[str]) -> float:
        if missing_evidence:
            return self.MISSING_SOURCE_CAPS.get(primary.kind, 0.30)
        cap = self.CONFIDENCE_CAPS.get(primary.kind, 0.35)
        # Candidate confidence thấp thì cap không được cao hơn nhiều.
        return self._clamp01(min(cap, max(0.30, primary.confidence + 0.10)))

    def _derive_missing_evidence(
        self,
        primary: SourceCandidate,
        candidates: Sequence[SourceCandidate],
    ) -> list[str]:
        missing: list[str] = []
        for candidate in candidates:
            # Missing ở source được user yêu cầu mới đáng chặn.
            if candidate.kind in {"uploaded_file", "current_screen", "web", "memory"}:
                missing.extend(candidate.missing)
        if primary.missing:
            missing.extend(primary.missing)
        return self._dedupe(missing)

    def _derive_forbidden_assumptions(
        self,
        *,
        primary_source: SourceKind,
        asks_about_file: bool,
        refers_to_screen: bool,
        code_detected: bool,
        file_evidence_present: bool,
        screen_evidence_present: bool,
        memory_evidence_present: bool,
        allow_web: bool,
        web_ref: bool,
    ) -> list[str]:
        forbidden: list[str] = []

        if asks_about_file and not file_evidence_present and not code_detected:
            forbidden.extend(
                [
                    "Không được nói đã đọc file.",
                    "Không được tóm tắt/đánh giá nội dung file khi chưa có file evidence.",
                    "Không được bịa tên hàm/class/dòng lỗi trong file.",
                ]
            )

        if refers_to_screen and not screen_evidence_present:
            forbidden.extend(
                [
                    "Không được nói 'tôi thấy trên màn hình'.",
                    "Không được chỉ nút/cửa sổ/vị trí UI cụ thể nếu không có screen evidence.",
                    "Không được kết luận lỗi hiện trên màn hình chỉ từ câu trỏ mơ hồ.",
                ]
            )

        if not code_detected and primary_source != "pasted_code":
            forbidden.append("Không được giả vờ user đã paste code nếu không có code block hoặc code-like text.")

        if web_ref and not allow_web:
            forbidden.append("Không được nói thông tin hiện tại/mới nhất như đã kiểm tra web.")

        if primary_source == "memory" and not memory_evidence_present:
            forbidden.append("Không được giả vờ nhớ chính xác chi tiết lịch sử khi không có memory packet.")

        # Rule chung.
        forbidden.extend(
            [
                "Memory/recollection chỉ là context phụ, không thay evidence hiện tại.",
                "Nếu confidence thấp, phải dùng wording mềm hoặc fallback.",
            ]
        )
        return self._dedupe(forbidden)

    def _derive_answer_style_rules(self, primary: SourceKind, *, missing_evidence: Sequence[str]) -> list[str]:
        rules = [
            "Answer-first nếu evidence đủ; fallback-first nếu evidence thiếu.",
            "Nêu rõ nguồn đang dùng nếu có nguy cơ lẫn file/màn hình/memory.",
            "Không chuyển thiếu evidence thành suy diễn tâm lý.",
        ]

        if primary == "pasted_code":
            rules.extend(
                [
                    "Phân tích dựa trên code user paste trong chat.",
                    "Có thể trích tên hàm/class từ pasted code nếu thật sự xuất hiện.",
                    "Không claim đã đọc file ngoài đoạn paste.",
                ]
            )
        elif primary == "uploaded_file":
            rules.extend(
                [
                    "Chỉ trả lời dựa trên file evidence đã có.",
                    "Nếu file evidence thiếu, yêu cầu user gửi/paste file thay vì đoán.",
                ]
            )
        elif primary == "filename_only":
            rules.extend(
                [
                    "File name alone is not file content.",
                    "Procedural memory may remind grounding rules, but semantic/episodic memory must not answer the file.",
                    "Ask for pasted code or retrieved file content before explaining the file.",
                ]
            )
        elif primary == "current_screen":
            rules.extend(
                [
                    "Chỉ nói về màn hình nếu có screen/vision/ocr evidence.",
                    "Nếu screen evidence yếu, dùng 'có vẻ' hoặc hỏi thêm bằng chứng.",
                ]
            )
        elif primary == "live_vision":
            rules.extend(
                [
                    "Use only fresh vision/screen evidence for the current-screen answer.",
                    "Memory may only provide procedural grounding rules, not screen content.",
                ]
            )
        elif primary == "user_text":
            rules.append("Chỉ dựa vào câu user hiện tại; không claim nhìn thấy file/màn hình.")
        elif primary == "memory":
            rules.append("Phân biệt rõ 'tôi nhớ bối cảnh' với 'bằng chứng hiện tại'.")
        elif primary == "web":
            rules.append("Chỉ dùng web nếu runtime đã search hoặc allow_web bật.")

        if missing_evidence:
            rules.append("Không gọi LLM dài dòng; trả fallback ngắn để lấy đúng evidence.")
        return self._dedupe(rules)

    def _derive_preempt_mode(
        self,
        *,
        normalized: str,
        file_mentions: Sequence[str],
        missing_evidence: Sequence[str],
    ) -> str:
        missing = set(missing_evidence)
        concrete_files = [item for item in file_mentions if item and item != "<current_or_uploaded_file>"]
        if concrete_files and "file_evidence" in missing and self._looks_like_file_content_request(normalized):
            return "filename_only"
        if "screen_evidence" in missing and self._is_deictic_screen_reference(normalized):
            return "deictic_without_vision"
        return ""

    def _detect_file_mentions(self, text: str, normalized: str) -> list[str]:
        mentions: list[str] = []

        for match in self.FILENAME_RE.finditer(text):
            value = re.sub(r"\s+", " ", match.group(1)).strip()
            if value:
                mentions.append(value)

        # Bắt tên file trong dấu quote nếu có extension bị regex bỏ sót.
        quoted = re.findall(r"['\"`“”]([^'\"`“”]{1,100}\.(?:" + "|".join(self.FILE_EXTENSIONS) + r"))['\"`“”]", text, flags=re.I)
        mentions.extend(item.strip() for item in quoted if item.strip())

        if self._has_any(normalized, self.FILE_REFERENCE_MARKERS):
            # Marker này không phải tên file cụ thể, nhưng là tín hiệu user trỏ file.
            mentions.append("<current_or_uploaded_file>")

        return self._dedupe(mentions)[:10]

    def _detect_screen_reference(self, normalized: str) -> tuple[bool, float]:
        hits = [marker for marker in self.SCREEN_REFERENCE_MARKERS if self._normalize(marker) in normalized]
        if not hits:
            return False, 0.0

        strength = min(1.0, 0.28 + len(hits) * 0.16)

        # "cái này" rất mơ hồ, chỉ cho strength thấp nếu không có marker mạnh khác.
        weak_only = all(self._normalize(hit) in {"cai nay", "cho nay", "loi nay"} for hit in hits)
        if weak_only:
            strength = min(strength, 0.42)

        # File/image markers cũng có thể là uploaded image, nên strength vừa phải.
        if any(hit in {"ảnh này", "hình này"} for hit in hits):
            strength = max(strength, 0.50)

        return True, self._clamp01(strength)

    def _is_deictic_screen_reference(self, normalized: str) -> bool:
        return any(self._normalize(marker) in normalized for marker in self.DEICTIC_SCREEN_MARKERS)

    def _looks_like_file_content_request(self, normalized: str) -> bool:
        if any(marker in normalized for marker in ("fix bug", "sua ", "sua loi", "implement ", "refactor ")):
            if not any(marker in normalized for marker in ("xem file", "doc file", "loi gi", "la gi", "review file")):
                return False
        return any(self._normalize(marker) in normalized for marker in self.FILE_CONTENT_REQUEST_MARKERS)

    def _detect_pasted_code(self, text: str) -> dict[str, Any]:
        if not text.strip():
            return {
                "detected": False,
                "language": "unknown",
                "block_count": 0,
                "confidence": 0.0,
                "preview": [],
            }

        fence_matches = list(self.CODE_FENCE_RE.finditer(text))
        languages = [match.group("lang").strip().lower() for match in fence_matches if match.group("lang").strip()]
        block_count = len(fence_matches)

        lines = [line.rstrip() for line in text.splitlines()]
        non_empty = [line for line in lines if line.strip()]
        code_like_score = 0.0
        preview: list[str] = []

        patterns = (
            r"^\s*(def|class|import|from)\s+",
            r"^\s*(async\s+def|await)\b",
            r"^\s*(public|private|protected|static|using|namespace)\b",
            r"^\s*(function|const|let|var|export|import)\b",
            r"^\s*(if|for|while|switch|try|catch|except|with)\b.*[:{]",
            r"^\s*[\w$]+\s*=\s*.+",
            r"^\s*</?\w+[^>]*>",
            r"^\s*#include\s*<",
            r"^\s*Traceback \(most recent call last\):",
            r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)\b",
        )

        for line in non_empty:
            stripped = line.strip()
            if len(preview) < 5 and stripped:
                preview.append(stripped[:160])
            if any(re.search(pattern, line, flags=re.I) for pattern in patterns):
                code_like_score += 1.0
            if any(token in line for token in ("{", "}", "=>", "::", "();", "==", "!=", "&&", "||")):
                code_like_score += 0.35
            if re.search(r"\b[a-zA-Z_][\w_]*\([^)]*\)", line):
                code_like_score += 0.35

        line_factor = min(1.0, len(non_empty) / 8.0)
        fence_bonus = 1.0 if block_count else 0.0
        density = code_like_score / max(1.0, len(non_empty))
        confidence = self._clamp01(0.20 * line_factor + 0.45 * fence_bonus + 0.65 * density)

        detected = bool(block_count or (len(non_empty) >= 3 and confidence >= 0.42))
        language = self._guess_code_language(text, languages=languages, preview=preview)

        return {
            "detected": detected,
            "language": language,
            "block_count": block_count,
            "confidence": max(confidence, 0.72 if block_count else confidence),
            "preview": preview[:5],
        }

    def _guess_code_language(self, text: str, *, languages: Sequence[str], preview: Sequence[str]) -> str:
        if languages:
            return str(languages[0] or "unknown").lower()

        low = text.lower()
        if re.search(r"^\s*(def|class|import|from)\s+", text, flags=re.M):
            return "python"
        if "using system" in low or re.search(r"\b(public|private|protected)\s+(class|void|string|int|float|bool)\b", low):
            return "csharp"
        if re.search(r"\b(function|const|let|var|export default|console\.log)\b", low):
            return "javascript"
        if re.search(r"</?\w+[^>]*>", text):
            return "xml/html"
        if re.search(r"\b(select|insert|update|delete|create table)\b", low):
            return "sql"
        if "#include" in low or "std::" in low:
            return "cpp"
        if "extends node" in low or "func _ready" in low:
            return "gdscript"
        if re.search(r"^\s*[{[]", text.strip()) and ":" in text:
            return "json"
        return "unknown"

    def _collect_file_evidence(
        self,
        *,
        frame: Any = None,
        active_files: Sequence[Any] | None = None,
        runtime_state: Any = None,
    ) -> dict[str, Any]:
        items: list[Any] = []
        if active_files:
            items.extend(active_files)

        for attr in (
            "active_files",
            "uploaded_files",
            "attached_files",
            "file_evidence",
            "source_files",
        ):
            value = getattr(frame, attr, None)
            if value:
                items.extend(self._as_list(value))

        for attr in ("active_file", "current_file", "uploaded_file"):
            value = getattr(runtime_state, attr, None)
            if value:
                items.append(value)

        # Evidence có source/tag file.
        for ev in self._as_list(getattr(frame, "evidence", None)):
            source = str(getattr(ev, "source", "") or self._mapping_get(ev, "source", "")).lower()
            tags = " ".join(str(tag) for tag in self._as_list(getattr(ev, "tags", self._mapping_get(ev, "tags", [])))).lower()
            if "file" in source or "upload" in source or "document" in source or "file" in tags or "uploaded" in tags:
                items.append(ev)

        ids, previews, confidence = self._summarize_evidence_items(items, default_confidence=0.72)
        return {
            "present": bool(items),
            "ids": ids,
            "preview": previews,
            "confidence": confidence,
        }

    def _collect_screen_evidence(
        self,
        *,
        frame: Any = None,
        screen_facts: Sequence[Any] | None = None,
        runtime_state: Any = None,
    ) -> dict[str, Any]:
        items: list[Any] = []
        if screen_facts:
            items.extend(screen_facts)

        for attr in (
            "screen_facts",
            "vision_facts",
            "ocr_facts",
            "visible_facts",
            "screen_evidence",
        ):
            value = getattr(frame, attr, None)
            if value:
                items.extend(self._as_list(value))

        for attr in ("vision_facts", "ocr_text", "current_screen", "screen_facts", "screen_evidence"):
            value = getattr(runtime_state, attr, None)
            if value:
                items.extend(self._as_list(value))

        snapshot = getattr(frame, "snapshot", None) or getattr(frame, "telemetry_snapshot", None)
        for attr in ("vision_facts", "screen_facts", "ocr_text", "screen_evidence", "current_screen"):
            value = getattr(snapshot, attr, None)
            if value:
                items.extend(self._as_list(value))

        for ev in self._as_list(getattr(frame, "evidence", None)):
            source = str(getattr(ev, "source", "") or self._mapping_get(ev, "source", "")).lower()
            tags_list = [
                str(tag or "").strip().lower()
                for tag in self._as_list(getattr(ev, "tags", self._mapping_get(ev, "tags", [])))
                if str(tag or "").strip()
            ]
            explicit_tag_tokens = {
                "vision",
                "vision_fact",
                "live_vision",
                "ocr",
                "ocr_text",
                "screen",
                "screen_capture",
                "screen_evidence",
                "visible",
                "visible_fact",
            }
            explicit_source = (
                source in explicit_tag_tokens
                or any(
                    source.startswith(prefix)
                    for prefix in ("vision_", "ocr_", "screen_", "visible_")
                )
            )
            explicit_tags = bool(set(tags_list) & explicit_tag_tokens)
            if explicit_source:
                items.append(ev)
            elif explicit_tags:
                items.append(ev)

        # Lọc bớt signal quá rỗng kiểu chỉ có "active window" không nội dung.
        non_empty_items = [item for item in items if self._preview_item(item)]
        ids, previews, confidence = self._summarize_evidence_items(non_empty_items, default_confidence=0.62)
        return {
            "present": bool(non_empty_items),
            "ids": ids,
            "preview": previews,
            "confidence": confidence,
        }

    def _collect_memory_evidence(self, *, frame: Any = None, memory_packet: Any = None) -> dict[str, Any]:
        items: list[Any] = []
        packet = memory_packet or getattr(frame, "memory_packet", None)
        if packet is not None:
            for attr in (
                "episodic",
                "semantic",
                "relational",
                "affective_residue",
                "procedural",
                "confidence_notes",
            ):
                value = getattr(packet, attr, None)
                if value:
                    items.extend(self._as_list(value))
            if isinstance(packet, Mapping):
                for key in (
                    "episodic",
                    "semantic",
                    "relational",
                    "affective_residue",
                    "procedural",
                    "confidence_notes",
                ):
                    value = packet.get(key)
                    if value:
                        items.extend(self._as_list(value))

        ids, previews, confidence = self._summarize_evidence_items(items, default_confidence=0.55)
        return {
            "present": bool(items),
            "ids": ids,
            "preview": previews,
            "confidence": min(confidence, 0.68),
        }

    def _collect_user_text_evidence(self, *, frame: Any = None, user_text: str = "") -> dict[str, Any]:
        ids: list[str] = []
        for ev in self._as_list(getattr(frame, "evidence", None)):
            source = str(getattr(ev, "source", "") or self._mapping_get(ev, "source", "")).lower()
            if "user" in source or "chat" in source:
                ev_id = str(getattr(ev, "id", "") or self._mapping_get(ev, "id", "") or "")
                if ev_id:
                    ids.append(ev_id)

        frame_id = str(getattr(frame, "cycle_id", "") or getattr(frame, "frame_id", "") or "")
        if frame_id and not ids:
            ids.append(frame_id)

        return {
            "ids": self._dedupe(ids)[:8],
            "preview": [user_text.strip()[:180]] if user_text.strip() else [],
        }

    def _summarize_evidence_items(self, items: Sequence[Any], *, default_confidence: float) -> tuple[list[str], list[str], float]:
        ids: list[str] = []
        previews: list[str] = []
        confidences: list[float] = []

        for item in items:
            item_id = str(
                getattr(item, "id", "")
                or getattr(item, "evidence_id", "")
                or self._mapping_get(item, "id", "")
                or self._mapping_get(item, "evidence_id", "")
                or ""
            )
            if item_id:
                ids.append(item_id)

            preview = self._preview_item(item)
            if preview:
                previews.append(preview[:180])

            conf = self._read_float(item, "confidence")
            rel = self._read_float(item, "reliability")
            if conf is not None:
                confidences.append(conf)
            elif rel is not None:
                confidences.append(rel)

        confidence = sum(confidences) / len(confidences) if confidences else default_confidence
        return self._dedupe(ids)[:12], self._dedupe(previews)[:8], self._clamp01(confidence)

    def _preview_item(self, item: Any) -> str:
        if item is None:
            return ""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, Mapping):
            for key in ("claim", "content", "text", "summary", "title", "filename", "name"):
                value = item.get(key)
                if value:
                    return str(value).strip()
            return json.dumps(dict(item), ensure_ascii=False)[:180]
        for attr in ("claim", "content", "text", "summary", "title", "filename", "name"):
            value = getattr(item, attr, None)
            if value:
                return str(value).strip()
        return str(item).strip()

    def _extract_user_text_from_frame(self, frame: Any) -> str:
        texts: list[str] = []
        for percept in self._as_list(getattr(frame, "percepts", None)):
            kind = str(getattr(percept, "kind", "") or self._mapping_get(percept, "kind", "")).lower()
            content = str(getattr(percept, "content", "") or self._mapping_get(percept, "content", "") or "")
            if kind == "user_message" and content.strip():
                texts.append(content.strip())

        if texts:
            return "\n".join(texts[-3:])

        for attr in ("user_text", "input_text", "message", "raw_user_text"):
            value = getattr(frame, attr, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _mapping_get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, Mapping):
            return obj.get(key, default)
        return default

    @staticmethod
    def _read_float(obj: Any, key: str) -> float | None:
        if obj is None:
            return None
        if isinstance(obj, Mapping):
            value = obj.get(key)
        else:
            value = getattr(obj, key, None)
        try:
            return float(value)
        except Exception:
            return None

    @classmethod
    def _normalize(cls, text: str) -> str:
        text = str(text or "").strip().lower()
        try:
            repaired = text.encode("latin1").decode("utf-8")
            if repaired:
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        text = unicodedata.normalize("NFD", text)
        text = "".join(char for char in text if unicodedata.category(char) != "Mn")
        text = text.replace("đ", "d").replace("Đ", "D")
        text = re.sub(r"\s+", " ", text)
        return text

    @classmethod
    def _has_any(cls, normalized_text: str, markers: Sequence[str]) -> bool:
        if not normalized_text:
            return False
        return any(cls._normalize(marker) in normalized_text for marker in markers)

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return list(value)
        # Mapping là một item, không bung keys ra.
        if isinstance(value, Mapping):
            return [value]
        # String cũng là một item.
        if isinstance(value, str):
            return [value]
        try:
            return list(value)
        except Exception:
            return [value]

    @staticmethod
    def _dedupe(items: Iterable[Any]) -> list[Any]:
        seen: set[str] = set()
        result: list[Any] = []
        for item in items:
            key = str(item).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _safe_setattr(obj: Any, key: str, value: Any) -> None:
        if obj is None:
            return
        try:
            setattr(obj, key, value)
        except Exception:
            return

    @staticmethod
    def _clamp01(value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.0
