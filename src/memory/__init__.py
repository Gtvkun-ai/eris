"""Public memory API for ERIS.

Use `MemoryKernel` from the package root for new integration.

Legacy core/query/commit types are intentionally no longer re-exported here.
Import them from `memory.memory_cognition` explicitly when compatibility is
still needed.
"""

from .memory_kernel import MemoryCoreKernel, MemoryKernel, MemoryKernelDebugSnapshot
from .memory_kernel_contracts import (
    MaintenanceBudget,
    MemoryAnswerResult,
    MemoryIngestMode,
    MemoryIngestResult,
    MemoryKernelConfig,
    MemoryMaintenanceReport,
)

__all__ = [
    "MemoryKernel",
    "MemoryCoreKernel",
    "MemoryKernelDebugSnapshot",
    "MemoryKernelConfig",
    "MemoryIngestMode",
    "MemoryIngestResult",
    "MemoryAnswerResult",
    "MemoryMaintenanceReport",
    "MaintenanceBudget",
]
