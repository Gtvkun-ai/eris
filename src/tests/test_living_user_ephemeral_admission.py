# -*- coding: utf-8 -*-
import pytest
from memory.living_user.models import (
    ProfileRecord,
    UserMemoryScope,
    is_ephemeral_directive,
    is_invalid_response_rule,
)
from memory.living_user.extractor import UserProfileExtractor, ProfileExtractionConfig
from memory.living_user.curator import LivingUserMemoryCurator
from memory.memory_admission import MemoryAdmissionPolicy


def test_is_ephemeral_directive_detection():
    # Turn and pacing constraints
    assert is_ephemeral_directive("trong 5 lượt tới. ko nhắn dồn. 5 lượt tới hãy nói kể về 5 chủ đề triết học đi. ok nha")
    assert is_ephemeral_directive("nói từ từ vài lượt đi cho tôi dễ hiểu")
    assert is_ephemeral_directive("chia nội dung thành nhiều lượt; mỗi lượt trình bày một tầng, không dồn tất cả vào một lượt")
    assert is_ephemeral_directive("Khi được yêu cầu đếm/liệt kê theo lượt, chia mỗi lượt một mục; không dồn tất cả vào một lượt.")
    assert is_ephemeral_directive("bạn tổng kết cuộc trò chuyện này bằng dẫn chứng 1 câu nói hay đi")

    # One-off speech / recitation commands
    assert is_ephemeral_directive("nói 'Thứ duy nhất mà toàn nhân loại đều bình đẳng... là cái chết' chỉ nói vậy thôi")
    assert is_ephemeral_directive("nói câu ' cái chết là bình đẳng đi'")
    assert is_ephemeral_directive("bạn nói câu này: ' Thứ duy nhất mà toàn nhân loại đều bình đẳng... là cái chết'")
    assert is_ephemeral_directive("Khi người dùng yêu cầu nói câu 'Thứ duy nhất...', chỉ nói đúng câu đó, không thêm bình luận.")
    assert is_ephemeral_directive("Khi người dùng yêu cầu đọc dõng dạc một câu/trích dẫn cụ thể, đọc đúng nguyên văn câu đó, không thêm bình luận trừ khi được hỏi.")

    # Durable rules must NOT be flagged as ephemeral
    assert not is_ephemeral_directive("từ giờ hãy trả lời ngắn gọn")
    assert not is_ephemeral_directive("không nói máy móc")
    assert not is_ephemeral_directive("Khi người dùng nói không hiểu, giải thích lại rõ ràng, đơn giản, từng bước; tránh mặc định người dùng đã hiểu.")
    assert not is_ephemeral_directive("Khi ERIS không thấy/không hiểu/không chắc hoặc bị lỗi, nói rõ giới hạn đó cho người dùng biết thay vì đoán mò; người dùng muốn biết để sửa ERIS ở lần sau.")


def test_is_invalid_response_rule():
    # Casual questions and gameplay leaks in response_rules
    assert is_invalid_response_rule("communication.response_rules", "Có 100 tù nhân, mỗi người bị nhốt trong một phòng riêng biệt. Luật chơi...")
    assert is_invalid_response_rule("communication.response_rules", "rồi rồi xin lỗi, ko vô dụng nữa. mà sao vùng unova route 12 farm con ngựa mà lúc ra con khác vậy")
    assert is_invalid_response_rule("communication.response_rules", "em nghĩ mình có khả năng nói chuyện, tư duy ntn hay ko")
    assert is_invalid_response_rule("communication.response_rules", "ô. ko có gì nói thì tôi mở bạn lên bạn phải kiếm gì nói với tôi chứ. ALO")

    # Non-response-rules paths should not be blocked for gaming/learning topics
    assert not is_invalid_response_rule("interests.games.pokemmo", "route 12 farm con ngựa")
    assert not is_invalid_response_rule("learning.active_topics", "câu đố 100 tù nhân")

    # Valid response rule
    assert not is_invalid_response_rule("communication.response_rules", "trả lời ngắn gọn, thẳng vào trọng tâm")


def test_memory_admission_policy_blocks_ephemeral_directives():
    policy = MemoryAdmissionPolicy()

    ephemeral_record = ProfileRecord(
        id="upr_test_1",
        path="communication.response_rules",
        value="Khi người dùng yêu cầu nói câu 'X', chỉ nói đúng câu đó, không thêm bình luận.",
        confidence=0.95,
        explicitness="explicit",
        sensitivity="normal",
        scope=UserMemoryScope(),
        cardinality="multi",
        status="active",
        evidence_ids=("turn_1",),
        recurrence=1,
        source="profile_model",
        valid_from=0.0,
        valid_until=None,
        expires_at=None,
    )
    decision = policy.decide_profile_record(ephemeral_record)
    assert not decision.admitted
    assert decision.reason == "ephemeral_turn_directive"

    valid_record = ProfileRecord(
        id="upr_test_2",
        path="communication.response_rules",
        value="Khi người dùng nói không hiểu, giải thích lại rõ ràng, đơn giản, từng bước.",
        confidence=0.90,
        explicitness="explicit",
        sensitivity="normal",
        scope=UserMemoryScope(),
        cardinality="multi",
        status="active",
        evidence_ids=("turn_1",),
        recurrence=1,
        source="profile_model",
        valid_from=0.0,
        valid_until=None,
        expires_at=None,
    )
    valid_decision = policy.decide_profile_record(valid_record)
    assert valid_decision.admitted


def test_extractor_rejects_ephemeral_directives():
    extractor = UserProfileExtractor(config=ProfileExtractionConfig())

    # Turn constraint prompt
    ops1 = extractor.from_turn(
        "trong 5 lượt tới. ko nhắn dồn. 5 lượt tới hãy nói kể về 5 chủ đề triết học đi. ok nha",
        evidence_ids=["turn_1"],
    )
    rule_ops1 = [op for op in ops1 if op.path == "communication.response_rules"]
    assert len(rule_ops1) == 0

    # One-off recitation prompt
    ops2 = extractor.from_turn(
        "nói 'Thứ duy nhất mà toàn nhân loại đều bình đẳng... là cái chết' chỉ nói vậy thôi",
        evidence_ids=["turn_2"],
    )
    rule_ops2 = [op for op in ops2 if op.path == "communication.response_rules"]
    assert len(rule_ops2) == 0

    # Valid durable preference
    ops3 = extractor.from_turn(
        "từ giờ hãy trả lời ngắn gọn thôi",
        evidence_ids=["turn_3"],
    )
    rule_ops3 = [op for op in ops3 if op.path == "communication.response_rules"]
    assert len(rule_ops3) == 1
    assert "ngắn gọn" in rule_ops3[0].value
