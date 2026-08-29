$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$GitPilot = Join-Path $Here '.venv\Scripts\gitpilot.exe'

if (-not (Test-Path $GitPilot)) {
    throw 'Chưa có .venv GitPilot. Chạy setup_eris_code_backend.ps1 trước.'
}

# Backend chỉ bind local; Eris Desktop không được launch từ script này.
& $GitPilot serve --port 8000
