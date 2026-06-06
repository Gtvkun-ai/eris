# -*- coding: utf-8 -*-
"""Worker Phase 1/2 cho subconscious runtime."""

from .user_modeler import UserModelerAgent
from .memory_resonator import MemoryResonatorAgent
from .goal_simulator import GoalSimulatorAgent
from .self_regulator import SelfRegulatorAgent
from .rehearsal import RehearsalAgent
from .curiosity_gap import CuriosityGapAgent

__all__ = [
    "UserModelerAgent",
    "MemoryResonatorAgent",
    "GoalSimulatorAgent",
    "SelfRegulatorAgent",
    "RehearsalAgent",
    "CuriosityGapAgent",
]


def build_phase12_workers(*, allow_surface_memory_echo: bool = False):
    """Tạo worker set Phase 1+2 mặc định.

    Mặc định memory echo không surface trực tiếp. Integration sâu hơn có thể bật
    `allow_surface_memory_echo=True` sau khi guard/runtime đã kiểm soát tốt.
    """

    return (
        UserModelerAgent(),
        MemoryResonatorAgent(allow_surface_echo=allow_surface_memory_echo),
        GoalSimulatorAgent(),
        SelfRegulatorAgent(),
        CuriosityGapAgent(),
        RehearsalAgent(),
    )

__all__.append("build_phase12_workers")
