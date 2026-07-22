# -*- coding: utf-8 -*-
from __future__ import annotations

from core.cognition import CognitiveFrame, DiscourseProjection, SemanticProjection
from runtime.cognition.normalization import contains_phrase, normalize_vi


class SemanticCortex:
    def project(self, frame: CognitiveFrame, discourse: DiscourseProjection) -> SemanticProjection:
        text = normalize_vi(frame.user_text)
        evidence = ("turn:user_text",)
        if discourse.relation == "continue_assistant_move":
            return SemanticProjection(
                user_act="continuation_bid",
                task_goal="complete_previous_assistant_implication",
                literal_question=False,
                confidence=0.95,
                ambiguity=0.05,
                evidence_ids=discourse.evidence_ids,
            )
        if discourse.relation == "challenge_assistant_relevance":
            return SemanticProjection(
                user_act="challenge_relevance",
                task_goal="explain_why_previous_claim_matters",
                literal_question=True,
                confidence=0.90,
                ambiguity=0.10,
                evidence_ids=discourse.evidence_ids,
            )
        if discourse.relation == "style_feedback":
            return SemanticProjection(
                user_act="style_criticism",
                task_goal="replace_previous_response_with_better_one",
                confidence=0.92,
                ambiguity=0.08,
                evidence_ids=discourse.evidence_ids,
            )
        if discourse.relation.startswith("clarify_assistant"):
            return SemanticProjection(
                user_act="clarification_request",
                task_goal="explain_previous_assistant_wording_literally",
                literal_question=True,
                confidence=0.92,
                ambiguity=0.08,
                evidence_ids=discourse.evidence_ids,
            )
        if discourse.relation == "challenge_assistant_assumption":
            return SemanticProjection(
                user_act="correction_or_challenge",
                task_goal="check_and_repair_previous_assumption",
                literal_question=True,
                confidence=0.90,
                ambiguity=0.10,
                evidence_ids=discourse.evidence_ids,
            )
        if discourse.relation == "close_topic":
            return SemanticProjection(
                user_act="close_topic",
                task_goal="acknowledge_and_stop_pushing_topic",
                confidence=0.90,
                ambiguity=0.08,
                evidence_ids=discourse.evidence_ids,
            )
        if discourse.relation == "relational_bid":
            return SemanticProjection(
                user_act="closeness_bid",
                task_goal="meet_the_relational_bid_without_false_capability_claims",
                literal_question=False,
                confidence=0.90,
                ambiguity=0.10,
                evidence_ids=discourse.evidence_ids,
            )
        action_markers = (
            "mở file", "mo file", "sửa file", "sua file", "xóa file", "xoa file", "chạy test", "chay test",
            "gửi file", "gui file", "đọc repo", "doc repo", "kiểm tra repo", "kiem tra repo",
        )
        if contains_phrase(text, *action_markers):
            return SemanticProjection(
                user_act="action_request",
                task_goal="perform_requested_runtime_action",
                action_requested=True,
                confidence=0.88,
                ambiguity=0.12,
                evidence_ids=evidence,
            )
        if "?" in str(frame.user_text) or text.startswith(("sao ", "tai sao ", "vi sao ", "la gi ", "co ")):
            return SemanticProjection(
                user_act="question",
                task_goal="answer_current_question",
                literal_question=True,
                confidence=0.78,
                ambiguity=0.22,
                evidence_ids=evidence,
            )
        if contains_phrase(text, "xin chào", "xin chao", "hello", "chào eris", "chao eris"):
            return SemanticProjection(
                user_act="greeting",
                task_goal="respond_to_greeting_naturally",
                confidence=0.90,
                ambiguity=0.08,
                evidence_ids=evidence,
            )
        return SemanticProjection(
            user_act="statement_or_social_bid",
            task_goal="respond_to_current_turn_in_context",
            confidence=0.62,
            ambiguity=0.36,
            evidence_ids=evidence,
        )
