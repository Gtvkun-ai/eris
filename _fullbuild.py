"""
_fullbuild.py -- One-click build Eris: moi .py -> .pyc, deploy sang build dir.

Chay bang VENV cua du an (bat buoc):
    & ".venv\\Scripts\\python.exe" _fullbuild.py

Bai hoc ghi nho:
    LUON build bang venv cua du an, KHONG dung 'python' tran trong PATH.
    Python 3.14.3 venv -> magic 2B0E.
    run_eris.bat inject venv vao PATH -> interpreter khop -> OK.
    Dung python 3.13 Anaconda compile -> magic F30D -> bad magic -> crash.
"""

import compileall
import hashlib
import os
import shutil
import sys

# ── Config ────────────────────────────────────────────────────────────────────
REPO    = os.path.dirname(os.path.abspath(__file__))
OUT     = os.path.normpath(os.path.join("C:\\", "Users", "Gtvkun", "Documents", "eris"))
VENV_PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")

# .py duoc giu lai trong build (Godot launch truc tiep file nay)
KEEP_PY = {"vision.py"}

# Thu muc qua nang / khong can ship
SKIP_HEAVY = {
    ".pytest_cache",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def banner(msg):
    sep = "=" * 58
    print("\n" + sep + "\n  " + msg + "\n" + sep)

def md5_short(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]

def count_ext(root, ext):
    total = 0
    for _, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(ext):
                total += 1
    return total

# ── Guard: phai chay bang dung venv ──────────────────────────────────────────
banner("Guard  --  kiem tra Python interpreter")

if not os.path.isfile(VENV_PY):
    print("[!] Khong tim thay venv: " + VENV_PY)
    print("    Tao venv: python -m venv .venv  &&  .venv\\Scripts\\pip install -r requirements.txt")
    sys.exit(1)

cur = os.path.normcase(os.path.abspath(sys.executable))
exp = os.path.normcase(os.path.abspath(VENV_PY))

if cur != exp:
    print("[!] Sai Python interpreter!")
    print("    Current  : " + sys.executable)
    print("    Expected : " + VENV_PY)
    print("")
    print('    Chay lai : & "' + VENV_PY + '" _fullbuild.py')
    sys.exit(1)

print("[OK] Python " + sys.version.split()[0] + "  --  " + sys.executable)

# ── 1. Xoa src/ cu, copy moi tu repo ─────────────────────────────────────────
banner("1 / 5  --  Copy src/ tu repo")

src_repo  = os.path.join(REPO, "src")
src_build = os.path.join(OUT, "src")

def remove_readonly(func, path, _):
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

if os.path.exists(src_build):
    print("  Xoa src/ cu trong build...")
    shutil.rmtree(src_build, onerror=remove_readonly)

print("  Copy: " + src_repo + "  ->  " + src_build)
shutil.copytree(src_repo, src_build, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", ".pytest_cache"))

for skip in SKIP_HEAVY:
    p = os.path.join(src_build, skip)
    if os.path.exists(p):
        shutil.rmtree(p, onerror=remove_readonly)
        print("  Skip (heavy): " + skip)

n_py_before = count_ext(src_build, ".py")
print("  File .py truoc compile: " + str(n_py_before))

# ── 2. Compile TOAN BO .py -> .pyc (legacy: .pyc dat canh .py) ───────────────
banner("2 / 5  --  Compile .py -> .pyc  [Python " + sys.version.split()[0] + "]")

import importlib.util
exp_magic = importlib.util.MAGIC_NUMBER[:2]
print("  Magic bytes (venv " + sys.version.split()[0] + "): " + exp_magic.hex().upper())

ok = compileall.compile_dir(
    src_build,
    force=True,
    quiet=1,       # 1 = chi hien loi, khong spam tung file
    legacy=True,   # -b: dat .pyc canh .py (khong vao __pycache__)
    optimize=0,
)

if not ok:
    print("[!] compileall bao loi -- kiem tra output phia tren.")
    sys.exit(1)

n_pyc = count_ext(src_build, ".pyc")
print("  Compile xong: " + str(n_pyc) + " file .pyc")

# ── 3. Xoa .py goc (giu vision.py) va cac file dev/doc thua ──────────────────
banner("3 / 5  --  Xoa .py goc va file dev/doc thua  (giu: " + ", ".join(sorted(KEEP_PY)) + ")")

removed_py = 0
removed_dev = 0
for dp, _, fns in os.walk(src_build):
    for fn in fns:
        fp = os.path.join(dp, fn)
        # Giu lai vision.py, xoa cac file .py khac
        if fn.endswith(".py"):
            if fn not in KEEP_PY:
                os.remove(fp)
                removed_py += 1
        # Xoa cac file tai lieu, batch va config dev trong src
        elif (
            (fn.endswith(".md") and fn != "SKILL.md") or
            fn.endswith(".bat") or
            fn.endswith(".toml") or
            fn.endswith(".ini") or
            fn.startswith("requirements-") or
            fn in {".gitignore", ".gitattributes"}
        ):
            os.remove(fp)
            removed_dev += 1

print("  Da xoa: " + str(removed_py) + " file .py")
print("  Da xoa: " + str(removed_dev) + " file dev/doc (.md, .bat, .toml, .ini, .gitignore)")
print("  Con lai: " + str(count_ext(src_build, ".py")) + " file .py  (vision.py)")

# Xoa __pycache__ thua (legacy .pyc dat canh file, __pycache__ khong can)
cleaned = 0
for dp, dirs, _ in os.walk(src_build, topdown=False):
    for d in list(dirs):
        if d == "__pycache__":
            shutil.rmtree(os.path.join(dp, d))
            cleaned += 1
print("  Xoa " + str(cleaned) + " thu muc __pycache__/")

# ── 4. Ep copy .env + secrets.json + Eris.exe + tao run_eris.bat dung ──────────
banner("4 / 5  --  Deploy .env + config/secrets.json + run_eris.bat")

deploy_pairs = [
    (os.path.join(REPO, ".env"),
     os.path.join(OUT,  ".env")),
    (os.path.join(REPO, "config", "secrets.json"),
     os.path.join(OUT,  "config", "secrets.json")),
    (os.path.join(REPO, "config", "elevenlabs_pool.db"),
     os.path.join(OUT,  "config", "elevenlabs_pool.db")),
    (os.path.join(REPO, "run_elevenlabs_pool_ui.bat"),
     os.path.join(OUT,  "run_elevenlabs_pool_ui.bat")),
    (os.path.join(REPO, "setup_gemini_login.bat"),
     os.path.join(OUT,  "setup_gemini_login.bat")),
    (os.path.join(REPO, "src", "settings", "runtime_settings.json"),
     os.path.join(OUT,  "src", "settings", "runtime_settings.json")),
]

# Copy optional root memory files if present in REPO
for mem_fn in ["long_term_memory.json", "goal_memory.json", "goal_profiles.json"]:
    src_mem = os.path.join(REPO, mem_fn)
    if os.path.isfile(src_mem):
        deploy_pairs.append((src_mem, os.path.join(OUT, mem_fn)))

# Copy Eris.exe / Eris.pck if built in REPO
for binary_fn in ["Eris.exe", "Eris.pck"]:
    src_bin = os.path.join(REPO, binary_fn)
    if os.path.isfile(src_bin):
        deploy_pairs.append((src_bin, os.path.join(OUT, binary_fn)))

all_deploy_ok = True
for src, dst in deploy_pairs:
    if not os.path.isfile(src):
        print("  [MISSING] " + src)
        all_deploy_ok = False
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print("  [OK] " + os.path.basename(dst) + "  md5=" + md5_short(dst))

# Tao _start_webai.bat -- helper khoi dong WebAI-to-API (co buoc sync cookie tu gemini.json)
webai_src = os.path.join(REPO, "tools", "WebAI-to-API")
webai_dst = os.path.join(OUT, "tools", "WebAI-to-API")
if os.path.exists(webai_src):
    print("  Deploying WebAI-to-API to build...")
    shutil.copytree(webai_src, webai_dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))

start_webai_path = os.path.join(OUT, "_start_webai.bat")
start_webai_content = (
    "@echo off\r\n"
    "cd /d \"%~dp0tools\\WebAI-to-API\"\r\n"
    "set PYTHONUTF8=1\r\n"
    "set PYTHONIOENCODING=utf-8\r\n"
    "set \"HF_HOME=%~dp0.cache\\huggingface\"\r\n"
    "set \"XDG_CACHE_HOME=%~dp0.cache\"\r\n"
    "set \"ERIS_AGENT_SERVICE_DISCOVERY=%~dp0.eris_state\\agent_service.json\"\r\n"
    "set \"ERIS_HOME=%~dp0.eris_home\"\r\n"
    "set \"ERIS_STATE_DIR=%~dp0.eris_state\"\r\n"
    "\r\n"
    "echo [WebAI] Syncing cookies from gemini.json...\r\n"
    "\"%~dp0.venv\\Scripts\\python.exe\" _sync_webai_cookies.py\r\n"
    "\r\n"
    "echo [WebAI] Starting server on port 8081...\r\n"
    "\"%~dp0.venv\\Scripts\\python.exe\" src\\run.py --host 0.0.0.0 --port 8081\r\n"
)
with open(start_webai_path, "wb") as fh:
    fh.write(start_webai_content.encode("ascii"))
print("  [OK] _start_webai.bat  (WebAI launcher helper + cookie sync + portable env)")

# Deploy embedding_model directory to build directory if present
embed_src = os.path.join(REPO, "embedding_model")
embed_dst = os.path.join(OUT, "embedding_model")
if os.path.exists(embed_src):
    print("  Deploying embedding_model to build...")
    try:
        shutil.copytree(embed_src, embed_dst, dirs_exist_ok=True)
        print("  [OK] embedding_model deployed")
    except Exception as exc:
        print("  [SKIP] embedding_model copy failed: " + str(exc))

# Deploy memory_core directory to build directory if present
mem_core_src = os.path.join(REPO, "memory_core")
mem_core_dst = os.path.join(OUT, "memory_core")
if os.path.exists(mem_core_src):
    print("  Deploying memory_core directory to build...")
    try:
        shutil.copytree(mem_core_src, mem_core_dst, dirs_exist_ok=True)
        print("  [OK] memory_core directory deployed")
    except Exception as exc:
        print("  [NOTICE] memory_core file(s) locked by running process; copying un-locked files...")
        for root, dirs, files in os.walk(mem_core_src):
            rel_path = os.path.relpath(root, mem_core_src)
            dest_dir = os.path.join(mem_core_dst, rel_path) if rel_path != "." else mem_core_dst
            os.makedirs(dest_dir, exist_ok=True)
            for f in files:
                sf = os.path.join(root, f)
                df = os.path.join(dest_dir, f)
                try:
                    shutil.copy2(sf, df)
                except PermissionError:
                    pass
        print("  [OK] memory_core deployed (skipped locked files)")

# Deploy whale2api binary and config to build directory if present
ds2api_src = os.path.join(REPO, "tools", "whale2api")
ds2api_dst = os.path.join(OUT, "tools", "whale2api")
if os.path.exists(ds2api_src):
    print("  Deploying whale2api binary and config to build...")
    os.makedirs(ds2api_dst, exist_ok=True)
    for fn in ["whale2api.exe", "poolui.exe", ".env", "accounts.csv", "whale2api.db", "whale2api.db-shm", "whale2api.db-wal"]:
        src_file = os.path.join(ds2api_src, fn)
        if os.path.exists(src_file):
            try:
                shutil.copy2(src_file, os.path.join(ds2api_dst, fn))
                print("  [OK] whale2api " + fn)
            except (PermissionError, OSError):
                print("  [SKIP] whale2api " + fn + "  (file dang bi lock boi process dang chay -- skip)")

# Copy .venv to build output
venv_src = os.path.join(REPO, ".venv")
venv_dst = os.path.join(OUT, ".venv")
if os.path.exists(venv_src):
    print("  Deploying .venv (Python Environment) to build... This may take a while.")
    shutil.copytree(venv_src, venv_dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "pip-cache"))
    print("  [OK] .venv deployed")

