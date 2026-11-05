"""Create condition-masked, stable IDs for utterance review."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = [json.loads(l) for l in (HERE / 'results.jsonl').read_text('utf-8').splitlines()]
blind, key = [], []
for row in rows:
    identity = [row['case'], row['condition'], row['repeat']]
    ident = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:6]
    parsed = row.get('parsed')
    if not isinstance(parsed, dict):
        try:
            parsed = json.loads(row.get('content', '').strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
        except (ValueError, TypeError):
            parsed = {}
    blind.append({'id': ident, 'case': row['case'], 'kind': parsed.get('kind', 'unparsed'),
                  'say': parsed.get('say', parsed.get('reason', row.get('content', ''))),
                  'http_status': row.get('http_status')})
    key.append({'id': ident, 'case': row['case'], 'condition': row['condition'], 'repeat': row['repeat']})
assert len({r['id'] for r in blind}) == len(blind)
(HERE / 'review_blind.json').write_text(json.dumps(sorted(blind, key=lambda r: r['id']), ensure_ascii=False, indent=2), 'utf-8')
(HERE / 'review_key.json').write_text(json.dumps(key, ensure_ascii=False, indent=2), 'utf-8')
print(len(blind))
