"""
_patchbuild.py -- Xay dung ban cap nhat nho (chi chua src) cho Eris.

Chay bang VENV cua du an (bat buoc):
    & ".venv\\Scripts\\python.exe" _patchbuild.py
"""

import compileall
import os
import shutil
import sys
from build_payload import source_copy_ignore

# ── Config ────────────────────────────────────────────────────────────────────
REPO    = os.path.dirname(os.path.abspath(__file__))
_USER_DOCS = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")
OUT     = os.path.normpath(os.path.join(_USER_DOCS, "eris"))
VENV_PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")

# .py duoc giu lai trong build
KEEP_PY = {"vision.py"}

# Thu muc qua nang / khong can ship
SKIP_HEAVY = {
    ".pytest_cache",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def banner(msg):
    sep = "=" * 58
    print("\n" + sep + "\n  " + msg + "\n" + sep)

def count_ext(root, ext):
    total = 0
    for _, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(ext):
                total += 1
    return total

def remove_readonly(func, path, _):
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

# ── Guard: phai chay bang dung venv ──────────────────────────────────────────
banner("Guard  --  kiem tra Python interpreter")

if not os.path.isfile(VENV_PY):
    print("[!] Khong tim thay venv: " + VENV_PY)
    sys.exit(1)

cur = os.path.normcase(os.path.abspath(sys.executable))
exp = os.path.normcase(os.path.abspath(VENV_PY))

if cur != exp:
    print("[!] Sai Python interpreter!")
    print("    Current  : " + sys.executable)
    print("    Expected : " + VENV_PY)
    print('    Chay lai : & "' + VENV_PY + '" _patchbuild.py')
    sys.exit(1)

print("[OK] Python " + sys.version.split()[0] + "  --  " + sys.executable)

# ── 1. Xoa src/ cu, copy moi tu repo ─────────────────────────────────────────
banner("1 / 3  --  Copy src/ tu repo (Chi Patch)")

src_repo  = os.path.join(REPO, "src")
src_build = os.path.join(OUT, "src")

if os.path.exists(src_build):
    print("  Xoa src/ cu trong build...")
    shutil.rmtree(src_build, onerror=remove_readonly)

print("  Copy: " + src_repo + "  ->  " + src_build)
shutil.copytree(src_repo, src_build, dirs_exist_ok=True, ignore=source_copy_ignore)

for skip in SKIP_HEAVY:
    p = os.path.join(src_build, skip)
    if os.path.exists(p):
        shutil.rmtree(p, onerror=remove_readonly)

# ── 2. Compile TOAN BO .py -> .pyc (legacy: .pyc dat canh .py) ───────────────
banner("2 / 3  --  Compile .py -> .pyc")

ok = compileall.compile_dir(
    src_build,
    force=True,
    quiet=1,
    legacy=True,
    optimize=0,
)

if not ok:
    print("[!] compileall bao loi -- kiem tra output phia tren.")
    sys.exit(1)

removed_py = 0
for dp, _, fns in os.walk(src_build):
    for fn in fns:
        fp = os.path.join(dp, fn)
        if fn.endswith(".py") and fn not in KEEP_PY:
            os.remove(fp)
            removed_py += 1
        elif fn.endswith(".md") or fn.endswith(".bat") or fn.endswith(".toml") or fn.endswith(".ini") or fn.startswith("requirements-") or fn in {".gitignore", ".gitattributes"}:
            if fn != "SKILL.md":
                os.remove(fp)

for dp, dirs, _ in os.walk(src_build, topdown=False):
    for d in list(dirs):
        if d == "__pycache__":
            shutil.rmtree(os.path.join(dp, d))

print("  Xong qua trinh compile. Con lai: " + str(count_ext(src_build, ".pyc")) + " file .pyc")

# Copy mot so script root neu can (vi du run_eris.bat, bat buoc)
for script in ["run_eris.bat"]:
    s_path = os.path.join(REPO, script)
    if os.path.exists(s_path):
        shutil.copy2(s_path, os.path.join(OUT, script))

# ── 3. Inno Setup Package (Patch) ────────────────────────────────────────────
banner("3 / 3  --  Inno Setup Package (Tao ban Update)")

possible_iscc = [os.environ.get("ISCC_EXE"), shutil.which("ISCC.exe")]
possible_iscc += [
    os.path.join(os.environ[base], version, "ISCC.exe")
    for base in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
    if os.environ.get(base)
    for version in ("Inno Setup 7", "Inno Setup 6")
]
iscc_path = None
for p in possible_iscc:
    if p and os.path.isfile(p):
        iscc_path = p
        break

if not iscc_path:
    print("  [WARN] Khong tim thay Inno Setup (ISCC.exe). Bo qua buoc dong goi.")
else:
    iss_file = os.path.join(REPO, "installer", "ErisPatch.iss")
    if os.path.exists(iss_file):
        print("  Dang tien hanh nen thanh file cai dat (chi vai giay)...")
        import subprocess
        res = subprocess.run([iscc_path, "/DSourceDir=" + OUT, iss_file], capture_output=True, text=True)
        if res.returncode == 0:
            print("  [OK] Dong goi Inno Setup thanh cong!")
            print(f"  File cai dat: {os.path.join(_USER_DOCS, 'eris_dist', 'ErisPatch.exe')}")
        else:
            print("  [FAIL] Inno Setup bao loi:")
            print("  " + (res.stderr or res.stdout)[:500])
    else:
        print("  [WARN] Khong tim thay file cau hinh: " + iss_file)

print("\n==========================================================")
print("  PATCH BUILD THANH CONG")
print("==========================================================")
