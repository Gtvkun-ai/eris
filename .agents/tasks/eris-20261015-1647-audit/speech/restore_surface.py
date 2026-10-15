import sys,json
from pathlib import Path
sys.path.insert(0,str(Path('src').resolve()))
from llm.raw_trace_store import restore_payload
p=Path('C:/eris_debug/deepseek_raw/events_20261015T094727Z_pid6980.jsonl')
for n,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
 e=json.loads(line)
 if e.get('event')=='response' and e.get('worker_role')=='surface':
  b=restore_payload(p.parent,e['raw_response_ref'])
  out=Path('.agents/tasks/eris-20261015-1647-audit/speech') / ('surface-'+str(n)+'.json')
  out.write_bytes(b)
  d=json.loads(b)
  c=d['choices'][0]['message']['content']
  print(json.dumps({'index_line':n,'at':e['at_utc'],'response_keys':list(d),'content':c},ensure_ascii=False))