# ── 4b. Deploy cline-bridge (build truoc, copy ca dist/ + node_modules) ──────
banner("4b/5  --  Deploy cline-bridge (Cline SDK sidecar)")

cline_src  = os.path.join(REPO, "cline-bridge")
cline_dst  = os.path.join(OUT,  "cline-bridge")

if os.path.exists(cline_src):
    # Buoc 1: build TypeScript -> dist/ (phai co node trong PATH)
    import subprocess
    node_ok = False
    try:
        node_ver = subprocess.check_output(["node", "--version"], stderr=subprocess.STDOUT, cwd=cline_src).decode().strip()
        print("  [OK] node " + node_ver)
        node_ok = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("  [WARN] node not found in PATH -- skipping cline-bridge build step")
        print("  [INFO] Machine can dich can cai Node.js >= 22")

    if node_ok:
        print("  Building cline-bridge (npm run build)...")
        build_result = subprocess.run(
            ["npm", "run", "build"],
            cwd=cline_src,
            capture_output=True,
            text=True,
            shell=True,
        )
        if build_result.returncode == 0:
            print("  [OK] cline-bridge build OK")
        else:
            print("  [WARN] cline-bridge build exit=" + str(build_result.returncode))
            print("  " + (build_result.stderr or build_result.stdout)[:400])

    # Buoc 2: copy toan bo cline-bridge sang build (bao gom node_modules + dist)
    print("  Copying cline-bridge -> build... (190MB node_modules, co the mat 1-2 phut)")
    shutil.copytree(
        cline_src, cline_dst,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "src", "tsconfig.json", "*.ts"),
    )
    print("  [OK] cline-bridge deployed (dist/ + node_modules/ + package.json)")
