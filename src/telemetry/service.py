from cortex import SeLens, TelemetrySnapshot

from .system import TelemetryMixin


class TelemetryService(TelemetryMixin):
    def __init__(self):
        self.se_lens = SeLens()

    def capture_snapshot(self, *, mood_score: int, inferred_pos_x: float) -> TelemetrySnapshot:
        raw = self.capture_raw_telemetry(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
        return self.se_lens.build_snapshot(raw)

    def format_snapshot(self, snapshot: TelemetrySnapshot) -> str:
        return self.se_lens.format_snapshot(snapshot)

    def get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float):
        snapshot = self.capture_snapshot(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
        return self.format_snapshot(snapshot)
