import json
from pathlib import Path
d = json.loads(Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\turns\20261103_215411.json').read_text('utf-8'))
out = []
for e in d['executive']:
    ev = e.get('event') or {}
    if ev.get('kind') != 'user_turn':
        continue
    ctx = e.get('ctx') or {}
    out.append('=== %s user=%r' % (e['req_local'][11:19], (ev.get('text') or '')[:80]))
    out.append('runtime_context keys: %s' % ctx.get('_keys'))
    for k in ('conversation_status', 'discourse_context', 'engagement_context', 'open_loop_hints', 'affective_voice_state', 'interrupt_context', 'language_hint'):
        if k in ctx:
            out.append('  %s = %s' % (k, json.dumps(ctx[k], ensure_ascii=False)[:700]))
    out.append('  reasoning_head: %s' % (e.get('reasoning_head') or '')[:1500])
Path(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\check_confusion.out.txt').write_text('\n'.join(out), 'utf-8')
print('ok')
