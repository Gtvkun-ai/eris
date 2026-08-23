# Eris secrets setup

File can dien tren may moi la:

```text
config\secrets.json
```

Khong dien key that vao `config\secrets.example.json`. File example chi la template sach de build/release.

## Cach nhanh

1. Chay `setup_secrets.bat` o thu muc goc Eris.
2. Neu `config\secrets.json` chua co, script se copy tu `config\secrets.example.json`.
3. Notepad se mo file huong dan nay va `config\secrets.json`.
4. Dien key that vao section `api_keys`.
5. Luu file, roi chay lai `run_eris.bat` hoac mo `ErisManager.exe`.

## DeepSeek pool / Whale2API

Mac dinh ban build nay dung DeepSeek pool noi bo qua Whale2API:

```text
ERIS_REMOTE_PROVIDER=deepseek_web
ERIS_DS2API_ENABLED=1
ERIS_DS2API_PORTS=6011,6012,6013,6014,6016
```

Can dien cac gateway key nay de Eris chay dung day:

```text
ERIS_DS_COMPANION_API_KEY
ERIS_DS_SURFACE_API_KEY
ERIS_DS_SEED_API_KEY
ERIS_DS_EXECUTIVE_API_KEY
ERIS_DS_CURATOR_API_KEY
```

Nen dien them cac key nay de cac worker phu khong bi tat:

```text
ERIS_DS_OBSERVER_API_KEY
ERIS_DS_CRITIC_API_KEY
ERIS_DS_INNER_API_KEY
```

`ERIS_DS_CURATOR_API_KEY` la lane "thu thu": don rac memory va gom/tom tat identity. `ERIS_DS_RESEARCH_API_KEY` da nghi huu, dung `CURATOR` thay cho research.
`ERIS_DS_CRITIC_API_KEY` cung gom viec repair/format/style/speech rescue; khong can tao key `STYLE` rieng.

Pool UI mac dinh:

```text
http://127.0.0.1:5010
POOL_UI_ADMIN_TOKEN=123456
```

### Cach tao pool DeepSeek cho nguoi khong dev

1. Chay `run_deepseek_pool_ui.bat` hoac bam `DeepSeek pool UI` trong Manager.
2. Dang nhap bang `123456`.
3. Bam `+ Tao moi`.
4. O `Ten Pool`, dat dung role can tao:

```text
companion
surface
seed
executive
curator
observer
critic
inner
```

5. Bam `Tao moi`.
6. Chon pool vua tao, bam `Nhap CSV`.
7. CSV phai co dang:

```csv
email,password
email1@example.com,password1
email2@example.com,password2
```

Khi chay `run_deepseek_pool_ui.bat`, Eris tu tao san file mau:

```text
tools\whale2api\accounts.template.csv
```

Mo file nay, thay `email1@example.com,password1` bang account DeepSeek that, luu lai, roi trong Pool UI chon `Nhap CSV`.
Khong dat file that la `accounts.csv` trong ban release/cong khai; file account that chi nam tren may user.

8. Bam `Check nick song`.
9. Neu co nick loi, bam `Vo hieu nick loi`.
10. Pool UI se tu tao Gateway Key cho pool do. Lap lai cho cac role can dung.
11. Quay ve Manager, bam `Apply DeepSeek pool keys`.

`Apply DeepSeek pool keys` se doc database cua Pool UI, tu nhan ten pool theo role, va dien cac `ERIS_DS_*_API_KEY` vao `config\secrets.json`. Neu tool bao "chua nhan ra role", doi ten pool/remark thanh mot trong cac role o tren roi chay lai.

## Neu khong dung Whale2API

Neu muon dung API DeepSeek official thay vi pool local:

```text
ERIS_REMOTE_PROVIDER=deepseek
ERIS_DS2API_ENABLED=0
DEEPSEEK_API_KEY=<key official>
```

Co the dien `DEEPSEEK_API_KEY` hoac `ERIS_REMOTE_API_KEY`.

## Voice / ElevenLabs

Voice la tuy chon. Neu chua co key, de:

```text
ERIS_TTS_ENABLED=0
```

Khi muon bat voice/pool ElevenLabs thi dien cac muc lien quan:

```text
ERIS_SPEECH_API_KEY
ELEVENLABS_BEARER_TOKEN
ELEVENLABS_EMAIL
ELEVENLABS_REFRESH_TOKEN
FIREBASE_API_KEY
```

### Cach them ElevenLabs account vao pool

1. Chay `setup_secrets.bat`, dien `FIREBASE_API_KEY` vao `config\secrets.json`.
2. Chay `run_elevenlabs_pool_ui.bat` hoac bam `ElevenLabs pool UI` trong Manager.
3. Web se mo tai `http://127.0.0.1:18888`.
4. Bam `+ Them Account`.
5. Dan `refresh_token` vao o `Refresh Token(s)`.
6. Co the dan nhieu token, moi dong mot token.
7. Bam `Luu & Dong Bo Quota`.
8. Neu dong bo loi "Thieu FIREBASE_API_KEY", quay lai `config\secrets.json` dien key Firebase truoc.

Ghi nho: `FIREBASE_API_KEY` dien mot lan trong secrets. `refresh_token` cua tung ElevenLabs account thi dan vao ElevenLabs Pool UI.

## Luu y release

Ban release khong nen chua cac file nay:

```text
.env
config\secrets.json co key that
config\elevenlabs_pool.db
tools\whale2api\accounts.csv
tools\whale2api\data\*.db
```

Neu build tu may dev, `_fullbuild.py --profile release` se chi copy template/housing setup, khong copy key va database ca nhan.