else:
    print("  [SKIP] cline-bridge directory not found: " + cline_src)

# ── 4c. Deploy .eris/ (steering files, specs) ────────────────────────────────
banner("4c/5  --  Deploy .eris/ (steering + specs)")

eris_cfg_src = os.path.join(REPO, ".eris")
eris_cfg_dst = os.path.join(OUT,  ".eris")

if os.path.exists(eris_cfg_src):
    shutil.copytree(eris_cfg_src, eris_cfg_dst, dirs_exist_ok=True)
    # Dem files
    n_steering = len(list(p for p in (eris_cfg_dst + "/steering").split() if os.path.exists(p))) if False else 0
    try:
        n_steering = sum(1 for _ in os.scandir(os.path.join(eris_cfg_dst, "steering"))) if os.path.exists(os.path.join(eris_cfg_dst, "steering")) else 0
        n_specs    = sum(1 for _ in os.scandir(os.path.join(eris_cfg_dst, "specs")))    if os.path.exists(os.path.join(eris_cfg_dst, "specs"))    else 0
    except Exception:
        n_steering = n_specs = 0
    print("  [OK] .eris/ deployed  (steering files: " + str(n_steering) + "  specs: " + str(n_specs) + ")")
else:
    print("  [SKIP] .eris/ not found in repo (se tao moi o may dich khi can)")

