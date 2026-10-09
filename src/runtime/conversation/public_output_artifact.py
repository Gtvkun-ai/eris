# -*- coding: utf-8 -*-
"""Character v0.3: bản nháp public ĐÃ QUA stage, chưa có tác dụng phụ.

Không gọi mạng, không ghi history, không phát âm thanh. Chỉ những bytes/chữ đã
được đóng băng ở đây mới có thể được đối chiếu với receipt của verifier.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping


def sha(text: str) -> str:
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()


def udp_clean(text: str) -> str:
    # Cùng hợp đồng transport/udp._strip_udp_unsafe_text.
    from transport.udp import _strip_udp_unsafe_text
    return _strip_udp_unsafe_text(str(text or ''))


def tts_clean(text: str) -> str:
    from runtime.tts_engine import _clean_text
    return _clean_text(str(text or ''))


@dataclass(frozen=True, slots=True)
class VerifiedTranscript:
    delivery_id: str
    generation: int
    segment_id: int
    transcript_hash: str


@dataclass(frozen=True, slots=True)
class PreparedPublicOutput:
    event_id: str
    session_id: str
    generation: int
    run_id: str
    move_id: str
    delivery_id: str
    channel: str
    display_text: str
    speech_text: str
    memory_text: str
    stage_frame: Any
    segments: tuple[Any, ...]
    payload: Mapping[str, Any]
    source_fingerprint: str
    # Decision được chuẩn bị cùng frame, giữ riêng trong process; tuyệt đối
    # không serialize object này vào UDP/memory.
    decision: Any = None

    @property
    def display_hash(self) -> str:
        return sha(self.display_text)

    @property
    def speech_hash(self) -> str:
        return sha(json.dumps([tts_clean(f.tts_text) for f in self.segments], ensure_ascii=False))

    @property
    def memory_hash(self) -> str:
        return sha(self.memory_text)

    @property
    def segment_hashes(self) -> tuple[str, ...]:
        return tuple(sha(tts_clean(f.tts_text)) for f in self.segments)


def prepare_public_output(*, event_id: str, turn: Any, channel: str, decision: Any,
                          payload: Mapping[str, Any], source_fingerprint: str = '') -> PreparedPublicOutput:
    """Dựng đúng StageFrame/segments theo pipeline thực, nhưng KHÔNG dispatch.

    Nếu Stage/UDP/TTS thay chữ, phát hiện ở đây hoặc tầng dispatch, không giả
    vờ rằng model text ban đầu chính là transcript đã phát.
    """
    from runtime.stage_contracts import StageFrameBuilder
    from runtime.stage_output import StageOutputPipeline
    from runtime.runtime_settings_store import runtime_text
    from runtime.public_surface_commit import GLOBAL_PUBLIC_SURFACE_COMMITTER
    from runtime.voice_profile_compiler import compile_voice_plan_from_payload
    from transport.udp import MAX_UDP_PAYLOAD_BYTES, _sanitize_udp_payload
    from runtime.json_boundary import public_payload

    did = str(getattr(turn, 'delivery_id', '') or '')
    if not did:
        raise RuntimeError('v03_delivery_identity_missing')
    # Chỉ chỉnh instance Decision candidate; không mutate host/state.
    surfaces = GLOBAL_PUBLIC_SURFACE_COMMITTER.build(str(getattr(decision, 'text', '') or ''))
    decision.text = surfaces.display_text
    safe_payload = public_payload(payload)
    safe_payload.update(decision.to_payload())
    safe_payload['user_text'] = str(payload.get('user_text', '')) if channel == 'chat' else ''
    language = runtime_text('tts', 'language', default='ja').strip().lower() or 'ja'
    if language == 'auto':
        language = 'ja'
    builder = StageFrameBuilder(language_hint=language)
    frame = builder.build(decision, payload=safe_payload, channel=channel,
                          frame=None, turn_id=None, segment_id=0)
    if frame.tts_text:
        try:
            frame = replace(frame, voice_plan=dict(compile_voice_plan_from_payload(
                safe_payload, fallback_style=frame.prosody_style,
            )))
        except Exception:
            # Lỗi metadata prosody không được đổi lời đã xác minh.
            pass
    segments = tuple(StageOutputPipeline().frames_for_tts(frame))
    if getattr(frame, 'audio_asset', ''):
        # WAV preset chưa chứng minh transcript đúng. Không dùng audio asset
        # không có receipt content riêng để phát một câu đã semantic-verify.
        raise RuntimeError('v03_unverified_preset_audio')
    if not frame.display_text.strip():
        raise RuntimeError('v03_empty_final_display')
    if str(getattr(decision, 'should_speak', False)) == 'True' and not segments:
        raise RuntimeError('v03_no_speech_segments')
    # TTS sẽ clean text lần nữa. Kiểm trước: hậu kiểm phải trùng nguyên văn.
    for segment in segments:
        if not tts_clean(segment.tts_text):
            raise RuntimeError('v03_empty_tts_segment')
        contract = dict(getattr(segment, 'speech_contract', {}) or {})
        if str(contract.get('language', '')).lower() == 'ja':
            from runtime.stage_contracts import _contains_japanese_script
            if not _contains_japanese_script(segment.tts_text):
                raise RuntimeError('v03_speech_language_mismatch')
    safe_payload['text'] = frame.display_text
    safe_payload['memory_text'] = frame.memory_text
    safe_payload.update(frame.to_payload_patch())
    safe_payload.setdefault('stage', {}).update({'segment_count':len(segments),'protocol':'eris.stage','protocol_version':1})
    # Một datagram riêng chứa speech, không chứa private panel. UDP sender không
    # được tự truncate câu v0.3; kiểm preflight giống định dạng json thực.
    body = dict(safe_payload)
    for key in ('private_mind_digest','private_life_digest','emotion_debug','depth_v2'):
        body.pop(key, None)
    packet = json.dumps(_sanitize_udp_payload(body), ensure_ascii=False).encode('utf-8')
    if len(packet) > MAX_UDP_PAYLOAD_BYTES:
        raise RuntimeError('v03_udp_payload_overflow')
    if udp_clean(frame.display_text) != frame.display_text:
        raise RuntimeError('v03_udp_display_changed')
    if udp_clean(frame.memory_text) != frame.memory_text:
        raise RuntimeError('v03_udp_memory_changed')
    return PreparedPublicOutput(
        event_id=event_id, session_id=turn.session_id, generation=turn.generation,
        run_id=turn.run_id, move_id=turn.move.move_id, delivery_id=did,
        channel=channel, display_text=frame.display_text,
        speech_text=' '.join(tts_clean(f.tts_text) for f in segments),
        memory_text=frame.memory_text, stage_frame=frame, segments=segments,
        payload=safe_payload, source_fingerprint=source_fingerprint,
        decision=decision,
    )


def lock_verified_segments(prepared: PreparedPublicOutput) -> PreparedPublicOutput:
    """Mang token hash tới TTS task và kiểm cả cache hits.

    Cần dùng SAU verdict pass, không set cờ trusted từ trước kiểm.
    """
    segments = []
    for frame in prepared.segments:
        contract = dict(frame.speech_contract)
        contract['verified_transcript_hash'] = sha(tts_clean(frame.tts_text))
        contract['verified_delivery_id'] = prepared.delivery_id
        segments.append(replace(frame, speech_contract=contract))
    return replace(prepared, segments=tuple(segments))


def validate_prepared(prepared: PreparedPublicOutput) -> None:
    """Không tin object đã qua stage nếu bị mutate lúc chờ callback."""
    if prepared.stage_frame.display_text != prepared.display_text:
        raise RuntimeError('v03_stage_display_tampered')
    if prepared.stage_frame.memory_text != prepared.memory_text:
        raise RuntimeError('v03_stage_memory_tampered')
    if any(sha(tts_clean(frame.tts_text)) != prepared.segment_hashes[i]
           for i, frame in enumerate(prepared.segments)):
        raise RuntimeError('v03_speech_tampered')
    if len(prepared.segments) == 0 or str(prepared.decision.text) != prepared.display_text:
        raise RuntimeError('v03_candidate_tampered')
