from .system import TelemetryMixin

# TelemetryService là một lớp dịch vụ để thu thập và cung cấp dữ liệu telemetry hệ thống,
#  nó kế thừa từ TelemetryMixin, cho phép nó sử dụng các phương thức
#  được định nghĩa trong mixin để thu thập thông tin về trạng thái tâm trạng và vị trí ước tính của hệ thống.
class TelemetryService(TelemetryMixin):
    def get_system_telemetry(self, *, mood_score: int, inferred_pos_x: float):
        return super().get_system_telemetry(
            mood_score=mood_score,
            inferred_pos_x=inferred_pos_x,
        )
