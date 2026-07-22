# -*- coding: utf-8 -*-
"""Renderer Live2D được body Godot bật/tắt theo context menu.

Godot sở hữu mode switch và forward event ``eris.stage`` sang UDP 4252. Renderer
chỉ vẽ model, điều khiển parameter và gửi yêu cầu mở context menu về UDP 4242.
"""

from .stage_state import Live2DStageState, Live2DSnapshot

__all__ = ["Live2DStageState", "Live2DSnapshot"]
