from __future__ import annotations

"""Public import cho memory intake 3 tầng.

StateCommitService cũ vẫn import MemoryCommitPolicy từ memory_commit_policy. File này
là tên kiến trúc mới, để code mới có thể import MemoryIntakePolicy mà không phá
đường cũ. Đúng, chỉ một alias thôi cũng cứu được vài buổi debug. Nhân loại đã
từng làm tệ hơn với inheritance.
"""

from .memory_commit_policy import MemoryCommitPolicy, MemoryIntakePolicy

__all__ = ["MemoryCommitPolicy", "MemoryIntakePolicy"]
