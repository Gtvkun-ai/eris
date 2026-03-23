import logging
import sys
# app_logging.py là một module để cấu hình và quản lý logging trong ứng dụng,
#  nó định nghĩa một CategoryFormatter để định dạng các bản ghi log với một trường category
#  tùy chỉnh, một hàm configure_logging để thiết lập cấu hình logging với mức độ log cụ thể,
#  và một hàm get_logger để tạo và trả về một LoggerAdapter với category được chỉ định,
#  cho phép phân loại và tổ chức các bản ghi log theo category một cách hiệu quả.

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
