# -*- coding: utf-8 -*-
"""Adapter from a root-owned move to the existing model surface writer."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Mapping, Sequence

from .contracts import ConversationEvent
from .delivery import SurfaceEnvelope
from .kernel import KernelTurn
from .writer import RenderedConversationMove


_SAFE_V03_ERROR = re.compile(r"^(?:v03_[a-z0-9_]+|public_writer_[a-z0-9_]+|[A-Z][A-Z0-9_]+)(?::[A-Z][A-Z0-9_,]*)?$")


def _v03_error_code(exc: Exception) -> str:
    """Chỉ trích mã lỗi cơ học để log/rewrite; không lộ prompt hoặc token API.

    Exception của provider đôi lúc mang nguyên response/request. Không bao giờ
    đưa chuỗi lạ ấy vào telemetry hoặc prompt sửa câu của SurfaceWorker.
    """
    raw = str(exc).strip()
    return raw[:180] if len(raw) <= 180 and _SAFE_V03_ERROR.fullmatch(raw) else type(exc).__name__


def _inspect_writer_manifest(payload: Mapping[str, Any], evidence_registry: Any) -> Any:
    """Gate typed-domain sơ bộ cho từng candidate, kể cả candidate rewrite.

    Không làm semantic verification (Task 5/6 của v0.3). Ref hiện diện chỉ là
    điều kiện cần, tuyệt đối chưa chứng minh toàn bộ nghĩa của câu.
    """
    from runtime.claim_domain_contract import (
        ClaimManifestEnvelope, inspect_claim_manifest, validate_claim_manifest,
    )
    from .claim_evidence import EvidenceRegistry
    envelope = payload.get("_typed_claim_manifest")
    if not isinstance(envelope, ClaimManifestEnvelope):
        # Fake router của những test V12 không có manifest là legacy, không
        # ngầm gán compliance mới. Router thật luôn trả _typed_claim_manifest.
        if "claim_manifest" not in payload:
            return None
        envelope = inspect_claim_manifest(payload)
    current = inspect_claim_manifest(payload)
    if envelope.structural_status != "valid":
        raise RuntimeError("public_writer_manifest_" + envelope.structural_status)
    if current.structural_status != "valid" or current.raw != envelope.raw:
        raise RuntimeError("public_writer_manifest_tampered")

    if isinstance(evidence_registry, EvidenceRegistry):
        # Allowlist thuộc quyền runtime, không lấy từ những ref writer tự khai.
        domains = {"opinion", "hypothetical", "internal_state", "self_preference"}
        refs: list[str] = []
        source_domains = {
            "runtime_state": ("self_model",),
            "user_statement": ("user_statement", "conversation_history"),
            "assistant_utterance": ("conversation_history",),
            "memory": ("memory", "user_profile", "shared_episode"),
            "current_screen": ("grounded_environment",),
            "live_vision": ("grounded_environment",),
            "pasted_code": ("discovery_artifact",),
            "uploaded_file": ("discovery_artifact",),
            "web": ("discovery_artifact",),
            "capability_result": ("discovery_artifact", "self_capability"),
        }
        for entry in evidence_registry.entries:
            if entry.status != "supported":
                continue
            refs.append(entry.ref)
            # assistant utterance KHÔNG chứng minh đã làm action; một ref chỉ
            # được xét trong domain/scope của chính nó, không nâng thành history.
            for domain in source_domains.get(entry.source_kind, ()):
                if (entry.source_kind == "memory" and entry.scope in {"summary", "unresolved"}
                        and domain in {"user_profile", "shared_episode"}):
                    continue
                domains.add(domain)
        decision = validate_claim_manifest(envelope,
                                           allowed_domains=tuple(domains),
                                           allowed_evidence_refs=tuple(refs))
        if not decision.allowed:
            raise RuntimeError("public_writer_" + decision.reason)
    return envelope


class RuntimeConversationWriter:
    def __init__(self, host: Any) -> None:
        self.host = host

    def _log_v03(self, level: str, *, turn: KernelTurn, attempt: int,
                 stage: str, status: str, code: str, duration_ms: int) -> None:
        """Log ranh giới từng candidate; không lưu câu user/speech hay evidence."""
        logger = getattr(self.host, 'logger', None)
        method = getattr(logger, level, None)
        if callable(method):
            try:
                method(
                    '[character-v03] writer_candidate run=%s generation=%s '
                    'attempt=%s/2 stage=%s status=%s code=%s duration_ms=%s',
                    turn.run_id, turn.generation, attempt, stage, status, code,
                    duration_ms,
                )
            except Exception:
                pass
        try:
            from runtime.observability import GLOBAL_OBSERVABILITY
            GLOBAL_OBSERVABILITY.log(
                'character_writer_candidate',
                tags={'stage': stage, 'status': status, 'code': code},
                fields={'run_id': turn.run_id, 'generation': turn.generation,
                        'attempt': attempt, 'duration_ms': duration_ms},
                status='ok' if status == 'pass' else 'degraded',
            )
        except Exception:
            # Telemetry không được làm hỏng conversation runtime.
            pass

    def _realize_v03(self, *, generate: Any, kwargs: dict[str, Any], turn: KernelTurn,
                     event: ConversationEvent, runtime_context: Mapping[str, Any],
                     evidence_registry: Any, move_payload: Mapping[str, Any]) -> RenderedConversationMove:
        """Task 6: một ngân sách duy nhất, tối đa 2 writer + 2 verifier.

        Root move/snapshot/registry GIỮ NGUYÊN khi retry; fail/unknown không có
        RenderedConversationMove để kernel giao cho delivery/observer.
        """
        from .delivery_adapter import RuntimeConversationDeliveryAdapter
        from .claim_verifier import CharacterClaimVerifier, build_verification_receipt
        from runtime.ai_orchestrated.model_router import _public_display_language_mismatch

        verifier = getattr(self.host, 'character_claim_verifier', None)
        if verifier is None:
            verifier = CharacterClaimVerifier(self.host.ai_model_router)
        adapter = RuntimeConversationDeliveryAdapter(self.host)
        base = dict(kwargs)
        base['allow_language_repair'] = False  # Router không còn retry ẩn của riêng nó.
        error = 'VERIFIER_UNAVAILABLE'
        rejected: list[str] = []
        for attempt in range(2):
            started_at = time.monotonic()
            stage = 'generate'
            request = dict(base)
            if attempt:
                request['retry_instruction'] = (
                    'CHARACTER_V03_REWRITE: ' + error + '. Viết lại CÙNG Root move, '
                    'không thêm sự kiện, hành động, lịch sử hay chủ đề. '
                    'Đưa đủ claim_manifest và hai surface cùng nghĩa, đúng ngôn ngữ.'
                )
                request['discourse_context'] = base['discourse_context'] + '\n' + request['retry_instruction']
            try:
                payload = generate(**request)
                stage = 'manifest'
                if not isinstance(payload, Mapping):
                    raise RuntimeError('v03_writer_invalid_payload')
                envelope = _inspect_writer_manifest(payload, evidence_registry)
                if envelope is None:
                    raise RuntimeError('MANIFEST_MISSING')
                stage = 'surfaces'
                display = str(payload.get('text', '') or '').strip()
                speech = str(payload.get('speech_text', '') or '').strip()
                if not display or not speech:
                    raise RuntimeError('v03_missing_public_surface')
                if _public_display_language_mismatch(display,
                        str(base.get('language_hint', 'vi') or 'vi')):
                    raise RuntimeError('v03_display_language_mismatch')
                # Chặn deterministic false action/sensor, cùng ngân sách rewrite.
                engine = runtime_context.get('__source_grounding_engine')
                report = runtime_context.get('__source_grounding_report')
                stage = 'grounding'
                if engine is not None and report is not None:
                    from runtime.grounding_surface_gate import evaluate_grounded_surface
                    for text in (display, speech):
                        verdict = evaluate_grounded_surface(
                            engine, text, report=report,
                            channel='chat' if event.kind == 'user_turn' else 'autonomous',
                        )
                        if not bool(getattr(verdict,'allowed',True)):
                            raise RuntimeError('v03_grounding_unsupported')
                stage = 'prepare'
                prepared = adapter.prepare_candidate(
                    turn=turn,event=event,payload=dict(payload),
                    source_fingerprint=evidence_registry.fingerprint,
                )
                stage = 'verify'
                result = verifier.verify(
                    prepared=prepared,manifest=envelope,move=turn.move,
                    registry=evidence_registry,
                    portrait=runtime_context.get('__character_portrait'),
                )
                if result.status != 'pass':
                    raise RuntimeError('v03_verify_' + result.status + ':' + ','.join(result.reason_codes))
                stage = 'receipt'
                receipt = build_verification_receipt(
                    prepared=prepared,result=result,registry=evidence_registry,
                    portrait=runtime_context.get('__character_portrait'),
                )
                self._log_v03('info', turn=turn, attempt=attempt + 1,
                              stage='verified', status='pass', code='PASS',
                              duration_ms=int((time.monotonic() - started_at) * 1000))
                return RenderedConversationMove(
                    surface=SurfaceEnvelope(
                        display_text=prepared.display_text,
                        speech_text=str(payload.get('speech_text', '') or ''),
                        language=str(payload.get('display_language',base.get('language_hint','vi')) or 'vi'),
                        alignment_safe=bool(payload.get('alignment_safe',False)),
                        metadata=dict(payload),
                    ),
                    decision_payload=move_payload,
                    metadata={
                        'writer':'runtime_model_router_v03',
                        'event_kind':event.kind, 'user_text':event.text,
                        'provider_payload':dict(payload),
                        'source_grounding_report':report if engine is not None else None,
                        'source_grounding_engine':engine,
                        'root_capabilities_used':(),
                        'evidence_registry':evidence_registry,
                        'character_portrait':runtime_context.get('__character_portrait'),
                        'claim_manifest_envelope':envelope,
                        'prepared_public_output':prepared,
                        'claim_verification_receipt':receipt,
                    },
                )
            except Exception as exc:
                error = _v03_error_code(exc)
                rejected.append(stage + '=' + error)
                self._log_v03('warning', turn=turn, attempt=attempt + 1,
                              stage=stage, status='rejected', code=error,
                              duration_ms=int((time.monotonic() - started_at) * 1000))
        # Mỗi lần fail đều có reason riêng; lỗi thứ nhất không còn bị ghi đè.
        # Chuỗi này chỉ chứa mã đã lọc, tuyệt đối không chứa text từ model.
        raise RuntimeError('v03_candidate_rejected:' + ';'.join(rejected))

    def realize(
        self,
        *,
        turn: KernelTurn,
        event: ConversationEvent,
        recent_history: Sequence[Mapping[str, Any]],
        runtime_context: Mapping[str, Any],
    ) -> RenderedConversationMove:
        router = getattr(self.host, "ai_model_router", None)
        generate = getattr(router, "generate_public_reply", None)
        if not callable(generate):
            raise RuntimeError("public_writer_unavailable")

        move_payload = turn.move.to_dict()
        root_context = (
            "ROOT_CONVERSATION_MOVE_V12: "
            + json.dumps(move_payload, ensure_ascii=False, separators=(",", ":"))
            + ". Realize this move with natural cadence. Small reactions, fragments or "
              "expressive pauses are fine; do not add a new topic, steering question, "
              "teaching step or continuation. The `after` field is lifecycle metadata."
        )
        prior_discourse = str(runtime_context.get("discourse_context", "") or "").strip()
        discourse_context = "\n\n".join(part for part in (prior_discourse, root_context) if part)
        # Canonical V12 context dùng *_context. Hai *_summary chỉ là fallback
        # tương thích cho signal/test cũ, không phải một schema semantic khác.
        personality_context = str(
            runtime_context.get("personality_context", "")
            or runtime_context.get("personality_summary", "")
            or ""
        )
        # Character v0.2: tuyệt đối không render portrait lần hai ở writer.
        # Dùng đúng canonical text mà ContextAssembler đã giao cho Root.
        portrait_render = runtime_context.get("__character_portrait_render")
        if portrait_render is not None and personality_context != portrait_render.text:
            raise RuntimeError("character_portrait_root_writer_mismatch")
        relationship_context = str(
            runtime_context.get("relationship_context", "")
            or runtime_context.get("relationship_summary", "")
            or ""
        )
        engagement = runtime_context.get("engagement_context", "")
        if isinstance(engagement, Mapping):
            engagement = json.dumps(dict(engagement), ensure_ascii=False, separators=(",", ":"))

        # Chỉ mở rộng bằng receipt của ĐÚNG run này, sau khi Root đã hoàn tất
        # capability. Không lấy Root.say làm chứng cứ và chưa bật semantic gate.
        from .claim_evidence import EvidenceRegistry, extend_evidence_registry, render_evidence_context
        evidence_registry = runtime_context.get("__evidence_registry")
        registry = runtime_context.get("__root_capabilities")
        if isinstance(evidence_registry, EvidenceRegistry):
            receipts_for = getattr(registry, "result_receipts_for", None)
            receipts = receipts_for(event.event_id, run_id=turn.run_id,
                                    generation=turn.generation) if callable(receipts_for) else ()
            evidence_registry = extend_evidence_registry(evidence_registry, receipts)
        else:
            evidence_registry = None

        generate_kwargs = {
            "chat_history": tuple(recent_history),
            "user_text": str(event.text or ""),
            "memory_context": str(runtime_context.get("memory_context", "") or ""),
            "grounding_context": str(runtime_context.get("grounding_context", "") or ""),
            "relationship_context": relationship_context,
            "personality_context": personality_context,
            "affective_voice_state": runtime_context.get("affective_voice_state", {}),
            "interrupt_context": str(runtime_context.get("interrupt_context", "") or ""),
            "engagement_context": str(engagement or ""),
            "routing_context": str(runtime_context.get("routing_context", "") or ""),
            "discourse_context": discourse_context,
            "use_escalation": bool(runtime_context.get("use_escalation", False)),
            # Surface worker chỉ wording một semantic move đã khóa. Mặc định
            # không cho nó mở một reasoning pass dài thứ hai sau RootAgent.
            "reasoning_effort": runtime_context.get("reasoning_effort", "low"),
            "thinking_mode": runtime_context.get("thinking_mode", "disabled"),
            "allow_fallback": bool(runtime_context.get("allow_fallback", False)),
            "language_hint": str(runtime_context.get("language_hint", "vi") or "vi"),
            "speech_language_hint": str(runtime_context.get("speech_language_hint", "ja") or "ja"),
        }
        # Chỉ bổ sung source refs CÓ SCOPE vào grounding context (không chạm
        # root move), để writer thấy kết quả executor của đúng run. Chưa có
        # semantic verifier ở v0.1 nên refs không tự biến câu nói thành fact.
        if evidence_registry is not None:
            rendered_refs = render_evidence_context(evidence_registry)
            if rendered_refs:
                generate_kwargs["grounding_context"] = "\n\n".join((
                    generate_kwargs["grounding_context"],
                    "CHARACTER_V1_SOURCE_REFS: refs only support their stated scope; "
                    "assistant utterance or failed/started tool does not prove world facts.\n" + rendered_refs,
                ))

        # Test/adapter cũ chỉ stub Router và không có Decision parser, nên vẫn
        # đi đường compatibility. Host production có parser mới bật gate V0.3.
        if callable(getattr(getattr(self.host, 'parser', None), 'parse', None)):
            if evidence_registry is None:
                raise RuntimeError('v03_evidence_registry_unavailable')
            return self._realize_v03(
                generate=generate, kwargs=generate_kwargs, turn=turn,
                event=event, runtime_context=runtime_context,
                evidence_registry=evidence_registry, move_payload=move_payload,
            )

        payload = generate(**generate_kwargs)
        if not isinstance(payload, Mapping):
            raise RuntimeError("public_writer_invalid_payload")

        manifest_envelope = _inspect_writer_manifest(payload, evidence_registry)

        # Post-generation grounding gate từng bị mất call-site khi V12 cutover.
        # Gate chỉ chặn claim vượt evidence; nếu fail, SurfaceWorker được đúng một
        # lần rewrite với cùng semantic move, không giao quyền semantic cho gate.
        engine = runtime_context.get("__source_grounding_engine")
        report = runtime_context.get("__source_grounding_report")
        first_text = str(payload.get("text", "") or "").strip()
        if engine is not None and report is not None and first_text:
            try:
                from runtime.grounding_surface_gate import evaluate_grounded_surface
                verdict = evaluate_grounded_surface(
                    engine, first_text, report=report,
                    channel="chat" if event.kind == "user_turn" else "autonomous",
                )
                if not bool(getattr(verdict, "allowed", True)):
                    retry_instruction = str(getattr(verdict, "retry_instruction", lambda: "")() or "")
                    retry_kwargs = dict(generate_kwargs)
                    retry_kwargs["discourse_context"] = "\n\n".join(
                        part for part in (
                            discourse_context,
                            "GROUNDING_REWRITE_V12: " + retry_instruction,
                            "Keep the exact RootConversationMove meaning. Remove only unsupported perception/action claims; do not add a new topic or question.",
                        ) if part.strip()
                    )
                    payload = generate(**retry_kwargs)
                    if not isinstance(payload, Mapping):
                        raise RuntimeError("public_writer_grounding_retry_invalid_payload")
            except RuntimeError:
                raise
            except Exception:
                # Defense-in-depth ở DeliveryAdapter vẫn chạy. Gate lỗi nội bộ
                # không được tự bịa một violation mới.
                pass
        # Grounding gate cũ có thể yêu cầu rewrite. Manifest câu SAU rewrite
        # phải được kiểm lại, không thừa hưởng verdict của candidate thứ nhất.
        manifest_envelope = _inspect_writer_manifest(payload, evidence_registry)
        display_text = str(payload.get("text", "") or "").strip()
        if not display_text:
            raise RuntimeError("public_writer_empty")
        speech_text = str(payload.get("speech_text", "") or "").strip()
        display_language = str(
            payload.get("display_language", runtime_context.get("language_hint", "vi")) or "vi"
        ).strip()
        registry = runtime_context.get("__root_capabilities")
        used_capabilities = ()
        invocations_for = getattr(registry, "invocations_for", None)
        if callable(invocations_for):
            try:
                used_capabilities = tuple(invocations_for(str(event.event_id or "")))
            except Exception:
                used_capabilities = ()

        return RenderedConversationMove(
            surface=SurfaceEnvelope(
                display_text=display_text,
                speech_text=speech_text,
                language=display_language,
                alignment_safe=bool(payload.get("alignment_safe", False)),
                metadata=dict(payload),
            ),
            decision_payload=move_payload,
            metadata={
                "writer": "runtime_model_router",
                "event_kind": event.kind,
                "user_text": event.text,
                "provider_payload": dict(payload),
                "source_grounding_report": runtime_context.get("__source_grounding_report"),
                "source_grounding_engine": runtime_context.get("__source_grounding_engine"),
                "root_capabilities_used": list(used_capabilities),
                # Metadata private cho Task 5/6; delivery không serialize nó.
                "evidence_registry": evidence_registry,
                "character_portrait": runtime_context.get("__character_portrait"),
                "claim_manifest_envelope": manifest_envelope,
            },
        )


__all__ = ["RuntimeConversationWriter"]
