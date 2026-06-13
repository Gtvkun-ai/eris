import os, py_compile
SRC = r"C:\Users\Gtvkun\Documents\GitHub\eris\src"
DST = r"C:\Users\Gtvkun\Documents\eris\src"
SKIP = {"__pycache__", ".hypothesis"}
ok = fail = 0
errors = []
for root, dirs, files in os.walk(SRC):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for f in files:
        if not f.endswith(".py"): continue
        sp = os.path.join(root, f)
        rel = os.path.relpath(sp, SRC)
        dp = os.path.join(DST, rel[:-3] + ".pyc")
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        try:
            py_compile.compile(sp, cfile=dp, doraise=True)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{rel}: {e}")
print(f"OK={ok} FAIL={fail}")
for e in errors[:20]: print("FAIL", e)
