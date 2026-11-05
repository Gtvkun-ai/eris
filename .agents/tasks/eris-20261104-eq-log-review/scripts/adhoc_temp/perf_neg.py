import json
from pathlib import Path
ds = Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\ds')
rows = [json.loads(l) for l in (ds / 'utterances.jsonl').read_text('utf-8').splitlines()]
out = []
for r in rows:
    if r['session'] in ('20261103_215411', '20261103_162914'):
        out.append('%s %s %s ch=%s perf=%s chars=%s | %s' % (r['session'], r['sent'][11:19], r['trigger'], r['channel'], r.get('perf'), r.get('chars'), (r.get('text') or '')[:70]))
Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\perf_neg.out.txt').write_text('\n'.join(out), 'utf-8')
print('ok')
