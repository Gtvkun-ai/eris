@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

rem Script nằm trong <project>\src. Project root là thư mục cha.
set "SRC_DIR=%~dp0"
for %%I in ("%SRC_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "CANONICAL_BODY=%PROJECT_ROOT%\body"
set "DUP_BODY=%SRC_DIR%body"

echo [V60.1] Project root : %PROJECT_ROOT%
echo [V60.1] Body chuẩn    : %CANONICAL_BODY%
echo [V60.1] Body trùng    : %DUP_BODY%
echo.

if not exist "%CANONICAL_BODY%\UdpListener.cs" (
  echo [ABORT] Không tìm thấy body\UdpListener.cs ở project root.
  echo Script sẽ KHÔNG xóa src\body vì chưa chứng minh được đâu là Body chuẩn.
  exit /b 2
)

if not exist "%DUP_BODY%" (
  echo [OK] Không còn src\body. Không cần dọn duplicate Body.
  goto :fixtures
)

set "STAMP=%RANDOM%_%RANDOM%"
set "BACKUP=%PROJECT_ROOT%\_backup_src_body_v60_1_%STAMP%"
echo [V60.1] Backup src\body -> %BACKUP%
move "%DUP_BODY%" "%BACKUP%" >nul
if errorlevel 1 (
  echo [ERROR] Không backup/move được src\body. Không tiếp tục.
  exit /b 3
)
echo [OK] Đã loại src\body khỏi đường compile. Backup vẫn còn ở:
echo      %BACKUP%

:fixtures
rem Nếu máy còn bản fixture .cs cũ từ lần giải nén trước, đổi đuôi để compiler bỏ qua.
set "FIXTURE_DIR=%SRC_DIR%integration\body_contracts"
for %%F in ("UdpListener.MemoryPanel.cs" "UdpListener.SettingsPanel.cs") do (
  if exist "%FIXTURE_DIR%\%%~F" (
    if not exist "%FIXTURE_DIR%\%%~F.fixture.txt" (
      move "%FIXTURE_DIR%\%%~F" "%FIXTURE_DIR%\%%~F.fixture.txt" >nul
      echo [OK] Đổi fixture %%~F -> %%~F.fixture.txt
    ) else (
      del /q "%FIXTURE_DIR%\%%~F"
      echo [OK] Xóa fixture .cs cũ %%~F vì bản .fixture.txt đã tồn tại.
    )
  )
)

echo.
echo [DONE] Đã dọn các nguồn C# trùng nằm trong src.
echo Nếu IDE vẫn hiện lỗi cũ, đóng Godot/VS Code, xóa cache build .godot\mono nếu cần rồi mở lại.
exit /b 0
