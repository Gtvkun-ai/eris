# -*- coding: utf-8 -*-
"""cortex.meaning — Phase 2 meaning layer package.

Tầng hiểu ý nghĩa (meaning) của Phase 2. Bọc (wrap) các module hiện hữu
(`semantic_hypothesis.py`, `meaning.py`, `affect_semantics.py`,
`continuity_threat.py`) vào các contract Phase 2 rõ ràng và cưỡng chế hai
ràng buộc xương sống: WorkspaceFrame-only (R1) và ToM-after-Meaning (R7).

Scaffolding only — stage logic được hiện thực ở các task sau.
"""

# Re-export the legacy meaning layer so that `from cortex.meaning import
# MeaningLayer` keeps resolving after meaning.py was moved into this package
# (src/cortex/meaning/meaning_layer.py). MeaningLayerResult is defined in
# cortex.contracts and re-exported here for backward compatibility.
from .meaning_layer import MeaningLayer, MeaningLayerResult

# Facade Phase 2: wiring toàn bộ pipeline meaning theo đúng thứ tự bắt buộc và
# cưỡng chế ToM-after-Meaning. Đặt trong module riêng (``pipeline.py``) để tránh
# phình __init__.py và tránh vấn đề thứ tự import.
from .pipeline import Phase2MeaningPipeline

__all__ = ["MeaningLayer", "MeaningLayerResult", "Phase2MeaningPipeline"]
