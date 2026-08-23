@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "HUONG_DAN_NGUOI_DUNG.md" start "" notepad "HUONG_DAN_NGUOI_DUNG.md"
if exist "VIDEO_GUIDE_POOL_SETUP_VI.md" start "" notepad "VIDEO_GUIDE_POOL_SETUP_VI.md"
exit /b 0
