$ErrorActionPreference = 'Stop'

# V78: tạo venv riêng ngay cạnh source GitPilot được vendored/submodule trong Eris.
# Nhờ vậy Eris Code chạy đúng source đang patch, không phụ thuộc một bản PyPI cũ
# vô tình có sẵn trên PATH.
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Here '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path $Python)) {
    py -3.12 -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e $Here

Write-Host ''
Write-Host 'GitPilot V78 backend ready.' -ForegroundColor Green
Write-Host "Run: $Python -m gitpilot.cli serve --port 8000"
