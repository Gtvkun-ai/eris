"""Chuẩn hóa external event với giới hạn kích thước, không chuyển nó thành lệnh."""
from __future__ import annotations
import hashlib
import itertools
import time
from typing import Any, Mapping
from .contracts import LiveEvent

_SEQUENCE = itertools.count(1)
KINDS = frozenset({'comment', 'gift', 'like', 'follow', 'room_end'})

def _get(value: Any, *names: str, default: Any = '') -> Any:
    for name in names:
        candidate = value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)
        if candidate is not None:
            return candidate
    return default

def _short(value: Any, size: int) -> str:
    return ' '.join(str(value or '').replace('\x00', '').split())[:size]

def normalize_event(raw: Any, *, kind: str, room_id: str, room_epoch: int,
                    now: float | None = None) -> LiveEvent:
    if kind not in KINDS:
        raise ValueError('unsupported_live_event')
    now = time.time() if now is None else float(now)
    user = _get(raw, 'user', default=None)
    uid = _short(_get(user, 'unique_id', 'uniqueId', 'user_id', 'id'), 96)
    nickname = _short(_get(user, 'nickname', 'display_name', 'name', default=uid), 80)
    if not uid:
        uid = _short(_get(raw, 'viewer_id', 'user_id'), 96)
    if not nickname:
        nickname = _short(_get(raw, 'viewer_name', 'nickname', default=uid), 80)
    source_id = _short(_get(raw, 'msg_id', 'message_id', 'event_id', 'id'), 140)
    # ID không tồn tại: dùng seq duy nhất trong process, không giả vờ exactly-once.
    if not source_id:
        source_id = f'local-{next(_SEQUENCE)}'
    # Gift streak thường tái dùng cùng msg_id cho các mốc count mới; ID phải
    # phân biệt update/final, vẫn dedup được khi replay cùng snapshot.
    gift = _get(raw, 'gift', default=None)
    gift_id = _short(_get(gift, 'id', 'name', default=_get(raw, 'gift_id')), 72)
    count = _get(raw, 'repeat_count', 'repeatCount', 'count', 'like_count', default=1)
    try:
        count = max(0, min(100000, int(count)))
    except (TypeError, ValueError):
        count = 1
    streaking_raw = _get(raw, 'streaking', default=None)
    streaking = None if streaking_raw is None else bool(streaking_raw)
    distinct = f'{count}|{streaking}' if kind == 'gift' else ''
    event_id = hashlib.blake2s(
        f'{room_id}|{room_epoch}|{kind}|{source_id}|{distinct}'.encode('utf-8'),
        digest_size=16
    ).hexdigest()
    return LiveEvent(
        event_id=event_id, room_id=_short(room_id, 80), room_epoch=int(room_epoch),
        kind=kind, occurred_at=now, viewer_id=uid, viewer_name=nickname,
        text=_short(_get(raw, 'comment', 'text', 'message'), 360),
        gift_id=gift_id, count=count, streaking=streaking,
    )
