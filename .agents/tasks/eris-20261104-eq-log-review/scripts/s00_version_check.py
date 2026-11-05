#!/usr/bin/env python
"""s00: xac minh phien ban code cua ban chay that (Documents/eris/src) so voi repo.

Chi doc. So git-blob-sha1 cua tung file .py trong ban chay voi blob o 3 revision:
  38a87584 (truoc nang cap), c5e16c3b, 1ccab39b (HEAD luc lap bao cao).
Chuan hoa CRLF->LF de tranh khac biet do autocrlf.

Chay:
    python -X utf8 s00_version_check.py <out_json>
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

REPO = r"c:\Users\Gtvkun\Documents\GitHub\eris"
PORT = r"C:\Users\Gtvkun\Documents\eris\src"
REVS = {"pre": "38a87584", "c5e": "c5e16c3b", "head": "1ccab39b"}
TZ = timezone(timedelta(hours=7))


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, check=True).stdout


def tree(rev: str) -> dict:
    raw = git("ls-tree", "-r", "-z", rev, "--", "src")
    res = {}
    for ent in raw.split(b"\0"):
        if not ent:
            continue
        meta, path = ent.split(b"\t", 1)
        mode, typ, sha = meta.decode().split()
        if typ == "blob":
            res[path.decode("utf-8")] = sha
    return res


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def port_shas(path: str):
    data = open(path, "rb").read()
    return blob_sha(data), blob_sha(data.replace(b"\r\n", b"\n"))


def main(out_path: str) -> None:
    trees = {k: tree(v) for k, v in REVS.items()}
    changed = git("diff", "--name-only", "-z", REVS["pre"], REVS["head"], "--", "src").decode("utf-8").split("\0")
    changed = sorted(p for p in changed if p)
    changed_py = [p for p in changed if p.endswith(".py")]
    files = []
    for root, _dirs, names in os.walk(PORT):
        if "__pycache__" in root:
            continue
        for n in names:
            if n.endswith(".py"):
                full = os.path.join(root, n)
                rel = "src/" + os.path.relpath(full, PORT).replace("\\", "/")
                files.append((rel, full))
    summary = {"n_portable_py": len(files), "match": {k: 0 for k in REVS}, "match_any": 0, "match_none": 0, "only_in_portable": 0}
    none_list = []
    per_file = {}
    for rel, full in files:
        raw, lf = port_shas(full)
        st = os.stat(full)
        mt = datetime.fromtimestamp(st.st_mtime, TZ).strftime("%Y-%m-%d %H:%M")
        row = {"mtime": mt}
        hit = False
        for k in REVS:
            sha = trees[k].get(rel)
            ok = sha is not None and sha in (raw, lf)
            row[k] = "eq" if ok else ("absent" if sha is None else "diff")
            if ok:
                summary["match"][k] += 1
                hit = True
        if hit:
            summary["match_any"] += 1
        else:
            summary["match_none"] += 1
            none_list.append(rel)
        if all(row[k] == "absent" for k in REVS):
            summary["only_in_portable"] += 1
        per_file[rel] = row
    # tap file doi giua pre..head: trang thai ban chay
    changed_status = []
    for p in changed_py:
        row = per_file.get(p)
        if row is None:
            changed_status.append({"path": p, "portable": "missing"})
            continue
        if row["head"] == "eq" and row["pre"] != "eq":
            st = "= HEAD (da nang cap)"
        elif row["pre"] == "eq" and row["head"] != "eq":
            st = "= 38a87584 (chua nang cap)"
        elif row["c5e"] == "eq":
            st = "= c5e16c3b"
        else:
            st = "khac ca ba"
        changed_status.append({"path": p, "portable": st, "mtime": row["mtime"]})
    # trong tap file doi, file moi hoan toan (khong co o pre)
    new_files = [p for p in changed_py if p not in trees["pre"]]
    mt_hist = {}
    for rel, row in per_file.items():
        d = row["mtime"][:10]
        mt_hist[d] = mt_hist.get(d, 0) + 1
    res = {
        "revs": REVS,
        "summary": summary,
        "changed_py_between_pre_and_head": len(changed_py),
        "changed_py_new_in_head": new_files,
        "changed_status": changed_status,
        "portable_files_matching_none": none_list[:200],
        "portable_mtime_histogram_by_day": dict(sorted(mt_hist.items())),
    }
    with open(out_path, "w", encoding="utf-8") as g:
        json.dump(res, g, ensure_ascii=False, indent=1)
    print("ok", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
