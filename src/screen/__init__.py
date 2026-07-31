from .evidence_models import (
    ActiveWindowInfo,
    PendingVisionEscalation,
    ScreenRouteDecision,
    ScreenTextBlock,
    ScreenTextSnapshot,
)
from .screen_anaphora_rescue import ScreenAnaphoraResolution, ScreenAnaphoraRescue
from .screen_evidence_store import ScreenEvidenceStore
from .screen_relevance_router import ScreenRelevanceRouter


def build_screen_text_runtime(*, logger=None):
    """Lazy import worker để test/Linux thiếu mss vẫn import được policy/store."""
    store = ScreenEvidenceStore()
    router = ScreenRelevanceRouter(store)
    try:
        from .ocr_worker import IncrementalScreenTextWorker
        worker = IncrementalScreenTextWorker(store, logger=logger)
    except Exception as exc:
        class _DisabledWorker:
            enabled = False
            def start(self):
                return None
            def stop(self):
                return None
        worker = _DisabledWorker()
        if logger is not None:
            try:
                logger.warning("[screen text] worker unavailable: %s", exc)
            except Exception:
                pass
    return store, worker, router


__all__ = [
    "ActiveWindowInfo",
    "PendingVisionEscalation",
    "ScreenRouteDecision",
    "ScreenTextBlock",
    "ScreenTextSnapshot",
    "ScreenAnaphoraResolution",
    "ScreenAnaphoraRescue",
    "ScreenEvidenceStore",
    "ScreenRelevanceRouter",
    "build_screen_text_runtime",
]
