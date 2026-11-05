import json, sys
from datetime import datetime, timezone, timedelta
TZ = timezone(timedelta(hours=7))
p = r'C:\Users\Gtvkun\Documents\eris\.eris_home\memory\core\living_user_trace.jsonl'
lo = datetime.strptime(sys.argv[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ).timestamp()
hi = datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ).timestamp()
rows = []
first = None
keys_seen = {}
n = 0
with open(p, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        n += 1
        try:
            d = json.loads(line)
        except Exception:
            continue
        if first is None:
            first = {k: (str(v)[:80]) for k, v in d.items()}
        ts = d.get('ts') or d.get('timestamp') or d.get('at') or d.get('time')
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts).timestamp()
            except Exception:
                ts = None
        if not isinstance(ts, (int, float)):
            continue
        if lo <= ts <= hi:
            rows.append((ts, d))
out = ['total_lines=%d first_keys=%s' % (n, json.dumps(first, ensure_ascii=False))]
for ts, d in sorted(rows, key=lambda x: x[0]):
    short = {}
    for k, v in d.items():
        if k in ('ts', 'timestamp', 'at', 'time'):
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            short[k] = v
        elif isinstance(v, str):
            short[k] = v[:80]
        elif isinstance(v, dict):
            short[k] = {kk: (vv if isinstance(vv, (int, float, bool)) else str(vv)[:50]) for kk, vv in list(v.items())[:10]}
        else:
            short[k] = '<%s len=%d>' % (type(v).__name__, len(v))
    out.append('%s %s' % (datetime.fromtimestamp(ts, TZ).strftime('%H:%M:%S.%f')[:-3], json.dumps(short, ensure_ascii=False)[:420]))
open(sys.argv[3], 'w', encoding='utf-8').write('\n'.join(out))
print('rows', len(rows))
