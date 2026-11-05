import json
from collections import defaultdict
rows = json.load(open(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\prompt_version.json', encoding='utf-8'))
groups = defaultdict(list)
for r in rows:
    if 'err' in r or 'system_sha12' not in r:
        continue
    key = (r['system_sha12'], r['system_chars'], tuple(sorted(k for k, v in r['marks'].items() if v)))
    groups[key].append(r['sid'])
out = []
for k, sids in sorted(groups.items(), key=lambda kv: kv[1][0]):
    out.append('sha=%s chars=%s marks=%s n=%d first=%s last=%s' % (k[0], k[1], list(k[2]), len(sids), sids[0], sids[-1]))
    out.append('    sessions: ' + ', '.join(sids[:40]))
open(r'C:\Users\Gtvkun\AppData\Local\Temp\eris_eq_review\sum_prompt_version.out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('groups', len(groups))
