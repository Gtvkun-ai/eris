# -*- coding: utf-8 -*-
"""Typed claim-domain contract cho public wording của ERIS.

Surface/public writer được quyền sáng tạo *cách nói*, không được tự mở thêm một
miền sự thật. Module này cố ý không dò keyword kiểu "quạt", "trời", "phòng".
Model phải khai báo các claim nó vừa đưa vào câu; runtime chỉ kiểm domain +
provenance typed. Regex grounding cũ vẫn có thể tồn tại như backstop tương thích,
nhưng không còn là kiến trúc chính của V42.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

CLAIM_DOMAIN_VERSION = "eris.claim_domains.v42.typed_surface"

KNOWN_CLAIM_DOMAINS = frozenset({
    "internal_state",
    "conversation_history",
    "user_statement",
    "user_profile",
    "shared_episode",
    "memory",
    "verified_runtime_clock",
    "grounded_environment",
    "engagement_state",
    "discovery_artifact",
    "self_capability",
    "self_preference",
    "self_model",
    "self_history",
    "opinion",
    "hypothetical",
})

EVIDENCE_REQUIRED_DOMAINS = frozenset({
    # P0 integrity: current-world, historical conversation/memory and embodied
    # self-history claims must carry direct typed provenance.
    "verified_runtime_clock",
    "grounded_environment",
    # "you told me before..." and autobiographical physical habits are
    # historical claims, not decorative wording. They require a real ref.
    "conversation_history",
    "user_statement",
    "user_profile",
    "shared_episode",
    "memory",
    "self_model",
    "self_history",
})

# Domain không cần evidence — ý kiến, giả thuyết, trạng thái nội tâm và sở thích.
# Model được phép khai báo bất kỳ evidence_refs nào (hoặc không có); refs lạ không block.
EVIDENCE_EXEMPT_DOMAINS = frozenset({
    "opinion",
    "hypothetical",
    "internal_state",
    "self_preference",
})


def _compact(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def normalize_claim_manifest(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    output: list[dict[str, Any]] = []
    for raw in value[:10]:
        if not isinstance(raw, Mapping):
            continue
        domain = _compact(raw.get("domain", ""), 64).lower()
        claim = _compact(raw.get("claim", ""), 320)
        refs_raw = raw.get("evidence_refs", ())
        refs = tuple(
            _compact(item, 140)
            for item in (refs_raw if isinstance(refs_raw, Sequence) and not isinstance(refs_raw, (str, bytes, bytearray)) else ())
            if _compact(item, 140)
        )[:8]
        if not domain:
            continue
        output.append({"domain": domain, "claim": claim, "evidence_refs": refs})
    return tuple(output)


@dataclass(frozen=True, slots=True)
class ClaimDomainDecision:
    allowed: bool
    reason: str
    added_claim_count: int = 0
    violating_domains: tuple[str, ...] = ()
    unknown_evidence_refs: tuple[str, ...] = ()
    manifest_missing: bool = False


def validate_claim_manifest(
    manifest: Any,
    *,
    allowed_domains: Sequence[str],
    allowed_evidence_refs: Sequence[str] = (),
    text_present: bool = True,
) -> ClaimDomainDecision:
    """Validate domain/provenance, không parse prose.

    ``manifest_missing`` được báo riêng để legacy test/plugin có thể migrate dần.
    Production schema V42 yêu cầu field này, nên model bình thường không đi qua
    nhánh thiếu manifest.
    """

    normalized = normalize_claim_manifest(manifest)
    allowed = {str(item or "").strip().lower() for item in allowed_domains if str(item or "").strip()}
    evidence = {str(item or "").strip() for item in allowed_evidence_refs if str(item or "").strip()}
    missing = bool(text_present and manifest is None)
    # V42 public boundary: đã có chữ public thì manifest không còn là metadata
    # trang trí. Thiếu manifest nghĩa là runtime không biết model vừa mở thêm
    # miền sự thật nào, nên phải fail closed và cho wording retry một lần.
    if missing:
        return ClaimDomainDecision(False, "claim_manifest_missing", manifest_missing=True)
    bad_domains: list[str] = []
    bad_refs: list[str] = []
    for item in normalized:
        domain = str(item["domain"])
        if domain not in KNOWN_CLAIM_DOMAINS or domain not in allowed:
            bad_domains.append(domain)
            continue
        refs = tuple(str(ref) for ref in item.get("evidence_refs", ()) if str(ref))
        if domain in EVIDENCE_REQUIRED_DOMAINS:
            if not refs:
                bad_refs.append(f"{domain}:missing")
            else:
                bad_refs.extend(ref for ref in refs if ref not in evidence)
        elif domain in EVIDENCE_EXEMPT_DOMAINS:
            # Tán nhảm, triết học, ý kiến — không cần evidence và cũng không
            # phạt model vì khai báo thêm ref tùy ý. Bỏ qua hoàn toàn.
            pass
        else:
            # Domain khác (memory, engagement_state, discovery_artifact…):
            # nếu runtime có evidence set và model thêm ref lạ thì mới cảnh báo.
            bad_refs.extend(ref for ref in refs if evidence and ref not in evidence)
    if bad_domains:
        return ClaimDomainDecision(
            False,
            "claim_domain_not_allowed",
            len(normalized),
            tuple(dict.fromkeys(bad_domains)),
            tuple(dict.fromkeys(bad_refs)),
            missing,
        )
    if bad_refs:
        return ClaimDomainDecision(
            False,
            "claim_evidence_not_allowed",
            len(normalized),
            (),
            tuple(dict.fromkeys(bad_refs)),
            missing,
        )
    return ClaimDomainDecision(True, "claim_domains_grounded", len(normalized), manifest_missing=missing)


__all__ = [
    "CLAIM_DOMAIN_VERSION",
    "EVIDENCE_EXEMPT_DOMAINS",
    "EVIDENCE_REQUIRED_DOMAINS",
    "KNOWN_CLAIM_DOMAINS",
    "ClaimDomainDecision",
    "normalize_claim_manifest",
    "validate_claim_manifest",
]
