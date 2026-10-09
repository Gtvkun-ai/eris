# -*- coding: utf-8 -*-
"""Hotfix production: mỗi lần Eris im lặng phải có reason code có thể truy vết.

Dùng fake provider, không gọi mạng hoặc ElevenLabs. Mọi lỗi đều fail-closed:
không phát lời, không ghi memory và không tự tạo receipt giả.
"""
from __future__ import annotations

from types import SimpleNamespace

from runtime.conversation.claim_evidence import build_evidence_registry
from runtime.conversation.contracts import ConversationEvent, NextConversationMove
from runtime.conversation.kernel import ConversationKernel
from runtime.conversation.runtime_writer import RuntimeConversationWriter
from test_character_claim_integrity_v1 import Parser, Router


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, template, *args):
        self.lines.append(('warning', template % args))

    def info(self, template, *args):
        self.lines.append(('info', template % args))


class _Agent:
    def decide(self, **kwargs):
        return NextConversationMove(intent='chào hỏi', say='chào người dùng')


class _Delivery:
    def __init__(self):
        self.calls = []

    def deliver(self, **kwargs):
        self.calls.append(kwargs)


def _run_with_router(router):
    log = _Log()
    host = SimpleNamespace(
        ai_model_router=router, parser=Parser(), logger=log,
        ai_stage_planner=None, current_stage_user_text='xin chào',
        chat_history=[], sent=[], last_text='',
    )
    delivery = _Delivery()
    kernel = ConversationKernel(_Agent(), writer=RuntimeConversationWriter(host),
                                delivery=delivery, logger=log)
    event = ConversationEvent(event_id='chat:hotfix', session_id='hotfix',
                              kind='user_turn', text='xin chào')
    registry = build_evidence_registry(
        event=event, state=None, affect=None, report=None,
        ledger_turns=(), memory_records=(), sampled_at=1.0,
    )
    outcome = kernel.handle_event(event, runtime_context={'__evidence_registry': registry})
    return outcome, log, delivery, router


def test_missing_manifest_reports_both_attempts_without_public_commit():
    router = Router()
    router.payloads = [{'text': 'Chào', 'speech_text': 'こんにちは。'}]
    outcome, log, delivery, router = _run_with_router(router)

    assert outcome.status == 'writer_failed'
    assert 'manifest=MANIFEST_MISSING' in outcome.failure_reason
    assert outcome.failure_reason.count('manifest=MANIFEST_MISSING') == 2
    assert len(router.writer_calls) == 2
    assert not router.worker_calls  # Deterministic failure không gọi checker tốn phí.
    assert not delivery.calls
    assert len([line for level, line in log.lines
                if level == 'warning' and 'writer_candidate' in line]) == 2
    assert any('writer_failed' in line and 'failure_reason=' not in line and
               'reason=v03_candidate_rejected:' in line
               for _, line in log.lines)
    assert all('xin chào' not in line for _, line in log.lines)


def test_checker_invalid_schema_is_visible_but_never_bypassed():
    router = Router()
    # Simulate router._call returning {} after provider timeout/admission failure.
    router.invoke_structured_worker = lambda *_args, **_kwargs: {}
    outcome, log, delivery, router = _run_with_router(router)

    assert outcome.status == 'writer_failed'
    assert 'verify=v03_verify_unknown:VERIFIER_SCHEMA_INVALID' in outcome.failure_reason
    assert len(router.writer_calls) == 2
    assert not delivery.calls
    assert any('stage=verify' in line and 'VERIFIER_SCHEMA_INVALID' in line
               for _, line in log.lines)


def test_successful_greeting_still_goes_through_verifier():
    router = Router()
    outcome, log, delivery, router = _run_with_router(router)

    assert outcome.status == 'delivering'
    assert outcome.failure_reason == ''
    assert len(router.writer_calls) == 1
    assert len(router.worker_calls) == 1
    assert len(delivery.calls) == 1
    rendered = delivery.calls[0]['rendered']
    assert rendered.metadata['claim_verification_receipt'].status == 'pass'
    assert any('stage=verified status=pass' in line for _, line in log.lines)


def test_provider_exception_message_never_reaches_log_or_rewrite():
    """Nội dung lỗi của provider có thể chứa key/response, chỉ dùng tên lớp lỗi."""
    from runtime.conversation.runtime_writer import _v03_error_code

    sensitive = RuntimeError('Authorization failed: Bearer sk-user-secret-example')
    assert _v03_error_code(sensitive) == 'RuntimeError'
    assert _v03_error_code(RuntimeError('v03_speech_language_mismatch')) == 'v03_speech_language_mismatch'
