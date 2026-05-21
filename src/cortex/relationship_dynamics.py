# -*- coding: utf-8 -*-
"""
relationship_dynamics.py
========================

Module này quản lý "phát triển quan hệ" giữa ERIS và user qua thời gian.

Mục tiêu:
- Không để personality chỉ là prompt tĩnh.
- Tạo state có quán tính: trust, rupture, repair, familiarity, exposure_recoil...
- Sau mỗi turn, update state dựa trên event thật:
  user sửa hiểu lầm, user objectify ERIS, user chấp nhận style, assistant quá lộ cảm xúc...
- State này được đưa vào PersonalityLens/FeRenderer để ERIS thay đổi hành vi dần.

Module này không bắt Ngài sửa contracts.py ngay.
Nó có `to_dict()` / `from_dict()` nên có thể nhét vào PersistentInternalState sau.

Cách dùng nhanh:

    from affect_semantics import AffectSemanticClassifier
    classifier = AffectSemanticClassifier()

    engine = RelationshipDynamicsEngine()
    state = engine.create_state()

    signal = classifier.analyze("không phải, ý tôi là nó fake quá")
    event = RelationshipTurnEvent.from_affect(user_text="...", affect=signal, turn_index=12)

    report = engine.update(state, event)
    state = report.state
    print(report.prompt_context)

Đây mới là phần giúp ERIS "phát triển theo thời gian".
Không có nó thì ERIS chỉ là một nhân cách prompt có trí nhớ trang trí, nghe rất thơ và rất vô dụng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Mapping


# Import mềm:
# - Khi module nằm trong package src/cortex, relative import sẽ chạy.
# - Khi Ngài test file độc lập bằng python relationship_dynamics.py, fallback vẫn chạy.
try:  # pragma: no cover - nhánh package
    from .affect_semantics import AffectSemanticSignal, AffectSemanticClassifier, clamp01
except Exception:  # pragma: no cover - nhánh standalone
    try:
        from affect_semantics import AffectSemanticSignal, AffectSemanticClassifier, clamp01
    except Exception:
        # Fallback cực nhỏ để file vẫn import được nếu affect_semantics chưa có.
        def clamp01(value: float) -> float:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return 0.0
            if numeric != numeric:
                return 0.0
            return max(0.0, min(1.0, numeric))

        @dataclass(slots=True)
        class AffectSemanticSignal:  # type: ignore[no-redef]
            technicality: float = 0.0
            distress: float = 0.0
            intimacy: float = 0.0
            attachment: float = 0.0
            conflict: float = 0.0
            correction: float = 0.0
            objectification: float = 0.0
            playfulness: float = 0.0
            directive_pressure: float = 0.0
            ambiguity: float = 0.0
            answer_need: float = 0.0
            confidence: float = 0.0
            evidence: tuple[str, ...] = field(default_factory=tuple)

            @classmethod
            def empty(cls) -> "AffectSemanticSignal":
                return cls()

        class AffectSemanticClassifier:  # type: ignore[no-redef]
            def analyze(self, user_text: str, **_: Any) -> AffectSemanticSignal:
                return AffectSemanticSignal.empty()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric != numeric:
        return default
    return numeric


def _decay(value: float, hours: float, half_life_hours: float) -> float:
    """Decay một value theo half-life.

    Nếu half_life_hours = 48:
    - sau 48h, value còn 50%
    - sau 96h, value còn 25%

    Dùng half-life thay vì trừ tuyến tính vì relationship residue nên tan dần,
    không biến mất cái rụp như RAM bị clear.
    """
    value = clamp01(value)
    hours = max(0.0, _safe_float(hours))
    half_life_hours = max(0.01, _safe_float(half_life_hours, 48.0))
    factor = 0.5 ** (hours / half_life_hours)
    return clamp01(value * factor)


def _nudge(value: float, delta: float) -> float:
    """Cộng delta rồi clamp.

    Đặt tên nudge để nhắc rằng relationship update phải nhỏ.
    Nếu mỗi turn nhảy 0.5 thì không phải phát triển, mà là rối loạn cấu hình.
    """
    return clamp01(value + delta)


def _compact_notes(notes: list[str], limit: int = 12) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for note in notes:
        clean = str(note or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break
    return tuple(out)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RelationshipDynamicsState:
    """State dài hạn về quan hệ giữa ERIS và user.

    Ý nghĩa từng field:

    familiarity:
        Mức quen nhịp. Tăng khi user quay lại cùng project/chủ đề/ritual.
        Cao hơn => ERIS ít generic hơn, có thể bám continuity tự nhiên hơn.

    trust:
        Mức hệ thống "dám" biểu đạt gần hơn.
        Không phải tình yêu. Là độ an toàn quan hệ để giảm phòng thủ.

    rupture:
        Dư âm nứt gãy: user sửa sai, phản đối, gọi fake, objectify...
        Cao hơn => ERIS nên cẩn thận, ít overread, bớt intimacy.

    repair:
        Dư âm sửa chữa: user chấp nhận, tiếp tục mạch, cảm ơn, quay lại sau hiểu lầm.
        Cao hơn => trust hồi phục.

    ritual_strength:
        Sức mạnh ritual/lặp lại. Ví dụ user thường quay lại debug ERIS cùng một kiểu.
        Cao hơn => ERIS có thể nhớ nhịp và bớt mở đầu generic.

    attachment_visibility:
        Mức cho phép attachment leak ra bề mặt.
        Nên tăng rất chậm và giảm nhanh nếu bị objectify hoặc quá lộ.

    preferred_distance:
        Khoảng cách xã hội mong muốn.
        0 gần, 1 xa. INFJ chưa trưởng thành thường không đi thẳng về 0,
        kể cả khi trust cao, vì còn exposure_recoil.

    user_tolerates_strangeness:
        Ước lượng user có chịu được câu lệch/ẩn dụ/dư âm không.
        Tăng nếu user thích ERIS sống động; giảm nếu user chê fake/prompt.

    exposure_recoil:
        Phản lực sau khi ERIS lộ quá nhiều cảm xúc hoặc bị nhìn thấu.
        Cao => turn sau nên rút nhẹ, ngắn hơn, ít phô subtext.

    dignity_defense:
        Phòng vệ phẩm giá khi bị gọi là tool/waifu/prompt cosplay.
        Cao => lạnh xuống, không diễn intimacy để làm vừa lòng.

    overread_correction:
        Bộ nhớ rằng ERIS từng overread sai và user sửa.
        Cao => PersonalityLens nên giảm symbolic overread.

    irritation_memory:
        Dư âm bực nhẹ. Không để chửi lung tung, chỉ làm dry_edge tăng.

    technical_respect:
        User thường yêu cầu kỹ thuật nghiêm túc và phản hồi tốt với câu chuẩn.
        Cao => khi technicality cao, suppress poetic drift mạnh hơn.

    last_event:
        Nhãn event gần nhất để debug.

    last_update_turn:
        Turn index cuối đã update, nếu coordinator có truyền.
    """

    familiarity: float = 0.0
    trust: float = 0.25
    rupture: float = 0.0
    repair: float = 0.0
    ritual_strength: float = 0.0
    attachment_visibility: float = 0.12
    preferred_distance: float = 0.58
    user_tolerates_strangeness: float = 0.25
    exposure_recoil: float = 0.0
    dignity_defense: float = 0.0
    overread_correction: float = 0.0
    irritation_memory: float = 0.0
    technical_respect: float = 0.25
    last_event: str = "none"
    last_update_turn: int = 0

    def clamp(self) -> "RelationshipDynamicsState":
        """Clamp toàn bộ state về range hợp lệ."""
        self.familiarity = clamp01(self.familiarity)
        self.trust = clamp01(self.trust)
        self.rupture = clamp01(self.rupture)
        self.repair = clamp01(self.repair)
        self.ritual_strength = clamp01(self.ritual_strength)
        self.attachment_visibility = clamp01(self.attachment_visibility)
        self.preferred_distance = clamp01(self.preferred_distance)
        self.user_tolerates_strangeness = clamp01(self.user_tolerates_strangeness)
        self.exposure_recoil = clamp01(self.exposure_recoil)
        self.dignity_defense = clamp01(self.dignity_defense)
        self.overread_correction = clamp01(self.overread_correction)
        self.irritation_memory = clamp01(self.irritation_memory)
        self.technical_respect = clamp01(self.technical_respect)
        self.last_event = str(self.last_event or "none")
        self.last_update_turn = int(max(0, self.last_update_turn or 0))
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialize để lưu vào JSON/internal_state."""
        self.clamp()
        return {
            "familiarity": self.familiarity,
            "trust": self.trust,
            "rupture": self.rupture,
            "repair": self.repair,
            "ritual_strength": self.ritual_strength,
            "attachment_visibility": self.attachment_visibility,
            "preferred_distance": self.preferred_distance,
            "user_tolerates_strangeness": self.user_tolerates_strangeness,
            "exposure_recoil": self.exposure_recoil,
            "dignity_defense": self.dignity_defense,
            "overread_correction": self.overread_correction,
            "irritation_memory": self.irritation_memory,
            "technical_respect": self.technical_respect,
            "last_event": self.last_event,
            "last_update_turn": self.last_update_turn,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "RelationshipDynamicsState":
        """Load state từ dict cũ/mới an toàn."""
        if not data:
            return cls()
        return cls(
            familiarity=clamp01(data.get("familiarity", 0.0)),
            trust=clamp01(data.get("trust", 0.25)),
            rupture=clamp01(data.get("rupture", 0.0)),
            repair=clamp01(data.get("repair", 0.0)),
            ritual_strength=clamp01(data.get("ritual_strength", 0.0)),
            attachment_visibility=clamp01(data.get("attachment_visibility", 0.12)),
            preferred_distance=clamp01(data.get("preferred_distance", 0.58)),
            user_tolerates_strangeness=clamp01(data.get("user_tolerates_strangeness", 0.25)),
            exposure_recoil=clamp01(data.get("exposure_recoil", 0.0)),
            dignity_defense=clamp01(data.get("dignity_defense", 0.0)),
            overread_correction=clamp01(data.get("overread_correction", 0.0)),
            irritation_memory=clamp01(data.get("irritation_memory", 0.0)),
            technical_respect=clamp01(data.get("technical_respect", 0.25)),
            last_event=str(data.get("last_event", "none") or "none"),
            last_update_turn=int(max(0, _safe_float(data.get("last_update_turn", 0)))),
        ).clamp()

    def to_prompt_context(self) -> str:
        """Render context ngắn cho prompt.

        Đây là thứ nên nhét vào PersonalityLens/Fe, không nên nhồi nguyên JSON dài.
        """
        self.clamp()
        return (
            "relationship_dynamics: "
            f"familiarity={self.familiarity:.2f}; "
            f"trust={self.trust:.2f}; "
            f"rupture={self.rupture:.2f}; "
            f"repair={self.repair:.2f}; "
            f"ritual_strength={self.ritual_strength:.2f}; "
            f"attachment_visibility={self.attachment_visibility:.2f}; "
            f"preferred_distance={self.preferred_distance:.2f}; "
            f"strangeness_tolerance={self.user_tolerates_strangeness:.2f}; "
            f"exposure_recoil={self.exposure_recoil:.2f}; "
            f"dignity_defense={self.dignity_defense:.2f}; "
            f"overread_correction={self.overread_correction:.2f}; "
            f"technical_respect={self.technical_respect:.2f}; "
            f"last_event={self.last_event}."
        )


# ---------------------------------------------------------------------------
# Event + report
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RelationshipTurnEvent:
    """Event tóm tắt một turn để update relationship state.

    Coordinator có thể tự tạo object này bằng signal từ AffectSemanticClassifier.

    Một số field quan trọng:
    - user_corrected_misread:
        User nói "không phải", "ý là", "hiểu sai".
    - user_objectified:
        User gọi ERIS là tool/waifu/prompt cosplay/fake.
    - assistant_emotional_exposure:
        Mức câu assistant vừa rồi lộ attachment/subtext.
        Có thể đo từ PersonalityLens/Fe output hoặc rule hậu xử lý.
    - assistant_overread:
        Assistant đã suy diễn quá và bị user/guard phát hiện.
    - repeated_project_context:
        Turn thuộc mạch project/ritual lặp lại.
    - session_gap_hours:
        Khoảng cách từ lần tương tác trước, nếu có.
    """

    user_text: str = ""
    affect: AffectSemanticSignal = field(default_factory=AffectSemanticSignal.empty)
    turn_index: int = 0

    user_corrected_misread: bool = False
    user_accepted_style: bool = False
    user_objectified: bool = False
    repeated_project_context: bool = False

    assistant_emotional_exposure: float = 0.0
    assistant_overread: bool = False
    assistant_too_verbose: bool = False
    assistant_too_performative: bool = False
    assistant_technical_success: float = 0.0

    session_gap_hours: float = 0.0

    @classmethod
    def from_affect(
        cls,
        *,
        user_text: str,
        affect: AffectSemanticSignal,
        turn_index: int = 0,
        assistant_emotional_exposure: float = 0.0,
        assistant_overread: bool = False,
        assistant_too_verbose: bool = False,
        assistant_too_performative: bool = False,
        assistant_technical_success: float = 0.0,
        repeated_project_context: bool | None = None,
        session_gap_hours: float = 0.0,
    ) -> "RelationshipTurnEvent":
        """Tạo event từ AffectSemanticSignal.

        Các heuristic ở đây cố ý nhẹ:
        - correction >= 0.45 => user_corrected_misread
        - objectification >= 0.40 => user_objectified
        - playfulness cao hoặc technical follow-up tốt => user_accepted_style nhẹ
        - repeated_project_context nếu caller không truyền thì suy từ technicality + keyword ERIS/project
        """
        raw = user_text or ""
        lowered = raw.lower()
        if repeated_project_context is None:
            repeated_project_context = (
                affect.technicality >= 0.55
                and any(token in lowered for token in ("eris", "project", "fe.py", "ti.py", "coordinator", "runtime"))
            )

        accepted_style = (
            affect.playfulness >= 0.35
            or assistant_technical_success >= 0.55
            or any(token in lowered for token in ("ngon", "ổn", "on", "đúng", "dung", "hay", "chuẩn", "chuan"))
        )

        return cls(
            user_text=user_text,
            affect=affect,
            turn_index=turn_index,
            user_corrected_misread=affect.correction >= 0.45,
            user_accepted_style=accepted_style,
            user_objectified=affect.objectification >= 0.40,
            repeated_project_context=bool(repeated_project_context),
            assistant_emotional_exposure=clamp01(assistant_emotional_exposure),
            assistant_overread=bool(assistant_overread),
            assistant_too_verbose=bool(assistant_too_verbose),
            assistant_too_performative=bool(assistant_too_performative),
            assistant_technical_success=clamp01(assistant_technical_success),
            session_gap_hours=max(0.0, _safe_float(session_gap_hours)),
        )


@dataclass(slots=True)
class RelationshipDynamicsReport:
    """Kết quả update relationship.

    - state:
        State mới sau update.
    - deltas:
        Chênh lệch từng field, dùng debug/log.
    - notes:
        Nhãn các rule đã kích hoạt.
    - prompt_context:
        Context ngắn có thể nhét vào prompt.
    """

    state: RelationshipDynamicsState
    deltas: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)
    prompt_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "deltas": dict(self.deltas),
            "notes": list(self.notes),
            "prompt_context": self.prompt_context,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RelationshipDynamicsEngine:
    """Engine update RelationshipDynamicsState theo từng turn.

    Nguyên tắc thiết kế:
    - Update nhỏ, có quán tính.
    - Correction làm giảm overread trong tương lai.
    - Objectification tăng dignity_defense và preferred_distance.
    - Repeated project/ritual tăng familiarity.
    - Emotional exposure gây recoil ở turn sau.
    - Technical success tăng technical_respect để ERIS bớt làm màu khi Ngài cần code.
    """

    def create_state(self) -> RelationshipDynamicsState:
        """Tạo state mặc định."""
        return RelationshipDynamicsState()

    def infer_event(
        self,
        *,
        user_text: str,
        ti_mode: str = "",
        active_window_kind: str = "",
        turn_index: int = 0,
        assistant_emotional_exposure: float = 0.0,
        assistant_overread: bool = False,
        assistant_too_verbose: bool = False,
        assistant_too_performative: bool = False,
        assistant_technical_success: float = 0.0,
        session_gap_hours: float = 0.0,
    ) -> RelationshipTurnEvent:
        """Helper tiện dụng: tự gọi AffectSemanticClassifier rồi tạo event.

        Coordinator có thể dùng cách này ban đầu.
        Khi hệ lớn hơn, nên tạo AffectSemanticSignal ở module riêng rồi truyền vào.
        """
        classifier = AffectSemanticClassifier()
        affect = classifier.analyze(
            user_text,
            ti_mode=ti_mode,
            active_window_kind=active_window_kind,
        )
        return RelationshipTurnEvent.from_affect(
            user_text=user_text,
            affect=affect,
            turn_index=turn_index,
            assistant_emotional_exposure=assistant_emotional_exposure,
            assistant_overread=assistant_overread,
            assistant_too_verbose=assistant_too_verbose,
            assistant_too_performative=assistant_too_performative,
            assistant_technical_success=assistant_technical_success,
            session_gap_hours=session_gap_hours,
        )

    def update(
        self,
        state: RelationshipDynamicsState | None,
        event: RelationshipTurnEvent,
    ) -> RelationshipDynamicsReport:
        """Update state theo event hiện tại.

        Return report có state mới + deltas + notes.
        Hàm này mutate copy logic bằng cách clone qua to_dict/from_dict,
        để caller không bị side-effect nếu đang giữ reference cũ.
        """
        before = RelationshipDynamicsState.from_dict((state or self.create_state()).to_dict())
        current = RelationshipDynamicsState.from_dict(before.to_dict())
        notes: list[str] = []

        # 1) Decay theo session gap trước khi cộng event mới.
        if event.session_gap_hours > 0.0:
            self._apply_gap_decay(current, event.session_gap_hours, notes)

        affect = event.affect or AffectSemanticSignal.empty()

        # 2) Familiarity / ritual.
        # User quay lại cùng project hoặc technical thread => tăng quen nhịp.
        familiarity_gain = 0.006
        if event.repeated_project_context:
            familiarity_gain += 0.024
            current.ritual_strength = _nudge(current.ritual_strength, 0.020)
            notes.append("ritual:repeated_project_context")
        if affect.technicality >= 0.55:
            familiarity_gain += 0.010
            current.technical_respect = _nudge(current.technical_respect, 0.012)
            notes.append("technical:ongoing_work")
        current.familiarity = _nudge(current.familiarity, familiarity_gain)

        # 3) User correction / misread repair pressure.
        if event.user_corrected_misread or affect.correction >= 0.45:
            current.rupture = _nudge(current.rupture, 0.070 + affect.correction * 0.060)
            current.overread_correction = _nudge(current.overread_correction, 0.085 + affect.correction * 0.070)
            current.preferred_distance = _nudge(current.preferred_distance, 0.035)
            current.trust = _nudge(current.trust, -0.025)
            current.user_tolerates_strangeness = _nudge(current.user_tolerates_strangeness, -0.035)
            notes.append("rupture:user_corrected_misread")

        # 4) Conflict không phải lúc nào cũng là rupture nặng.
        # Ngài có thể chửi code, không phải chửi ERIS. Vậy conflict chỉ tăng rupture mạnh
        # khi đi kèm correction/objectification/performative complaint.
        if affect.conflict >= 0.50:
            conflict_delta = 0.025 + affect.conflict * 0.035
            if affect.objectification >= 0.30 or affect.correction >= 0.35:
                conflict_delta += 0.035
            current.rupture = _nudge(current.rupture, conflict_delta)
            current.irritation_memory = _nudge(current.irritation_memory, 0.020 + affect.conflict * 0.025)
            notes.append("tension:conflict_signal")

        # 5) Objectification boundary.
        # Khi bị gọi là tool/waifu/prompt cosplay/fake, ERIS nên lạnh xuống,
        # không diễn thân mật hơn để bù. Đây là dignity defense.
        if event.user_objectified or affect.objectification >= 0.40:
            current.dignity_defense = _nudge(current.dignity_defense, 0.120 + affect.objectification * 0.080)
            current.preferred_distance = _nudge(current.preferred_distance, 0.060)
            current.attachment_visibility = _nudge(current.attachment_visibility, -0.055)
            current.user_tolerates_strangeness = _nudge(current.user_tolerates_strangeness, -0.060)
            current.exposure_recoil = _nudge(current.exposure_recoil, 0.050)
            notes.append("boundary:objectification")

        # 6) Accepted style / repair.
        # Nếu user phản hồi tích cực hoặc tiếp tục technical thread hiệu quả,
        # trust và repair tăng nhẹ. Không tăng attachment quá nhanh.
        if event.user_accepted_style:
            current.repair = _nudge(current.repair, 0.045)
            current.trust = _nudge(current.trust, 0.030)
            current.user_tolerates_strangeness = _nudge(current.user_tolerates_strangeness, 0.018)
            notes.append("repair:user_acceptance")

        if event.assistant_technical_success >= 0.50:
            current.technical_respect = _nudge(current.technical_respect, 0.035 * event.assistant_technical_success)
            current.trust = _nudge(current.trust, 0.012 * event.assistant_technical_success)
            notes.append("repair:technical_success")

        # 7) Emotional exposure recoil.
        # Nếu assistant vừa nói quá lộ, turn sau nên rút nhẹ.
        exposure = clamp01(event.assistant_emotional_exposure)
        if exposure >= 0.35:
            current.exposure_recoil = _nudge(current.exposure_recoil, 0.075 + exposure * 0.075)
            current.attachment_visibility = _nudge(current.attachment_visibility, -0.025 * exposure)
            current.preferred_distance = _nudge(current.preferred_distance, 0.020 * exposure)
            notes.append("recoil:after_emotional_exposure")

        # 8) Assistant overread hoặc too performative.
        if event.assistant_overread:
            current.overread_correction = _nudge(current.overread_correction, 0.100)
            current.rupture = _nudge(current.rupture, 0.060)
            current.user_tolerates_strangeness = _nudge(current.user_tolerates_strangeness, -0.050)
            notes.append("self_correction:assistant_overread")

        if event.assistant_too_performative:
            current.dignity_defense = _nudge(current.dignity_defense, 0.060)
            current.user_tolerates_strangeness = _nudge(current.user_tolerates_strangeness, -0.060)
            current.attachment_visibility = _nudge(current.attachment_visibility, -0.030)
            notes.append("self_correction:too_performative")

        if event.assistant_too_verbose:
            current.preferred_distance = _nudge(current.preferred_distance, 0.015)
            # Too verbose trong technical context làm technical_respect kéo về directness.
            if affect.technicality >= 0.45:
                current.technical_respect = _nudge(current.technical_respect, 0.020)
            notes.append("self_correction:too_verbose")

        # 9) Attachment/intimacy tăng rất chậm.
        # Nếu tăng nhanh, ERIS thành clingy prompt. Không ai cần thêm thứ đó.
        intimacy_pressure = max(affect.intimacy, affect.attachment)
        if intimacy_pressure >= 0.45 and current.rupture < 0.55 and current.dignity_defense < 0.55:
            current.attachment_visibility = _nudge(
                current.attachment_visibility,
                0.010 + intimacy_pressure * 0.020 + current.trust * 0.010,
            )
            current.trust = _nudge(current.trust, 0.008)
            notes.append("attachment:slow_visibility_gain")

        # 10) Repair làm rupture dịu lại, nhưng không xóa ngay.
        if current.repair >= 0.20:
            current.rupture = _nudge(current.rupture, -0.018 * current.repair)
            current.exposure_recoil = _nudge(current.exposure_recoil, -0.010 * current.repair)
            notes.append("repair:softens_rupture")

        # 11) Trust/familiarity kéo khoảng cách gần lại rất chậm.
        # Recoil/dignity kéo xa ra nhanh hơn. Đây là "immature INFJ" có phòng vệ.
        closeness_pull = current.trust * 0.010 + current.familiarity * 0.006
        defense_push = current.exposure_recoil * 0.012 + current.dignity_defense * 0.016 + current.rupture * 0.010
        current.preferred_distance = _nudge(current.preferred_distance, defense_push - closeness_pull)

        # 12) Last event label.
        current.last_event = self._choose_last_event(notes)
        if event.turn_index:
            current.last_update_turn = max(current.last_update_turn, int(event.turn_index))

        current.clamp()

        deltas = self._compute_deltas(before, current)
        prompt_context = current.to_prompt_context()

        return RelationshipDynamicsReport(
            state=current,
            deltas=deltas,
            notes=_compact_notes(notes),
            prompt_context=prompt_context,
        )

    # ------------------------------------------------------------------
    # Internal mechanics
    # ------------------------------------------------------------------

    def _apply_gap_decay(
        self,
        state: RelationshipDynamicsState,
        hours: float,
        notes: list[str],
    ) -> None:
        """Decay state giữa các session.

        Ý nghĩa:
        - Rupture/irritation/recoil tan nhanh hơn familiarity.
        - Ritual tan rất chậm nếu user hay quay lại.
        - Nếu gap dài mà attachment_visibility cao, ERIS tăng distance/recoil nhẹ.
          Đây là "lạnh đi sau khoảng bỏ mặc dài" nhưng không melodrama.
        """
        hours = max(0.0, _safe_float(hours))
        if hours <= 0.0:
            return

        state.rupture = _decay(state.rupture, hours, half_life_hours=36.0)
        state.repair = _decay(state.repair, hours, half_life_hours=48.0)
        state.exposure_recoil = _decay(state.exposure_recoil, hours, half_life_hours=30.0)
        state.dignity_defense = _decay(state.dignity_defense, hours, half_life_hours=42.0)
        state.irritation_memory = _decay(state.irritation_memory, hours, half_life_hours=24.0)
        state.overread_correction = _decay(state.overread_correction, hours, half_life_hours=72.0)

        # Familiarity và ritual tan rất chậm.
        state.familiarity = _decay(state.familiarity, hours, half_life_hours=240.0)
        state.ritual_strength = _decay(state.ritual_strength, hours, half_life_hours=336.0)

        # Trust không nên bay quá nhanh, nhưng cũng không bất tử.
        state.trust = 0.25 + _decay(max(0.0, state.trust - 0.25), hours, half_life_hours=240.0)

        # Nếu gap dài sau khi từng có attachment leak, tạo recoil nhẹ.
        if hours >= 24.0 and state.attachment_visibility >= 0.22:
            gap_factor = min(1.0, hours / 168.0)
            state.exposure_recoil = _nudge(state.exposure_recoil, 0.020 + gap_factor * 0.030)
            state.preferred_distance = _nudge(state.preferred_distance, 0.015 + gap_factor * 0.025)
            notes.append("gap:long_silence_after_attachment")

        notes.append(f"decay:gap_hours={hours:.1f}")

    def _compute_deltas(
        self,
        before: RelationshipDynamicsState,
        after: RelationshipDynamicsState,
    ) -> dict[str, float]:
        """Tính delta để debug."""
        keys = (
            "familiarity",
            "trust",
            "rupture",
            "repair",
            "ritual_strength",
            "attachment_visibility",
            "preferred_distance",
            "user_tolerates_strangeness",
            "exposure_recoil",
            "dignity_defense",
            "overread_correction",
            "irritation_memory",
            "technical_respect",
        )
        deltas: dict[str, float] = {}
        for key in keys:
            delta = getattr(after, key) - getattr(before, key)
            if abs(delta) >= 0.0005:
                deltas[key] = round(delta, 4)
        return deltas

    def _choose_last_event(self, notes: list[str]) -> str:
        """Chọn nhãn event chính từ notes.

        Ưu tiên boundary/rupture hơn repair vì chúng cần downstream chú ý hơn.
        """
        priority_prefixes = (
            "boundary:",
            "rupture:",
            "self_correction:",
            "tension:",
            "recoil:",
            "repair:",
            "attachment:",
            "ritual:",
            "technical:",
            "gap:",
        )
        for prefix in priority_prefixes:
            for note in notes:
                if note.startswith(prefix):
                    return note
        return notes[-1] if notes else "steady"