# ── 4d. Deploy eris_setup.py + pool scripts ──────────────────────────────────
banner("4d/5  --  Deploy setup wizard & pool scripts")

ROOT_COPY = [
    "eris_setup.py",
    "_setup_gemini_pool_auth.bat",
    "_start_gemini_pool.bat",
    "run_gemini_web2api.bat",
    "run_manager.bat",
]
for fn in ROOT_COPY:
    src_f = os.path.join(REPO, fn)
    dst_f = os.path.join(OUT, fn)
    if os.path.exists(src_f):
        shutil.copy2(src_f, dst_f)
        print("  [OK] " + fn)
    else:
        print("  [SKIP] " + fn + " not found")

# Generate run_eris.bat cho build output (CRLF, dung _start_webai.bat helper)

bat_path     = os.path.join(OUT, "run_eris.bat")
start_webai  = os.path.join(OUT, "_start_webai.bat")  # da tao o tren
venv_scripts = os.path.dirname(VENV_PY)

bat_lines = [
    "@echo off",
    "REM run_eris.bat -- AUTO-GENERATED by _fullbuild.py, DO NOT EDIT",
    "REM Python " + sys.version.split()[0] + "  magic=" + exp_magic.hex().upper(),
    "setlocal enabledelayedexpansion",
    "chcp 65001 >nul",
    "title Eris Launcher",
    "cd /d \"%~dp0\"",
    "",
    "set \"VENV_PY=%~dp0.venv\\Scripts\\python.exe\"",
    "set \"PATH=%~dp0.venv\\Scripts;%PATH%\"",
    "set \"HF_HOME=%~dp0.cache\\huggingface\"",
    "set \"XDG_CACHE_HOME=%~dp0.cache\"",
    "set \"ERIS_AGENT_SERVICE_DISCOVERY=%~dp0.eris_state\\agent_service.json\"",
    "set \"ERIS_HOME=%~dp0.eris_home\"",
    "set \"ERIS_STATE_DIR=%~dp0.eris_state\"",
    "",
    "echo.",
    "echo  ===============================================",
    "echo    ERIS - AUTO LAUNCHER",
    "echo  ===============================================",
    "echo.",
    "",
    ":: Python",
    "set \"PYTHON=%VENV_PY%\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=python\"",
    "echo [INFO] Python: %PYTHON%",
    "",
    ":: Step 1: Check / Start WebAI-to-API :8081",
    "echo.",
    "echo [STEP 1/3] Checking port 8081...",
    "netstat -ano | findstr \":8081\" | findstr \"LISTENING\" >nul 2>nul",
    "if %ERRORLEVEL% == 0 (",
    "    echo [OK]   WebAI-to-API already running on :8081",
    "    goto START_ERIS",
    ")",
    "",
    "echo [INFO]  Port 8081 free -- starting WebAI-to-API...",
    "if not exist \"%~dp0_start_webai.bat\" (",
    "    echo [ERROR] _start_webai.bat not found!",
    "    pause",
    "    exit /b 1",
    ")",
    "start \"WebAI-to-API\" cmd /k \"%~dp0_start_webai.bat\"",
    "",
    ":: Step 1b: Start cline-bridge sidecar",
    "if exist \"%~dp0cline-bridge\\dist\\bridge.js\" (",
    "    echo [INFO]  Starting cline-bridge sidecar...",
    "    start \"Cline Bridge\" cmd /c \"node \"%~dp0cline-bridge\\dist\\bridge.js\"\" ",
    "    timeout /t 1 /nobreak >nul",
    ") else (",
    "    echo [WARN]  cline-bridge not found -- Cline features unavailable",
    ")",
    "",
    "",
    ":: Step 2: Wait for server (max 50s)",
    "echo [STEP 2/3] Waiting for server (max 50s)...",
    "set /a R=0",
    ":WAIT_LOOP",
    "    timeout /t 2 /nobreak >nul",
    "    netstat -ano | findstr \":8081\" | findstr \"LISTENING\" >nul 2>nul",
    "    if %ERRORLEVEL% == 0 goto SERVER_READY",
    "    set /a R+=1",
    "    if !R! geq 25 (",
    "        echo [WARN]  Timeout -- proceeding anyway.",
    "        goto START_ERIS",
    "    )",
    "    echo [INFO]  Waiting !R!/25...",
    "    goto WAIT_LOOP",
    "",
    ":SERVER_READY",
    "echo [OK]   WebAI-to-API UP at http://localhost:8081",
    "",
    ":: Step 3: Start Eris",
    ":START_ERIS",
    "echo.",
    "echo [STEP 3/3] Starting Eris...",
    "if exist \"%~dp0Eris.exe\" (",
    "    echo [INFO]  Launching Eris.exe...",
    "    start \"Eris Runtime\" \"%~dp0Eris.exe\"",
    ") else (",
    "    echo [INFO]  Eris.exe not found -- launching Python runtime...",
    "    start \"Eris Runtime\" cmd /k \"set PYTHONUTF8=1 & \"%PYTHON%\" \"%~dp0src\\vision.py\"\"",
    ")",
    "",
    "echo.",
    "echo  [DONE] Tat ca da khoi dong!",
    "echo  WebAI UI: http://localhost:8081/ui",
    "echo.",
    "start \"\" \"http://localhost:8081/ui\"",
    "pause",
]
bat_content_crlf = "\r\n".join(bat_lines) + "\r\n"
with open(bat_path, "wb") as fh:
    fh.write(bat_content_crlf.encode("ascii"))
