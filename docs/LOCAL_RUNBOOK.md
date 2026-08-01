# Eris Local Runbook

Muc tieu cua runbook nay: dua repo tu clone/local folder sang trang thai co the kiem tra trong vai phut.

## 1. Bootstrap

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Neu ban chi muon smoke test re tien, dung preset:

```powershell
Copy-Item .\env-examples\.env.local-smoke.example .\.env -Force
```

Sau do dien mot key model vao `.env` hoac `config\secrets.json`.

## 2. Kiem Tra Moi Truong

```powershell
.\run_doctor.bat
```

Doctor chi in trang thai co/thieu. Gia tri key luon bi an.

## 3. Chay Test Nhanh

```powershell
.\run_smoke_test.bat
```

Lenh nay chay nhom test runtime/readiness/settings/provider nho, dung de biet repo con dung duoc khong.

## 4. Chay Runtime

```powershell
.\run_runtime.bat
```

Godot body la lop hien thi rieng. Mo `project.godot` bang Godot 4 .NET neu can body UI.

## 5. Key Can Co

Toi thieu can mot trong cac key sau:

```text
DEEPSEEK_API_KEY
ERIS_REMOTE_API_KEY
GEMINI_API_KEY
OPENAI_API_KEY
ERIS_GROQ_API_KEY
```

TTS la tuy chon. Neu chua co voice key, dat:

```text
ERIS_TTS_ENABLED=0
```

DS2API/Whale2API cung la tuy chon. Neu khong chay gateway local, dat:

```text
ERIS_DS2API_ENABLED=0
```
