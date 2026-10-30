"""Files excluded from the Python runtime payload in full and patch builds."""

from shutil import ignore_patterns


source_copy_ignore = ignore_patterns(
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "src.zip", "*.bak", "*.patch", "*.diff", "*.tsbuildinfo",
)
