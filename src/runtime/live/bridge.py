"""TikTok là môi trường xã hội mới của *cùng* Eris RootAgent.

Không gọi LLM/TTS trên callback. Chỉ poll worker được phép wake kernel.
Không sử dụng context assembler/chat history/long-term memory của owner.
"""
from __future__ import annotations
import os
import threading
import time
import uuid
from collections import deque
from typing import Any
from contextlib import contextmanager
from .batcher import LiveBatcher
from .contracts import AudienceScope, LiveBatch, LiveCounters, LiveEvent
from .intake import BoundedLiveIntake
from .lifecycle import LiveLifecycle
from .experience import LiveExperienceLedger
from .learning import LiveAggregateLearning
from .normalize import normalize_event
from .scope import public_context, public_affect_projection
from .session import LiveSession

_BUSY = {'thinking', 'working', 'writing', 'delivering', 'continuation_pending'}

class ErisLiveRuntime:
    def __init__(self, host: Any, *, enabled: bool = False, interval: float = 5.0) -> None:
        self.host = host
        self.enabled = enabled
        self.interval = max(1.0, min(20.0, float(interval)))
        self.lifecycle = LiveLifecycle()
        self.counters = LiveCounters()
        self.intake = BoundedLiveIntake(counters=self.counters)
        self.batcher = LiveBatcher()
        self.experience = LiveExperienceLedger()
        self.learning = LiveAggregateLearning()
        self.mode = 'offline'
        self._started_at = 0.0
        self._events_preview: deque[dict] = deque(maxlen=12)  # RAM, public-only
        self.session: LiveSession | None = None
        self._last_batch: LiveBatch | None = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._connector: Any = None
        self._lock = threading.RLock()
        self._terminal: dict[str, str] = {}
        self.blocked_reason = ''
        self._tracked_dids: set[str] = set()
        self._speaking_did = ''

    def start(self, room_id: str, *, connect: bool = False, background: bool = True) -> int:
        if not self.enabled:
            raise PermissionError('ERIS_LIVE_ENABLED must be explicitly enabled')
        self.stop()
        with self._lock:
            epoch = self.lifecycle.start(room_id)
            self._started_at = time.time()
            self._events_preview.clear()
            self.mode = 'connecting' if connect else 'simulator'
            self.session = LiveSession(room_id=room_id, epoch=epoch)
            # Counters are per live session; summaries persist separately on opt-in.
            self.counters = LiveCounters()
            self.intake.counters = self.counters
            self.batcher.reset()
            self.experience.clear()
            self.intake.clear()
            self._last_batch = None
            self._terminal.clear()
            self._tracked_dids.clear()
            self._speaking_did = ''
            self._stop = threading.Event()  # Old worker keeps old signal.
            if background:
                self._worker = threading.Thread(target=self._work_loop,
                     args=(self._stop, room_id, epoch),
                     name='ErisLivePoll', daemon=True)
                self._worker.start()
            if connect:
                from .connector import TikTokLiveConnector
                self._connector = TikTokLiveConnector(self, unique_id=room_id)
                self._connector.start()
            return epoch

    def stop(self) -> None:
        with self._lock:
            old_session = self.session
            was_active = self.lifecycle.snapshot()[2]
            previous_started_at = self._started_at
            previous_counts = self.counters.snapshot()
            self.lifecycle.stop()  # Invalidate all Root/Writer guard closures NOW.
            self._stop.set()
            connector = self._connector
            self._connector = None
            self.session = None
            self._last_batch = None
            self.intake.clear()
            self.batcher.reset()
            self.experience.clear()
            self._terminal.clear()
            self.mode = 'offline'
            self._events_preview.clear()
            live_ids_at_stop = set(self._tracked_dids)
            self._tracked_dids.clear()
            self._speaking_did = ''
        if was_active and previous_started_at:
            self.learning.finish(previous_counts, duration_s=time.time() - previous_started_at)
        if connector is not None:
            connector.stop()
        if old_session is not None:
            # Hủy đúng live TTS đang nắm audio floor; không cắt lời owner.
            clock = getattr(self.host, 'interaction_clock', None)
            floor = str(getattr(clock, 'audio_floor_turn_id', '') or '')
            if floor and floor in live_ids_at_stop:
                voice = getattr(self.host, 'voice_manager', None)
                cancel = getattr(voice, '_cancel_audio', None)
                if callable(cancel):
                    try:
                        cancel(reason='public_live_stopped')
                    except Exception:
                        pass
            # stop is a trusted owner/local control; viewer comment cannot call it.
            kernel = getattr(self.host, 'conversation_kernel', None)
            if kernel is not None:
                try:
                    kernel.preempt_for_user(old_session.session_id)
                except Exception:
                    pass
            old_session.clear()
        # Không mặc định hủy toàn bộ TTS host: audio cá nhân có thể đang phát;
        # stop ở đây invalidate future packets. Live audio đang chơi cần Stop TTS
        # thủ công qua voice manager theo ứng dụng hiện tại.

    def _owner_busy(self) -> bool:
        if bool(getattr(self.host, '_chat_processing', False)):
            return True
        sid = str(getattr(self.host, 'conversation_id', '') or
                  getattr(self.host, 'thread_id', '') or 'foreground:primary')[:180]
        if sid.startswith('public_live:'):
            return False
        kernel = getattr(self.host, 'conversation_kernel', None)
        if kernel is None:
            return False
        try:
            phase = getattr(kernel.snapshot(sid).phase, 'value', '')
            return phase in _BUSY
        except Exception:
            return False

    def guard(self, *, room: str, epoch: int) -> bool:
        return self.lifecycle.valid(room, epoch)

    def guard_turn(self, turn: Any) -> bool:
        session = self.session
        return (session is not None and turn.session_id == session.session_id
                and self.guard(room=session.room_id, epoch=session.epoch))

    def ingest(self, raw: Any, *, kind: str, now: float | None = None) -> bool:
        room, epoch, active = self.lifecycle.snapshot()
        if not active:
            self.counters.stale += 1
            return False
        event = normalize_event(raw, kind=kind, room_id=room, room_epoch=epoch, now=now)
        return self.offer(event)

    def offer(self, event: LiveEvent) -> bool:
        if not self.guard(room=event.room_id, epoch=event.room_epoch):
            self.counters.stale += 1
            return False
        if event.kind == 'room_end':
            # Do not call stop on provider thread (may deadlock connector).
            self._stop.set()
            return True
        offered = self.intake.offer(event)
        if offered:
            with self._lock:
                # No raw chat persisted; avoid logging private owner IDs.
                self._events_preview.append({
                    'kind': event.kind, 'viewer': event.viewer_name[:50],
                    'text': event.text[:160] if event.kind == 'comment' else '',
                    'gift': event.gift_id[:60] if event.kind == 'gift' else '',
                    'count': event.count if event.kind in {'gift', 'like'} else 1,
                    'time': round(event.occurred_at, 1),
                })
        return offered

    def _work_loop(self, stopping: threading.Event, room: str, epoch: int) -> None:
        while self.guard(room=room, epoch=epoch) and not stopping.wait(self.interval):
            try:
                self.tick()
            except Exception:
                self.counters.errors += 1
        # Provider disconnect/room end: prevent speech from an expired room.
        if stopping.is_set() and self.guard(room=room, epoch=epoch):
            self.stop()

    def tick(self) -> str:
        if self._stop.is_set():
            self.stop()
            return 'inactive'
        session = self.session
        if session is None or not self.guard(room=session.room_id, epoch=session.epoch):
            return 'inactive'
        # Ngăn Root/DeepSeek sinh câu không thể phát vì cài đặt TTS đang ja.
        from runtime.speech_contract import configured_speech_language
        if configured_speech_language() != 'vi':
            self.blocked_reason = 'set_tts_language_to_vi_before_live'
            return 'tts_config_blocked'
        self.blocked_reason = ''
        events = self.intake.drain()
        fresh = [event for event in events if self.guard(room=event.room_id, epoch=event.room_epoch)]
        self.counters.stale += len(events) - len(fresh)
        batch = self.batcher.build(fresh)
        if batch is not None and not batch.is_empty:
            self.experience.observe_batch(batch)
            old = self._last_batch
            if old is not None and old.room_epoch == batch.room_epoch and old.room_id == batch.room_id and time.time() - old.emitted_at < self.intake.ttl_seconds:
                # Giữ sự kiện gift quan trọng và một cửa sổ comment gần nhất
                # khi audio floor bận; không replay tất cả raw events.
                batch = LiveBatch(
                    room_id=batch.room_id, room_epoch=batch.room_epoch,
                    emitted_at=batch.emitted_at,
                    comments=(old.comments + batch.comments)[-12:],
                    gifts=(old.gifts + batch.gifts)[-12:],
                    likes=old.likes + batch.likes,
                    follows=old.follows + batch.follows,
                    received=old.received + batch.received,
                )
            self._last_batch = batch
        if self._last_batch is None:
            return 'empty'
        from runtime.conversation.bootstrap import ensure_conversation_kernel
        from runtime.conversation.contracts import ConversationEvent
        kernel = ensure_conversation_kernel(self.host)
        status = getattr(kernel.snapshot(session.session_id).phase, 'value', '')
        if status in _BUSY or self._owner_busy():
            self.counters.root_busy += 1
            return 'busy'
        clock = getattr(self.host, 'interaction_clock', None)
        audio_busy = getattr(clock, 'speech_floor_busy', None)
        if callable(audio_busy) and audio_busy():
            self.counters.root_busy += 1
            return 'audio_busy'
        chosen = self._last_batch
        if time.time() - chosen.emitted_at > self.intake.ttl_seconds:
            self._last_batch = None
            self.counters.expired += 1
            return 'expired'
        self._last_batch = None
        self.counters.batches += 1
        scope = AudienceScope(channel='public_live', session_id=session.session_id,
                              room_epoch=session.epoch)
        bound_guard = lambda: (self.guard(room=session.room_id, epoch=session.epoch)
                               and not self._owner_busy())
        if not bound_guard():
            return 'stale'
        context = public_context(chosen, scope, active_guard=bound_guard)
        current_affect = public_affect_projection(self.host)
        if current_affect:
            context['affective_voice_state'] = current_affect
        old_sessions = self.learning.evidence()
        if old_sessions:
            context['discourse_context'] += ('\nPrevious live sessions (aggregate operational evidence, '
                'NOT popularity rewards or causal proof): ' + str(old_sessions)[:650])
        feedback = self.experience.public_summary()
        if feedback:
            context['discourse_context'] += '\nRecent live reception (aggregate, NOT a causal score): ' + str(feedback)[:800]
        # Chỉ event.metadata/public_context từ dữ liệu được chọn. Không gọi
        # assemble_autonomous() hay host._chat_history_for_llm().
        event = ConversationEvent(event_id=f'live:{uuid.uuid4().hex}',
                                  session_id=session.session_id, kind='live_signal',
                                  metadata={'public_live': chosen.to_context(),
                                            'trust': 'external_untrusted'})
        history = session.history()
        self.counters.root_attempts += 1
        try:
            result = kernel.handle_event(event, recent_history=history,
                                         runtime_context=context)
        except Exception:
            self.counters.errors += 1
            return 'error'
        result_status = str(getattr(result, 'status', '') or '')
        if result_status == 'busy':
            # Không tự quay vòng quá nhanh; event mới có thể thay snapshot này.
            self._last_batch = chosen
            self.counters.root_busy += 1
        elif result_status == 'no_reply':
            self.counters.no_reply += 1
        elif result_status == 'delivering':
            self.counters.delivery += 1
        if result_status not in {'busy', 'stale', 'delivery_failed', 'writer_failed',
                                 'root_provider_failed'} and bound_guard():
            session.add_observation('Phòng live có ' + str(chosen.received) + ' sự kiện mới. '
                + '; '.join(str(item['viewer']) + ': ' + str(item['text'])
                            for item in chosen.comments[-3:])[:700])
        return result_status

    @contextmanager
    def dispatch_guard(self, turn: Any):
        # Serialized with stop(): after stop returns, no new live packet may
        # enter _send_decision_to_body. This is a mechanical lease only.
        with self._lock:
            if not self.guard_turn(turn):
                raise RuntimeError('live_room_stale_at_transport')
            yield

    def track_delivery(self, delivery_id: str) -> None:
        with self._lock:
            if self.session is not None:
                self._tracked_dids.add(delivery_id)
                if len(self._tracked_dids) > 128:
                    self._tracked_dids.pop()

    def is_live_delivery(self, delivery_id: str) -> bool:
        with self._lock:
            return delivery_id in self._tracked_dids

    def cancel_delivery(self, delivery_id: str) -> None:
        with self._lock:
            self._tracked_dids.discard(delivery_id)
            if self._speaking_did == delivery_id: self._speaking_did = ''
            self._terminal.pop(delivery_id, None)

    def delivery_accepted(self, delivery_id: str, text: str) -> None:
        session = self.session
        if session is None:
            return
        session.accepted(delivery_id, text)
        previous = self._terminal.pop(delivery_id, None)
        if previous:
            session.finish(delivery_id, delivered=previous == 'delivered')
            if previous == 'delivered':
                self.counters.audio_delivered += 1
                self.experience.delivered(delivery_id)
            elif previous == 'failed':
                self.counters.audio_failed += 1
            elif previous == 'cancelled':
                self.counters.audio_cancelled += 1

    def on_audio_started(self, delivery_id: str) -> None:
        """Playback edge from StageEventBus; subtitle is NOT displayed on generation."""
        with self._lock:
            if self.session is not None and delivery_id in self._tracked_dids:
                self._speaking_did = delivery_id

    def on_audio_outcome(self, delivery_id: str, status: str) -> None:
        if not delivery_id or status not in {'delivered', 'failed', 'cancelled'}:
            return
        with self._lock:
            session = self.session
            if session is None or delivery_id not in self._tracked_dids:
                return
            if self._speaking_did == delivery_id:
                self._speaking_did = ''
            if delivery_id in session._pending:
                session.finish(delivery_id, delivered=status == 'delivered')
                if status == 'delivered':
                    self.counters.audio_delivered += 1
                    self.experience.delivered(delivery_id)
                elif status == 'failed':
                    self.counters.audio_failed += 1
                elif status == 'cancelled':
                    self.counters.audio_cancelled += 1
            else:
                self._terminal[delivery_id] = status
                if len(self._terminal) > 64:
                    self._terminal.pop(next(iter(self._terminal)))

    def status(self) -> dict:
        room, epoch, active = self.lifecycle.snapshot()
        with self._lock:
            preview = list(self._events_preview)
            current_did = self._speaking_did
            # Text already passed the public-output gate. Never expose owner chat.
            caption = str(self.session._pending.get(current_did, '') if self.session else '')[:360]
            connection = getattr(self._connector, 'connection_state', 'disconnected')
        return {'active': active, 'room': room, 'epoch': epoch,
                'mode': self.mode, 'connection': connection,
                'uptime_s': round(max(0, time.time() - self._started_at), 1) if active else 0,
                'events': preview, 'caption': caption, 'audio_speaking': bool(current_did),
                'experience': self.experience.public_summary(),
                'queue_depth': self.intake.depth, 'blocked_reason': self.blocked_reason,
                **self.counters.snapshot()}


def ensure_live_runtime(host: Any) -> ErisLiveRuntime:
    current = getattr(host, 'eris_live', None)
    if isinstance(current, ErisLiveRuntime):
        return current
    enabled = os.environ.get('ERIS_LIVE_ENABLED', '0').lower() in {'1', 'true', 'on', 'yes'}
    runtime = ErisLiveRuntime(host, enabled=enabled,
                 interval=float(os.environ.get('ERIS_LIVE_BATCH_SECONDS', '5') or 5))
    host.eris_live = runtime
    return runtime