print("  [OK] run_eris.bat  (generated CRLF, venv " + sys.version.split()[0] + ")")

if not all_deploy_ok:
    print("[!] Mot so file deploy bi thieu.")
    sys.exit(1)

# ── 5. Sanity check ───────────────────────────────────────────────────────────
banner("5 / 5  --  Sanity check")

must_exist = [
    os.path.join(OUT, "src",          "vision.py"),
    os.path.join(OUT, "src",          "actions",  "__init__.pyc"),
    os.path.join(OUT, "src",          "llm",      "client.pyc"),
    os.path.join(OUT, "src",          "llm",      "key_pool.pyc"),
    os.path.join(OUT, "src",          "llm",      "process_manager.pyc"),
    os.path.join(OUT, "src",          "runtime",  "coordinator.pyc"),
    os.path.join(OUT, ".env"),
    os.path.join(OUT, "config",       "secrets.json"),
    os.path.join(OUT, "cline-bridge", "dist",     "bridge.js"),
]

all_ok = True
for p in must_exist:
    exists = os.path.isfile(p)
    tag    = "OK " if exists else "MISSING"
    print("  [" + tag + "] " + os.path.relpath(p, OUT))
    if not exists:
        all_ok = False

# Eris.exe check (optional GUI host)
eris_exe_path = os.path.join(OUT, "Eris.exe")
if os.path.isfile(eris_exe_path):
    print("  [OK ] Eris.exe")
else:
    print("  [NOTICE] Eris.exe (Godot GUI executable missing; run_eris.bat will launch Python runtime directly)")

# Magic number check
sample_pyc = os.path.join(OUT, "src", "actions", "__init__.pyc")
if os.path.isfile(sample_pyc):
    with open(sample_pyc, "rb") as fh:
        actual_magic = fh.read(2)
    match = actual_magic == exp_magic
    print("\n  Magic check: " + actual_magic.hex().upper() +
          " == " + exp_magic.hex().upper() +
          "  =>  " + ("OK" if match else "MISMATCH!"))
    if not match:
        print("  [!] Magic mismatch! .pyc bi compile boi Python khac.")
        all_ok = False

# Tong ket
print("")
if all_ok:
    sep = "=" * 58
    print(sep)
    print("  BUILD THANH CONG")
    print("  Output : " + OUT)
    print("  Python : " + sys.version.split()[0])
    print("  Chay   : " + os.path.join(OUT, "run_eris.bat"))
    print(sep)
else:
    print("[!] BUILD CO VAN DE -- xem log phia tren.")
    sys.exit(1)

