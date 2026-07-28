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
    "paraphrase-multilingual-MiniLM-L12-v2",
    "embedding_model",
    "tests",
    "tools",
    ".pytest_cache",
    ".github",
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
            fn.endswith(".md") or
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
    (os.path.join(REPO, "src", "settings", "runtime_settings.json"),
     os.path.join(OUT,  "src", "settings", "runtime_settings.json")),
]

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

# Deploy whale2api binary and config to build directory if present
ds2api_src = os.path.join(REPO, "tools", "whale2api")
ds2api_dst = os.path.join(OUT, "tools", "whale2api")
if os.path.exists(ds2api_src):
    print("  Deploying whale2api binary and config to build...")
    os.makedirs(ds2api_dst, exist_ok=True)
    for fn in ["whale2api.exe", "poolui.exe", ".env", "accounts.csv", "whale2api.db", "whale2api.db-shm", "whale2api.db-wal"]:
        src_file = os.path.join(ds2api_src, fn)
        if os.path.exists(src_file):
            shutil.copy2(src_file, os.path.join(ds2api_dst, fn))
            print("  [OK] whale2api " + fn)

# Tao run_eris.bat dung venv 3.14/3.12 (inject PATH truoc khi launch)
bat_path = os.path.join(OUT, "run_eris.bat")
venv_scripts = os.path.dirname(VENV_PY)   # .venv\Scripts trong REPO
bat_content = (
    "@echo off\r\n"
    "REM Launcher Eris -- inject venv Python " + sys.version.split()[0] + " vao PATH\r\n"
    "REM .pyc trong build duoc compile boi chinh venv nay (magic " + exp_magic.hex().upper() + ")\r\n"
    "set \"PATH=" + venv_scripts + ";%PATH%\"\r\n"
    "cd /d \"%~dp0\"\r\n"
    "if exist \"%~dp0Eris.exe\" (\r\n"
    "    start \"\" \"%~dp0Eris.exe\"\r\n"
    ") else (\r\n"
    "    \"" + VENV_PY + "\" \"%~dp0src\\vision.py\"\r\n"
    ")\r\n"
)
with open(bat_path, "w", encoding="ascii") as fh:
    fh.write(bat_content)
print("  [OK] run_eris.bat  (inject venv " + sys.version.split()[0] + ")")

if not all_deploy_ok:
    print("[!] Mot so file deploy bi thieu.")
    sys.exit(1)

# ── 5. Sanity check ───────────────────────────────────────────────────────────
banner("5 / 5  --  Sanity check")

must_exist = [
    os.path.join(OUT, "src",    "vision.py"),
    os.path.join(OUT, "src",    "actions",  "__init__.pyc"),
    os.path.join(OUT, "src",    "llm",      "client.pyc"),
    os.path.join(OUT, "src",    "llm",      "key_pool.pyc"),
    os.path.join(OUT, "src",    "llm",      "process_manager.pyc"),
    os.path.join(OUT, "src",    "runtime",  "coordinator.pyc"),
    os.path.join(OUT, ".env"),
    os.path.join(OUT, "config", "secrets.json"),
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

