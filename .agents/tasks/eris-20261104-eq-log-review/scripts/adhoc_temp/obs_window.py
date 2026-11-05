import json, sys
from datetime import datetime, timezone, timedelta
TZ = timezone(timedelta(hours=7))
p = r'C:\Users\Gtvkun\Documents\eris\logs\eris_observability.jsonl'
lo = datetime.strptime(sys.argv[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ).timestamp()
hi = datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ).timestamp()
skip = {'environment_event_total', 'environment_source_to_ingress_ms', 'environment_bus_publish_duration_ms', 'environment_event_to_bus_ms',
        'environment_callback_to_enqueue_ms', 'environment_semantic_queue_depth', 'environment_semantic_queue_wait_ms', 'environment_semantic_processing_ms',
        'environment_ingress_to_semantic_ms', 'environment_event_to_semantic_ms', 'environment_source_to_semantic_ms', 'user_situation_from_environment_total',
        'environment_source_callback_delay_ms', 'environment_enrichment_ms', 'environment_semantic_wake_coalesced_total', 'environment_scheduler_coalesced_total',
        'foreground_to_user_situation_ms'}
out = []
with open(p, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        if '"timestamp": 17937' not in line and '"timestamp":17937' not in line and '17937' not in line[:200]:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = d.get('timestamp')
        if not isinstance(ts, (int, float)) or ts < lo or ts > hi:
            continue
        if d.get('name') in skip:
            continue
        fl = d.get('fields') or {}
        # tranh in noi dung: chi in khoa so/chuoi ngan
        fs = {k: (v if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) < 60) else '<%s>' % type(v).__name__) for k, v in fl.items()}
        out.append((ts, '%s %s|%s v=%s tags=%s fields=%s' % (datetime.fromtimestamp(ts, TZ).strftime('%H:%M:%S.%f')[:-3], d.get('signal'), d.get('name'), d.get('value'), json.dumps(d.get('tags'), ensure_ascii=False)[:200], json.dumps(fs, ensure_ascii=False)[:300])))
out.sort()
open(sys.argv[3], 'w', encoding='utf-8').write('\n'.join(x[1] for x in out))
print('n=', len(out))
