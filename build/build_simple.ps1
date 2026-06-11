# build\build_simple.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Tao ban chay thu ERIS khong dung PyInstaller.
# - Compile Python source thanh .pyc (ma hoa co ban), xoa .py goc.
# - Copy src/, config/, model gguf, .env.example, log dir.
# - Tester can Python 3.10+ + pip install requirements.txt.
# - KHONG can Ollama, KHONG can llama-server.
#
# Chay tu goc repo:
#   powershell -ExecutionPolicy Bypass -File build\build_simple.ps1
#
# Tham so:
#   -Out <duong dan>   Thu muc dau ra (mac dinh: C:\Users\Gtvkun\Documents\eris)
# ─────────────────────────────────────────────────────────────────────────────
param(
    [string]$Out = "C:\Users\Gtvkun\Documents\eris"
)

$ErrorActionPreference = "Stop"
$Repo  = Split-Path -Parent $PSScriptRoot
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "[build] Repo   : $Repo"
Write-Host "[build] Output : $Out"
Write-Host ""

# ── 0. Dọn hoặc tạo thư mục đích ─────────────────────────────────────────────
if (Test-Path $Out) {
    Write-Host "[build] Xoa thu muc cu: $Out"
    Remove-Item -Recurse -Force $Out
}
New-Item -ItemType Directory -Path $Out | Out-Null

# ── 1. Copy src/ rồi compile .py → .pyc ──────────────────────────────────────
$SrcDst = Join-Path $Out "src"
Write-Host "[build] Copy src/ ..."
Copy-Item -Recurse -Force (Join-Path $Repo "src") $Out

Write-Host "[build] Compile .py -> .pyc (compileall) ..."
python -m compileall -q -b "$SrcDst"

Write-Host "[build] Xoa file .py goc (giu lai .pyc) ..."
Get-ChildItem -Recurse -Filter "*.py" "$SrcDst" | Where-Object {
    # Giu lai vision.py: la entry point ma Godot goi truc tiep bang 'python src/vision.py'
    $_.Name -ne "vision.py"
} | Remove-Item -Force

# Giu lai __init__.py rong (can cho import package, pyc cua no la __init__.pyc)
# -> thuc ra compileall da tao __init__.pyc, nen xoa .py luon cung dc. Giu lai cho an toan.
Get-ChildItem -Recurse -Filter "__init__.py" "$SrcDst" | ForEach-Object {
    # Phuc hoi neu da xoa o buoc tren
    if (!(Test-Path $_.FullName)) {
        New-Item -ItemType File $_.FullName | Out-Null
    }
}

# ── 2. KHÔNG ship embedding model (paraphrase-multilingual-MiniLM-L12-v2)
#    Model này ~8GB torch weights, quá nặng cho bản beta.
#    Memory recall sẽ fallback về rule-based (vẫn chạy được, recall kém hơn).
#    Tester muốn full embedding thì tự pip install transformers torch và đặt
#    ERIS_EMBEDDING_MODEL trong .env.
Write-Host "[build] Bo qua embedding model (qua nang ~8GB). Memory recall dung fallback."

# ── 3. Config mẫu (KHÔNG ship secrets) ───────────────────────────────────────
$CfgDst = Join-Path $Out "config"
New-Item -ItemType Directory -Path $CfgDst | Out-Null
Copy-Item -Force (Join-Path $Repo "config\secrets.example.json") (Join-Path $CfgDst "secrets.example.json")
Write-Host "[build] Config: chi ship secrets.example.json. Tester tu copy + dien key."

# ── 4. .env — copy sẵn (không chứa key thật), tester chỉ cần điền GEMINI_API_KEY ──
Copy-Item -Force (Join-Path $Repo ".env.example") (Join-Path $Out ".env")
Copy-Item -Force (Join-Path $Repo ".env.example") (Join-Path $Out ".env.example")
Write-Host "[build] .env da copy san. Tester chi can dien GEMINI_API_KEY vao .env."

# ── 5. requirements.txt ───────────────────────────────────────────────────────
Copy-Item -Force (Join-Path $Repo "requirements.txt") (Join-Path $Out "requirements.txt")

# ── 6. Tao thu muc runtime state (memory_core/, logs/) de tranh loi khi chay ──
foreach ($dir in @("memory_core", "logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Out $dir) | Out-Null
}
# Placeholder de git / zip khong bo trong
"" | Out-File (Join-Path $Out "memory_core\.keep") -Encoding utf8
"" | Out-File (Join-Path $Out "logs\.keep") -Encoding utf8

# ── 7. README ngắn cho tester ─────────────────────────────────────────────────
$Readme = @"
# ERIS — Ban chay thu $Stamp

## Yeu cau
- Python 3.10+  (khuyen Python 3.12)
- Godot 4.6 .NET  (de chay body)
- NVIDIA GPU CUDA  (neu khong co: doi ERIS_LLAMACPP_N_GPU_LAYERS=0 trong .env)

## Cai dependencies
  pip install -r requirements.txt

  # llama-cpp-python co GPU (khuyen):
  #   Xem README chinh de biet cach build CUDA.
  # llama-cpp-python chi CPU:
  pip install llama-cpp-python

## Cau hinh
1. Copy config\secrets.example.json  ->  config\secrets.json
2. Dien GEMINI_API_KEY vao hai cho:
   - config\secrets.json  (truong "GEMINI_API_KEY")
   - .env                 (dong GEMINI_API_KEY=)
   Chi can dien 1 trong 2 cung duoc; secrets.json duoc doc truoc.

## Chay
- Dung Godot editor: mo du an, nhan Run.
- Hoac chay runtime rieng de debug:
    set PYTHONPATH=src
    set ERIS_PROJECT_ROOT=%CD%
    python src\vision.py
"@
$Readme | Out-File (Join-Path $Out "README_TESTER.txt") -Encoding utf8

# ── 8. Tong ket ───────────────────────────────────────────────────────────────
$TotalMB = [math]::Round((Get-ChildItem -Recurse $Out | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "=========================================="
Write-Host "[build] HOAN THANH: $Out"
Write-Host "[build] Kich thuoc: ~${TotalMB} MB (chua tinh gguf)"
Write-Host ""
Write-Host "VIEC CON LAI CUA BAN:"
Write-Host "  1. Copy 3 file gguf vao $Out\src\"
Write-Host "     - qwen3-1.7b-q4_k_m.gguf    (~1 GB)"
Write-Host "     - moondream2-q4_k.gguf       (~877 MB)"
Write-Host "     - moondream2-mmproj-f16.gguf (~868 MB)"
Write-Host "  2. Export Godot body vao $Out (Eris.exe + Eris.pck)"
Write-Host "  3. Giao cho tester: tu dien key vao config\secrets.json"
Write-Host "=========================================="
