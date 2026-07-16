# -*- coding: utf-8 -*-
"""Phiên bản contract của kiến trúc Autonomous VTuber.

Tách version ra một file nhỏ để prompt, debug panel, telemetry và test cùng dùng
một nguồn sự thật. Nếu mỗi nơi tự gõ ``v7`` thì sớm muộn cũng sẽ có một nơi còn
kẹt ở ``v6`` và mọi người lại được thưởng thức khảo cổ phần mềm lúc nửa đêm.
"""

AUTONOMOUS_STAGE_ARCHITECTURE_VERSION = "autonomous_stage.v7"
AUTONOMOUS_STAGE_PHASE = 7
AUTONOMOUS_STAGE_STATUS = "integration_closure"


__all__ = [
    "AUTONOMOUS_STAGE_ARCHITECTURE_VERSION",
    "AUTONOMOUS_STAGE_PHASE",
    "AUTONOMOUS_STAGE_STATUS",
]
