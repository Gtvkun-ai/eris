import json, sys
from pathlib import Path
sid = sys.argv[1]
d = json.loads(Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\turns\%s.json' % sid).read_text('utf-8'))
out = ['# surface responses for ' + sid]
for s in sorted(d['surface'], key=lambda x: x['req_local']):
    r = s.get('resp') or {}
    out.append('[%s -> %s] elapsed=%s http=%s' % (s['req_local'][11:19], s['resp_local'][11:19], s.get('elapsed_ms'), s.get('http_status')))
    out.append('   text=%s' % (r.get('text') if 'text' in r else r.get('_raw')))
    out.append('   keys=%s should_speak=%s perf=%s' % (sorted(r.keys()), r.get('should_speak'), r.get('performance_hint')))
out.append('# executive http != 200')
for e in d['executive']:
    if e.get('http_status') != 200:
        out.append('[%s] http=%s elapsed=%s lane=%s event=%s' % (e['req_local'][11:19], e.get('http_status'), e.get('elapsed_ms'), e.get('lane'), (e.get('event') or {}).get('kind')))
Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\show_surface.%s.txt' % sid).write_text('\n'.join(out), 'utf-8')
print('ok')
