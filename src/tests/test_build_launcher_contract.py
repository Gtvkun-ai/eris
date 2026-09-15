from __future__ import annotations

from pathlib import Path


def test_generated_launcher_exits_without_holding_a_console() -> None:
    build_script = Path(__file__).resolve().parents[2] / "_fullbuild.py"
    source = build_script.read_text(encoding="utf-8")

    assert "start \"Eris Runtime\" cmd /k" not in source
    assert "\"pause\"," not in source
    assert "exit /b 0" in source
    assert "pythonw.exe" in source
