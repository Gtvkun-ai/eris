"""Compatibility shim for the removed local daydream adapter."""


class RuntimeDaydreamModelAdapter:
    @classmethod
    def from_env(cls, *, logger=None):
        if logger is not None:
            try:
                logger.info("RuntimeDaydreamModelAdapter is disabled; using llm_service style client.")
            except Exception:
                pass
        return None
