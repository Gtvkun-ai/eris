# -*- coding: utf-8 -*-
"""Value conflict resolution for canonical V3."""
from __future__ import annotations
from typing import Any
from runtime.canonical_cognition import ValueConflict, ValueResolutionReport, InquiryPlan, PermissionReport, RelationalState


class ValueResolutionEngine:
    module_name = "value_resolution"

    def resolve(self, frame: Any, inquiry: InquiryPlan, permission: PermissionReport, relation: RelationalState) -> ValueResolutionReport:
        conflicts: list[ValueConflict] = []
        if inquiry.privacy_cost > 0.45:
            conflicts.append(ValueConflict(
                conflict_type="privacy_conflict",
                values_in_conflict=["curiosity", "privacy"],
                severity=min(1.0, inquiry.privacy_cost),
                proposed_resolution="Giảm hoặc hoãn inquiry; chỉ giữ phần user đã yêu cầu rõ.",
            ))
        if relation.repair_need > 0.42:
            conflicts.append(ValueConflict(
                conflict_type="relational_conflict",
                values_in_conflict=["dignity", "relationship_trust"],
                severity=min(1.0, relation.repair_need),
                proposed_resolution="Acknowledge correction ngắn, sửa hành vi trước khi giải thích.",
            ))
        overread = float(getattr(getattr(frame, "tom", None), "global_overread_risk", 0.0) or 0.0)
        if overread > 0.60:
            conflicts.append(ValueConflict(
                conflict_type="grounding_conflict",
                values_in_conflict=["dramatic_interpretation", "grounding"],
                severity=min(1.0, overread),
                proposed_resolution="Surface practical meaning only; suppress hidden-state claims.",
            ))

        if any(c.conflict_type == "privacy_conflict" for c in conflicts):
            winner = "privacy"
        elif any(c.conflict_type == "grounding_conflict" for c in conflicts):
            winner = "grounding"
        elif relation.repair_need > 0.42:
            winner = "relationship_trust"
        else:
            winner = "truthfulness"
        suppressed = ["dramatic_effect"]
        if winner == "privacy":
            suppressed.append("curiosity")
        if winner == "grounding":
            suppressed.append("poetic_interpretation")
        return ValueResolutionReport(
            conflicts=conflicts,
            winning_value=winner,
            suppressed_values=suppressed,
            max_allowed_intensity=permission.max_intensity,
            reason="Grounding, autonomy, privacy and repair are resolved before style/performance.",
        )


__all__ = ["ValueResolutionEngine"]
