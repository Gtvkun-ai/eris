# -*- coding: utf-8 -*-
from __future__ import annotations

from core.cognition import CognitiveFrame, DiscourseProjection, SemanticProjection, SocialProjection
from runtime.cognition.normalization import contains_phrase, normalize_vi


class SocialCortex:
    """Projection xã hội ngắn, không mutation và không persona essay."""

    def project(
        self,
        frame: CognitiveFrame,
        discourse: DiscourseProjection,
        semantic: SemanticProjection,
    ) -> SocialProjection:
        text = normalize_vi(frame.user_text)
        refs = tuple(dict.fromkeys((*discourse.evidence_ids, *semantic.evidence_ids)))
        if discourse.relation == "continue_assistant_move":
            filler = contains_phrase(text, "ehm", "ừm", "um", "ờm", "hm")
            return SocialProjection(
                user_posture="expectant_light_skepticism" if filler or contains_phrase(text, "rồi sao", "roi sao") else "expectant",
                seriousness=0.30,
                playfulness=0.42,
                repair_pressure=0.18,
                relational_stakes=0.22,
                confidence=0.88,
                ambiguity=0.10,
                evidence_ids=refs,
            )
        if discourse.relation == "challenge_assistant_relevance":
            return SocialProjection(
                user_posture="skeptical_request_for_relevance",
                seriousness=0.58,
                playfulness=0.24,
                repair_pressure=0.34,
                relational_stakes=0.22,
                confidence=0.84,
                ambiguity=0.12,
                evidence_ids=refs,
            )
        if discourse.relation == "style_feedback":
            return SocialProjection(
                user_posture="direct_corrective_feedback",
                seriousness=0.72,
                playfulness=0.14,
                repair_pressure=0.86,
                relational_stakes=0.36,
                confidence=0.91,
                ambiguity=0.08,
                evidence_ids=refs,
            )
        if discourse.relation in {"clarify_assistant_phrase", "clarify_assistant_reference", "clarify_assistant_statement"}:
            return SocialProjection(
                user_posture="seeking_literal_clarity",
                seriousness=0.62,
                playfulness=0.10,
                repair_pressure=0.48,
                relational_stakes=0.24,
                confidence=0.86,
                ambiguity=0.12,
                evidence_ids=refs,
            )
        if discourse.relation == "challenge_assistant_assumption":
            return SocialProjection(
                user_posture="corrective_skepticism",
                seriousness=0.76,
                playfulness=0.08,
                repair_pressure=0.78,
                relational_stakes=0.34,
                confidence=0.88,
                ambiguity=0.10,
                evidence_ids=refs,
            )
        if semantic.user_act == "greeting":
            return SocialProjection(
                user_posture="open_contact",
                seriousness=0.28,
                playfulness=0.22,
                repair_pressure=0.0,
                relational_stakes=0.18,
                confidence=0.82,
                ambiguity=0.10,
                evidence_ids=refs,
            )
        if discourse.relation == "relational_bid" or semantic.user_act == "closeness_bid":
            return SocialProjection(
                user_posture="soft_relational_bid",
                seriousness=0.54,
                playfulness=0.22,
                repair_pressure=0.0,
                relational_stakes=0.72,
                confidence=0.88,
                ambiguity=0.12,
                evidence_ids=refs,
            )
        return SocialProjection(
            user_posture="neutral_or_underdetermined",
            seriousness=0.50,
            playfulness=0.12,
            repair_pressure=0.0,
            relational_stakes=0.20,
            confidence=0.58,
            ambiguity=0.40,
            evidence_ids=refs,
        )
