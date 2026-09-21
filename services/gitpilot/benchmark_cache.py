import json, time
from pathlib import Path

cache_root = Path.home() / ".gitpilot" / "repo_cache"
cache_files = list(cache_root.glob("*eris*/cache.json"))
if not cache_files:
    print("No eris cache found")
    exit(1)

cache_file = cache_files[0]
size_mb = cache_file.stat().st_size / 1024 / 1024

t0 = time.perf_counter()
data = json.loads(cache_file.read_text(encoding="utf-8"))
t1 = time.perf_counter()
files = data.get("files", {})
print(f"Cache file  : {size_mb:.1f} MB")
print(f"Read+parse  : {(t1-t0)*1000:.0f} ms")
print(f"File count  : {len(files)}")

t2 = time.perf_counter()
for rel, rec in files.items():
    text = rel + rec.get("module_doc", "") + " ".join(rec.get("classes", []))
    _ = "orchestrator" in text.lower()
t3 = time.perf_counter()
print(f"Scoring loop: {(t3-t2)*1000:.0f} ms")
print(f"TOTAL overhead/request: ~{(t1-t0+t3-t2)*1000:.0f} ms")
