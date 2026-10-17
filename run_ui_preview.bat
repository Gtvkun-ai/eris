@echo off
setlocal
cd /d "%~dp0"
set "ERIS_UI_GODOT=%~dp0scratch\ui-qa\godot\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64.exe"
if not exist "%ERIS_UI_GODOT%" (
    echo Khong tim thay Godot .NET trong scratch\ui-qa\godot.
    echo Mo tools\ui-preview\companion_preview.tscn bang Godot .NET va nhan F6.
    pause
    exit /b 1
)
start "" "%ERIS_UI_GODOT%" --path "%~dp0." --scene "res://tools/ui-preview/companion_preview.tscn" -- %*
