# ERIS

ERIS lÃ  má»™t hiá»‡n diá»‡n desktop (desktop companion) cháº¡y trÃªn Godot: pháº§n thÃ¢n (body)
váº½ báº±ng Godot/C#, pháº§n nháº­n thá»©c (cortex/runtime) viáº¿t báº±ng Python. Body vÃ  runtime
nÃ³i chuyá»‡n vá»›i nhau qua UDP. Cognition dÃ¹ng cÃ¡c model qua API miá»…n phÃ­ (Gemini / Groq),
cÃ³ cÆ¡ cháº¿ **xoay vÃ²ng nhiá»u key** Ä‘á»ƒ táº­n dá»¥ng free quota.

> Báº£n beta. Cáº§n chuáº©n bá»‹ key API free cá»§a riÃªng báº¡n (xem pháº§n Cáº¥u hÃ¬nh key).

---

## 1. YÃªu cáº§u

| ThÃ nh pháº§n | PhiÃªn báº£n | Ghi chÃº |
|---|---|---|
| Godot | 4.6 (báº£n **.NET / C#**) | Cháº¡y pháº§n body. Pháº£i lÃ  báº£n Mono/.NET, khÃ´ng pháº£i báº£n standard. |
| .NET SDK | 8.0+ | Äá»ƒ Godot build C#. |
| Python | 3.10+ (Ä‘Ã£ test trÃªn 3.13) | Cháº¡y pháº§n cortex/runtime. |
| OS | Windows | Runtime dÃ¹ng `mss`, `uiautomation`, `msvcrt` (hiá»‡n bÃ¡m Windows). |

Báº¡n cÅ©ng cáº§n Ã­t nháº¥t má»™t **Gemini API key** (báº¯t buá»™c) vÃ  tÃ¹y chá»n thÃªm **Groq API key**.
Cáº£ hai Ä‘á»u cÃ³ báº­c miá»…n phÃ­.

---

## 2. CÃ i Ä‘áº·t

### 2.1. Láº¥y mÃ£ nguá»“n
```powershell
git clone <repo-url> eris
cd eris
```

### 2.2. MÃ´i trÆ°á»ng Python
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` chá»‰ liá»‡t kÃª cÃ¡c lib runtime cá»‘t lÃµi (`mss`, `Pillow`, `psutil`,
`requests`, `uiautomation`). Pháº§n embedding/semantic dÃ¹ng model
`paraphrase-multilingual-MiniLM-L12-v2` (Ä‘Ã£ kÃ¨m trong repo) qua `transformers` + `torch`.
Náº¿u import bÃ¡o thiáº¿u, cÃ i thÃªm:
```powershell
pip install transformers torch
```

### 2.3. Build phÃ­a Godot
Má»Ÿ thÆ° má»¥c dá»± Ã¡n báº±ng **Godot 4.6 .NET**. Láº§n Ä‘áº§u Godot sáº½ tá»± khÃ´i phá»¥c NuGet vÃ 
build assembly `Eris`. Náº¿u build C# lá»—i, kiá»ƒm tra .NET SDK Ä‘Ã£ cÃ i Ä‘Ãºng.

### 2.4. Model runtime

GGUF / llama-cpp local inference has been removed. ERIS now uses remote providers for the main brain and private-mind fragment lanes. Ollama can still be used as a separate server-backed option for observer/tutor experiments, but there is no in-process GGUF backend in this repo.


---

## 3. Cáº¥u hÃ¬nh key (quan trá»ng)

ERIS Ä‘á»c key tá»« `config/secrets.json`. File nÃ y **Ä‘Ã£ Ä‘Æ°á»£c .gitignore** nÃªn sáº½ khÃ´ng
bá»‹ commit. Táº¡o nÃ³ tá»« file máº«u:

```powershell
copy config\secrets.example.json config\secrets.json
```

Rá»“i má»Ÿ `config/secrets.json` vÃ  dÃ¡n key tháº­t vÃ o.

### Láº¥y key free
- **Gemini** (báº¯t buá»™c): táº¡o key táº¡i Google AI Studio. Má»—i key thuá»™c má»™t Google
  project khÃ¡c nhau, má»—i project cÃ³ hÅ© free quota riÃªng.
- **Groq** (tÃ¹y chá»n, dÃ¹ng cho máº¡ch "private mind" / viá»‡c cáº§n JSON chuáº©n): táº¡o key táº¡i
  Groq Console.

### VÃ¬ sao nÃªn dÃ¡n NHIá»€U key
Free tier tÃ­nh theo **project**, khÃ´ng theo key. ERIS giá»¯ má»™t pool key dÃ¹ng chung cho
má»i máº¡ch gá»i; khi má»™t key dÃ­nh lá»—i `429` (háº¿t quota táº¡m thá»i) nÃ³ **tá»± xoay sang key káº¿
tiáº¿p**. CÃ ng nhiá»u key thuá»™c cÃ¡c project/tÃ i khoáº£n khÃ¡c nhau â†’ free quota tá»•ng cÃ ng lá»›n,
ERIS cÃ ng Ã­t bá»‹ "cÃ¢m".

- Key Gemini chÃ­nh: `api_keys.ERIS_REMOTE_API_KEY`
- CÃ¡c key Gemini dá»± phÃ²ng (xoay vÃ²ng): thÃªm vÃ o máº£ng `api_keys.ERIS_PRIVATE_MIND_FALLBACK_API_KEYS`
- Key Groq chÃ­nh + dá»± phÃ²ng: `api_keys.ERIS_GROQ_API_KEY` vÃ  `api_keys.ERIS_GROQ_FALLBACK_API_KEYS`

CÃ¡c giÃ¡ trá»‹ báº¯t Ä‘áº§u báº±ng `PASTE_` Ä‘Æ°á»£c coi lÃ  placeholder vÃ  bá»‹ bá» qua, nÃªn cá»© Ä‘á»ƒ
nguyÃªn slot nÃ o chÆ°a dÃ¹ng.

> Tinh chá»‰nh thÃªm (nhá»‹p nÃ³i, timeout, vision...) cÃ³ thá»ƒ Ä‘áº·t qua biáº¿n mÃ´i trÆ°á»ng â€”
> xem máº«u trong `.env.example`. Env sáº½ override `secrets.json`.

---

## 4. Cháº¡y

### CÃ¡ch thÆ°á»ng: qua Godot
Báº¥m **Run** trong Godot (main scene). Khi body khá»Ÿi Ä‘á»™ng, nÃ³ tá»± spawn tiáº¿n trÃ¬nh
Python runtime (`src/vision.py`) vÃ  inject env cáº§n thiáº¿t. Body â†” runtime trao Ä‘á»•i qua
UDP **cá»•ng 4242** (decision vá» body) vÃ  **4243** (event/chat lÃªn runtime).

### CÃ¡ch thá»§ cÃ´ng: cháº¡y runtime riÃªng (Ä‘á»ƒ debug)
```powershell
$env:PYTHONPATH = "src"
python src\vision.py
```
Há»¯u Ã­ch khi muá»‘n xem log cortex/LLM mÃ  khÃ´ng phá»¥ thuá»™c Godot.

---

## 5. Cháº¡y test
```powershell
python run_tests.py
```
hoáº·c trá»±c tiáº¿p:
```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/ -q
```

---

## 6. Xá»­ lÃ½ sá»± cá»‘

| Triá»‡u chá»©ng | Kiá»ƒm tra |
|---|---|
| ERIS khÃ´ng nÃ³i gÃ¬ | Key sai/háº¿t quota. Xem log máº¡ch `LLM`. ThÃªm key dá»± phÃ²ng vÃ o pool. |
| Body hiá»‡n nhÆ°ng khÃ´ng pháº£n há»“i | Runtime Python chÆ°a cháº¡y hoáº·c UDP 4242/4243 bá»‹ cháº·n (firewall). |
| `ModuleNotFoundError` khi cháº¡y test | ChÆ°a set `PYTHONPATH=src`, hoáº·c thiáº¿u dependency. |
| Build C# fail trong Godot | Thiáº¿u .NET SDK, hoáº·c Ä‘ang dÃ¹ng báº£n Godot khÃ´ng pháº£i .NET. |
| Import lá»—i vá» embedding/torch | `pip install transformers torch`. |

---

## 7. LÆ°u Ã½ cho beta

- **KhÃ´ng bao giá» commit `config/secrets.json` hay `.env`** â€” cáº£ hai Ä‘Ã£ náº±m trong
  `.gitignore`. Chá»‰ chia sáº» `config/secrets.example.json`.
- Náº¿u gá»­i build cho ngÆ°á»i khÃ¡c, tuyá»‡t Ä‘á»‘i khÃ´ng kÃ¨m file key cá»§a báº¡n; má»—i tester nÃªn
  tá»± táº¡o key free riÃªng.
- CÃ¡c file state runtime (`memory_core/`, `long_term_memory.json`, ...) lÃ  dá»¯ liá»‡u cÃ¡
  nhÃ¢n cá»§a tá»«ng láº§n cháº¡y, khÃ´ng nÃªn commit.

---

## 8. Curiosity Tutor (gia sÆ° web â€” tÃ¹y chá»n, máº·c Ä‘á»‹nh Táº®T)

ERIS cÃ³ thá»ƒ tá»± "Ä‘i há»i gia sÆ°" khi gáº·p lá»— hiá»ƒu biáº¿t: khi má»™t vi pháº¡m ká»³ vá»ng
(`SituationModel`) hoáº·c má»™t tÃ¬nh huá»‘ng mÃ n hÃ¬nh khÃ´ng phÃ¢n loáº¡i Ä‘Æ°á»£c xuáº¥t hiá»‡n, ERIS hÃ¬nh
thÃ nh cÃ¢u há»i (báº±ng **local LLM**), **má»Ÿ má»™t cá»­a sá»• trÃ¬nh duyá»‡t tháº­t** tá»›i
`gemini.google.com` báº±ng tÃ i khoáº£n Google Ä‘Äƒng nháº­p sáºµn, gÃµ cÃ¢u há»i nhÆ° ngÆ°á»i, rá»“i chÆ°ng
cáº¥t cÃ¢u tráº£ lá»i thÃ nh claim Ä‘Æ°a vÃ o trÃ­ nhá»› ngá»¯ nghÄ©a. ÄÃ´i khi ERIS sáº½ tá»± nhiÃªn "khoe"
Ä‘iá»u vá»«a há»c báº±ng giá»ng cá»§a chÃ­nh nÃ³ (cÃ³ tiáº¿t cháº¿). ToÃ n bá»™ cháº¡y ngoÃ i hot path.

> âš ï¸ **Rá»§i ro cáº§n biáº¿t.** Tá»± Ä‘á»™ng hÃ³a tÃ i khoáº£n Google tiÃªu dÃ¹ng **vi pháº¡m ToS cá»§a
> Google** vÃ  tÃ i khoáº£n **cÃ³ thá»ƒ bá»‹ khÃ³a**. Cá»­a sá»• Gemini tháº­t cÃ³ thá»ƒ **lá»™ email/tab
> khÃ¡c** trÃªn mÃ n hÃ¬nh. Máº·c Ä‘á»‹nh tÃ­nh nÄƒng **Táº®T**; chá»‰ báº­t náº¿u báº¡n cháº¥p nháº­n rá»§i ro nÃ y.

### 8.1. CÃ i Playwright (chá»‰ khi dÃ¹ng Tutor)
```powershell
pip install playwright
playwright install chromium
```

### 8.2. ÄÄƒng nháº­p profile má»™t láº§n (báº±ng tay) â€” Báº®T BUá»˜C
ÄÃ£ cÃ³ sáºµn script. Cháº¡y **má»™t láº§n**:
```powershell
python tutor_login.py
```
Cá»­a sá»• Chromium má»Ÿ `gemini.google.com` vá»›i profile bá»n vá»¯ng
(`C:\Users\Gtvkun\Documents\eris_tutor_profile`). ÄÄƒng nháº­p Google trong cá»­a sá»• Ä‘Ã³, rá»“i
quay láº¡i terminal nháº¥n Enter Ä‘á»ƒ lÆ°u phiÃªn. Tá»« Ä‘Ã³ ERIS dÃ¹ng láº¡i phiÃªn nÃ y.

> Náº¿u chÆ°a Ä‘Äƒng nháº­p, lÆ°á»£t há»i Ä‘áº§u sáº½ tháº¥y mÃ n login/captcha â†’ Tutor **táº¡m ngÆ°ng** (khÃ´ng
> tá»± vÆ°á»£t) cho tá»›i khi báº¡n Ä‘Äƒng nháº­p tay; nÃ³ khÃ´ng spam tÃ i khoáº£n.

### 8.3. Báº­t trong `.env`
```dotenv
ERIS_TUTOR_ENABLED=1
ERIS_TUTOR_PROFILE_DIR=C:\eris_tutor_profile
ERIS_TUTOR_LOCAL_MODEL=qwen3:1.7b
```
CÃ¡c tinh chá»‰nh khÃ¡c (nhá»‹p há»i, tráº§n/giá», selector, táº§n suáº¥t khoe) xem `.env.example`.

### 8.4. LÆ°u viá»‡c lÆ°u claim
Máº·c Ä‘á»‹nh ERIS sáº½ **há»i + diá»…n cáº£nh** nhÆ°ng **chÆ°a lÆ°u claim** cho tá»›i khi Ä‘Æ°á»ng commit
vÃ o trÃ­ nhá»› Ä‘Æ°á»£c ná»‘i (adapter `tutor_ingest_fn`). ÄÃ¢y lÃ  bÆ°á»›c cá»‘ tÃ¬nh Ä‘á»ƒ ngá» vÃ¬ ghi vÃ o
trÃ­ nhá»› dÃ i háº¡n lÃ  thao tÃ¡c nháº¡y cáº£m â€” gáº¯n má»™t callable `tutor_ingest_fn(text, *, source,
gap_id, citations) -> int` lÃªn runtime Ä‘á»ƒ báº­t lÆ°u claim.
