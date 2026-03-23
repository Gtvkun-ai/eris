from .system import TelemetryMixin


class TelemetryService(TelemetryMixin):
    def get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float):
        return super().get_system_telemetry(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
