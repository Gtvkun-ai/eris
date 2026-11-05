import os, json, subprocess
from datetime import datetime, timezone, timedelta
TZ = timezone(timedelta(hours=7))
PORT = r'C:\Users\Gtvkun\Documents\eris\src'
cut = datetime(2026, 11, 1, 0, 0, tzinfo=TZ).timestamp()
rows = []
for root, _d, names in os.walk(PORT):
    if '__pycache__' in root:
        continue
    for n in names:
        full = os.path.join(root, n)
        st = os.stat(full)
        if st.st_mtime >= cut:
            rows.append((datetime.fromtimestamp(st.st_mtime, TZ).strftime('%Y-%m-%d %H:%M'), os.path.relpath(full, PORT).replace('\\', '/'), st.st_size))
rows.sort()
out = ['n=%d (mtime >= 2026-11-01, all file types)' % len(rows)]
for r in rows:
    out.append('%s  %8d  %s' % (r[0], r[2], r[1]))
open(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\recent_mtime.out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('ok')
