import json, gzip, hashlib
from pathlib import Path
BASE = Path(r'C:\eris_debug\deepseek_raw')
name = 'events_20261103T080642Z_pid21944.jsonl'
def restore(m):
    parts = []
    for d in m['chunks']:
        p = gzip.decompress((BASE / 'objects' / d[:2] / (d + '.gz')).read_bytes())
        assert hashlib.sha256(p).hexdigest() == d
        parts.append(p)
    return b''.join(parts)
rows = [json.loads(l) for l in (BASE / name).read_text('utf-8').splitlines()]
byreq = {}
for r in rows:
    byreq.setdefault(r.get('request_id'), []).append(r)
out = []
for r in rows:
    if r.get('event') == 'response' and r.get('worker_role') == 'executive' and r.get('at_utc', '')[11:19] in ('08:08:22', '08:08:25', '08:08:56', '08:09:34', '08:10:16'):
        out.append('--- resp at %s status=%s elapsed=%s chars=%s lane=%s' % (r['at_utc'], r.get('http_status'), r.get('elapsed_ms'), r.get('response_chars'), r.get('lane')))
        body = restore(r['raw_response_ref']).decode('utf-8', 'replace')
        out.append('BODY[:1200]: ' + body[:1200])
print('n=', len(out))
Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\inspect_prose2.out.txt').write_text('\n'.join(out), 'utf-8')
