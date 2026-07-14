$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Không tìm thấy Python venv tại $Python"
}

& $Python -m pip install --upgrade rapidocr-onnxruntime
Write-Host "Đã cài RapidOCR. Khởi động lại Eris để Screen Text Index nhận backend." -ForegroundColor Green
