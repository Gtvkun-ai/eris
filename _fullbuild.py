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
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys

# ── Config ────────────────────────────────────────────────────────────────────
REPO    = os.path.dirname(os.path.abspath(__file__))
DEV_OUT = os.path.normpath(os.path.join("C:\\", "Users", "Gtvkun", "Documents", "eris"))
RELEASE_OUT = os.path.normpath(os.path.join("C:\\", "Users", "Gtvkun", "Documents", "eris_release"))
VENV_PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")

# .py duoc giu lai trong build (Godot launch truc tiep file nay)
KEEP_PY = {"vision.py"}

# Thu muc qua nang / khong can ship
SKIP_HEAVY = {
    ".pytest_cache",
}

PRIVATE_FILE_NAMES = {
    ".env",
    "secrets.json",
    "elevenlabs_pool.db",
}

PRIVATE_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
)

PRIVATE_DIR_NAMES = {
    ".cache",
    ".eris_home",
    ".eris_state",
    "__pycache__",
    "logs",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
RELEASE_SRC_PRUNE_DIR_NAMES = {
    "docs",
    "test",
    "tests",
}

RELEASE_NOISE_DIR_NAMES = {
    ".pytest_cache",
    "__pycache__",
    "test",
    "tests",
}

RELEASE_NOISE_FILE_SUFFIXES = (
    ".bak",
    ".log",
    ".tmp",
)

def banner(msg):
    sep = "=" * 58
    print("\n" + sep + "\n  " + msg + "\n" + sep)

def md5_short(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]

def find_whale2api_db(root):
    candidates = [
        os.path.join(root, "tools", "whale2api", "docker-data", "whale2api", "whale2api.db"),
        os.path.join(root, "tools", "whale2api", "whale2api.db"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""

def copy_sqlite_db(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source:
            with sqlite3.connect(dst) as target:
                source.backup(target)
        return
    except sqlite3.Error as exc:
        print("  [WARN] SQLite backup failed; falling back to file copy: " + str(exc))
    shutil.copy2(src, dst)

def load_build_api_keys(secrets_path):
    if not os.path.isfile(secrets_path):
        return {}
    try:
        with open(secrets_path, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    api_keys = payload.get("api_keys") if isinstance(payload, dict) else {}
    return api_keys if isinstance(api_keys, dict) else {}

def verify_deepseek_pool_db(db_path, secrets_path):
    required = {
        "companion": "ERIS_DS_COMPANION_API_KEY",
        "surface": "ERIS_DS_SURFACE_API_KEY",
        "seed": "ERIS_DS_SEED_API_KEY",
        "critic": "ERIS_DS_CRITIC_API_KEY",
        "inner": "ERIS_DS_INNER_API_KEY",
        "observer": "ERIS_DS_OBSERVER_API_KEY",
        "curator": "ERIS_DS_CURATOR_API_KEY",
    }
    api_keys = load_build_api_keys(secrets_path)
    if not api_keys:
        print("  [FAIL] Cannot read DeepSeek api_keys from " + secrets_path)
        sys.exit(1)
    if not os.path.isfile(db_path):
        print("  [FAIL] Missing Whale2API pool DB for dev build: " + db_path)
        sys.exit(1)

    failures = []
    with sqlite3.connect(db_path) as conn:
        for role, secret_name in required.items():
            key = str(api_keys.get(secret_name) or "").strip()
            if not key:
                failures.append(f"{role}: missing {secret_name}")
                continue
            row = conn.execute(
                "SELECT enabled FROM gateway_api_keys WHERE api_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                failures.append(f"{role}: key not registered in gateway pool")
                continue
            if not int(row[0] or 0):
                failures.append(f"{role}: gateway key disabled")
                continue
            active = conn.execute(
                """
                SELECT COUNT(*)
                FROM pool_bindings pb
                JOIN pool_accounts pa ON pa.id = pb.account_id
                WHERE pb.api_key = ? AND COALESCE(pa.discarded, 0) = 0
                """,
                (key,),
            ).fetchone()[0]
            if int(active or 0) <= 0:
                failures.append(f"{role}: no active account bound to gateway key")

    if failures:
        print("  [FAIL] DeepSeek pool DB does not match config\\secrets.json:")
        for item in failures:
            print("    - " + item)
        print("  Run run_deepseek_pool_ui.bat, then apply_deepseek_pool_to_secrets.bat.")
        sys.exit(1)
    print("  [OK] DeepSeek pool DB matches config\\secrets.json")

def count_ext(root, ext):
    total = 0
    for _, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(ext):
                total += 1
    return total

def ensure_portable_python_can_import_src(python_dir):
    pth_path = os.path.join(python_dir, "python312._pth")
    if not os.path.isfile(pth_path):
        print("  [WARN] python312._pth not found; portable Python may not see src/")
        return

    with open(pth_path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    normalized = {line.strip().replace("/", "\\").lower() for line in lines}
    if "..\\src" not in normalized:
        insert_at = 0
        for i, line in enumerate(lines):
            if line.strip().lower() == "import site":
                insert_at = i
                break
        lines.insert(insert_at, "..\\src")
        with open(pth_path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")
        print("  [OK] Patched python312._pth with ..\\src")
    else:
        print("  [OK] python312._pth already includes ..\\src")

def ensure_live2d_dependencies(python_dir):
    python_exe = os.path.join(python_dir, "python.exe")
    requirements = os.path.join(REPO, "requirements-live2d.txt")
    if not os.path.isfile(python_exe):
        print("  [WARN] portable python.exe not found; cannot verify Live2D deps")
        return
    if not os.path.isfile(requirements):
        print("  [WARN] requirements-live2d.txt not found; cannot install Live2D deps")
        return

    probe = "import glfw, live2d.v3"
    check = subprocess.run(
        [python_exe, "-c", probe],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        print("  [OK] Live2D deps available (glfw + live2d-py)")
        return

    print("  [INFO] Live2D deps missing; installing requirements-live2d.txt ...")
    install = subprocess.run(
        [python_exe, "-m", "pip", "install", "-r", requirements],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        print("  [FAIL] Could not install Live2D deps:")
        print("  " + (install.stderr or install.stdout)[-1200:])
        sys.exit(1)

    recheck = subprocess.run(
        [python_exe, "-c", probe],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if recheck.returncode != 0:
        print("  [FAIL] Live2D deps installed but import still fails:")
        print("  " + (recheck.stderr or recheck.stdout)[-1200:])
        sys.exit(1)
    print("  [OK] Live2D deps installed and verified")

def assert_live2d_source_contract(root):
    manager = os.path.join(root, "src", "body", "Live2DBodyManager.cs")
    if not os.path.isfile(manager):
        print("  [FAIL] Missing Live2DBodyManager.cs; cannot validate Live2D runtime launcher")
        sys.exit(1)
    with open(manager, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    required = [
        'Path.Combine(root, "python", "python.exe")',
        'Python (portable runtime)',
        'Renderer launcher',
    ]
    missing = [item for item in required if item not in text]
    if missing:
        print("  [FAIL] Live2D runtime launcher is missing portable-Python guard:")
        for item in missing:
            print("    - " + item)
        sys.exit(1)
    print("  [OK] Live2D source contract: portable Python is preferred in exported runtime")

def newest_mtime(paths):
    newest = 0.0
    newest_path = ""
    for path in paths:
        if os.path.isfile(path):
            mt = os.path.getmtime(path)
            if mt > newest:
                newest = mt
                newest_path = path
        elif os.path.isdir(path):
            for dp, dirs, fns in os.walk(path):
                dirs[:] = [
                    d for d in dirs
                    if d not in {".git", ".pytest_cache", "__pycache__", "node_modules"}
                ]
                for fn in fns:
                    if not fn.endswith((".cs", ".tscn", ".tres", ".gd", ".godot")):
                        continue
                    fp = os.path.join(dp, fn)
                    try:
                        mt = os.path.getmtime(fp)
                    except OSError:
                        continue
                    if mt > newest:
                        newest = mt
                        newest_path = fp
    return newest, newest_path

def assert_godot_pack_fresh(pack_path):
    if not os.path.isfile(pack_path):
        return
    source_mtime, source_path = newest_mtime([
        os.path.join(REPO, "Eris.csproj"),
        os.path.join(REPO, "project.godot"),
        os.path.join(REPO, "src", "body"),
        os.path.join(REPO, "src", "scenes"),
    ])
    if not source_mtime:
        return
    pack_mtime = os.path.getmtime(pack_path)
    if pack_mtime + 2 < source_mtime:
        print("  [FAIL] Eris.pck is older than runtime source:")
        print("    pck   : " + pack_path)
        print("    source: " + source_path)
        print("  Re-export the Godot C# runtime before running _fullbuild.py.")
        sys.exit(1)
    print("  [OK] Eris.pck freshness check")

def find_godot_export_file(filename):
    candidates = [
        os.path.join(REPO, filename),
        os.path.join(DEV_OUT, filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""

def _godot_dotnet_required_files(data_dir):
    return [
        os.path.join(data_dir, "Eris.dll"),
        os.path.join(data_dir, "Eris.deps.json"),
        os.path.join(data_dir, "Eris.runtimeconfig.json"),
        os.path.join(data_dir, "GodotSharp.dll"),
    ]

def is_godot_dotnet_export_dir(path):
    if not os.path.isdir(path):
        return False
    return all(os.path.isfile(fp) for fp in _godot_dotnet_required_files(path))

def find_godot_dotnet_export_dir():
    roots = [REPO, DEV_OUT]
    preferred_names = [
        "data_Eris_windows_x86_64",
        "data_Eris.console_windows_x86_64",
    ]
    for root in roots:
        for name in preferred_names:
            path = os.path.join(root, name)
            if is_godot_dotnet_export_dir(path):
                return path
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if not name.lower().startswith("data_eris"):
                continue
            path = os.path.join(root, name)
            if is_godot_dotnet_export_dir(path):
                return path
    return ""

def deploy_godot_dotnet_export_dir():
    src_dir = find_godot_dotnet_export_dir()
    if not src_dir:
        print("  [MISSING] Godot .NET export data dir (data_Eris_windows_x86_64)")
        return False

    dst_dir = os.path.join(OUT, os.path.basename(src_dir))
    try:
        if os.path.exists(dst_dir) and not os.path.samefile(src_dir, dst_dir):
            shutil.rmtree(dst_dir, onerror=remove_readonly)
        if not os.path.exists(dst_dir):
            shutil.copytree(src_dir, dst_dir)
    except OSError as exc:
        print("  [FAIL] Godot .NET export data dir copy failed: " + str(exc))
        return False

    dll_count = count_ext(dst_dir, ".dll")
    print("  [OK] " + os.path.basename(dst_dir) + f"  dlls={dll_count}  md5(Eris.dll)=" + md5_short(os.path.join(dst_dir, "Eris.dll")))
    return True

def validate_godot_dotnet_output():
    if not os.path.isfile(os.path.join(OUT, "Eris.exe")):
        return True
    candidates = []
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):
            if name.lower().startswith("data_eris"):
                candidates.append(os.path.join(OUT, name))
    for data_dir in candidates:
        if is_godot_dotnet_export_dir(data_dir):
            print("  [OK ] Godot .NET assemblies: " + os.path.basename(data_dir))
            return True
    print("  [MISSING] Godot .NET assemblies beside Eris.exe")
    print("            Expected data_Eris_windows_x86_64 with Eris.dll/.deps.json/.runtimeconfig.json/GodotSharp.dll")
    return False

def prune_named_dirs(root, names):
    removed = 0
    if not os.path.isdir(root):
        return removed
    wanted = {name.lower() for name in names}
    for dp, dirs, _ in os.walk(root, topdown=True):
        for d in list(dirs):
            if d.lower() in wanted:
                shutil.rmtree(os.path.join(dp, d), onerror=remove_readonly)
                dirs.remove(d)
                removed += 1
    return removed

def strip_release_noise(root):
    if not IS_RELEASE or not os.path.isdir(root):
        return
    removed_files = 0
    removed_dirs = prune_named_dirs(root, RELEASE_NOISE_DIR_NAMES)
    for dp, _, fns in os.walk(root):
        for fn in fns:
            lower = fn.lower()
            if lower.endswith(RELEASE_NOISE_FILE_SUFFIXES):
                try:
                    os.remove(os.path.join(dp, fn))
                    removed_files += 1
                except OSError:
                    pass
    print(f"  [OK] Release noise stripped: removed_files={removed_files} removed_dirs={removed_dirs}")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Build Eris dev/release outputs without mixing private runtime data.",
    )
    parser.add_argument(
        "--profile",
        choices=("dev", "release"),
        default="dev",
        help="dev = fast local build with private config; release = clean user staging.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Override output directory. Defaults: Documents\\eris for dev, Documents\\eris_release for release.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Keep .py sources and skip .pyc stripping.",
    )
    parser.add_argument(
        "--release-compiled",
        action="store_true",
        help="Compatibility flag; release builds compile by default.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Run non-interactively.",
    )
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="Skip Inno Setup packaging.",
    )
    return parser.parse_args()

ARGS = parse_args()
PROFILE = ARGS.profile
IS_RELEASE = PROFILE == "release"
OUT = os.path.normpath(ARGS.output or (RELEASE_OUT if IS_RELEASE else DEV_OUT))
BUILD_INSTALLER = IS_RELEASE and not ARGS.skip_installer

def clean_release_output():
    if not IS_RELEASE or not os.path.exists(OUT):
        return
    out_abs = os.path.abspath(OUT)
    release_abs = os.path.abspath(RELEASE_OUT)
    if out_abs in {
        os.path.abspath(REPO),
        os.path.abspath(DEV_OUT),
        os.path.dirname(os.path.abspath(REPO)),
        os.path.abspath(os.sep),
    }:
        print("[!] Refuse to clean unsafe release output: " + OUT)
        sys.exit(1)
    if not (os.path.basename(out_abs).lower().startswith("eris_release") or out_abs == release_abs):
        print("[!] Refuse to auto-clean custom release output without eris_release name: " + OUT)
        sys.exit(1)
    print("  Clean release staging: " + OUT)
    shutil.rmtree(OUT, onerror=remove_readonly)

def sanitize_release_output():
    if not IS_RELEASE:
        return
    removed_files = 0
    removed_dirs = 0
    for dp, dirs, fns in os.walk(OUT, topdown=True):
        for d in list(dirs):
            if d.lower() in PRIVATE_DIR_NAMES:
                shutil.rmtree(os.path.join(dp, d), onerror=remove_readonly)
                dirs.remove(d)
                removed_dirs += 1
        for fn in fns:
            lower = fn.lower()
            if lower in PRIVATE_FILE_NAMES or lower.endswith(PRIVATE_SUFFIXES) or lower.endswith(".bak"):
                try:
                    os.remove(os.path.join(dp, fn))
                    removed_files += 1
                except OSError:
                    pass
    print(f"  [OK] Release sanitized: removed_private_files={removed_files} removed_private_dirs={removed_dirs}")

def ensure_release_env_template():
    if not IS_RELEASE:
        return
    src = os.path.join(REPO, ".env")
    source_name = ".env"
    if not os.path.isfile(src):
        src = os.path.join(OUT, ".env.example")
        source_name = ".env.example"
    dst = os.path.join(OUT, ".env")
    if not os.path.isfile(src):
        print("  [WARN] Cannot create release .env; missing repo .env and .env.example")
        return
    secret_name_markers = (
        "api_key",
        "apikey",
        "secret",
        "password",
        "bearer",
        "access_token",
        "refresh_token",
        "auth_token",
    )
    suspicious = []
    with open(src, "r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name_l = name.strip().lower()
            value = value.strip().strip("\"'")
            if not value:
                continue
            if any(marker in name_l for marker in secret_name_markers):
                suspicious.append(name.strip())
    if suspicious:
        print("  [FAIL] Refusing to ship release .env with non-empty secret-like values:")
        for name in suspicious:
            print("    - " + name)
        print("  Move secrets to config\\secrets.json or leave these .env values blank before release.")
        sys.exit(1)
    shutil.copy2(src, dst)
    print("  [OK] Release .env copied from " + source_name)

def build_manager_exe():
    spec_path = os.path.join(REPO, "ErisManager.spec")
    manager_src = os.path.join(REPO, "src", "manager_gui.py")
    if not os.path.isfile(manager_src):
        print("  [WARN] manager_gui.py not found; skipping ErisManager.exe")
        return
    if not os.path.isfile(spec_path):
        print("  [WARN] ErisManager.spec not found; skipping ErisManager.exe")
        return

    print("  Building ErisManager.exe...")
    res = subprocess.run(
        [VENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean", spec_path],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print("  [FAIL] ErisManager.exe build failed:")
        print("  " + (res.stderr or res.stdout)[-1200:])
        sys.exit(1)
    built_exe = os.path.join(REPO, "dist", "ErisManager.exe")
    if not os.path.isfile(built_exe):
        print("  [FAIL] PyInstaller finished but dist\\ErisManager.exe is missing")
        sys.exit(1)
    print("  [OK] ErisManager.exe built in dist\\")

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
print("[OK] Profile: " + PROFILE + "  ->  " + OUT)

if not ARGS.yes:
    ch = input("\nBat dau build profile '" + PROFILE + "'? [y/n]: ").strip().lower()
    if ch != 'y':
        print("Huy build.")
        sys.exit(0)

if ARGS.debug:
    is_debug = True
elif IS_RELEASE:
    # Release mac dinh la ban dong goi cho user: compile .pyc va strip source.
    # Dung --debug neu can mot release staging de trace loi.
    is_debug = False
else:
    if ARGS.yes:
        is_debug = True
    else:
        raw_debug = input("Build ban Debug/fast (giu nguyen ma nguon .py)? [Y/n]: ").strip().lower()
        is_debug = (raw_debug or "y") == "y"

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

clean_release_output()

if os.path.exists(src_build):
    print("  Xoa src/ cu trong build...")
    shutil.rmtree(src_build, onerror=remove_readonly)

print("  Copy: " + src_repo + "  ->  " + src_build)
shutil.copytree(src_repo, src_build, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", ".pytest_cache"))
assert_live2d_source_contract(OUT)
if IS_RELEASE:
    pruned_src_dirs = prune_named_dirs(src_build, RELEASE_SRC_PRUNE_DIR_NAMES)
    print("  [OK] Release src pruned dirs: " + str(pruned_src_dirs))

for skip in SKIP_HEAVY:
    p = os.path.join(src_build, skip)
    if os.path.exists(p):
        shutil.rmtree(p, onerror=remove_readonly)
        print("  Skip (heavy): " + skip)

n_py_before = count_ext(src_build, ".py")
print("  File .py truoc compile: " + str(n_py_before))

# ── 2. Compile TOAN BO .py -> .pyc (legacy: .pyc dat canh .py) ───────────────
if not is_debug:
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
else:
    import importlib.util
    exp_magic = importlib.util.MAGIC_NUMBER[:2]
    print("  [DEBUG MODE] Bo qua compile .pyc")

# ── 3. Xoa .py goc (giu vision.py) va cac file dev/doc thua ──────────────────
if not is_debug:
    banner("3 / 5  --  Xoa .py goc va file dev/doc thua  (giu: " + ", ".join(sorted(KEEP_PY)) + ")")
else:
    banner("3 / 5  --  Xoa cac file dev/doc thua (Giu nguyen toan bo ma nguon .py)")

removed_py = 0
removed_dev = 0
for dp, _, fns in os.walk(src_build):
    for fn in fns:
        fp = os.path.join(dp, fn)
        # Giu lai vision.py, xoa cac file .py khac
        if fn.endswith(".py"):
            if not is_debug and fn not in KEEP_PY:
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
banner("4 / 5  --  Deploy runtime files + run_eris.bat")

build_manager_exe()

deploy_pairs = [
    (os.path.join(REPO, "run_elevenlabs_pool_ui.bat"),
     os.path.join(OUT,  "run_elevenlabs_pool_ui.bat")),
    (os.path.join(REPO, "run_deepseek_pool_ui.bat"),
     os.path.join(OUT,  "run_deepseek_pool_ui.bat")),
    (os.path.join(REPO, "setup_gemini_login.bat"),
     os.path.join(OUT,  "setup_gemini_login.bat")),
    (os.path.join(REPO, "src", "settings", "runtime_settings.json"),
     os.path.join(OUT,  "src", "settings", "runtime_settings.json")),
]

if IS_RELEASE:
    deploy_pairs.extend([
        (os.path.join(REPO, ".env.example"),
         os.path.join(OUT,  ".env.example")),
        (os.path.join(REPO, "config", "secrets.example.json"),
         os.path.join(OUT,  "config", "secrets.example.json")),
    ])
else:
    deploy_pairs.extend([
        (os.path.join(REPO, ".env"),
         os.path.join(OUT,  ".env")),
        (os.path.join(REPO, "config", "secrets.json"),
         os.path.join(OUT,  "config", "secrets.json")),
        (os.path.join(REPO, "config", "elevenlabs_pool.db"),
         os.path.join(OUT,  "config", "elevenlabs_pool.db")),
    ])

# Copy optional root config files if present in REPO
for mem_fn in ["goal_profiles.json"]:
    src_mem = os.path.join(REPO, mem_fn)
    if os.path.isfile(src_mem):
        deploy_pairs.append((src_mem, os.path.join(OUT, mem_fn)))

# Copy Eris.exe / Eris.pck if built in REPO
for binary_fn in ["Eris.exe", "Eris.pck"]:
    src_bin = find_godot_export_file(binary_fn)
    if os.path.isfile(src_bin):
        if binary_fn == "Eris.pck":
            assert_godot_pack_fresh(src_bin)
        deploy_pairs.append((src_bin, os.path.join(OUT, binary_fn)))
    else:
        print("  [MISSING] " + binary_fn + " (looked in repo root and " + DEV_OUT + ")")

manager_exe = os.path.join(REPO, "dist", "ErisManager.exe")
if os.path.isfile(manager_exe):
    deploy_pairs.append((manager_exe, os.path.join(OUT, "ErisManager.exe")))
    deploy_pairs.append((manager_exe, os.path.join(OUT, "ErisSetup.exe")))

all_deploy_ok = True
for src, dst in deploy_pairs:
    if not os.path.isfile(src):
        print("  [MISSING] " + src)
        all_deploy_ok = False
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.samefile(src, dst):
        print("  [OK] " + os.path.basename(dst) + "  md5=" + md5_short(dst))
        continue
    shutil.copy2(src, dst)
    print("  [OK] " + os.path.basename(dst) + "  md5=" + md5_short(dst))

if os.path.isfile(os.path.join(OUT, "Eris.exe")):
    all_deploy_ok = deploy_godot_dotnet_export_dir() and all_deploy_ok



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
if IS_RELEASE:
    os.makedirs(mem_core_dst, exist_ok=True)
    with open(os.path.join(mem_core_dst, ".gdignore"), "w", encoding="utf-8") as fh:
        fh.write("")
    print("  [OK] memory_core scaffold created (release excludes local memory)")
elif os.path.exists(mem_core_src):
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
    # Release khong ship accounts.csv/.env/*.db. Dev build sync DB rieng va verify ben duoi.
    for fn in ["whale2api.exe", "poolui.exe", "accounts.example.csv"]:
        src_file = os.path.join(ds2api_src, fn)
        if os.path.exists(src_file):
            try:
                shutil.copy2(src_file, os.path.join(ds2api_dst, fn))
                print("  [OK] whale2api " + fn)
            except (PermissionError, OSError):
                print("  [SKIP] whale2api " + fn + "  (file dang bi lock boi process dang chay -- skip)")
    if not IS_RELEASE:
        ds2api_db_src = find_whale2api_db(REPO)
        ds2api_db_dst = os.path.join(ds2api_dst, "docker-data", "whale2api", "whale2api.db")
        if not ds2api_db_src:
            print("  [FAIL] Dev build needs Whale2API pool DB but none was found in repo tools\\whale2api.")
            print("  Run run_deepseek_pool_ui.bat and apply_deepseek_pool_to_secrets.bat first.")
            sys.exit(1)
        copy_sqlite_db(ds2api_db_src, ds2api_db_dst)
        print("  [OK] whale2api pool DB synced  md5=" + md5_short(ds2api_db_dst))
        verify_deepseek_pool_db(
            ds2api_db_dst,
            os.path.join(OUT, "config", "secrets.json"),
        )

tool_helper_src = os.path.join(REPO, "tools", "open_url_when_ready.ps1")
tool_helper_dst = os.path.join(OUT, "tools", "open_url_when_ready.ps1")
if os.path.exists(tool_helper_src):
    os.makedirs(os.path.dirname(tool_helper_dst), exist_ok=True)
    shutil.copy2(tool_helper_src, tool_helper_dst)
    print("  [OK] tools\\open_url_when_ready.ps1")

ds_pool_apply_src = os.path.join(REPO, "tools", "apply_deepseek_pool_to_secrets.py")
ds_pool_apply_dst = os.path.join(OUT, "tools", "apply_deepseek_pool_to_secrets.py")
if os.path.exists(ds_pool_apply_src):
    os.makedirs(os.path.dirname(ds_pool_apply_dst), exist_ok=True)
    shutil.copy2(ds_pool_apply_src, ds_pool_apply_dst)
    print("  [OK] tools\\apply_deepseek_pool_to_secrets.py")

# Copy portable_python to build output
portable_src = os.path.join(REPO, "portable_python")
portable_dst = os.path.join(OUT, "python")
if os.path.exists(portable_src):
    try:
        _src_real = os.path.realpath(portable_src)
        _dst_real = os.path.realpath(portable_dst)
        _same_dir = os.path.normcase(_src_real) == os.path.normcase(_dst_real)
    except Exception:
        _same_dir = False
    if _same_dir:
        print("  [OK] Portable Python source == destination (skipping copy)")
        ensure_portable_python_can_import_src(portable_dst)
        ensure_live2d_dependencies(portable_dst)
    else:
        print("  Deploying Portable Python Runtime to build... This may take a while.")
        shutil.copytree(portable_src, portable_dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "pip-cache"))
        ensure_portable_python_can_import_src(portable_dst)
        ensure_live2d_dependencies(portable_dst)
        print("  [OK] Portable Python deployed")
elif os.path.exists(portable_dst):
    print("  [OK] Portable Python pre-deployed at build output (skipping copy)")
    ensure_portable_python_can_import_src(portable_dst)
    ensure_live2d_dependencies(portable_dst)
else:
    print("  [ERROR] portable_python not found. Please run 'eris_setup.py' -> 'Create Portable Python' first!")
    sys.exit(1)

# ── 4b. Deploy cline-bridge (build truoc, copy ca dist/ + node_modules) ──────
banner("4b/5  --  Deploy cline-bridge (Cline SDK sidecar)")

cline_src  = os.path.join(REPO, "cline-bridge")
cline_dst  = os.path.join(OUT,  "cline-bridge")

def try_copy_f(src, dst):
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print("  [OK] " + os.path.basename(dst))

f_copy = [
    "package.json"
]
for n in f_copy:
    try_copy_f(os.path.join(REPO, "cline-bridge", n), os.path.join(OUT, "cline-bridge", n))

# ── 4e. Deploy Assets & Voice Presets ────────────────────────────────────────
banner("4e/5  --  Deploy Assets & Voice Presets")
def _copy_heavy_dir(dirname: str) -> None:
    src_dir = os.path.join(REPO, dirname)
    dst_dir = os.path.join(OUT, dirname)
    if os.path.exists(src_dir):
        print(f"  Copying {dirname}/ -> build...")
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir, onerror=remove_readonly)
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "*.pyc"))
        print(f"  [OK] {dirname}/ deployed")
    else:
        print(f"  [SKIP] {dirname}/ not found")

_copy_heavy_dir("asset")
_copy_heavy_dir("voice_presets")
_copy_heavy_dir("gemini_manager")

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
    try:
        shutil.copytree(
            cline_src, cline_dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "src", "tsconfig.json", "*.ts"),
        )
    except shutil.Error as e:
        print("  [WARN] Mot so file trong cline-bridge bi khoa (locked) khong the copy. Bo qua...")
    except Exception as e:
        print("  [WARN] Loi khi copy cline-bridge: " + str(e))
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
    "run_manager.bat",
    "setup_secrets.bat",
    "apply_deepseek_pool_to_secrets.bat",
    "_setup_gemini_pool_auth.bat",
    "_start_gemini_pool.bat",
    "run_gemini_web2api.bat",
    "install_live2d_body.bat",
    "requirements-live2d.txt",
    "setup_tutor_browser.bat",
    "tutor_login.bat",
    "tutor_login.py",
    "run_elevenlabs_pool_ui.bat",
    "run_deepseek_pool_ui.bat",
    "run_doctor.bat",
    "run_smoke_test.bat",
    "run_runtime.bat",
]
for fn in ROOT_COPY:
    src_f = os.path.join(REPO, fn)
    dst_f = os.path.join(OUT, fn)
    if os.path.exists(src_f):
        shutil.copy2(src_f, dst_f)
        print("  [OK] " + fn)
    else:
        print("  [SKIP] " + fn + " not found")

# Generate run_eris launchers cho build output.

bat_path     = os.path.join(OUT, "run_eris.bat")
vbs_path     = os.path.join(OUT, "run_eris.vbs")
start_webai  = os.path.join(OUT, "_start_webai.bat")  # da tao o tren
venv_scripts = os.path.dirname(VENV_PY)

bat_lines = [
    "@echo off",
    "REM run_eris.bat -- AUTO-GENERATED compatibility shim by _fullbuild.py, DO NOT EDIT",
    "REM Python " + sys.version.split()[0] + "  magic=" + exp_magic.hex().upper(),
    "setlocal",
    "chcp 65001 >nul",
    "cd /d \"%~dp0\"",
    "",
    "if exist \"%~dp0run_eris.vbs\" (",
    "    start \"\" \"%SystemRoot%\\System32\\wscript.exe\" \"%~dp0run_eris.vbs\"",
    "    exit /b 0",
    ")",
    "",
    "set \"PYTHON=%~dp0python\\pythonw.exe\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=%~dp0python\\python.exe\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=%~dp0.venv\\Scripts\\pythonw.exe\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=%~dp0.venv\\Scripts\\python.exe\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=python\"",
    "",
    "if exist \"%~dp0Eris.exe\" (",
    "    start \"\" \"%~dp0Eris.exe\"",
    ") else (",
    "    start \"\" \"%PYTHON%\" \"%~dp0src\\vision.py\"",
    ")",
    "exit /b 0",
]
bat_content_crlf = "\r\n".join(bat_lines) + "\r\n"
with open(bat_path, "wb") as fh:
    fh.write(bat_content_crlf.encode("ascii"))

vbs_lines = [
    "Option Explicit",
    "Dim shell, fso, env, root, python, bridge",
    "Set shell = CreateObject(\"WScript.Shell\")",
    "Set fso = CreateObject(\"Scripting.FileSystemObject\")",
    "root = fso.GetParentFolderName(WScript.ScriptFullName) & \"\\\"",
    "shell.CurrentDirectory = root",
    "Set env = shell.Environment(\"PROCESS\")",
    "",
    "Function Q(value)",
    "    Q = Chr(34) & value & Chr(34)",
    "End Function",
    "",
    "env(\"PYTHONUTF8\") = \"1\"",
    "env(\"PYTHONIOENCODING\") = \"utf-8\"",
    "env(\"PYTHONUNBUFFERED\") = \"1\"",
    "env(\"PYTHONPATH\") = root & \"src;\" & env(\"PYTHONPATH\")",
    "env(\"PATH\") = root & \"python;\" & root & \"python\\Scripts;\" & env(\"PATH\")",
    "env(\"HF_HOME\") = root & \".cache\\huggingface\"",
    "env(\"XDG_CACHE_HOME\") = root & \".cache\"",
    "env(\"ERIS_AGENT_SERVICE_DISCOVERY\") = root & \".eris_state\\agent_service.json\"",
    "env(\"ERIS_HOME\") = root & \".eris_home\"",
    "env(\"ERIS_STATE_DIR\") = root & \".eris_state\"",
    "",
    "If Not fso.FolderExists(root & \".eris_state\") Then fso.CreateFolder(root & \".eris_state\")",
    "",
    "If Not fso.FileExists(root & \"config\\secrets.json\") Then",
    "    If fso.FileExists(root & \"setup_secrets.bat\") Then shell.Run Q(root & \"setup_secrets.bat\"), 1, False",
    "    WScript.Quit 1",
    "End If",
    "",
    "bridge = root & \"cline-bridge\\dist\\bridge.js\"",
    "If fso.FileExists(bridge) Then",
    "    shell.Run \"cmd.exe /c node \" & Q(bridge), 0, False",
    "End If",
    "",
    "If fso.FileExists(root & \"Eris.exe\") Then",
    "    shell.Run Q(root & \"Eris.exe\"), 1, False",
    "Else",
    "    python = root & \"python\\pythonw.exe\"",
    "    If Not fso.FileExists(python) Then python = root & \"python\\python.exe\"",
    "    If Not fso.FileExists(python) Then python = root & \".venv\\Scripts\\pythonw.exe\"",
    "    If Not fso.FileExists(python) Then python = root & \".venv\\Scripts\\python.exe\"",
    "    If Not fso.FileExists(python) Then python = \"python\"",
    "    shell.Run Q(python) & \" \" & Q(root & \"src\\vision.py\"), 0, False",
    "End If",
]
vbs_content_crlf = "\r\n".join(vbs_lines) + "\r\n"
with open(vbs_path, "wb") as fh:
    fh.write(vbs_content_crlf.encode("ascii"))
print("  [OK] run_eris.bat + run_eris.vbs  (generated CRLF, venv " + sys.version.split()[0] + ")")

service_bat_path = os.path.join(OUT, "run_eris_service.bat")
service_bat_lines = [
    "@echo off",
    "REM run_eris_service.bat -- AUTO-GENERATED by _fullbuild.py, DO NOT EDIT",
    "REM Headless VS Code bridge launcher. Does not open Eris.exe.",
    "setlocal enabledelayedexpansion",
    "chcp 65001 >nul",
    "cd /d \"%~dp0\"",
    "",
    "set \"PYTHON=%~dp0python\\python.exe\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=%~dp0.venv\\Scripts\\python.exe\"",
    "if not exist \"%PYTHON%\" set \"PYTHON=python\"",
    "",
    "set \"PYTHONUTF8=1\"",
    "set \"PYTHONIOENCODING=utf-8\"",
    "set \"PYTHONUNBUFFERED=1\"",
    "set \"PYTHONPATH=%~dp0src;%PYTHONPATH%\"",
    "set \"ERIS_PROJECT_ROOT=%~dp0\"",
    "set \"HF_HOME=%~dp0.cache\\huggingface\"",
    "set \"XDG_CACHE_HOME=%~dp0.cache\"",
    "if not exist \"%~dp0.eris_state\" mkdir \"%~dp0.eris_state\"",
    "if not defined ERIS_AGENT_SERVICE_DISCOVERY set \"ERIS_AGENT_SERVICE_DISCOVERY=%~dp0.eris_state\\agent_service.json\"",
    "set \"ERIS_HOME=%~dp0.eris_home\"",
    "set \"ERIS_STATE_DIR=%~dp0.eris_state\"",
    "",
    "set \"ERIS_VSCODE_SERVICE_MODE=1\"",
    "if not defined ERIS_RUNTIME_SETTINGS_PATH set \"ERIS_RUNTIME_SETTINGS_PATH=%~dp0.eris_state\\vscode_service_runtime_settings.json\"",
    "set \"ERIS_TTS_ENABLED=0\"",
    "set \"ERIS_COMMENTARY_ENABLED=0\"",
    "set \"ERIS_AUTONOMOUS_EXPRESSION_ENABLED=0\"",
    "set \"ERIS_INITIATIVE_ENABLED=0\"",
    "set \"ERIS_AI_STARTUP_GREETING_ENABLED=0\"",
    "set \"ERIS_AI_STARTUP_SCREEN_OPENING=0\"",
    "set \"ERIS_AI_STARTUP_FORCE_SPEAK=0\"",
    "set \"ERIS_RANDOM_CHAT_SEED_RESERVOIR_ENABLED=0\"",
    "set \"ERIS_BACKGROUND_TUTOR_ENABLED=0\"",
    "set \"ERIS_BACKGROUND_OBSERVER=0\"",
    "set \"ERIS_MEMORY_BACKGROUND_DIGEST=0\"",
    "set \"ERIS_BROWSER_BRIDGE_ENABLED=0\"",
    "set \"ERIS_CHESS_BRIDGE_ENABLED=0\"",
    "set \"ERIS_ELEVENLABS_POOL_UI_ENABLED=0\"",
    "",
    "if not exist \"%~dp0config\\secrets.json\" (",
    "    echo [SETUP] Missing config\\secrets.json.",
    "    exit /b 1",
    ")",
    "",
    "\"%PYTHON%\" \"%~dp0src\\vision.py\"",
]
service_bat_content_crlf = "\r\n".join(service_bat_lines) + "\r\n"
with open(service_bat_path, "wb") as fh:
    fh.write(service_bat_content_crlf.encode("ascii"))
print("  [OK] run_eris_service.bat  (headless VS Code bridge)")

sanitize_release_output()
ensure_release_env_template()
strip_release_noise(OUT)

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
    os.path.join(OUT, "run_eris.bat"),
    os.path.join(OUT, "run_eris.vbs"),
    os.path.join(OUT, "run_eris_service.bat"),
    os.path.join(OUT, "ErisManager.exe"),
    os.path.join(OUT, "ErisSetup.exe"),
    os.path.join(OUT, "cline-bridge", "dist",     "bridge.js"),
]
if is_debug:
    must_exist = [p for p in must_exist if not p.endswith(".pyc")]
if IS_RELEASE:
    must_exist.extend([
        os.path.join(OUT, "Eris.exe"),
        os.path.join(OUT, "Eris.pck"),
        os.path.join(OUT, ".env"),
        os.path.join(OUT, ".env.example"),
        os.path.join(OUT, "setup_secrets.bat"),
        os.path.join(OUT, "apply_deepseek_pool_to_secrets.bat"),
        os.path.join(OUT, "tools", "apply_deepseek_pool_to_secrets.py"),
        os.path.join(OUT, "config", "secrets.example.json"),
    ])
else:
    must_exist.extend([
        os.path.join(OUT, ".env"),
        os.path.join(OUT, "setup_secrets.bat"),
        os.path.join(OUT, "apply_deepseek_pool_to_secrets.bat"),
        os.path.join(OUT, "tools", "apply_deepseek_pool_to_secrets.py"),
        os.path.join(OUT, "config", "secrets.json"),
    ])

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
    if not validate_godot_dotnet_output():
        all_ok = False
elif IS_RELEASE:
    print("  [MISSING] Eris.exe (release requires exported Godot GUI runtime)")
    all_ok = False
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

# ── 6. Inno Setup Package ──────────────────────────────────────────────────────
banner("6 / 6  --  Inno Setup Package")

possible_iscc = [
    r"C:\Program Files\Inno Setup 7\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe"
]
iscc_path = None
for p in possible_iscc:
    if os.path.exists(p):
        iscc_path = p
        break

if not iscc_path:
    if BUILD_INSTALLER:
        print("  [WARN] Khong tim thay Inno Setup (ISCC.exe). Bo qua buoc dong goi (chua cai Inno Setup).")
    else:
        print("  [SKIP] Installer disabled for profile=" + PROFILE)
else:
    iss_file = os.path.join(REPO, "installer", "Eris.iss")
    if not BUILD_INSTALLER:
        print("  [SKIP] Installer disabled for profile=" + PROFILE)
    elif os.path.exists(iss_file):
        print("  Dang tien hanh nen thanh file cai dat (co the mat 1-2 phut)...")
        import subprocess
        res = subprocess.run(
            [
                iscc_path,
                "/DSourceDir=" + OUT,
                "/DSetupOutputBaseFilename=ErisSetup",
                iss_file,
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            print("  [OK] Dong goi Inno Setup thanh cong!")
            print("  File cai dat: C:\\Users\\Gtvkun\\Documents\\eris_dist\\ErisSetup.exe")
        else:
            print("  [FAIL] Inno Setup bao loi:")
            print("  " + (res.stderr or res.stdout)[:500])
    else:
        print("  [WARN] Khong tim thay file cau hinh: " + iss_file)

# Tong ket
print("")
if all_ok:
    sep = "=" * 58
    print(sep)
    print("  BUILD THANH CONG")
    print("  Profile: " + PROFILE)
    print("  Output : " + OUT)
    print("  Python : " + sys.version.split()[0])
    print("  Chay   : " + os.path.join(OUT, "run_eris.vbs"))
    print(sep)
else:
    print("[!] BUILD CO VAN DE -- xem log phia tren.")
    sys.exit(1)