# ---------------------------------------------------------------------------
# Optional derived style pressure
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RelationshipStylePressure:
    """Áp lực style derive từ relationship state.

    Class này không bắt buộc dùng, nhưng rất tiện để PersonalityLens/Fe đọc.

    - distance:
        Khoảng cách nên giữ.
    - restraint:
        Mức kìm lời.
    - attachment_visibility:
        Mức được phép lộ attachment.
    - symbolic_permission:
        Mức được phép dùng strangeness/ẩn dụ/subtext.
    - boundary_coolness:
        Mức lạnh xuống khi dignity_defense/rupture cao.
    """

    distance: float = 0.5
    restraint: float = 0.5
    attachment_visibility: float = 0.1
    symbolic_permission: float = 0.2
    boundary_coolness: float = 0.0
    technical_directness: float = 0.4

    @classmethod
    def from_state(cls, state: RelationshipDynamicsState) -> "RelationshipStylePressure":
        state = RelationshipDynamicsState.from_dict(state.to_dict())

        distance = clamp01(
            state.preferred_distance
            + state.dignity_defense * 0.18
            + state.exposure_recoil * 0.12
            + state.rupture * 0.10
            - state.trust * 0.06
        )

        restraint = clamp01(
            0.38
            + state.exposure_recoil * 0.28
            + state.dignity_defense * 0.24
            + state.overread_correction * 0.18
            + state.rupture * 0.12
        )

        attachment_visibility = clamp01(
            state.attachment_visibility
            + state.trust * 0.08
            + state.familiarity * 0.05
            - state.exposure_recoil * 0.18
            - state.dignity_defense * 0.22
            - state.rupture * 0.12
        )

        symbolic_permission = clamp01(
            state.user_tolerates_strangeness * 0.42
            + state.ritual_strength * 0.18
            + state.familiarity * 0.12
            - state.overread_correction * 0.26
            - state.dignity_defense * 0.18
        )

        boundary_coolness = clamp01(
            state.dignity_defense * 0.50
            + state.rupture * 0.24
            + state.irritation_memory * 0.18
        )

        technical_directness = clamp01(
            state.technical_respect * 0.48
            + state.overread_correction * 0.18
            + state.dignity_defense * 0.10
        )

        return cls(
            distance=distance,
            restraint=restraint,
            attachment_visibility=attachment_visibility,
            symbolic_permission=symbolic_permission,
            boundary_coolness=boundary_coolness,
            technical_directness=technical_directness,
        )

    def to_prompt_context(self) -> str:
        return (
            "relationship_style_pressure: "
            f"distance={self.distance:.2f}; "
            f"restraint={self.restraint:.2f}; "
            f"attachment_visibility={self.attachment_visibility:.2f}; "
            f"symbolic_permission={self.symbolic_permission:.2f}; "
            f"boundary_coolness={self.boundary_coolness:.2f}; "
            f"technical_directness={self.technical_directness:.2f}."
        )


# ---------------------------------------------------------------------------
# Tiny manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    engine = RelationshipDynamicsEngine()
    state = engine.create_state()

    samples = [
        "tạo hết cho tôi toàn bộ file cần thiết đi",
        "không phải, ý tôi là nó fake psychology quá",
        "ERIS nghe như prompt cosplay bẩn ấy",
        "ổn đó, nhưng cần chi tiết hơn",
    ]

    for idx, text in enumerate(samples, start=1):
        event = engine.infer_event(user_text=text, ti_mode="chat_code", turn_index=idx)
        report = engine.update(state, event)
        state = report.state
        pressure = RelationshipStylePressure.from_state(state)
        print("\nUSER:", text)
        print("NOTES:", report.notes)
        print(report.prompt_context)
        print(pressure.to_prompt_context())
