"""Compatibility shim for the removed local sensory adapter."""


class RuntimeSensoryModelAdapter:
    @classmethod
    def from_env(cls, *, logger=None):
        if logger is not None:
            try:
                logger.info("RuntimeSensoryModelAdapter is disabled; using rule-based observer.")
            except Exception:
                pass
        return None
