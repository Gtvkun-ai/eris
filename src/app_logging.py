import logging
import sys


class CategoryFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "category"):
            record.category = record.name
        return super().format(record)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CategoryFormatter("[%(category)s][%(levelname)s] %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(category: str) -> logging.LoggerAdapter:
    logger = logging.getLogger(category)
    return logging.LoggerAdapter(logger, {"category": category})
