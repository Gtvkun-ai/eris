import json
from pathlib import Path
d = Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\turns')
rows = []
total_user_req = 0
for p in sorted(d.glob('2026*.json')):
    s = json.loads(p.read_text('utf-8'))
    if p.stem < '20261018':
        continue
    seen = set()
    for e in s['executive']:
        ev = e.get('event') or {}
        if ev.get('kind') != 'user_turn':
            continue
        key = ev.get('event_id')
        if key in seen:
            continue
        seen.add(key)
        total_user_req += 1
        ctx = e.get('ctx') or {}
        if 'confusion_signal' in (ctx.get('_keys') or []):
            rows.append((p.stem, (ev.get('text') or '')[:110]))
out = ['user_turn events since 10/18 (unique event_id): %d; with confusion_signal: %d' % (total_user_req, len(rows))]
for sid, t in rows:
    out.append('%s | %s' % (sid, t))
Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\confusion_hits.out.txt').write_text('\n'.join(out), 'utf-8')
print('ok')
