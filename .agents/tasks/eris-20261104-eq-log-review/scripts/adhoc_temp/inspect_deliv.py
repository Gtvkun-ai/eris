import json, sys
from pathlib import Path
sid = sys.argv[1]
d = json.loads(Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\joined\%s.json' % sid).read_text('utf-8'))
out = ['session', sid, 'runlog', str(d['runlog'])]
for x in d['deliveries']:
    out.append('%s | ch=%s trig=%s sent=%s chars=%s tts=%s outcome=%s commit=%s matched=%s\n     goal=%s' % (
        x['id'][:30], x.get('channel'), x.get('trigger'), (x.get('sent') or '')[11:23], x.get('chars'), x.get('tts'), x.get('outcome'), x.get('commit'), x.get('matched'), (x.get('goal') or '')[:200]))
out.append('--- lines (warn/err/notes)')
for l in d['lines']:
    out.append('%s %s %s' % (l['at'][11:23], l['level'], l['msg'][:200]))
Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\inspect_deliv.%s.txt' % sid).write_text('\n'.join(out), 'utf-8')
print('ok')
