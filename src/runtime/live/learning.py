"""P7: bằng chứng tổng hợp giữa các buổi live, hoàn toàn không phải persona engine.

Mặc định OFF. Không lưu tên/người xem/chat/voice/memory; các nhận xét chỉ là
thống kê bối cảnh để Root tự lựa chọn hành vi, KHÔNG phải tín hiệu thưởng.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone

class LiveAggregateLearning:
    def __init__(self, path: str | Path | None = None, *, enabled: bool | None = None):
        self.enabled = (os.getenv('ERIS_LIVE_LEARNING_ENABLED', '0').lower()
                        in {'1','true','yes','on'}) if enabled is None else bool(enabled)
        if path is not None:
            self.path = Path(path)
        else:
            from runtime.workspace_manager import default_eris_home
            self.path = Path(default_eris_home()) / 'logs' / 'live_experience_aggregate.json'
        self._lock = RLock()
        self._sessions: list[dict] = []
        if self.enabled:
            self._load()

    def _load(self):
        try:
            content = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(content, list):
                self._sessions = [self._sanitize(x) for x in content[-20:] if isinstance(x, dict)]
        except (OSError, ValueError, TypeError):
            self._sessions = []

    @staticmethod
    def _sanitize(item: dict) -> dict:
        # Whitelist ONLY numeric operational evidence; never preserve viewer/chat.
        keys = ('duration_s', 'accepted', 'duplicate', 'overflow', 'batches',
                'root_attempts', 'no_reply', 'delivery', 'audio_delivered', 'errors')
        out = {k: max(0, min(10_000_000, int(item.get(k, 0) or 0)))
               for k in keys}
        out['date'] = str(item.get('date', ''))[:10] if str(item.get('date', ''))[:10].replace('-', '').isdigit() else ''
        return out

    def finish(self, counters: dict, *, duration_s: float) -> None:
        if not self.enabled:
            return
        data = dict(counters)
        data['duration_s'] = duration_s
        data['date'] = datetime.now(timezone.utc).date().isoformat()
        record = self._sanitize(data)
        with self._lock:
            self._sessions = (self._sessions + [record])[-20:]
            # Atomic replace; opt-in, no raw data. Not a diary and no person identifiers.
            tmp = self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(self._sessions, ensure_ascii=False, indent=2), encoding='utf-8')
                tmp.replace(self.path)
            except OSError:
                try: tmp.unlink(missing_ok=True)
                except OSError: pass

    def evidence(self) -> tuple[dict, ...]:
        if not self.enabled:
            return ()
        with self._lock:
            return tuple(dict(x) for x in self._sessions[-3:])
