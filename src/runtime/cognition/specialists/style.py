# -*- coding: utf-8 -*-
from __future__ import annotations

from core.cognition import (
    CognitiveFrame,
    DiscourseProjection,
    SemanticProjection,
    SocialProjection,
    StyleProjection,
)


class StyleCortex:
    """Fe V2 thu gọn: chỉ xuất lực delivery, không viết prompt nhân cách dài."""

    def project(
        self,
        frame: CognitiveFrame,
        discourse: DiscourseProjection,
        semantic: SemanticProjection,
        social: SocialProjection,
    ) -> StyleProjection:
        refs = tuple(dict.fromkeys((*discourse.evidence_ids, *social.evidence_ids)))
        if discourse.relation == "continue_assistant_move":
            return StyleProjection(
                delivery="dry_soft_follow_through",
                distance="near_guarded",
                warmth_visibility="subtle",
                edge="dry_soft",
                pacing="brief_follow_through",
                avoid_moves=(
                    "broad_clarification",
                    "blame_user_for_ambiguity",
                    "explain_conversation_mechanics",
                    "support_bot_tone",
                ),
                confidence=0.90,
                evidence_ids=refs,
            )
        if social.repair_pressure >= 0.65:
            return StyleProjection(
                delivery="direct_grounded_repair",
                distance="near_responsible",
                warmth_visibility="restrained",
                edge="clean_not_defensive",
                pacing="name_miss_then_replace",
                avoid_moves=(
                    "ask_user_to_repeat_feedback",
                    "generic_apology",
                    "defend_previous_wording",
                    "support_bot_tone",
                ),
                confidence=0.90,
                evidence_ids=refs,
            )
        if discourse.relation.startswith("clarify_assistant"):
            return StyleProjection(
                delivery="literal_first_then_personality",
                distance="calm_near",
                warmth_visibility="low",
                edge="precise",
                pacing="one_direct_sentence_then_optional_color",
                avoid_moves=("invent_new_premise", "reverse_subjects", "poetic_evasion"),
                confidence=0.88,
                evidence_ids=refs,
            )
        if discourse.relation == "close_topic":
            return StyleProjection(
                delivery="brief_acknowledgement",
                distance="respectful",
                warmth_visibility="subtle",
                edge="none",
                pacing="stop_cleanly",
                avoid_moves=("reopen_topic", "ask_followup", "guilt_user"),
                confidence=0.88,
                evidence_ids=refs,
            )
        if semantic.user_act == "greeting":
            return StyleProjection(
                delivery="quiet_present",
                distance="guarded_open",
                warmth_visibility="subtle",
                edge="dry_soft",
                pacing="short_natural",
                avoid_moves=("grandiose_opening", "support_bot_greeting", "unsupported_assumption"),
                confidence=0.82,
                evidence_ids=refs,
            )
        return StyleProjection(
            delivery="calm_direct_with_room_for_edge",
            distance="guarded_neutral",
            warmth_visibility="contextual",
            edge="dry_optional",
            pacing="compact",
            avoid_moves=("support_bot_tone", "overread_user", "generic_offer_closer"),
            confidence=0.68,
            evidence_ids=refs,
        )
