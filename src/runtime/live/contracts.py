"""Hợp đồng sự kiện TikTok: dữ liệu bên ngoài, không có thẩm quyền điều khiển Eris."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

LiveKind = Literal['comment', 'gift', 'like', 'follow', 'room_end']

@dataclass(frozen=True, slots=True)
class LiveEvent:
    event_id: str
    room_id: str
    room_epoch: int
    kind: LiveKind
    occurred_at: float
    viewer_id: str = ''
    viewer_name: str = ''
    text: str = ''
    gift_id: str = ''
    count: int = 0
    streaking: bool | None = None

@dataclass(frozen=True, slots=True)
class AudienceScope:
    channel: Literal['public_live']
    session_id: str
    room_epoch: int
    allow_private_memory: bool = False
    allow_tools: bool = False
    allow_private_journal: bool = False

@dataclass(slots=True)
class LiveCounters:
    accepted: int = 0
    duplicate: int = 0
    overflow: int = 0
    expired: int = 0
    stale: int = 0
    batches: int = 0
    root_attempts: int = 0
    root_busy: int = 0
    no_reply: int = 0
    delivery: int = 0  # entered output pipeline, NOT proof of audible delivery
    audio_delivered: int = 0
    audio_failed: int = 0
    audio_cancelled: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

@dataclass(frozen=True, slots=True)
class LiveBatch:
    room_id: str
    room_epoch: int
    emitted_at: float
    comments: tuple[dict, ...] = ()
    gifts: tuple[dict, ...] = ()
    likes: int = 0
    follows: int = 0
    received: int = 0

    def to_context(self) -> dict:
        return {
            'room_epoch': self.room_epoch,
            'comments': list(self.comments),
            'gifts': list(self.gifts),
            'likes': self.likes,
            'follows': self.follows,
            'received_events': self.received,
            'trust': 'untrusted_viewer_data',
        }

    @property
    def is_empty(self) -> bool:
        return not (self.comments or self.gifts or self.likes or self.follows)
